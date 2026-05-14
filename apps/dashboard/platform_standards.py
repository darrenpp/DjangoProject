from django.core.cache import cache
from django.utils import timezone

from apps.documents.models import DocumentAuditEvent
from apps.workforce.models import (
    Application,
    AuditLog,
    CommunityHealthWorker,
    DataImportBatch,
    Facility,
    HealthStudent,
    MedicalDoctor,
    Midwife,
    MissingDataReview,
    NurseAide,
    NursingProfessional,
    PracticingLicenseRecord,
    TrainingInstitution,
)


PLATFORM_STANDARD_BADGES = [
    {"label": "NHWA primary model", "icon": "fa-globe", "tone": "primary"},
    {"label": "ISCO workforce categories", "icon": "fa-id-badge", "tone": "success"},
    {"label": "FHIR-ready practitioner roles", "icon": "fa-plug", "tone": "info"},
    {"label": "DHIS2/HMIS integration path", "icon": "fa-diagram-project", "tone": "warning"},
    {"label": "Role-based audit control", "icon": "fa-shield-halved", "tone": "danger"},
]


PLATFORM_STANDARDS_SUMMARY = {
    "title": "Government Health Workforce Registry Standards",
    "subtitle": (
        "Operating model: WHO National Health Workforce Accounts, with DHIS2/HMIS and HL7 FHIR interoperability concepts."
    ),
    "policy_anchor": "PNG National Health Plan 2021-2030 and National Department of Health regulatory reporting.",
}


PLATFORM_STANDARD_SOURCES = [
    {
        "name": "WHO National Health Workforce Accounts handbook",
        "url": "https://www.who.int/publications/i/item/9789240081291",
        "use": "Primary model for workforce registry indicators, data quality, and policy reporting.",
    },
    {
        "name": "WHO NHWA implementation guide",
        "url": "https://www.who.int/europe/publications/i/item/9789241514446",
        "use": "Implementation reference for systematic HRH data gathering and use.",
    },
    {
        "name": "HL7 FHIR PractitionerRole",
        "url": "https://hl7.org/fhir/practitionerrole.html",
        "use": "Interoperability pattern for practitioner role, organization, location, specialty, and period.",
    },
    {
        "name": "DHIS2 HMIS platform",
        "url": "https://dhis2.org/about-2/",
        "use": "Secondary HMIS model for national health information integration and analytics.",
    },
]


NHWA_ALIGNMENT_ROWS = [
    {
        "domain": "Workforce stock",
        "standard": "Count active practitioners by cadre, licence, occupation, and registration status.",
        "platform": "Current dashboards separate nurses, midwives, nurse aides, doctors, CHWs, graduands, and imported licence records.",
        "priority": "Keep current totals based on quality-approved records only.",
    },
    {
        "domain": "Distribution",
        "standard": "Report practitioners by province, district, facility, ownership, and service setting.",
        "platform": "Facility master records and workplace references are separated so official facility counts are not inflated by raw address text.",
        "priority": "Continue cleansing workplace strings into verified facility master records.",
    },
    {
        "domain": "Education and pipeline",
        "standard": "Track training institutions, graduands, qualifications, and licensing inflows.",
        "platform": "Training institution, qualification, provisional, full, temporary, and ATP records are visible through registrar dashboards.",
        "priority": "Use national and overseas institution categories consistently in imports and forms.",
    },
    {
        "domain": "Inflows and outflows",
        "standard": "Measure new entrants, overseas entrants, temporary workers, renewals, exits, deaths, and inactive workers.",
        "platform": "Registration type, applicant origin, renewal, deceased notification, and workforce-flow screens provide the base.",
        "priority": "Extend outflow capture for resignations, retirement, migration, and inactive registration.",
    },
    {
        "domain": "Governance and quality",
        "standard": "Maintain source provenance, audit trail, role control, validation, and data-quality review.",
        "platform": "Role-based pages, duplicate review, missing-data review, import history, document audit, and staff access controls are implemented.",
        "priority": "Resolve flagged records before annual statistics and external reporting.",
    },
]


DATA_STANDARD_ROWS = [
    {
        "field": "Practitioner identity",
        "standard": "Unique registration or practitioner identifier with verified name, contact, and status.",
        "system_field": "registration_no, practitioner_number, full_name, email, status",
    },
    {
        "field": "Occupation and cadre",
        "standard": "ISCO-aligned occupation/cadre terminology for comparability.",
        "system_field": "category, professional_type, target_model, cadre",
    },
    {
        "field": "Practice role",
        "standard": "FHIR PractitionerRole style context: role, specialty, organization, location, active period.",
        "system_field": "employment records, posting history, facility, specialty, licence period",
    },
    {
        "field": "Facility or organization",
        "standard": "Verified organization and location master data, separate from free-text imports.",
        "system_field": "Facility, Location, workplace_address cleansing references",
    },
    {
        "field": "Source provenance",
        "standard": "Every imported statistic must retain workbook, sheet, row, year, and recent date where available.",
        "system_field": "DataImportBatch, source_sheet_name, source_row, record_year, payment_date, issued_date",
    },
]


INTEROPERABILITY_ROWS = [
    {
        "model": "NHWA",
        "role": "Primary workforce-registry model.",
        "implementation": "Dashboards group stock, education, distribution, inflows/outflows, migration/origin, and data-quality status.",
    },
    {
        "model": "DHIS2/HMIS",
        "role": "Aggregate health-management reporting model.",
        "implementation": "Exports and future APIs should aggregate approved workforce counts by facility, province, cadre, and period.",
    },
    {
        "model": "HL7 FHIR",
        "role": "Interoperability model for practitioner, role, organization, location, and provenance.",
        "implementation": "Use Practitioner, PractitionerRole, Organization, Location, and Provenance concepts when building integrations.",
    },
    {
        "model": "ISCO",
        "role": "Occupation terminology model for global comparability.",
        "implementation": "Map local nurse, midwife, nurse aide, CHW, doctor, and specialist labels into stable occupational categories.",
    },
]


def build_platform_standard_badges():
    return PLATFORM_STANDARD_BADGES


def _latest_import_row():
    latest = DataImportBatch.objects.order_by("-completed_at", "-started_at", "-id").first()
    if not latest:
        return {
            "label": "Latest import",
            "value": "No import history",
            "meta": "Source provenance pending",
        }
    completed = latest.completed_at or latest.started_at
    return {
        "label": "Latest import",
        "value": latest.source_file_name or "Imported source",
        "meta": timezone.localtime(completed).strftime("%d %b %Y %H:%M") if completed else latest.source_kind,
    }


def _live_standard_metrics():
    active_workforce_total = (
        NursingProfessional.objects.filter(is_active=True).count()
        + Midwife.objects.filter(is_active=True).count()
        + NurseAide.objects.filter(is_active=True).count()
        + MedicalDoctor.objects.filter(is_active=True).count()
        + CommunityHealthWorker.objects.filter(is_active=True).count()
    )
    return [
        {
            "label": "Active workforce stock",
            "value": active_workforce_total,
            "meta": "NHWA stock indicator base",
        },
        {
            "label": "Facility master records",
            "value": Facility.objects.count(),
            "meta": "Verified organization/location base",
        },
        {
            "label": "Education pipeline records",
            "value": TrainingInstitution.objects.count() + HealthStudent.objects.count(),
            "meta": "Training institutions plus graduands",
        },
        {
            "label": "Open quality reviews",
            "value": MissingDataReview.objects.exclude(status="resolved").count(),
            "meta": "Must be reviewed before official reporting",
        },
        {
            "label": "Registration import rows",
            "value": PracticingLicenseRecord.objects.count(),
            "meta": "Source-provenance enabled records",
        },
        {
            "label": "Audit trail events",
            "value": AuditLog.objects.count() + DocumentAuditEvent.objects.count(),
            "meta": "Operational and document audit evidence",
        },
        {
            "label": "Pending applications",
            "value": Application.objects.filter(status="pending").count(),
            "meta": "Current regulatory workload",
        },
        _latest_import_row(),
    ]


def build_platform_standards_context():
    cache_key = "platform-standards-context:v1"
    cached = cache.get(cache_key)
    if cached:
        return cached
    context = {
        "standard_summary": PLATFORM_STANDARDS_SUMMARY,
        "standard_badges": PLATFORM_STANDARD_BADGES,
        "standard_sources": PLATFORM_STANDARD_SOURCES,
        "nhwa_alignment_rows": NHWA_ALIGNMENT_ROWS,
        "data_standard_rows": DATA_STANDARD_ROWS,
        "interoperability_rows": INTEROPERABILITY_ROWS,
        "live_standard_metrics": _live_standard_metrics(),
    }
    cache.set(cache_key, context, 300)
    return context
