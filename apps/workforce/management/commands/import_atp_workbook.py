from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.workforce.services.data_quality import audit_imported_license_rows, audit_professional_profiles
from apps.workforce.services.ndata_workbook_import import NDataWorkbookImporter


DEFAULT_ATP_WORKBOOK = Path(
    r"C:\Users\timhi\OneDrive\Desktop\ParotOs\NDOH_Database\ATP_LATEST\2026 Current ATP-DATA Statistics & Tracking latest.xlsx"
)


class Command(BaseCommand):
    help = "Import the current Authority To Practice workbook into the Nursing Council analytics store."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            default=str(DEFAULT_ATP_WORKBOOK),
            help="Path to the ATP workbook.",
        )

    def handle(self, *args, **options):
        workbook = Path(options["file"])
        if not workbook.exists():
            raise CommandError(f"Workbook not found: {workbook}")

        importer = NDataWorkbookImporter(workbook_path=workbook)
        batch = importer.import_workbook()
        profile_audit = audit_professional_profiles(send_notifications=False)
        import_audit = audit_imported_license_rows(batch=batch)

        self.stdout.write(self.style.SUCCESS(f"Imported ATP workbook batch #{batch.id}"))
        self.stdout.write(f"Status: {batch.status}")
        self.stdout.write(f"Sheets processed: {batch.processed_sheets}/{batch.total_sheets}")
        self.stdout.write(f"Rows imported: {batch.processed_rows}")
        self.stdout.write(f"Missing profile audit: {profile_audit}")
        self.stdout.write(f"Missing import-row audit: {import_audit}")
        self.stdout.write(f"Summary: {batch.summary}")
