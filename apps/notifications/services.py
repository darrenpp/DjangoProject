from django.db.models import Q
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import OperationalAccessRequest, User
from apps.accounts.staff_approval import (
    can_registrar_approve_staff_account,
    can_system_admin_approve_staff_account,
    pending_staff_accounts_for_approver,
    staff_account_scope_label,
)
from apps.dashboard.access import (
    MEDICAL_BOARD_FORM_CODES,
    can_access_staff_domain,
    imported_record_domain,
    is_medical_board_staff,
    is_nursing_council_staff,
    is_system_admin,
    professional_domain,
)
from apps.documents.models import Document
from apps.workforce.models import (
    Application,
    CommunityHealthWorker,
    HealthStudent,
    MedicalDoctor,
    Midwife,
    NurseAide,
    NursingProfessional,
    PracticingLicenseRecord,
)

from .models import EnquiryMailboxState, EnquiryThread, Notification


DIRECT_MESSAGE_MODELS = [
    ("Nursing Professionals", NursingProfessional),
    ("Midwives", Midwife),
    ("Nurse Aides", NurseAide),
    ("Graduands", HealthStudent),
    ("Medical Doctors", MedicalDoctor),
    ("Community Health Workers", CommunityHealthWorker),
    ("Imported Workbook Rows", PracticingLicenseRecord),
]

DIRECT_MESSAGE_DELIVERY_CHANNELS = {"mailbox", "email", "both"}


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
    queryset = EnquiryThread.objects.select_related("created_by", "assigned_to", "recipient_user").prefetch_related("messages", "mailbox_states").order_by("-updated_at")
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


def _thread_messages(thread):
    return list(thread.messages.all())


def latest_thread_message(thread):
    messages = _thread_messages(thread)
    return messages[-1] if messages else None


def latest_incoming_thread_message(thread, user):
    for message in reversed(_thread_messages(thread)):
        if message.sender_id != getattr(user, "id", None):
            return message
    return None


def mailbox_state_for_user(thread, user):
    prefetched_states = getattr(thread, "_prefetched_objects_cache", {}).get("mailbox_states")
    if prefetched_states is not None:
        for state in prefetched_states:
            if state.user_id == getattr(user, "id", None):
                return state
        return None
    return EnquiryMailboxState.objects.filter(thread=thread, user=user).first()


def mailbox_thread_is_unread_for_user(thread, user, state=None):
    if not getattr(user, "is_authenticated", False):
        return False
    latest_incoming = latest_incoming_thread_message(thread, user)
    if latest_incoming is None:
        return False
    state = state if state is not None else mailbox_state_for_user(thread, user)
    if state and state.read_at and state.read_at >= latest_incoming.created_at:
        return False
    return True


def mailbox_status_for_user(thread, user, state=None):
    if mailbox_thread_is_unread_for_user(thread, user, state=state):
        return {
            "label": "Unread",
            "level": "warning",
            "description": "New message waiting",
        }

    latest_message = latest_thread_message(thread)
    if latest_message and latest_message.sender_id == getattr(user, "id", None):
        opened = EnquiryMailboxState.objects.filter(
            thread=thread,
            read_at__gte=latest_message.created_at,
        ).exclude(user=user).exists()
        if opened:
            return {
                "label": "Opened",
                "level": "success",
                "description": "Recipient opened this message",
            }
        return {
            "label": "Sent",
            "level": "secondary",
            "description": "Waiting for recipient to open",
        }

    return {
        "label": "Read",
        "level": "success",
        "description": "Opened by you",
    }


def mark_thread_notifications_read_for_user(thread, user, read_at=None):
    if not getattr(user, "is_authenticated", False):
        return 0
    read_at = read_at or timezone.now()
    subjects = [thread.subject, f"New mailbox message: {thread.subject}"]
    return Notification.objects.filter(
        user=user,
        read_at__isnull=True,
        subject__in=subjects,
    ).update(read_at=read_at)


def mark_thread_read_for_user(thread, user):
    if not getattr(user, "is_authenticated", False):
        return None
    read_at = timezone.now()
    state, _ = EnquiryMailboxState.objects.get_or_create(user=user, thread=thread)
    state.read_at = read_at
    state.last_read_message = latest_thread_message(thread)
    state.save(update_fields=["read_at", "last_read_message", "updated_at"])
    mark_thread_notifications_read_for_user(thread, user, read_at=read_at)
    return state


def decorate_mailbox_threads_for_user(threads, user):
    threads = list(threads)
    states = EnquiryMailboxState.objects.filter(user=user, thread__in=threads)
    state_by_thread_id = {state.thread_id: state for state in states}
    for thread in threads:
        state = state_by_thread_id.get(thread.pk)
        thread.mailbox_state_for_user = state
        thread.mailbox_unread_for_user = mailbox_thread_is_unread_for_user(thread, user, state=state)
        thread.mailbox_status_for_user = mailbox_status_for_user(thread, user, state=state)
    return threads


def _record_display_name(record):
    full_name = getattr(record, "full_name", "") or ""
    if full_name:
        return full_name
    return f"{getattr(record, 'first_name', '')} {getattr(record, 'last_name', '')}".strip()


def _record_registration(record):
    return (
        getattr(record, "registration_no", "")
        or getattr(record, "registration_number", "")
        or getattr(record, "practitioner_number", "")
        or ""
    )


def _record_email(record):
    return getattr(record, "email", "") or ""


def _record_label(record):
    name = _record_display_name(record) or "Unnamed record"
    registration = _record_registration(record)
    email = _record_email(record)
    parts = [name]
    if registration:
        parts.append(registration)
    if email:
        parts.append(email)
    if isinstance(record, PracticingLicenseRecord):
        parts.append(record.get_target_model_display())
        if record.source_sheet_name or record.source_row:
            source = f"{record.source_sheet_name or 'Workbook'} row {record.source_row or '-'}"
            parts.append(source)
    return " - ".join(str(part) for part in parts if part)


def _record_domain(record):
    if isinstance(record, PracticingLicenseRecord):
        return imported_record_domain(record)
    return professional_domain(record)


def _record_queryset_for_staff(user, model):
    if model is PracticingLicenseRecord:
        queryset = model.objects.exclude(record_type="summary")
    else:
        queryset = model.objects.all()
        if hasattr(model, "is_active"):
            queryset = queryset.filter(is_active=True)

    if getattr(user, "role", "") == "admin":
        return queryset

    sample_domain = ""
    if model is PracticingLicenseRecord:
        if is_medical_board_staff(user) and not is_nursing_council_staff(user):
            return queryset.filter(target_model__in=["medicaldoctor", "communityhealthworker"])
        if is_nursing_council_staff(user):
            return queryset.filter(target_model__in=["nursingprofessional", "midwife", "nurseaide", "healthstudent"])
        return queryset.none()

    empty_instance = model()
    sample_domain = _record_domain(empty_instance)
    return queryset if can_access_staff_domain(user, sample_domain) else queryset.none()


def _record_search_filter(search):
    query = Q()
    for term in [item for item in search.split() if item]:
        term_query = (
            Q(first_name__icontains=term)
            | Q(last_name__icontains=term)
            | Q(registration_no__icontains=term)
            | Q(registration_number__icontains=term)
            | Q(email__icontains=term)
        )
        query &= term_query
    return query


def _imported_record_search_filter(search):
    query = Q()
    for term in [item for item in search.split() if item]:
        term_query = (
            Q(full_name__icontains=term)
            | Q(first_name__icontains=term)
            | Q(last_name__icontains=term)
            | Q(registration_no__icontains=term)
            | Q(practitioner_number__icontains=term)
            | Q(source_sheet_name__icontains=term)
        )
        query &= term_query
    return query


def direct_message_record_reference(record):
    content_type = ContentType.objects.get_for_model(record, for_concrete_model=False)
    return f"record:{content_type.pk}:{record.pk}"


def find_user_for_record(record):
    email = _record_email(record)
    registration = _record_registration(record)
    lookups = []
    if email:
        lookups.append({"email__iexact": email})
    if registration:
        lookups.extend([
            {"registration_number__iexact": registration},
            {"license_number__iexact": registration},
            {"username__iexact": registration},
        ])
    for lookup in lookups:
        user = User.objects.filter(is_active=True, **lookup).first()
        if user:
            return user
    return None


def build_direct_message_recipient_groups(user, *, search="", selected_reference="", limit=40):
    if getattr(user, "role", "") not in {"admin", "registrar"}:
        return []

    selected_record = None
    if selected_reference:
        selected = resolve_direct_message_recipient(selected_reference, user)
        selected_record = selected.get("record") if selected else None

    groups = []
    for group_label, model in DIRECT_MESSAGE_MODELS:
        queryset = _record_queryset_for_staff(user, model)
        if search:
            queryset = queryset.filter(
                _imported_record_search_filter(search)
                if model is PracticingLicenseRecord
                else _record_search_filter(search)
            )
        if model is PracticingLicenseRecord:
            queryset = queryset.order_by("-record_year", "full_name", "source_row")
        else:
            queryset = queryset.order_by("last_name", "first_name", "registration_no")

        records = list(queryset[:limit])
        if selected_record and isinstance(selected_record, model) and selected_record not in records:
            records.insert(0, selected_record)

        options = [
            {
                "value": direct_message_record_reference(record),
                "label": _record_label(record),
                "email": _record_email(record),
                "selected": direct_message_record_reference(record) == selected_reference,
            }
            for record in records
        ]
        if options:
            groups.append({"label": group_label, "options": options})
    return groups


def resolve_direct_message_recipient(reference, user):
    if getattr(user, "role", "") not in {"admin", "registrar"}:
        return None
    if not reference or not str(reference).startswith("record:"):
        return None

    try:
        _prefix, content_type_id, object_id = str(reference).split(":", 2)
    except ValueError:
        return None
    try:
        content_type = ContentType.objects.get(pk=int(content_type_id))
    except (ContentType.DoesNotExist, TypeError, ValueError):
        return None
    model = content_type.model_class()
    allowed_models = {entry[1] for entry in DIRECT_MESSAGE_MODELS}
    if model not in allowed_models:
        return None
    try:
        record = model.objects.get(pk=int(object_id))
    except (model.DoesNotExist, TypeError, ValueError):
        return None

    domain = _record_domain(record)
    if not can_access_staff_domain(user, domain):
        return None

    return {
        "record": record,
        "content_type": content_type,
        "object_id": record.pk,
        "name": _record_display_name(record),
        "label": _record_label(record),
        "email": _record_email(record),
        "registration": _record_registration(record),
        "domain": domain,
        "office": "medical" if domain == "medical" else "nursing" if domain == "nursing" else "general",
        "user": find_user_for_record(record),
    }


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
            "recent_complaint_cases": [],
            "recent_disciplinary_cases": [],
            "pending_application_count": 0,
            "open_thread_count": 0,
            "document_review_count": 0,
            "pending_access_request_count": 0,
            "pending_staff_account_count": 0,
            "complaint_case_count": 0,
            "high_risk_complaint_case_count": 0,
            "open_discipline_count": 0,
            "pending_access_requests": [],
            "pending_staff_account_requests": [],
        }

    pending_applications_qs = scoped_application_queryset(user).filter(status="pending")
    suppressed_thread_ids = EnquiryMailboxState.objects.filter(
        user=user,
        folder__in=["archived", "deleted"],
    ).values("thread_id")
    open_threads_qs = scoped_enquiry_queryset(user).filter(status__in=["open", "pending"]).exclude(id__in=suppressed_thread_ids)
    documents_for_review_qs = scoped_document_queryset(user).filter(status="draft")
    access_requests_qs = scoped_operational_access_requests(user)
    staff_account_requests_qs = pending_staff_accounts_for_approver(user)
    from apps.complaints.services import complaint_summary_for_user, discipline_summary_for_user

    complaint_summary = complaint_summary_for_user(user)
    discipline_summary = discipline_summary_for_user(user)

    pending_application_count = pending_applications_qs.count()
    open_thread_count = open_threads_qs.count()
    document_review_count = documents_for_review_qs.count()
    pending_access_request_count = access_requests_qs.count()
    pending_staff_account_count = staff_account_requests_qs.count()
    complaint_case_count = complaint_summary["open_case_count"]
    high_risk_complaint_case_count = complaint_summary["high_risk_case_count"]
    open_discipline_count = discipline_summary["open_discipline_count"]

    pending_applications = list(pending_applications_qs[:5])
    open_threads = list(open_threads_qs[:5])
    unread_threads = [
        thread for thread in open_threads_qs
        if mailbox_thread_is_unread_for_user(thread, user)
    ]
    unread_thread_count = len(unread_threads)
    documents_for_review = list(documents_for_review_qs[:5])
    pending_access_requests = list(access_requests_qs[:10])
    pending_staff_account_requests = [
        {
            "user": pending_user,
            "scope_label": staff_account_scope_label(pending_user),
            "can_registrar_approve": can_registrar_approve_staff_account(user, pending_user),
            "can_system_admin_approve": can_system_admin_approve_staff_account(user, pending_user),
        }
        for pending_user in staff_account_requests_qs[:10]
    ]

    items = []
    if pending_application_count:
        items.append({
            "level": "warning",
            "title": "Applications awaiting approval",
            "message": f"{pending_application_count} pending application(s) need registrar review.",
            "url": reverse("staff_communications"),
            "action": "Open approvals",
        })
    if unread_thread_count:
        items.append({
            "level": "info",
            "title": "Inbox messages waiting",
            "message": f"{unread_thread_count} unread enquiry conversation(s) need attention or reply.",
            "url": reverse("enquiry_thread", args=[unread_threads[0].pk]) if unread_threads else reverse("staff_communications"),
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
    if pending_staff_account_count:
        items.append({
            "level": "danger",
            "title": "Staff account approvals",
            "message": f"{pending_staff_account_count} staff account request(s) need Registrar and/or System Admin approval.",
            "url": reverse("staff_communications"),
            "action": "Review accounts",
        })
    if complaint_case_count:
        items.append({
            "level": "danger" if high_risk_complaint_case_count else "warning",
            "title": "ICMS complaint cases",
            "message": f"{complaint_case_count} open complaint or incident case(s) need formal tracking.",
            "url": reverse("complaint_case_list"),
            "action": "Open ICMS",
        })
    if open_discipline_count:
        items.append({
            "level": "danger",
            "title": "Disciplinary cases",
            "message": f"{open_discipline_count} open disciplinary case(s) need due-process tracking.",
            "url": reverse("disciplinary_case_list"),
            "action": "Open discipline",
        })

    return {
        "count": len(items),
        "items": items,
        "pending_applications": pending_applications,
        "open_threads": open_threads,
        "documents_for_review": documents_for_review,
        "recent_complaint_cases": complaint_summary["recent_cases"],
        "recent_disciplinary_cases": discipline_summary["recent_disciplinary_cases"],
        "pending_access_requests": pending_access_requests,
        "pending_staff_account_requests": pending_staff_account_requests,
        "pending_application_count": pending_application_count,
        "open_thread_count": open_thread_count,
        "unread_thread_count": unread_thread_count,
        "unread_threads": unread_threads[:5],
        "document_review_count": document_review_count,
        "pending_access_request_count": pending_access_request_count,
        "pending_staff_account_count": pending_staff_account_count,
        "complaint_case_count": complaint_case_count,
        "high_risk_complaint_case_count": high_risk_complaint_case_count,
        "unassigned_complaint_case_count": complaint_summary["unassigned_case_count"],
        "open_discipline_count": open_discipline_count,
        "high_severity_discipline_count": discipline_summary["high_severity_count"],
    }


def _notification_item(notification):
    url = reverse("user_profile")
    action = "View notice"
    if notification.subject.startswith("Mobile intake review required:"):
        url = reverse("mobile_intake_queue")
        action = "Open queue"
    return {
        "id": notification.pk,
        "level": "info",
        "title": notification.subject,
        "message": notification.message,
        "url": url,
        "action": action,
        "created_at": notification.created_at,
        "unread": notification.read_at is None,
    }


def _personal_mailbox_queryset(user):
    suppressed_thread_ids = EnquiryMailboxState.objects.filter(
        user=user,
        folder__in=["archived", "deleted"],
    ).values("thread_id")
    if getattr(user, "role", "") in {"admin", "registrar"}:
        queryset = scoped_enquiry_queryset(user)
    else:
        queryset = EnquiryThread.objects.select_related(
            "created_by",
            "assigned_to",
            "recipient_user",
        ).prefetch_related(
            "messages",
            "mailbox_states",
        ).filter(
            Q(created_by=user) | Q(assigned_to=user) | Q(recipient_user=user),
        )
    return queryset.filter(status__in=["open", "pending"]).exclude(id__in=suppressed_thread_ids).distinct()


def build_user_notification_summary(user):
    if not getattr(user, "is_authenticated", False):
        return {
            "count": 0,
            "items": [],
            "unread_items": [],
            "history_items": [],
            "current_items": [],
            "notifications": [],
            "open_threads": [],
        }

    current_items = []
    if getattr(user, "role", "") in {"admin", "registrar"}:
        current_items.extend(build_staff_notification_summary(user).get("items", []))

    open_threads_qs = _personal_mailbox_queryset(user)
    open_thread_count = open_threads_qs.count()
    unread_mailbox_threads = [
        thread for thread in open_threads_qs
        if mailbox_thread_is_unread_for_user(thread, user)
    ]
    unread_mailbox_count = len(unread_mailbox_threads)
    open_threads = list(open_threads_qs.order_by("-updated_at")[:5])

    mailbox_notification_subjects = set()
    for thread in unread_mailbox_threads:
        mailbox_notification_subjects.add(thread.subject)
        mailbox_notification_subjects.add(f"New mailbox message: {thread.subject}")

    notifications_qs = Notification.objects.filter(user=user).order_by("-created_at")
    unread_qs = notifications_qs.filter(read_at__isnull=True)
    if mailbox_notification_subjects:
        unread_qs = unread_qs.exclude(subject__in=mailbox_notification_subjects)
    unread_count = unread_qs.count()
    notifications = list(notifications_qs[:10])
    history_items = [_notification_item(notification) for notification in notifications]
    unread_items = [_notification_item(notification) for notification in unread_qs[:8]]

    if unread_mailbox_count and getattr(user, "role", "") not in {"admin", "registrar"}:
        current_items.insert(0, {
            "level": "info",
            "title": "Mailbox messages waiting",
            "message": f"{unread_mailbox_count} unread message conversation(s) are available in your mailbox.",
            "url": reverse("enquiry_thread", args=[unread_mailbox_threads[0].pk]) if unread_mailbox_threads else reverse("enquiry_inbox"),
            "action": "Open mailbox",
        })
    unread_total_count = unread_count + unread_mailbox_count

    return {
        "count": min(unread_total_count, 99),
        "items": history_items[:8],
        "unread_items": unread_items,
        "history_items": history_items,
        "current_items": current_items[:6],
        "notifications": notifications,
        "notification_count": notifications_qs.count(),
        "unread_notification_count": unread_count,
        "unread_mailbox_count": unread_mailbox_count,
        "unread_total_count": unread_total_count,
        "unread_mailbox_threads": unread_mailbox_threads[:5],
        "open_threads": open_threads,
        "open_thread_count": open_thread_count,
    }
