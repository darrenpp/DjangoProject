from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Delete application data while preserving authorised system users and authentication records."

    protected_models = {
        "accounts.User",
        "auth.Group",
        "auth.Permission",
        "contenttypes.ContentType",
        "admin.LogEntry",
        "sessions.Session",
    }

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without making changes.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        User = get_user_model()
        deleted = []

        with transaction.atomic():
            for model in django_apps.get_models():
                label = f"{model._meta.app_label}.{model.__name__}"
                if label in self.protected_models or not model._meta.managed:
                    continue
                if model is User:
                    continue

                count = model.objects.count()
                if count == 0:
                    continue

                deleted.append((label, count))
                if not dry_run:
                    model.objects.all().delete()

        if deleted:
            for label, count in deleted:
                action = "Would delete" if dry_run else "Deleted"
                self.stdout.write(f"{action} {count} rows from {label}")
        else:
            self.stdout.write("No non-user data found.")
