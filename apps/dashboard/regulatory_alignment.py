from collections import Counter, defaultdict
from datetime import date

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db.models import Count, Q
from django.utils import timezone

from apps.documents.models import Document, DocumentAuditEvent
from apps.notifications.models import EnquiryThread
from apps.workforce.models import (
    Application,
    DataImportBatch,
    EmploymentRecord,
    HealthStudent,
    Midwife,
    NurseAide,
    NursingProfessional,
    PracticingLicenseRecord,
    Qualification,
)


STATUTORY_CONTEXT = {
    "title": "Statutory Context and Mandate of the PNG Nursing Council",
    "summary": (
        "This wording is aligned to the January 2026 ministerial submission and situational analysis. "
        "It reflects the Council's regulatory mandate under the current medical registration framework referenced in those reports."
    ),
    "mandate_points": [
        "Accreditation and monitoring of nursing and midwifery education programmes.",
        "Registration and licensure of nurses and midwives.",
        "Maintenance of professional registers and regulatory histories.",
        "Recognition of qualifications and approved specialisations.",
        "Setting and enforcing professional standards to protect public safety.",
    ],
    "out_of_scope_points": [
        "Employment and payroll records.",
        "Deployment or posting of nurses and midwives.",
        "Workforce vacancy management.",
        "Employment status categories such as STC, permanent, acting, or unattached positions.",
    ],
    "alignment_note": (
        "The two source reports use slightly different historical/legal wording for the Council's establishment history. "
        "For system alignment, this platform now uses a single operational statement focused on the current regulatory mandate. "
        "Any final legal wording for gazettal, legislation, or ministerial correspondence should still be confirmed by the Council's legal and policy leadership."
    ),
}


MINISTERIAL_TABLE_1 = {
    "title": "Table 1: Nursing Training Institution Graduates Output Summary",
    "description": (
        "Reference data from the ministerial submission showing graduate output from nursing training institutions. "
        "These are training outputs and do not automatically equal workforce absorption."
    ),
    "headers": ["Institution", "2017", "2018", "2019", "2020", "2021", "2022", "2023", "2024", "Total"],
    "rows": [
        ["Lae College of Nursing", 48, 37, 47, 62, 46, 62, 50, 46, 398],
        ["Highlands Regional College of Nursing", 50, 49, 56, 66, 77, 73, 70, 81, 522],
        ["St Mary's DWU SON Rabaul Campus", 32, 36, 36, 40, 39, 33, 33, 35, 284],
        ["Lutheran School of Nursing", 40, 40, 45, 43, 50, 53, 52, 53, 376],
        ["St Barnabas School of Nursing", 25, 42, 55, 120, "No Gradn", 49, 46, 32, 369],
        ["Nazarene College of Nursing", 45, 34, 32, 53, 34, 38, 40, 37, 313],
        ["Mendi School of Nursing", 80, 56, "No Gradn", 152, "No Gradn", 36, "No Grad.", "Pending", 324],
        ["Enga College of Nursing", 12, 32, 21, 23, 21, 12, 13, "Pending", 134],
        ["Pacific Adventist University", 43, 41, 45, 5, 43, 49, 63, 52, 341],
        ["Bougainville College of Nursing", "", 22, 21, 25, 15, 12, 24, 25, 144],
        ["WNB School of Nursing", "", "", 17, 30, 25, 30, 27, 32, 161],
        ["APIASETTS School of Nursing - NCD", "", "", "", 10, 4, 8, 8, 10, 40],
        ["Kundiawa School of Nursing", "", "", "", 27, 43, 100, 132, 101, 403],
        ["Lemakot (Scared Heart SON)", "", "", "", "", 12, 16, 17, 16, 61],
        ["East Sepik School of Nursing", "", "", "", "", 18, 27, 27, 40, 112],
        ["St Benedict School of Nursing", "", "", "", "", 30, 25, 30, 39, 124],
        ["Tuna Bay School of Nursing", "", "", "", "", "", "", 36, 50, 86],
        ["Computer Health Science School of Nursing-NCD", "", "", "", "", "", "", 17, "Not yet Rec.doc", 17],
        ["TOTAL", 397, 388, 379, 646, 454, 635, 686, 624, 4209],
    ],
    "source_note": (
        "Some late-year institution cells in the source PDF include blanks, pending values, or non-numeric notes. "
        "Those have been carried into the platform as reference text rather than forced into a numeric value."
    ),
}


MINISTERIAL_TABLE_2 = {
    "title": "Table 2: Bachelor Midwifery Program Graduates Output Summary",
    "description": (
        "Reference data from the ministerial submission showing annual output from midwifery programmes. "
        "These are graduate outputs and do not automatically equal employment placement."
    ),
    "headers": ["Institution", "2016", "2017", "2018", "2019", "2020", "2021", "2022", "2023", "2024", "Total"],
    "rows": [
        ["UPNG School of Nursing", 2, 15, 24, 17, 10, 24, 6, 9, 13, 120],
        ["University of Goroka", "", 11, 11, 14, 7, 14, 22, 11, 12, 102],
        ["Lae School of Nursing", 21, 10, 10, 15, 17, 18, 15, 12, 17, 135],
        ["DWU St Mary's SoN", 16, "", 17, 4, 12, 14, 12, 21, "Pending", 96],
        ["Pacific Adventist University (PAU)", 16, 12, 4, 14, 13, 11, 13, 14, 22, 119],
        ["TOTAL", 66, 48, 69, 57, 66, 89, 57, 68, 52, 572],
    ],
    "source_note": "The source PDF shows one pending 2024 value and one leading blank institution-year cell.",
}


MINISTERIAL_TABLE_2_1 = {
    "title": "Table 2.1: Bachelor Midwifery Full License Issuance Summary",
    "description": "Reference data from the ministerial submission showing midwifery full licence issuance.",
    "headers": ["Year", "Report Value"],
    "rows": [
        [2021, 54],
        [2022, 59],
        [2023, 101],
        [2024, 114],
        [2025, "Not stated in source PDF text"],
    ],
    "source_note": (
        "The extracted PDF text shows four numeric values and a 2025 column heading. "
        "The platform preserves that wording rather than guessing a missing 2025 count."
    ),
}


MINISTERIAL_TABLE_3 = {
    "title": "Table 3: Registration Elements Summary",
    "description": (
        "Reference totals from the ministerial submission covering provisional registration, full registration, "
        "temporary overseas registration, and Authority to Practise (ATP) activity."
    ),
    "headers": ["Registration Element", "Report Total", "Source Note"],
    "rows": [
        ["PNG Provisional", 3118, "Year cells in the PDF include blanks/merged spacing."],
        ["PNG Full License", 3571, "Year cells in the PDF include blanks/merged spacing."],
        ["Overseas Provisional", 217, "Year cells in the PDF include blanks/merged spacing."],
        ["Overseas Full License", 109, "Year cells in the PDF include blanks/merged spacing."],
        ["Overseas Temporary", 426, "Year cells in the PDF include blanks/merged spacing."],
        ["Authority to Practice", 14987, "The source PDF includes a 'Missing' note in the year cells; total retained as reference."],
        ["TOTAL", 22428, "Reference total from the source PDF."],
    ],
    "source_note": (
        "Because the PDF text extraction merged some year cells, the platform uses source totals as the authoritative comparison point for this table."
    ),
}


MINISTERIAL_TABLE_6 = {
    "title": "Table 6: Employment Type",
    "description": "Reference employment engagement summary from the ministerial submission.",
    "headers": ["Employment Type", "Report Value"],
    "rows": [
        ["Unemployed Nurse", 189],
        ["Studying/Residing Offshore", 10],
        ["Clinical Nurse / Nurse Administrator / Nurse Educator", "Not fully disaggregated in source table"],
        ["Total", 199],
    ],
    "source_note": "The source report notes that employment subcategories were not yet fully disaggregated.",
}


MINISTERIAL_TABLE_7 = {
    "title": "Table 7: Scheme of General Nurse (2022 to 2023)",
    "description": (
        "Reference scheme of qualification summary from the ministerial submission. "
        "The source PDF lists the category labels but only provides the total figure."
    ),
    "headers": ["Qualification Scheme", "Report Value"],
    "rows": [
        ["General Certificate in Nursing", "Not itemised in source PDF"],
        ["Diploma Certificate in Nursing", "Not itemised in source PDF"],
        ["Bachelor Certificate in Nursing", "Not itemised in source PDF"],
        ["Total", 2959],
    ],
    "source_note": "Only the total was stated in the extracted source PDF text.",
}


MINISTERIAL_TABLE_8 = {
    "title": "Table 8: Segregation by Specialisation",
    "description": (
        "Reference specialisation summary from the ministerial submission. "
        "It distinguishes general nurses, midwives, nurse aides, and specialist categories over three reporting windows."
    ),
    "headers": ["Cadre / Specialisation", "2020-2021", "2022-2023", "2024-2025"],
    "rows": [
        ["General Nurses", 100, 2959, 3504],
        ["Enrolled Nurse", 19, 30, 11],
        ["Nurse Aides", 28, 513, 588],
        ["Midwives", 328, 746, 926],
        ["Maternal & Child Health Nurse", 11, 36, 61],
        ["Paediatric / Child Health Nurse", 27, 8, 216],
        ["Acute Care Nurses", 14, 81, 368],
        ["Mental Health Nurses", "", 28, 81],
        ["Eye Care Nursing", "", 10, 37],
        ["Nursing Management & Leadership", "", "", ""],
        ["Community Health Nurses", "", "", ""],
        ["Unidentified Specialty Nurse", 413, 6, ""],
    ],
    "source_note": (
        "The source PDF table contains blank and partially merged cells. "
        "The platform preserves the extracted values and compares only the categories that can be mapped safely."
    ),
}


SITUATIONAL_SWOT = {
    "strengths": [
        "Clear national mandate to regulate nurses and midwives.",
        "Committed leadership and Board oversight.",
        "Increasing policy and standards development.",
        "Strong stakeholder engagement and regulatory expertise.",
    ],
    "weaknesses": [
        "Outdated legislative framework.",
        "Weak or inconsistent SOP coverage.",
        "Poor documentation control and version management.",
        "Manual systems and weak audit trails.",
        "Inconsistent complaints handling and limited formal case management.",
    ],
    "opportunities": [
        "Digital systems to modernise regulation.",
        "PNG Nursing Act reform opportunity.",
        "Health sector reform momentum and international benchmarks.",
        "Technical partner support and workforce growth.",
    ],
    "threats": [
        "Legal challenges to Council decisions.",
        "Court scrutiny of due process and fairness.",
        "Political pressure and reputational damage.",
        "Loss of public trust if complaints or standards are handled inconsistently.",
    ],
}


GAP_ANALYSIS_ROWS = [
    ["Legal Framework", "Medical Act / Medical Registration framework", "PNG Nursing Act", "External / policy-led", "A software platform cannot replace the need for a dedicated Act."],
    ["Policies", "Limited", "Full regulatory policies", "Partial", "The platform can store and control documents, but policy content still needs formal approval."],
    ["SOPs", "Inconsistent", "Standard SOPs", "Partial", "The system can host versioned SOPs; drafting and enforcement remain operational tasks."],
    ["Complaints", "Ad-hoc", "Formal ICMS", "Partial", "Enquiries and staff inbox workflows exist, but a full incident and complaints case module is still needed."],
    ["Discipline", "Variable", "Standard pathway", "Pending", "No dedicated disciplinary case workflow has been implemented yet."],
    ["Documentation", "Weak control", "Versioned and approved", "Improving", "The document repository now supports versioning, access policy, and audit events."],
    ["Records", "Manual", "Digital systems", "Improving", "The registry, OCR imports, role-based dashboards, and repository search have digitised core records."],
    ["Audit Trail", "Weak", "Strong tracking", "Partial", "Document audit events exist; broader end-to-end regulatory audit coverage is still incomplete."],
    ["Governance", "Partial", "Strengthened frameworks", "Operational", "Board governance and ethics frameworks sit outside the software build and need governance action."],
]


RISK_ALIGNMENT_ROWS = [
    ["Regulatory decisions not defensible in court", "Very High", "High", "Partial", "Role-scoped workflows and document trails help, but full SOP-backed legal defensibility still needs policy and case-management work."],
    ["Weak documentation control", "High", "High", "Improving", "Document repository, versioning, and audit events address part of this risk."],
    ["Inconsistent complaints handling", "High", "High", "Partial", "Inbox and enquiry tools exist, but a formal ICMS workflow is still required."],
    ["Manual systems", "Medium", "High", "Improving", "Digital registration, search, OCR, repository, and analytics reduce manual handling."],
    ["Outdated legislation", "Very High", "Medium", "External", "This remains a legislative reform issue rather than an application defect."],
    ["Staff capacity gaps", "Medium", "Medium", "Operational", "Training, SOP adoption, and change-management are still required."],
    ["Unauthorised editing of documents", "High", "Medium", "Partial", "Repository permissions and version history help, but formal document-control policy is still needed."],
    ["Reputational damage", "High", "Medium", "Partial", "Privacy separation, live reporting, and better traceability reduce risk but do not remove it entirely."],
]


ROADMAP_ROWS = [
    ["Phase 1: Institutional Strengthening", "Foundation governance, documentation management, and SOP control.", "Partially supported", "The platform can now host controlled documents, version history, and registrar-facing intelligence."],
    ["Phase 2: Systems Modernisation and Regulatory Oversight", "Digital registration, oversight, and data systems.", "Supported / in progress", "The registry, dashboards, search, OCR intake, and repository modules support this phase."],
    ["Phase 3: Legislative Reform and Regulatory Maturity", "PNG Nursing Act and statutory autonomy.", "External / pending", "Legislative reform must be handled through policy and government processes, not software alone."],
]

REGULATORY_ALIGNMENT_CACHE_TIMEOUT = 300


def _format_datetime(value):
    if not value:
        return ""
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.strftime("%d %b %Y %H:%M")


def _person_key(row):
    return row.get("registration_no") or row.get("practitioner_number") or row.get("full_name")


def _latest_nursing_batch():
    return (
        DataImportBatch.objects.filter(
            source_kind__in=["ndata_workbook", "nursing_full_registration_2026"],
            status="completed",
        )
        .order_by("-completed_at", "-started_at")
        .first()
    )


def _safe_ratio(report_value, live_value):
    if not isinstance(report_value, (int, float)) or not isinstance(live_value, (int, float)):
        return None
    if report_value == 0:
        return 0 if live_value == 0 else None
    return abs(live_value - report_value) / report_value


def _alignment_status(report_value, live_value):
    if isinstance(report_value, str) or report_value in (None, ""):
        return "Reference only"
    if live_value is None:
        return "Not captured"
    if report_value == live_value:
        return "Match"
    ratio = _safe_ratio(report_value, live_value)
    if ratio is None:
        return "Needs review"
    if ratio <= 0.10:
        return "Close alignment"
    if ratio <= 0.25:
        return "Partial alignment"
    return "Mismatch"


def _variance_text(report_value, live_value):
    if not isinstance(report_value, (int, float)) or not isinstance(live_value, (int, float)):
        return "Reference comparison only"
    delta = live_value - report_value
    if report_value == 0:
        return f"{delta:+,}"
    percent = (delta / report_value) * 100
    return f"{delta:+,} ({percent:+.1f}%)"


def _year_count_map(queryset, year_field):
    counts = defaultdict(int)
    for row in queryset.values(year_field).annotate(total=Count("id")).order_by(year_field):
        counts[row[year_field]] = row["total"]
    return counts


def _distinct_year_counts(queryset, start_year, end_year):
    counts = {year: 0 for year in range(start_year, end_year + 1)}
    grouped = defaultdict(set)
    for row in queryset.values("record_year", "registration_no", "practitioner_number", "full_name").iterator():
        if not row["record_year"]:
            continue
        key = _person_key(row)
        if key:
            grouped[row["record_year"]].add(key)
    for year in range(start_year, end_year + 1):
        counts[year] = len(grouped.get(year, set()))
    return counts


def _latest_table_8_value(row):
    for value in reversed(row[1:]):
        if value not in ("", None):
            return value
    return None


def _qualification_scheme_counts_2022_2023():
    queryset = Qualification.objects.filter(
        completion_year__gte=2022,
        completion_year__lte=2023,
    ).filter(
        Q(qualification_name__icontains="nursing") | Q(program_completed__icontains="nursing")
    ).exclude(
        Q(qualification_name__icontains="midwif") | Q(program_completed__icontains="midwif")
    )

    counts = Counter()
    for qualification_name in queryset.values_list("qualification_name", flat=True):
        text = (qualification_name or "").lower()
        if "cert" in text and "nursing" in text:
            counts["General Certificate in Nursing"] += 1
        elif "diplom" in text:
            counts["Diploma Certificate in Nursing"] += 1
        elif "bachelor" in text:
            counts["Bachelor Certificate in Nursing"] += 1
        else:
            counts["Unclassified"] += 1
    return counts


def _specialisation_counts():
    counts = Counter()
    for qualification_level in NursingProfessional.objects.values_list("qualification_level", flat=True):
        text = (qualification_level or "").strip().lower()
        if not text:
            counts["Unspecified"] += 1
        elif "acute care" in text or "emergency" in text or "intensive care" in text or "perioperative" in text:
            counts["Acute Care Nurses"] += 1
        elif "mental" in text:
            counts["Mental Health Nurses"] += 1
        elif "eye care" in text or "ophthalm" in text:
            counts["Eye Care Nursing"] += 1
        elif "maternal" in text or "child health" in text:
            counts["Maternal & Child Health Nurse"] += 1
        elif "paediatric" in text or "pediatric" in text:
            counts["Paediatric / Child Health Nurse"] += 1
        elif "leadership" in text or "management" in text:
            counts["Nursing Management & Leadership"] += 1
        elif "community health" in text:
            counts["Community Health Nurses"] += 1
        elif "enrolled" in text:
            counts["Enrolled Nurse"] += 1
        elif "specialist" in text:
            counts["Unidentified Specialty Nurse"] += 1
        else:
            counts["General Nurses"] += 1

    counts["Midwives"] = Midwife.objects.count()
    counts["Nurse Aides"] = NurseAide.objects.count()
    return counts


def _table_1_comparison():
    student_ct = ContentType.objects.get_for_model(HealthStudent)
    live_years = _year_count_map(
        Qualification.objects.filter(
            content_type=student_ct,
            completion_year__gte=2017,
            completion_year__lte=2024,
        ).filter(
            Q(qualification_name__icontains="nursing") | Q(program_completed__icontains="nursing")
        ).exclude(
            Q(qualification_name__icontains="midwif")
            | Q(program_completed__icontains="midwif")
            | Q(institution_name__icontains="overseas")
        ),
        "completion_year",
    )
    report_totals = dict(zip(range(2017, 2025), [397, 388, 379, 646, 454, 635, 686, 624]))
    rows = []
    for year in range(2017, 2025):
        live_value = live_years.get(year, 0)
        report_value = report_totals[year]
        rows.append([
            year,
            report_value,
            live_value,
            _variance_text(report_value, live_value),
            _alignment_status(report_value, live_value),
        ])
    total_report = 4209
    total_live = sum(live_years.get(year, 0) for year in range(2017, 2025))
    rows.append([
        "Total",
        total_report,
        total_live,
        _variance_text(total_report, total_live),
        _alignment_status(total_report, total_live),
    ])
    return rows, total_report, total_live


def _table_2_comparison():
    live_years = _year_count_map(
        Qualification.objects.filter(
            completion_year__gte=2016,
            completion_year__lte=2024,
        ).filter(
            Q(qualification_name__icontains="midwif") | Q(program_completed__icontains="midwif")
        ).exclude(
            Q(institution_name__icontains="overseas")
        ),
        "completion_year",
    )
    report_totals = dict(zip(range(2016, 2025), [66, 48, 69, 57, 66, 89, 57, 68, 52]))
    rows = []
    for year in range(2016, 2025):
        live_value = live_years.get(year, 0)
        report_value = report_totals[year]
        rows.append([
            year,
            report_value,
            live_value,
            _variance_text(report_value, live_value),
            _alignment_status(report_value, live_value),
        ])
    total_report = 572
    total_live = sum(live_years.get(year, 0) for year in range(2016, 2025))
    rows.append([
        "Total",
        total_report,
        total_live,
        _variance_text(total_report, total_live),
        _alignment_status(total_report, total_live),
    ])
    return rows, total_report, total_live


def _table_2_1_comparison():
    queryset = PracticingLicenseRecord.objects.filter(
        target_model="midwife",
        record_type="full",
        record_year__gte=2021,
        record_year__lte=2025,
    )
    live_distinct = _distinct_year_counts(queryset, 2021, 2025)
    live_raw = _year_count_map(queryset, "record_year")
    report_values = {
        2021: 54,
        2022: 59,
        2023: 101,
        2024: 114,
        2025: None,
    }
    rows = []
    for year in range(2021, 2026):
        report_value = report_values.get(year)
        live_value = live_distinct.get(year, 0)
        rows.append([
            year,
            report_value if report_value is not None else "Not stated",
            live_value,
            live_raw.get(year, 0),
            _variance_text(report_value, live_value) if isinstance(report_value, int) else "Reference comparison only",
            _alignment_status(report_value, live_value),
        ])
    total_report = 328
    total_live = sum(live_distinct.values())
    rows.append([
        "Total stated in source",
        total_report,
        total_live,
        sum(live_raw.values()),
        _variance_text(total_report, total_live),
        _alignment_status(total_report, total_live),
    ])
    return rows, total_report, total_live


def _table_3_comparison():
    table_rows = []
    config = [
        ("PNG Provisional", 3118, {"target_model": "healthstudent", "record_type": "provisional", "applicant_type": "national"}, "Distinct provisional practitioners in the import history."),
        ("PNG Full License", 3571, {"target_model": "nursingprofessional", "record_type": "full", "applicant_type": "national"}, "Distinct full-registration practitioners in the import history."),
        ("Overseas Provisional", 217, {"target_model": "healthstudent", "record_type": "provisional", "applicant_type": "overseas"}, "Distinct overseas provisional practitioners in the import history."),
        ("Overseas Full License", 109, {"target_model": "nursingprofessional", "record_type": "full", "applicant_type": "overseas"}, "Distinct overseas full-registration practitioners in the import history."),
        ("Overseas Temporary", 426, {"record_type": "temporary", "applicant_type": "overseas"}, "Imported temporary overseas records."),
        ("Authority to Practice", 14987, {"record_type": "practicing_license", "target_model__in": ["nursingprofessional", "midwife", "nurseaide"]}, "Practising licence records across nursing, midwifery, and nurse aide rows."),
    ]

    total_report = 22428
    total_live_distinct = 0
    total_live_raw = 0
    for label, report_value, filters, note in config:
        queryset = PracticingLicenseRecord.objects.filter(record_year__gte=2019, record_year__lte=2026, **filters)
        raw_count = queryset.count()
        distinct_sum = sum(_distinct_year_counts(queryset, 2019, 2026).values())
        total_live_distinct += distinct_sum
        total_live_raw += raw_count
        table_rows.append([
            label,
            report_value,
            raw_count,
            distinct_sum,
            _variance_text(report_value, distinct_sum),
            _alignment_status(report_value, distinct_sum),
            note,
        ])

    table_rows.append([
        "TOTAL",
        total_report,
        total_live_raw,
        total_live_distinct,
        _variance_text(total_report, total_live_distinct),
        _alignment_status(total_report, total_live_distinct),
        "Summed comparison using live distinct practitioner totals.",
    ])
    return table_rows, total_report, total_live_distinct


def _table_6_comparison():
    live_counts = Counter()
    for status in EmploymentRecord.objects.values_list("employment_status", flat=True):
        if status == "unemployed":
            live_counts["Unemployed Nurse"] += 1
        elif status == "studying":
            live_counts["Studying/Residing Offshore"] += 1
        else:
            live_counts["Other Captured Status"] += 1
    report_totals = {
        "Unemployed Nurse": 189,
        "Studying/Residing Offshore": 10,
        "Total": 199,
    }
    total_live = EmploymentRecord.objects.count()
    rows = [
        [
            "Unemployed Nurse",
            189,
            live_counts.get("Unemployed Nurse", 0),
            _variance_text(189, live_counts.get("Unemployed Nurse", 0)),
            _alignment_status(189, live_counts.get("Unemployed Nurse", 0)),
        ],
        [
            "Studying/Residing Offshore",
            10,
            live_counts.get("Studying/Residing Offshore", 0),
            _variance_text(10, live_counts.get("Studying/Residing Offshore", 0)),
            _alignment_status(10, live_counts.get("Studying/Residing Offshore", 0)),
        ],
        [
            "Total",
            report_totals["Total"],
            total_live,
            _variance_text(report_totals["Total"], total_live),
            _alignment_status(report_totals["Total"], total_live),
        ],
    ]
    return rows, report_totals["Total"], total_live


def _table_7_comparison():
    live_counts = _qualification_scheme_counts_2022_2023()
    total_live = (
        live_counts.get("General Certificate in Nursing", 0)
        + live_counts.get("Diploma Certificate in Nursing", 0)
        + live_counts.get("Bachelor Certificate in Nursing", 0)
    )
    rows = [
        [
            "General Certificate in Nursing",
            "Not itemised in source",
            live_counts.get("General Certificate in Nursing", 0),
            "Reference only",
            "Reference only",
        ],
        [
            "Diploma Certificate in Nursing",
            "Not itemised in source",
            live_counts.get("Diploma Certificate in Nursing", 0),
            "Reference only",
            "Reference only",
        ],
        [
            "Bachelor Certificate in Nursing",
            "Not itemised in source",
            live_counts.get("Bachelor Certificate in Nursing", 0),
            "Reference only",
            "Reference only",
        ],
        [
            "Total",
            2959,
            total_live,
            _variance_text(2959, total_live),
            _alignment_status(2959, total_live),
        ],
    ]
    return rows, 2959, total_live


def _table_8_comparison():
    live_counts = _specialisation_counts()
    rows = []
    comparable_rows = []
    for source_row in MINISTERIAL_TABLE_8["rows"]:
        label = source_row[0]
        report_value = _latest_table_8_value(source_row)
        live_value = live_counts.get(label, 0)
        rows.append([
            label,
            report_value if report_value not in ("", None) else "Source cell blank / not captured",
            live_value,
            _variance_text(report_value, live_value) if isinstance(report_value, int) else "Reference comparison only",
            _alignment_status(report_value, live_value),
        ])
        if isinstance(report_value, int):
            comparable_rows.append((report_value, live_value))
    report_total = sum(report for report, _ in comparable_rows)
    live_total = sum(live for _, live in comparable_rows)
    rows.append([
        "Comparable total",
        report_total,
        live_total,
        _variance_text(report_total, live_total),
        _alignment_status(report_total, live_total),
    ])
    return rows, report_total, live_total


def _comparison_summary(reference_tables):
    rows = []
    for table in reference_tables:
        rows.append([
            table["title"],
            table["report_total"],
            table["live_total"],
            _variance_text(table["report_total"], table["live_total"]),
            _alignment_status(table["report_total"], table["live_total"]),
            table["comparison_note"],
        ])
    return rows


def _live_snapshot():
    return [
        ["Registered Nurses", NursingProfessional.objects.count(), NursingProfessional.objects.filter(is_active=True).count()],
        ["Midwives", Midwife.objects.count(), Midwife.objects.filter(is_active=True).count()],
        ["Nurse Aides", NurseAide.objects.count(), NurseAide.objects.filter(is_active=True).count()],
        ["Graduands", HealthStudent.objects.count(), HealthStudent.objects.filter(is_active=True).count()],
    ]


def _platform_alignment_snapshot():
    latest_batch = _latest_nursing_batch()
    latest_source_name = latest_batch.source_file_name if latest_batch else "Not captured"
    latest_completed = _format_datetime(latest_batch.completed_at) if latest_batch else "Not captured"
    return {
        "applications": Application.objects.filter(form_code__startswith="N").count() + Application.objects.filter(form_code__startswith="G").count(),
        "documents": Document.objects.filter(office_scope__in=["nursing", "general"]).count(),
        "document_audits": DocumentAuditEvent.objects.count(),
        "open_enquiries": EnquiryThread.objects.filter(office="nursing").count(),
        "latest_source_name": latest_source_name,
        "latest_completed": latest_completed,
    }


def build_nursing_regulatory_alignment_context():
    cache_key = "nursing-regulatory-alignment:full"
    cached = cache.get(cache_key)
    if cached:
        return cached

    table_1_rows, table_1_report_total, table_1_live_total = _table_1_comparison()
    table_2_rows, table_2_report_total, table_2_live_total = _table_2_comparison()
    table_2_1_rows, table_2_1_report_total, table_2_1_live_total = _table_2_1_comparison()
    table_3_rows, table_3_report_total, table_3_live_total = _table_3_comparison()
    table_6_rows, table_6_report_total, table_6_live_total = _table_6_comparison()
    table_7_rows, table_7_report_total, table_7_live_total = _table_7_comparison()
    table_8_rows, table_8_report_total, table_8_live_total = _table_8_comparison()

    reference_tables = [
        {
            "title": MINISTERIAL_TABLE_1["title"],
            "description": MINISTERIAL_TABLE_1["description"],
            "source_headers": MINISTERIAL_TABLE_1["headers"],
            "source_rows": MINISTERIAL_TABLE_1["rows"],
            "source_note": MINISTERIAL_TABLE_1["source_note"],
            "comparison_headers": ["Year", "Report Total", "Live Database Total", "Variance", "Alignment"],
            "comparison_rows": table_1_rows,
            "comparison_note": "Compared against live qualification records for nursing graduands (2017-2024).",
            "report_total": table_1_report_total,
            "live_total": table_1_live_total,
        },
        {
            "title": MINISTERIAL_TABLE_2["title"],
            "description": MINISTERIAL_TABLE_2["description"],
            "source_headers": MINISTERIAL_TABLE_2["headers"],
            "source_rows": MINISTERIAL_TABLE_2["rows"],
            "source_note": MINISTERIAL_TABLE_2["source_note"],
            "comparison_headers": ["Year", "Report Total", "Live Database Total", "Variance", "Alignment"],
            "comparison_rows": table_2_rows,
            "comparison_note": "Compared against live midwifery qualification records (2016-2024).",
            "report_total": table_2_report_total,
            "live_total": table_2_live_total,
        },
        {
            "title": MINISTERIAL_TABLE_2_1["title"],
            "description": MINISTERIAL_TABLE_2_1["description"],
            "source_headers": MINISTERIAL_TABLE_2_1["headers"],
            "source_rows": MINISTERIAL_TABLE_2_1["rows"],
            "source_note": MINISTERIAL_TABLE_2_1["source_note"],
            "comparison_headers": ["Year", "Report Value", "Live Distinct Practitioners", "Live Raw Rows", "Variance", "Alignment"],
            "comparison_rows": table_2_1_rows,
            "comparison_note": "Compared against live midwife full-registration rows in PracticingLicenseRecord (2021-2025).",
            "report_total": table_2_1_report_total,
            "live_total": table_2_1_live_total,
        },
        {
            "title": MINISTERIAL_TABLE_3["title"],
            "description": MINISTERIAL_TABLE_3["description"],
            "source_headers": MINISTERIAL_TABLE_3["headers"],
            "source_rows": MINISTERIAL_TABLE_3["rows"],
            "source_note": MINISTERIAL_TABLE_3["source_note"],
            "comparison_headers": ["Registration Element", "Report Total", "Live Raw Rows", "Live Distinct Practitioners", "Variance", "Alignment", "Live Comparison Basis"],
            "comparison_rows": table_3_rows,
            "comparison_note": "Compared against imported registration records from 2019-2026 using raw rows and distinct practitioner counts.",
            "report_total": table_3_report_total,
            "live_total": table_3_live_total,
        },
        {
            "title": MINISTERIAL_TABLE_6["title"],
            "description": MINISTERIAL_TABLE_6["description"],
            "source_headers": MINISTERIAL_TABLE_6["headers"],
            "source_rows": MINISTERIAL_TABLE_6["rows"],
            "source_note": MINISTERIAL_TABLE_6["source_note"],
            "comparison_headers": ["Employment Type", "Report Value", "Live Database Value", "Variance", "Alignment"],
            "comparison_rows": table_6_rows,
            "comparison_note": "Compared against EmploymentRecord rows. The live database currently has no captured employment records.",
            "report_total": table_6_report_total,
            "live_total": table_6_live_total,
        },
        {
            "title": MINISTERIAL_TABLE_7["title"],
            "description": MINISTERIAL_TABLE_7["description"],
            "source_headers": MINISTERIAL_TABLE_7["headers"],
            "source_rows": MINISTERIAL_TABLE_7["rows"],
            "source_note": MINISTERIAL_TABLE_7["source_note"],
            "comparison_headers": ["Qualification Scheme", "Report Value", "Live Database Value", "Variance", "Alignment"],
            "comparison_rows": table_7_rows,
            "comparison_note": "Compared against qualification rows completed in 2022-2023 and grouped into certificate, diploma, and bachelor pathways.",
            "report_total": table_7_report_total,
            "live_total": table_7_live_total,
        },
        {
            "title": MINISTERIAL_TABLE_8["title"],
            "description": MINISTERIAL_TABLE_8["description"],
            "source_headers": MINISTERIAL_TABLE_8["headers"],
            "source_rows": MINISTERIAL_TABLE_8["rows"],
            "source_note": MINISTERIAL_TABLE_8["source_note"],
            "comparison_headers": ["Cadre / Specialisation", "Latest Report Value", "Live Database Value", "Variance", "Alignment"],
            "comparison_rows": table_8_rows,
            "comparison_note": "Compared against current live qualification-level and register counts. Blank source cells were not forced into numeric comparisons.",
            "report_total": table_8_report_total,
            "live_total": table_8_live_total,
        },
    ]

    latest_batch = _latest_nursing_batch()
    latest_batch_row = None
    if latest_batch:
        latest_batch_row = {
            "source_file_name": latest_batch.source_file_name,
            "source_kind": latest_batch.source_kind,
            "completed_at": _format_datetime(latest_batch.completed_at),
            "processed_rows": latest_batch.processed_rows,
            "total_rows": latest_batch.total_rows,
            "summary": latest_batch.summary,
        }

    context = {
        "generated_on": date.today().strftime("%d %b %Y"),
        "statutory_context": STATUTORY_CONTEXT,
        "live_snapshot_rows": _live_snapshot(),
        "latest_batch_row": latest_batch_row,
        "platform_alignment": _platform_alignment_snapshot(),
        "comparison_summary_headers": ["Source Table", "Report Total", "Live Database Total", "Variance", "Alignment", "Note"],
        "comparison_summary_rows": _comparison_summary(reference_tables),
        "reference_tables": reference_tables,
        "swot": SITUATIONAL_SWOT,
        "gap_analysis_headers": ["Area", "Source Current State", "Required State", "Platform Status", "Alignment Note"],
        "gap_analysis_rows": GAP_ANALYSIS_ROWS,
        "risk_headers": ["Key Risk", "Impact", "Likelihood", "Platform Status", "Alignment Note"],
        "risk_rows": RISK_ALIGNMENT_ROWS,
        "roadmap_headers": ["Roadmap Phase", "Source Focus", "Platform Readiness", "Alignment Note"],
        "roadmap_rows": ROADMAP_ROWS,
    }
    cache.set(cache_key, context, REGULATORY_ALIGNMENT_CACHE_TIMEOUT)
    return context


def build_nursing_regulatory_alignment_summary_context():
    cache_key = "nursing-regulatory-alignment:summary"
    cached = cache.get(cache_key)
    if cached:
        return cached

    latest_batch = _latest_nursing_batch()
    live_snapshot_rows = _live_snapshot()
    summary = {
        "generated_on": date.today().strftime("%d %b %Y"),
        "statutory_context": STATUTORY_CONTEXT,
        "live_snapshot_rows": live_snapshot_rows,
        "latest_batch_row": {
            "source_file_name": latest_batch.source_file_name,
            "source_kind": latest_batch.source_kind,
            "completed_at": _format_datetime(latest_batch.completed_at),
            "processed_rows": latest_batch.processed_rows,
            "total_rows": latest_batch.total_rows,
        } if latest_batch else None,
        "platform_alignment": _platform_alignment_snapshot(),
        "live_registry_total": sum(row[1] for row in live_snapshot_rows),
    }
    cache.set(cache_key, summary, REGULATORY_ALIGNMENT_CACHE_TIMEOUT)
    return summary
