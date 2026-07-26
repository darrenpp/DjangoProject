from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from apps.dashboard.access import can_access_nursing_board_portal, can_manage_regulatory_operations, is_nursing_council_board_member, is_system_admin
from apps.dashboard.models import (
    NursingCouncilBoardActionItem,
    NursingCouncilBoardAgendaItem,
    NursingCouncilBoardAttendance,
    NursingCouncilBoardMeeting,
    NursingCouncilBoardPaper,
)

from .models import (
    BoardCommittee,
    BoardDecisionQueueItem,
    BoardMinutes,
    BoardNotice,
    BoardPack,
    BoardPackReadReceipt,
    BoardPaperReadReceipt,
    BoardPortalAuditEvent,
    BoardProfile,
    BoardResolution,
    BoardRiskItem,
    ConflictDeclaration,
    GovernanceLibraryItem,
)


DEFAULT_COMMITTEES = [
    ("registration", "Registration Committee", "registration", "Board-level registration recommendations, renewal decisions, duplicate and identity assurance."),
    ("education", "Education Committee", "education", "Education accreditation, training institutions, graduate batches, curriculum and audit conditions."),
    ("standards", "Standards Committee", "standards", "Professional standards, policy review, CPD, scope of practice and ethics guidance."),
    ("conduct", "Disciplinary / Professional Conduct Committee", "conduct", "Board-level conduct, discipline, hearings, conditions, appeals and public-protection governance."),
]


DECISION_STATUS_FROM_ACTION = {
    "approve": "approved",
    "approve_conditions": "approved_conditions",
    "defer": "deferred",
    "reject": "rejected",
    "request_information": "information_requested",
    "return_committee": "returned_to_committee",
    "refer_registrar": "needs_review",
    "note": "closed",
}


OPEN_QUEUE_STATUSES = {"ready", "needs_review", "deferred", "information_requested", "returned_to_committee"}
RESTRICTED_BOARD_CLASSIFICATIONS = {"confidential", "highly_confidential"}
REGISTRATION_QUEUE_CATEGORIES = {
    "provisional_registration",
    "full_registration",
    "licence_renewal",
    "provisional_to_full",
    "overseas_registration",
    "temporary_registration",
    "restoration",
}
EDUCATION_QUEUE_CATEGORIES = {"education_accreditation", "institution_approval"}
CONDUCT_QUEUE_CATEGORIES = {"complaint_discipline", "appeal_review"}


def can_manage_board_governance(user):
    if is_system_admin(user) or can_manage_regulatory_operations(user):
        return True
    if not is_nursing_council_board_member(user):
        return False
    profile = getattr(user, "board_profile", None)
    if not (profile and profile.is_active):
        return False
    return profile.board_role in {
        "chair",
        "deputy_chair",
        "secretariat",
        "registrar",
        "system_admin",
    }


def ensure_default_committees():
    committees = []
    for slug, name, committee_type, description in DEFAULT_COMMITTEES:
        committee, _created = BoardCommittee.objects.get_or_create(
            slug=slug,
            defaults={
                "name": name,
                "committee_type": committee_type,
                "description": description,
            },
        )
        committees.append(committee)
    return committees


def get_current_board_meeting():
    now = timezone.now()
    meetings = NursingCouncilBoardMeeting.objects.select_related("chair", "secretary").exclude(status="cancelled")
    return meetings.filter(scheduled_for__gte=now).order_by("scheduled_for").first() or meetings.order_by("-scheduled_for").first()


def get_or_create_board_pack(meeting):
    if not meeting:
        return None
    pack, _created = BoardPack.objects.get_or_create(meeting=meeting)
    return pack


def board_role_for_user(meeting, user):
    profile = getattr(user, "board_profile", None)
    if profile and profile.is_active:
        return profile.board_role
    if meeting and meeting.chair_id == getattr(user, "id", None):
        return "chair"
    if meeting and meeting.secretary_id == getattr(user, "id", None):
        return "secretariat"
    if is_system_admin(user):
        return "system_admin"
    return "board_member" if is_nursing_council_board_member(user) else "observer"


def _choice_label(choices, value):
    return dict(choices).get(value, value)


def build_readiness(meeting, pack=None):
    if not meeting:
        return {
            "score": 0,
            "checks": [],
            "ready_count": 0,
            "total_count": 0,
        }

    pack = pack or get_or_create_board_pack(meeting)
    agenda_items = meeting.agenda_items.all()
    papers = meeting.papers.all()
    attendance = meeting.attendance_records.all()
    profile_count = BoardProfile.objects.filter(is_active=True).count()
    present_count = attendance.filter(attendance_status="present").count()
    declared_count = attendance.exclude(attendance_status="expected").count()
    confidential_papers = papers.filter(classification__in=["confidential", "highly_confidential", "private"])
    committee_categories = {"registration", "education", "standards", "conduct"}
    committee_reports_ready = agenda_items.filter(category__in=committee_categories).exclude(status="pending").count()
    minutes_ready = hasattr(meeting, "board_minutes") and meeting.board_minutes.status in {
        "chair_review",
        "board_confirmation",
        "confirmed",
        "signed_locked",
    }

    checks = [
        ("Agenda completed", agenda_items.exists(), "Agenda has items ready for the Board pack."),
        ("Papers uploaded", papers.exists(), "Supporting papers are linked to agenda items or repository documents."),
        ("Chair/Registrar review", bool(pack and pack.status in {"chair_review", "ready", "issued", "archived"}), "Board pack has reached Chair review or issue stage."),
        ("Quorum confirmed", present_count >= meeting.quorum_required, f"{present_count} present of {meeting.quorum_required} required."),
        ("Declarations completed", declared_count >= max(profile_count, 1) if profile_count else attendance.exists(), "Board members have recorded attendance and conflict declarations."),
        ("Committee reports received", committee_reports_ready >= 3, "Registration, Education, Standards, and Conduct reporting is tracked."),
        ("Confidential papers classified", confidential_papers.count() == papers.filter(agenda_item__confidentiality__in=["confidential", "private"]).count(), "Sensitive papers have privacy classification."),
        ("Previous minutes ready", minutes_ready or bool(meeting.minutes_summary), "Minutes are ready for confirmation or already summarised."),
    ]
    ready_count = sum(1 for _label, ok, _detail in checks if ok)
    total_count = len(checks)
    return {
        "score": round((ready_count / total_count) * 100) if total_count else 0,
        "checks": [{"label": label, "ok": ok, "detail": detail} for label, ok, detail in checks],
        "ready_count": ready_count,
        "total_count": total_count,
    }


def build_governance_health(readiness, meeting):
    if not meeting:
        return {"score": readiness["score"], "checks": readiness["checks"]}
    actions = meeting.action_items.all()
    open_actions = actions.exclude(status__in=["completed", "cancelled"])
    overdue_actions = open_actions.filter(due_date__lt=timezone.localdate()).count()
    policies_due = GovernanceLibraryItem.objects.filter(is_current=True, review_due_date__lt=timezone.localdate()).count()
    resolutions_with_authority = BoardResolution.objects.filter(meeting=meeting).exclude(authority_reference="").count()
    resolution_count = BoardResolution.objects.filter(meeting=meeting).count()
    checks = list(readiness["checks"]) + [
        {
            "label": "Actions closed on time",
            "ok": overdue_actions == 0,
            "detail": f"{overdue_actions} overdue board action(s).",
        },
        {
            "label": "Policies reviewed on time",
            "ok": policies_due == 0,
            "detail": f"{policies_due} governance library item(s) overdue for review.",
        },
        {
            "label": "Decisions have authority reference",
            "ok": not resolution_count or resolutions_with_authority == resolution_count,
            "detail": f"{resolutions_with_authority} of {resolution_count} resolution(s) have an authority reference.",
        },
    ]
    ready_count = sum(1 for item in checks if item["ok"])
    return {
        "score": round((ready_count / len(checks)) * 100) if checks else 0,
        "checks": checks,
    }


def build_risk_radar(user):
    open_queue = BoardDecisionQueueItem.objects.filter(status__in=OPEN_QUEUE_STATUSES)
    registration_items = open_queue.filter(category__in=REGISTRATION_QUEUE_CATEGORIES).count()
    renewal_items = open_queue.filter(category="licence_renewal").count()
    conduct_items = open_queue.filter(category__in=CONDUCT_QUEUE_CATEGORIES).count()
    education_items = open_queue.filter(category__in=EDUCATION_QUEUE_CATEGORIES).count()
    information_requests = open_queue.filter(status__in=["information_requested", "returned_to_committee"]).count()
    policy_overdue = GovernanceLibraryItem.objects.filter(is_current=True, review_due_date__lt=timezone.localdate()).count()
    finance_items = open_queue.filter(category="finance_fee").count()

    synthetic = [
        ("Registration matters awaiting Board", "registration_backlog", registration_items, 5, 12),
        ("Renewal matters awaiting Board", "renewal_backlog", renewal_items, 3, 8),
        ("Conduct matters awaiting Board", "complaints_pending", conduct_items, 3, 8),
        ("Disciplinary decisions awaiting Board", "disciplinary_pending", conduct_items, 3, 8),
        ("Education items awaiting Board", "education_audits", education_items, 2, 5),
        ("Accreditation conditions for Board", "accreditation_conditions", education_items, 2, 5),
        ("Policy reviews overdue", "policy_reviews", policy_overdue, 1, 4),
        ("Board information requests", "data_quality", information_requests, 4, 10),
        ("Fee or finance matters awaiting Board", "payments", finance_items, 2, 5),
    ]
    radar = []
    for label, category, count, amber_at, red_at in synthetic:
        status = "red" if count >= red_at else "amber" if count >= amber_at else "green"
        radar.append({
            "label": label,
            "category": category,
            "count": count,
            "status": status,
            "detail": "Board-governance summary only. Operational Nursing Council portal records are not exposed here.",
        })

    for item in BoardRiskItem.objects.filter(is_active=True).order_by("status", "due_date")[:8]:
        radar.append({
            "label": item.title,
            "category": item.category,
            "count": "",
            "status": item.status,
            "detail": item.summary or item.source_reference,
            "href": reverse("board_nursing_risk"),
        })
    return radar


def build_decision_queue(user):
    rows = []
    can_manage = can_manage_board_governance(user)
    for item in BoardDecisionQueueItem.objects.select_related("committee", "board_paper").order_by("status", "due_date", "-updated_at")[:20]:
        is_restricted = item.confidentiality in RESTRICTED_BOARD_CLASSIFICATIONS and not can_manage
        rows.append({
            "kind": "board_queue",
            "pk": item.pk,
            "reference": item.reference or f"BQ-{item.pk}",
            "title": "Restricted board item" if is_restricted else item.title,
            "subject": "Restricted to authorised board governance officers" if is_restricted else item.subject,
            "type": item.get_category_display(),
            "committee": item.committee.name if item.committee_id else "Board",
            "recommendation": "Restricted" if is_restricted else item.get_committee_recommendation_display(),
            "risk_flag": "Restricted" if is_restricted else (item.risk_flag or "None recorded"),
            "required_action": item.get_required_action_display(),
            "due_date": item.due_date,
            "status": item.get_status_display(),
            "status_code": item.status,
            "confidentiality": item.get_confidentiality_display(),
            "confidentiality_code": item.confidentiality,
            "is_overdue": item.is_overdue,
            "href": "" if is_restricted else reverse("board_nursing_decision_queue"),
            "restricted": is_restricted,
        })

    return rows


def build_decision_urgency(decision_rows, meeting):
    today = timezone.localdate()
    next_meeting_date = meeting.scheduled_for.date() if meeting else None
    buckets = [
        {"label": "Due today", "count": 0, "theme": "amber"},
        {"label": "Due before next Board", "count": 0, "theme": "navy"},
        {"label": "Overdue", "count": 0, "theme": "red"},
        {"label": "Deferred from previous meeting", "count": 0, "theme": "slate"},
        {"label": "Returned for more information", "count": 0, "theme": "green"},
    ]
    for row in decision_rows:
        due_date = row.get("due_date")
        status_code = row.get("status_code")
        if due_date == today:
            buckets[0]["count"] += 1
        if due_date and next_meeting_date and today < due_date <= next_meeting_date:
            buckets[1]["count"] += 1
        if row.get("is_overdue") or (due_date and due_date < today and status_code not in {"approved", "approved_conditions", "rejected", "closed", "final"}):
            buckets[2]["count"] += 1
        if status_code == "deferred":
            buckets[3]["count"] += 1
        if status_code in {"information_requested", "returned_to_committee"}:
            buckets[4]["count"] += 1
    return buckets


def build_committee_workspaces(user):
    committees = {committee.slug: committee for committee in ensure_default_committees()}
    open_queue = BoardDecisionQueueItem.objects.filter(status__in=OPEN_QUEUE_STATUSES)
    pending_registration_count = open_queue.filter(category__in=REGISTRATION_QUEUE_CATEGORIES).count()
    full_registration_count = open_queue.filter(category__in=["full_registration", "provisional_to_full", "overseas_registration"]).count()
    renewal_count = open_queue.filter(category="licence_renewal").count()
    education_count = open_queue.filter(category__in=EDUCATION_QUEUE_CATEGORIES).count()
    policy_count = GovernanceLibraryItem.objects.filter(category__in=["professional_standard", "registration_policy", "education_standard"]).count()
    policy_due_count = GovernanceLibraryItem.objects.filter(is_current=True, review_due_date__lt=timezone.localdate()).count()
    conduct_count = open_queue.filter(category__in=CONDUCT_QUEUE_CATEGORIES).count()
    conduct_needs_review = open_queue.filter(category__in=CONDUCT_QUEUE_CATEGORIES, status__in=["ready", "needs_review"]).count()

    consultation_count = sum(
        1 for item in GovernanceLibraryItem.objects.only("tags")
        if "consultation" in (item.tags or [])
    )

    return [
        {
            "slug": "registration",
            "committee": committees["registration"],
            "icon": "fas fa-id-card",
            "purpose": "Board-level registration matters, renewal decisions, restoration requests and committee recommendations.",
            "metrics": [("Board registration items", pending_registration_count), ("Full registration items", full_registration_count), ("Renewal items", renewal_count)],
            "href": reverse("board_nursing_committee", args=["registration"]),
        },
        {
            "slug": "education",
            "committee": committees["education"],
            "icon": "fas fa-school",
            "purpose": "Accreditation calendar, institution profile, audit conditions, programme approval and graduate batch review.",
            "metrics": [("Board education items", education_count), ("Accreditation matters", open_queue.filter(category="education_accreditation").count()), ("Institution approvals", open_queue.filter(category="institution_approval").count())],
            "href": reverse("board_nursing_committee", args=["education"]),
        },
        {
            "slug": "standards",
            "committee": committees["standards"],
            "icon": "fas fa-book-medical",
            "purpose": "Policy register, CPD standards, scope of practice, professional conduct and review calendar.",
            "metrics": [("Policy records", policy_count), ("Reviews overdue", policy_due_count), ("Consultation items", consultation_count)],
            "href": reverse("board_nursing_committee", args=["standards"]),
        },
        {
            "slug": "conduct",
            "committee": committees["conduct"],
            "icon": "fas fa-scale-balanced",
            "purpose": "Board-level conduct, discipline, appeal and public-protection governance matters.",
            "metrics": [("Board conduct items", conduct_count), ("Ready for Board", conduct_needs_review), ("Appeal/review items", open_queue.filter(category="appeal_review").count())],
            "href": reverse("board_nursing_committee", args=["conduct"]),
        },
    ]


def build_meeting_pack_rows(meeting):
    if not meeting:
        return []
    rows = []
    for agenda_item in meeting.agenda_items.prefetch_related("papers").order_by("order", "id"):
        papers = list(agenda_item.papers.select_related("document").all())
        rows.append({
            "agenda_item": agenda_item,
            "papers": papers,
            "paper_count": len(papers),
            "status": "ready" if papers or agenda_item.status in {"ready", "approved", "noted"} else "pending",
        })
    return rows


def build_matters_arising(meeting):
    if not meeting:
        return []
    previous_meeting = (
        NursingCouncilBoardMeeting.objects.exclude(pk=meeting.pk)
        .filter(scheduled_for__lt=meeting.scheduled_for)
        .order_by("-scheduled_for")
        .first()
    )
    rows = []
    if previous_meeting:
        for action in previous_meeting.action_items.exclude(status__in=["completed", "cancelled"]).select_related("owner")[:10]:
            rows.append({
                "source": "Previous action",
                "title": action.title,
                "detail": action.description or "Action carried forward.",
                "status": action.get_status_display(),
                "due_date": action.due_date,
            })
    for item in BoardDecisionQueueItem.objects.filter(status__in=["deferred", "information_requested", "returned_to_committee"]).order_by("due_date")[:10]:
        rows.append({
            "source": "Decision queue",
            "title": item.title,
            "detail": item.reason or item.risk_flag or "Matter requires further Board attention.",
            "status": item.get_status_display(),
            "due_date": item.due_date,
        })
    return rows


def build_governance_library_rows():
    return list(
        GovernanceLibraryItem.objects.select_related("document", "linked_decision")
        .order_by("category", "title")[:50]
    )


def build_notice_rows():
    now = timezone.now()
    return list(
        BoardNotice.objects.select_related("meeting", "agenda_item", "posted_by")
        .filter(publish_at__lte=now)
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gte=now))
        .order_by("-publish_at")[:12]
    )


def build_board_dashboard_context(user):
    ensure_default_committees()
    meeting = get_current_board_meeting()
    pack = get_or_create_board_pack(meeting)
    readiness = build_readiness(meeting, pack)
    governance_health = build_governance_health(readiness, meeting)
    decision_rows = build_decision_queue(user)
    risk_radar = build_risk_radar(user)
    attendance_records = list(meeting.attendance_records.select_related("member").order_by("role_on_board", "member__last_name") if meeting else [])
    action_items = list(meeting.action_items.select_related("owner", "agenda_item").order_by("status", "due_date", "priority") if meeting else [])
    papers = list(meeting.papers.select_related("agenda_item", "document", "prepared_by").order_by("agenda_item__order", "title") if meeting else [])
    minutes = None
    if meeting:
        minutes, _created = BoardMinutes.objects.get_or_create(meeting=meeting, defaults={"created_by": user if getattr(user, "is_authenticated", False) else None})

    present_count = sum(1 for item in attendance_records if item.attendance_status == "present")
    conflict_count = sum(1 for item in attendance_records if item.conflict_declared)
    overdue_actions = [item for item in action_items if item.due_date and item.due_date < timezone.localdate() and item.status not in {"completed", "cancelled"}]
    metrics = [
        {"label": "Board Readiness", "value": f"{readiness['score']}%", "icon": "fas fa-gauge-high", "theme": "green" if readiness["score"] >= 80 else "amber"},
        {"label": "Governance Health", "value": f"{governance_health['score']}%", "icon": "fas fa-shield-halved", "theme": "navy"},
        {"label": "Decisions Awaiting Board", "value": len(decision_rows), "icon": "fas fa-list-check", "theme": "amber" if decision_rows else "green"},
        {"label": "Actions Overdue", "value": len(overdue_actions), "icon": "fas fa-clipboard-check", "theme": "red" if overdue_actions else "slate"},
        {"label": "Declarations Due", "value": max(BoardProfile.objects.filter(is_active=True).count() - len(attendance_records), 0), "icon": "fas fa-scale-balanced", "theme": "red" if not attendance_records else "green"},
        {"label": "Regulatory Risk Alerts", "value": sum(1 for item in risk_radar if item["status"] in {"amber", "red"}), "icon": "fas fa-triangle-exclamation", "theme": "red"},
    ]

    return {
        "board_current_meeting": meeting,
        "board_pack": pack,
        "board_minutes": minutes,
        "board_readiness": readiness,
        "board_governance_health": governance_health,
        "board_decision_queue": decision_rows,
        "board_decision_urgency": build_decision_urgency(decision_rows, meeting),
        "board_risk_radar": risk_radar,
        "board_committee_rows": build_committee_workspaces(user),
        "board_meeting_pack_rows": build_meeting_pack_rows(meeting),
        "board_matters_arising": build_matters_arising(meeting),
        "board_library_items": build_governance_library_rows(),
        "board_notices": build_notice_rows(),
        "board_attendance_records": attendance_records,
        "board_action_items": action_items,
        "board_papers": papers,
        "board_profile": BoardProfile.objects.filter(user=user).first(),
        "board_metrics": metrics,
        "board_present_count": present_count,
        "board_apology_count": sum(1 for item in attendance_records if item.attendance_status == "apology"),
        "board_conflict_count": conflict_count,
        "board_quorum_required": meeting.quorum_required if meeting else 0,
        "board_quorum_met": present_count >= meeting.quorum_required if meeting else False,
        "board_user_role": board_role_for_user(meeting, user),
        "board_can_manage": can_manage_board_governance(user),
        "board_can_access": can_access_nursing_board_portal(user),
        "board_attendance_status_choices": NursingCouncilBoardAttendance.STATUS_CHOICES,
        "board_action_status_choices": NursingCouncilBoardActionItem.STATUS_CHOICES,
        "board_action_priority_choices": NursingCouncilBoardActionItem.PRIORITY_CHOICES,
        "board_agenda_purpose_choices": NursingCouncilBoardAgendaItem.PURPOSE_CHOICES,
        "board_agenda_category_choices": NursingCouncilBoardAgendaItem.CATEGORY_CHOICES,
        "board_decision_action_choices": BoardDecisionQueueItem.RECOMMENDATION_CHOICES,
        "board_decision_category_choices": BoardDecisionQueueItem.CATEGORY_CHOICES,
        "board_confidentiality_choices": BoardDecisionQueueItem.CONFIDENTIALITY_CHOICES,
        "board_minutes_status_choices": BoardMinutes.STATUS_CHOICES,
        "board_library_category_choices": GovernanceLibraryItem.CATEGORY_CHOICES,
        "board_notice_type_choices": BoardNotice.NOTICE_TYPE_CHOICES,
        "board_risk_category_choices": BoardRiskItem.CATEGORY_CHOICES,
        "board_today": timezone.localdate(),
    }


def _board_ai_session_id(session_id):
    value = str(session_id or "").strip()
    return value if value else f"board-{timezone.now().strftime('%Y%m%d%H%M%S')}"


def _board_ai_links(*names):
    labels = {
        "board_nursing_dashboard": "Board Dashboard",
        "board_nursing_meetings": "Meetings",
        "board_nursing_papers": "Board Papers",
        "board_nursing_decision_queue": "Decision Queue",
        "board_nursing_committees": "Committees",
        "board_nursing_actions": "Actions and Minutes",
        "board_nursing_risk": "Risk and Compliance",
        "board_nursing_library": "Governance Library",
        "board_nursing_profile": "Board Member Profile",
    }
    return [{"label": labels.get(name, name), "url": reverse(name)} for name in names]


def _board_user_label(user):
    full_name = ""
    get_full_name = getattr(user, "get_full_name", None)
    if callable(get_full_name):
        full_name = get_full_name()
    return full_name or getattr(user, "username", "") or "this signed-in board user"


def _board_question_is_platform_scope_question(question):
    lowered = str(question or "").lower()
    return any(
        token in lowered
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
            "what are you",
            "who are you",
            "what can you do",
            "what does this platform do",
            "tell me about this platform",
            "board portal scope",
        )
    )


def _board_platform_scope_answer(user, base_payload):
    user_label = _board_user_label(user)
    return {
        **base_payload,
        "title": "Nursing Council Board Portal Scope",
        "answer": (
            f"{user_label}, you are signed in within the Nursing Council Board governance scope. "
            "This board portal supports board meetings, board packs, papers, minutes, declarations, committees, decisions, governance library, risks, and board action tracking."
        ),
        "bullets": [
            "This is not the operational Nursing Council portal, and it does not expose applicant files, registry records, receipts, workbook imports, or individual practitioner records.",
            "It is also separate from the Medical Board operational workspace.",
            "Use this assistant for board-governance questions only; final board decisions, minutes, and approvals remain human-governance actions.",
        ],
        "links": _board_ai_links("board_nursing_dashboard", "board_nursing_papers", "board_nursing_decision_queue"),
        "suggestions": ["Board pack readiness", "Decision queue", "Board actions and risks"],
    }


def _board_scope_refusal(question):
    lowered = str(question or "").lower()
    restricted_terms = {
        "applicant",
        "application",
        "application detail",
        "application form",
        "application record",
        "patient",
        "medical board",
        "doctor",
        "chw",
        "community health worker",
        "records hub",
        "individual record",
        "nursing council portal data",
        "nursing council portal records",
        "registration number",
        "registration form",
        "registration forms",
        "renewal form",
        "renewal forms",
        "public form",
        "public forms",
        "nursing form",
        "nursing forms",
        "nursing council form",
        "nursing council forms",
        "medical form",
        "medical forms",
        "medical board form",
        "medical board forms",
        "online registration",
        "sign up form",
        "signup form",
        "nc1",
        "nc2",
        "nc3",
        "nc4",
        "nc5",
        "nc6",
        "nc7",
        "form fee",
        "form fees",
        "required documents",
        "licence number",
        "license number",
        "receipt",
        "payment",
        "workbook",
        "import",
        "complaint case",
        "disciplinary case",
        "case file",
        "personal data",
        "confidential data",
    }
    return any(term in lowered for term in restricted_terms)


def build_board_ai_chat_response(user, question, *, session_id="", browser_session_key=""):
    question_text = str(question or "").strip()
    session_value = _board_ai_session_id(session_id or browser_session_key)
    base_payload = {
        "session_id": session_value,
        "scope": "board",
        "scope_label": "Nursing Council Board governance only",
        "sources": [
            {
                "label": "Board governance portal",
                "detail": "Meetings, papers, decisions, committees, minutes, actions, risk, and library only.",
            }
        ],
    }

    if not question_text:
        return {
            **base_payload,
            "title": "Board Governance Assistant",
            "answer": "Ask about board meetings, board packs, agenda readiness, conflicts, minutes, decision queue items, committees, governance library, risks, or board actions.",
            "bullets": [
                "This assistant does not access Nursing Council operational portal records.",
                "This assistant does not access Medical Board records or applicant case files.",
            ],
            "links": _board_ai_links("board_nursing_dashboard", "board_nursing_papers", "board_nursing_decision_queue"),
            "suggestions": ["Board pack readiness", "Decision queue", "Board actions and risks"],
        }

    if _board_scope_refusal(question_text):
        return {
            **base_payload,
            "title": "Board Scope Boundary",
            "answer": "I can only help with Nursing Council Board governance matters. I cannot answer questions about Nursing Council forms, Medical Board forms, sign-up or registration forms, and I cannot access operational Nursing Council portal data, Medical Board data, applicant records, individual identifiers, receipts, workbook imports, or complaint and discipline case files.",
            "bullets": [
                "Use the board decision queue for board-ready summaries only.",
                "Use board papers and minutes only where they are controlled through the board portal.",
                "Ask the Registrar or System Admin through the proper operational workflow for forms, sign-up, registration, payments, and other non-board records.",
            ],
            "links": _board_ai_links("board_nursing_dashboard", "board_nursing_decision_queue", "board_nursing_library"),
            "suggestions": ["Summarize board readiness", "List board risks", "Show board action priorities"],
        }

    if _board_question_is_platform_scope_question(question_text):
        return _board_platform_scope_answer(user, base_payload)

    lowered = question_text.lower()
    meeting = get_current_board_meeting()
    pack = get_or_create_board_pack(meeting)
    readiness = build_readiness(meeting, pack) if meeting else {"score": 0, "checks": [], "ready_count": 0, "total_count": 0}
    open_decisions = BoardDecisionQueueItem.objects.filter(status__in=OPEN_QUEUE_STATUSES).count()
    open_risks = BoardRiskItem.objects.filter(is_active=True).exclude(status="green").count()
    overdue_library = GovernanceLibraryItem.objects.filter(is_current=True, review_due_date__lt=timezone.localdate()).count()
    action_queryset = meeting.action_items.exclude(status__in=["completed", "cancelled"]) if meeting else NursingCouncilBoardActionItem.objects.none()
    overdue_actions = action_queryset.filter(due_date__lt=timezone.localdate()).count() if meeting else 0

    if any(term in lowered for term in ("pack", "paper", "readiness", "review first", "before the next meeting")):
        pending_checks = [check["label"] for check in readiness.get("checks", []) if not check["ok"]]
        return {
            **base_payload,
            "title": f"Board Pack Readiness {readiness['score']}%",
            "answer": "The board pack view is limited to agenda, papers, Chair review, quorum, declarations, committee reports, classification, and previous minutes.",
            "bullets": pending_checks[:5] or ["Current readiness checks are complete for the available board data."],
            "links": _board_ai_links("board_nursing_papers", "board_nursing_meetings", "board_nursing_actions"),
            "suggestions": ["Decision queue", "Conflict declarations", "Minutes status"],
        }

    if any(term in lowered for term in ("decision", "queue", "approval", "resolution")):
        return {
            **base_payload,
            "title": "Board Decision Queue",
            "answer": f"{open_decisions} board decision item(s) are open for board-governance attention. This is a board summary only, not an operational case-file view.",
            "bullets": [
                "Review the required board action and due date.",
                "Record decisions through minutes and controlled board actions.",
                "Do not use the board portal to browse applicant or complaint case records.",
            ],
            "links": _board_ai_links("board_nursing_decision_queue", "board_nursing_minutes"),
            "suggestions": ["Board minutes", "Risk items", "Committee workspaces"],
        }

    if any(term in lowered for term in ("risk", "compliance", "overdue", "action")):
        return {
            **base_payload,
            "title": "Board Actions and Risk",
            "answer": f"There are {overdue_actions} overdue board action(s), {open_risks} active amber/red board risk item(s), and {overdue_library} governance library review(s) overdue.",
            "bullets": [
                "Use the board action register for owner, due date, and status updates.",
                "Use risk and compliance for board-level governance risks only.",
                "Operational agency records remain outside the board assistant.",
            ],
            "links": _board_ai_links("board_nursing_actions", "board_nursing_risk", "board_nursing_library"),
            "suggestions": ["Pack readiness", "Decision queue", "Governance library"],
        }

    if any(term in lowered for term in ("committee", "registration oversight", "education", "standards", "conduct")):
        return {
            **base_payload,
            "title": "Committee Workspaces",
            "answer": "The board committee workspaces cover Registration Oversight, Education and Accreditation, Standards and Policy, and Conduct Governance at board-summary level.",
            "bullets": [
                "Registration matters are board-ready recommendations, not applicant files.",
                "Education matters focus on accreditation and institution governance.",
                "Conduct matters are board governance summaries and do not expose complaint case files.",
            ],
            "links": _board_ai_links("board_nursing_committees", "board_nursing_decision_queue", "board_nursing_library"),
            "suggestions": ["Education committee", "Standards policy", "Conduct governance"],
        }

    meeting_label = meeting.title if meeting else "No current board meeting scheduled"
    return {
        **base_payload,
        "title": "Nursing Council Board Governance",
        "answer": f"{meeting_label}. Board readiness is {readiness['score']}%, with {open_decisions} open board decision item(s) and {overdue_actions} overdue board action(s).",
        "bullets": [
            "Use this assistant for board meetings, packs, minutes, actions, risks, decisions, committees, and governance library.",
            "The assistant does not retrieve operational Nursing Council or Medical Board data.",
            "Final approvals, minutes, and decisions remain human-governance actions.",
        ],
        "links": _board_ai_links("board_nursing_dashboard", "board_nursing_papers", "board_nursing_decision_queue"),
        "suggestions": ["Board pack readiness", "Decision queue", "Board actions and risks"],
    }


def record_audit_event(event_type, user, request=None, target=None, metadata=None):
    content_type = None
    object_id = None
    if target is not None:
        content_type = ContentType.objects.get_for_model(target, for_concrete_model=False)
        object_id = target.pk
    return BoardPortalAuditEvent.objects.create(
        event_type=event_type,
        user=user if getattr(user, "is_authenticated", False) else None,
        path=request.path if request else "",
        target_content_type=content_type,
        target_object_id=object_id,
        metadata=metadata or {},
    )


def mark_pack_read(pack, user, acknowledge=False, notes="", bookmarked=False, request=None):
    receipt, _created = BoardPackReadReceipt.objects.get_or_create(pack=pack, member=user)
    now = timezone.now()
    receipt.marked_read_at = receipt.marked_read_at or now
    receipt.last_viewed_at = now
    receipt.acknowledged_confidentiality = acknowledge or receipt.acknowledged_confidentiality
    receipt.private_notes = notes
    receipt.bookmarked = bookmarked
    receipt.save()
    record_audit_event("marked_read", user, request=request, target=pack)
    return receipt


def mark_paper_read(paper, user, acknowledge=False, notes="", bookmarked=False, request=None):
    receipt, _created = BoardPaperReadReceipt.objects.get_or_create(paper=paper, member=user)
    now = timezone.now()
    receipt.marked_read_at = receipt.marked_read_at or now
    receipt.last_viewed_at = now
    receipt.acknowledged_confidentiality = acknowledge or receipt.acknowledged_confidentiality
    receipt.private_notes = notes
    receipt.bookmarked = bookmarked
    receipt.save()
    record_audit_event("marked_read", user, request=request, target=paper)
    return receipt


def record_conflict_declaration(meeting, user, status, note="", agenda_item=None, recusal_required=False, request=None):
    declaration = ConflictDeclaration.objects.create(
        meeting=meeting,
        agenda_item=agenda_item,
        member=user,
        declaration_type="agenda_item" if agenda_item else "meeting",
        status=status,
        declaration_text=note,
        recusal_required=recusal_required,
    )
    record_audit_event("conflict_declared", user, request=request, target=declaration)
    return declaration


def record_decision_action(queue_item, user, action, reason="", conditions="", minute_reference="", request=None):
    queue_item.status = DECISION_STATUS_FROM_ACTION.get(action, queue_item.status)
    queue_item.required_action = action if action in dict(BoardDecisionQueueItem.RECOMMENDATION_CHOICES) else queue_item.required_action
    queue_item.reason = reason
    queue_item.conditions = conditions
    queue_item.final_minute_reference = minute_reference
    queue_item.decided_by = user
    queue_item.decided_at = timezone.now()
    queue_item.save()
    record_audit_event("decision_recorded", user, request=request, target=queue_item, metadata={"action": action})
    return queue_item


def build_minutes_outline(meeting):
    if not meeting:
        return ""
    lines = [
        f"Meeting: {meeting.title}",
        f"Date/time: {timezone.localtime(meeting.scheduled_for).strftime('%d %b %Y, %H:%M')}",
        f"Venue/mode: {meeting.location or 'To be confirmed'} / {meeting.get_meeting_mode_display()}",
        "",
        "Attendance and quorum:",
    ]
    for attendance in meeting.attendance_records.select_related("member").order_by("role_on_board", "member__last_name"):
        lines.append(f"- {attendance.member.account_display_name}: {attendance.get_attendance_status_display()} ({attendance.get_role_on_board_display()})")
    lines.extend(["", "Agenda items and decisions:"])
    for item in meeting.agenda_items.order_by("order", "id"):
        lines.append(f"{item.order}. {item.title} - {item.get_purpose_display()} - {item.get_status_display()}")
        if item.recommendation:
            lines.append(f"   Recommendation: {item.recommendation}")
    lines.extend(["", "Actions:"])
    for action in meeting.action_items.select_related("owner").order_by("due_date", "title"):
        owner = action.owner.account_display_name if action.owner_id else "Unassigned"
        lines.append(f"- {action.title} | Owner: {owner} | Due: {action.due_date or 'No due date'} | Status: {action.get_status_display()}")
    return "\n".join(lines)
