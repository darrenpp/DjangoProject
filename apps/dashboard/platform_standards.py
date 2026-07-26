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
        "name": "PNG National Department of Health",
        "url": "https://www.health.gov.pg/",
        "use": "Primary PNG health-sector source for NDoH mandate, National Health Plan, NHSS compliance, health standards, and health policy publications.",
    },
    {
        "name": "PNG NDoH policies, standards, M&E and health-sector documents",
        "url": "https://www.health.gov.pg/subindex.php?acts=1",
        "use": "Official publication page for National Health Plan, M&E framework, data management SOP, HRH policy, WASH, community health post, and other health-sector policy documents.",
    },
    {
        "name": "PNG National Health Plan 2021-2030",
        "url": "https://www.health.gov.pg/pdf/NHP_1A15.pdf",
        "use": "National policy directions, principles, KRAs, partnership model, quality-access commitments, and health-system strengthening priorities.",
    },
    {
        "name": "PNG NDoH National Corporate Plan 2022-2026",
        "url": "https://www.health.gov.pg/pdf/NDoHC_P2022-2026.pdf",
        "use": "NDoH organizational mandate for standards, quality assurance, regulatory compliance, PHA support, and health-sector leadership.",
    },
    {
        "name": "PNG NDoH Routine Health Information System Data Management SOP",
        "url": "https://www.health.gov.pg/pdf/SOPdm_2024.pdf",
        "use": "Data governance model for routine health information management, data quality, reporting, and accountability.",
    },
    {
        "name": "PNG Nursing Council Situational Analysis Report, 30 January 2026",
        "url": "",
        "use": "Internal reform source for legal defensibility, governance, SOPs, documentation control, audit trails, case management, and digital regulatory systems.",
    },
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


PNG_NDOH_STANDARD_ROWS = [
    {
        "standard_area": "NDoH stewardship and compliance mandate",
        "source": "National Department of Health mandate and Corporate Plan 2022-2026",
        "expectation": "Provide health-sector leadership, set quality health standards, support legislation and coordination, and ensure service delivery agencies comply with policies, plans, and the National Health Service Standards.",
        "platform_alignment": "Standards dashboards, role-based registrar workflows, audit trails, facility ownership groups, PHA/private/NGO reporting, and compliance evidence for regulatory decisions.",
    },
    {
        "standard_area": "National Health Plan 2021-2030 policy directions",
        "source": "NHP 2021-2030 Volume 1",
        "expectation": "Support people-centred, equitable, integrated, evidence-based, partnership-driven health services with stronger health systems and no one left behind.",
        "platform_alignment": "Workforce dashboards show stock, cadre, training pipeline, province, facility, applicant origin, current practice status, and quality flags for evidence-based planning.",
    },
    {
        "standard_area": "National Health Service Standards and accreditation",
        "source": "NHSS / NHP 2021-2030 service quality and accreditation references",
        "expectation": "Maintain minimum service expectations for staffing, facility function, equipment, scope of practice, service quality, and continuous accreditation improvement.",
        "platform_alignment": "Facility and practitioner records distinguish official facility masters from raw workplace strings and show staffing distribution across PHA, private, NGO, church, and review-needed facilities.",
    },
    {
        "standard_area": "Monitoring, evaluation, reporting, and data management",
        "source": "NHP M&E Framework, M&E Strategic Plan, data dictionary, and Routine HIS Data Management SOP",
        "expectation": "Use standard data definitions, maintain source provenance, improve data quality, monitor performance, and produce reliable periodic reports.",
        "platform_alignment": "Imports retain source workbook, sheet, row, year, dates, record type, data-quality flags, duplicate review, and recent-date statistics before dashboard totals are trusted.",
    },
    {
        "standard_area": "Health workforce and HRH policy alignment",
        "source": "Health Sector Human Resource Policy and NHP workforce priorities",
        "expectation": "Track workforce categories, training, deployment, professional registration, facility posting, capacity building, and workforce gaps.",
        "platform_alignment": "The registry separates nurses, midwives, nurse aides, doctors, CHWs, graduands, specialists, overseas workers, national workers, employment details, and facilities.",
    },
    {
        "standard_area": "PHA, private, NGO, church, and partner coordination",
        "source": "NHP partnership and NDoH stakeholder model",
        "expectation": "Coordinate PHAs, DDAs, churches, NGOs, private providers, education institutions, professional bodies, and development partners under a single national health-sector plan.",
        "platform_alignment": "Dashboards group workers and facilities by PHA, private, NGO/church, province, institution, facility, current/past activity, and national/overseas origin.",
    },
    {
        "standard_area": "Public health, WASH, community health post, and facility environment standards",
        "source": "NDoH WASH in healthcare facilities and Community Health Post policy references",
        "expectation": "Recognise facility-level standards that affect safe service delivery, community access, infection prevention, and workforce placement needs.",
        "platform_alignment": "Facility master data and workforce-flow reporting provide the staffing and location layer needed to connect regulatory workforce data with service-standard reviews.",
    },
    {
        "standard_area": "Medicines, clinical support, and regulated health practice",
        "source": "Medicines and Cosmetics Act, National Medicines Policy, and pharmaceutical services standards references",
        "expectation": "Maintain regulatory oversight for safe, effective, quality health products and licensed clinical support services where workforce regulation intersects with service delivery.",
        "platform_alignment": "Medical Board and future specialist-role modules can use the same practitioner, facility, licence, source-provenance, and audit pattern.",
    },
    {
        "standard_area": "Digital health, data security, and interoperability",
        "source": "NDoH data and interoperability focus, Routine HIS SOP, NHWA, DHIS2/HMIS, and FHIR concepts",
        "expectation": "Use secure digital records, standard reporting definitions, controlled access, reliable audit trails, and future exchange-ready data structures.",
        "platform_alignment": "The system applies role-based access, searchable registries, import histories, audit events, document audit, FHIR-style practitioner-role concepts, and DHIS2/HMIS-ready aggregate outputs.",
    },
]


PNGNC_SITUATIONAL_ANALYSIS_ROWS = [
    {
        "domain": "Legal and governance",
        "finding": "The current framework relies on the Medical Act and needs a dedicated PNG Nursing Act for modern nursing and midwifery regulation.",
        "platform_action": "Keep legal authority, decision status, committee pathways, and board/registrar actions explicit in every regulatory workflow.",
    },
    {
        "domain": "Policies and SOPs",
        "finding": "Policies and SOPs are limited or inconsistent, which weakens defensibility and standard practice.",
        "platform_action": "Expose standard workflows for registration, licensing, complaints, discipline, accreditation, inspection, and document control.",
    },
    {
        "domain": "Documentation control",
        "finding": "Weak version control and uncontrolled document editing create regulatory and legal risk.",
        "platform_action": "Use repository metadata, approval or rejection sign-off, current-version history, staff ownership, access rules, and audit events for official regulatory documents.",
    },
    {
        "domain": "Complaints, discipline, and case management",
        "finding": "Complaints and disciplinary handling must move from ad-hoc handling to a formal case-management pathway.",
        "platform_action": "Use the ICMS case module to maintain case intake, assigned officer, status, evidence, decision notes, due-process checkpoints, and final outcomes.",
    },
    {
        "domain": "Audit trails and legal defensibility",
        "finding": "Weak audit trails and informal decisions are major risks if Council decisions are challenged.",
        "platform_action": "Record source, user, time, action, field changes, approval status, formal decision rationale, authority, appeal rights, and supporting evidence for each major decision.",
    },
    {
        "domain": "Digital regulatory systems",
        "finding": "Manual and fragmented systems should be replaced with digital registration, licensing, and case tracking.",
        "platform_action": "Prioritise fast, paginated data tables, clean imports, validated forms, dashboards by year/date, and record-quality review before official reporting.",
    },
    {
        "domain": "Capacity building",
        "finding": "Staff need training in regulatory practice, documentation, decision writing, investigations, and disciplinary processes.",
        "platform_action": "Use guided workflow labels, dashboard explanations, required fields, and standard reports to support consistent registrar practice.",
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
    cache_key = "platform-standards-context:v2"
    cached = cache.get(cache_key)
    if cached:
        return cached
    context = {
        "standard_summary": PLATFORM_STANDARDS_SUMMARY,
        "standard_badges": PLATFORM_STANDARD_BADGES,
        "standard_sources": PLATFORM_STANDARD_SOURCES,
        "nhwa_alignment_rows": NHWA_ALIGNMENT_ROWS,
        "png_ndoh_standard_rows": PNG_NDOH_STANDARD_ROWS,
        "pngnc_situational_analysis_rows": PNGNC_SITUATIONAL_ANALYSIS_ROWS,
        "data_standard_rows": DATA_STANDARD_ROWS,
        "interoperability_rows": INTEROPERABILITY_ROWS,
        "live_standard_metrics": _live_standard_metrics(),
    }
    cache.set(cache_key, context, 300)
    return context
