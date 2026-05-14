import re


OVERSEAS_INSTITUTION_TERMS = (
    "AMERICA",
    "AMERICAN",
    "AFRICA",
    "AUST",
    "AUSSIE",
    "AUCKLAND",
    "AUSTRALIA",
    "AVONDALE UNIVERSITY",
    "BANGLADESH",
    "BANGALORE",
    "CANADA",
    "CEBU",
    "CHAD",
    "CHAMBERLAIN COLLEGE",
    "CHENNAI",
    "CHINA",
    "CURTIN UNIVERSITY",
    "DEAKIN UNIVERSITY",
    "FIJI",
    "FINDERS UNIVERSITY",
    "FINNISH",
    "FLINDERS UNIVERSITY",
    "INDIA",
    "INDONESEA",
    "INDONESIA",
    "IRELAND",
    "ITALY",
    "JAPAN",
    "JAMES COOK UNIVERSITY",
    "KARNATAKA",
    "LOMA LINDA UNIVERSITY",
    "LONDON",
    "MALAYSIA",
    "MANILA",
    "METROPOLITAN UNIVERSITY FINNISH",
    "MONOROVIA",
    "MOUNT ROYAL UNIVERSITY",
    "MOUNT ROYL UNIVERSITY",
    "NEW MEXICO",
    "NEW ZEALAND",
    "NEW ZEALND",
    "NEW ZELAND",
    "NEWCASTLE",
    "NSW",
    "PHILIPP",
    "POLAND",
    "PRINCESS MARGARET HOSPITAL",
    "QUEENSLAND",
    "SCOTLAND",
    "SINGAPORE",
    "SOUTH AFRICA",
    "SOUTH AUSTRALIA",
    "SOUTH BANK UNIVERSITY",
    "SOUTHERN ADVENTIST UNIVERSITY",
    "SOUTHERN CROSS UNIVERSITY",
    "SYDNEY",
    "TAMILNADU",
    "TASMANIA",
    "THAILAND",
    "TORINO",
    "TURKEY",
    "UGANDA",
    "UNITED KINGDOM",
    "UNITED STATES",
    "USA",
    "VICTORIA AUSTRALIA",
    "WAIKATO",
    "WESTERN GOVERNORS UNIVERSITY",
    "WITWATERSRAND",
    "ZIMBAB",
)

OVERSEAS_SHORT_CODES = ("NZ", "UK", "USA")


def normalize_institution_text(value):
    normalized = re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper())
    return re.sub(r"\s+", " ", normalized).strip()


def is_overseas_institution(name, institution_type=""):
    normalized_name = normalize_institution_text(name)
    normalized_type = normalize_institution_text(institution_type)
    if not normalized_name:
        return False
    if "OVERSEAS" in normalized_type:
        return True
    if any(term in normalized_name for term in OVERSEAS_INSTITUTION_TERMS):
        return True

    padded_name = f" {normalized_name} "
    return any(f" {code} " in padded_name for code in OVERSEAS_SHORT_CODES)


def classify_training_institution(name, institution_type=""):
    if is_overseas_institution(name, institution_type):
        return "Overseas Institution"
    return "National Institution"


def applicant_type_for_institution(name, institution_type=""):
    return "overseas" if is_overseas_institution(name, institution_type) else "national"
