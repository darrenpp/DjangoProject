from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.dashboard.access import (
    is_data_quality_reviewer,
    is_finance_reviewer,
    is_medical_board_staff,
    is_nursing_council_staff,
    is_system_admin,
)

from .models import NHWAWebWorkbook
from .population import populate_workbooks_from_2026_registry
from .services import (
    bootstrap_web_workbooks,
    build_submission_pack,
    build_sheet_grid,
    build_sheet_header_fields,
    ensure_sheet_entry_state,
    lock_workbooks_for_signoff,
    save_sheet_entries,
    sheet_completion,
    sheet_scope_note,
    source_document_statuses,
    unlock_workbooks,
    workbook_completion,
    workbook_readiness,
)


def _allowed_scopes(user):
    if is_system_admin(user):
        return ["nursing", "medical"]
    if is_data_quality_reviewer(user) or is_finance_reviewer(user):
        return ["nursing", "medical"]
    scopes = []
    if is_nursing_council_staff(user):
        scopes.append("nursing")
    if is_medical_board_staff(user):
        scopes.append("medical")
    if scopes:
        return scopes
    return []


def _can_edit_workbook(user, workbook):
    if workbook.status != "active":
        return False
    return is_system_admin(user) and workbook.office_scope in _allowed_scopes(user)


def _can_run_alignment_actions(user):
    return is_system_admin(user)


def _scopes_from_request(request):
    scope = request.POST.get("scope") or request.GET.get("scope") or "all"
    allowed = _allowed_scopes(request.user)
    if scope == "all":
        return tuple(allowed)
    if scope in allowed:
        return (scope,)
    return tuple()


def _workbook_cards_for_user(user):
    workbooks = list(
        NHWAWebWorkbook.objects
        .filter(office_scope__in=_allowed_scopes(user))
        .prefetch_related("sheets")
        .order_by("office_scope", "title")
    )
    return [
        {
            "workbook": workbook,
            "completion": workbook_completion(workbook),
            "readiness": workbook_readiness(workbook),
            "can_edit": _can_edit_workbook(user, workbook),
        }
        for workbook in workbooks
    ]


def _safe_next_url(request, fallback_name="nhwa_alignment_centre"):
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return reverse(fallback_name)


def _sheet_group_label(sheet):
    source_name = sheet.source_sheet_name
    if source_name == "GUIDE":
        return "Setup"
    if source_name in {"T1_PHA_ESTABLISHMENT", "T2_TRAINING_SCHOOL", "T3_COUNCIL_REGISTER"}:
        return "Workforce"
    if source_name == "T4_FINANCE":
        return "Finance"
    if source_name == "DATA_QUALITY_CHECKLIST":
        return "Quality"
    return "Reference"


def _completion_status(sheet, completion):
    if not sheet.editable:
        return {"label": "Reference", "tone": "secondary"}
    if completion["editable"] == 0:
        return {"label": "No Entry Cells", "tone": "secondary"}
    if completion["missing"] == 0:
        return {"label": "Complete", "tone": "success"}
    if completion["filled"]:
        return {"label": "In Progress", "tone": "warning"}
    return {"label": "Not Started", "tone": "danger"}


def _sheet_tab_rows(sheets, readiness, current_sheet):
    completion_by_sheet_id = {
        row["sheet"].id: row["completion"]
        for row in readiness["sheet_rows"]
    }
    rows = []
    for candidate in sheets:
        completion = completion_by_sheet_id.get(candidate.id) or sheet_completion(candidate)
        rows.append({
            "sheet": candidate,
            "group": _sheet_group_label(candidate),
            "completion": completion,
            "status": _completion_status(candidate, completion),
            "is_current": candidate.id == current_sheet.id,
        })
    return rows


def _actor_label(actor):
    if not actor:
        return "System"
    display_name = actor.get_full_name() if hasattr(actor, "get_full_name") else ""
    return display_name or getattr(actor, "username", "") or "System"


def _workbook_status_cards(workbook, readiness, latest_save_event):
    completion = readiness["completion"]
    status_tone = {
        "active": "success",
        "draft": "warning",
        "locked": "primary",
        "archived": "secondary",
    }.get(workbook.status, "secondary")
    checklist_label = "Complete" if readiness["checklist_complete"] else "Incomplete"
    export_label = "Ready" if readiness["export_ready"] else "Blocked"
    signoff_label = "Ready" if readiness["ready_for_signoff"] else "Not Ready"
    return [
        {
            "label": "Workbook Status",
            "value": workbook.get_status_display(),
            "detail": "Sign-off locked" if workbook.status == "locked" else "Open for controlled entry",
            "tone": status_tone,
        },
        {
            "label": "Reporting Year",
            "value": workbook.reporting_year,
            "detail": workbook.source_version or "Source version not set",
            "tone": "info",
        },
        {
            "label": "Completion",
            "value": f"{completion['percent']}%",
            "detail": f"{completion['filled']} of {completion['editable']} entry cells",
            "tone": "success" if completion["percent"] >= 95 else "warning" if completion["percent"] else "danger",
        },
        {
            "label": "Quality Checklist",
            "value": checklist_label,
            "detail": "Required before sign-off",
            "tone": "success" if readiness["checklist_complete"] else "danger",
        },
        {
            "label": "Sign-off",
            "value": signoff_label,
            "detail": "System Admin action after checklist",
            "tone": "success" if readiness["ready_for_signoff"] else "secondary",
        },
        {
            "label": "Export",
            "value": export_label,
            "detail": "Export only after locked sign-off",
            "tone": "success" if readiness["export_ready"] else "warning",
        },
        {
            "label": "Last Saved",
            "value": latest_save_event.created_at.strftime("%d %b %Y %H:%M") if latest_save_event else "No saves yet",
            "detail": _actor_label(getattr(latest_save_event, "actor", None)) if latest_save_event else "No audit event",
            "tone": "info",
        },
    ]


def _sheet_validation_issues(sheet, readiness, header_fields, scope_note):
    completion = sheet_completion(sheet)
    issues = []
    missing_header_fields = [
        field for field in header_fields
        if field.get("is_editable") and not str(field.get("value") or "").strip()
    ]
    if sheet.editable and completion["missing"]:
        examples = ", ".join(completion["missing_examples"])
        issues.append({
            "title": "Entry cells still need values",
            "detail": f"{completion['missing']} editable cell(s) are blank. Examples: {examples or 'No examples available'}.",
            "tone": "warning",
            "icon": "fas fa-pen-to-square",
        })
    elif sheet.editable:
        issues.append({
            "title": "Current sheet entry cells are complete",
            "detail": "All visible editable cells on this sheet have stored values.",
            "tone": "success",
            "icon": "fas fa-circle-check",
        })
    else:
        issues.append({
            "title": "Reference-only sheet",
            "detail": "This sheet is retained for classification and source guidance; it cannot be edited here.",
            "tone": "secondary",
            "icon": "fas fa-lock",
        })

    if missing_header_fields:
        labels = ", ".join(field["label"] for field in missing_header_fields)
        issues.append({
            "title": "Reporting header details are incomplete",
            "detail": f"Complete these header fields before sign-off: {labels}.",
            "tone": "warning",
            "icon": "fas fa-list-check",
        })

    if readiness["checklist_complete"]:
        issues.append({
            "title": "Data Quality Checklist is complete",
            "detail": "The workbook can be locked when the remaining sheet checks are acceptable.",
            "tone": "success",
            "icon": "fas fa-shield-check",
        })
    else:
        issues.append({
            "title": "Data Quality Checklist blocks sign-off",
            "detail": "Complete the Data Quality Checklist before locking this workbook for NHWA submission.",
            "tone": "danger",
            "icon": "fas fa-triangle-exclamation",
        })

    if readiness["export_ready"]:
        issues.append({
            "title": "Export-ready workbook",
            "detail": "This workbook is locked and can be included in the NHWA submission pack.",
            "tone": "success",
            "icon": "fas fa-file-export",
        })
    elif readiness["ready_for_signoff"]:
        issues.append({
            "title": "Ready for sign-off lock",
            "detail": "System Admin can lock this workbook once the registrar confirms the captured values.",
            "tone": "success",
            "icon": "fas fa-lock",
        })

    if scope_note:
        issues.append({
            "title": "Office scope filter applied",
            "detail": scope_note,
            "tone": "info",
            "icon": "fas fa-filter",
        })
    return issues


@login_required
def workbook_index(request):
    scopes = _allowed_scopes(request.user)
    if not scopes:
        raise Http404("NHWA workbooks are not available for this account.")

    cards = _workbook_cards_for_user(request.user)
    return render(
        request,
        "nhwa_workbooks/index.html",
        {
            "cards": cards,
            "has_workbooks": bool(cards),
        },
    )


@login_required
def alignment_centre(request):
    scopes = _allowed_scopes(request.user)
    if not scopes:
        raise Http404("NHWA alignment centre is not available for this account.")

    cards = _workbook_cards_for_user(request.user)
    recent_events = []
    if cards:
        workbook_ids = [card["workbook"].id for card in cards]
        recent_events = (
            cards[0]["workbook"].audit_events.model.objects
            .filter(workbook_id__in=workbook_ids)
            .select_related("workbook", "actor")
            .order_by("-created_at")[:12]
        )
    return render(
        request,
        "nhwa_workbooks/alignment_centre.html",
        {
            "cards": cards,
            "has_workbooks": bool(cards),
            "source_documents": source_document_statuses(),
            "can_run_actions": _can_run_alignment_actions(request.user),
            "recent_events": recent_events,
        },
    )


@login_required
@require_POST
def alignment_action(request):
    if not _can_run_alignment_actions(request.user):
        raise Http404("NHWA alignment actions are restricted to System Admin users.")

    action = request.POST.get("action", "")
    scopes = _scopes_from_request(request)
    if not scopes:
        messages.error(request, "No valid NHWA office scope was selected.")
        return redirect("nhwa_alignment_centre")

    if action == "bootstrap":
        result = bootstrap_web_workbooks(actor=request.user)
        messages.success(
            request,
            "NHWA toolkit bootstrapped: "
            f"{result['workbooks']} new workbook(s), {result['sheets']} new sheet(s), "
            f"{result['cells']} new cell template(s).",
        )
    elif action == "populate_2026":
        result = populate_workbooks_from_2026_registry(actor=request.user, year=2026, scopes=scopes)
        total_changed = sum(row["changed_cells"] for row in result.values())
        messages.success(request, f"NHWA web workbooks populated from verified 2026 platform data: {total_changed} cell(s) changed.")
    elif action == "lock_signoff":
        result = lock_workbooks_for_signoff(actor=request.user, scopes=scopes)
        if result["blocked"]:
            blocked_names = ", ".join(item["workbook"].title for item in result["blocked"])
            messages.error(request, f"Sign-off blocked until the Data Quality Checklist is complete: {blocked_names}.")
        if result["locked"]:
            locked_names = ", ".join(workbook.title for workbook in result["locked"])
            messages.success(request, f"NHWA workbook sign-off locked: {locked_names}.")
    elif action == "unlock":
        unlocked = unlock_workbooks(actor=request.user, scopes=scopes)
        if unlocked:
            messages.success(request, f"Reopened {len(unlocked)} NHWA workbook(s) for correction.")
        else:
            messages.info(request, "No locked NHWA workbooks were available for the selected scope.")
    else:
        messages.error(request, "Unknown NHWA alignment action.")
    return redirect(_safe_next_url(request))


@login_required
def export_submission_pack(request):
    if not _can_run_alignment_actions(request.user):
        raise Http404("NHWA export is restricted to System Admin users.")
    scopes = _scopes_from_request(request)
    workbooks = list(
        NHWAWebWorkbook.objects
        .filter(office_scope__in=scopes)
        .prefetch_related("sheets__cell_templates__entry")
        .order_by("office_scope", "title")
    )
    if not workbooks:
        messages.error(request, "No NHWA workbooks are available for export.")
        return redirect("nhwa_alignment_centre")
    unlocked = [workbook.title for workbook in workbooks if workbook.status != "locked"]
    if unlocked:
        messages.error(request, "Export blocked until workbook sign-off is locked: " + ", ".join(unlocked))
        return redirect("nhwa_alignment_centre")

    content = build_submission_pack(workbooks, actor=request.user)
    response = HttpResponse(content, content_type="application/zip")
    response["Content-Disposition"] = 'attachment; filename="NHWA_Submission_Pack_2026.zip"'
    return response


@login_required
def workbook_detail(request, slug):
    scopes = _allowed_scopes(request.user)
    workbook = get_object_or_404(
        NHWAWebWorkbook.objects.prefetch_related("sheets"),
        slug=slug,
        office_scope__in=scopes,
    )
    sheets = list(workbook.sheets.all())
    if not sheets:
        messages.warning(request, "This NHWA web workbook has no sheet templates yet. Run the bootstrap command first.")
        return redirect("nhwa_workbook_index")
    for candidate in sheets:
        ensure_sheet_entry_state(candidate)

    requested_sheet_id = request.GET.get("sheet")
    sheet = None
    if requested_sheet_id:
        sheet = next((candidate for candidate in sheets if str(candidate.id) == str(requested_sheet_id)), None)
    if sheet is None:
        sheet = next((candidate for candidate in sheets if candidate.source_sheet_name == "T3_COUNCIL_REGISTER"), sheets[0])

    ensure_sheet_entry_state(sheet)
    can_edit = _can_edit_workbook(request.user, workbook) and sheet.editable
    if request.method == "POST":
        if not can_edit:
            raise Http404("This NHWA sheet is read-only for this account.")
        build_sheet_header_fields(sheet)
        changed = save_sheet_entries(sheet, request.POST, request.user, request)
        if changed:
            messages.success(request, f"Saved {changed} workbook cell update(s). Formula cells remain locked and are recalculated on screen.")
        else:
            messages.info(request, "No workbook cell values changed.")
        return redirect(f"{reverse('nhwa_workbook_detail', args=[workbook.slug])}?sheet={sheet.id}")

    sheet = (
        workbook.sheets.filter(id=sheet.id)
        .prefetch_related("cell_templates__entry")
        .get()
    )
    ensure_sheet_entry_state(sheet)
    header_fields = build_sheet_header_fields(sheet)
    readiness = workbook_readiness(workbook)
    latest_save_event = (
        workbook.audit_events
        .filter(action__in=["SHEET_SAVED", "LOCKED", "UNLOCKED"])
        .select_related("actor")
        .order_by("-created_at")
        .first()
    )
    scope_note = sheet_scope_note(sheet)
    can_run_actions = _can_run_alignment_actions(request.user)
    return render(
        request,
        "nhwa_workbooks/workbook.html",
        {
            "workbook": workbook,
            "sheets": sheets,
            "sheet": sheet,
            "grid_rows": build_sheet_grid(sheet),
            "header_fields": header_fields,
            "header_field_ids": [field["template_id"] for field in header_fields],
            "scope_note": scope_note,
            "completion": readiness["completion"],
            "readiness": readiness,
            "sheet_tab_rows": _sheet_tab_rows(sheets, readiness, sheet),
            "sheet_completion": sheet_completion(sheet),
            "workbook_status_cards": _workbook_status_cards(workbook, readiness, latest_save_event),
            "validation_issues": _sheet_validation_issues(sheet, readiness, header_fields, scope_note),
            "recent_audit_events": (
                workbook.audit_events
                .select_related("actor", "sheet")
                .order_by("-created_at")[:8]
            ),
            "can_edit": can_edit,
            "can_run_actions": can_run_actions,
            "can_lock_signoff": can_run_actions and readiness["ready_for_signoff"],
            "can_unlock_workbook": can_run_actions and workbook.status == "locked",
            "can_export_submission_pack": can_run_actions and readiness["export_ready"],
        },
    )
