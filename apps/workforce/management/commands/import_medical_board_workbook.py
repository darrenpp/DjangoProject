from django.core.management.base import BaseCommand

from apps.workforce.services.medical_board_workbook_import import (
    DEFAULT_MEDICAL_BOARD_WORKBOOK,
    MedicalBoardWorkbookImporter,
)
from apps.workforce.services.data_quality import audit_imported_license_rows, audit_professional_profiles


class Command(BaseCommand):
    help = "Import the Medical Board CHW workbook into the centralized workforce registry."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            default=str(DEFAULT_MEDICAL_BOARD_WORKBOOK),
            help="Path to the Medical Board workbook.",
        )

    def handle(self, *args, **options):
        batch = MedicalBoardWorkbookImporter(workbook_path=options["file"]).import_workbook()
        profile_audit = audit_professional_profiles(send_notifications=True)
        import_audit = audit_imported_license_rows(batch=batch)
        summary = batch.summary or {}
        self.stdout.write(self.style.SUCCESS(
            f"Imported Medical Board workbook batch #{batch.id}: "
            f"{summary.get('chw_imported', 0)} CHW records, "
            f"{summary.get('pending_chw_imported', 0)} pending records, "
            f"{summary.get('training_institutions_imported', 0)} training institutions."
        ))
        self.stdout.write(f"Missing profile audit: {profile_audit}")
        self.stdout.write(f"Missing import-row audit: {import_audit}")
