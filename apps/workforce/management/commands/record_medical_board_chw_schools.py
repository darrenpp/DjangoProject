from django.core.management.base import BaseCommand
from django.db import transaction

from apps.dashboard.report_freshness import mark_report_data_changed
from apps.workforce.models import AuditLog, TrainingInstitution


SOURCE_REFERENCE = "PNG Medical Board accredited/licensed CHW training institutions list photographed 2026-05-26"
REGULATORY_BODY = "PNG Medical Board"
TYPE_LABEL = "CHW Training School"
COUNTRY = "Papua New Guinea"


SCHOOLS = [
    {
        "row": 1,
        "name": "Braun CHW Training School",
        "source_name": "Braun CHW T School",
        "ownership": "Lutheran Church",
        "location": "Finschafen",
        "status": "Registered",
        "aliases": ["Braun", "Braun CHWTS", "Braun Training School", "Braun APO Training School"],
    },
    {
        "row": 2,
        "name": "Gaubin CHW Training School",
        "source_name": "Gaubin CHW T School",
        "ownership": "Lutheran Church",
        "location": "Karkar Island, Madang",
        "status": "Registered",
        "aliases": ["Gaubin", "Gaubin CHWTS"],
    },
    {
        "row": 3,
        "name": "Telefomin CHW Training College",
        "source_name": "Telefomin CHW T College",
        "ownership": "Baptist Church",
        "location": "Telefomin, West Sepik Province",
        "status": "Registered",
        "aliases": ["Telefomin", "Telefomin CHWTC", "Telefomin CHW T College"],
    },
    {
        "row": 4,
        "name": "Onamuga CHW Training College",
        "source_name": "Onamuga CHW T College",
        "ownership": "Salvation Army",
        "location": "Kainantu, Eastern Highlands Province",
        "status": "Registered",
        "aliases": ["Onamuga", "Onamuga CHWTC"],
    },
    {
        "row": 5,
        "name": "Kumin Training College",
        "source_name": "Kumin Training College",
        "ownership": "Catholic Church",
        "location": "Mendi, Southern Highlands Province",
        "status": "Registered",
        "aliases": ["Kumin", "Kumin CHWTS"],
    },
    {
        "row": 6,
        "name": "Kugumanda CHW Training College",
        "source_name": "Kugumanda CHW T College",
        "ownership": "Four Square Church",
        "location": "Wapenamanda, Enga Province",
        "status": "Registered",
        "aliases": ["Kugumanda", "Kugumanda CHWTS", "Kugumanda Foursquare CHWTS"],
    },
    {
        "row": 7,
        "name": "Kundiawa CHW Training College",
        "source_name": "Kundiawa CHW Training College",
        "ownership": "Private",
        "location": "Kundiawa, Simbu Province",
        "status": "In Progress",
        "aliases": ["Kundiawa", "Kundiawa CHWTC"],
    },
    {
        "row": 8,
        "name": "Rumginae CHW Training College",
        "source_name": "Rumginae CHW Training College",
        "ownership": "Evangelical Church of PNG",
        "location": "Kiunga, Western Province",
        "status": "Registered",
        "aliases": ["Rumginae", "Rumginae CHWTS"],
    },
    {
        "row": 9,
        "name": "Tinsley CHW Training College",
        "source_name": "Tinsley CHW Training College",
        "ownership": "Baptist Church",
        "location": "Baiyer, Western Highlands Province",
        "status": "Registered",
        "aliases": ["Tinsley", "Tinsey", "Tinsley CHWTS"],
    },
    {
        "row": 10,
        "name": "Kapuna CHW Training College",
        "source_name": "Kapuna CHW Training College",
        "ownership": "Church of Gulf",
        "location": "Kikori, Gulf Province",
        "status": "Registered",
        "aliases": ["Kapuna", "Kapuna CHWTS"],
    },
    {
        "row": 11,
        "name": "St. Gerard CHW Training College",
        "source_name": "St. Gerard CHW Training College",
        "ownership": "Catholic Church",
        "location": "Bereina, Central Province",
        "status": "Registered",
        "aliases": ["St Gerard", "St. Gerard", "Gerard's", "Gerards"],
    },
    {
        "row": 12,
        "name": "St Margaret CHW Training College",
        "source_name": "St Margaret CHW Training College",
        "ownership": "Anglican Church",
        "location": "Popondetta, Northern Province",
        "status": "Registered",
        "aliases": ["St Margaret", "St. Margaret", "St Margarets", "St. Margarets"],
    },
    {
        "row": 13,
        "name": "Salamo CHW Training College",
        "source_name": "Salamo CHW Training College",
        "ownership": "United Church",
        "location": "Salamo, Alotau",
        "status": "Registered",
        "aliases": ["Salamo", "Salamo CHWTC"],
    },
    {
        "row": 14,
        "name": "Rabaul CHW Training College",
        "source_name": "Rabaul CHW T College",
        "ownership": "Private",
        "location": "Rabaul, East New Britain Province",
        "status": "Registered",
        "aliases": ["Rabaul", "Rabaul CHWTC"],
    },
    {
        "row": 15,
        "name": "Lemakot CHW Training College",
        "source_name": "Lemakot CHW T College",
        "ownership": "Catholic Church",
        "location": "Kavieng, New Ireland Province",
        "status": "Registered",
        "aliases": ["Lemakot", "Lemakot CHWTC"],
    },
    {
        "row": 16,
        "name": "Tamanalo CHW Training College",
        "source_name": "Tamanalo CHW T College",
        "ownership": "AROB (Private)",
        "location": "Buka, Autonomous Region of Bougainville",
        "status": "In Progress",
        "aliases": ["Tamanalo", "Tamanalo CHWTC"],
    },
    {
        "row": 17,
        "name": "Kwikila CHW College",
        "source_name": "Kwikila CHW College",
        "ownership": "Private",
        "location": "Rigo, Central Province",
        "status": "Registered",
        "aliases": ["Kwikila", "Kwikila CHW College"],
    },
    {
        "row": 18,
        "name": "Tombil CHW College",
        "source_name": "Tombil CHW College",
        "ownership": "SDA Church",
        "location": "Banz, Jiwaka Province",
        "status": "Registered",
        "aliases": ["Tombil", "Tombil CHWTS", "Tombil Adventist CHWTS"],
    },
    {
        "row": 19,
        "name": "Okari AOG CHW Training College",
        "source_name": "Okari AOG CHW T College",
        "ownership": "AOG Church",
        "location": "Lae, Morobe Province",
        "status": "Registered",
        "aliases": ["Okari AOG", "Okari AOG CHWTC"],
    },
    {
        "row": 20,
        "name": "Bulu CHW Training College",
        "source_name": "Bulu CHW Training College",
        "ownership": "Private",
        "location": "Karkar Island, Madang Province",
        "status": "Registered",
        "aliases": ["Bulu", "Bulu CHWTC", "Bulu CHWT College"],
    },
    {
        "row": 21,
        "name": "PAI CHW Training College",
        "source_name": "PAI CHW Training College",
        "ownership": "Private",
        "location": "Mt Hagen, Western Highlands Province",
        "status": "Registered",
        "aliases": ["PAI", "PAI CHW College"],
    },
    {
        "row": 22,
        "name": "Career CHW Training College",
        "source_name": "Career CHW Training College",
        "ownership": "Private",
        "location": "Goroka, Eastern Highlands Province",
        "status": "Registered",
        "aliases": ["Career Training Inst.", "Career CHW Training College"],
    },
    {
        "row": 23,
        "name": "APIASETS CHW Training College",
        "source_name": "APIASETS CHW Training College",
        "ownership": "Private",
        "location": "Hohola, National Capital District",
        "status": "Registered",
        "aliases": ["APIASETS", "APIASETS CHWTS", "APIASETS National Capital District"],
    },
    {
        "row": 24,
        "name": "Raihu CHW Training College",
        "source_name": "Raihu CHW Training College",
        "ownership": "Catholic Church",
        "location": "West Sepik Province",
        "status": "Registered",
        "aliases": ["Raihu", "Raihu CHWTS", "Raihu CHTS"],
    },
]


class Command(BaseCommand):
    help = "Record the PNG Medical Board accredited/licensed CHW training institutions from the official photographed list."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Show what would be recorded without saving changes.")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        created = 0
        updated = 0
        unchanged = 0
        recorded = []

        with transaction.atomic():
            for row in SCHOOLS:
                institution, was_created = self._get_or_create_institution(row)
                before = {
                    "name": institution.name,
                    "type": institution.type,
                    "ownership": institution.ownership,
                    "location_name": institution.location_name,
                    "registration_status": institution.registration_status,
                    "regulatory_body_name": institution.regulatory_body_name,
                    "country": institution.country,
                    "source_reference": institution.source_reference,
                    "source_metadata": institution.source_metadata,
                    "is_active": institution.is_active,
                }
                metadata = {
                    "source_row": row["row"],
                    "source_name": row["source_name"],
                    "aliases": row.get("aliases", []),
                    "data_classification": "internal_reference",
                    "source_note": "Transcribed from user-provided Medical Board CHW training institution photographs.",
                }
                institution.name = row["name"]
                institution.type = TYPE_LABEL
                institution.ownership = row["ownership"]
                institution.location_name = row["location"]
                institution.registration_status = row["status"]
                institution.regulatory_body_name = REGULATORY_BODY
                institution.country = COUNTRY
                institution.source_reference = SOURCE_REFERENCE
                institution.source_metadata = metadata
                institution.is_active = True

                after = {
                    "name": institution.name,
                    "type": institution.type,
                    "ownership": institution.ownership,
                    "location_name": institution.location_name,
                    "registration_status": institution.registration_status,
                    "regulatory_body_name": institution.regulatory_body_name,
                    "country": institution.country,
                    "source_reference": institution.source_reference,
                    "source_metadata": institution.source_metadata,
                    "is_active": institution.is_active,
                }

                if before == after and not was_created:
                    unchanged += 1
                else:
                    if was_created:
                        created += 1
                    else:
                        updated += 1
                    institution.save()

                recorded.append(
                    {
                        "row": row["row"],
                        "name": row["name"],
                        "ownership": row["ownership"],
                        "location": row["location"],
                        "registration_status": row["status"],
                        "regulatory_body": REGULATORY_BODY,
                    }
                )

            if dry_run:
                transaction.set_rollback(True)
            else:
                AuditLog.objects.create(
                    actor=None,
                    action="MEDICAL_BOARD_CHW_TRAINING_INSTITUTIONS_RECORDED",
                    entity_type="TrainingInstitution",
                    entity_id="medical-board-chw-schools",
                    new_values_json={
                        "source_reference": SOURCE_REFERENCE,
                        "recorded_count": len(recorded),
                        "created": created,
                        "updated": updated,
                        "unchanged": unchanged,
                        "schools": recorded,
                    },
                )
                mark_report_data_changed(
                    scope="medical",
                    reason="Medical Board CHW training institution reference update",
                    source_label=SOURCE_REFERENCE,
                )

        prefix = "Dry run: " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}recorded {len(recorded)} Medical Board CHW training institution reference row(s): "
                f"{created} created, {updated} updated, {unchanged} unchanged."
            )
        )

    def _get_or_create_institution(self, row):
        candidate_names = [row["name"], row["source_name"], *row.get("aliases", [])]
        for name in candidate_names:
            institution = TrainingInstitution.objects.filter(name__iexact=name).order_by("id").first()
            if institution:
                if institution.name != row["name"] and TrainingInstitution.objects.filter(name__iexact=row["name"]).exclude(pk=institution.pk).exists():
                    return TrainingInstitution.objects.get(name__iexact=row["name"]), False
                return institution, False
        return TrainingInstitution(name=row["name"]), True
