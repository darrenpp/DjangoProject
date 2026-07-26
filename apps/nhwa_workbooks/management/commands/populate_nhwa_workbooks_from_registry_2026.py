from django.core.management.base import BaseCommand

from apps.nhwa_workbooks.population import populate_workbooks_from_2026_registry


class Command(BaseCommand):
    help = "Populate NHWA web workbooks from verified 2026 database records only."

    def add_arguments(self, parser):
        parser.add_argument(
            "--scope",
            choices=["all", "nursing", "medical"],
            default="all",
            help="Limit population to one office scope.",
        )
        parser.add_argument(
            "--year",
            type=int,
            default=2026,
            help="Database record_year/completion_year to use for workbook population.",
        )

    def handle(self, *args, **options):
        scope = options["scope"]
        scopes = None if scope == "all" else (scope,)
        result = populate_workbooks_from_2026_registry(year=options["year"], scopes=scopes)
        for office_scope, summary in result.items():
            self.stdout.write(
                self.style.SUCCESS(
                    f"{office_scope}: populated {summary['changed_cells']} workbook cell(s) "
                    f"from {options['year']} database records."
                )
            )
