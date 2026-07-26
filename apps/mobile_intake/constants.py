API_VERSION = "v1"

OFFICE_SCOPE_GENERAL = "general"
OFFICE_SCOPE_NURSING = "nursing"
OFFICE_SCOPE_MEDICAL = "medical"
OFFICE_SCOPES = {OFFICE_SCOPE_GENERAL, OFFICE_SCOPE_NURSING, OFFICE_SCOPE_MEDICAL}

STATUS_RECEIVED = "RECEIVED"
STATUS_VALIDATING = "VALIDATING"
STATUS_DUPLICATE_RISK = "DUPLICATE_RISK"
STATUS_NEEDS_REVIEW = "NEEDS_REVIEW"
STATUS_NEEDS_CORRECTION = "NEEDS_CORRECTION"
STATUS_REJECTED = "REJECTED"
STATUS_ACCEPTED = "ACCEPTED"
STATUS_PROMOTED = "PROMOTED"
STATUS_FAILED = "FAILED"
STATUS_SUPERSEDED = "SUPERSEDED"

SUBMISSION_STATUSES = (
    STATUS_RECEIVED,
    STATUS_VALIDATING,
    STATUS_DUPLICATE_RISK,
    STATUS_NEEDS_REVIEW,
    STATUS_NEEDS_CORRECTION,
    STATUS_REJECTED,
    STATUS_ACCEPTED,
    STATUS_PROMOTED,
    STATUS_FAILED,
    STATUS_SUPERSEDED,
)

ALLOWED_ATTACHMENT_TYPES = {"image/jpeg", "image/png", "application/pdf"}
MAX_ATTACHMENT_MB = 20
MAX_ATTACHMENT_BYTES = MAX_ATTACHMENT_MB * 1024 * 1024

NURSING_FORM_CODES = ("NC1", "NC2", "NC3", "NC6", "NC7", "G1", "G2", "G3", "G4", "G5", "G6", "G7")
MEDICAL_FORM_CODES = ("MD1", "MD2", "CHW1", "CHWP", "CHWF", "MBSP", "MBRN", "MBAC", "MBPF", "MBTC")

DEFAULT_SCHEMA_VERSION = "2026.05.19"

FORM_DEFAULTS = {
    "NC1": ("Application for Provisional Licence", OFFICE_SCOPE_NURSING),
    "NC2": ("Application for Full Licence", OFFICE_SCOPE_NURSING),
    "NC3": ("Renewal of Licence", OFFICE_SCOPE_NURSING),
    "NC6": ("Competency for Full Licence Nursing", OFFICE_SCOPE_NURSING),
    "NC7": ("Competency for Full Licence Midwifery", OFFICE_SCOPE_NURSING),
    "G1": ("Graduate Nurses Checklist", OFFICE_SCOPE_NURSING),
    "G2": ("List of New Graduate Nurses", OFFICE_SCOPE_NURSING),
    "G3": ("Graduate Vitae", OFFICE_SCOPE_NURSING),
    "G4": ("Statement of Competency - Nurses", OFFICE_SCOPE_NURSING),
    "G5": ("Statement of Competency - Midwives", OFFICE_SCOPE_NURSING),
    "G6": ("Graduate Midwives Checklist", OFFICE_SCOPE_NURSING),
    "G7": ("List of Graduate Midwives", OFFICE_SCOPE_NURSING),
    "MD1": ("Medical Registration", OFFICE_SCOPE_MEDICAL),
    "MD2": ("Medical Renewal", OFFICE_SCOPE_MEDICAL),
    "CHW1": ("Community Health Worker Registration", OFFICE_SCOPE_MEDICAL),
    "CHWP": ("CHW Provisional Licence", OFFICE_SCOPE_MEDICAL),
    "CHWF": ("CHW Full Licence", OFFICE_SCOPE_MEDICAL),
    "MBSP": ("Medical Board Specialist Application", OFFICE_SCOPE_MEDICAL),
    "MBRN": ("Medical Board Renewal Registration", OFFICE_SCOPE_MEDICAL),
    "MBAC": ("Facility Accreditation Checklist", OFFICE_SCOPE_MEDICAL),
    "MBPF": ("Private Health Facility Checklist", OFFICE_SCOPE_MEDICAL),
    "MBTC": ("Training College Facility Form", OFFICE_SCOPE_MEDICAL),
}

DEFAULT_REQUIRED_FIELDS = (
    "first_name",
    "surname",
    "gender",
    "date_of_birth",
    "province",
)

EMPLOYMENT_STATUSES = ("employed", "unemployed", "inactive", "retired", "deceased", "overseas", "unknown")
EMPLOYMENT_SECTORS = ("public", "church", "private", "ngo", "overseas", "unknown")
