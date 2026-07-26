from django.core.management.base import BaseCommand

from apps.dashboard.registry_archive import (
    DEFAULT_LAPSED_YEARS,
    DEFAULT_RETIREMENT_AGE,
    current_archive_year,
    sync_registry_archives,
)


class Command(BaseCommand):
    help = "Create or refresh registry archive records for old-age, lapsed-renewal, inactive, retired, and deceased-review records."

    def add_arguments(self, parser):
        parser.add_argument("--scope", choices=["all", "nursing", "medical"], default="all")
        parser.add_argument("--year", type=int, default=current_archive_year())
        parser.add_argument("--retirement-age", type=int, default=DEFAULT_RETIREMENT_AGE)
        parser.add_argument("--lapsed-years", type=int, default=DEFAULT_LAPSED_YEARS)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--limit", type=int, default=None)

    def handle(self, *args, **options):
        result = sync_registry_archives(
            scope=options["scope"],
            current_year=options["year"],
            retirement_age=options["retirement_age"],
            lapsed_years=options["lapsed_years"],
            dry_run=options["dry_run"],
            limit=options["limit"],
        )
        mode = "would archive" if options["dry_run"] else "archived"
        self.stdout.write(
            self.style.SUCCESS(
                f"{mode} {result['reviewed']} record(s): {result['created']} created, {result['updated']} updated."
            )
        )
