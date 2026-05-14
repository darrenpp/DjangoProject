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
            "--skip-audit",
            action="store_true",
            help="Skip missing-data audit for imported rows.",
        )

    def handle(self, *args, **options):
        paths = options["files"] or [str(path) for path in DEFAULT_MEDICAL_BOARD_LEGACY_WORKBOOKS]
        batch = MedicalBoardLegacyWorkbookImporter(workbook_paths=paths).import_workbooks()
        import_audit = {"skipped": True} if options["skip_audit"] else audit_imported_license_rows(batch=batch)
        summary = batch.summary or {}
        self.stdout.write(self.style.SUCCESS(
            f"Imported Medical Board legacy workbook batch #{batch.id}: "
            f"{summary.get('records_created', 0)} import records, "
            f"{summary.get('medical_doctors_upserted', 0)} Medical Doctor profiles, "
            f"{summary.get('other_rows', 0)} allied-health/other rows."
        ))
        self.stdout.write(f"Missing import-row audit: {import_audit}")
