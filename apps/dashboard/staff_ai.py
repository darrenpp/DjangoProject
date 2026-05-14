from collections import Counter
from datetime import date
from difflib import SequenceMatcher

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db.models import Count, Q, Subquery

from apps.common.models import DuplicateReviewQueue
from apps.dashboard.access import (
    MEDICAL_BOARD_FORM_CODES,
    MEDICAL_BOARD_PROFESSIONAL_MODELS,
    NURSING_COUNCIL_PROFESSIONAL_MODELS,
    is_medical_board_staff,
    is_nursing_council_staff,
)
from apps.dashboard.ai_provider import ai_provider_status, maybe_generate_live_staff_response
from apps.dashboard.models import Receipt
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


def _registry_rows_for_scope(scope):
    if scope == "medical":
        return [
            ("Medical Doctors", MedicalDoctor.objects.count()),
            ("Community Health Workers", CommunityHealthWorker.objects.count()),
        ]
    if scope == "all":
        return [
            ("Registered Nurses", NursingProfessional.objects.count()),
            ("Midwives", Midwife.objects.count()),
            ("Nurse Aides", NurseAide.objects.count()),
            ("Graduands", HealthStudent.objects.count()),
            ("Medical Doctors", MedicalDoctor.objects.count()),
            ("Community Health Workers", CommunityHealthWorker.objects.count()),
        ]
    return [
        ("Registered Nurses", NursingProfessional.objects.count()),
        ("Midwives", Midwife.objects.count()),
        ("Nurse Aides", NurseAide.objects.count()),
        ("Graduands", HealthStudent.objects.count()),
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
        "chat_suggestions": CHAT_SUGGESTIONS,
        "action_rows": ACTION_ROWS,
        "ai_provider": ai_provider_status(),
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
    cache.set(cache_key, context, STAFF_AI_CACHE_TIMEOUT)
    return context


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
    ]
    if scope == "nursing":
        links.append(("Nursing Council Live Statistics", "nursing_regulatory_alignment"))
    return links


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
        "suggestions": CHAT_SUGGESTIONS,
    }


def _build_local_staff_ai_chat_response(user, question):
    context = build_staff_ai_context(user, detailed=False)
    latest_import = _latest_import_summary(context["scope"])
    live_stats = _current_live_statistics(context["scope"])
    cleaned = " ".join((question or "").strip().split())
    if not cleaned:
        return _default_staff_ai_answer(user, context)

    question_lower = cleaned.lower()

    metric_label, metric_value = _find_registry_metric(question_lower, live_stats)
    if metric_label and any(token in question_lower for token in ("total", "how many", "count", "number of", "current")):
        source_note = "This is a direct live registry count from the main table."
        if metric_label == "Midwives":
            source_note = "This is counted live from the `Midwife` registry table."
        elif metric_label == "Registered Nurses":
            source_note = "This is counted live from the `NursingProfessional` registry table."
        elif metric_label == "Nurse Aides":
            source_note = "This is counted live from the `NurseAide` registry table."
        elif metric_label == "Graduands":
            source_note = "This is counted live from the `HealthStudent` registry table."
        elif metric_label == "Medical Doctors":
            source_note = "This is counted live from the `MedicalDoctor` registry table."
        elif metric_label == "Community Health Workers":
            source_note = "This is counted live from the `CommunityHealthWorker` registry table."

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
    }


def build_staff_ai_chat_response(user, question):
    local_response = _build_local_staff_ai_chat_response(user, question)
    context = build_staff_ai_context(user, detailed=False)
    return maybe_generate_live_staff_response(user, question, context, local_response)
