from collections import Counter, defaultdict

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.dashboard.nursing_analytics import active_nursing_analytics_snapshot
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
    ["Policies", "Limited", "Full regulatory policies", "Platform-ready / content pending", "The repository now supports controlled policy storage, versioning, access rules, approval or rejection sign-off, and audit history. Policy drafting and formal adoption remain governance actions."],
    ["SOPs", "Inconsistent", "Standard SOPs", "Platform-ready / content pending", "SOPs can now be stored as controlled records, versioned, approved, linked to cases or decisions, and audited. Staff still need approved SOP content and training."],
    ["Complaints", "Ad-hoc", "Formal ICMS", "Implemented / needs SOP adoption", "A formal ICMS case module now tracks public submissions, escalated enquiries, case assignment, status history, evidence, and closure summaries."],
    ["Discipline", "Variable", "Standard pathway", "Implemented / needs SOP adoption", "A dedicated disciplinary workflow now supports preliminary assessment, investigation, committee review, notice, hearing, decision, appeal monitoring, sanctions, and closure."],
    ["Documentation", "Weak control", "Versioned and approved", "Operational", "The repository supports versioning, access policy, approval or rejection sign-off, current-version tracking, and audit events."],
    ["Records", "Manual", "Digital systems", "Operational / improving", "The registry, OCR imports, mobile intake, analytics snapshots, role dashboards, repository search, and server-side drilldowns digitise core records while preserving legal source boundaries."],
    ["Audit Trail", "Weak", "Strong tracking", "Improving", "Document approvals, ICMS events, discipline events, formal decision records, import batches, receipt links, and security audit events now cover the major regulatory workflows."],
    ["Governance", "Partial", "Strengthened frameworks", "Platform-supported / governance-led", "The platform provides registers, approvals, role controls, forums, reports, and audit trails; Board governance and ethics decisions still require formal institutional action."],
]


RISK_ALIGNMENT_ROWS = [
    ["Regulatory decisions not defensible in court", "Very High", "High", "Improving", "Formal decision records now capture decision text, rationale, authority, evidence, conditions, appeal rights, decision maker, and effective dates; legal defensibility still depends on approved SOPs and lawful authority."],
    ["Weak documentation control", "High", "High", "Operational", "Document repository, versioning, approval or rejection sign-off, current-version tracking, permissions, and audit events now address the platform side of this risk."],
    ["Inconsistent complaints handling", "High", "High", "Implemented", "Inbox enquiries can be escalated into formal ICMS cases with status history, ownership, evidence, closure notes, and disciplinary escalation where required."],
    ["Manual systems", "Medium", "High", "Improving", "Digital registration, search, OCR, repository, and analytics reduce manual handling."],
    ["Outdated legislation", "Very High", "Medium", "External", "This remains a legislative reform issue rather than an application defect."],
    ["Staff capacity gaps", "Medium", "Medium", "Platform-supported / training required", "Guided workflows, standard queues, case registers, decision records, and controlled documents support staff practice; training and change management remain operational requirements."],
    ["Unauthorised editing of documents", "High", "Medium", "Improving", "Repository permissions, version history, approval sign-off, and audit events reduce unauthorised editing risk; final enforcement still depends on policy and staff roles."],
    ["Reputational damage", "High", "Medium", "Improving", "Privacy separation, scoped access, formal complaint handling, decision records, live reporting, and traceability reduce risk but do not remove governance or legal exposure."],
]


ROADMAP_ROWS = [
    ["Phase 1: Institutional Strengthening", "Foundation governance, documentation management, and SOP control.", "Supported / governance content pending", "The platform now hosts controlled documents, approvals, version history, case workflows, decision registers, and registrar-facing intelligence; formal policy content still needs institutional adoption."],
    ["Phase 2: Systems Modernisation and Regulatory Oversight", "Digital registration, oversight, and data systems.", "Supported / in progress", "The registry, dashboards, search, OCR intake, mobile intake, analytics snapshots, repository, ICMS, discipline workflow, and decision register support this phase."],
    ["Phase 3: Legislative Reform and Regulatory Maturity", "PNG Nursing Act and statutory autonomy.", "External / pending", "Legislative reform must be handled through policy and government processes, not software alone."],
]

NURSING_SOURCE_KINDS = {
    "ndata_workbook",
    "nursing_analytics_snapshot",
    "nursing_catherine_licence_breakdown",
    "nursing_full_registration_2026",
    "nursing_license_workbook",
    "nursing_live_workflow",
}

REGISTERED_NURSE_ATP_CADRES = {
    "registered nurse",
    "nursing",
    "enrolled nurse",
    "maternal & child health nurse",
    "mental health nurse",
    "paediatric nurse",
}

MIDWIFE_ATP_CADRES = {"midwife", "midwifery"}
NURSE_AIDE_ATP_CADRES = {"nurse aide", "nurse aides"}


def _format_datetime(value):
    if not value:
        return ""
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.strftime("%d %b %Y %H:%M")


def _safe_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _normalise_cadre(value):
    return " ".join(str(value or "").strip().lower().replace("/", " ").split())


def _snapshot_completed_at(snapshot):
    if not snapshot:
        return None
    source_batch = snapshot.source_batch
    if source_batch:
        return source_batch.completed_at or source_batch.started_at or snapshot.activated_at or snapshot.created_at
    return snapshot.activated_at or snapshot.created_at


def _active_snapshot_source_kind(snapshot):
    if snapshot and snapshot.source_batch and snapshot.source_batch.source_kind:
        return snapshot.source_batch.source_kind
    return "nursing_analytics_snapshot"


def _person_key(row):
    return row.get("registration_no") or row.get("practitioner_number") or row.get("full_name")


def _latest_nursing_batch():
    return (
        DataImportBatch.objects.filter(
            source_kind__in=NURSING_SOURCE_KINDS,
            status="completed",
        )
        .order_by("-completed_at", "-started_at")
        .first()
    )


def _latest_source_row(snapshot=None):
    snapshot = snapshot or active_nursing_analytics_snapshot()
    if snapshot:
        source_batch = snapshot.source_batch
        return {
            "source_file_name": snapshot.source_file_name,
            "source_kind": _active_snapshot_source_kind(snapshot),
            "completed_at": _format_datetime(_snapshot_completed_at(snapshot)),
            "processed_rows": snapshot.imported_rows or (source_batch.processed_rows if source_batch else 0),
            "total_rows": snapshot.total_rows or (source_batch.total_rows if source_batch else 0),
            "summary": snapshot.import_summary or (source_batch.summary if source_batch else {}),
        }

    latest_batch = _latest_nursing_batch()
    if not latest_batch:
        return None
    return {
        "source_file_name": latest_batch.source_file_name,
        "source_kind": latest_batch.source_kind,
        "completed_at": _format_datetime(latest_batch.completed_at),
        "processed_rows": latest_batch.processed_rows,
        "total_rows": latest_batch.total_rows,
        "summary": latest_batch.summary,
    }


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


def _snapshot_institution_year_counts(lifecycle_stage, cadre, start_year, end_year):
    snapshot = active_nursing_analytics_snapshot()
    if not snapshot:
        return None
    queryset = snapshot.institution_cadre_year_metrics.filter(
        lifecycle_stage=lifecycle_stage,
        cadre=cadre,
        year__gte=start_year,
        year__lte=end_year,
    )
    if not queryset.exists():
        return None
    counts = {year: 0 for year in range(start_year, end_year + 1)}
    for row in queryset.values("year").annotate(total=Sum("count")).order_by("year"):
        counts[row["year"]] = _safe_int(row["total"])
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


def _specialisation_counts(snapshot=None):
    if snapshot:
        counts = Counter()
        for row in snapshot.cadre_stage_metrics.values("cadre").annotate(total=Sum("authority_to_practice_count")):
            cadre = row["cadre"] or "Unspecified"
            count = _safe_int(row["total"])
            normalised = _normalise_cadre(cadre)
            if normalised == "registered nurse":
                counts["General Nurses"] += count
            elif normalised == "nursing":
                counts["General Nurses"] += count
            elif normalised == "midwife":
                counts["Midwives"] += count
            elif normalised == "nurse aide":
                counts["Nurse Aides"] += count
            elif normalised == "mental health nurse":
                counts["Mental Health Nurses"] += count
            elif normalised == "paediatric nurse":
                counts["Paediatric / Child Health Nurse"] += count
            elif normalised == "maternal & child health nurse":
                counts["Maternal & Child Health Nurse"] += count
            elif normalised == "enrolled nurse":
                counts["Enrolled Nurse"] += count
            elif "community health" in normalised:
                counts["Community Health Nurses"] += count
            elif "unclassified" in normalised or "missing" in normalised:
                counts["Unidentified Specialty Nurse"] += count
            elif "nurse" in normalised:
                counts["General Nurses"] += count
        return counts

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
    live_years = _snapshot_institution_year_counts("Provisional Licence", "Nursing Graduand", 2017, 2024)
    if live_years is None:
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
    live_years = _snapshot_institution_year_counts("Full Licence", "Midwifery", 2016, 2024)
    if live_years is None:
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
    snapshot_years = _snapshot_institution_year_counts("Full Licence", "Midwifery", 2021, 2025)
    if snapshot_years is not None:
        live_distinct = snapshot_years
        live_raw = snapshot_years
    else:
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
    snapshot = active_nursing_analytics_snapshot()
    if snapshot:
        kpis = snapshot.kpi_summary or {}
        provisional_total = _safe_int(kpis.get("clean_provisional_records"))
        full_total = _safe_int(kpis.get("clean_full_licence_records"))
        atp_total = _safe_int(kpis.get("clean_atp_records"))
        lifecycle_total = _safe_int(kpis.get("total_lifecycle_records")) or provisional_total + full_total + atp_total
        not_split = "Not separated in cleaned snapshot"
        table_rows = [
            [
                "PNG Provisional",
                3118,
                provisional_total,
                provisional_total,
                _variance_text(3118, provisional_total),
                _alignment_status(3118, provisional_total),
                "Cleaned provisional total from the active analytics snapshot; national/overseas split is not authoritative for this stage.",
            ],
            [
                "PNG Full License",
                3571,
                full_total,
                full_total,
                _variance_text(3571, full_total),
                _alignment_status(3571, full_total),
                "Cleaned full-licence total from the active analytics snapshot; national/overseas split is not authoritative for this stage.",
            ],
            [
                "Overseas Provisional",
                217,
                not_split,
                not_split,
                "Reference comparison only",
                "Not captured",
                "The cleaned snapshot keeps the provisional stage total but does not expose a trusted overseas provisional split.",
            ],
            [
                "Overseas Full License",
                109,
                not_split,
                not_split,
                "Reference comparison only",
                "Not captured",
                "The cleaned snapshot keeps the full-licence stage total but does not expose a trusted overseas full-licence split.",
            ],
            [
                "Overseas Temporary",
                426,
                not_split,
                not_split,
                "Reference comparison only",
                "Not captured",
                "Temporary overseas rows are not separated from the cleaned lifecycle snapshot in V1.",
            ],
            [
                "Authority to Practice",
                14987,
                atp_total,
                atp_total,
                _variance_text(14987, atp_total),
                _alignment_status(14987, atp_total),
                "Clean ATP total from the active analytics snapshot.",
            ],
            [
                "TOTAL",
                22428,
                lifecycle_total,
                lifecycle_total,
                _variance_text(22428, lifecycle_total),
                _alignment_status(22428, lifecycle_total),
                "Total cleaned lifecycle rows in the active analytics snapshot.",
            ],
        ]
        return table_rows, 22428, lifecycle_total

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
    live_counts = _specialisation_counts(active_nursing_analytics_snapshot())
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


def _analytics_atp_cadre_totals(snapshot):
    rows = (
        snapshot.cadre_stage_metrics
        .values("cadre")
        .annotate(total=Sum("authority_to_practice_count"))
    )
    registered_nurse_total = 0
    midwife_total = 0
    nurse_aide_total = 0

    for row in rows:
        cadre = _normalise_cadre(row["cadre"])
        count = _safe_int(row["total"])
        if cadre in MIDWIFE_ATP_CADRES:
            midwife_total += count
        elif cadre in NURSE_AIDE_ATP_CADRES:
            nurse_aide_total += count
        elif cadre in REGISTERED_NURSE_ATP_CADRES or (
            "nurse" in cadre and "aide" not in cadre and "midwife" not in cadre and "graduand" not in cadre
        ):
            registered_nurse_total += count

    return registered_nurse_total, midwife_total, nurse_aide_total


def _analytics_live_snapshot(snapshot):
    kpis = snapshot.kpi_summary or {}
    total_lifecycle = _safe_int(kpis.get("total_lifecycle_records")) or snapshot.lifecycle_facts.count()
    clean_atp = _safe_int(kpis.get("clean_atp_records"))
    clean_provisional = _safe_int(kpis.get("clean_provisional_records"))
    clean_full = _safe_int(kpis.get("clean_full_licence_records"))
    registered_nurse_total, midwife_total, nurse_aide_total = _analytics_atp_cadre_totals(snapshot)
    other_atp = max(clean_atp - registered_nurse_total - midwife_total - nurse_aide_total, 0)

    rows = [
        ["Total Lifecycle Records", total_lifecycle, "All cleaned Provisional, Full Licence, and ATP records"],
        ["Clean ATP Records", clean_atp, "Authority to Practice"],
        ["Clean Provisional Records", clean_provisional, "Provisional Licence / graduands"],
        ["Clean Full-Licence Records", clean_full, "Full Licence"],
        ["Registered Nurse ATP Cadre", registered_nurse_total, "Active ATP cadre grouping"],
        ["Midwife ATP Cadre", midwife_total, "Active ATP cadre grouping"],
        ["Nurse Aide ATP Cadre", nurse_aide_total, "Active ATP cadre grouping"],
    ]
    if other_atp:
        rows.append(["Other / Unclassified ATP Cadre", other_atp, "Active ATP records needing cadre review"])
    return rows


def _live_snapshot(snapshot=None):
    snapshot = snapshot or active_nursing_analytics_snapshot()
    if snapshot:
        return _analytics_live_snapshot(snapshot)
    return [
        ["Registered Nurses", NursingProfessional.objects.count(), NursingProfessional.objects.filter(is_active=True).count()],
        ["Midwives", Midwife.objects.count(), Midwife.objects.filter(is_active=True).count()],
        ["Nurse Aides", NurseAide.objects.count(), NurseAide.objects.filter(is_active=True).count()],
        ["Graduands", HealthStudent.objects.count(), HealthStudent.objects.filter(is_active=True).count()],
    ]


def _live_registry_total(snapshot, live_snapshot_rows):
    if snapshot:
        return _safe_int((snapshot.kpi_summary or {}).get("total_lifecycle_records"))
    return sum(row[1] for row in live_snapshot_rows)


def _platform_alignment_snapshot(snapshot=None):
    snapshot = snapshot or active_nursing_analytics_snapshot()
    latest_source = _latest_source_row(snapshot)
    latest_source_name = latest_source["source_file_name"] if latest_source else "Not captured"
    latest_completed = latest_source["completed_at"] if latest_source else "Not captured"
    return {
        "applications": Application.objects.filter(form_code__startswith="N").count() + Application.objects.filter(form_code__startswith="G").count(),
        "documents": Document.objects.filter(office_scope__in=["nursing", "general"]).count(),
        "document_audits": DocumentAuditEvent.objects.count(),
        "open_enquiries": EnquiryThread.objects.filter(office="nursing").count(),
        "latest_source_name": latest_source_name,
        "latest_completed": latest_completed,
    }


def build_nursing_regulatory_alignment_context():
    analytics_snapshot = active_nursing_analytics_snapshot()
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
            "comparison_note": "Compared against active cleaned Nursing analytics institution-year rows for nursing graduands (2017-2024), falling back to live qualification records if no snapshot is active.",
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
            "comparison_note": "Compared against active cleaned Nursing analytics full-licence midwifery rows (2016-2024), falling back to live qualification records if no snapshot is active.",
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
            "comparison_note": "Compared against active cleaned Nursing analytics midwifery full-licence rows (2021-2025), falling back to PracticingLicenseRecord if no snapshot is active.",
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
            "comparison_note": "Compared against active cleaned Nursing analytics lifecycle totals when available, falling back to imported registration records from 2019-2026.",
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
            "comparison_note": (
                "Compared against live EmploymentRecord rows. "
                f"Current employment rows in the database: {table_6_live_total:,}."
            ),
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
            "comparison_note": "Compared against active cleaned Nursing analytics ATP cadre rows when available. Blank source cells were not forced into numeric comparisons.",
            "report_total": table_8_report_total,
            "live_total": table_8_live_total,
        },
    ]

    latest_batch_row = _latest_source_row(analytics_snapshot)
    live_snapshot_rows = _live_snapshot(analytics_snapshot)
    source_file_name = latest_batch_row["source_file_name"] if latest_batch_row else "the live operational database"

    context = {
        "generated_on": _format_datetime(timezone.now()),
        "live_refresh_note": (
            f"These figures are read from the active cleansed Nursing analytics snapshot ({source_file_name}) on every page load. "
            "The operational legal registry is unchanged; accepted imports and promoted records are reflected after the next analytics snapshot import."
        ),
        "statutory_context": STATUTORY_CONTEXT,
        "live_snapshot_rows": live_snapshot_rows,
        "latest_batch_row": latest_batch_row,
        "platform_alignment": _platform_alignment_snapshot(analytics_snapshot),
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
    return context


def build_nursing_regulatory_alignment_summary_context():
    analytics_snapshot = active_nursing_analytics_snapshot()
    latest_batch_row = _latest_source_row(analytics_snapshot)
    live_snapshot_rows = _live_snapshot(analytics_snapshot)
    source_file_name = latest_batch_row["source_file_name"] if latest_batch_row else "the live operational database"
    summary = {
        "generated_on": _format_datetime(timezone.now()),
        "live_refresh_note": (
            f"These figures are read from the active cleansed Nursing analytics snapshot ({source_file_name}) on every page load."
        ),
        "statutory_context": STATUTORY_CONTEXT,
        "live_snapshot_rows": live_snapshot_rows,
        "latest_batch_row": latest_batch_row,
        "platform_alignment": _platform_alignment_snapshot(analytics_snapshot),
        "live_registry_total": _live_registry_total(analytics_snapshot, live_snapshot_rows),
    }
    return summary
