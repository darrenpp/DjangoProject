from django.core.management.base import BaseCommand

from apps.workforce.models import DataImportBatch
from apps.workforce.services.data_quality import (
    audit_imported_license_rows,
    audit_professional_profiles,
    notify_expiring_licenses,
)


class Command(BaseCommand):
    help = "Audit workforce records for missing required data and notify affected profiles."

    def add_arguments(self, parser):
        parser.add_argument(
            "--send-notifications",
            action="store_true",
            help="Create profile notifications and send email where contact details exist.",
        )
        parser.add_argument(
            "--audit-import-rows",
            action="store_true",
            help="Also flag incomplete imported licence-history rows.",
        )
        parser.add_argument(
            "--latest-batch",
            action="store_true",
            help="When auditing import rows, only audit the latest completed N-DATA workbook batch.",
        )
        parser.add_argument(
            "--notify-expiring",
            action="store_true",
            help="Send licence expiry reminders for records nearing expiry.",
        )
        parser.add_argument(
            "--expiry-days",
            type=int,
            default=30,
            help="Number of days ahead to check for licence expiry reminders.",
        )

    def handle(self, *args, **options):
        profile_result = audit_professional_profiles(
            send_notifications=options["send_notifications"],
        )
        self.stdout.write(self.style.SUCCESS(
            "Profile audit: "
            f"{profile_result['reviewed']} reviewed, "
            f"{profile_result['created']} created, "
            f"{profile_result['updated']} updated, "
            f"{profile_result['resolved']} resolved, "
            f"{profile_result['open_reviews']} open."
        ))

        if options["audit_import_rows"]:
            batch = None
            if options["latest_batch"]:
                batch = DataImportBatch.objects.filter(
                    source_kind='ndata_workbook',
                    status='completed',
                ).order_by('-started_at').first()
            import_result = audit_imported_license_rows(batch=batch)
            batch_label = f" batch #{batch.id}" if batch else ""
            self.stdout.write(self.style.SUCCESS(
                "Import-row audit"
                f"{batch_label}: {import_result['reviewed']} reviewed, "
                f"{import_result['created']} created, "
                f"{import_result['updated']} updated, "
                f"{import_result['resolved']} resolved, "
                f"{import_result['open_reviews']} open."
            ))

        if options["notify_expiring"]:
            expiry_result = notify_expiring_licenses(days=options["expiry_days"])
            self.stdout.write(self.style.SUCCESS(
                f"Expiry reminders: {expiry_result['notified']} notifications/emails created "
                f"for licences expiring within {expiry_result['days']} days."
            ))
