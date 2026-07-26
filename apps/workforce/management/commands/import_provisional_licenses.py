from datetime import date
from datetime import timedelta
from pathlib import Path

import pandas as pd
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.workforce.models import Application, Cadre, NursingProfessional, Qualification, TrainingInstitution
from apps.workforce.services.institution_classification import (
    applicant_type_for_institution,
    classify_training_institution,
)


def clean_cell(value):
    if pd.isna(value):
        return ""
    return str(value).strip()


def limit_text(value, max_length):
    value = clean_cell(value)
    if not value:
        return ""
    return value[:max_length]


class Command(BaseCommand):
    help = "Import provisional nursing license records from the Excel workbook."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            default=str(Path("notebooks") / "Provional_Cleansed_data2009_2026.xlsx"),
            help="Path to the provisional workbook.",
        )
        parser.add_argument(
            "--sheet",
            type=str,
            default="Provisional_License_Data2009_26",
            help="Worksheet name containing provisional records.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate and count rows without saving.",
        )

    def handle(self, *args, **options):
        workbook = Path(options["file"])
        sheet_name = options["sheet"]
        dry_run = options["dry_run"]

        if not workbook.exists():
            raise CommandError(f"Workbook not found: {workbook}")

        self.stdout.write(f"Loading workbook: {workbook}")

        try:
            df = pd.read_excel(workbook, sheet_name=sheet_name)
        except Exception as exc:
            raise CommandError(f"Could not read sheet '{sheet_name}': {exc}") from exc

        df.columns = [str(col).strip() for col in df.columns]
        required_columns = {"ID", "Name", "License Type", "Provisional/No", "Issued_Date", "Institution_Attended", "Year", "Qualification"}
        missing = required_columns - set(df.columns)
        if missing:
            raise CommandError(f"Missing required columns: {', '.join(sorted(missing))}")

        df = df[df["License Type"].astype(str).str.contains("Provisional", case=False, na=False)].copy()
        df = df[df["Name"].notna()].copy()

        total_rows = len(df)
        self.stdout.write(self.style.SUCCESS(f"Found {total_rows} provisional records"))

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run selected. No data will be saved."))
            return

        nurse_cadre, _ = Cadre.objects.get_or_create(name="Nursing", defaults={"category": "nursing"})
        nurse_ct = ContentType.objects.get_for_model(NursingProfessional)

        created_professionals = 0
        updated_professionals = 0
        created_applications = 0
        created_qualifications = 0

        with transaction.atomic():
            for index, row in df.iterrows():
                name = clean_cell(row.get("Name", ""))
                if not name:
                    continue

                name_parts = name.split()
                first_name = limit_text(name_parts[0], 100)
                last_name = limit_text(" ".join(name_parts[1:]) if len(name_parts) > 1 else "", 100)

                source_id = row.get("ID")
                try:
                    source_id = int(source_id)
                except Exception:
                    source_id = index + 1

                provisional_no = clean_cell(row.get("Provisional/No", ""))
                registration_no = f"PROV-{source_id}"

                issued = pd.to_datetime(row.get("Issued_Date"), errors="coerce", dayfirst=True)
                issued_date = issued.date() if not pd.isna(issued) else date.today()
                expiry_date = issued_date + timedelta(days=180) if issued_date else None

                qualification = clean_cell(row.get("Qualification", ""))
                institution_name = clean_cell(row.get("Institution_Attended", ""))
                year_value = row.get("Year")
                try:
                    year_value = int(year_value)
                except Exception:
                    year_value = None

                institution = None
                applicant_type = applicant_type_for_institution(institution_name)
                if institution_name:
                    institution_type = classify_training_institution(institution_name)
                    institution, created = TrainingInstitution.objects.get_or_create(
                        name=institution_name[:255],
                        defaults={"type": institution_type},
                    )
                    if not created and institution.type != institution_type:
                        institution.type = institution_type
                        institution.save(update_fields=["type"])

                professional, created = NursingProfessional.objects.update_or_create(
                    registration_no=registration_no,
                    defaults={
                        "first_name": first_name,
                        "last_name": last_name,
                        "applicant_type": applicant_type,
                        "gender": "Female",
                        "primary_phone": "",
                        "email": "",
                        "date_issued": issued_date,
                        "license_expiry_date": expiry_date,
                        "qualification_level": limit_text(qualification, 100),
                        "cadre": nurse_cadre,
                        "is_active": True,
                    },
                )
                if created:
                    created_professionals += 1
                else:
                    updated_professionals += 1

                application_notes = (
                    f"Imported from {workbook.name} / {sheet_name}. "
                    f"Original provisional number: {provisional_no or 'n/a'}. "
                    f"Institution: {institution_name or 'n/a'}. "
                    f"Qualification: {qualification or 'n/a'}."
                )

                application, _ = Application.objects.update_or_create(
                    content_type=nurse_ct,
                    object_id=professional.id,
                    form_code="NC1",
                    defaults={
                        "status": "approved",
                        "expiry_date": expiry_date,
                        "reviewer_notes": application_notes,
                    },
                )
                application.submitted_date = issued_date
                application.approved_date = issued_date
                application.expiry_date = expiry_date
                application.reviewer_notes = application_notes
                application.status = "approved"
                application.save(update_fields=["submitted_date", "approved_date", "expiry_date", "reviewer_notes", "status"])
                created_applications += 1

                if qualification:
                    _, qual_created = Qualification.objects.get_or_create(
                        content_type=nurse_ct,
                        object_id=professional.id,
                        qualification_name=qualification,
                        defaults={
                            "institution": institution,
                            "completion_year": year_value,
                            "qualification_type": "Provisional License",
                        },
                    )
                    if qual_created:
                        created_qualifications += 1

        self.stdout.write(self.style.SUCCESS("Provisional import completed"))
        self.stdout.write(f"Professionals created: {created_professionals}")
        self.stdout.write(f"Professionals updated: {updated_professionals}")
        self.stdout.write(f"Applications processed: {created_applications}")
        self.stdout.write(f"Qualifications processed: {created_qualifications}")
