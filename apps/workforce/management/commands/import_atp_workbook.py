from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.workforce.services.data_quality import audit_imported_license_rows, audit_professional_profiles
from apps.workforce.services.ndata_workbook_import import NDataWorkbookImporter


DEFAULT_ATP_WORKBOOK = Path(
    r"C:\Users\darre\OneDrive\Documents\ProjectApps\databasedocuments\spreadsheets\ATP_LATEST_FROM_JOYCE\2026 Current ATP-DATA Statistics & Tracking latest.xlsx"
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
        parser.add_argument(
            "--sync-live-profiles",
            action="store_true",
            help=(
                "Also create/update live professional and application rows. "
                "Leave disabled for ATP cycle imports so licence renewals do not inflate live worker totals."
            ),
        )
        parser.add_argument(
            "--sheet",
            dest="sheet_names",
            action="append",
            default=[],
            help=(
                "Optional exact worksheet tab to import. Repeat this option to import multiple tabs. "
                "When omitted, all supported ATP record and payment sheets are imported."
            ),
        )

    def handle(self, *args, **options):
        workbook = Path(options["file"])
        if not workbook.exists():
            raise CommandError(f"Workbook not found: {workbook}")

        sheet_names = [name.strip() for name in options["sheet_names"] if name and name.strip()]
        try:
            importer = NDataWorkbookImporter(
                workbook_path=workbook,
                sync_live_profiles=options["sync_live_profiles"],
                sheet_names=sheet_names,
            )
            batch = importer.import_workbook()
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        profile_audit = audit_professional_profiles(send_notifications=False)
        import_audit = audit_imported_license_rows(batch=batch)

        self.stdout.write(self.style.SUCCESS(f"Imported ATP workbook batch #{batch.id}"))
        self.stdout.write(f"Status: {batch.status}")
        self.stdout.write(f"Sheets processed: {batch.processed_sheets}/{batch.total_sheets}")
        if sheet_names:
            self.stdout.write(f"Selected sheets: {', '.join(sheet_names)}")
        self.stdout.write(f"Rows imported: {batch.processed_rows}")
        self.stdout.write(f"Missing profile audit: {profile_audit}")
        self.stdout.write(f"Missing import-row audit: {import_audit}")
        self.stdout.write(f"Summary: {batch.summary}")
