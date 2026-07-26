from django.core.management.base import BaseCommand

from apps.workforce.services.data_quality import audit_imported_license_rows
from apps.workforce.services.medical_board_legacy_import import (
    DEFAULT_MEDICAL_BOARD_LEGACY_WORKBOOKS,
    MedicalBoardLegacyWorkbookImporter,
)


class Command(BaseCommand):
    help = "Import Medical Board legacy professional workbooks as Medical Board-only records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            action="append",
            dest="files",
            help="Path to a Medical Board legacy workbook. Repeat for multiple workbooks. Defaults to the known current files.",
        )
        parser.add_argument(
            "--sheets",
            action="append",
            help="Comma or repeatable list of sheet names to include (legacy importer only).",
        )
        parser.add_argument(
            "--include-sheet",
            dest="include_sheet",
            action="append",
            help="Alias for --sheets (supports sheet-name filtering).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Run mapping only and do not persist records.",
        )
        parser.add_argument(
            "--preview",
            action="store_true",
            help="Alias for --dry-run when previewing importability.",
        )
        parser.add_argument(
            "--skip-audit",
            action="store_true",
            help="Skip missing-data audit for imported rows.",
        )

    def handle(self, *args, **options):
        paths = options["files"] or [str(path) for path in DEFAULT_MEDICAL_BOARD_LEGACY_WORKBOOKS]
        include_sheets = []
        for raw in (options.get("sheets") or []) + (options.get("include_sheet") or []):
            include_sheets.extend([part.strip() for part in raw.split(",") if part.strip()])
        dry_run = bool(options.get("dry_run") or options.get("preview"))
        batch = MedicalBoardLegacyWorkbookImporter(
            workbook_paths=paths,
            include_sheets=include_sheets,
            dry_run=dry_run,
        ).import_workbooks()
        if dry_run:
            self.stdout.write(self.style.WARNING("Legacy importer preview mode: no rows were persisted."))
            summary = batch.summary or {}
            self.stdout.write(f"Sheets processed: {summary.get('sheets_imported', 0)}")
            self.stdout.write(f"Sheets skipped: {summary.get('sheets_skipped', 0)}")
            self.stdout.write(f"Records that would be created: {summary.get('records_created', 0)}")
            self.stdout.write("Record-type mix:")
            for record_type in ("full", "provisional", "workforce_listing", "practicing_license", "payment"):
                self.stdout.write(f"  - {record_type}: {summary.get(f'record_type_{record_type}', 0)}")
            for report in summary.get("sheet_reports", []):
                self.stdout.write(
                    f" - {report.get('source_file', '')} :: {report.get('source_sheet', '')} "
                    f"[{report.get('status', '')}] layout={report.get('layout', 'n/a')} "
                    f"imported={report.get('imported_rows', 0)} skipped={report.get('skipped_rows', 0)}"
                )
            return

        import_audit = {"skipped": True} if options["skip_audit"] else audit_imported_license_rows(batch=batch)
        summary = batch.summary or {}
        self.stdout.write(self.style.SUCCESS(
            f"Imported Medical Board legacy workbook batch #{batch.id}: "
            f"{summary.get('records_created', 0)} import records, "
            f"{summary.get('medical_doctors_upserted', 0)} Medical Doctor profiles, "
            f"{summary.get('other_rows', 0)} allied-health/other rows."
        ))
        self.stdout.write(f"Missing import-row audit: {import_audit}")
