import json
import re
import time
import urllib.parse
import urllib.request
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.dashboard.models import MappedEntity, MappedEntityVerification


INVALID_ENTITY_NAMES = {"", ".", "-", "--", "n/a", "na", "none", "null", "unknown"}


def normalize_name(value):
    return " ".join(str(value or "").strip().lower().split())


def is_valid_entity_name(value):
    normalized = normalize_name(str(value or "").strip(" \t\r\n-."))
    if normalized in INVALID_ENTITY_NAMES:
        return False
    if len(normalized) < 3:
        return False
    if normalized.isdigit():
        return False
    if re.fullmatch(r"[\W_]+", normalized):
        return False
    return any(character.isalpha() for character in normalized)


class Command(BaseCommand):
    help = "Populate stored MappedEntity coordinates using the Google Geocoding API."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=50, help="Maximum records to geocode in this run.")
        parser.add_argument(
            "--office",
            choices=["all", "nursing", "medical", "shared"],
            default="all",
            help="Limit by office scope.",
        )
        parser.add_argument("--type", dest="entity_type", default="all", help="Limit by mapped entity type.")
        parser.add_argument("--dry-run", action="store_true", help="Show candidate queries without saving results.")
        parser.add_argument("--force", action="store_true", help="Re-geocode records that already have coordinates.")

    def handle(self, *args, **options):
        api_key = getattr(settings, "GOOGLE_GEOCODING_API_KEY", "").strip()
        if not api_key:
            raise CommandError(
                "GOOGLE_GEOCODING_API_KEY or GOOGLE_MAPS_API_KEY is not configured. Add a key to .env and restart Django."
            )

        limit = max(options["limit"], 0)
        if limit == 0:
            self.stdout.write("No records requested.")
            return

        queryset = MappedEntity.objects.filter(is_active=True).order_by("name")
        if not options["force"]:
            queryset = queryset.filter(latitude__isnull=True, longitude__isnull=True)
        if options["office"] != "all":
            queryset = queryset.filter(office_scope=options["office"])
        if options["entity_type"] != "all":
            queryset = queryset.filter(entity_type=options["entity_type"])

        updated = 0
        skipped = 0
        failed = 0
        for entity in queryset[:limit]:
            if not is_valid_entity_name(entity.name):
                skipped += 1
                continue

            query = self.build_query(entity)
            if options["dry_run"]:
                self.stdout.write(f"{entity.pk}: {query}")
                skipped += 1
                continue

            result = self.geocode(api_key, query)
            status = result.get("status")
            if status != "OK" or not result.get("results"):
                failed += 1
                error_message = result.get("error_message", "")
                detail = f"{status}: {error_message}" if error_message else status
                self.stdout.write(self.style.WARNING(f"{entity.pk}: {entity.name} not geocoded ({detail})"))
                continue

            first = result["results"][0]
            location = first["geometry"]["location"]
            previous_status = entity.verification_status
            entity.latitude = Decimal(str(location["lat"]))
            entity.longitude = Decimal(str(location["lng"]))
            entity.google_place_id = first.get("place_id", "")
            if entity.verification_status != "verified":
                entity.verification_status = "pending"
            entity.save(update_fields=[
                "latitude",
                "longitude",
                "google_place_id",
                "verification_status",
                "updated_at",
            ])
            MappedEntityVerification.objects.create(
                entity=entity,
                previous_status=previous_status,
                new_status=entity.verification_status,
                note="Google Geocoding API coordinates stored for staff verification.",
            )
            updated += 1
            self.stdout.write(self.style.SUCCESS(f"{entity.pk}: {entity.name} -> {entity.latitude}, {entity.longitude}"))
            time.sleep(0.1)

        self.stdout.write(self.style.SUCCESS(
            f"Geocoding complete: updated={updated}, skipped={skipped}, failed={failed}"
        ))

    def build_query(self, entity):
        parts = [
            entity.name,
            entity.address,
            entity.district,
            entity.province,
            "Papua New Guinea",
        ]
        return ", ".join(part for part in parts if part)

    def geocode(self, api_key, query):
        params = urllib.parse.urlencode({"address": query, "key": api_key})
        url = f"https://maps.googleapis.com/maps/api/geocode/json?{params}"
        with urllib.request.urlopen(url, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
