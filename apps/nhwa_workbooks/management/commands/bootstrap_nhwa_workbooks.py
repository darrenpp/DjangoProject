from django.core.management.base import BaseCommand

from apps.nhwa_workbooks.services import bootstrap_web_workbooks


class Command(BaseCommand):
    help = "Create or refresh editable NHWA web workbooks from the controlled source workbook."

    def add_arguments(self, parser):
        parser.add_argument("--source", default="", help="Optional path to the NHWA source workbook.")

    def handle(self, *args, **options):
        result = bootstrap_web_workbooks(source_path=options.get("source") or None)
        self.stdout.write(
            self.style.SUCCESS(
                "NHWA web workbooks bootstrapped: "
                f"{result['workbooks']} new workbook(s), "
                f"{result['sheets']} new sheet(s), "
                f"{result['cells']} new cell template(s)."
            )
        )
