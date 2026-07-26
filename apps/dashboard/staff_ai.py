from collections import Counter
from datetime import date
from difflib import SequenceMatcher
import re

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db.models import Count, Q, Subquery
from django.urls import NoReverseMatch, reverse

from apps.common.models import DuplicateReviewQueue
from apps.dashboard.assistant_memory import (
    assistant_memory_rows,
    get_or_create_assistant_conversation,
    recent_assistant_history,
    record_assistant_turn,
    retrieve_assistant_sources,
    serialize_sources,
)
from apps.dashboard.access import (
    MEDICAL_BOARD_FORM_CODES,
    MEDICAL_BOARD_PROFESSIONAL_MODELS,
    NURSING_COUNCIL_PROFESSIONAL_MODELS,
    is_medical_board_staff,
    is_nursing_council_staff,
)
from apps.dashboard.ai_provider import ai_provider_status, maybe_generate_live_staff_response
from apps.dashboard.regulatory_ai_agents import build_regulatory_ai_tool_contract
from apps.dashboard.staff_ai_record_tools import search_staff_registry_records_for_user
from apps.dashboard.models import Receipt
from apps.dashboard.nursing_lapsed_renewal import lapsed_renewal_assistant_summary, lapsed_renewal_review_context
from apps.dashboard.registry_archive import (
    active_professional_count,
    archive_assistant_summary,
    current_archive_year,
)
from apps.dashboard.assistant_scope_context import (
    detect_cross_scope_question,
    nursing_cadre_answer_payload,
    nursing_cadre_dataflow_context,
    nursing_pathway_context,
    scope_policy_context,
)
from apps.documents.models import Document
from apps.notifications.models import EnquiryThread
from apps.workforce.models import (
    Application,
    CommunityHealthWorker,
    DataImportBatch,
    HealthStudent,
    MedicalDoctor,
    MissingDataReview,
    Midwife,
    NurseAide,
    NursingProfessional,
    PracticingLicenseRecord,
    ProfessionalDocument,
)
from apps.workforce.services.data_quality import quality_approved_import_records

STAFF_AI_CACHE_TIMEOUT = 120
ACTION_ROWS = [
    {
        "label": "Financial Forecast",
        "url_name": "financial_forecast_dashboard",
        "description": "Open the dedicated finance page to track manual receipts, spreadsheet receipts, monthly totals, yearly totals, and forecast trends by office.",
    },
    {
        "label": "Duplicate Review Workflow",
        "url_name": "duplicate_review_workflow",
        "description": "Open the staff duplicate-review queue to inspect grouped practitioner records and mark cases as reviewed or merged.",
    },
    {
        "label": "Open Bulk Import",
        "url_name": "import_data",
        "description": "Use this when a new workbook or CSV file needs to be loaded into the system.",
    },
    {
        "label": "Monthly Excel Report",
        "url_name": "export_monthly_analytics_excel",
        "description": "Exports the detailed Excel analytics workbook for the current staff scope.",
    },
    {
        "label": "Monthly PDF Report",
        "url_name": "export_monthly_analytics_pdf",
        "description": "Exports the printable monthly PDF report for the current staff scope.",
    },
    {
        "label": "Yearly Excel Report",
        "url_name": "export_yearly_analytics_excel",
        "description": "Exports a year-focused Excel workbook for the current staff scope.",
    },
    {
        "label": "Yearly PDF Report",
        "url_name": "export_yearly_analytics_pdf",
        "description": "Exports a year-focused printable PDF report for the current staff scope.",
    },
    {
        "label": "Minister Brief",
        "url_name": "export_minister_brief_docx",
        "description": "Generates the latest Minister-ready Word brief with live statistics and interface screenshots.",
    },
    {
        "label": "Registrar & Secretary Brief",
        "url_name": "export_registrar_secretary_brief_docx",
        "description": "Generates the full system Word brief for office management and administrative support staff.",
    },
]
GUIDE_ROWS = [
    "Start with a focused question that names your office scope and asks for sources; for example, ask for Nursing Council ATP approval checks with sources.",
    "Treat every answer as decision support. Open the cited platform source and complete the required registrar review before approving, licensing, or changing a record.",
    "Open the AI assistant before or after an import to see the latest data-quality and screening signals.",
    "Use the screening queue first. Every pending application should be checked for a linked practitioner record, receipt, supporting documents, and any missing-data review.",
    "Run the missing-data audit after imports or bulk updates so the queue reflects the latest state of the registry.",
    "Use monthly and yearly reports after imports and audits so management sees refreshed statistics rather than stale totals.",
    "Applicants do not have access to this assistant. They should continue using the public AI helpdesk and enquiry tools only.",
]
CHAT_SUGGESTIONS = [
    "How many pending applications do I need to review?",
    "What should I check before approving an applicant?",
    "Do we have missing data that needs follow-up?",
    "Which report should I generate for management?",
]
FOCUSED_CHAT_SUGGESTIONS = {
    "nursing": [
        "For Nursing Council, list the checks before approving an ATP renewal, with sources.",
        "For Nursing Council, explain the NC1, NC2, and NC3 pathway with sources.",
        "Show the Nursing workforce retirement outlook and facility staffing signals, with sources.",
        "How many nurses under 35 are working in rural facilities? Include sources.",
        "Find the Nursing Council ATP record for registration RN-12345.",
        "What Nursing Council data-quality reviews should I clear before reporting?",
    ],
    "medical": [
        "For Medical Board, list the checks before approving a doctor or CHW application, with sources.",
        "Show Medical Board specialist, accreditation, credential, and clinical-privilege signals, with sources.",
        "How many cardiologists are in Western Province? Include sources.",
        "Find the Medical Board record for registration MB-12345.",
        "What Medical Board data-quality reviews should I clear before reporting?",
        "Which Medical Board report should I generate for management?",
    ],
    "all": [
        "For Nursing Council, list the checks before approving an ATP renewal, with sources.",
        "For Medical Board, list the checks before approving a doctor or CHW application, with sources.",
        "Show Nursing workforce retirement signals with sources.",
        "How many nurses under 35 are working in rural facilities? Include sources.",
        "Show Medical Board specialist and facility-accreditation signals with sources.",
        "How many cardiologists are in Western Province? Include sources.",
        "Compare only the authorised Nursing Council and Medical Board workflows, with sources.",
    ],
}
DECISION_SUPPORT_NOTICE = (
    "Decision support only - verify the cited platform sources before any approval, licence, legal, clinical, or payment decision."
)
ARCHIVE_QUESTION_TOKENS = (
    "archive",
    "archives",
    "archived",
    "archive table",
    "old worker",
    "old workers",
    "old nurses",
    "old staff",
    "old by age",
    "retired",
    "retirement",
    "deceased",
    "death",
    "lapsed renewal",
    "lapsed renewals",
    "lapsed licence",
    "lapsed license",
    "outdated",
    "out dated",
    "filter out",
    "exclude from total",
    "exclude from active",
    "active totals",
    "accurate data totals",
)


def _staff_scope(user):
    if getattr(user, "role", "") == "admin":
        return "all"
    if is_medical_board_staff(user):
        return "medical"
    if is_nursing_council_staff(user):
        return "nursing"
    return ""


def _scope_label(scope):
    return {
        "all": "All Regulatory Offices",
        "nursing": "Nursing Council",
        "medical": "Medical Board",
    }.get(scope, "Restricted")


def _agent_label(scope, role):
    if role == "admin":
        return "AI Admin Assistant"
    if scope == "medical":
        return "AI Medical Board Assistant"
    return "AI Registrar Assistant"


def _chat_suggestions_for_scope(scope):
    return FOCUSED_CHAT_SUGGESTIONS.get(scope, CHAT_SUGGESTIONS)


def _registry_rows_for_scope(scope):
    if scope == "medical":
        return [
            ("Medical Doctors", active_professional_count(MedicalDoctor, scope="medical")),
            ("Community Health Workers", active_professional_count(CommunityHealthWorker, scope="medical")),
        ]
    if scope == "all":
        return [
            ("Registered Nurses", active_professional_count(NursingProfessional, scope="nursing")),
            ("Midwives", active_professional_count(Midwife, scope="nursing")),
            ("Nurse Aides", active_professional_count(NurseAide, scope="nursing")),
            ("Graduands", active_professional_count(HealthStudent, scope="nursing")),
            ("Medical Doctors", active_professional_count(MedicalDoctor, scope="medical")),
            ("Community Health Workers", active_professional_count(CommunityHealthWorker, scope="medical")),
        ]
    return [
        ("Registered Nurses", active_professional_count(NursingProfessional, scope="nursing")),
        ("Midwives", active_professional_count(Midwife, scope="nursing")),
        ("Nurse Aides", active_professional_count(NurseAide, scope="nursing")),
        ("Graduands", active_professional_count(HealthStudent, scope="nursing")),
    ]


def _employment_totals_for_scope(scope):
    # Current employment records are not yet scoped by office in a clean
    # way, so for Nursing Council we only report the live totals if present.
    # This is still useful for direct management questions.
    from apps.workforce.models import EmploymentRecord

    total = EmploymentRecord.objects.count()
    employed = EmploymentRecord.objects.exclude(employment_status__in=["", "unemployed", "studying"]).count()
    unemployed = EmploymentRecord.objects.filter(employment_status="unemployed").count()
    return {
        "total": total,
        "employed": employed,
        "unemployed": unemployed,
    }


def _current_live_statistics(scope):
    latest_import = _latest_import_summary(scope)
    registry_rows = _registry_rows_for_scope(scope)
    stats = {
        "latest_import": latest_import,
        "registry_counts": {label.lower(): count for label, count in registry_rows},
        "registry_rows": registry_rows,
        "employment": _employment_totals_for_scope(scope),
    }
    return stats


def _find_registry_metric(question_lower, stats):
    aliases = [
        (("midwife", "midwives"), "Midwives"),
        (("nurse aide", "nurse aides", "nurseaide", "nurse aide total"), "Nurse Aides"),
        (("registered nurse", "registered nurses", "nurses", "nurse total"), "Registered Nurses"),
        (("graduand", "graduands", "students"), "Graduands"),
        (("medical doctor", "medical doctors", "doctors"), "Medical Doctors"),
        (("community health worker", "community health workers", "chw", "chws"), "Community Health Workers"),
    ]
    for tokens, label in aliases:
        if any(token in question_lower for token in tokens):
            return label, dict(stats["registry_rows"]).get(label)
    return None, None


def _question_is_source_question(question_lower):
    tokens = (
        "where did the latest data come from",
        "where did this data come from",
        "latest data come from",
        "latest source",
        "source file",
        "latest import",
        "recent import",
        "what was the latest source",
        "what was the recent source",
        "when was the recent data from",
        "when was the latest data from",
    )
    return any(token in question_lower for token in tokens)


def _question_is_archive_filter_question(question_lower):
    return any(token in question_lower for token in ARCHIVE_QUESTION_TOKENS)


def _question_is_facility_breakdown_question(question_lower):
    has_facility_term = any(token in question_lower for token in (
        "facility",
        "facilities",
        "workplace",
        "workplaces",
        "hospital",
        "hospitals",
    ))
    has_breakdown_term = any(token in question_lower for token in (
        "breakdown",
        "break down",
        "list",
        "find",
        "show",
        "where",
        "top",
    ))
    return has_facility_term and has_breakdown_term


def _facility_breakdown_for_scope(scope, limit=5):
    """Return a scoped summary of quality-approved imported workplace records."""
    records = quality_approved_import_records(
        PracticingLicenseRecord.objects.filter(batch__status="completed")
    ).exclude(workplace_address__isnull=True).exclude(workplace_address="")
    if scope == "nursing":
        records = records.filter(
            target_model__in=["nursingprofessional", "midwife", "nurseaide", "healthstudent"],
        ).exclude(batch__source_kind="medical_board_workbook")
    elif scope == "medical":
        records = records.filter(
            batch__source_kind="medical_board_workbook",
            target_model__in=["medicaldoctor", "communityhealthworker", "other"],
        )
    else:
        records = records.filter(
            target_model__in=[
                "nursingprofessional",
                "midwife",
                "nurseaide",
                "healthstudent",
                "medicaldoctor",
                "communityhealthworker",
                "other",
            ],
        )

    grouped = {}
    total_rows = 0
    for row in records.values("workplace_address").annotate(total=Count("id")):
        label = " ".join((row["workplace_address"] or "").split())
        if not label:
            continue
        key = label.casefold()
        current = grouped.setdefault(key, {"label": label, "count": 0})
        current["count"] += row["total"]
        total_rows += row["total"]

    top_rows = sorted(grouped.values(), key=lambda item: (-item["count"], item["label"]))[:limit]
    return {
        "facility_count": len(grouped),
        "workplace_row_count": total_rows,
        "top_rows": top_rows,
    }


def _facility_breakdown_links(scope):
    nursing_links = [
        ("Facility & Institution Breakdown", reverse("nursing_council_portal") + "#institution-facility-breakdown"),
        ("ATP Workplace Breakdown", reverse("nursing_council_portal") + "#atp-workplace-breakdown"),
    ]
    medical_links = [
        ("Medical Board Facilities", "medical_board_portal"),
    ]
    if scope == "nursing":
        return nursing_links
    if scope == "medical":
        return medical_links
    return nursing_links + medical_links


def _facility_breakdown_answer(context, scope):
    breakdown = _facility_breakdown_for_scope(scope)
    links = _facility_breakdown_links(scope)
    source_url = links[0][1] if links else ""
    if not breakdown["workplace_row_count"]:
        return {
            "title": "Facility And Workplace Breakdown",
            "answer": (
                f"I could not find quality-approved imported workplace rows in {context['scope_label']} yet. "
                "Open the facility reference screen to review master facilities or load the approved workbook data first."
            ),
            "bullets": [
                "This answer only uses quality-approved imported workplace records.",
                "A blank result does not mean there are no facility master records; it means there are no approved workplace rows to group.",
            ],
            "links": links,
            "suggestions": [
                "Show the ATP workplace breakdown",
                "Which report should I generate for management?",
                "Where did the latest data come from?",
            ],
            "_skip_live_model": True,
        }

    top_rows = breakdown["top_rows"]
    return {
        "title": "Facility And Workplace Breakdown",
        "answer": (
            f"I found {breakdown['facility_count']} distinct workplace references across "
            f"{breakdown['workplace_row_count']} quality-approved imported workbook rows in {context['scope_label']}. "
            "The leading references are listed below; open the breakdown screen for the full drilldown."
        ),
        "bullets": [
            *[
                f"{row['label']}: {row['count']} imported workplace row{'s' if row['count'] != 1 else ''}."
                for row in top_rows
            ],
            "These are scoped workbook workplace references, not a combined cross-office facility total.",
        ],
        "links": links,
        "suggestions": [
            "Show the ATP workplace breakdown",
            "Which facility has the most imported records?",
            "Where did the latest data come from?",
        ],
        "sources": [{
            "label": "Quality-approved imported workplace records",
            "detail": "Grouped from the authorised office scope after data-quality exclusions.",
            "url": source_url,
        }],
        "_skip_live_model": True,
    }


def _application_queryset(scope):
    queryset = Application.objects.select_related("content_type", "reviewed_by").order_by("-submitted_date")
    if scope == "medical":
        return queryset.filter(form_code__in=MEDICAL_BOARD_FORM_CODES)
    if scope == "nursing":
        return queryset.exclude(form_code__in=MEDICAL_BOARD_FORM_CODES)
    return queryset


def _missing_review_queryset(scope):
    queryset = MissingDataReview.objects.exclude(status="resolved").order_by("-missing_count", "full_name")
    if scope == "all":
        return queryset
    if scope == "medical":
        practicing_content_type = ContentType.objects.get_for_model(PracticingLicenseRecord)
        practicing_record_ids = PracticingLicenseRecord.objects.filter(
            batch__source_kind="medical_board_workbook",
            target_model__in=["medicaldoctor", "communityhealthworker", "other"],
            record_year__isnull=False,
            record_year__lte=date.today().year,
        ).values("id")
        return queryset.filter(
            Q(content_type__model__in=MEDICAL_BOARD_PROFESSIONAL_MODELS)
            | Q(professional_type__in=["Medical Doctor", "Community Health Worker"])
            | Q(content_type=practicing_content_type, object_id__in=Subquery(practicing_record_ids))
        )
    if scope == "nursing":
        practicing_content_type = ContentType.objects.get_for_model(PracticingLicenseRecord)
        practicing_record_ids = PracticingLicenseRecord.objects.filter(
            target_model__in=["nursingprofessional", "midwife", "nurseaide", "healthstudent"],
        ).exclude(batch__source_kind="medical_board_workbook").values("id")
        return queryset.filter(
            Q(content_type__model__in=NURSING_COUNCIL_PROFESSIONAL_MODELS)
            | Q(professional_type__in=["Nursing Professional", "Midwife", "Nurse Aide", "Graduand"])
            | Q(content_type=practicing_content_type, object_id__in=Subquery(practicing_record_ids))
        )
    return queryset.none()


def _duplicate_review_queryset(scope):
    queryset = DuplicateReviewQueue.objects.filter(status="pending").select_related("content_type").order_by("-similarity_score")
    if scope == "all":
        return queryset
    allowed_models = MEDICAL_BOARD_PROFESSIONAL_MODELS if scope == "medical" else NURSING_COUNCIL_PROFESSIONAL_MODELS
    practicing_record_ids = PracticingLicenseRecord.objects.filter(
        target_model__in=allowed_models
    ).values("id")
    practicing_content_type = ContentType.objects.get_for_model(PracticingLicenseRecord)
    return queryset.filter(
        Q(content_type__model__in=allowed_models)
        | Q(suspected_duplicate__target_model__in=allowed_models)
        | Q(content_type=practicing_content_type, object_id__in=Subquery(practicing_record_ids))
    )


def _import_queryset(scope):
    queryset = DataImportBatch.objects.order_by("-started_at")
    if scope == "medical":
        return queryset.filter(source_kind="medical_board_workbook")
    if scope == "nursing":
        return queryset.filter(source_kind__in=["ndata_workbook", "nursing_full_registration_2026"])
    return queryset


def _document_queryset(scope):
    queryset = Document.objects.order_by("-updated_at")
    if scope == "all":
        return queryset
    return queryset.filter(office_scope__in=[scope, "general"])


def _enquiry_queryset(scope):
    queryset = EnquiryThread.objects.order_by("-updated_at")
    if scope == "all":
        return queryset
    return queryset.filter(office=scope)


def _application_domain_for_row(application, scope):
    if scope == "all":
        return "medical" if application.form_code in MEDICAL_BOARD_FORM_CODES else "nursing"
    return scope


def _professional_reference_filter(applications):
    professional_refs = {
        (application.content_type_id, application.object_id)
        for application in applications
        if application.content_type_id and application.object_id
    }
    query = Q()
    for content_type_id, object_id in professional_refs:
        query |= Q(content_type_id=content_type_id, object_id=object_id)
    return query, professional_refs


def _screening_queue(scope, limit=20):
    pending_queryset = _application_queryset(scope).filter(status="pending")
    pending_total = pending_queryset.count()
    applications = list(pending_queryset[:limit])

    receipt_counts = {
        row["application_id"]: row["total"]
        for row in Receipt.objects.filter(application_id__in=[application.id for application in applications])
        .values("application_id")
        .annotate(total=Count("id"))
    }

    professional_filter, _ = _professional_reference_filter(applications)
    document_counts = {}
    missing_reviews = {}
    if professional_filter:
        document_counts = {
            (row["content_type_id"], row["object_id"]): row["total"]
            for row in ProfessionalDocument.objects.filter(professional_filter)
            .values("content_type_id", "object_id")
            .annotate(total=Count("id"))
        }
        missing_reviews = {
            (row["content_type_id"], row["object_id"]): row["missing_fields"]
            for row in MissingDataReview.objects.filter(professional_filter)
            .exclude(status="resolved")
            .values("content_type_id", "object_id", "missing_fields")
        }

    queue_rows = []
    needs_follow_up = 0
    for application in applications:
        professional_key = (
            (application.content_type_id, application.object_id)
            if application.content_type_id and application.object_id
            else None
        )
        professional = getattr(application, "professional", None)
        receipt_count = receipt_counts.get(application.id, 0)
        document_count = document_counts.get(professional_key, 0) if professional_key else 0
        missing_fields = missing_reviews.get(professional_key) if professional_key else None
        flags = []

        if professional is None:
            flags.append("No linked practitioner record")
        if receipt_count == 0:
            flags.append("No linked receipt record")
        if professional_key and document_count == 0:
            flags.append("No supporting documents on file")
        if missing_fields:
            preview = ", ".join(str(field) for field in missing_fields[:3]) if missing_fields else "registry fields"
            flags.append(f"Missing data review open: {preview}")

        if not flags:
            flags = ["Ready for registrar screening"]
            status_label = "Ready to review"
        else:
            status_label = "Needs follow-up"
            needs_follow_up += 1

        queue_rows.append({
            "application": application,
            "professional": professional,
            "domain": _application_domain_for_row(application, scope),
            "receipt_count": receipt_count,
            "document_count": document_count,
            "flags": flags,
            "status_label": status_label,
        })
    return queue_rows, pending_total, needs_follow_up


def _top_missing_fields(scope, limit=8):
    counter = Counter()
    for review in _missing_review_queryset(scope):
        for field in review.missing_fields:
            counter[str(field)] += 1
    return counter.most_common(limit)


def _latest_import_summary(scope):
    batch = _import_queryset(scope).filter(status="completed").first()
    if not batch:
        return None
    summary = batch.summary or {}
    return {
        "batch": batch,
        "source_file_name": batch.source_file_name,
        "source_kind": batch.source_kind,
        "processed_rows": batch.processed_rows,
        "total_rows": batch.total_rows,
        "duplicates_detected": summary.get("duplicates_detected", 0),
        "applications_created": summary.get("applications_created", 0),
        "applications_updated": summary.get("applications_updated", 0),
        "professionals_created": summary.get("professionals_created", 0),
        "professionals_updated": summary.get("professionals_updated", 0),
        "practice_records_created": summary.get("practice_records_created", 0),
    }


def _assistant_recommendations(scope, latest_import, missing_reviews, duplicate_reviews, screening_total, needs_follow_up):
    recommendations = []
    if latest_import:
        if latest_import["duplicates_detected"]:
            recommendations.append(
                f"Review {latest_import['duplicates_detected']} duplicate candidates from the latest import before approving downstream records."
            )
        if latest_import["applications_created"]:
            recommendations.append(
                f"Screen the {latest_import['applications_created']} newly created applications from the latest import batch."
            )

    if missing_reviews:
        recommendations.append(
            f"Resolve or notify {missing_reviews} active missing-data reviews so applicant files can move through screening cleanly."
        )

    if duplicate_reviews:
        recommendations.append(
            f"Work through {duplicate_reviews} pending duplicate-review items to reduce misaligned registry records."
        )

    if screening_total:
        recommendations.append(
            f"{screening_total} pending applications are in the screening queue, with {needs_follow_up} already showing missing-receipt, missing-document, or missing-data flags."
        )

    if not recommendations:
        recommendations.append("No urgent data-alignment risks were detected in the current scope. Continue routine screening and audit checks.")
    return recommendations


def build_staff_ai_context(user, detailed=True):
    scope = _staff_scope(user)
    cache_key = f"staff-ai:{user.id}:{scope}:{'detailed' if detailed else 'profile'}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    pending_application_count = _application_queryset(scope).filter(status="pending").count()
    missing_review_count = _missing_review_queryset(scope).count()
    duplicate_review_count = _duplicate_review_queryset(scope).count()
    open_enquiry_count = _enquiry_queryset(scope).filter(status="open").count()
    document_review_count = _document_queryset(scope).filter(status="draft").count()

    context = {
        "scope": scope,
        "scope_label": _scope_label(scope),
        "agent_label": _agent_label(scope, getattr(user, "role", "")),
        "pending_application_count": pending_application_count,
        "screening_total": pending_application_count,
        "missing_review_count": missing_review_count,
        "duplicate_review_count": duplicate_review_count,
        "open_enquiry_count": open_enquiry_count,
        "document_review_count": document_review_count,
        "guide_rows": GUIDE_ROWS,
        "chat_suggestions": _chat_suggestions_for_scope(scope),
        "action_rows": ACTION_ROWS,
        "ai_provider": ai_provider_status(),
        "scope_policy": scope_policy_context(scope),
    }
    if detailed:
        screening_rows, screening_total, needs_follow_up = _screening_queue(scope)
        latest_import = _latest_import_summary(scope)
        context.update({
            "latest_import": latest_import,
            "screening_total": screening_total,
            "screening_rows": screening_rows,
            "top_missing_fields": _top_missing_fields(scope),
            "assistant_recommendations": _assistant_recommendations(
                scope,
                latest_import,
                missing_review_count,
                duplicate_review_count,
                screening_total,
                needs_follow_up,
            ),
            "recent_imports": list(_import_queryset(scope)[:5]),
        })
        if scope in {"all", "nursing"}:
            context.update(lapsed_renewal_review_context(limit=15))
            context["nursing_pathway_context"] = nursing_pathway_context()
            context["nursing_cadre_context"] = nursing_cadre_dataflow_context(limit=12)
    cache.set(cache_key, context, STAFF_AI_CACHE_TIMEOUT)
    return context


def _quick_staff_ai_context(user, scope):
    return {
        "scope": scope,
        "scope_label": _scope_label(scope),
        "agent_label": _agent_label(scope, getattr(user, "role", "")),
        "ai_provider": ai_provider_status(),
    }


def _score_staff_question(question, keywords):
    score = 0.0
    for keyword in keywords:
        keyword_text = keyword.lower()
        if keyword_text in question:
            score += 3.0 + min(len(keyword_text), 18) / 18
        else:
            score += SequenceMatcher(None, question, keyword_text).ratio()
    return score


def _chat_links_for_scope(scope):
    links = [
        ("Open Full Assistant", "staff_ai_assistant"),
        ("Duplicate Review Workflow", "duplicate_review_workflow"),
        ("Staff Inbox & Chat", "staff_communications"),
        ("Bulk Import", "import_data"),
        ("Repository Search", "repository_search"),
        ("Registry Archives", "registry_archive"),
    ]
    if scope == "nursing":
        links.append(("Nursing Council Live Statistics", "nursing_regulatory_alignment"))
    return links


def _serialize_chat_links(links):
    serialized = []
    for link in links or []:
        if isinstance(link, dict):
            label = link.get("label")
            url = link.get("url")
        else:
            try:
                label, url = link
            except (TypeError, ValueError):
                continue
        if not label or not url:
            continue
        url = str(url)
        if not url.startswith(("/", "http://", "https://", "#")):
            try:
                url = reverse(url)
            except NoReverseMatch:
                continue
        serialized.append({"label": str(label), "url": url})
    return serialized[:5]


def _default_staff_ai_answer(user, context):
    role_label = "admin" if getattr(user, "role", "") == "admin" else "registrar"
    return {
        "title": context["agent_label"],
        "answer": (
            f"You are signed in as a {role_label} with {context['scope_label']} access. "
            "Ask me about screening, missing data, duplicate records, imports, reports, documents, or role access."
        ),
        "bullets": [
            f"There are {context['pending_application_count']} pending applications in your current scope.",
            f"There are {context['missing_review_count']} open missing-data reviews and {context['duplicate_review_count']} duplicate-review items.",
            "I can guide you to the right report, import tool, document screen, or follow-up workflow.",
        ],
        "links": _chat_links_for_scope(context["scope"]),
        "suggestions": _chat_suggestions_for_scope(context["scope"]),
    }


def _staff_user_label(user):
    full_name = ""
    get_full_name = getattr(user, "get_full_name", None)
    if callable(get_full_name):
        full_name = get_full_name()
    return full_name or getattr(user, "username", "") or "this signed-in user"


def _question_is_platform_scope_question(question_lower):
    return any(
        token in question_lower
        for token in (
            "explain the platform",
            "explain this platform",
            "what is this platform",
            "what platform is this",
            "where am i",
            "which portal am i in",
            "which scope am i in",
            "what is my scope",
            "current scope",
            "my current scope",
            "how does this platform work",
            "what does this platform do",
            "tell me about this platform",
            "platform scope",
        )
    )


def _question_is_assistant_intro(question_lower):
    greeting_tokens = ("hi", "hello", "hey", "good morning", "good afternoon", "good evening")
    identity_tokens = (
        "what are you",
        "who are you",
        "what can you do",
        "introduce yourself",
        "your name",
        "are you ai",
        "are you an ai",
        "what is this assistant",
    )
    if any(token in question_lower for token in identity_tokens):
        return True
    words = set(question_lower.replace("?", " ").replace(",", " ").split())
    return bool(words & set(greeting_tokens)) and len(words) <= 12


SENSITIVE_RECORD_REQUEST_TOKENS = (
    "date of birth",
    "dob",
    "mobile number",
    "phone number",
    "phone",
    "telephone",
    "contact details",
    "contact information",
    "contact number",
    "email address",
    "email of",
    "full address",
    "home address",
    "residential address",
    "postal address",
    "address of",
    "raw payload",
    "raw import",
    "payment amount",
    "payment details",
)

# A record lookup is intentionally more conservative than the normal AI
# assistant language handling.  It is only started by an explicit search-like
# request with a person-shaped name, or by a prefixed registration/practitioner
# identifier.  This keeps broad operational questions out of the live-record
# path and avoids turning the assistant into an unrestricted people search.
STAFF_AI_RECORD_IDENTIFIER_RE = re.compile(
    r"\b(?:[a-z]{1,8}[-/][a-z0-9]{2,}(?:[-/][a-z0-9]+)*|[a-z]{2,8}\d{3,}[a-z0-9-]*)\b",
    re.IGNORECASE,
)
STAFF_AI_RECORD_LOOKUP_ACTION_RE = re.compile(
    r"\b(?:look\s*up|lookup|search(?:\s+for)?|find|show|open|get|retrieve|fetch|bring\s+up|pull\s+up)\b",
    re.IGNORECASE,
)
STAFF_AI_RECORD_BROAD_TERMS = {
    "all",
    "any",
    "every",
    "records",
    "record",
    "registry",
    "registries",
    "statistics",
    "summary",
    "summaries",
    "report",
    "reports",
    "count",
    "counts",
    "total",
    "totals",
    "pending",
    "expired",
    "active",
    "missing",
    "duplicate",
    "duplicates",
    "applications",
    "application",
    "facilities",
    "facility",
    "province",
    "provinces",
    "distribution",
    "workforce",
    "staffing",
    "shortage",
    "shortages",
    "gap",
    "gaps",
    "data",
    "review",
    "reviews",
}
STAFF_AI_RECORD_TARGET_TERMS = (
    ("community health worker", "communityhealthworker"),
    ("nursing professional", "nursingprofessional"),
    ("registered nurse", "nursingprofessional"),
    ("medical doctor", "medicaldoctor"),
    ("nurse aide", "nurseaide"),
    ("health student", "healthstudent"),
    ("graduand", "healthstudent"),
    ("midwife", "midwife"),
    ("doctor", "medicaldoctor"),
    ("nurse", "nursingprofessional"),
    ("chw", "communityhealthworker"),
)
STAFF_AI_RECORD_TYPE_TERMS = (
    ("authority to practice", "practicing_license"),
    ("practising licence", "practicing_license"),
    ("practicing licence", "practicing_license"),
    ("practising license", "practicing_license"),
    ("practicing license", "practicing_license"),
    ("atp", "practicing_license"),
    ("full approved", "full_approved"),
    ("full licence", "full"),
    ("full license", "full"),
    ("provisional", "provisional"),
    ("temporary", "temporary"),
)


def _compact_record_lookup_text(value, max_length=160):
    return " ".join(str(value or "").strip().split())[:max_length]


def _record_lookup_identifier(question_lower):
    for match in STAFF_AI_RECORD_IDENTIFIER_RE.finditer(question_lower or ""):
        identifier = _compact_record_lookup_text(match.group(0), max_length=100)
        if identifier:
            return identifier
    return ""


def _record_lookup_target_model(question_lower):
    for term, target_model in STAFF_AI_RECORD_TARGET_TERMS:
        if re.search(rf"\b{re.escape(term)}\b", question_lower or ""):
            return target_model
    return ""


def _record_lookup_record_type(question_lower):
    for term, record_type in STAFF_AI_RECORD_TYPE_TERMS:
        if re.search(rf"\b{re.escape(term)}\b", question_lower or ""):
            return record_type
    return ""


def _record_lookup_year(question_lower):
    matches = re.findall(r"\b(?:19\d{2}|20\d{2}|2100)\b", question_lower or "")
    return int(matches[-1]) if matches else 0


def _record_lookup_name_candidate(question_lower):
    """Return a narrow person-name query from an explicit record request."""
    if not STAFF_AI_RECORD_LOOKUP_ACTION_RE.search(question_lower or ""):
        return ""

    text = _compact_record_lookup_text(question_lower)
    # Prefer unambiguous "record/profile/registration for Name" forms.
    patterns = (
        r"\b(?:show|open|get|retrieve|fetch|bring\s+up|pull\s+up)\s+(?:me\s+)?(.+?)(?:['\u2019]s)?\s+(?:registry\s+)?(?:records?|profiles?|registrations?|licen[cs]es?)\b",
        r"\b(?:record|registry(?:\s+record)?|profile|registration|practitioner|professional|licen[cs]e)\s+(?:for|of|named|called)\s+(.+)$",
        r"\b(?:look\s*up|lookup|search(?:\s+for)?|find|show|open|get|retrieve|fetch|bring\s+up|pull\s+up)\s+(?:the\s+)?(?:registry\s+)?(?:record|profile|registration|practitioner|professional|licen[cs]e)\s+(?:for|of|named|called)\s+(.+)$",
        r"\b(?:look\s*up|lookup|search(?:\s+for)?|find|show|open|get|retrieve|fetch|bring\s+up|pull\s+up)\s+(.+?)(?:['’]s)?\s+(?:registry\s+)?(?:record|profile|registration|licen[cs]e)\b",
        r"\b(?:look\s*up|lookup|search(?:\s+for)?|find|show|open|get|retrieve|fetch|bring\s+up|pull\s+up)\s+(.+)$",
        r"\b(?:for|of)\s+(.+?)(?:['’]s)?\s+(?:registry\s+)?(?:record|profile|registration|licen[cs]e)\b",
    )
    candidate = ""
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            candidate = match.group(1)
            break
    if not candidate:
        return ""

    candidate = re.sub(r"\b(?:with|and)\s+sources?\b.*$", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(
        r"^(?:the\s+)?(?:registry\s+)?(?:record|profile|registration|practitioner|professional|licen[cs]e)\s+(?:for|of)\s+",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(
        r"^(?:dr\.?|doctor|medical doctor|registered nurse|nursing professional|nurse aide|community health worker|chw|nurse|midwife|graduand|health student)\s+",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    # A year is a structured lookup filter, not part of a person's name.
    candidate = re.sub(r"\s+(?:(?:in|for)\s+)?(?:19\d{2}|20\d{2}|2100)\b", "", candidate)
    candidate = _compact_record_lookup_text(candidate.strip(" .?!,:;\"'"), max_length=120)
    name_tokens = re.findall(r"[a-z][a-z.'-]*", candidate.lower())
    if not 2 <= len(name_tokens) <= 5:
        return ""
    if any(token in STAFF_AI_RECORD_BROAD_TERMS for token in name_tokens):
        return ""
    if any(term in candidate.lower() for term in ("how many", "number of", "current ", "latest ")):
        return ""
    return candidate


def _explicit_staff_record_lookup(question):
    """Parse only explicit, narrow requests for an authorised live record lookup."""
    question_lower = _compact_record_lookup_text(question).lower()
    if not question_lower:
        return None

    identifier = _record_lookup_identifier(question_lower)
    name_query = _record_lookup_name_candidate(question_lower)
    if not identifier and not name_query:
        return None

    return {
        "query": identifier or name_query,
        "record_type": _record_lookup_record_type(question_lower),
        "target_model": _record_lookup_target_model(question_lower),
        "year": _record_lookup_year(question_lower),
        "trigger": "registration_identifier" if identifier else "explicit_record_request",
    }


def _safe_record_lookup_value(value, max_length=180):
    return _compact_record_lookup_text(value, max_length=max_length)


def _safe_staff_record_lookup_record(record):
    """Whitelist data fields before an operational record summary enters chat history."""
    try:
        record_id = int(record.get("id"))
    except (TypeError, ValueError):
        record_id = None
    record_url = ""
    if record_id:
        # Rebuild the only permitted detail URL rather than trusting a value
        # passed through from an imported record or a future tool change.
        try:
            record_url = reverse(
                "record_detail",
                kwargs={"model_slug": "practicinglicenserecord", "pk": record_id},
            )
        except NoReverseMatch:
            record_url = ""
    return {
        "id": record_id,
        "record_url": record_url,
        "full_name": _safe_record_lookup_value(record.get("full_name"), 120),
        "record_type": _safe_record_lookup_value(record.get("record_type"), 80),
        "record_type_code": _safe_record_lookup_value(record.get("record_type_code"), 40),
        "target": _safe_record_lookup_value(record.get("target"), 80),
        "target_model": _safe_record_lookup_value(record.get("target_model"), 40),
        "registration_no": _safe_record_lookup_value(record.get("registration_no"), 100),
        "practitioner_number": _safe_record_lookup_value(record.get("practitioner_number"), 100),
        "record_year": record.get("record_year") if isinstance(record.get("record_year"), int) else None,
        "category": _safe_record_lookup_value(record.get("category"), 120),
        "province": _safe_record_lookup_value(record.get("province"), 100),
        "issued_date": _safe_record_lookup_value(record.get("issued_date"), 20),
        "source_reference": _safe_record_lookup_value(record.get("source_reference"), 180),
    }


def _record_lookup_bullet(record):
    details = []
    if record.get("registration_no"):
        details.append(f"registration {record['registration_no']}")
    if record.get("practitioner_number"):
        details.append(f"practitioner {record['practitioner_number']}")
    if record.get("record_type"):
        details.append(record["record_type"])
    if record.get("record_year"):
        details.append(f"year {record['record_year']}")
    if record.get("category"):
        details.append(record["category"])
    if record.get("province"):
        details.append(record["province"])
    if record.get("source_reference"):
        details.append(f"source {record['source_reference']}")
    name = record.get("full_name") or f"Registry record #{record.get('id') or 'unknown'}"
    return f"Record #{record.get('id') or 'unknown'} - {name}: {'; '.join(details) or 'authorised record summary available.'}"[:520]


def _staff_record_lookup_answer(user, lookup, scope):
    """Return a fast, read-only, model-free response for a narrow staff lookup."""
    result = search_staff_registry_records_for_user(
        user,
        query=lookup["query"],
        record_type=lookup["record_type"],
        target_model=lookup["target_model"],
        year=lookup["year"],
        limit=5,
    )
    result_scope = result.get("scope") or scope or "restricted"
    result_scope_label = result.get("scope_label") or _scope_label(result_scope)
    if result.get("status") != "ok":
        return {
            "title": "Live Registry Lookup Restricted",
            "answer": "This account is not authorised for live registry record lookup.",
            "bullets": [
                "The staff assistant will not search private records without an authorised staff scope.",
                "Use the applicable Records Hub workflow after the required staff access is approved.",
            ],
            "links": [("Records Hub", "records_home"), ("Open Full Assistant", "staff_ai_assistant")],
            "suggestions": _chat_suggestions_for_scope(scope),
            "sources": [{
                "label": "Staff record-lookup access policy",
                "detail": "Live record retrieval is read-only and limited to the signed-in staff role and office.",
                "url": reverse("records_home"),
            }],
            "record_lookup": {
                "status": "denied",
                "scope": result_scope,
                "scope_label": result_scope_label,
                "query": lookup["query"],
                "records": [],
                "redactions": ["date_of_birth", "contact_details", "full_address", "raw_payload", "payment_amounts"],
            },
            "_skip_live_model": True,
        }

    safe_records = [
        _safe_staff_record_lookup_record(record)
        for record in result.get("records") or []
    ]
    try:
        total_matches = max(0, int(result.get("total_matches") or 0))
    except (TypeError, ValueError):
        total_matches = 0
    record_sources = [{
        "label": "Live scoped registry lookup",
        "detail": (
            f"Read-only active registry search in {result_scope_label}; results are restricted to the signed-in staff role and office."
        ),
        "url": reverse("records_home"),
    }]
    for record in safe_records[:5]:
        record_sources.append({
            "label": f"Registry record #{record.get('id') or 'unknown'}",
            "detail": record.get("source_reference") or "Live, role-scoped registry record.",
            "url": record.get("record_url") or reverse("records_home"),
        })

    lookup_payload = {
        "status": "ok",
        "scope": result_scope,
        "scope_label": result_scope_label,
        "query": lookup["query"],
        "trigger": lookup["trigger"],
        "total_matches": total_matches,
        "returned": len(safe_records),
        "records": safe_records,
        "redactions": ["date_of_birth", "contact_details", "full_address", "raw_payload", "payment_amounts"],
    }
    if not safe_records:
        return {
            "title": "No Authorised Registry Record Found",
            "answer": (
                f"No active registry record matched '{lookup['query']}' in your {result_scope_label} scope. "
                "I did not broaden the search to another office, archived records, or private fields."
            ),
            "bullets": [
                "Check the spelling or use the exact registration or practitioner number.",
                "Open the Records Hub to follow the approved review process if a record may be archived or needs correction.",
                "This is decision support only; a registrar must verify the official record before acting.",
            ],
            "links": [("Records Hub", "records_home"), ("Registry Archives", "registry_archive")],
            "suggestions": [
                "Look up an exact registration number.",
                "What should I review before approving an applicant?",
            ],
            "sources": record_sources,
            "record_lookup": lookup_payload,
            "_skip_live_model": True,
        }

    record_links = [
        (f"Open record #{record.get('id') or 'unknown'}", record["record_url"])
        for record in safe_records
        if record.get("record_url")
    ]
    record_links.append(("Records Hub", "records_home"))
    matching_label = "record" if len(safe_records) == 1 else "records"
    extra_match_note = ""
    if total_matches > len(safe_records):
        extra_match_note = f" Showing the first {len(safe_records)} of {total_matches}; refine with an exact registration number if needed."
    return {
        "title": "Authorised Registry Record Lookup",
        "answer": (
            f"I found {len(safe_records)} authorised active registry {matching_label} matching '{lookup['query']}' "
            f"in your {result_scope_label} scope.{extra_match_note}"
        ),
        "bullets": [
            *[_record_lookup_bullet(record) for record in safe_records],
            "The summary is read-only and excludes date of birth, contact details, full addresses, raw import payloads, and payment amounts.",
            "Verify the linked official record and complete the registrar workflow before any decision or change.",
        ][:7],
        "links": record_links,
        "suggestions": [
            "Look up another exact registration number.",
            "What should I check before approving an applicant?",
        ],
        "sources": record_sources,
        "record_lookup": lookup_payload,
        "_skip_live_model": True,
    }


def _question_requests_sensitive_record_data(question_lower):
    return any(token in question_lower for token in SENSITIVE_RECORD_REQUEST_TOKENS)


FAST_STAFF_ASSISTANT_PROMPTS = (
    "what should i review first",
    "review priorities",
    "do we have missing data",
    "missing data to clear",
    "missing data that blocks approvals",
    "missing data that needs follow-up",
    "which report should i generate",
    "which report should i send",
    "report should i generate",
    "pending applications to clear",
    "how many pending applications",
    "how many duplicate records",
    "duplicate records need review",
    "how do i handle duplicate records",
    "what was the latest import",
    "where did the latest data come from",
    "what should i check before approving",
    "check before approving an applicant",
    "how do i use the import tools safely",
    "how do i review scanned documents",
    "what is the total for",
    "current total for",
    "what can i ask in this assistant",
    "role-based privacy controls",
    "which records are in my current office scope",
)

NURSING_WORKFORCE_INTELLIGENCE_TOKENS = (
    "workforce intelligence",
    "workforce distribution",
    "province distribution",
    "nursing shortage",
    "nursing shortages",
    "nurse shortage",
    "nurse shortages",
    "staffing gap",
    "staffing gaps",
    "facility staffing",
    "retirement outlook",
    "retire in",
    "retirement",
    "age analysis",
    "age group",
    "under 35",
    "under-35",
    "younger than 35",
    "rural facilities",
    "rural facility",
)
MEDICAL_REGULATION_INTELLIGENCE_TOKENS = (
    "specialist distribution",
    "specialty distribution",
    "specialist coverage",
    "cardiologist",
    "cardiologists",
    "facility accreditation",
    "accreditation status",
    "clinical privilege",
    "clinical privileges",
    "credential verification",
    "verified credentials",
)

# These phrases deliberately select the local, aggregate-only forecasting
# service before a general workforce answer or generation-model request.  The
# forecast service has a bounded ten-year horizon and returns a data gap when
# its governed source coverage is insufficient.
WORKFORCE_FORECAST_TOKENS = (
    "workforce forecast",
    "workforce prediction",
    "retirement forecast",
    "retirement projection",
    "shortage forecast",
    "shortage prediction",
    "projected shortage",
    "project future",
    "predict future",
    "next 10 years",
    "next ten years",
)
REGULATORY_ML_FORECAST_CACHE_PREFIX = "staff-ai:regulatory-ml-forecast:v1"


def _question_is_fast_staff_assistant_prompt(question_lower):
    return any(token in question_lower for token in FAST_STAFF_ASSISTANT_PROMPTS)


def _question_requests_nursing_workforce_intelligence(question_lower):
    return any(token in question_lower for token in NURSING_WORKFORCE_INTELLIGENCE_TOKENS)


def _question_requests_workforce_forecast(question_lower):
    return any(token in question_lower for token in WORKFORCE_FORECAST_TOKENS)


def _question_requests_rural_under_35_workforce(question_lower):
    """Recognise the joined workforce measure before generic age handling."""
    has_rural_term = "rural" in question_lower
    has_age_term = any(
        token in question_lower
        for token in ("under 35", "under-35", "younger than 35")
    )
    return has_rural_term and has_age_term


def _question_requests_medical_regulation_intelligence(question_lower):
    return any(token in question_lower for token in MEDICAL_REGULATION_INTELLIGENCE_TOKENS) or bool(
        re.search(
            r"\b[a-z]+(?:ologist|ologists|iatrist|iatrists|surgeon|surgeons|physician|physicians)\b",
            question_lower,
        )
    )


def _regulatory_ml_forecast_context(scope):
    """Return a short-lived, aggregate-only local forecast for an AI scope.

    The cache key intentionally contains no user, practitioner, facility, or
    question information.  The underlying service is local and read-only; a
    configured cache simply keeps repeated Staff AI planning questions fast.
    """

    if not bool(getattr(settings, "REGULATORY_ML_ENABLED", True)):
        return None

    try:
        horizon = int(getattr(settings, "REGULATORY_ML_FORECAST_HORIZON_YEARS", 10) or 10)
    except (TypeError, ValueError):
        horizon = 10
    cache_key = f"{REGULATORY_ML_FORECAST_CACHE_PREFIX}:{scope}:{horizon}"
    cached = cache.get(cache_key)
    if isinstance(cached, dict):
        return cached

    try:
        from apps.dashboard.workforce_forecasting import build_workforce_forecast_context

        kwargs = {"horizon_years": horizon}
        # Supply an empty context for the other office rather than allowing a
        # scoped user request to fetch that office's aggregate intelligence.
        if scope == "nursing":
            from apps.dashboard.nursing_intelligence import build_nursing_workforce_intelligence_context

            kwargs["nursing_context"] = build_nursing_workforce_intelligence_context()
            kwargs["medical_context"] = {}
        elif scope == "medical":
            from apps.dashboard.medical_intelligence import build_medical_board_intelligence_context

            kwargs["nursing_context"] = {}
            kwargs["medical_context"] = build_medical_board_intelligence_context()
        elif scope != "all":
            return None
        forecast = build_workforce_forecast_context(**kwargs)
    except Exception:
        # Forecasting is an optional decision-support enhancement.  A
        # temporary analytics issue must never prevent the established Staff
        # AI safety or workflow guidance from responding.
        return None

    timeout = max(0, int(getattr(settings, "REGULATORY_ML_CACHE_SECONDS", 300) or 0))
    if timeout:
        cache.set(cache_key, forecast, timeout)
    return forecast


def _workforce_forecast_sources(scope):
    sources = []
    if scope in {"all", "nursing"}:
        sources.append({
            "label": "Nursing Council workforce forecast",
            "detail": "Local, read-only aggregate retirement and approved-target staffing planning signals; human review required.",
            "url": reverse("nursing_council_portal") + "#regulatory-ml-forecast",
        })
    if scope in {"all", "medical"}:
        sources.append({
            "label": "Medical Board workforce planning readiness",
            "detail": "Local, read-only aggregate planning readiness; shortage claims are withheld until approved need baselines and longitudinal data exist.",
            "url": reverse("medical_board_portal") + "#regulatory-ml-forecast",
        })
    return sources


def _nursing_workforce_forecast_answer(forecast, question_lower):
    nursing = (forecast or {}).get("nursing") or {}
    retirement = nursing.get("retirement_projection") or {}
    shortage = nursing.get("approved_target_shortage_risk") or {}
    horizon = (forecast or {}).get("horizon_years") or 10

    if any(token in question_lower for token in ("shortage", "staffing gap", "staffing", "risk")):
        if shortage.get("available"):
            answer = (
                f"The current approved-target Nursing staffing signal is {shortage.get('risk_level', 'unavailable').upper()} across "
                f"{shortage.get('approved_target_row_count', 0)} displayed governed target row(s): "
                f"{shortage.get('displayed_gap', 0)} reported gap against {shortage.get('displayed_target', 0)} approved positions."
            )
            bullets = [
                "This is a current aggregate planning signal, not a future staffing forecast or a national total.",
                f"Displayed gap ratio: {round(float(shortage.get('displayed_gap_ratio') or 0) * 100, 1)}%.",
                "Only rows with an explicit approved staffing target are included; no facility, professional, or workplace identity is returned here.",
            ]
        else:
            answer = (
                "A Nursing shortage prediction is not available because the current governed aggregate view lacks sufficient valid approved staffing-target evidence. "
                "I will not infer a target, rural need, or national shortage from observed workforce counts."
            )
            bullets = list(shortage.get("data_quality_reasons") or [])[:3]
            bullets.append("Record and approve staffing targets through the governing workforce process before relying on a gap signal.")
        title = "Nursing Approved-Target Staffing Signal"
    elif retirement.get("available"):
        answer = (
            f"For the configured {horizon}-year planning horizon, the governed Nursing Council age-band analysis gives a retirement-eligibility cohort range of "
            f"{retirement.get('projection_lower_bound')} to {retirement.get('projection_upper_bound')} active practitioners. "
            "It is not a count of people who will definitely retire."
        )
        bullets = [
            f"Age coverage: {retirement.get('age_coverage_percent')}% of the active-practitioner denominator ({retirement.get('known_age_count')} governed age observations).",
            f"Configured retirement age: {retirement.get('retirement_age')}; confidence: {retirement.get('confidence')}.",
            "The local cohort method does not model migration, new graduates, return-to-work, mortality, or policy changes.",
            "No names, dates of birth, registration numbers, facilities, or individual work histories are used or returned.",
        ]
        title = "Nursing Workforce Retirement Planning Range"
    else:
        answer = (
            "A Nursing retirement projection is not available because governed aggregate age coverage or age-band consistency is insufficient. "
            "I will not estimate retirements from names, registration numbers, or unverified source rows."
        )
        bullets = list(retirement.get("data_quality_reasons") or [])[:3]
        bullets.extend([
            "Load and review governed aggregate age evidence through the approved data-quality workflow.",
            "Use the cited Nursing Council workspace for current metrics; no staffing, employment, or registration action is automated.",
        ])
        title = "Nursing Workforce Forecast Data Gap"

    return {
        "title": title,
        "answer": answer,
        "bullets": bullets[:7],
        "links": [("Nursing Workforce Forecast", reverse("nursing_council_portal") + "#regulatory-ml-forecast")],
        "suggestions": [
            "Show the Nursing workforce distribution with sources.",
            "What data-quality reviews are needed before using a staffing gap?",
        ],
        "sources": _workforce_forecast_sources("nursing"),
        "_skip_live_model": True,
    }


def _medical_workforce_forecast_answer(forecast):
    medical = (forecast or {}).get("medical") or {}
    readiness = medical.get("planning_readiness") or {}
    baseline = readiness.get("aggregate_baseline") or {}
    if readiness.get("available"):
        answer = (
            "A Medical Board shortage prediction is intentionally not issued from the current governed data. "
            f"The available aggregate baseline is {baseline.get('active_practitioners', 0)} active practitioners and "
            f"{baseline.get('specialists', 0)} specialist profiles."
        )
        bullets = [
            str(readiness.get("reason") or "An approved need baseline and longitudinal aggregate snapshots are required before forecasting."),
            "Specialty distribution is not converted into a service-availability or shortage claim without an approved population denominator and establishment target.",
            "No credential, privilege, complaint, disciplinary, or individual practitioner information is used in this planning response.",
        ]
        title = "Medical Board Workforce Forecast Readiness"
    else:
        answer = (
            "Medical Board workforce forecasting is not currently available because governed aggregate planning inputs are not ready. "
            "I will not substitute a model-generated estimate or unscoped registry search."
        )
        bullets = [
            str(readiness.get("reason") or "Load approved aggregate Medical Board planning data before forecasting."),
            "Use the Medical Board clinical-regulation workspace to verify current aggregate metrics and sources.",
        ]
        title = "Medical Board Forecast Data Gap"
    return {
        "title": title,
        "answer": answer,
        "bullets": bullets[:7],
        "links": [("Medical Board Workforce Planning", reverse("medical_board_portal") + "#regulatory-ml-forecast")],
        "suggestions": [
            "Show Medical Board specialist distribution with sources.",
            "What approved inputs are needed before a Medical Board shortage forecast?",
        ],
        "sources": _workforce_forecast_sources("medical"),
        "_skip_live_model": True,
    }


def _all_office_workforce_forecast_answer(forecast):
    nursing = (forecast or {}).get("nursing", {}).get("retirement_projection", {})
    medical = (forecast or {}).get("medical", {}).get("planning_readiness", {})
    nursing_line = (
        f"Nursing Council: retirement-eligibility planning range {nursing.get('projection_lower_bound')} to {nursing.get('projection_upper_bound')} over the configured horizon."
        if nursing.get("available")
        else "Nursing Council: no retirement projection is issued until governed aggregate age coverage is sufficient."
    )
    medical_line = (
        f"Medical Board: {medical.get('aggregate_baseline', {}).get('active_practitioners', 0)} active practitioners in the available aggregate baseline; no shortage claim is issued."
        if medical.get("available")
        else "Medical Board: planning forecast readiness is unavailable pending governed aggregate inputs."
    )
    return {
        "title": "Separate Regulatory Workforce Forecasts",
        "answer": (
            "This all-office planning response keeps Nursing Council workforce forecasting and Medical Board clinical-regulation planning separate. "
            "It does not merge records, make a cross-office operational decision, or create a national shortage claim."
        ),
        "bullets": [
            nursing_line,
            medical_line,
            "Both outputs are local, aggregate-only decision support and require source review before a Board, staffing, licensing, or policy action.",
        ],
        "links": [
            ("Nursing Workforce Forecast", reverse("nursing_council_portal") + "#regulatory-ml-forecast"),
            ("Medical Board Workforce Planning", reverse("medical_board_portal") + "#regulatory-ml-forecast"),
        ],
        "suggestions": _chat_suggestions_for_scope("all"),
        "sources": _workforce_forecast_sources("all"),
        "_skip_live_model": True,
    }


def _workforce_forecast_answer(scope, question_lower):
    forecast = _regulatory_ml_forecast_context(scope)
    if forecast is None:
        return {
            "title": "Regulatory ML Forecasting Unavailable",
            "answer": (
                "The local aggregate workforce forecasting service is currently disabled or unavailable. "
                "Use the cited governed workspace for current operational metrics; no prediction will be generated as a fallback."
            ),
            "bullets": [
                "Forecasting is optional, local, aggregate-only, and never required for a registration, licensing, credential, accreditation, staffing, or disciplinary decision.",
                "An authorised operator can enable or restore the bounded service after reviewing its configuration and source readiness.",
            ],
            "links": _chat_links_for_scope(scope),
            "suggestions": _chat_suggestions_for_scope(scope),
            "sources": _source_defaults(scope),
            "_skip_live_model": True,
        }
    if scope == "nursing":
        return _nursing_workforce_forecast_answer(forecast, question_lower)
    if scope == "medical":
        return _medical_workforce_forecast_answer(forecast)
    if "nurs" in question_lower or "atp" in question_lower or "midwi" in question_lower:
        return _nursing_workforce_forecast_answer(forecast, question_lower)
    if any(token in question_lower for token in ("medical", "doctor", "specialist", "chw")):
        return _medical_workforce_forecast_answer(forecast)
    return _all_office_workforce_forecast_answer(forecast)


def _province_staffing_gap_rows(facility_rows):
    """Aggregate only displayed, approved-target facility gaps by province.

    This deliberately reports planning signals from source rows that carry an
    approved staffing target.  It must not be presented as proof of an entire
    province's need or service availability.
    """

    grouped = {}
    for row in facility_rows or []:
        if row.get("gap_status") != "reported":
            continue
        try:
            gap = max(0, int(row.get("gap") or 0))
            observed = max(0, int(row.get("observed_staff_count") or 0))
            target = max(0, int(row.get("staffing_target") or 0))
        except (TypeError, ValueError):
            # A malformed aggregate row cannot support a shortage signal.
            continue
        if gap <= 0:
            continue
        province = _compact_record_lookup_text(row.get("province"), max_length=100) or "Province not captured"
        aggregate = grouped.setdefault(province, {
            "province": province,
            "facility_count": 0,
            "observed_staff_count": 0,
            "staffing_target": 0,
            "gap": 0,
        })
        aggregate["facility_count"] += 1
        aggregate["observed_staff_count"] += observed
        aggregate["staffing_target"] += target
        aggregate["gap"] += gap
    return sorted(
        grouped.values(),
        key=lambda row: (-row["gap"], -row["staffing_target"], row["province"]),
    )


def _nursing_workforce_intelligence_answer(question_lower):
    """Answer a bounded workforce-analysis question from cached aggregate data."""

    from apps.dashboard.nursing_intelligence import build_nursing_workforce_intelligence_context

    intelligence = build_nursing_workforce_intelligence_context()
    practitioner = intelligence["practitioner_status"]
    age = intelligence["age_and_retirement"]
    facility = intelligence["facility_staffing"]
    province_rows = intelligence["province_distribution"]["rows"]
    sources = [{
        "label": "Nursing Workforce Intelligence",
        "detail": "Aggregate-only Nursing Council metrics from governed registry, snapshot, and approved workplace sources.",
        "url": reverse("nursing_council_portal") + "#nursing-workforce-intelligence",
    }]

    if _question_requests_rural_under_35_workforce(question_lower):
        rural_measure = intelligence.get("rural_under_35_measure") or {}
        if rural_measure.get("available") and rural_measure.get("count") is not None:
            answer = (
                f"The governed Nursing Council aggregate measure reports {rural_measure['count']} nurses under 35 working in facilities "
                "with an approved rural classification."
            )
            bullets = [
                "The result is aggregate-only and relies on approved age, current-employment, and rural/urban facility classifications.",
                "Do not use this planning signal as an automatic staffing, employment, or registration decision.",
            ]
        else:
            answer = (
                "A reliable count of nurses under 35 working in rural facilities is not available from the current governed Nursing Council sources. "
                "I will not infer rural status from a province, district, facility name, or facility level."
            )
            bullets = [
                rural_measure.get("note") or (
                    "Load a governed rural/urban facility classification linked to approved age and current-employment evidence before calculating this measure."
                ),
                "The assistant does not join individual age and workplace records or expose individual dates of birth.",
                "Use a reviewed aggregate report once the missing classification and linkage have been approved.",
            ]
        title = "Nursing Rural Under-35 Workforce Measure"
    elif any(token in question_lower for token in ("retire", "retirement", "age analysis", "age group", "under 35", "under-35", "younger than 35")):
        if not age["available"]:
            answer = (
                "A reliable Nursing Council age or retirement count is not available because valid governed age evidence has not been loaded. "
                "I will not infer age from names, registration numbers, or unverified data."
            )
            bullets = [age["note"], "Load and verify appropriate age data through the approved data-quality process before using retirement planning figures."]
        else:
            answer = (
                f"The aggregate Nursing Council analysis shows {age['retirement_within_five_years_count']} professionals within five years of the configured retirement age "
                f"and {age['retirement_age_or_older_count']} at or above that age, based on {age['known_age_count']} valid age observations."
            )
            bullets = [
                *[f"Age {row['band']}: {row['count']} professionals." for row in age["age_band_rows"]],
                "This is an aggregate planning signal; it does not expose individual dates of birth or make retirement decisions.",
            ]
        title = "Nursing Workforce Retirement Outlook"
    elif (
        any(token in question_lower for token in ("nursing shortage", "nursing shortages", "nurse shortage", "nurse shortages"))
        and any(token in question_lower for token in ("province", "provinces"))
    ):
        province_gaps = _province_staffing_gap_rows(facility["rows"])
        if not province_gaps:
            answer = (
                "No province staffing signal can be shown because the current Nursing Council view has no displayed facility gaps "
                "backed by approved staffing targets. Observed registry counts are not treated as a province shortage."
            )
            bullets = [
                facility["note"],
                "Record and approve facility staffing targets before using the dashboard to identify province-level planning signals.",
            ]
        else:
            answer = (
                f"I found {len(province_gaps)} province{'s' if len(province_gaps) != 1 else ''} represented in displayed facility staffing gaps "
                "backed by approved targets. These are planning signals, not a determination that an entire province is short staffed."
            )
            bullets = [
                (
                    f"{row['province']}: {row['observed_staff_count']} observed / {row['staffing_target']} approved target / "
                    f"gap {row['gap']} across {row['facility_count']} displayed facility "
                    f"{'row' if row['facility_count'] == 1 else 'rows'}."
                )
                for row in province_gaps[:6]
            ]
            bullets.append(
                "Only facility rows with an explicit approved staffing target are included; a missing province is not evidence that it has no workforce need."
            )
        title = "Nursing Province Staffing Signals"
    elif any(token in question_lower for token in (
        "staffing gap", "staffing gaps", "facility staffing", "rural facilit",
        "nursing shortage", "nursing shortages", "nurse shortage", "nurse shortages",
    )):
        reported_gaps = [row for row in facility["rows"] if row.get("gap_status") == "reported"]
        if not reported_gaps:
            answer = (
                "No approved Nursing Council facility staffing target is available for a reliable gap calculation. "
                "Observed workforce counts are not treated as an establishment requirement."
            )
            bullets = [facility["note"], "Record approved facility staffing targets before using the dashboard for gap prioritisation."]
        else:
            answer = (
                f"I found {len(reported_gaps)} displayed facility staffing signal{'s' if len(reported_gaps) != 1 else ''} with approved targets. "
                "The largest reported gaps are listed below."
            )
            bullets = [
                f"{row['facility']} ({row['province'] or 'province not captured'}): {row['observed_staff_count']} observed / {row['staffing_target']} target / gap {row['gap']}."
                for row in reported_gaps[:5]
            ]
            if "rural" in question_lower:
                bullets.append("Rural/urban classification is not inferred; load a governed facility geography classification before reporting a rural-only total.")
        title = "Nursing Facility Staffing Signals"
    else:
        answer = (
            f"The Nursing Council aggregate intelligence has {practitioner['active_practitioner_count']} active registry profile{'s' if practitioner['active_practitioner_count'] != 1 else ''} "
            f"and {practitioner['atp_current_person_count']} current ATP person record{'s' if practitioner['atp_current_person_count'] != 1 else ''} "
            f"for the {practitioner['atp_current_year'] or 'available'} cycle."
        )
        bullets = [
            *[f"{row['province']}: {row['count']} aggregate current-ATP people." for row in province_rows[:6]],
            f"Renewal due within {practitioner['renewal_due_within_days']} days where expiry is captured: {practitioner['renewal_due_count']}.",
            "Use the Nursing Council workspace filters and cited governed sources before taking any staffing or registration action.",
        ]
        title = "Nursing Workforce Intelligence"

    return {
        "title": title,
        "answer": answer,
        "bullets": bullets[:7],
        "links": [("Nursing Workforce Intelligence", reverse("nursing_council_portal") + "#nursing-workforce-intelligence")],
        "suggestions": [
            "For Nursing Council, list the checks before approving an ATP renewal, with sources.",
            "What Nursing Council data-quality reviews should I clear before reporting?",
        ],
        "sources": sources,
        "_skip_live_model": True,
    }


def _medical_regulation_intelligence_answer(question_lower):
    """Answer a bounded clinical-regulation question from aggregate Medical data."""

    from apps.dashboard.medical_intelligence import (
        build_medical_board_intelligence_context,
        resolve_medical_board_aggregate_filters,
    )

    # Resolve query wording only against the dashboard's governed aggregate
    # filter labels.  This is not a person/record search, and an ambiguous
    # province or specialty must produce a data-gap response instead of a
    # guessed count.
    base_intelligence = build_medical_board_intelligence_context()
    filter_resolution = resolve_medical_board_aggregate_filters(
        question_lower,
        base_intelligence.get("medical_intelligence_filter_options"),
    )
    has_unresolved_regional_specialty_request = (
        filter_resolution["specialty_requested"]
        and filter_resolution["geography_requested"]
        and (filter_resolution["unresolved_specialty"] or filter_resolution["unresolved_geography"])
    )
    intelligence = (
        build_medical_board_intelligence_context(filter_resolution["filters"])
        if filter_resolution["filters"] and not has_unresolved_regional_specialty_request
        else base_intelligence
    )
    metrics = intelligence["medical_executive_metrics"]
    specialty_rows = intelligence["medical_specialty_distribution"]
    province_rows = intelligence["medical_province_distribution"]
    accreditation = intelligence["medical_facility_accreditation"]
    credentials = intelligence["medical_credential_evidence"]
    privileges = intelligence["medical_clinical_privileges"]
    sources = [{
        "label": "Medical Board Clinical Regulation Intelligence",
        "detail": "Aggregate-only Medical Board practitioner, specialty, facility, credential, and privilege metrics.",
        "url": reverse("medical_board_portal") + "#medical-workforce-intelligence",
    }]

    medical_state = intelligence.get("medical_intelligence") or {}
    if not medical_state.get("available", True):
        return {
            "title": "Medical Board Intelligence Data Gap",
            "answer": (
                "I cannot provide a reliable Medical Board aggregate count because the governed intelligence data is not ready. "
                "I will not substitute a zero, an unscoped record search, or a model-generated estimate."
            ),
            "bullets": [
                str(medical_state.get("status") or "Medical Board registry intelligence is unavailable."),
                "Apply the pending registry migrations and load approved Medical Board records before relying on this analysis.",
                "Use the cited workspace to verify readiness; no clinical, registration, credential, or facility decision is automated.",
            ],
            "links": [("Medical Board Clinical Regulation Intelligence", reverse("medical_board_portal") + "#medical-workforce-intelligence")],
            "suggestions": _chat_suggestions_for_scope("medical"),
            "sources": sources,
            "_skip_live_model": True,
        }

    geographic_filters = filter_resolution["geographic_filters"]
    if has_unresolved_regional_specialty_request:
        missing = []
        if filter_resolution["unresolved_specialty"]:
            missing.append("specialty")
        if filter_resolution["unresolved_geography"]:
            missing.append("province, district, or facility")
        return {
            "title": "Medical Specialist Intelligence Data Gap",
            "answer": (
                "I cannot give an exact regional specialist count because the requested "
                f"{' and '.join(missing)} does not match a governed Medical Board aggregate filter. "
                "I will not guess from free-text locations or incomplete profile data."
            ),
            "bullets": [
                "Use the Medical Board dashboard's recorded specialty and province, district, or facility filters, then ask the focused question again.",
                "A zero or missing match must not be treated as proof that a clinician or service is unavailable.",
                "Specialty is distinct from verified credentials and an approved clinical privilege.",
            ],
            "links": [("Medical Board Clinical Regulation Intelligence", reverse("medical_board_portal") + "#medical-workforce-intelligence")],
            "suggestions": [
                "How many Cardiology specialist profiles match Western Province, with sources?",
                "Show Medical Board specialist distribution with sources.",
            ],
            "sources": sources,
            "_skip_live_model": True,
        }

    if filter_resolution["specialty_requested"]:
        selected_specialty = filter_resolution["filters"].get("specialty")
        if geographic_filters:
            geography_label = ", ".join(geographic_filters.values())
            specialty_label = f"{selected_specialty} " if selected_specialty else ""
            if metrics["specialists"]:
                answer = (
                    f"The governed Medical Board aggregate registry has {metrics['specialists']} "
                    f"{specialty_label}specialist profile{'s' if metrics['specialists'] != 1 else ''} "
                    f"matching {geography_label}."
                )
            else:
                answer = (
                    f"No {specialty_label}specialist profile currently matches the governed geography filter for {geography_label}. "
                    "This is a zero matching profile-evidence result, not proof that a clinical service is unavailable."
                )
            province_bullets = [
                f"{row['label']}: {row['practitioner_count']} matching specialist profile{'s' if row['practitioner_count'] != 1 else ''}."
                for row in province_rows[:6]
            ]
            bullets = [
                *province_bullets,
                (
                    "Province-only matching uses a current Medical Board workplace province where recorded, "
                    "or the professional profile's recorded province; it does not prove current service availability."
                    if set(geographic_filters) == {"province"}
                    else "District and facility matching uses current Medical Board workplace evidence only; it does not prove service availability."
                ),
                "Specialty is separate from an approved clinical privilege and verified credential decision.",
            ]
            title = "Medical Regional Specialist Intelligence"
        elif selected_specialty:
            answer = (
                f"The Medical Board aggregate registry currently reports {metrics['specialists']} {selected_specialty} "
                f"specialist profile{'s' if metrics['specialists'] != 1 else ''}. "
                "Specialty is separate from an approved clinical privilege."
            )
            bullets = [
                *[
                    f"{row['label']}: {row['practitioner_count']} matching specialist profile{'s' if row['practitioner_count'] != 1 else ''}."
                    for row in province_rows[:8]
                ],
                "Province rows show profile or current-workplace evidence only; do not infer service availability from incomplete profile data.",
            ]
            title = "Medical Specialist Intelligence"
        else:
            answer = (
                f"The Medical Board aggregate register currently reports {metrics['specialists']} specialist profile{'s' if metrics['specialists'] != 1 else ''}. "
                "Specialty is separate from an approved clinical privilege."
            )
            bullets = [
                *[f"{row['label']}: {row['practitioner_count']} specialist profile{'s' if row['practitioner_count'] != 1 else ''}." for row in specialty_rows[:8]],
                "Use the Medical Board dashboard filters for province, district, facility, sector, and gender; do not infer service availability from incomplete profile data.",
            ]
            title = "Medical Specialist Intelligence"
    elif any(token in question_lower for token in ("facility accreditation", "accreditation status")):
        answer = (
            f"There are {accreditation['registered_facility_count']} current accredited or conditional facility record{'s' if accreditation['registered_facility_count'] != 1 else ''} "
            f"in the Medical Board aggregate view. Source: {accreditation['source']}."
        )
        bullets = [
            accreditation["metric_definition"],
            f"Pending accreditation workflow items: {accreditation['pending_application_count']}.",
            "Facility accreditation remains a reviewable Board decision; this assistant does not approve a facility.",
        ]
        title = "Medical Facility Accreditation Intelligence"
    elif any(token in question_lower for token in ("clinical privilege", "clinical privileges", "credential verification", "verified credentials")):
        answer = (
            f"The aggregate Medical Board view has {credentials['verified_credential_records']} verified credential record{'s' if credentials['verified_credential_records'] != 1 else ''} "
            f"and {privileges['active_privilege_count']} current dedicated clinical privilege record{'s' if privileges['active_privilege_count'] != 1 else ''}."
        )
        bullets = [
            credentials["note"],
            privileges["note"],
            "Clinical privileges are never inferred from specialty or an uploaded document; an explicit approved privilege record is required.",
        ]
        title = "Medical Credential and Clinical Privilege Intelligence"
    else:
        answer = (
            f"The Medical Board aggregate workspace reports {metrics['registered_doctors']} registered doctors, "
            f"{metrics['active_practitioners']} active practitioners, {metrics['pending_renewals']} pending renewals, and "
            f"{metrics['open_disciplinary_cases']} open disciplinary case{'s' if metrics['open_disciplinary_cases'] != 1 else ''}."
        )
        bullets = [
            "Use the clinical regulation dashboard filters for specialty, province, district, facility, sector, and gender.",
            "These are aggregate decision-support metrics; private complaint, disciplinary, and practitioner identities are not included.",
        ]
        title = "Medical Board Clinical Regulation Intelligence"

    return {
        "title": title,
        "answer": answer,
        "bullets": bullets[:7],
        "links": [("Medical Board Clinical Regulation Intelligence", reverse("medical_board_portal") + "#medical-workforce-intelligence")],
        "suggestions": [
            "For Medical Board, list the checks before approving a doctor or CHW application, with sources.",
            "What Medical Board data-quality reviews should I clear before reporting?",
        ],
        "sources": sources,
        "_skip_live_model": True,
    }


def _all_office_intelligence_comparison_answer():
    """Give an admin an aggregate comparison without blending office records."""

    from apps.dashboard.medical_intelligence import build_medical_board_intelligence_context
    from apps.dashboard.nursing_intelligence import build_nursing_workforce_intelligence_context

    nursing = build_nursing_workforce_intelligence_context()
    medical = build_medical_board_intelligence_context()
    return {
        "title": "Separate Regulatory Intelligence Comparison",
        "answer": (
            "This is an aggregate all-office comparison. Nursing Council workforce planning and Medical Board clinical regulation remain "
            "separate regulatory workspaces; the figures must not be merged into one operational approval or private-record search."
        ),
        "bullets": [
            f"Nursing Council: {nursing['practitioner_status']['active_practitioner_count']} active registry profiles and {nursing['practitioner_status']['atp_current_person_count']} current ATP people.",
            f"Medical Board: {medical['medical_executive_metrics']['registered_doctors']} registered doctors and {medical['medical_executive_metrics']['specialists']} specialist profiles.",
            "Nursing analysis is workforce-focused (ATP, pathways, distribution, age and staffing signals).",
            "Medical analysis is clinical-regulation-focused (registration, specialty, credential, facility accreditation, clinical privileges and public safety).",
            "Open the separate cited workspace before making an office-specific decision.",
        ],
        "links": [
            ("Nursing Workforce Intelligence", reverse("nursing_council_portal") + "#nursing-workforce-intelligence"),
            ("Medical Clinical Regulation Intelligence", reverse("medical_board_portal") + "#medical-workforce-intelligence"),
        ],
        "sources": [
            {
                "label": "Nursing Workforce Intelligence",
                "detail": "Aggregate-only governed Nursing Council workforce metrics.",
                "url": reverse("nursing_council_portal") + "#nursing-workforce-intelligence",
            },
            {
                "label": "Medical Board Clinical Regulation Intelligence",
                "detail": "Aggregate-only governed Medical Board regulation metrics.",
                "url": reverse("medical_board_portal") + "#medical-workforce-intelligence",
            },
        ],
        "suggestions": _chat_suggestions_for_scope("all"),
        "_skip_live_model": True,
    }


def staff_ai_question_needs_knowledge_search(question):
    question_lower = " ".join(str(question or "").strip().lower().split())
    if not question_lower:
        return False
    # Exact staff record searches are answered from the role-scoped database
    # path below.  They should not wait for RAG or a generation-model round
    # trip, and their record data must never be handed to a model.
    if _explicit_staff_record_lookup(question_lower):
        return False
    if _question_requests_workforce_forecast(question_lower):
        return False
    if _question_requests_nursing_workforce_intelligence(question_lower):
        return False
    if _question_requests_medical_regulation_intelligence(question_lower):
        return False
    if _question_is_platform_scope_question(question_lower) or _question_is_assistant_intro(question_lower):
        return False
    if _question_is_fast_staff_assistant_prompt(question_lower):
        return False
    return not any(
        token in question_lower
        for token in ("remember", "what did i ask", "earlier", "last question", "previous")
    )


def _assistant_intro_answer(user, context):
    ai_provider = context.get("ai_provider") or {}
    rag_detail = ai_provider.get("rag_detail") or "Knowledge search follows the platform configuration."
    user_label = _staff_user_label(user)
    return {
        "title": context["agent_label"],
        "answer": (
            f"I am the {context['agent_label']} for the PNG Regulatory Bodies Online Platform. "
            f"{user_label}, I answer staff questions inside your authorised {context['scope_label']} scope and guide you to the right workflow, report, record, import, or review screen."
        ),
        "bullets": [
            f"Current AI mode: {ai_provider.get('label', 'Local assistant')}.",
            rag_detail,
            "I can explain platform records and workflows, but I do not approve applications, issue licences, merge records, or change data for you.",
        ],
        "links": _chat_links_for_scope(context["scope"]),
        "suggestions": [
            "What should I review first today?",
            "What can I ask in this assistant?",
            "Which report should I generate for management?",
        ],
        "_skip_live_model": True,
    }


def _platform_scope_answer(user, context):
    scope = context["scope"]
    user_label = _staff_user_label(user)
    ai_provider = context.get("ai_provider") or {}
    if scope == "medical":
        title = "Medical Board Platform Scope"
        answer = (
            f"{user_label}, you are signed in within the Medical Board scope. "
            "This platform area supports Medical Board staff work for doctors, specialists, CHWs, medical applications, facilities, payments, documents, reviews, and management reporting."
        )
        bullets = [
            "Medical Board records stay separate from Nursing Council nurse, midwife, nurse aide, graduand, ATP, and Nursing Council analytics records.",
            "Use this assistant for Medical Board workflow guidance, screening priorities, missing-data reviews, duplicate checks, documents, receipts, and reports.",
            "The assistant can explain where to work, but it cannot approve applications, issue registrations, alter payments, or change live records.",
            f"Current AI mode: {ai_provider.get('label', 'Local assistant')}.",
        ]
        links = [("Medical Board Portal", "medical_board_portal"), ("Medical Staff Workspace", "medical_staff_portal"), ("Review Centre", "review_centre")]
        suggestions = [
            "Explain the Medical Board workflow",
            "What should Medical Board staff review first?",
            "Which Medical Board report should I generate?",
        ]
    elif scope == "all":
        title = "All Regulatory Offices Platform Scope"
        answer = (
            f"{user_label}, you are signed in with all-office access. "
            "This platform connects Nursing Council and Medical Board operations while keeping each office's records, workflows, analytics, and reports separated in the assistant answer."
        )
        bullets = [
            "Nursing Council scope covers nurses, midwives, nurse aides, graduands, provisional-to-full pathways, ATP renewals, Nursing Council analytics, and nursing imports.",
            "Medical Board scope covers doctors, specialists, CHWs, medical facilities, medical applications, Medical Board receipts, documents, and reports.",
            "Board governance remains a separate Nursing Council Board portal and does not expose operational applicant or registry records.",
            f"Current AI mode: {ai_provider.get('label', 'Local assistant')}.",
        ]
        links = [("Nursing Council Portal", "nursing_council_portal"), ("Medical Board Portal", "medical_board_portal"), ("Review Centre", "review_centre")]
        suggestions = [
            "Explain Nursing Council scope",
            "Explain Medical Board scope",
            "How are office records separated?",
        ]
    else:
        title = "Nursing Council Platform Scope"
        answer = (
            f"{user_label}, you are signed in within the Nursing Council scope. "
            "This platform area supports Nursing Council work for register verification, provisional-to-full pathways, ATP renewals, nursing practitioners, recognised schools, imports, data quality, standards, and reporting."
        )
        bullets = [
            "Nursing Council records stay separate from Medical Board doctor, specialist, CHW, facility, and medical application records.",
            "Use this assistant for Nursing Council workflow guidance, screening priorities, missing-data reviews, duplicate checks, imports, analytics, documents, receipts, and reports.",
            "Nursing Council Board governance is a separate board portal and does not expose operational applicant or registry records to board users.",
            f"Current AI mode: {ai_provider.get('label', 'Local assistant')}.",
        ]
        links = [("Nursing Council Portal", "nursing_council_portal"), ("Nursing Forms", "nursing_forms_portal"), ("Review Centre", "review_centre")]
        suggestions = [
            "Explain NC1, NC2, and NC3",
            "What should Nursing Council staff review first?",
            "How does ATP renewal fit in this platform?",
        ]
    return {
        "title": title,
        "answer": answer,
        "bullets": bullets,
        "links": links,
        "suggestions": suggestions,
        "_skip_live_model": True,
    }


def _source_defaults(scope):
    sources = [
        {
            "label": "Scoped platform counts",
            "detail": "Live counts are filtered by the user's role, regulatory office scope, and registry archive exclusions.",
            "url": "",
        },
        {
            "label": "Registry Archives",
            "detail": "Old-age, lapsed-renewal, inactive, retired, and deceased-review records excluded from active totals.",
            "url": reverse("registry_archive"),
        }
    ]
    if scope in {"all", "nursing"}:
        sources.append({
            "label": "Nursing Council analytics snapshot",
            "detail": "Active lifecycle snapshot and practitioner index.",
            "url": reverse("nursing_council_portal"),
        })
        sources.append({
            "label": "Nursing Council pathway and cadre workbooks",
            "detail": "Current cleansed Nursing Council licence, cadre, dashboard, and template guideline sources.",
            "url": reverse("nursing_council_portal"),
        })
    if scope in {"all", "medical"}:
        sources.append({
            "label": "Medical Board scoped workspace",
            "detail": "Medical Board doctor, specialist, CHW, facility, and medical workflow records.",
            "url": reverse("medical_board_portal"),
        })
    return sources


def _with_sources(response, sources):
    response["sources"] = serialize_sources([*(response.get("sources") or []), *sources])
    return response


def _finalize_staff_ai_response(response, verified_sources):
    """Attach sources selected by the platform, never unverified model citations."""
    response["sources"] = serialize_sources(verified_sources)
    response["citations_verified"] = bool(response["sources"])
    response["decision_support_notice"] = DECISION_SUPPORT_NOTICE
    return response


def _redacted_record_lookup_persistence(question, response):
    """Avoid retaining individual lookup queries or results in AI chat history.

    The immediate, authorised response can show a minimal record summary, but
    assistant conversations and feedback must not become a second registry or
    a source of raw record data for later review.  Preserve an audit-friendly
    generic event only; the official Records Hub remains the record system.
    """

    lookup = response.get("record_lookup") or {}
    if not lookup:
        return question, response

    scope_label = _safe_record_lookup_value(lookup.get("scope_label"), 80) or "authorised"
    persistence_response = {
        "title": response.get("title") or "Authorised Registry Record Lookup",
        "answer": (
            f"An authorised individual registry lookup was completed in {scope_label} scope. "
            "The individual query and result were intentionally not retained in assistant chat history."
        ),
        "bullets": [
            "Open the official Records Hub to verify the live record before taking any action.",
            "Assistant feedback remains subject to redaction and human review; it is not used for automatic training.",
        ],
        "links": [{"label": "Records Hub", "url": reverse("records_home")}],
        "sources": [{
            "label": "Staff record-lookup retention safeguard",
            "detail": "Individual registry lookup queries and result details are excluded from assistant conversation history.",
            "url": reverse("records_home"),
        }],
        "record_lookup_redacted": True,
        "model_generated": False,
        "decision_support_notice": DECISION_SUPPORT_NOTICE,
    }
    return "Authorised registry record lookup (details redacted from assistant history).", persistence_response


def _build_local_staff_ai_chat_response(user, question, *, conversation=None, browser_session_key=""):
    cleaned = " ".join((question or "").strip().split())
    scope = _staff_scope(user)
    context = _quick_staff_ai_context(user, scope)
    base_sources = _source_defaults(scope)
    if not cleaned:
        return _with_sources(_default_staff_ai_answer(user, context), base_sources)

    question_lower = cleaned.lower()
    fast_local_prompt = _question_is_fast_staff_assistant_prompt(question_lower)
    if _question_is_platform_scope_question(question_lower):
        return _with_sources(_platform_scope_answer(user, context), base_sources)

    if _question_is_assistant_intro(question_lower):
        return _with_sources(_assistant_intro_answer(user, context), base_sources)

    cross_scope = detect_cross_scope_question(scope, question_lower)
    if cross_scope.get("detected"):
        return _with_sources({
            "title": "Office Scope Boundary",
            "answer": cross_scope["message"],
            "bullets": [
                f"Your current assistant scope is {context['scope_label']}.",
                "Use the correct registrar workspace or ask a system admin for authorised cross-office access.",
                "The assistant will not combine Nursing Council and Medical Board private data in a single office-scoped answer.",
            ],
            "links": [("Open Full Assistant", "staff_ai_assistant")],
            "suggestions": [
                f"What can I ask in {context['scope_label']} scope?",
                "Explain role-based privacy controls",
                "Which records are in my current office scope?",
            ],
            "_skip_live_model": True,
        }, base_sources)

    if _question_requests_sensitive_record_data(question_lower):
        return _with_sources({
            "title": "Private Record Protection",
            "answer": (
                "I cannot provide private record data such as dates of birth, contact details, full addresses, raw import payloads, or payment amounts. "
                "Use the authorised record workspace and the applicable staff approval process instead."
            ),
            "bullets": [
                "The assistant only uses role-scoped, read-only data and redacts sensitive personal and financial fields.",
                "A registrar must verify any operational record through the approved platform screen before making a decision.",
                "Feedback and evaluation data are reviewed and redacted before any human-led quality analysis; they are not used for automatic training.",
            ],
            "links": [("Open Full Assistant", "staff_ai_assistant"), ("Repository Search", "repository_search")],
            "suggestions": _chat_suggestions_for_scope(scope),
            "_skip_live_model": True,
        }, base_sources)

    record_lookup = _explicit_staff_record_lookup(cleaned)
    if record_lookup:
        return _staff_record_lookup_answer(user, record_lookup, scope)

    workforce_forecast_requested = _question_requests_workforce_forecast(question_lower)
    nursing_intelligence_requested = _question_requests_nursing_workforce_intelligence(question_lower)
    medical_intelligence_requested = _question_requests_medical_regulation_intelligence(question_lower)
    # These aggregate fast paths are still office-scoped.  Do not let an
    # otherwise generic phrase such as "credential verification" or
    # "retirement outlook" bypass the normal cross-office wording detector.
    if medical_intelligence_requested and scope == "nursing":
        return _with_sources({
            "title": "Office Scope Boundary",
            "answer": (
                "Medical Board clinical-regulation intelligence is not available in Nursing Council scope. "
                "Use an authorised Medical Board workspace; I will not query or combine that office's data here."
            ),
            "bullets": [
                "Nursing Council staff can use Nursing workforce, pathway, ATP, and data-quality intelligence in this assistant.",
                "Medical specialist, credential, clinical-privilege, and facility-accreditation metrics remain Medical Board-only.",
            ],
            "links": [("Open Full Assistant", "staff_ai_assistant")],
            "suggestions": _chat_suggestions_for_scope(scope),
            "_skip_live_model": True,
        }, base_sources)
    if nursing_intelligence_requested and scope == "medical":
        return _with_sources({
            "title": "Office Scope Boundary",
            "answer": (
                "Nursing Council workforce intelligence is not available in Medical Board scope. "
                "Use an authorised Nursing Council workspace; I will not query or combine that office's data here."
            ),
            "bullets": [
                "Medical Board staff can use clinical-regulation, specialist, credential, privilege, and facility-accreditation intelligence in this assistant.",
                "Nursing workforce, ATP, pathway, and retirement metrics remain Nursing Council-only.",
            ],
            "links": [("Open Full Assistant", "staff_ai_assistant")],
            "suggestions": _chat_suggestions_for_scope(scope),
            "_skip_live_model": True,
        }, base_sources)
    if workforce_forecast_requested:
        return _with_sources(_workforce_forecast_answer(scope, question_lower), base_sources)
    if scope == "all" and nursing_intelligence_requested and medical_intelligence_requested:
        return _with_sources(_all_office_intelligence_comparison_answer(), base_sources)
    if scope in {"all", "nursing"} and nursing_intelligence_requested and not medical_intelligence_requested:
        return _with_sources(_nursing_workforce_intelligence_answer(question_lower), base_sources)
    if scope in {"all", "medical"} and medical_intelligence_requested and not nursing_intelligence_requested:
        return _with_sources(_medical_regulation_intelligence_answer(question_lower), base_sources)

    if any(token in question_lower for token in ("remember", "what did i ask", "earlier", "last question", "previous")):
        memory_rows = assistant_memory_rows(
            assistant_kind="staff_assistant",
            user=user,
            browser_session_key=browser_session_key,
            scope=scope,
        )
        context["assistant_memory"] = memory_rows
        history = recent_assistant_history(conversation)
        history_lines = [
            f"{item['role']}: {item['content']}"
            for item in history[-6:]
        ]
        if not history_lines and memory_rows:
            history_lines = [row["text"] for row in memory_rows]
        if history_lines:
            return _with_sources({
                "title": "Assistant Memory",
                "answer": "I can use the recent assistant conversation for continuity within your authorised scope.",
                "bullets": history_lines[:6],
                "links": [("Open Full Assistant", "staff_ai_assistant")],
                "suggestions": [
                    "Show lapsed renewal review candidates",
                    "Do we have missing data that needs follow-up?",
                    "Which report should I generate for management?",
                ],
            }, base_sources + [{
                "label": "Assistant conversation memory",
                "detail": "Recent messages stored in the platform assistant conversation log.",
                "url": "",
            }])
        return _with_sources({
            "title": "Assistant Memory",
            "answer": "I do not have earlier conversation context for this assistant session yet.",
            "bullets": ["Ask a question in this session and I will keep the recent context for follow-up questions."],
            "links": [("Open Full Assistant", "staff_ai_assistant")],
            "suggestions": CHAT_SUGGESTIONS,
        }, base_sources)

    context = build_staff_ai_context(user, detailed=False)
    if _question_is_facility_breakdown_question(question_lower):
        return _with_sources(_facility_breakdown_answer(context, scope), base_sources)

    retrieval_sources = []
    if scope in {"all", "nursing"} and any(
        token in question_lower
        for token in (
            "cadre",
            "cadres",
            "cadre breakdown",
            "qualification",
            "dataflow",
            "data flow",
            "cleaned licence",
            "cleaned license",
            "integrated dashboard",
            "pathway",
            "provisional",
            "full licence",
            "full license",
            "authority to practice",
            "atp",
            "nc1",
            "nc2",
            "nc3",
            "nc4",
            "nc5",
            "nc8",
            "nc9",
            "lapsed",
            "relapsed",
            "stopped renewing",
            "not renewing",
            "deceased",
            "inactive",
            "old nurses",
        )
    ):
        retrieval_sources = retrieve_assistant_sources(question=cleaned, scope=scope, public=False)
        base_sources = _source_defaults(scope) + retrieval_sources
        context["assistant_retrieval_sources"] = retrieval_sources

    lapsed_summary = None
    if scope in {"all", "nursing"} and any(token in question_lower for token in ("lapsed", "relapsed", "deceased", "inactive", "stopped renewing", "old nurses", "atp 2026")):
        lapsed_summary = lapsed_renewal_assistant_summary()
        context["lapsed_renewal_summary"] = lapsed_summary.get("summary", "")
        base_sources += lapsed_summary.get("sources", [])
    if scope in {"all", "nursing"}:
        context["nursing_pathway_context"] = nursing_pathway_context()
        context["nursing_cadre_context"] = nursing_cadre_dataflow_context(limit=12)

    if scope == "all" and any(
        token in question_lower for token in ("medical board", "doctor", "chw", "medical workflow")
    ) and any(
        token in question_lower for token in ("nursing council", "nurse", "atp", "nc1", "nc2", "nc3")
    ):
        return _with_sources({
            "title": "Authorised Cross-Office Workflow Comparison",
            "answer": (
                "As an all-office admin, you can compare the Nursing Council and Medical Board workflows, but each office's "
                "records, approvals, reports, and operational decisions remain separate. Use the source links for the relevant office before acting."
            ),
            "bullets": [
                "Nursing Council: confirm the applicable NC pathway, linked practitioner record, required evidence, data-quality reviews, and registrar approval before an ATP or licence decision.",
                "Medical Board: confirm the doctor or CHW pathway, linked practitioner record, required evidence, data-quality reviews, and Medical Board registrar approval before a registration decision.",
                "Do not merge Nursing Council and Medical Board totals or private record details in a single office decision; produce each office report from its authorised workspace.",
            ],
            "links": [
                ("Nursing Council Portal", "nursing_council_portal"),
                ("Medical Board Portal", "medical_board_portal"),
                ("Review Centre", "review_centre"),
            ],
            "suggestions": _chat_suggestions_for_scope(scope),
            "_skip_live_model": True,
        }, base_sources)

    if scope in {"all", "nursing"} and "atp" in question_lower and any(
        token in question_lower for token in ("approve", "approval", "check", "review")
    ):
        return _with_sources({
            "title": "ATP Renewal Approval Checks",
            "answer": (
                "Before a registrar approves an ATP renewal, verify the applicant is in the authorised Nursing Council pathway, "
                "the practitioner record is correctly linked, required payment evidence and supporting documents are present, "
                "and there are no unresolved missing-data or duplicate-review warnings."
            ),
            "bullets": [
                "Confirm the correct Nursing Council applicant and ATP renewal pathway before reviewing the file.",
                "Check the linked practitioner record, registration details, required documents, and payment evidence in the authorised workspace.",
                "Clear or document missing-data and duplicate-review flags before final registrar approval.",
                "Verify the cited source documents and retain the final decision in the platform; this assistant does not approve or issue a licence.",
            ],
            "links": [("Open Screening Queue", "staff_ai_assistant"), ("Nursing Forms", "nursing_forms_portal")],
            "suggestions": [
                "Explain NC1, NC2, and NC3 with sources.",
                "Do we have missing data that blocks approvals?",
                "Which Nursing Council report should I generate for management?",
            ],
            "_skip_live_model": True,
        }, base_sources)

    if _question_is_archive_filter_question(question_lower):
        archive_summary = archive_assistant_summary(scope)
        base_sources += archive_summary.get("sources", [])
        return _with_sources({
            "title": "Registry Archive Filter",
            "answer": (
                f"The {context['scope_label']} archive filter currently excludes {archive_summary['total']} records from active totals. "
                "It separates old-age, lapsed-renewal, retired, inactive, and deceased-review records into the Registry Archives table while keeping the source records available for audit."
            ),
            "bullets": [
                *archive_summary.get("bullets", [])[:5],
                f"Current archive year: {current_archive_year()}.",
                "Possible deceased matches stay review-required until the registrar confirms the deceased notification evidence.",
            ][:7],
            "links": [("Registry Archives", "registry_archive"), ("Records Hub", "records_home"), ("Review Centre", "review_centre")],
            "suggestions": [
                "Show archived lapsed renewals",
                "Filter archives by year",
                "What active totals are archive-aware?",
            ],
            "_skip_live_model": True,
        }, base_sources)

    if scope in {"all", "nursing"} and not any(
        token in question_lower
        for token in ("lapsed", "relapsed", "stopped renewing", "not renewing", "deceased", "inactive", "old nurses", "1960", "1970", "1980", "1990")
    ) and any(
        token in question_lower
        for token in (
            "cadre",
            "cadres",
            "cadre breakdown",
            "qualification",
            "dataflow",
            "data flow",
            "cleaned licence",
            "cleaned license",
            "integrated dashboard",
            "pathway",
            "provisional",
            "full licence",
            "full license",
            "authority to practice",
            "atp",
            "nc1",
            "nc2",
            "nc3",
            "nc4",
            "nc5",
            "nc8",
            "nc9",
        )
    ):
        pathway_context = context.get("nursing_pathway_context") or nursing_pathway_context()
        answer_payload = nursing_cadre_answer_payload(context)
        pathway_lines = [
            f"{row['primary_form_code']} - {row['pathway_name']} creates {row['creates_licence_type'] or 'supporting workflow'}"
            for row in pathway_context.get("pathways", [])[:6]
        ]
        dataflow_steps = (context.get("nursing_cadre_context") or {}).get("dataflow_steps", [])[:3]
        return _with_sources({
            "title": "Nursing Cadre Pathway And Dataflow",
            "answer": answer_payload["answer"],
            "bullets": [
                *(answer_payload.get("bullets") or [])[:4],
                *pathway_lines[:3],
                *dataflow_steps[:2],
            ][:8],
            "links": [("Nursing Council Portal", "nursing_council_portal"), ("Nursing Forms", "nursing_forms_portal")],
            "suggestions": [
                "Explain NC1, NC2, and NC3",
                "Which cadres are unclassified for review?",
                "How does ATP relate to renewal?",
            ],
            "_skip_live_model": True,
        }, base_sources)

    if scope in {"all", "nursing"} and any(
        token in question_lower
        for token in ("lapsed", "relapsed", "stopped renewing", "not renewing", "deceased", "inactive", "old nurses", "1960", "1970", "1980", "1990")
    ):
        lapsed_context = lapsed_renewal_review_context(limit=5)
        cards = {card["label"]: card["value"] for card in lapsed_context.get("nursing_lapsed_cards", [])}
        risk_rows = lapsed_context.get("nursing_lapsed_risk_rows", [])
        risk_text = [f"{row['label']}: {row['count']}" for row in risk_rows[:4]]
        candidate_rows = lapsed_context.get("nursing_lapsed_candidate_rows", [])
        sample_text = [
            f"{row['name']} ({row['registration_nos'] or 'no registration number'}), first {row['first_year'] or 'unknown'}, latest {row['latest_year'] or 'unknown'}"
            for row in candidate_rows[:3]
        ]
        return _with_sources({
            "title": "Lapsed Renewal Review",
            "answer": (
                f"The Nursing Council index shows {cards.get('Not current ATP 2026', 0)} people are not current in the 2026 ATP set. "
                f"{cards.get('Current ATP 2026', 0)} are current ATP 2026 records. Treat possible deceased matches as review candidates only."
            ),
            "bullets": [
                *risk_text,
                *(sample_text or ["Open the Nursing Council portal to review the candidate table."]),
            ][:6],
            "links": [("Nursing Council Portal", "nursing_council_portal"), ("Review Centre", "review_centre")],
            "suggestions": [
                "Show me high priority lapsed records",
                "What should the registrar verify before marking deceased?",
                "Which decade has the oldest records?",
            ],
            "_skip_live_model": True,
        }, base_sources)

    latest_import = _latest_import_summary(scope)
    live_stats = _current_live_statistics(scope)
    metric_label, metric_value = _find_registry_metric(question_lower, live_stats)
    if metric_label and any(token in question_lower for token in ("total", "how many", "count", "number of", "current")):
        source_note = "This is a direct live registry count after excluding Registry Archives records from active totals."
        if metric_label == "Midwives":
            source_note = "This is counted live from the `Midwife` registry table after Registry Archives exclusions."
        elif metric_label == "Registered Nurses":
            source_note = "This is counted live from the `NursingProfessional` registry table after Registry Archives exclusions."
        elif metric_label == "Nurse Aides":
            source_note = "This is counted live from the `NurseAide` registry table after Registry Archives exclusions."
        elif metric_label == "Graduands":
            source_note = "This is counted live from the `HealthStudent` registry table after Registry Archives exclusions."
        elif metric_label == "Medical Doctors":
            source_note = "This is counted live from the `MedicalDoctor` registry table after Registry Archives exclusions."
        elif metric_label == "Community Health Workers":
            source_note = "This is counted live from the `CommunityHealthWorker` registry table after Registry Archives exclusions."

        latest_import_text = "No completed import batch is currently recorded in your scope."
        if live_stats["latest_import"]:
            latest_import_text = (
                f"The latest completed import source is {live_stats['latest_import']['source_file_name']} "
                f"with completion recorded after processing {live_stats['latest_import']['processed_rows']} rows."
            )

        return {
            "title": f"Current {metric_label} Total",
            "answer": f"The current total for {metric_label.lower()} is {metric_value}.",
            "bullets": [
                source_note,
                latest_import_text,
                "If you need the management version, generate the monthly report or open the live statistics screen.",
            ],
            "links": _chat_links_for_scope(context["scope"]) + [("Monthly PDF Report", "export_monthly_analytics_pdf")],
            "suggestions": [
                "Where did the latest data come from?",
                "Which report should I generate for management?",
                "How many pending applications do I need to review?",
            ],
            "_skip_live_model": True,
        }

    if any(token in question_lower for token in ("employed", "unemployed", "employment")) and any(
        token in question_lower for token in ("total", "how many", "count", "number of", "current")
    ):
        employment = live_stats["employment"]
        return {
            "title": "Current Employment Totals",
            "answer": (
                f"The current live employment totals are {employment['employed']} employed, "
                f"{employment['unemployed']} unemployed, from {employment['total']} employment records."
            ),
            "bullets": [
                "These totals come from the EmploymentRecord table.",
                "If the totals are low or zero, it means employment records have not yet been fully populated electronically.",
                "Use this carefully in management reporting and explain whether the employment module is fully populated.",
            ],
            "links": [("Monthly PDF Report", "export_monthly_analytics_pdf"), ("Open Full Assistant", "staff_ai_assistant")],
            "suggestions": [
                "What is the total for Midwives?",
                "Where did the latest data come from?",
                "Which report should I generate for management?",
            ],
            "_skip_live_model": True,
        }

    if _question_is_source_question(question_lower):
        if latest_import:
            completed_label = latest_import["batch"].completed_at.strftime("%d %b %Y") if latest_import["batch"].completed_at else "Not captured"
            return {
                "title": "Latest Source Import",
                "answer": (
                    f"The latest data in your current scope came from {latest_import['source_file_name']}. "
                    f"The most recent completed import was recorded on {completed_label}."
                ),
                "bullets": [
                    f"Source kind: {latest_import['source_kind']}.",
                    f"Processed rows: {latest_import['processed_rows']} of {latest_import['total_rows']}.",
                    f"Duplicate candidates detected in that batch: {latest_import['duplicates_detected']}.",
                ],
                "links": [("Open Bulk Import", "import_data"), ("Monthly PDF Report", "export_monthly_analytics_pdf"), ("Open Full Assistant", "staff_ai_assistant")],
                "suggestions": [
                    "What is the total for Midwives?",
                    "Which report should I generate for management?",
                    "Do we have pending applications to clear first?",
                ],
                "_skip_live_model": True,
            }
        return {
            "title": "Latest Source Import",
            "answer": "No completed import batch is currently recorded in your scope, so there is no captured latest source file yet.",
            "bullets": [
                "Use Bulk Import to load the next workbook or CSV source.",
                "After import, return to the AI assistant to see the updated source and screening summary.",
            ],
            "links": [("Open Bulk Import", "import_data"), ("Open Full Assistant", "staff_ai_assistant")],
            "suggestions": [
                "How do I use the import tools safely?",
                "Which report should I generate for management?",
                "What is the total for Midwives?",
            ],
            "_skip_live_model": True,
        }

    intents = [
        (
            "Screening And Approvals",
            ("screening", "approve", "approval", "pending", "application", "review", "applicant"),
        ),
        (
            "Missing Data Follow-Up",
            ("missing data", "incomplete", "missing fields", "fix data", "follow up", "correction"),
        ),
        (
            "Duplicate Records",
            ("duplicate", "same person", "duplicate review", "duplicate records", "merge"),
        ),
        (
            "Imports And Data Alignment",
            ("import", "workbook", "excel", "csv", "upload data", "cleanse", "alignment"),
        ),
        (
            "Reports And Briefs",
            ("report", "monthly", "yearly", "brief", "minister", "statistics", "analytics", "management report"),
        ),
        (
            "Document Review And OCR",
            ("document", "ocr", "receipt", "repository", "pdf", "scan", "supporting documents"),
        ),
        (
            "Role Access And Privacy",
            ("access", "privacy", "role", "who can view", "medical board", "nursing council", "scope"),
        ),
    ]

    best_title, best_keywords = max(intents, key=lambda item: _score_staff_question(question_lower, item[1]))

    if best_title == "Screening And Approvals":
        return {
            "title": best_title,
            "answer": (
                f"You currently have {context['pending_application_count']} pending applications in {context['scope_label']}. "
                "Before approval, confirm the applicant record is linked correctly, payment evidence is attached, supporting documents exist, and no missing-data review is still open."
            ),
            "bullets": [
                "Start with the Applicant Screening Queue in the AI assistant.",
                "If the file has no receipt, no documents, or an open missing-data review, follow up before approving it.",
                "Use Staff Inbox & Chat if you need to request corrections or clarification.",
            ],
            "links": [("Open Screening Queue", "staff_ai_assistant"), ("Staff Inbox & Chat", "staff_communications")],
            "suggestions": [
                "Do we have missing data that blocks approvals?",
                "How many duplicate records need review?",
                "Which report should I send to management?",
            ],
            "_skip_live_model": fast_local_prompt,
        }

    if best_title == "Missing Data Follow-Up":
        return {
            "title": best_title,
            "answer": (
                f"There are {context['missing_review_count']} active missing-data reviews in your current scope. "
                "These should be checked before final approval so incomplete records do not flow into live statistics and reports."
            ),
            "bullets": [
                "Review the top missing fields inside the AI assistant.",
                "Use Staff Inbox & Chat to request corrections from the right office or applicant.",
                "Run the missing-data audit after new imports or large updates.",
            ],
            "links": [("Open Full Assistant", "staff_ai_assistant"), ("Staff Inbox & Chat", "staff_communications")],
            "suggestions": [
                "What should I check before approving an applicant?",
                "How do I handle duplicate records?",
                "What was the latest import batch?",
            ],
            "_skip_live_model": fast_local_prompt,
        }

    if best_title == "Duplicate Records":
        return {
            "title": best_title,
            "answer": (
                f"There are {context['duplicate_review_count']} duplicate-review items in your current scope. "
                "These need review so one person is not counted twice across imports, applications, or reports."
            ),
            "bullets": [
                "Check duplicate candidates before publishing management statistics.",
                "Compare registration numbers, names, and attached documents before deciding a record is truly duplicated.",
                "Use repository search and workforce records to confirm the correct source record.",
            ],
            "links": [("Duplicate Review Workflow", "duplicate_review_workflow"), ("Repository Search", "repository_search")],
            "suggestions": [
                "Do we have missing data that needs follow-up?",
                "How many pending applications do I need to review?",
                "Which report should I generate for management?",
            ],
            "_skip_live_model": fast_local_prompt,
        }

    if best_title == "Imports And Data Alignment":
        import_note = "No completed import batch is currently recorded in your scope."
        if latest_import:
            import_note = (
                f"The latest completed import is {latest_import['source_file_name']} with "
                f"{latest_import['processed_rows']} processed rows and {latest_import['duplicates_detected']} duplicate candidates."
            )
        return {
            "title": best_title,
            "answer": (
                f"{import_note} Use Bulk Import for new workbook loads, then check the AI assistant for screening, missing-data, and duplicate signals before relying on the refreshed totals."
            ),
            "bullets": [
                "Import first, then review duplicate and missing-data warnings.",
                "After major loads, generate monthly or yearly reports again so statistics reflect the latest data.",
                "Use the repository and OCR tools for supporting files that arrive as scans or PDFs.",
            ],
            "links": [("Open Bulk Import", "import_data"), ("Open Full Assistant", "staff_ai_assistant")],
            "suggestions": [
                "Which report should I generate for management?",
                "What should I check before approving an applicant?",
                "How do I review scanned documents?",
            ],
            "_skip_live_model": fast_local_prompt,
        }

    if best_title == "Reports And Briefs":
        brief_name = "Nursing Council Live Statistics" if context["scope"] == "nursing" else "AI Staff Assistant"
        return {
            "title": best_title,
            "answer": (
                "Use the monthly reports for current operational reporting, yearly reports for broader trends, and the Minister or Registrar brief when leadership needs a formatted summary. "
                f"For your role, {brief_name} is also available as a live reference screen."
            ),
            "bullets": [
                "Generate reports after imports and data-quality reviews, not before.",
                "Monthly reports are best for recent live counts, receipts, applications, and import status.",
                "Brief documents are better for management reading packs and executive updates.",
            ],
            "links": _chat_links_for_scope(context["scope"]) + [("Monthly PDF Report", "export_monthly_analytics_pdf")],
            "suggestions": [
                "Where did the latest data come from?",
                "Do we have pending applications to clear first?",
                "How do I use the import tools safely?",
            ],
            "_skip_live_model": fast_local_prompt,
        }

    if best_title == "Document Review And OCR":
        return {
            "title": best_title,
            "answer": (
                f"There are {context['document_review_count']} draft repository documents in your current scope. "
                "Use repository search to review uploaded files, and use the OCR import tools when receipts or forms arrive as scanned PDFs."
            ),
            "bullets": [
                "Repository Search is where staff review document records.",
                "OCR import is useful for scanned receipts, forms, and other paper records.",
                "Supporting documents should be present before final approval where the form requires them.",
            ],
            "links": [("Repository Search", "repository_search"), ("PDF Document Import", "ocr_import"), ("Open Full Assistant", "staff_ai_assistant")],
            "suggestions": [
                "What should I check before approving an applicant?",
                "Do we have missing data that needs follow-up?",
                "How many duplicate records need review?",
            ],
            "_skip_live_model": fast_local_prompt,
        }

    return {
        "title": "Role Access And Privacy",
        "answer": (
            f"Your current access is scoped to {context['scope_label']}. The staff assistant follows the same role and office boundaries as the rest of the platform, so Nursing Council staff do not use Medical Board-only data and Medical Board staff do not use Nursing Council-only data."
        ),
        "bullets": [
            "Admin users can work across both regulatory offices.",
            "Registrar users are limited to their own office scope.",
            "Applicants keep using the separate AI Helpdesk and do not get staff-assistant access.",
        ],
        "links": [("My Profile", "user_profile"), ("Open Full Assistant", "staff_ai_assistant")],
        "suggestions": [
            "How many pending applications do I need to review?",
            "Which report should I generate for management?",
            "How do I handle duplicate records?",
        ],
        "_skip_live_model": fast_local_prompt,
    }


def build_staff_ai_chat_response(user, question, *, session_id="", browser_session_key="", persist=True):
    scope = _staff_scope(user)
    conversation = None
    if persist:
        conversation, _created = get_or_create_assistant_conversation(
            session_id=session_id,
            assistant_kind="staff_assistant",
            user=user,
            browser_session_key=browser_session_key,
            scope=scope or "restricted",
            role=getattr(user, "role", ""),
        )
    # Route before any specialised response branch.  The supervisor returns a
    # declarative policy contract only; it does not execute a query or model.
    # A restricted contract prevents a direct caller from reaching a local
    # record, analytics, or retrieval path. A cross-office contract still
    # reaches the established local boundary response, which stops before any
    # cross-office lookup and explains the correct workspace to use.
    regulatory_ai_route = build_regulatory_ai_tool_contract(question, user)
    if (
        regulatory_ai_route.get("status") == "blocked"
        and regulatory_ai_route.get("scope") == "restricted"
    ):
        local_response = {
            "title": "Regulatory AI Access Boundary",
            "answer": regulatory_ai_route.get("routing_reason") or (
                "This account is not authorised to use the Regulatory AI staff assistant for this request."
            ),
            "bullets": [
                "No registry record, document, analytics, model, or workflow tool was called.",
                "Use an approved staff account in the correct regulatory workspace or ask an administrator to review access.",
            ],
            "links": [],
            "suggestions": [],
            "sources": [],
            "_skip_live_model": True,
        }
    else:
        local_response = _build_local_staff_ai_chat_response(
            user,
            question,
            conversation=conversation,
            browser_session_key=browser_session_key,
        )
    local_response["regulatory_ai_route"] = regulatory_ai_route
    local_response["links"] = _serialize_chat_links(local_response.get("links", []))
    if local_response.get("_skip_live_model"):
        local_response["ai_provider"] = ai_provider_status()
        local_response.pop("_skip_live_model", None)
        local_response["model_generated"] = False
        _finalize_staff_ai_response(local_response, local_response.get("sources") or _source_defaults(scope))
        local_response["session_id"] = conversation.session_id if conversation else ""
        if persist:
            persistence_question, persistence_response = _redacted_record_lookup_persistence(question, local_response)
            assistant_message = record_assistant_turn(
                conversation=conversation,
                question=persistence_question,
                response=persistence_response,
                assistant_kind="staff_assistant",
                user=user,
                browser_session_key=browser_session_key,
                scope=scope,
            )
            local_response["assistant_message_id"] = assistant_message.id if assistant_message else None
        return local_response

    if not local_response.get("sources"):
        retrieval_sources = retrieve_assistant_sources(question=question, scope=scope, public=False)
        local_response["sources"] = serialize_sources(
            _source_defaults(scope) + retrieval_sources
        )
    else:
        retrieval_sources = None

    context = build_staff_ai_context(user, detailed=False)
    context["assistant_memory"] = assistant_memory_rows(
        assistant_kind="staff_assistant",
        user=user,
        browser_session_key=browser_session_key,
        scope=scope,
    )
    if retrieval_sources is None:
        retrieval_sources = retrieve_assistant_sources(question=question, scope=scope, public=False)
    context["assistant_retrieval_sources"] = retrieval_sources
    context["regulatory_ai_route"] = regulatory_ai_route
    if scope in {"all", "nursing"}:
        context["lapsed_renewal_summary"] = lapsed_renewal_assistant_summary().get("summary", "")
        context["nursing_pathway_context"] = nursing_pathway_context()
        context["nursing_cadre_context"] = nursing_cadre_dataflow_context(limit=12)
    response = maybe_generate_live_staff_response(user, question, context, local_response)
    # Model output cannot change the platform-selected supervisor route or
    # expand its declared tool contract.
    response["regulatory_ai_route"] = regulatory_ai_route
    response["links"] = _serialize_chat_links(response.get("links", []))
    _finalize_staff_ai_response(response, local_response.get("sources") or _source_defaults(scope))
    response["session_id"] = conversation.session_id if conversation else ""
    if persist:
        assistant_message = record_assistant_turn(
            conversation=conversation,
            question=question,
            response=response,
            assistant_kind="staff_assistant",
            user=user,
            browser_session_key=browser_session_key,
            scope=scope,
        )
        response["assistant_message_id"] = assistant_message.id if assistant_message else None
    return response
