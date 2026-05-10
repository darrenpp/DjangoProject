from django.db.models import Q
from django.urls import reverse

from apps.accounts.models import OperationalAccessRequest
from apps.dashboard.access import MEDICAL_BOARD_FORM_CODES, is_medical_board_staff, is_nursing_council_staff, is_system_admin
from apps.documents.models import Document
from apps.workforce.models import Application

from .models import EnquiryThread


def staff_scope(user):
    if getattr(user, "role", "") == "admin":
        return ""
    if is_medical_board_staff(user):
        return "medical"
    if is_nursing_council_staff(user):
        return "nursing"
    return ""


def scoped_application_queryset(user):
    queryset = Application.objects.order_by("-submitted_date")
    if getattr(user, "role", "") == "admin":
        return queryset
    if is_medical_board_staff(user):
        return queryset.filter(form_code__in=MEDICAL_BOARD_FORM_CODES)
    if is_nursing_council_staff(user):
        return queryset.exclude(form_code__in=MEDICAL_BOARD_FORM_CODES)
    return queryset.none()


def scoped_document_queryset(user):
    queryset = Document.objects.select_related("folder", "document_type").order_by("-updated_at")
    scope = staff_scope(user)
    if scope:
        return queryset.filter(office_scope=scope)
    if getattr(user, "role", "") == "admin":
        return queryset
    return queryset.none()


def scoped_enquiry_queryset(user):
    queryset = EnquiryThread.objects.select_related("created_by", "assigned_to").prefetch_related("messages").order_by("-updated_at")
    if getattr(user, "role", "") == "admin":
        return queryset
    if getattr(user, "role", "") == "registrar":
        offices = ["general"]
        if is_nursing_council_staff(user):
            offices.append("nursing")
        if is_medical_board_staff(user):
            offices.append("medical")
        return queryset.filter(
            Q(office__in=offices) | Q(created_by=user) | Q(assigned_to=user)
        ).distinct()
    return queryset.none()


def scoped_operational_access_requests(user):
    queryset = OperationalAccessRequest.objects.select_related("user", "decided_by").filter(status="pending")
    if is_system_admin(user):
        return queryset
    if getattr(user, "role", "") != "registrar":
        return queryset.none()
    if is_medical_board_staff(user):
        return queryset.filter(requested_office__in=["medical", "finance", "general"])
    if is_nursing_council_staff(user):
        return queryset.filter(requested_office__in=["nursing", "finance", "general"])
    return queryset.none()


def build_staff_notification_summary(user):
    if not getattr(user, "is_authenticated", False) or getattr(user, "role", "") not in {"admin", "registrar"}:
        return {
            "count": 0,
            "items": [],
            "pending_applications": [],
            "open_threads": [],
            "documents_for_review": [],
            "pending_application_count": 0,
            "open_thread_count": 0,
            "document_review_count": 0,
            "pending_access_request_count": 0,
            "pending_access_requests": [],
        }

    pending_applications_qs = scoped_application_queryset(user).filter(status="pending")
    open_threads_qs = scoped_enquiry_queryset(user).filter(status__in=["open", "pending"])
    documents_for_review_qs = scoped_document_queryset(user).filter(status="draft")
    access_requests_qs = scoped_operational_access_requests(user)

    pending_application_count = pending_applications_qs.count()
    open_thread_count = open_threads_qs.count()
    document_review_count = documents_for_review_qs.count()
    pending_access_request_count = access_requests_qs.count()

    pending_applications = list(pending_applications_qs[:5])
    open_threads = list(open_threads_qs[:5])
    documents_for_review = list(documents_for_review_qs[:5])
    pending_access_requests = list(access_requests_qs[:10])

    items = []
    if pending_application_count:
        items.append({
            "level": "warning",
            "title": "Applications awaiting approval",
            "message": f"{pending_application_count} pending application(s) need registrar review.",
            "url": reverse("staff_communications"),
            "action": "Open approvals",
        })
    if open_thread_count:
        items.append({
            "level": "info",
            "title": "Inbox messages waiting",
            "message": f"{open_thread_count} enquiry conversation(s) need attention or reply.",
            "url": reverse("staff_communications"),
            "action": "Open inbox",
        })
    if document_review_count:
        items.append({
            "level": "secondary",
            "title": "Documents ready for review",
            "message": f"{document_review_count} repository document(s) are still in draft review state.",
            "url": reverse("repository_search"),
            "action": "Review documents",
        })
    if pending_access_request_count:
        items.append({
            "level": "danger",
            "title": "Operational access requests",
            "message": f"{pending_access_request_count} reviewer access request(s) need approval or rejection.",
            "url": reverse("staff_communications"),
            "action": "Review access",
        })

    return {
        "count": len(items),
        "items": items,
        "pending_applications": pending_applications,
        "open_threads": open_threads,
            "documents_for_review": documents_for_review,
            "pending_access_requests": pending_access_requests,
            "pending_application_count": pending_application_count,
            "open_thread_count": open_thread_count,
            "document_review_count": document_review_count,
            "pending_access_request_count": pending_access_request_count,
        }
