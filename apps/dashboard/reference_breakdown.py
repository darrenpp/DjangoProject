from collections import defaultdict

from django.core.cache import cache

from apps.workforce.models import Facility, PracticingLicenseRecord, TrainingInstitution
from apps.workforce.services.institution_classification import (
    classify_training_institution,
    normalize_institution_text,
)


PNG_NURSING_SCHOOL_RULES = (
    {
        "name": "APIASETS School of Nursing",
        "ownership": "non_government",
        "aliases": ("APIASETS", "ASIA PACIFIC INSTITUTE OF APPLIED SOCIAL"),
    },
    {
        "name": "Atoifi Adventist College of Nursing",
        "ownership": "non_government",
        "aliases": ("ATOIFI ADVENTIST", "ATOIFI"),
    },
    {
        "name": "Bougainville College of Nursing",
        "ownership": "government",
        "aliases": ("BOUGAINVILLE COLLEGE OF NURSING", "BOUGANINVILLE COLLEGE OF NURSING", "ARAWA SCHOOL OF NURSING", "ARAWA SON", "ASON AROB", "AWAWA SON"),
    },
    {
        "name": "Divine Word University School of Nursing",
        "ownership": "non_government",
        "aliases": ("DIVINE WORD UNIVERSITY", "DWU SON", "DWU SCHOOL OF NURSING"),
    },
    {
        "name": "East Sepik School of Nursing",
        "ownership": "government",
        "aliases": ("EAST SEPIK SCHOOL OF NURSING", "EAST SEPIK SON", "EAST SEPIK COLLEGE OF NURSING"),
    },
    {
        "name": "Enga College of Nursing",
        "ownership": "government",
        "aliases": ("ENGA COLLEGE OF NURSING", "ENGA CON", "ENGA SON", "ENGAN CON"),
    },
    {
        "name": "Goroka School of Nursing",
        "ownership": "government",
        "aliases": ("GOROKA SCHOOL OF NURSING", "GOROKA SON"),
    },
    {
        "name": "Highlands Regional College of Nursing",
        "ownership": "needs_review",
        "aliases": ("HIGHLANDS REGIONAL COLLEGE OF NURSING", "HIGHLANDS REGIONAL CON", "HIGHLANDS REGIONAL COLLEGE", "HIGHLANDS REGINONAL COLLEGE", "HIGHLANDS REGIONAL", "HIGHLAND REGIONAL", "HIGHLANDS COLLEGE OF NURSING", "HIGHLAND COLLEGE OF NURSING"),
    },
    {
        "name": "Kundiawa College of Nursing",
        "ownership": "government",
        "aliases": ("KUNDIAWA COLLEGE OF NURSING", "KUNDIAWA"),
    },
    {
        "name": "Lae School of Nursing",
        "ownership": "government",
        "aliases": ("LAE SCHOOL OF NURSING", "LAE SON", "LEA SON"),
    },
    {
        "name": "Lutheran School of Nursing",
        "ownership": "non_government",
        "aliases": ("LUTHERAN SCHOOL OF NURSING", "LUTHERAN SON", "LUSON", "LUSON", "LUSON"),
    },
    {
        "name": "Madang School of Nursing",
        "ownership": "government",
        "aliases": ("MADANG SCHOOL OF NURSING", "MADANG SON"),
    },
    {
        "name": "Mendi School of Nursing",
        "ownership": "government",
        "aliases": ("MENDI SCHOOL OF NURSING", "MENDI SON", "MENDI"),
    },
    {
        "name": "Nazarene College of Nursing",
        "ownership": "non_government",
        "aliases": ("NAZARENE COLLEGE OF NURSING", "NAZARENE CON", "NAZERENE CON", "NARAZENE CON", "NAZARENE"),
    },
    {
        "name": "Pacific Adventist University School of Nursing",
        "ownership": "non_government",
        "aliases": ("PACIFIC ADVENTIST", "PAU"),
    },
    {
        "name": "Sacred Heart School of Nursing, Lemakot",
        "ownership": "non_government",
        "aliases": ("SACRED HEART", "LEMAKOT SON", "LEMAKOT SACRED HEART", "SCARED HEART"),
    },
    {
        "name": "St Barnabas School of Nursing",
        "ownership": "non_government",
        "aliases": ("ST BARNABAS", "ST BARNBAS", "BARNABAS SON", "ST BANABAS", "ST BARBANAS", "ST BARANABAS"),
    },
    {
        "name": "St Benedict's School of Nursing",
        "ownership": "non_government",
        "aliases": ("ST BENEDICT",),
    },
    {
        "name": "St Mary's School of Nursing",
        "ownership": "non_government",
        "aliases": ("ST MARY", "ST MAY", "ST. MARY", "ST MARYS", "ST MARY'S"),
    },
    {
        "name": "West New Britain School of Nursing",
        "ownership": "government",
        "aliases": ("WEST NEW BRITAIN SCHOOL OF NURSING", "WNB SCHOOL OF NURSING", "WNB SON"),
    },
)

OVERSEAS_KEYWORDS = (
    "PHILIPP",
    "INDIA",
    "AUSTRALIA",
    "NEW ZEALAND",
    " NZ ",
    "USA",
    "AMERICA",
    "CANADA",
    "FIJI",
    "GERMAN",
    "SINGAPORE",
    "JAPAN",
    "CHINA",
    "MALAYSIA",
    "OVERSEAS",
    "ZIMBAB",
    "BRITISH",
)
CHW_KEYWORDS = (
    "CHW",
    "CHWTS",
    "CHWTC",
    "CHWTSP",
    "TRAINING SCHOOL",
    "TRAINING COLLEGE",
)
LOCAL_NURSING_HINTS = (
    "SCHOOL OF NURSING",
    "COLLEGE OF NURSING",
    " SON",
    " CON",
)
INSTITUTION_BREAKDOWN_CACHE_KEY = "dashboard_reference_breakdown_v3"


def _normalize_text(value):
    return normalize_institution_text(value)


def _clean_facility_name(value):
    text = " ".join(str(value or "").replace("\n", " ").split())
    upper = text.upper()
    if not text:
        return "Facility not captured"
    aliases = [
        (("POM GENERAL", "PORT MORESBY GENERAL"), "Port Moresby General Hospital"),
        (("ANGAU",), "ANGAU Memorial Hospital"),
        (("MT HAGEN", "MOUNT HAGEN"), "Mt Hagen Provincial Hospital"),
        (("KUNDIAWA",), "Kundiawa General Hospital"),
        (("NONGA",), "Nonga General Hospital"),
        (("ENGA PROVINCIAL",), "Enga Provincial Health Authority"),
        (("GOROKA",), "Goroka Provincial Hospital"),
        (("MENDI",), "Mendi Provincial Hospital"),
        (("ALOTAU",), "Alotau Provincial Hospital"),
        (("KIMBE",), "Kimbe General Hospital"),
    ]
    for tokens, label in aliases:
        if any(token in upper for token in tokens):
            return label
    for marker in [",", " PO BOX", " P O BOX", " PMB", " PRIVATE MAIL BAG", " BOX "]:
        index = upper.find(marker)
        if index > 6:
            text = text[:index].strip()
            break
    return text[:120].title()


def _matches_any(text, options):
    padded = f" {text} "
    return any(option in text or option in padded for option in options)


def _match_png_nursing_school(normalized_name):
    for rule in PNG_NURSING_SCHOOL_RULES:
        if _matches_any(normalized_name, rule["aliases"]):
            return rule
    return None


def build_reference_breakdown():
    cached = cache.get(INSTITUTION_BREAKDOWN_CACHE_KEY)
    if cached is not None:
        return cached

    institution_rows = list(TrainingInstitution.objects.values_list("name", "type"))
    raw_institution_total = len(institution_rows)

    school_matches = defaultdict(list)
    national_rows = []
    unmapped_local_rows = []
    overseas_rows = []
    chw_rows = []
    legacy_rows = []

    for name, institution_type in institution_rows:
        normalized_name = _normalize_text(name)
        normalized_type = _normalize_text(institution_type)
        if not normalized_name:
            continue
        if normalized_name.isdigit():
            legacy_rows.append(name)
            continue

        if classify_training_institution(name, institution_type) == "Overseas Institution":
            overseas_rows.append(name)
            continue

        if "CHW" in normalized_type or _matches_any(normalized_name, CHW_KEYWORDS):
            chw_rows.append(name)
            continue

        matched_school = _match_png_nursing_school(normalized_name)
        if matched_school:
            school_matches[matched_school["name"]].append(name)
            national_rows.append(name)
            continue

        if "NATIONAL" in normalized_type or _matches_any(normalized_name, LOCAL_NURSING_HINTS):
            national_rows.append(name)
            unmapped_local_rows.append(name)
            continue

        legacy_rows.append(name)

    nursing_school_rows = []
    for rule in PNG_NURSING_SCHOOL_RULES:
        matched_rows = school_matches.get(rule["name"], [])
        nursing_school_rows.append(
            {
                "name": rule["name"],
                "ownership": rule["ownership"],
                "raw_reference_count": len(matched_rows),
                "examples": matched_rows[:5],
            }
        )

    grouped_facility_names = {
        _clean_facility_name(value)
        for value in PracticingLicenseRecord.objects.exclude(workplace_address__isnull=True)
        .exclude(workplace_address="")
        .order_by()
        .values_list("workplace_address", flat=True)
        .distinct()
        if value
    }
    grouped_facility_names.discard("Facility not captured")

    reference_breakdown = {
        "raw_institution_total": raw_institution_total,
        "png_nursing_school_count": len(PNG_NURSING_SCHOOL_RULES),
        "government_nursing_school_count": sum(1 for row in nursing_school_rows if row["ownership"] == "government"),
        "non_government_nursing_school_count": sum(1 for row in nursing_school_rows if row["ownership"] == "non_government"),
        "review_nursing_school_count": sum(1 for row in nursing_school_rows if row["ownership"] == "needs_review"),
        "mapped_nursing_reference_count": sum(len(rows) for rows in school_matches.values()),
        "national_institution_reference_count": len(national_rows),
        "chw_training_reference_count": len(chw_rows),
        "overseas_institution_reference_count": len(overseas_rows),
        "unmapped_local_nursing_reference_count": len(unmapped_local_rows),
        "legacy_institution_reference_count": len(legacy_rows),
        "nursing_school_rows": nursing_school_rows,
        "national_examples": national_rows[:12],
        "unmapped_local_examples": unmapped_local_rows[:12],
        "overseas_examples": overseas_rows[:12],
        "legacy_examples": legacy_rows[:12],
        "facility_master_count": Facility.objects.count(),
        "facility_grouped_reference_count": len(grouped_facility_names),
        "facility_raw_reference_count": PracticingLicenseRecord.objects.exclude(workplace_address__isnull=True)
        .exclude(workplace_address="")
        .order_by()
        .values("workplace_address")
        .distinct()
        .count(),
    }
    cache.set(INSTITUTION_BREAKDOWN_CACHE_KEY, reference_breakdown, 300)
    return reference_breakdown
