from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.workforce.models import (
    Application,
    Cadre,
    HealthStudent,
    Qualification,
    TrainingInstitution,
)
from apps.workforce.services.institution_classification import classify_training_institution
from notebooks.cleanse_provisional_graduands import (
    DEFAULT_SHEET,
    WORKBOOK_PATH,
    cleanse_workbook,
    export_outputs,
)


class Command(BaseCommand):
    help = "Cleanse and import provisional licence holders as graduands."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            default=str(WORKBOOK_PATH),
            help="Path to the provisional workbook.",
        )
        parser.add_argument(
            "--sheet",
            type=str,
            default=DEFAULT_SHEET,
            help="Worksheet name containing provisional records.",
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

        self.stdout.write(self.style.SUCCESS(f"Cleaned graduand rows ready: {len(cleaned)}"))
        self.stdout.write(f"Quality issue rows logged: {len(result.issues)}")
        self.stdout.write(f"Missing issued dates after cleaning: {int(cleaned['issued_date'].isna().sum())}")

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
        student_ct = ContentType.objects.get_for_model(HealthStudent)

        created_students = 0
        updated_students = 0
        created_qualifications = 0
        updated_qualifications = 0
        created_applications = 0
        updated_applications = 0

        with transaction.atomic():
            for row in cleaned.to_dict("records"):
                source_id = row.get("source_id")
                provisional_no = row.get("provisional_no")
                graduation_year = row.get("graduation_year")
                issued_date = row.get("issued_date")

                source_id_value = int(source_id) if pd.notna(source_id) else None
                provisional_no_value = str(int(provisional_no)) if pd.notna(provisional_no) else ""
                graduation_year_value = int(graduation_year) if pd.notna(graduation_year) else None

                institution = None
                institution_name = (row.get("institution_name") or "").strip()
                if institution_name:
                    institution_type = classify_training_institution(institution_name)
                    institution, created = TrainingInstitution.objects.get_or_create(
                        name=institution_name[:255],
                        defaults={"type": institution_type},
                    )
                    if not created and institution.type != institution_type:
                        institution.type = institution_type
                        institution.save(update_fields=["type"])

                profession_track = row.get("profession_track") or "nursing"
                cadre = midwifery_cadre if profession_track == "midwifery" else nursing_cadre

                expected_graduation_date = None
                if graduation_year_value:
                    try:
                        expected_graduation_date = date(graduation_year_value, 12, 31)
                    except (TypeError, ValueError):
                        expected_graduation_date = None

                defaults = {
                    "first_name": (row.get("first_name") or "")[:100],
                    "last_name": (row.get("last_name") or "")[:100],
                    "applicant_type": row.get("applicant_type") or "national",
                    "program": (row.get("qualification_name") or "General Nursing")[:150],
                    "institution": institution,
                    "expected_graduation_date": expected_graduation_date,
                    "is_graduate": True,
                    "cadre": cadre,
                    "is_active": True,
                }

                student, created = HealthStudent.objects.update_or_create(
                    registration_no=row["registration_no"],
                    defaults=defaults,
                )
                if created:
                    created_students += 1
                else:
                    updated_students += 1

                qualification_defaults = {
                    "institution": institution,
                    "institution_name": institution_name[:255],
                    "program_completed": (row.get("qualification_name") or "")[:255],
                    "completion_year": graduation_year_value,
                    "date_completed": expected_graduation_date,
                    "qualification_type": "Provisional Licence",
                    "country": "Papua New Guinea" if row.get("applicant_type") != "overseas" else "",
                }

                qualification, qual_created = Qualification.objects.update_or_create(
                    content_type=student_ct,
                    object_id=student.id,
                    qualification_name=(row.get("qualification_name") or "General Nursing")[:200],
                    defaults=qualification_defaults,
                )
                if qual_created:
                    created_qualifications += 1
                else:
                    updated_qualifications += 1

                if pd.isna(issued_date):
                    issued_date = None
                elif hasattr(issued_date, "date"):
                    issued_date = issued_date.date()

                expiry_date = issued_date + timedelta(days=180) if issued_date else None
                payload = {
                    "source_workbook": workbook.name,
                    "source_sheet": sheet_name,
                    "source_id": source_id_value,
                    "source_full_name": row.get("full_name") or "",
                    "provisional_number": provisional_no_value,
                    "issued_date_status": row.get("issued_date_status") or "",
                    "institution_name": institution_name,
                    "qualification_name": row.get("qualification_name") or "",
                    "graduation_year": graduation_year_value,
                }

                application_defaults = {
                    "pathway": row.get("pathway") or "other",
                    "form_title": "Application for Provisional Licence",
                    "profession_track": profession_track,
                    "status": "approved",
                    "expiry_date": expiry_date,
                    "payload": payload,
                    "reviewer_notes": (
                        f"Imported from {workbook.name}. Original provisional number: "
                        f"{payload['provisional_number'] or 'n/a'}."
                    ),
                }

                application, app_created = Application.objects.update_or_create(
                    content_type=student_ct,
                    object_id=student.id,
                    form_code="NC1",
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

        self.stdout.write(self.style.SUCCESS("Provisional graduand import completed."))
        self.stdout.write(f"Graduands created: {created_students}")
        self.stdout.write(f"Graduands updated: {updated_students}")
        self.stdout.write(f"Qualifications created: {created_qualifications}")
        self.stdout.write(f"Qualifications updated: {updated_qualifications}")
        self.stdout.write(f"Applications created: {created_applications}")
        self.stdout.write(f"Applications updated: {updated_applications}")
