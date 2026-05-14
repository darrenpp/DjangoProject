from datetime import timedelta
from pathlib import Path

import pandas as pd
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.workforce.models import (
    Application,
    Cadre,
    Midwife,
    NursingProfessional,
    Qualification,
    TrainingInstitution,
)
from apps.workforce.services.institution_classification import classify_training_institution
from apps.workforce.services.data_quality import audit_professional_profiles
from notebooks.cleanse_full_registrations import (
    DEFAULT_SHEET,
    WORKBOOK_PATH,
    cleanse_workbook,
    export_outputs,
)


class Command(BaseCommand):
    help = "Cleanse and import full licence registrations."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            default=str(WORKBOOK_PATH),
            help="Path to the workbook containing the full-registration sheet.",
        )
        parser.add_argument(
            "--sheet",
            type=str,
            default=DEFAULT_SHEET,
            help="Worksheet name containing full-registration records.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate and count rows without saving.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Optional number of cleaned rows to import for testing.",
        )

    def handle(self, *args, **options):
        workbook = Path(options["file"])
        sheet_name = options["sheet"]
        dry_run = options["dry_run"]
        limit = options["limit"] or None

        if not workbook.exists():
            raise CommandError(f"Workbook not found: {workbook}")

        self.stdout.write(f"Cleaning workbook: {workbook} [{sheet_name}]")
        try:
            result = cleanse_workbook(workbook_path=workbook, sheet_name=sheet_name)
        except Exception as exc:
            raise CommandError(f"Unable to cleanse workbook: {exc}") from exc

        export_outputs(result)
        cleaned = result.cleaned.copy()
        if limit:
            cleaned = cleaned.head(limit).copy()

        self.stdout.write(self.style.SUCCESS(f"Cleaned full-registration rows ready: {len(cleaned)}"))
        self.stdout.write(f"Quality issue rows logged: {len(result.issues)}")
        self.stdout.write(f"Rows without issued dates after cleaning: {int(cleaned['issued_date'].isna().sum()) if not cleaned.empty else 0}")

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run selected. No database records were changed."))
            return

        nursing_cadre, _ = Cadre.objects.get_or_create(
            name="Nursing",
            defaults={"category": "nursing"},
        )
        midwifery_cadre, _ = Cadre.objects.get_or_create(
            name="Midwifery",
            defaults={"category": "midwifery"},
        )
        nurse_ct = ContentType.objects.get_for_model(NursingProfessional)
        midwife_ct = ContentType.objects.get_for_model(Midwife)

        created_professionals = 0
        updated_professionals = 0
        created_qualifications = 0
        updated_qualifications = 0
        created_applications = 0
        updated_applications = 0

        with transaction.atomic():
            for row in cleaned.to_dict("records"):
                profession_track = row.get("profession_track") or "nursing"
                model = Midwife if row.get("target_model") == "midwife" else NursingProfessional
                content_type = midwife_ct if model is Midwife else nurse_ct
                cadre = midwifery_cadre if profession_track == "midwifery" else nursing_cadre

                institution = None
                institution_name = (row.get("institution_name") or "").strip()
                if institution_name and institution_name.upper() not in {"TBA", "N/A", "NA"}:
                    institution_type = classify_training_institution(institution_name)
                    institution, created = TrainingInstitution.objects.get_or_create(
                        name=institution_name[:255],
                        defaults={"type": institution_type},
                    )
                    if not created and institution.type != institution_type:
                        institution.type = institution_type
                        institution.save(update_fields=["type"])

                issued_date = row.get("issued_date")
                if pd.isna(issued_date):
                    issued_date = None
                elif hasattr(issued_date, "date"):
                    issued_date = issued_date.date()

                graduation_year = row.get("graduation_year")
                graduation_year_value = int(graduation_year) if pd.notna(graduation_year) else None
                expiry_date = issued_date + timedelta(days=1095) if issued_date else None

                registration_number = (row.get("practitioner_no") or "").strip() or None

                defaults = {
                    "first_name": (row.get("first_name") or "")[:100],
                    "last_name": (row.get("last_name") or "")[:100],
                    "applicant_type": row.get("applicant_type") or "national",
                    "registration_number": registration_number,
                    "date_issued": issued_date,
                    "license_expiry_date": expiry_date,
                    "qualification_level": (row.get("qualification_name") or "")[:100],
                    "cadre": cadre,
                    "is_active": True,
                }

                professional, created = model.objects.update_or_create(
                    registration_no=row["registration_no"],
                    defaults=defaults,
                )
                if created:
                    created_professionals += 1
                else:
                    updated_professionals += 1

                qualification_defaults = {
                    "institution": institution,
                    "institution_name": institution_name[:255],
                    "program_completed": (row.get("qualification_name") or "")[:255],
                    "completion_year": graduation_year_value,
                    "date_completed": None,
                    "qualification_type": "Full Licence",
                    "country": "Papua New Guinea" if row.get("applicant_type") != "overseas" else "",
                }
                qualification, qual_created = Qualification.objects.update_or_create(
                    content_type=content_type,
                    object_id=professional.id,
                    qualification_name=(row.get("qualification_name") or "Full Licence")[:200],
                    defaults=qualification_defaults,
                )
                if qual_created:
                    created_qualifications += 1
                else:
                    updated_qualifications += 1

                source_id = row.get("source_id")
                source_id_value = int(source_id) if pd.notna(source_id) else None
                payload = {
                    "source_workbook": workbook.name,
                    "source_sheet": sheet_name,
                    "source_id": source_id_value,
                    "p_code": row.get("p_code") or "",
                    "license_no": row.get("license_no") or "",
                    "practitioner_no": row.get("practitioner_no") or "",
                    "issued_date_status": row.get("issued_date_status") or "",
                    "institution_name": institution_name,
                    "qualification_name": row.get("qualification_name") or "",
                    "graduation_year": graduation_year_value,
                }
                application_defaults = {
                    "pathway": row.get("pathway") or "other",
                    "form_title": "Application for Full Licence",
                    "profession_track": profession_track,
                    "status": "approved",
                    "expiry_date": expiry_date,
                    "payload": payload,
                    "reviewer_notes": (
                        f"Imported from {workbook.name}. Original registration number: "
                        f"{row['registration_no']}."
                    ),
                }
                application, app_created = Application.objects.update_or_create(
                    content_type=content_type,
                    object_id=professional.id,
                    form_code="NC2",
                    defaults=application_defaults,
                )
                if issued_date:
                    application.submitted_date = issued_date
                    application.approved_date = issued_date
                    application.expiry_date = expiry_date
                    application.save(
                        update_fields=["submitted_date", "approved_date", "expiry_date"]
                    )
                if app_created:
                    created_applications += 1
                else:
                    updated_applications += 1

        self.stdout.write(self.style.SUCCESS("Full registration import completed."))
        self.stdout.write(f"Professionals created: {created_professionals}")
        self.stdout.write(f"Professionals updated: {updated_professionals}")
        self.stdout.write(f"Qualifications created: {created_qualifications}")
        self.stdout.write(f"Qualifications updated: {updated_qualifications}")
        self.stdout.write(f"Applications created: {created_applications}")
        self.stdout.write(f"Applications updated: {updated_applications}")
        self.stdout.write(f"Missing profile audit: {audit_professional_profiles(send_notifications=True)}")
