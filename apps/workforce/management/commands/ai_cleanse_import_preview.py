from pathlib import Path

import pandas as pd
from django.core.management.base import BaseCommand, CommandError

from apps.workforce.services.ai_import_cleanser import cleanse_rows, dumps_report


class Command(BaseCommand):
    help = (
        "Preview AI-assisted import cleansing suggestions without writing to live registry tables. "
        "Default mode is local/offline unless external GPT cleansing is explicitly enabled."
    )

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Path to CSV or Excel workbook to preview.")
        parser.add_argument("--sheet", default=None, help="Excel sheet name. Defaults to the first sheet.")
        parser.add_argument("--rows", type=int, default=25, help="Number of rows to preview.")
        parser.add_argument("--scope", choices=["nursing", "medical", "all"], default="nursing")
        parser.add_argument("--output", default="", help="Optional JSON output path.")

    def _read_rows(self, path, sheet_name, rows):
        suffix = path.suffix.lower()
        if suffix == ".csv":
            frame = pd.read_csv(path, nrows=rows)
        elif suffix in {".xls", ".xlsx", ".xlsm"}:
            frame = pd.read_excel(path, sheet_name=sheet_name or 0, nrows=rows)
        else:
            raise CommandError("Only CSV and Excel files are supported for cleansing preview.")
        frame = frame.fillna("")
        return frame.to_dict(orient="records")

    def handle(self, *args, **options):
        path = Path(options["file"])
        if not path.exists():
            raise CommandError(f"Import file not found: {path}")

        rows = self._read_rows(path, options["sheet"], options["rows"])
        report = cleanse_rows(
            rows,
            source_label=path.name if not options["sheet"] else f"{path.name} / {options['sheet']}",
            scope=options["scope"],
        )

        output = options["output"]
        if output:
            output_path = Path(output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(dumps_report(report), encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Wrote cleansing preview: {output_path}"))

        self.stdout.write(self.style.SUCCESS("AI import cleansing preview complete."))
        self.stdout.write(f"Rows reviewed: {report['row_count']}")
        self.stdout.write(f"Issues detected: {report['issue_count']}")
        self.stdout.write(f"Rows needing human review: {report['requires_human_review']}")
        if not output:
            self.stdout.write(dumps_report(report))
