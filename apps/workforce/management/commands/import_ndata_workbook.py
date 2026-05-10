from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.workforce.services.ndata_workbook_import import DEFAULT_WORKBOOK, NDataWorkbookImporter
from apps.workforce.services.data_quality import audit_imported_license_rows, audit_professional_profiles


class Command(BaseCommand):
    help = "Import the N-DATA statistics and tracking workbook into normalized registry tables."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            default=str(DEFAULT_WORKBOOK),
            help="Path to the N-DATA workbook.",
        )

    def handle(self, *args, **options):
        workbook = Path(options["file"])
        if not workbook.exists():
            raise CommandError(f"Workbook not found: {workbook}")

        importer = NDataWorkbookImporter(workbook_path=workbook)
        batch = importer.import_workbook()
        profile_audit = audit_professional_profiles(send_notifications=True)
        import_audit = audit_imported_license_rows(batch=batch)

        self.stdout.write(self.style.SUCCESS(f"Imported workbook batch #{batch.id}"))
        self.stdout.write(f"Status: {batch.status}")
        self.stdout.write(f"Sheets processed: {batch.processed_sheets}/{batch.total_sheets}")
        self.stdout.write(f"Rows imported: {batch.processed_rows}")
        self.stdout.write(f"Missing profile audit: {profile_audit}")
        self.stdout.write(f"Missing import-row audit: {import_audit}")
        self.stdout.write(f"Summary: {batch.summary}")
