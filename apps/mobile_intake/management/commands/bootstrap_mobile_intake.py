from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.mobile_intake.services.bootstrap import bootstrap_mobile_forms


class Command(BaseCommand):
    help = "Bootstrap mobile intake form schemas for Android offline intake."

    def add_arguments(self, parser):
        parser.add_argument("--created-by", default="", help="Optional username recorded as schema creator.")

    def handle(self, *args, **options):
        user = None
        username = options.get("created_by")
        if username:
            user = get_user_model().objects.filter(username=username).first()
            if not user:
                self.stdout.write(self.style.WARNING(f"Creator user {username!r} was not found."))
        result = bootstrap_mobile_forms(created_by=user)
        self.stdout.write(self.style.SUCCESS(
            f"Mobile intake schemas bootstrapped: {result['created']} created, {result['updated']} updated."
        ))
