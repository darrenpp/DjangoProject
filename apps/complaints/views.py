from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.dashboard.access import can_access_staff_domain, is_staff_dashboard_user, is_system_admin
from apps.notifications.models import EnquiryThread

from .forms import (
    ComplaintCaseEventForm,
    ComplaintCaseUpdateForm,
    ComplaintPublicIntakeForm,
    ComplaintStaffCaseForm,
    DisciplinaryCaseEventForm,
    DisciplinaryCaseForm,
    DisciplinaryCaseUpdateForm,
    RegulatoryDecisionRecordForm,
)
from .models import (
    ComplaintCase,
    ComplaintCaseAttachment,
    ComplaintCaseEvent,
    DisciplinaryCase,
    DisciplinaryCaseAttachment,
    DisciplinaryCaseEvent,
    RegulatoryDecisionRecord,
)
from .services import (
    can_access_complaint_case,
    can_access_complaints_workspace,
    can_access_decision_record,
    can_access_disciplinary_case,
    complaint_summary_for_user,
    discipline_summary_for_user,
    scoped_complaint_cases,
    scoped_decision_records,
    scoped_disciplinary_cases,
    staff_complaint_scope,
)


CASE_ATTACHMENT_MAX_FILES = 8
CASE_ATTACHMENT_MAX_SIZE = 15 * 1024 * 1024
CASE_ATTACHMENT_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".txt",
}


def _attachment_error(files):
    if len(files) > CASE_ATTACHMENT_MAX_FILES:
        return f"Attach no more than {CASE_ATTACHMENT_MAX_FILES} files to one case action."
    for upload in files:
        extension = Path(upload.name or "").suffix.lower()
        if extension not in CASE_ATTACHMENT_EXTENSIONS:
            allowed = ", ".join(sorted(CASE_ATTACHMENT_EXTENSIONS))
            return f"{upload.name} is not an allowed attachment type. Allowed types: {allowed}."
        if upload.size and upload.size > CASE_ATTACHMENT_MAX_SIZE:
            return f"{upload.name} is too large. Maximum file size is 15 MB."
    return ""


def _save_case_attachments(case, event, user, files):
    for upload in files:
        ComplaintCaseAttachment.objects.create(
            case=case,
            event=event,
            uploaded_by=user if getattr(user, "is_authenticated", False) else None,
            file=upload,
            original_filename=upload.name or "attachment",
            content_type=getattr(upload, "content_type", "") or "",
            file_size=getattr(upload, "size", 0) or 0,
        )


def _save_discipline_attachments(case, event, user, files):
    for upload in files:
        DisciplinaryCaseAttachment.objects.create(
            case=case,
            event=event,
            uploaded_by=user if getattr(user, "is_authenticated", False) else None,
            file=upload,
            original_filename=upload.name or "attachment",
            content_type=getattr(upload, "content_type", "") or "",
            file_size=getattr(upload, "size", 0) or 0,
        )


def _office_filter_options(user):
    if is_system_admin(user):
        return [
            ("all", "All offices"),
            ("general", "General Registry"),
            ("nursing", "Nursing Council"),
            ("medical", "Medical Board"),
        ]
    scope = staff_complaint_scope(user)
    if scope == "medical":
        return [("medical", "Medical Board"), ("general", "General Registry")]
    if scope == "nursing":
        return [("nursing", "Nursing Council"), ("general", "General Registry")]
    return [("general", "General Registry")]


def _allowed_office_scope(user, requested_scope):
    requested_scope = requested_scope if requested_scope in {"general", "nursing", "medical", "all"} else "all"
    if is_system_admin(user):
        return "" if requested_scope == "all" else requested_scope
    if requested_scope == "all":
        return ""
    scope = staff_complaint_scope(user)
    if requested_scope == "general":
        return "general"
    if scope and requested_scope in {"all", scope}:
        return scope
    return scope or "general"


def _staff_can_use_office_scope(user, office_scope):
    if is_system_admin(user):
        return True
    if office_scope == "general" and is_staff_dashboard_user(user):
        return True
    return can_access_staff_domain(user, office_scope)


def _enquiry_visible_to_user(enquiry, user):
    if not enquiry:
        return False
    if is_system_admin(user):
        return True
    if enquiry.created_by_id == user.id or enquiry.assigned_to_id == user.id or enquiry.recipient_user_id == user.id:
        return True
    if enquiry.office == "general" and is_staff_dashboard_user(user):
        return True
    return can_access_staff_domain(user, enquiry.office)


def _enquiry_prefill(enquiry):
    latest_message = enquiry.messages.order_by("-created_at").first()
    body = latest_message.body if latest_message else ""
    return {
        "title": enquiry.subject,
        "description": body or f"Complaint case opened from enquiry thread {enquiry.pk}.",
        "office_scope": enquiry.office if enquiry.office in {"general", "nursing", "medical"} else "general",
        "source": "enquiry",
        "complainant_name": enquiry.created_by.get_full_name() or enquiry.created_by.username,
        "complainant_email": enquiry.created_by.email,
        "subject_name": enquiry.recipient_name,
        "source_enquiry": enquiry,
    }


@login_required
def complaint_case_list(request):
    if not can_access_complaints_workspace(request.user):
        raise PermissionDenied("Complaints case management is only available to authorised staff.")

    selected_scope = _allowed_office_scope(request.user, request.GET.get("office", "all"))
    queryset = scoped_complaint_cases(request.user)
    if selected_scope:
        queryset = queryset.filter(office_scope=selected_scope)

    status = request.GET.get("status", "open")
    if status == "open":
        queryset = queryset.exclude(status__in=["resolved", "closed", "withdrawn"])
    elif status and status != "all":
        queryset = queryset.filter(status=status)

    priority = request.GET.get("priority", "all")
    if priority in {"low", "normal", "high", "critical"}:
        queryset = queryset.filter(priority=priority)

    query = request.GET.get("q", "").strip()
    if query:
        queryset = queryset.filter(
            Q(case_number__icontains=query)
            | Q(title__icontains=query)
            | Q(description__icontains=query)
            | Q(complainant_name__icontains=query)
            | Q(complainant_email__icontains=query)
            | Q(subject_name__icontains=query)
            | Q(subject_identifier__icontains=query)
        )

    status_counts = scoped_complaint_cases(request.user).values("status").annotate(total=Count("id"))
    paginator = Paginator(queryset, 25)
    page = paginator.get_page(request.GET.get("page"))

    return render(request, "complaints/case_list.html", {
        "cases": page,
        "summary": complaint_summary_for_user(request.user),
        "status_counts": {row["status"]: row["total"] for row in status_counts},
        "office_options": _office_filter_options(request.user),
        "selected_office": selected_scope or "all",
        "selected_status": status,
        "selected_priority": priority,
        "query": query,
        "status_choices": ComplaintCase.STATUS_CHOICES,
        "priority_choices": ComplaintCase.PRIORITY_CHOICES,
    })


@login_required
def complaint_case_create(request):
    if not can_access_complaints_workspace(request.user):
        raise PermissionDenied("Complaints case management is only available to authorised staff.")

    enquiry = None
    initial = {}
    enquiry_id = request.GET.get("enquiry") or request.POST.get("source_enquiry_id")
    if enquiry_id:
        enquiry = EnquiryThread.objects.filter(pk=enquiry_id).prefetch_related("messages").select_related("created_by").first()
        if enquiry and not _enquiry_visible_to_user(enquiry, request.user):
            raise PermissionDenied("You cannot open a case from this enquiry.")
        if enquiry:
            initial.update(_enquiry_prefill(enquiry))

    if request.method == "POST":
        form = ComplaintStaffCaseForm(request.POST, request.FILES, initial=initial)
        files = request.FILES.getlist("attachments")
        attachment_error = _attachment_error(files)
        if attachment_error:
            messages.error(request, attachment_error)
        elif form.is_valid():
            case = form.save(commit=False)
            if not _staff_can_use_office_scope(request.user, case.office_scope):
                form.add_error("office_scope", "You cannot open an ICMS case for that office scope.")
                return render(request, "complaints/case_form.html", {
                    "form": form,
                    "source_enquiry": enquiry,
                })
            case.created_by = request.user
            case.source_enquiry = enquiry
            if enquiry:
                case.source = "enquiry"
            if case.assigned_to_id and case.status == "new":
                case.status = "assigned"
            case.save()
            event = ComplaintCaseEvent.objects.create(
                case=case,
                action_type="intake",
                created_by=request.user,
                to_status=case.status,
                body="Formal ICMS case opened.",
                metadata={"source_enquiry_id": enquiry.pk if enquiry else None},
            )
            _save_case_attachments(case, event, request.user, files)
            messages.success(request, f"ICMS case {case.case_number} has been opened.")
            return redirect("complaint_case_detail", case_uuid=case.case_uuid)
    else:
        form = ComplaintStaffCaseForm(initial=initial)

    return render(request, "complaints/case_form.html", {
        "form": form,
        "source_enquiry": enquiry,
    })


@login_required
def complaint_case_detail(request, case_uuid):
    case = get_object_or_404(
        scoped_complaint_cases(request.user).select_related("assigned_to", "created_by", "source_enquiry"),
        case_uuid=case_uuid,
    )
    if not can_access_complaint_case(request.user, case):
        raise PermissionDenied("You cannot access this complaint case.")

    update_form = ComplaintCaseUpdateForm(instance=case)
    event_form = ComplaintCaseEventForm()
    if request.method == "POST":
        form_name = request.POST.get("form_name")
        if form_name == "update":
            old_status = ComplaintCase.objects.only("status").get(pk=case.pk).status
            old_assignee_id = ComplaintCase.objects.only("assigned_to").get(pk=case.pk).assigned_to_id
            update_form = ComplaintCaseUpdateForm(request.POST, instance=case)
            if update_form.is_valid():
                updated_case = update_form.save(commit=False)
                if updated_case.status in {"closed", "resolved", "withdrawn"} and not updated_case.closure_summary:
                    messages.error(request, "Add a closure summary before resolving, closing, or withdrawing the case.")
                else:
                    updated_case.save()
                    action_type = "status_change" if old_status != updated_case.status else "assignment" if old_assignee_id != updated_case.assigned_to_id else "note"
                    ComplaintCaseEvent.objects.create(
                        case=updated_case,
                        action_type=action_type,
                        created_by=request.user,
                        from_status=old_status if old_status != updated_case.status else "",
                        to_status=updated_case.status if old_status != updated_case.status else "",
                        body="Case fields updated.",
                        metadata={
                            "old_assigned_to_id": old_assignee_id,
                            "new_assigned_to_id": updated_case.assigned_to_id,
                            "priority": updated_case.priority,
                            "risk_level": updated_case.risk_level,
                        },
                    )
                    messages.success(request, "Case details updated.")
                    return redirect("complaint_case_detail", case_uuid=case.case_uuid)
        elif form_name == "event":
            event_form = ComplaintCaseEventForm(request.POST)
            files = request.FILES.getlist("attachments")
            attachment_error = _attachment_error(files)
            if attachment_error:
                messages.error(request, attachment_error)
            elif event_form.is_valid():
                event = event_form.save(commit=False)
                event.case = case
                event.created_by = request.user
                if event.action_type == "closure":
                    old_status = case.status
                    case.status = "resolved"
                    case.closed_at = timezone.now()
                    if not case.closure_summary:
                        case.closure_summary = event.body
                    case.save(update_fields=["status", "closed_at", "closure_summary", "updated_at"])
                    event.from_status = old_status
                    event.to_status = case.status
                event.save()
                _save_case_attachments(case, event, request.user, files)
                messages.success(request, "Case action recorded.")
                return redirect("complaint_case_detail", case_uuid=case.case_uuid)
        else:
            messages.error(request, "Unknown case action.")

    return render(request, "complaints/case_detail.html", {
        "case": case,
        "events": case.events.select_related("created_by").prefetch_related("attachments"),
        "update_form": update_form,
        "event_form": event_form,
    })


def complaint_public_submit(request):
    submitted_case = None
    if request.method == "POST":
        form = ComplaintPublicIntakeForm(request.POST, request.FILES)
        files = request.FILES.getlist("attachments")
        attachment_error = _attachment_error(files)
        if attachment_error:
            messages.error(request, attachment_error)
        elif form.is_valid():
            case = form.save(commit=False)
            case.source = "public_portal"
            case.is_public_submission = True
            case.status = "new"
            case.priority = "normal"
            case.risk_level = "medium"
            if request.user.is_authenticated:
                case.created_by = request.user
                case.complainant_user = request.user
            case.save()
            event = ComplaintCaseEvent.objects.create(
                case=case,
                action_type="intake",
                created_by=request.user if request.user.is_authenticated else None,
                to_status=case.status,
                body="Public complaint submitted through the portal.",
            )
            _save_case_attachments(case, event, request.user, files)
            submitted_case = case
            form = ComplaintPublicIntakeForm()
    else:
        form = ComplaintPublicIntakeForm()

    return render(request, "complaints/public_complaint_form.html", {
        "form": form,
        "submitted_case": submitted_case,
    })


@login_required
@require_POST
def complaint_case_acknowledge(request, case_uuid):
    case = get_object_or_404(scoped_complaint_cases(request.user), case_uuid=case_uuid)
    if not can_access_complaint_case(request.user, case):
        raise PermissionDenied("You cannot access this complaint case.")
    if not case.acknowledged_at:
        case.acknowledged_at = timezone.now()
        if case.status == "new":
            case.status = "triage"
        case.save(update_fields=["acknowledged_at", "status", "updated_at"])
        ComplaintCaseEvent.objects.create(
            case=case,
            action_type="triage",
            created_by=request.user,
            to_status=case.status,
            body="Case acknowledged for triage.",
        )
        messages.success(request, "Case acknowledged for triage.")
    return redirect("complaint_case_detail", case_uuid=case.case_uuid)


def _complaint_prefill_for_discipline(case):
    return {
        "office_scope": case.office_scope,
        "subject_name": case.subject_name or case.title,
        "subject_identifier": case.subject_identifier,
        "allegation_summary": case.description,
        "stage": "preliminary_assessment",
        "status": "open",
        "severity": "high" if case.risk_level in {"high", "critical"} else "medium",
    }


@login_required
def disciplinary_case_list(request):
    if not can_access_complaints_workspace(request.user):
        raise PermissionDenied("Disciplinary case management is only available to authorised staff.")

    selected_scope = _allowed_office_scope(request.user, request.GET.get("office", "all"))
    queryset = scoped_disciplinary_cases(request.user)
    if selected_scope:
        queryset = queryset.filter(office_scope=selected_scope)

    stage = request.GET.get("stage", "open")
    if stage == "open":
        queryset = queryset.exclude(status__in=["closed", "withdrawn"])
    elif stage and stage != "all":
        queryset = queryset.filter(stage=stage)

    query = request.GET.get("q", "").strip()
    if query:
        queryset = queryset.filter(
            Q(discipline_number__icontains=query)
            | Q(subject_name__icontains=query)
            | Q(subject_identifier__icontains=query)
            | Q(allegation_summary__icontains=query)
            | Q(source_complaint__case_number__icontains=query)
        )

    paginator = Paginator(queryset, 25)
    return render(request, "complaints/disciplinary_case_list.html", {
        "cases": paginator.get_page(request.GET.get("page")),
        "summary": discipline_summary_for_user(request.user),
        "office_options": _office_filter_options(request.user),
        "selected_office": selected_scope or "all",
        "selected_stage": stage,
        "stage_choices": DisciplinaryCase.STAGE_CHOICES,
        "query": query,
    })


@login_required
def disciplinary_case_create(request):
    if not can_access_complaints_workspace(request.user):
        raise PermissionDenied("Disciplinary case management is only available to authorised staff.")

    source_complaint = None
    initial = {}
    complaint_uuid = request.GET.get("complaint") or request.POST.get("source_complaint_uuid")
    if complaint_uuid:
        source_complaint = get_object_or_404(scoped_complaint_cases(request.user), case_uuid=complaint_uuid)
        if not can_access_complaint_case(request.user, source_complaint):
            raise PermissionDenied("You cannot open a discipline case from this ICMS case.")
        initial.update(_complaint_prefill_for_discipline(source_complaint))

    if request.method == "POST":
        form = DisciplinaryCaseForm(request.POST, request.FILES, initial=initial)
        files = request.FILES.getlist("attachments")
        attachment_error = _attachment_error(files)
        if attachment_error:
            messages.error(request, attachment_error)
        elif form.is_valid():
            case = form.save(commit=False)
            if not _staff_can_use_office_scope(request.user, case.office_scope):
                form.add_error("office_scope", "You cannot open a discipline case for that office scope.")
            else:
                case.created_by = request.user
                case.source_complaint = source_complaint
                case.save()
                event = DisciplinaryCaseEvent.objects.create(
                    case=case,
                    action_type="intake",
                    created_by=request.user,
                    to_stage=case.stage,
                    body="Formal disciplinary case opened.",
                    metadata={"source_complaint_id": source_complaint.pk if source_complaint else None},
                )
                _save_discipline_attachments(case, event, request.user, files)
                if source_complaint and source_complaint.status not in {"closed", "resolved", "withdrawn"}:
                    source_complaint.status = "escalated"
                    source_complaint.save(update_fields=["status", "updated_at"])
                    ComplaintCaseEvent.objects.create(
                        case=source_complaint,
                        action_type="escalation",
                        created_by=request.user,
                        to_status=source_complaint.status,
                        body=f"Escalated to disciplinary case {case.discipline_number}.",
                    )
                messages.success(request, f"Disciplinary case {case.discipline_number} has been opened.")
                return redirect("disciplinary_case_detail", discipline_uuid=case.discipline_uuid)
    else:
        form = DisciplinaryCaseForm(initial=initial)

    return render(request, "complaints/disciplinary_case_form.html", {
        "form": form,
        "source_complaint": source_complaint,
    })


@login_required
def disciplinary_case_detail(request, discipline_uuid):
    case = get_object_or_404(scoped_disciplinary_cases(request.user), discipline_uuid=discipline_uuid)
    if not can_access_disciplinary_case(request.user, case):
        raise PermissionDenied("You cannot access this disciplinary case.")

    update_form = DisciplinaryCaseUpdateForm(instance=case)
    event_form = DisciplinaryCaseEventForm()
    decision_initial = {
        "office_scope": case.office_scope,
        "decision_type": "discipline",
        "title": f"Decision for {case.discipline_number}",
        "subject_name": case.subject_name,
        "subject_identifier": case.subject_identifier,
        "related_complaint": case.source_complaint,
        "evidence_summary": case.allegation_summary,
        "authority_reference": case.statutory_basis,
        "decided_by": request.user.pk,
    }
    decision_form = RegulatoryDecisionRecordForm(initial=decision_initial)

    if request.method == "POST":
        form_name = request.POST.get("form_name")
        if form_name == "update":
            old_stage = DisciplinaryCase.objects.only("stage").get(pk=case.pk).stage
            old_assignee_id = DisciplinaryCase.objects.only("assigned_to").get(pk=case.pk).assigned_to_id
            update_form = DisciplinaryCaseUpdateForm(request.POST, instance=case)
            if update_form.is_valid():
                updated_case = update_form.save()
                action_type = "stage_change" if old_stage != updated_case.stage else "assignment" if old_assignee_id != updated_case.assigned_to_id else "note"
                DisciplinaryCaseEvent.objects.create(
                    case=updated_case,
                    action_type=action_type,
                    created_by=request.user,
                    from_stage=old_stage if old_stage != updated_case.stage else "",
                    to_stage=updated_case.stage if old_stage != updated_case.stage else "",
                    body="Disciplinary case fields updated.",
                    metadata={
                        "old_assigned_to_id": old_assignee_id,
                        "new_assigned_to_id": updated_case.assigned_to_id,
                        "status": updated_case.status,
                        "severity": updated_case.severity,
                        "sanction_type": updated_case.sanction_type,
                    },
                )
                messages.success(request, "Disciplinary case updated.")
                return redirect("disciplinary_case_detail", discipline_uuid=case.discipline_uuid)
        elif form_name == "event":
            event_form = DisciplinaryCaseEventForm(request.POST)
            files = request.FILES.getlist("attachments")
            attachment_error = _attachment_error(files)
            if attachment_error:
                messages.error(request, attachment_error)
            elif event_form.is_valid():
                event = event_form.save(commit=False)
                event.case = case
                event.created_by = request.user
                event.save()
                _save_discipline_attachments(case, event, request.user, files)
                messages.success(request, "Disciplinary action recorded.")
                return redirect("disciplinary_case_detail", discipline_uuid=case.discipline_uuid)
        elif form_name == "decision":
            decision_form = RegulatoryDecisionRecordForm(request.POST)
            if decision_form.is_valid():
                decision = decision_form.save(commit=False)
                if not _staff_can_use_office_scope(request.user, decision.office_scope):
                    decision_form.add_error("office_scope", "You cannot create a decision for that office scope.")
                else:
                    decision.created_by = request.user
                    decision.related_complaint = case.source_complaint
                    decision.subject_content_type = case.subject_content_type
                    decision.subject_object_id = case.subject_object_id
                    decision.save()
                    case.decision_record = decision
                    case.stage = "decision"
                    case.status = "decided"
                    case.save(update_fields=["decision_record", "stage", "status", "updated_at"])
                    DisciplinaryCaseEvent.objects.create(
                        case=case,
                        action_type="decision",
                        created_by=request.user,
                        to_stage=case.stage,
                        body=f"Formal decision recorded: {decision.decision_number}.",
                        metadata={"decision_id": decision.pk},
                    )
                    messages.success(request, f"Decision {decision.decision_number} recorded.")
                    return redirect("disciplinary_case_detail", discipline_uuid=case.discipline_uuid)
        else:
            messages.error(request, "Unknown disciplinary case action.")

    return render(request, "complaints/disciplinary_case_detail.html", {
        "case": case,
        "events": case.events.select_related("created_by").prefetch_related("attachments"),
        "update_form": update_form,
        "event_form": event_form,
        "decision_form": decision_form,
    })


@login_required
def regulatory_decision_list(request):
    if not can_access_complaints_workspace(request.user):
        raise PermissionDenied("The decision register is only available to authorised staff.")

    selected_scope = _allowed_office_scope(request.user, request.GET.get("office", "all"))
    queryset = scoped_decision_records(request.user)
    if selected_scope:
        queryset = queryset.filter(office_scope=selected_scope)

    decision_type = request.GET.get("type", "all")
    if decision_type != "all":
        queryset = queryset.filter(decision_type=decision_type)

    query = request.GET.get("q", "").strip()
    if query:
        queryset = queryset.filter(
            Q(decision_number__icontains=query)
            | Q(title__icontains=query)
            | Q(subject_name__icontains=query)
            | Q(subject_identifier__icontains=query)
            | Q(decision_text__icontains=query)
        )

    paginator = Paginator(queryset, 25)
    return render(request, "complaints/decision_list.html", {
        "decisions": paginator.get_page(request.GET.get("page")),
        "office_options": _office_filter_options(request.user),
        "selected_office": selected_scope or "all",
        "selected_type": decision_type,
        "decision_type_choices": RegulatoryDecisionRecord.DECISION_TYPE_CHOICES,
        "query": query,
    })


@login_required
def regulatory_decision_detail(request, decision_uuid):
    decision = get_object_or_404(scoped_decision_records(request.user), decision_uuid=decision_uuid)
    if not can_access_decision_record(request.user, decision):
        raise PermissionDenied("You cannot access this regulatory decision.")
    return render(request, "complaints/decision_detail.html", {"decision": decision})
