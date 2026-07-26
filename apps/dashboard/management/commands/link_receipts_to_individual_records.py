from django.core.management.base import BaseCommand, CommandError

from apps.dashboard.receipt_linking import link_receipts_to_individual_records
from apps.workforce.models import AuditLog


class Command(BaseCommand):
    help = (
        "Link receipt/payment records to the application, account, professional, or imported "
        "licence row that paid. Unmatched or ambiguous receipts become high-severity reviews."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write payer links and high-value review records. Without this, only a dry run is reported.",
        )
        parser.add_argument(
            "--scope",
            choices=["all", "nursing", "medical"],
            default="all",
            help="Limit receipts to a regulatory office scope.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Only process the first N eligible receipts.",
        )
        parser.add_argument(
            "--include-failed",
            action="store_true",
            help="Include failed receipts. By default failed payment attempts are ignored.",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        if limit is not None and limit <= 0:
            raise CommandError("--limit must be greater than zero.")

        scope = None if options["scope"] == "all" else options["scope"]
        result = link_receipts_to_individual_records(
            apply_changes=options["apply"],
            scope=scope,
            limit=limit,
            include_failed=options["include_failed"],
        )

        if options["apply"]:
            AuditLog.objects.create(
                action="link_receipts_to_individual_records",
                entity_type="dashboard.receipt",
                entity_id=result["scope"],
                new_values_json=result,
            )

        self.stdout.write(self.style.SUCCESS("Receipt ownership linkage complete."))
        self.stdout.write(f"Mode: {result['mode']}")
        self.stdout.write(f"Scope: {result['scope']}")
        self.stdout.write(f"Receipts reviewed: {result['reviewed']}")
        self.stdout.write(f"New/updated payer links: {result['linked']}")
        self.stdout.write(f"Already linked: {result['already_linked']}")
        self.stdout.write(
            "Unmatched high-value reviews created/updated: "
            f"{result['unmatched_reviews_created']}/{result['unmatched_reviews_updated']}"
        )
        self.stdout.write(
            "Ambiguous high-value reviews created/updated: "
            f"{result['ambiguous_reviews_created']}/{result['ambiguous_reviews_updated']}"
        )
        self.stdout.write(f"Resolved receipt reviews: {result['resolved_reviews']}")
        self.stdout.write(f"Match rules: {result['by_rule']}")
