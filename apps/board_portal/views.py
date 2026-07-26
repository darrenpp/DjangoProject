import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.dashboard.models import (
    NursingCouncilBoardActionItem,
    NursingCouncilBoardAgendaItem,
    NursingCouncilBoardAttendance,
    NursingCouncilBoardMeeting,
    NursingCouncilBoardPaper,
)
from apps.documents.models import Document

from .models import (
    BoardDecisionQueueItem,
    BoardMinutes,
    BoardNotice,
    BoardPack,
    BoardRiskItem,
    GovernanceLibraryItem,
)
from .services import (
    build_board_dashboard_context,
    build_board_ai_chat_response,
    build_minutes_outline,
    can_manage_board_governance,
    get_or_create_board_pack,
    mark_pack_read,
    mark_paper_read,
    record_audit_event,
    record_conflict_declaration,
    record_decision_action,
)


BOARD_TEMPLATE = "board_portal/nursing_governance_portal.html"

BOARD_PAGE_DETAILS = {
    "dashboard": (
        "Board Dashboard",
        "Board readiness, next meeting, decision workload, action status, risk, and governance health at a glance.",
    ),
    "meetings": (
        "Meetings",
        "Board meeting details, quorum, attendance declarations, agenda builder, and matters arising.",
    ),
    "papers": (
        "Board Papers",
        "Board pack reader, issued papers, read acknowledgements, bookmarks, and member notes.",
    ),
    "decisions": (
        "Decision Queue",
        "Board-level decision items only. Operational applicant, complaint, and registration records remain outside this portal.",
    ),
    "committees": (
        "Committees",
        "Registration, Education, Standards, and Conduct committee workspaces for board governance oversight.",
    ),
    "registration": (
        "Registration Oversight",
        "Board-level registration recommendations, restorations, renewals, and committee decisions.",
    ),
    "education": (
        "Education & Accreditation",
        "Education accreditation, institution approval, programme review, and graduate-batch oversight.",
    ),
    "standards": (
        "Standards & Policy",
        "Standards, policies, CPD, scope of practice, consultation, and review calendar governance.",
    ),
    "conduct": (
        "Conduct Governance",
        "Board-level conduct, discipline, appeal, and public-protection governance matters.",
    ),
    "actions": (
        "Actions & Minutes",
        "Board actions, owners, due dates, minutes workflow, motions, resolutions, and public-safe extracts.",
    ),
    "risk": (
        "Risk & Compliance",
        "Board governance risk register, compliance status, controls, owners, and due dates.",
    ),
    "library": (
        "Governance Library",
        "Board policies, terms of reference, templates, notices, review dates, and controlled governance documents.",
    ),
    "profile": (
        "Board Member Profile",
        "Board role, appointment details, committee access, induction, MFA expectation, and portal permissions.",
    ),
}


def _choice_or_default(value, choices, default):
    allowed = {choice_value for choice_value, _label in choices}
    return value if value in allowed else default


def _safe_next(request, fallback):
    next_url = request.POST.get("next") or fallback
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return next_url
    if str(next_url).startswith("/"):
        return next_url
    return fallback


def _render_board(request, active_section="dashboard", **extra):
    if not request.user.is_authenticated:
        return redirect(f"{reverse('board_login')}?next={request.path}")
    from apps.dashboard.access import can_access_nursing_board_portal

    if not can_access_nursing_board_portal(request.user):
        record_audit_event("access_denied", request.user, request=request, metadata={"section": active_section})
        return redirect("main_dashboard")
    page_title, page_description = BOARD_PAGE_DETAILS.get(active_section, BOARD_PAGE_DETAILS["dashboard"])
    context = build_board_dashboard_context(request.user)
    context.update(
        {
            "board_active_section": active_section,
            "board_page_title": page_title,
            "board_page_description": page_description,
            "board_nav_items": _board_nav_items(),
        }
    )
    context.update(extra)
    record_audit_event("viewed", request.user, request=request, metadata={"section": active_section})
    return render(request, BOARD_TEMPLATE, context)


def _board_nav_items():
    return [
        ("dashboard", "Board Dashboard", "board_nursing_dashboard", "fas fa-gauge-high"),
        ("meetings", "Meetings", "board_nursing_meetings", "fas fa-calendar-check"),
        ("papers", "Board Papers", "board_nursing_papers", "fas fa-folder-open"),
        ("decisions", "Decision Queue", "board_nursing_decision_queue", "fas fa-list-check"),
        ("committees", "Committees", "board_nursing_committees", "fas fa-sitemap"),
        ("registration", "Registration Oversight", "board_nursing_committee_registration", "fas fa-id-card"),
        ("education", "Education & Accreditation", "board_nursing_committee_education", "fas fa-school"),
        ("standards", "Standards & Policy", "board_nursing_committee_standards", "fas fa-book-medical"),
        ("conduct", "Conduct Governance", "board_nursing_committee_conduct", "fas fa-scale-balanced"),
        ("actions", "Actions & Minutes", "board_nursing_actions", "fas fa-clipboard-check"),
        ("risk", "Risk & Compliance", "board_nursing_risk", "fas fa-triangle-exclamation"),
        ("library", "Governance Library", "board_nursing_library", "fas fa-landmark"),
        ("profile", "Board Member Profile", "board_nursing_profile", "fas fa-user-shield"),
    ]


@login_required(login_url="board_login")
def nursing_board_dashboard(request):
    if request.method == "POST":
        return _handle_board_post(request, reverse("board_nursing_dashboard"))
    return _render_board(request, "dashboard")


@login_required(login_url="board_login")
def nursing_board_meetings(request):
    if request.method == "POST":
        return _handle_board_post(request, reverse("board_nursing_meetings"))
    meetings = NursingCouncilBoardMeeting.objects.select_related("chair", "secretary").exclude(status="cancelled").order_by("-scheduled_for")[:20]
    return _render_board(request, "meetings", board_meetings=list(meetings))


@login_required(login_url="board_login")
def nursing_board_meeting_detail(request, meeting_id):
    meeting = get_object_or_404(NursingCouncilBoardMeeting, pk=meeting_id)
    if request.method == "POST":
        return _handle_board_post(request, reverse("board_nursing_meeting_detail", args=[meeting_id]))
    pack = get_or_create_board_pack(meeting)
    minutes, _created = BoardMinutes.objects.get_or_create(meeting=meeting, defaults={"created_by": request.user})
    return _render_board(
        request,
        "meetings",
        board_current_meeting=meeting,
        board_pack=pack,
        board_minutes=minutes,
    )


@login_required(login_url="board_login")
def nursing_board_pack_reader(request, pack_id):
    pack = get_object_or_404(BoardPack.objects.select_related("meeting"), pk=pack_id)
    if request.method == "POST":
        return _handle_board_post(request, reverse("board_nursing_board_pack", args=[pack_id]))
    receipt, _created = pack.read_receipts.get_or_create(member=request.user)
    receipt.last_viewed_at = timezone.now()
    receipt.save(update_fields=["last_viewed_at"])
    record_audit_event("viewed", request.user, request=request, target=pack)
    return _render_board(request, "papers", board_current_meeting=pack.meeting, board_pack=pack, board_pack_receipt=receipt)


@login_required(login_url="board_login")
def nursing_board_papers(request):
    if request.method == "POST":
        return _handle_board_post(request, reverse("board_nursing_papers"))
    papers = NursingCouncilBoardPaper.objects.select_related("meeting", "agenda_item", "document", "prepared_by").order_by("-meeting__scheduled_for", "agenda_item__order")[:50]
    return _render_board(request, "papers", board_all_papers=list(papers))


@login_required(login_url="board_login")
def nursing_board_decision_queue(request):
    if request.method == "POST":
        return _handle_board_post(request, reverse("board_nursing_decision_queue"))
    return _render_board(request, "decisions")


@login_required(login_url="board_login")
def nursing_board_committees(request):
    return _render_board(request, "committees")


@login_required(login_url="board_login")
def nursing_board_committee(request, slug):
    allowed = {"registration", "education", "standards", "conduct"}
    if slug not in allowed:
        raise Http404("Committee workspace not found")
    return _render_board(request, slug, board_selected_committee=slug)


@login_required(login_url="board_login")
def nursing_board_actions(request):
    if request.method == "POST":
        return _handle_board_post(request, reverse("board_nursing_actions"))
    return _render_board(request, "actions")


@login_required(login_url="board_login")
def nursing_board_minutes(request):
    if request.method == "POST":
        return _handle_board_post(request, reverse("board_nursing_minutes"))
    return _render_board(request, "actions")


@login_required(login_url="board_login")
def nursing_board_library(request):
    if request.method == "POST":
        return _handle_board_post(request, reverse("board_nursing_library"))
    return _render_board(request, "library")


@login_required(login_url="board_login")
def nursing_board_risk(request):
    if request.method == "POST":
        return _handle_board_post(request, reverse("board_nursing_risk"))
    return _render_board(request, "risk")


@login_required(login_url="board_login")
def nursing_board_profile(request):
    return _render_board(request, "profile")


@login_required(login_url="board_login")
@require_POST
def nursing_board_ai_chat(request):
    from apps.dashboard.access import can_access_nursing_board_portal

    if not can_access_nursing_board_portal(request.user):
        record_audit_event("access_denied", request.user, request=request, metadata={"section": "board_ai"})
        return JsonResponse({"error": "Board governance assistant access is restricted to approved Nursing Council Board users."}, status=403)

    question = request.POST.get("question", "")
    session_id = request.POST.get("session_id", "")
    if not question and request.content_type == "application/json":
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {}
        question = payload.get("question", "")
        session_id = payload.get("session_id", session_id)

    if not request.session.session_key:
        request.session.save()
    response = build_board_ai_chat_response(
        request.user,
        question,
        session_id=session_id,
        browser_session_key=request.session.session_key or "",
    )
    record_audit_event("viewed", request.user, request=request, metadata={"section": "board_ai", "scope": response.get("scope")})
    return JsonResponse(response)


def _handle_board_post(request, fallback):
    from apps.dashboard.access import can_access_nursing_board_portal

    if not can_access_nursing_board_portal(request.user):
        record_audit_event("access_denied", request.user, request=request)
        return redirect("main_dashboard")

    action = request.POST.get("board_action", "")
    target = _safe_next(request, fallback)

    if action == "record_attendance":
        meeting = get_object_or_404(NursingCouncilBoardMeeting, pk=request.POST.get("meeting_id"))
        attendance_status = _choice_or_default(request.POST.get("attendance_status"), NursingCouncilBoardAttendance.STATUS_CHOICES, "expected")
        conflict_declared = request.POST.get("conflict_declared") == "on"
        conflict_note = str(request.POST.get("conflict_note") or "").strip()
        recusal_required = conflict_declared and request.POST.get("recusal_required") == "on"
        attendance, _created = NursingCouncilBoardAttendance.objects.update_or_create(
            meeting=meeting,
            member=request.user,
            defaults={
                "role_on_board": request.POST.get("role_on_board") or "member",
                "attendance_status": attendance_status,
                "conflict_declared": conflict_declared,
                "conflict_note": conflict_note,
                "recusal_required": recusal_required,
            },
        )
        record_conflict_declaration(
            meeting,
            request.user,
            "recused" if recusal_required else "declared" if conflict_declared else "no_conflict",
            note=conflict_note,
            recusal_required=recusal_required,
            request=request,
        )
        record_audit_event("viewed", request.user, request=request, target=attendance, metadata={"action": "attendance_saved"})
        messages.success(request, "Attendance and conflict declaration saved.")
        return redirect(f"{target}#board-attendance")

    if action == "add_agenda_item":
        meeting = get_object_or_404(NursingCouncilBoardMeeting, pk=request.POST.get("meeting_id"))
        if not can_manage_board_governance(request.user):
            messages.error(request, "Only authorised governance staff can add agenda items.")
            return redirect(f"{target}#board-agenda")
        title = str(request.POST.get("title") or "").strip()
        if not title:
            messages.error(request, "Agenda item title is required.")
            return redirect(f"{target}#board-agenda")
        order = (meeting.agenda_items.order_by("-order").values_list("order", flat=True).first() or 0) + 1
        item = NursingCouncilBoardAgendaItem.objects.create(
            meeting=meeting,
            order=order,
            title=title,
            purpose=_choice_or_default(request.POST.get("purpose"), NursingCouncilBoardAgendaItem.PURPOSE_CHOICES, "discussion"),
            category=_choice_or_default(request.POST.get("category"), NursingCouncilBoardAgendaItem.CATEGORY_CHOICES, "governance"),
            confidentiality=_choice_or_default(request.POST.get("confidentiality"), NursingCouncilBoardAgendaItem.CONFIDENTIALITY_CHOICES, "private"),
            summary=str(request.POST.get("summary") or "").strip(),
            recommendation=str(request.POST.get("recommendation") or "").strip(),
            presenter=request.user,
        )
        record_audit_event("viewed", request.user, request=request, target=item, metadata={"action": "agenda_item_created"})
        messages.success(request, "Agenda item added.")
        return redirect(f"{target}#board-agenda")

    if action == "add_action_item":
        meeting = get_object_or_404(NursingCouncilBoardMeeting, pk=request.POST.get("meeting_id"))
        title = str(request.POST.get("title") or "").strip()
        if not title:
            messages.error(request, "Action title is required.")
            return redirect(f"{target}#board-actions")
        item = NursingCouncilBoardActionItem.objects.create(
            meeting=meeting,
            title=title,
            description=str(request.POST.get("description") or "").strip(),
            due_date=parse_date(request.POST.get("due_date") or ""),
            priority=_choice_or_default(request.POST.get("priority"), NursingCouncilBoardActionItem.PRIORITY_CHOICES, "normal"),
            owner=request.user,
            created_by=request.user,
        )
        record_audit_event("viewed", request.user, request=request, target=item, metadata={"action": "action_created"})
        messages.success(request, "Board action item added.")
        return redirect(f"{target}#board-actions")

    if action == "update_action_status":
        item = get_object_or_404(NursingCouncilBoardActionItem, pk=request.POST.get("action_id"))
        if not (can_manage_board_governance(request.user) or item.owner_id == request.user.id):
            messages.error(request, "Only the action owner or authorised governance staff can update this action.")
            return redirect(f"{target}#board-actions")
        item.status = _choice_or_default(request.POST.get("status"), NursingCouncilBoardActionItem.STATUS_CHOICES, item.status)
        item.save(update_fields=["status", "completed_at", "updated_at"])
        record_audit_event("viewed", request.user, request=request, target=item, metadata={"action": "action_status_updated"})
        messages.success(request, "Action status updated.")
        return redirect(f"{target}#board-actions")

    if action == "mark_pack_read":
        pack = get_object_or_404(BoardPack, pk=request.POST.get("pack_id"))
        mark_pack_read(
            pack,
            request.user,
            acknowledge=request.POST.get("acknowledge_confidentiality") == "on",
            notes=str(request.POST.get("private_notes") or "").strip(),
            bookmarked=request.POST.get("bookmarked") == "on",
            request=request,
        )
        messages.success(request, "Board pack read acknowledgement saved.")
        return redirect(f"{target}#board-papers")

    if action == "mark_paper_read":
        paper = get_object_or_404(NursingCouncilBoardPaper, pk=request.POST.get("paper_id"))
        mark_paper_read(
            paper,
            request.user,
            acknowledge=request.POST.get("acknowledge_confidentiality") == "on",
            notes=str(request.POST.get("private_notes") or "").strip(),
            bookmarked=request.POST.get("bookmarked") == "on",
            request=request,
        )
        messages.success(request, "Board paper read acknowledgement saved.")
        return redirect(f"{target}#board-papers")

    if action == "issue_pack":
        meeting = get_object_or_404(NursingCouncilBoardMeeting, pk=request.POST.get("meeting_id"))
        if not can_manage_board_governance(request.user):
            messages.error(request, "Only authorised governance staff can issue a board pack.")
            return redirect(f"{target}#board-papers")
        pack = get_or_create_board_pack(meeting)
        pack.status = "issued"
        pack.issued_at = timezone.now()
        pack.issued_by = request.user
        pack.contains_confidential = meeting.papers.filter(classification__in=["confidential", "highly_confidential", "private"]).exists()
        pack.save(update_fields=["status", "issued_at", "issued_by", "contains_confidential", "updated_at"])
        record_audit_event("viewed", request.user, request=request, target=pack, metadata={"action": "pack_issued"})
        messages.success(request, "Board pack issued to members.")
        return redirect(f"{target}#board-papers")

    if action == "add_decision_queue_item":
        if not can_manage_board_governance(request.user):
            messages.error(request, "Only authorised governance staff can add decision queue items.")
            return redirect(f"{target}#board-decisions")
        title = str(request.POST.get("title") or "").strip()
        if not title:
            messages.error(request, "Decision title is required.")
            return redirect(f"{target}#board-decisions")
        item = BoardDecisionQueueItem.objects.create(
            title=title,
            reference=str(request.POST.get("reference") or "").strip(),
            subject=str(request.POST.get("subject") or "").strip(),
            category=_choice_or_default(request.POST.get("category"), BoardDecisionQueueItem.CATEGORY_CHOICES, "provisional_registration"),
            committee_recommendation=_choice_or_default(request.POST.get("committee_recommendation"), BoardDecisionQueueItem.RECOMMENDATION_CHOICES, "approve"),
            required_action=_choice_or_default(request.POST.get("required_action"), BoardDecisionQueueItem.RECOMMENDATION_CHOICES, "approve"),
            due_date=parse_date(request.POST.get("due_date") or ""),
            confidentiality=_choice_or_default(request.POST.get("confidentiality"), BoardDecisionQueueItem.CONFIDENTIALITY_CHOICES, "internal"),
            risk_flag=str(request.POST.get("risk_flag") or "").strip(),
            created_by=request.user,
        )
        record_audit_event("viewed", request.user, request=request, target=item, metadata={"action": "decision_queue_item_created"})
        messages.success(request, "Decision queue item added.")
        return redirect(f"{target}#board-decisions")

    if action == "record_decision_action":
        item = get_object_or_404(BoardDecisionQueueItem, pk=request.POST.get("queue_item_id"))
        action_value = _choice_or_default(request.POST.get("decision_action"), BoardDecisionQueueItem.RECOMMENDATION_CHOICES, "defer")
        record_decision_action(
            item,
            request.user,
            action_value,
            reason=str(request.POST.get("reason") or "").strip(),
            conditions=str(request.POST.get("conditions") or "").strip(),
            minute_reference=str(request.POST.get("minute_reference") or "").strip(),
            request=request,
        )
        messages.success(request, "Board decision action recorded.")
        return redirect(f"{target}#board-decisions")

    if action == "update_minutes":
        meeting = get_object_or_404(NursingCouncilBoardMeeting, pk=request.POST.get("meeting_id"))
        if not can_manage_board_governance(request.user):
            messages.error(request, "Only authorised governance staff can update minutes.")
            return redirect(f"{target}#board-minutes")
        minutes, _created = BoardMinutes.objects.get_or_create(meeting=meeting, defaults={"created_by": request.user})
        if request.POST.get("generate_outline") == "on":
            minutes.draft_text = build_minutes_outline(meeting)
        else:
            minutes.draft_text = str(request.POST.get("draft_text") or minutes.draft_text).strip()
        minutes.public_safe_extract = str(request.POST.get("public_safe_extract") or minutes.public_safe_extract).strip()
        minutes.status = _choice_or_default(request.POST.get("status"), BoardMinutes.STATUS_CHOICES, minutes.status)
        minutes.updated_by = request.user
        if minutes.status in {"confirmed", "signed_locked"} and not minutes.confirmed_at:
            minutes.confirmed_at = timezone.now()
        minutes.save()
        record_audit_event("minutes_updated", request.user, request=request, target=minutes)
        messages.success(request, "Board minutes updated.")
        return redirect(f"{target}#board-minutes")

    if action == "add_library_item":
        if not can_manage_board_governance(request.user):
            messages.error(request, "Only authorised governance staff can add governance library items.")
            return redirect(f"{target}#board-library")
        document = get_object_or_404(Document, pk=request.POST.get("document_id"))
        item = GovernanceLibraryItem.objects.create(
            title=str(request.POST.get("title") or document.title).strip(),
            category=_choice_or_default(request.POST.get("category"), GovernanceLibraryItem.CATEGORY_CHOICES, "template"),
            document=document,
            classification=_choice_or_default(request.POST.get("classification"), GovernanceLibraryItem.CLASSIFICATION_CHOICES, "internal"),
            policy_owner=str(request.POST.get("policy_owner") or "").strip(),
            review_due_date=parse_date(request.POST.get("review_due_date") or ""),
        )
        record_audit_event("viewed", request.user, request=request, target=item, metadata={"action": "library_item_created"})
        messages.success(request, "Governance library item added.")
        return redirect(f"{target}#board-library")

    if action == "add_risk_item":
        if not can_manage_board_governance(request.user):
            messages.error(request, "Only authorised governance staff can add risk items.")
            return redirect(f"{target}#board-risk")
        title = str(request.POST.get("title") or "").strip()
        if not title:
            messages.error(request, "Risk title is required.")
            return redirect(f"{target}#board-risk")
        item = BoardRiskItem.objects.create(
            title=title,
            category=_choice_or_default(request.POST.get("category"), BoardRiskItem.CATEGORY_CHOICES, "data_quality"),
            status=_choice_or_default(request.POST.get("status"), BoardRiskItem.STATUS_CHOICES, "amber"),
            summary=str(request.POST.get("summary") or "").strip(),
            owner=request.user,
            due_date=parse_date(request.POST.get("due_date") or ""),
        )
        record_audit_event("viewed", request.user, request=request, target=item, metadata={"action": "risk_item_created"})
        messages.success(request, "Risk item added.")
        return redirect(f"{target}#board-risk")

    if action == "add_notice":
        if not can_manage_board_governance(request.user):
            messages.error(request, "Only authorised governance staff can add board notices.")
            return redirect(f"{target}#board-notices")
        title = str(request.POST.get("title") or "").strip()
        if not title:
            messages.error(request, "Notice title is required.")
            return redirect(f"{target}#board-notices")
        notice = BoardNotice.objects.create(
            notice_type=_choice_or_default(request.POST.get("notice_type"), BoardNotice.NOTICE_TYPE_CHOICES, "secretariat_notice"),
            title=title,
            message=str(request.POST.get("message") or "").strip(),
            classification=_choice_or_default(request.POST.get("classification"), BoardNotice.CLASSIFICATION_CHOICES, "internal"),
            posted_by=request.user,
        )
        record_audit_event("notice_created", request.user, request=request, target=notice)
        messages.success(request, "Board notice added.")
        return redirect(f"{target}#board-notices")

    messages.error(request, "Board portal action was not recognised.")
    return redirect(target)
