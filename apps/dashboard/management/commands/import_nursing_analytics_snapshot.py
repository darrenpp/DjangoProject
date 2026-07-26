from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.dashboard.nursing_analytics_import import (
    DEFAULT_NURSING_ANALYTICS_WORKBOOK,
    NursingAnalyticsSnapshotImporter,
)


class Command(BaseCommand):
    help = "Import the cleansed Nursing Council integrated analytics workbook as the active dashboard snapshot."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            default=str(DEFAULT_NURSING_ANALYTICS_WORKBOOK),
            help="Path to PNG_Nursing_Council_Integrated_Dashboard_Model.xlsx.",
        )
        parser.add_argument(
            "--no-activate",
            action="store_true",
            help="Import the snapshot but do not make it the active Nursing Council dashboard source.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-import even when a snapshot with the same workbook hash already exists.",
        )

    def handle(self, *args, **options):
        workbook_path = Path(options["file"])
        if not workbook_path.exists():
            raise CommandError(f"Workbook not found: {workbook_path}")

        importer = NursingAnalyticsSnapshotImporter(
            workbook_path=workbook_path,
            activate=not options["no_activate"],
            force=options["force"],
        )
        snapshot, created = importer.import_workbook()

        action = "Imported" if created else "Reused existing"
        self.stdout.write(self.style.SUCCESS(f"{action} Nursing Council analytics snapshot #{snapshot.pk}"))
        self.stdout.write(f"Snapshot UUID: {snapshot.snapshot_id}")
        self.stdout.write(f"Active: {snapshot.is_active}")
        self.stdout.write(f"Workbook generated on: {snapshot.workbook_generated_on or 'not supplied'}")
        self.stdout.write(f"Rows imported: {snapshot.imported_rows}")
        self.stdout.write(f"KPI summary: {snapshot.kpi_summary}")
