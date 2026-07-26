from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.dashboard.nursing_catherine_breakdown import (
    DEFAULT_CADRE_BREAKDOWN_WORKBOOK,
    DEFAULT_CLEANED_LICENCE_WORKBOOK,
    import_catherine_breakdown,
)


class Command(BaseCommand):
    help = (
        "Import Catherine's cleaned Nursing Council provisional/full-licence workbooks as a "
        "refreshable analytics verification overlay without duplicating legal registry records."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--licence-workbook",
            type=str,
            default=str(DEFAULT_CLEANED_LICENCE_WORKBOOK),
            help="Path to PNG_Nursing_Council_Cleaned_Licence_Breakdown.xlsx.",
        )
        parser.add_argument(
            "--cadre-workbook",
            type=str,
            default=str(DEFAULT_CADRE_BREAKDOWN_WORKBOOK),
            help="Path to PNG_Nursing_Council_Cadre_Breakdown.xlsx.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Create a new verification batch even if the same workbook hash pair was already imported.",
        )

    def handle(self, *args, **options):
        licence_path = Path(options["licence_workbook"])
        cadre_path = Path(options["cadre_workbook"])
        if not licence_path.exists():
            raise CommandError(f"Cleaned licence workbook not found: {licence_path}")
        if not cadre_path.exists():
            raise CommandError(f"Cadre breakdown workbook not found: {cadre_path}")

        batch, snapshot, created = import_catherine_breakdown(
            licence_workbook_path=licence_path,
            cadre_workbook_path=cadre_path,
            force=options["force"],
        )
        summary = batch.summary or {}
        comparison = summary.get("active_snapshot_comparison", {})
        clean_rows = summary.get("licence_dashboard", {}).get("Clean rows retained after exact dedupe", {})
        institution_rows = summary.get("licence_dashboard", {}).get("Rows included in institution/year breakdown", {})
        unclassified_rows = summary.get("cadre_breakdown", {}).get("unclassified_clean_rows", 0)

        action = "Imported" if created else "Reused existing"
        self.stdout.write(self.style.SUCCESS(f"{action} Catherine Nursing licence verification batch #{batch.pk}"))
        self.stdout.write(f"Source kind: {batch.source_kind}")
        self.stdout.write(f"Combined source hash: {summary.get('combined_source_hash')}")
        self.stdout.write(
            "Clean rows retained: "
            f"Provisional={clean_rows.get('provisional', 0)}, "
            f"Full Licence={clean_rows.get('full_licence', 0)}, "
            f"Combined={clean_rows.get('combined', 0)}"
        )
        self.stdout.write(
            "Institution/year rows included: "
            f"Provisional={institution_rows.get('provisional', 0)}, "
            f"Full Licence={institution_rows.get('full_licence', 0)}, "
            f"Combined={institution_rows.get('combined', 0)}"
        )
        self.stdout.write(f"Unclassified clean rows: {unclassified_rows}")
        self.stdout.write(f"Active snapshot comparison: {comparison.get('status', 'not compared')}")
        self.stdout.write(f"Database action: {comparison.get('database_action', 'verification batch only')}")
        if snapshot:
            self.stdout.write(f"Attached overlay to active Nursing analytics snapshot #{snapshot.pk}")
        else:
            self.stdout.write(self.style.WARNING("No active Nursing analytics snapshot was available to attach this overlay."))
