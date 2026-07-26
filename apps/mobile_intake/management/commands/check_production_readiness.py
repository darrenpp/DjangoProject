from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from apps.documents.models import DocumentFolder
from apps.mobile_intake.models import MobileFormSchema
from apps.workforce.models import ApplicationPathway, RegulatoryBody


class Command(BaseCommand):
    help = "Check launch-critical production readiness settings and platform bootstrap state."

    def add_arguments(self, parser):
        parser.add_argument("--no-fail", action="store_true", help="Print blockers without returning a command failure.")

    def handle(self, *args, **options):
        blockers = []
        warnings = []

        def require(condition, message):
            if not condition:
                blockers.append(message)

        def warn(condition, message):
            if not condition:
                warnings.append(message)

        require(settings.DEBUG is False, "DEBUG must be False.")
        require(bool(settings.ALLOWED_HOSTS), "ALLOWED_HOSTS must be configured.")
        require(getattr(settings, "USE_HTTPS", False), "USE_HTTPS must be True.")
        require(settings.SESSION_COOKIE_SECURE, "SESSION_COOKIE_SECURE must be True.")
        require(settings.CSRF_COOKIE_SECURE, "CSRF_COOKIE_SECURE must be True.")
        require(settings.SECURE_SSL_REDIRECT, "SECURE_SSL_REDIRECT must be True.")
        require(settings.SECURE_HSTS_SECONDS >= 31536000, "SECURE_HSTS_SECONDS must be at least 31536000.")
        require(settings.SECURE_HSTS_INCLUDE_SUBDOMAINS, "SECURE_HSTS_INCLUDE_SUBDOMAINS must be True.")
        require(settings.SECURE_HSTS_PRELOAD, "SECURE_HSTS_PRELOAD must be True.")
        require(getattr(settings, "REQUIRE_STAFF_MFA", False), "REQUIRE_STAFF_MFA must be enabled.")
        require(len(settings.SECRET_KEY) >= 50, "SECRET_KEY must be a strong configured secret.")

        db_configured = bool(settings.DATABASES.get("default", {}).get("ENGINE")) and "sqlite" not in settings.DATABASES["default"]["ENGINE"]
        require(db_configured, "Production database must be configured and must not be SQLite.")
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        except Exception as exc:
            blockers.append(f"Database connectivity failed: {exc}")

        require(settings.EMAIL_BACKEND != "django.core.mail.backends.console.EmailBackend", "Production email backend must not be console-only.")
        require(bool(getattr(settings, "EMAIL_HOST", "")), "EMAIL_HOST must be configured.")
        require(bool(getattr(settings, "MEDIA_ROOT", "")), "MEDIA_ROOT/media storage must be configured.")
        warn(bool(getattr(settings, "BACKUP_ROOT", "") or getattr(settings, "DATABASE_BACKUP_PATH", "")), "Backup root/path is not configured.")

        User = get_user_model()
        require(User.objects.filter(role="admin", is_superuser=True, is_active=True).exists(), "At least one active System Admin superuser is required.")
        require(
            User.objects.filter(
                role="registrar",
                is_active=True,
                role_approved=True,
                system_admin_approved=True,
            ).exists(),
            "At least one Registrar with registrar and System Admin approval is required.",
        )
        warn(not User.objects.filter(password__icontains="pbkdf2_sha256$").filter(username__icontains="test").exists(), "Review and change any remaining test accounts/passwords.")

        require(DocumentFolder.objects.exists(), "Document repository folders must be bootstrapped.")
        require(RegulatoryBody.objects.filter(is_active=True).exists(), "Regulatory bodies must be bootstrapped.")
        require(ApplicationPathway.objects.filter(active=True).exists(), "Workflow/application pathways must be bootstrapped.")
        require(MobileFormSchema.objects.filter(is_enabled=True).exists(), "Mobile intake form schemas must be bootstrapped.")

        warn(False, "Pending external launch gates: NDOH ICT hosting, domain/HTTPS, production email test, restore drill, vulnerability scan, penetration test, UAT sign-off, staff training, support owner.")

        if blockers:
            self.stdout.write(self.style.ERROR("Production readiness blockers:"))
            for blocker in blockers:
                self.stdout.write(f" - {blocker}")
        else:
            self.stdout.write(self.style.SUCCESS("No critical production readiness blockers found."))

        if warnings:
            self.stdout.write(self.style.WARNING("Warnings and launch gates:"))
            for warning in warnings:
                self.stdout.write(f" - {warning}")

        if blockers and not options["no_fail"]:
            raise CommandError("Production readiness check failed.")
