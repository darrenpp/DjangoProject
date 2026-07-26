import ipaddress
import socket

from django.conf import settings
from django.core.management.base import BaseCommand
from django.test import Client
from django.urls import reverse

from apps.mobile_intake.models import MobileFormSchema


def local_ipv4_addresses():
    addresses = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            value = info[4][0]
            ip = ipaddress.ip_address(value)
            if ip.is_private and not ip.is_loopback:
                addresses.append(value)
    except OSError:
        pass
    return list(dict.fromkeys(addresses))


class Command(BaseCommand):
    help = "Print and smoke-check the local Django-to-Android integrated testing setup."

    def add_arguments(self, parser):
        parser.add_argument("--port", default="8000", help="Local Django port. Defaults to 8000.")
        parser.add_argument(
            "--check-api",
            action="store_true",
            help="Run an in-process smoke check against /api/mobile/v1/health/.",
        )

    def handle(self, *args, **options):
        port = str(options["port"])
        phone_ips = local_ipv4_addresses()
        desktop_url = f"http://127.0.0.1:{port}/"
        emulator_url = f"http://10.0.2.2:{port}/"

        self.stdout.write(self.style.SUCCESS("Local mobile integrated testing setup"))
        self.stdout.write("")
        self.stdout.write("Start Django with:")
        self.stdout.write(self.style.WARNING(f"  python manage.py runserver 0.0.0.0:{port}"))
        self.stdout.write("")
        self.stdout.write("Use these base URLs:")
        self.stdout.write(f"  Desktop browser : {desktop_url}")
        self.stdout.write(f"  Android emulator: {emulator_url}")
        if phone_ips:
            for ip in phone_ips:
                self.stdout.write(f"  Physical phone  : http://{ip}:{port}/")
        else:
            self.stdout.write("  Physical phone  : run ipconfig and use http://YOUR-PC-IP:8000/")

        self.stdout.write("")
        self.stdout.write("Mobile API smoke endpoints:")
        for path in (
            "api/mobile/v1/health/",
            "api/mobile/v1/auth/login/",
            "api/mobile/v1/bootstrap/",
            "api/mobile/v1/forms/",
            "api/mobile/v1/lookups/",
            "api/mobile/v1/submissions/status/",
            "api/mobile/v1/accounts/register/",
            "api/mobile/v1/accounts/status/",
        ):
            self.stdout.write(f"  {emulator_url}{path}")

        self.stdout.write("")
        self.stdout.write("Windows firewall rule for phone testing, run PowerShell as Administrator:")
        self.stdout.write(self.style.WARNING(
            f'  netsh advfirewall firewall add rule name="Django Local Test {port}" dir=in action=allow protocol=TCP localport={port}'
        ))
        self.stdout.write("")
        self.stdout.write("USB fallback for a physical phone:")
        self.stdout.write(self.style.WARNING(f"  adb reverse tcp:{port} tcp:{port}"))
        self.stdout.write(f"  Then use http://127.0.0.1:{port}/ inside the phone app.")

        self.stdout.write("")
        self.stdout.write("Current Django local settings:")
        self.stdout.write(f"  DEBUG={settings.DEBUG}")
        self.stdout.write(f"  LOCAL_MOBILE_TESTING={getattr(settings, 'LOCAL_MOBILE_TESTING', False)}")
        self.stdout.write(f"  ALLOWED_HOSTS={', '.join(settings.ALLOWED_HOSTS)}")
        self.stdout.write(f"  Enabled mobile form schemas={MobileFormSchema.objects.filter(is_enabled=True).count()}")

        if options["check_api"]:
            health_url = reverse("mobile_v1_health")
            response = Client(HTTP_HOST="127.0.0.1").get(health_url)
            if response.status_code == 200 and response.json().get("status") == "ok":
                self.stdout.write(self.style.SUCCESS(f"Health endpoint OK: {health_url}"))
            else:
                self.stdout.write(self.style.ERROR(
                    f"Health endpoint failed: {health_url} returned HTTP {response.status_code}"
                ))
