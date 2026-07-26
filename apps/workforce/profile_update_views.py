"""Views for staged professional-profile update requests."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.dashboard.access import (
    can_access_staff_domain,
    can_manage_regulatory_operations,
    is_medical_board_staff,
    is_nursing_council_staff,
    professional_domain,
)

from .models import ProfessionalProfileUpdateRequest
from .profile_updates import (
    ProfessionalProfileUpdateRequestForm,
    build_professional_identity_context,
    create_profile_update_request,
    profile_update_requests_for,
    review_profile_update_request,
)


def _linked_professional_for_request(user):
    """Only the linked account holder can submit a self-service proposal."""

    if getattr(user, "professional_record_status", "") != "linked":
        return None
    professional = getattr(user, "professional_record", None)
    if professional is None or professional_domain(professional) not in {"medical", "nursing"}:
        return None
    return professional


@login_required
def professional_profile_update_request(request):
    professional = _linked_professional_for_request(request.user)
    if professional is None:
        messages.warning(request, "Link and verify your professional record before submitting a profile update.")
        return redirect("professional_dashboard")

    if request.method == "POST":
        form = ProfessionalProfileUpdateRequestForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                update_request = create_profile_update_request(
                    professional=professional,
                    requested_by=request.user,
                    form=form,
                )
            except ValueError as exc:
                form.add_error(None, str(exc))
            else:
                messages.success(
                    request,
                    f"Your {update_request.get_update_type_display().lower()} request was submitted for regulatory review. "
                    "Your official record has not changed yet.",
                )
                return redirect("professional_profile_update_request")
    else:
        form = ProfessionalProfileUpdateRequestForm(initial={
            "primary_phone": getattr(professional, "primary_phone", ""),
            "email": getattr(professional, "email", ""),
            "province": getattr(professional, "province", ""),
        })

    context = {
        "form": form,
        "professional": professional,
        "profile_update_requests": profile_update_requests_for(professional)[:20],
    }
    context.update(build_professional_identity_context(professional))
    return render(request, "workforce/professional_profile_update_request.html", context)


def _review_scope_for(user, requested_scope):
    if getattr(user, "role", "") == "admin":
        return requested_scope if requested_scope in {"medical", "nursing"} else "nursing"
    if is_medical_board_staff(user):
        return "medical"
    if is_nursing_council_staff(user):
        return "nursing"
    return ""


@login_required
def professional_profile_update_queue(request):
    if not can_manage_regulatory_operations(request.user):
        raise Http404("Profile-update queue not available")
    scope = _review_scope_for(request.user, request.GET.get("office", ""))
    if not scope or not can_access_staff_domain(request.user, scope):
        raise Http404("Profile-update queue not available")

    status = request.GET.get("status", "submitted")
    allowed_statuses = {choice[0] for choice in ProfessionalProfileUpdateRequest.STATUS_CHOICES}
    if status not in allowed_statuses | {"all"}:
        status = "submitted"
    queryset = ProfessionalProfileUpdateRequest.objects.filter(office_scope=scope).select_related(
        "content_type", "requested_by", "reviewer"
    )
    if status != "all":
        queryset = queryset.filter(status=status)

    return render(request, "workforce/professional_profile_update_queue.html", {
        "office_scope": scope,
        "profile_update_requests": queryset[:100],
        "selected_status": status,
        "status_choices": [("all", "All"), *ProfessionalProfileUpdateRequest.STATUS_CHOICES],
        "pending_profile_update_count": ProfessionalProfileUpdateRequest.objects.filter(
            office_scope=scope,
            status__in=["submitted", "under_review"],
        ).count(),
    })


@login_required
@require_POST
def review_professional_profile_update_request(request, pk):
    update_request = get_object_or_404(ProfessionalProfileUpdateRequest, pk=pk)
    if not can_manage_regulatory_operations(request.user) or not can_access_staff_domain(
        request.user, update_request.office_scope
    ):
        raise Http404("Profile-update request not available")

    action = request.POST.get("action")
    if action not in {"approve", "reject"}:
        messages.error(request, "Choose approve or reject for the profile-update request.")
        return redirect("professional_profile_update_queue")
    reviewer_note = request.POST.get("reviewer_note", "").strip()
    if action == "reject" and not reviewer_note:
        messages.error(request, "Record a reviewer reason before rejecting a profile-update request.")
        return redirect(f"{reverse('professional_profile_update_queue')}?office={update_request.office_scope}")
    try:
        review_profile_update_request(
            request_id=update_request.pk,
            actor=request.user,
            approved=action == "approve",
            reviewer_note=reviewer_note,
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        label = "approved and applied to the official profile" if action == "approve" else "rejected"
        messages.success(request, f"Profile-update request {label}.")
    return redirect(f"{reverse('professional_profile_update_queue')}?office={update_request.office_scope}")
