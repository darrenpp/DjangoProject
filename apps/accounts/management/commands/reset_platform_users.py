from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction


NEW_PLATFORM_USERS = [
    {
        "username": "system_admin",
        "password": "NDOH-Admin@2026!",
        "email": "system.admin@ndoh.gov.pg",
        "role": "admin",
        "department": "Administration",
        "is_superuser": True,
        "is_staff": True,
        "role_approved": True,
    },
    {
        "username": "nursing_registrar",
        "password": "NC-Registrar@2026!",
        "email": "nursing.registrar@ndoh.gov.pg",
        "role": "registrar",
        "department": "Nursing Council",
        "is_staff": True,
        "role_approved": True,
    },
    {
        "username": "medical_registrar",
        "password": "MB-Registrar@2026!",
        "email": "medical.registrar@ndoh.gov.pg",
        "role": "registrar",
        "department": "Medical Board",
        "is_staff": True,
        "role_approved": True,
    },
    {
        "username": "nursing_reviewer",
        "password": "NC-Reviewer@2026!",
        "email": "nursing.reviewer@ndoh.gov.pg",
        "role": "reviewer",
        "department": "Nursing Council",
        "is_staff": True,
        "role_approved": True,
    },
    {
        "username": "medical_reviewer",
        "password": "MB-Reviewer@2026!",
        "email": "medical.reviewer@ndoh.gov.pg",
        "role": "reviewer",
        "department": "Medical Board",
        "is_staff": True,
        "role_approved": True,
    },
    {
        "username": "finance_officer",
        "password": "Finance@2026!",
        "email": "finance.officer@ndoh.gov.pg",
        "role": "reviewer",
        "department": "Finance",
        "is_staff": True,
        "role_approved": True,
    },
    {
        "username": "data_quality_officer",
        "password": "DataQuality@2026!",
        "email": "data.quality@ndoh.gov.pg",
        "role": "reviewer",
        "department": "Data Quality",
        "is_staff": True,
        "role_approved": True,
    },
    {
        "username": "nurse_user",
        "password": "Nurse@2026!",
        "email": "nurse.user@ndoh.gov.pg",
        "role": "nurse",
        "department": "Nursing Council",
        "registration_number": "PG-2324",
        "license_number": "PG-2324",
        "role_approved": True,
    },
    {
        "username": "graduand_user",
        "password": "Graduand@2026!",
        "email": "graduand.user@ndoh.gov.pg",
        "role": "graduand",
        "department": "Nursing Council",
        "registration_number": "678765",
        "license_number": "678765",
        "role_approved": True,
    },
    {
        "username": "nurse_aide_user",
        "password": "NurseAide@2026!",
        "email": "nurse.aide.user@ndoh.gov.pg",
        "role": "nurse_aide",
        "department": "Nursing Council",
        "registration_number": "3943",
        "license_number": "O11994",
        "role_approved": True,
    },
    {
        "username": "chw_user",
        "password": "CHW@2026!",
        "email": "chw.user@ndoh.gov.pg",
        "role": "chw",
        "department": "Medical Board",
        "registration_number": "9157",
        "license_number": "G 4926",
        "role_approved": True,
    },
    {
        "username": "doctor_user",
        "password": "Doctor@2026!",
        "email": "doctor.user@ndoh.gov.pg",
        "role": "doctor",
        "department": "Medical Board",
        "role_approved": True,
    },
    {
        "username": "viewer_user",
        "password": "Viewer@2026!",
        "email": "viewer.user@ndoh.gov.pg",
        "role": "viewer",
        "department": "General Registry",
        "role_approved": True,
    },
]


class Command(BaseCommand):
    help = "Remove existing login accounts and create clean role-based platform accounts while preserving registry data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Required. Confirms existing user accounts should be replaced.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if not options["confirm"]:
            self.stderr.write("Use --confirm to reset platform user accounts.")
            return

        User = apps.get_model(settings.AUTH_USER_MODEL)

        archive_user, _created = User.objects.update_or_create(
            username="system_archive",
            defaults={
                "email": "system.archive@ndoh.gov.pg",
                "role": "viewer",
                "department": "System Archive",
                "is_active": False,
                "is_staff": False,
                "is_superuser": False,
                "role_approved": False,
            },
        )
        archive_user.set_unusable_password()
        archive_user.save()

        old_users = User.objects.exclude(pk=archive_user.pk)
        old_user_count = old_users.count()

        self._preserve_user_links(old_users, archive_user)
        old_users.delete()

        created_users = []
        for spec in NEW_PLATFORM_USERS:
            spec = spec.copy()
            password = spec.pop("password")
            user = User(**spec)
            user.is_active = True
            user.is_email_verified = True
            user.set_password(password)
            user.save()
            created_users.append((user.username, user.role, password))

        self.stdout.write(self.style.SUCCESS(f"Removed {old_user_count} existing login account(s)."))
        self.stdout.write(self.style.SUCCESS(f"Created {len(created_users)} clean platform account(s)."))
        for username, role, password in created_users:
            self.stdout.write(f"{username}|{role}|{password}")

    def _preserve_user_links(self, old_users, archive_user):
        user_ids = list(old_users.values_list("id", flat=True))
        if not user_ids:
            return

        try:
            Receipt = apps.get_model("dashboard", "Receipt")
            Receipt.objects.filter(user_id__in=user_ids).update(user=None)
        except LookupError:
            pass

        try:
            Notification = apps.get_model("notifications", "Notification")
            Notification.objects.filter(user_id__in=user_ids).update(user=archive_user)
            EnquiryThread = apps.get_model("notifications", "EnquiryThread")
            EnquiryThread.objects.filter(created_by_id__in=user_ids).update(created_by=archive_user)
            EnquiryThread.objects.filter(assigned_to_id__in=user_ids).update(assigned_to=None)
            EnquiryMessage = apps.get_model("notifications", "EnquiryMessage")
            EnquiryMessage.objects.filter(sender_id__in=user_ids).update(sender=archive_user)
        except LookupError:
            pass

        try:
            DocumentAccessPolicy = apps.get_model("documents", "DocumentAccessPolicy")
            DocumentAccessPolicy.objects.filter(user_id__in=user_ids).update(user=None)
        except LookupError:
            pass
