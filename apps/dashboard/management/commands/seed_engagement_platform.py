import re

from django.core.management.base import BaseCommand
from django.db.models import Sum

from apps.dashboard.models import (
    FAQCategory,
    FAQEntry,
    ForumCategory,
    MappedEntity,
)
from apps.dashboard.nursing_analytics import active_nursing_analytics_snapshot
from apps.workforce.models import Facility, TrainingInstitution


FAQ_SEED = [
    (
        "Public Registry and Licence Verification",
        "public-registry-and-licence-verification",
        "Questions for the public about checking registration and licence status.",
        [
            (
                "How do I verify if a nurse has authority to practice?",
                "Use the public register search or contact the Nursing Council if a record cannot be verified online. Analytics snapshot rows are for reporting and must not be treated as legal proof unless the operational register confirms them.",
                "verify licence ATP authority practice registered nurse",
            ),
            (
                "Why can a cleansed workbook record appear outside the legal registry?",
                "The cleansed workbook feeds analytics and quality review. Legal registration depends on approved operational registry records and Council workflows.",
                "analytics snapshot legal registry workbook",
            ),
        ],
    ),
    (
        "Applications and Renewals",
        "applications-and-renewals",
        "Questions for provisional, full-licence and ATP applicants.",
        [
            (
                "Where do provisional licence applicants start?",
                "PNG nursing graduands should use the provisional licence pathway and submit the required identification, education, payment and institution evidence.",
                "provisional licence NC1 graduand",
            ),
            (
                "What happens after full-licence approval?",
                "Approved practitioners move into the active register and must keep ATP renewal, CPD, payment and workplace details current.",
                "full licence approved ATP renewal",
            ),
        ],
    ),
    (
        "Schools, Institutions and Facilities",
        "schools-institutions-and-facilities",
        "Questions about approved education institutions, facilities and map references.",
        [
            (
                "Why is a school or facility on the map marked pending verification?",
                "The platform stores local map records first. Coordinates and Google Place IDs should be verified by authorised staff before they are treated as official.",
                "map school facility verification google",
            ),
        ],
    ),
]


FORUM_SEED = [
    ("Public Questions", "public-questions", "Public", "public", "shared", True, True, 10),
    ("Registration and Licensing", "registration-and-licensing", "General registration, licensing and workflow questions.", "public", "shared", True, True, 20),
    ("Provisional Licence Support", "provisional-licence-support", "Private discussion area for provisional licence holders and graduands.", "provisional", "nursing", True, False, 30),
    ("Full Licence Applicants", "full-licence-applicants", "Private discussion area for full-licence applicants.", "full_applicant", "nursing", True, False, 40),
    ("ATP Renewal", "atp-renewal", "Renewal questions for active practitioners.", "practitioner", "shared", True, False, 50),
    ("Registered Nurses Forum", "registered-nurses-forum", "Private discussion area for registered nurses.", "registered_nurse", "nursing", True, False, 60),
    ("Nursing Council Staff Forum", "nursing-council-staff-forum", "Internal Nursing Council staff discussion.", "nursing_staff", "nursing", False, False, 70),
    ("Medical Board Staff Forum", "medical-board-staff-forum", "Internal Medical Board staff discussion.", "medical_staff", "medical", False, False, 80),
    ("Training Institutions", "training-institutions", "Institution, school and accreditation questions.", "public", "shared", True, True, 90),
    ("Facility and Employer Questions", "facility-and-employer-questions", "Facility and employer verification questions.", "public", "shared", True, True, 100),
]


def normalize_name(value):
    return " ".join(str(value or "").strip().lower().split())


INVALID_ENTITY_NAMES = {"", ".", "-", "--", "n/a", "na", "none", "null", "unknown"}


def display_entity_name(value):
    return str(value or "").strip(" \t\r\n-.")


def is_valid_entity_name(value):
    normalized = normalize_name(display_entity_name(value))
    if normalized in INVALID_ENTITY_NAMES:
        return False
    if len(normalized) < 3:
        return False
    if normalized.isdigit():
        return False
    if re.fullmatch(r"[\W_]+", normalized):
        return False
    return any(character.isalpha() for character in normalized)


def institution_scope(institution):
    text = f"{institution.name} {institution.type} {institution.regulatory_body_name} {institution.source_reference}".lower()
    if any(token in text for token in ["medical", "chw", "community health"]):
        return "medical"
    if any(token in text for token in ["nursing", "nurse", "midwife", "midwifery"]):
        return "nursing"
    return "shared"


def institution_type(institution):
    text = f"{institution.name} {institution.type}".lower()
    if "school" in text or "college" in text or "university" in text or "training" in text:
        return "school"
    return "institution"


def facility_entity_type(facility):
    text = f"{facility.name} {facility.type}".lower()
    if "hospital" in text:
        return "hospital"
    if "provincial health authority" in text or "pha" in text:
        return "pha"
    if "private" in text or facility.ownership == "private":
        return "private_clinic"
    return "facility"


class Command(BaseCommand):
    help = "Seed FAQs, forums, and local map references for Nursing Council / Medical Board engagement."

    def add_arguments(self, parser):
        parser.add_argument("--skip-map-refresh", action="store_true", help="Only seed FAQ and forum rows.")

    def handle(self, *args, **options):
        faq_count = self.seed_faqs()
        forum_count = self.seed_forums()
        map_count = 0
        if not options["skip_map_refresh"]:
            map_count = self.seed_mapped_entities()
        self.stdout.write(self.style.SUCCESS(
            f"Seeded engagement platform: FAQs={faq_count}, forum categories={forum_count}, mapped entities refreshed={map_count}"
        ))

    def seed_faqs(self):
        total = 0
        for order, (name, slug, description, entries) in enumerate(FAQ_SEED, start=1):
            category, _created = FAQCategory.objects.update_or_create(
                slug=slug,
                defaults={
                    "name": name,
                    "description": description,
                    "audience": "public",
                    "office_scope": "shared",
                    "display_order": order * 10,
                    "is_active": True,
                },
            )
            for entry_order, (question, answer, keywords) in enumerate(entries, start=1):
                FAQEntry.objects.update_or_create(
                    category=category,
                    question=question,
                    defaults={
                        "answer": answer,
                        "keywords": keywords,
                        "display_order": entry_order * 10,
                        "is_published": True,
                    },
                )
                total += 1
        return total

    def seed_forums(self):
        total = 0
        for name, slug, description, visibility, scope, moderation, public_posts, order in FORUM_SEED:
            ForumCategory.objects.update_or_create(
                slug=slug,
                defaults={
                    "name": name,
                    "description": description,
                    "visibility": visibility,
                    "office_scope": scope,
                    "requires_moderation": moderation,
                    "allow_public_posts": public_posts,
                    "display_order": order,
                    "is_active": True,
                },
            )
            total += 1
        return total

    def seed_mapped_entities(self):
        refreshed = self.clean_existing_mapped_entities()
        for institution in TrainingInstitution.objects.all().order_by("name"):
            name = display_entity_name(institution.name)
            if not is_valid_entity_name(name):
                continue
            normalized = normalize_name(name)
            scope = institution_scope(institution)
            entity_type = institution_type(institution)
            defaults = {
                "name": name,
                "entity_type": entity_type,
                "office_scope": scope,
                "province": institution.location_name[:120],
                "district": "",
                "address": institution.location_name,
                "source": institution.source_reference or "training_institution",
                "source_model": "workforce.TrainingInstitution",
                "source_object_id": str(institution.pk),
                "verification_status": "pending",
                "is_active": institution.is_active,
            }
            MappedEntity.objects.update_or_create(
                normalized_name=normalized,
                entity_type=entity_type,
                office_scope=scope,
                province=defaults["province"],
                defaults=defaults,
            )
            refreshed += 1

        for facility in Facility.objects.select_related("location").all().order_by("name"):
            name = display_entity_name(facility.name)
            if not is_valid_entity_name(name):
                continue
            normalized = normalize_name(name)
            province = facility.location.province if facility.location else ""
            district = facility.location.district if facility.location else ""
            defaults = {
                "name": name,
                "entity_type": facility_entity_type(facility),
                "office_scope": "shared",
                "province": province,
                "district": district,
                "address": str(facility.location or ""),
                "source": "facility_master",
                "source_model": "workforce.Facility",
                "source_object_id": str(facility.pk),
                "verification_status": "pending",
                "is_active": True,
            }
            MappedEntity.objects.update_or_create(
                normalized_name=normalized,
                entity_type=defaults["entity_type"],
                office_scope="shared",
                province=province,
                defaults=defaults,
            )
            refreshed += 1

        snapshot = active_nursing_analytics_snapshot()
        if snapshot:
            refreshed += self.seed_snapshot_institutions(snapshot)
            refreshed += self.seed_snapshot_facilities(snapshot)
        return refreshed

    def clean_existing_mapped_entities(self):
        cleaned = 0
        for entity in MappedEntity.objects.all().only("id", "name", "is_active", "verification_status"):
            clean_name = display_entity_name(entity.name)
            if not is_valid_entity_name(clean_name) or clean_name != entity.name:
                entity.is_active = False
                entity.verification_status = "rejected"
                entity.save(update_fields=["is_active", "verification_status", "updated_at"])
                cleaned += 1
        return cleaned

    def seed_snapshot_institutions(self, snapshot):
        count = 0
        rows = (
            snapshot.institution_cadre_year_metrics
            .values("institution")
            .annotate(total=Sum("count"))
            .order_by("-total", "institution")[:300]
        )
        for row in rows:
            name = display_entity_name(row["institution"])
            if not is_valid_entity_name(name):
                continue
            normalized = normalize_name(name)
            MappedEntity.objects.update_or_create(
                normalized_name=normalized,
                entity_type="school",
                office_scope="nursing",
                province="",
                defaults={
                    "name": name,
                    "source": f"nursing_analytics_snapshot:{snapshot.pk}",
                    "source_model": "dashboard.NursingInstitutionCadreYearMetric",
                    "active_workforce_count": row["total"] or 0,
                    "verification_status": "pending",
                    "is_active": True,
                },
            )
            count += 1
        return count

    def seed_snapshot_facilities(self, snapshot):
        count = 0
        rows = (
            snapshot.facility_cadre_year_metrics
            .values("facility", "province", "organization_type")
            .annotate(total=Sum("count"))
            .order_by("-total", "facility")[:500]
        )
        for row in rows:
            name = display_entity_name(row["facility"])
            if not is_valid_entity_name(name):
                continue
            normalized = normalize_name(name)
            org_type = row.get("organization_type") or ""
            entity_type = "private_clinic" if "private" in org_type.lower() else "facility"
            MappedEntity.objects.update_or_create(
                normalized_name=normalized,
                entity_type=entity_type,
                office_scope="nursing",
                province=row.get("province") or "",
                defaults={
                    "name": name,
                    "province": row.get("province") or "",
                    "source": f"nursing_analytics_snapshot:{snapshot.pk}",
                    "source_model": "dashboard.NursingFacilityCadreYearMetric",
                    "active_workforce_count": row["total"] or 0,
                    "verification_status": "pending",
                    "is_active": True,
                },
            )
            count += 1
        return count
