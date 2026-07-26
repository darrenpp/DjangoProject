from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.mail import EmailMessage, send_mail
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from pathlib import Path

from apps.accounts.models import User
from apps.dashboard.access import is_medical_board_user, is_nursing_council_board_member, is_nursing_council_user
from apps.dashboard.assistant_memory import get_or_create_assistant_conversation, record_assistant_turn
from apps.workforce.models import Application, MissingDataReview

from .helpdesk import DEFAULT_ANSWER, get_helpdesk_response, maybe_generate_live_helpdesk_response
from .models import EnquiryMailboxState, EnquiryMessage, EnquiryMessageAttachment, EnquiryThread, Notification
from .services import (
    DIRECT_MESSAGE_DELIVERY_CHANNELS,
    build_direct_message_recipient_groups,
    build_staff_notification_summary,
    build_user_notification_summary,
    decorate_mailbox_threads_for_user,
    mark_thread_read_for_user,
    resolve_direct_message_recipient,
)


MAILBOX_FOLDERS = [
    {
        "key": "inbox",
        "label": "Inbox",
        "icon": "fas fa-inbox",
        "description": "Active conversations and enquiries visible to your account.",
    },
    {
        "key": "sent",
        "label": "Sent Items",
        "icon": "fas fa-paper-plane",
        "description": "Conversations you created or replied to.",
    },
    {
        "key": "archived",
        "label": "Archived",
        "icon": "fas fa-archive",
        "description": "Conversations you moved out of your active inbox.",
    },
    {
        "key": "deleted",
        "label": "Deleted Items",
        "icon": "fas fa-trash-alt",
        "description": "Conversations you removed from your active mailbox.",
    },
    {
        "key": "history",
        "label": "Conversation History",
        "icon": "fas fa-folder-open",
        "description": "All non-deleted conversation records visible to you.",
    },
    {
        "key": "notes",
        "label": "Notes",
        "icon": "fas fa-sticky-note",
        "description": "Conversations where you saved private mailbox notes.",
    },
]

MAILBOX_FOLDER_KEYS = {folder["key"] for folder in MAILBOX_FOLDERS}
MAILBOX_ATTACHMENT_MAX_FILES = 5
MAILBOX_ATTACHMENT_MAX_SIZE = 10 * 1024 * 1024
MAILBOX_ATTACHMENT_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
}


def _mailbox_attachment_error(files):
    if len(files) > MAILBOX_ATTACHMENT_MAX_FILES:
        return f"Attach no more than {MAILBOX_ATTACHMENT_MAX_FILES} files to one message."
    for upload in files:
        extension = Path(upload.name or "").suffix.lower()
        if extension not in MAILBOX_ATTACHMENT_EXTENSIONS:
            allowed = ", ".join(sorted(MAILBOX_ATTACHMENT_EXTENSIONS))
            return f"{upload.name} is not an allowed attachment type. Allowed types: {allowed}."
        if upload.size and upload.size > MAILBOX_ATTACHMENT_MAX_SIZE:
            return f"{upload.name} is too large. Maximum file size is 10 MB."
    return ""


def _save_message_attachments(message, files):
    attachments = []
    for upload in files:
        attachments.append(EnquiryMessageAttachment.objects.create(
            message=message,
            file=upload,
            original_filename=upload.name or "attachment",
            content_type=getattr(upload, "content_type", "") or "",
            file_size=getattr(upload, "size", 0) or 0,
        ))
    return attachments


def _send_email_with_attachments(subject, body, recipients, attachments=None):
    recipients = [recipient for recipient in recipients if recipient]
    if not recipients:
        return False
    email = EmailMessage(
        subject,
        body,
        getattr(settings, 'DEFAULT_FROM_EMAIL', 'no-reply@ndoh.gov.pg'),
        recipients,
    )
    for attachment in attachments or []:
        if not attachment.file:
            continue
        try:
            attachment.file.open("rb")
            email.attach(
                attachment.original_filename or Path(attachment.file.name).name,
                attachment.file.read(),
                attachment.content_type or None,
            )
        finally:
            attachment.file.close()
    return bool(email.send(fail_silently=True))


def _office_for_user(user):
    if is_medical_board_user(user) and not is_nursing_council_user(user):
        return 'medical'
    if is_nursing_council_user(user):
        return 'nursing'
    return 'general'


def _can_create_direct_messages(user):
    return getattr(user, "role", "") in {"admin", "registrar"}


def _thread_queryset_for_user(user):
    qs = EnquiryThread.objects.select_related('created_by', 'assigned_to', 'recipient_user').prefetch_related('messages__attachments')
    if user.role == 'admin':
        return qs
    if user.role == 'registrar':
        offices = ['general']
        if is_nursing_council_user(user):
            offices.append('nursing')
        if is_medical_board_user(user):
            offices.append('medical')
        return qs.filter(Q(office__in=offices) | Q(created_by=user) | Q(assigned_to=user) | Q(recipient_user=user)).distinct()
    return qs.filter(Q(created_by=user) | Q(assigned_to=user) | Q(recipient_user=user)).distinct()


def _state_thread_ids(user, *folders):
    return EnquiryMailboxState.objects.filter(user=user, folder__in=folders).values('thread_id')


def _mailbox_threads_for_folder(user, folder):
    folder = folder if folder in MAILBOX_FOLDER_KEYS else "inbox"
    queryset = _thread_queryset_for_user(user).order_by("-updated_at")
    deleted_thread_ids = _state_thread_ids(user, "deleted")

    if folder == "deleted":
        return queryset.filter(id__in=deleted_thread_ids).distinct()
    if folder == "archived":
        return queryset.filter(id__in=_state_thread_ids(user, "archived")).distinct()

    queryset = queryset.exclude(id__in=deleted_thread_ids)
    if folder == "sent":
        return queryset.filter(Q(created_by=user) | Q(messages__sender=user)).distinct()
    if folder == "history":
        return queryset.distinct()
    if folder == "notes":
        noted_thread_ids = EnquiryMailboxState.objects.filter(user=user).exclude(notes="").values('thread_id')
        return queryset.filter(id__in=noted_thread_ids).distinct()
    return queryset.exclude(id__in=_state_thread_ids(user, "archived")).distinct()


def _active_mailbox_folder(request):
    folder = request.GET.get("folder", "inbox")
    return folder if folder in MAILBOX_FOLDER_KEYS else "inbox"


def _mailbox_context(user, active_folder="inbox"):
    active_folder = active_folder if active_folder in MAILBOX_FOLDER_KEYS else "inbox"
    folders = []
    active = MAILBOX_FOLDERS[0]
    for folder in MAILBOX_FOLDERS:
        item = {
            **folder,
            "active": folder["key"] == active_folder,
            "count": _mailbox_threads_for_folder(user, folder["key"]).count(),
            "url": f"{reverse('enquiry_inbox')}?folder={folder['key']}",
        }
        if item["active"]:
            active = item
        folders.append(item)
    return {
        "folders": folders,
        "active": active,
    }


def _notify_thread_participants(thread, message):
    recipients = set()
    portal_recipients = {}
    email_enabled = getattr(thread, "delivery_channel", "office") in {"office", "email", "both"}
    mailbox_enabled = getattr(thread, "delivery_channel", "office") in {"office", "mailbox", "both"}

    def add_portal_recipient(user):
        if user and user.id != message.sender_id:
            portal_recipients[user.id] = user

    if thread.created_by_id != message.sender_id:
        add_portal_recipient(thread.created_by)
    add_portal_recipient(thread.assigned_to)
    add_portal_recipient(thread.recipient_user)

    if (
        getattr(thread, "delivery_channel", "office") == "office"
        and not thread.assigned_to
        and not thread.recipient_user
        and not thread.recipient_email
    ):
        staff = User.objects.filter(role__in=['admin', 'registrar'], is_active=True)
        if thread.office == 'nursing':
            staff = [user for user in staff if is_nursing_council_user(user)]
        elif thread.office == 'medical':
            staff = [user for user in staff if is_medical_board_user(user)]
        for user in staff:
            add_portal_recipient(user)

    if mailbox_enabled:
        for user in portal_recipients.values():
            EnquiryMailboxState.objects.get_or_create(user=user, thread=thread)
            Notification.objects.create(
                user=user,
                subject=f"New mailbox message: {thread.subject}",
                message=message.body,
            )

    if not email_enabled:
        return False

    if thread.created_by.email and thread.created_by_id != message.sender_id:
        recipients.add(thread.created_by.email)
    if thread.assigned_to and thread.assigned_to.email and thread.assigned_to_id != message.sender_id:
        recipients.add(thread.assigned_to.email)
    if thread.recipient_user and thread.recipient_user.email and thread.recipient_user_id != message.sender_id:
        recipients.add(thread.recipient_user.email)
    if thread.recipient_email and thread.recipient_email != getattr(message.sender, "email", ""):
        recipients.add(thread.recipient_email)
    if not thread.assigned_to and not thread.recipient_user and not thread.recipient_email:
        staff = User.objects.filter(role__in=['admin', 'registrar'], is_active=True)
        if thread.office == 'nursing':
            staff = [user for user in staff if is_nursing_council_user(user)]
        elif thread.office == 'medical':
            staff = [user for user in staff if is_medical_board_user(user)]
        for user in staff:
            if user.email and user.id != message.sender_id:
                recipients.add(user.email)
    if not recipients:
        return False
    _send_email_with_attachments(
        f"NDOH Registry enquiry: {thread.subject}",
        message.body,
        list(recipients),
        message.attachments.all(),
    )
    message.emailed = True
    message.save(update_fields=['emailed'])
    return True


def _send_direct_message_email(recipient_email, subject, body, sender, attachments=None):
    if not recipient_email:
        return False
    sender_name = sender.get_full_name() or sender.username
    message_body = (
        f"{body}\n\n"
        f"Sent by {sender_name} through the NDOH Regulatory Bodies System"
    )
    sent_count = _send_email_with_attachments(
        f"NDOH Registry message: {subject}",
        message_body,
        [recipient_email],
        attachments,
    )
    return bool(sent_count)


def _create_direct_message(request, recipient_reference, subject, body, attachment_files=None):
    attachment_files = attachment_files or []
    recipient = resolve_direct_message_recipient(recipient_reference, request.user)
    if not recipient:
        messages.error(request, "Please select a valid individual record in your office scope.")
        return None

    requested_delivery = request.POST.get("delivery_channel", "both")
    if requested_delivery not in DIRECT_MESSAGE_DELIVERY_CHANNELS:
        requested_delivery = "both"

    recipient_user = recipient.get("user")
    recipient_email = recipient.get("email") or getattr(recipient_user, "email", "")
    actual_delivery = requested_delivery

    if requested_delivery == "mailbox" and not recipient_user:
        messages.error(request, "This record is not linked to a portal user. Choose Direct email or link the record to a user account first.")
        return None
    if requested_delivery == "email" and not recipient_email:
        messages.error(request, "This record does not have an email address. Choose Platform mailbox for linked portal users.")
        return None
    if requested_delivery == "both" and not recipient_user and recipient_email:
        actual_delivery = "email"
        messages.info(request, "No linked portal user was found, so the follow-up was sent by direct email only.")
    elif requested_delivery == "both" and recipient_user and not recipient_email:
        actual_delivery = "mailbox"
        messages.info(request, "No email address was found, so the follow-up was sent through the platform mailbox only.")
    elif requested_delivery == "both" and not recipient_user and not recipient_email:
        messages.error(request, "This record needs either a linked portal user or an email address before a follow-up can be sent.")
        return None

    mailbox_user = recipient_user if actual_delivery in {"mailbox", "both"} else None
    thread = EnquiryThread.objects.create(
        subject=subject,
        office=recipient.get("office") or _office_for_user(request.user),
        created_by=request.user,
        recipient_user=mailbox_user,
        recipient_content_type=recipient.get("content_type"),
        recipient_object_id=recipient.get("object_id"),
        recipient_name=recipient.get("name") or recipient.get("label") or "",
        recipient_email=recipient_email,
        delivery_channel=actual_delivery,
    )
    message = EnquiryMessage.objects.create(thread=thread, sender=request.user, body=body)
    attachments = _save_message_attachments(message, attachment_files)

    email_sent = False
    if actual_delivery in {"email", "both"}:
        email_sent = _send_direct_message_email(
            recipient_email,
            subject,
            body,
            request.user,
            attachments,
        )
        message.emailed = email_sent
        message.save(update_fields=["emailed"])

    if mailbox_user:
        EnquiryMailboxState.objects.get_or_create(user=mailbox_user, thread=thread)
        Notification.objects.create(
            user=mailbox_user,
            subject=subject,
            message=body,
            sent=email_sent,
        )
    mark_thread_read_for_user(thread, request.user)

    return thread


def _review_prefill_context(request):
    review_id = request.GET.get("review")
    if not review_id or not _can_create_direct_messages(request.user):
        return {}
    review = MissingDataReview.objects.filter(pk=review_id).first()
    if not review:
        return {}

    recipient = resolve_direct_message_recipient(
        f"record:{review.content_type_id}:{review.object_id}",
        request.user,
    )
    if not recipient:
        return {}

    issues = ", ".join(str(item) for item in (review.missing_fields or []))
    return {
        "prefill_subject": f"Follow up: missing information for {review.full_name or recipient.get('name') or 'your record'}",
        "prefill_body": (
            f"Dear {review.full_name or recipient.get('name') or 'Registry user'},\n\n"
            f"We are reviewing your {review.professional_type or 'registry'} record and need the following information: {issues or 'additional profile details'}.\n\n"
            "Please reply through the platform mailbox or email the registry office with the missing information so your record can be completed."
        ),
    }


@login_required
def enquiry_inbox(request):
    active_folder = _active_mailbox_folder(request)
    threads = decorate_mailbox_threads_for_user(
        _mailbox_threads_for_folder(request.user, active_folder),
        request.user,
    )
    return render(request, 'notifications/enquiry_inbox.html', {
        'threads': threads,
        'mailbox': _mailbox_context(request.user, active_folder),
        'active_mailbox_folder': active_folder,
        'staff_summary': build_staff_notification_summary(request.user),
    })


@login_required
def enquiry_create(request):
    if request.method == 'POST':
        subject = request.POST.get('subject', '').strip()
        body = request.POST.get('body', '').strip()
        recipient_reference = request.POST.get("recipient", "")
        attachment_files = request.FILES.getlist("attachments")
        attachment_error = _mailbox_attachment_error(attachment_files)
        if attachment_error:
            messages.error(request, attachment_error)
        elif not subject or not body:
            messages.error(request, 'Please enter both a subject and message.')
        elif recipient_reference.startswith("record:") and _can_create_direct_messages(request.user):
            thread = _create_direct_message(request, recipient_reference, subject, body, attachment_files)
            if thread:
                messages.success(request, 'Your message has been sent to the selected record contact.')
                return redirect('enquiry_thread', pk=thread.pk)
        else:
            office = request.POST.get('office') or _office_for_user(request.user)
            if recipient_reference.startswith("office:"):
                office = recipient_reference.split(":", 1)[1]
            if office not in {'general', 'nursing', 'medical'}:
                office = 'general'
            thread = EnquiryThread.objects.create(
                subject=subject,
                office=office,
                created_by=request.user,
            )
            message = EnquiryMessage.objects.create(thread=thread, sender=request.user, body=body)
            _save_message_attachments(message, attachment_files)
            _notify_thread_participants(thread, message)
            mark_thread_read_for_user(thread, request.user)
            messages.success(request, 'Your enquiry has been created and sent to the right team.')
            return redirect('enquiry_thread', pk=thread.pk)

    selected_recipient = request.POST.get("recipient", "") if request.method == "POST" else request.GET.get("recipient", "")
    recipient_search = request.GET.get("recipient_search", "").strip()
    direct_message_context = {
        "can_create_direct_messages": _can_create_direct_messages(request.user),
        "selected_recipient": selected_recipient,
        "recipient_search": recipient_search,
        "recipient_groups": build_direct_message_recipient_groups(
            request.user,
            search=recipient_search,
            selected_reference=selected_recipient,
        ) if _can_create_direct_messages(request.user) else [],
    }
    direct_message_context.update(_review_prefill_context(request))
    return render(request, 'notifications/enquiry_form.html', {
        'default_office': _office_for_user(request.user),
        'mailbox': _mailbox_context(request.user, "sent"),
        'staff_summary': build_staff_notification_summary(request.user),
        **direct_message_context,
    })


@login_required
def enquiry_thread(request, pk):
    thread = get_object_or_404(_thread_queryset_for_user(request.user), pk=pk)
    mailbox_state = mark_thread_read_for_user(thread, request.user)
    if request.method == 'POST':
        if request.POST.get("thread_action") == "note":
            mailbox_state.notes = request.POST.get("notes", "").strip()
            mailbox_state.save(update_fields=["notes", "updated_at"])
            messages.success(request, "Mailbox note saved.")
            return redirect('enquiry_thread', pk=thread.pk)
        body = request.POST.get('body', '').strip()
        status = request.POST.get('status')
        attachment_files = request.FILES.getlist("attachments")
        attachment_error = _mailbox_attachment_error(attachment_files)
        if attachment_error:
            messages.error(request, attachment_error)
            return redirect('enquiry_thread', pk=thread.pk)
        if request.user.role in {'admin', 'registrar'} and status in {'open', 'pending', 'closed'}:
            thread.status = status
            thread.save(update_fields=['status', 'updated_at'])
        if body or attachment_files:
            if not body:
                body = "Please see the attached file(s)."
            message = EnquiryMessage.objects.create(thread=thread, sender=request.user, body=body)
            _save_message_attachments(message, attachment_files)
            thread.status = 'pending' if request.user.role not in {'admin', 'registrar'} else 'open'
            thread.save(update_fields=['status', 'updated_at'])
            _notify_thread_participants(thread, message)
            mailbox_state = mark_thread_read_for_user(thread, request.user)
            messages.success(request, 'Message sent.')
            return redirect('enquiry_thread', pk=thread.pk)
        if not body and status:
            messages.success(request, 'Thread status updated.')
            return redirect('enquiry_thread', pk=thread.pk)
        messages.error(request, 'Please enter a message before sending.')
    return render(request, 'notifications/enquiry_thread.html', {
        'thread': thread,
        'mailbox': _mailbox_context(request.user, "history"),
        'mailbox_state': mailbox_state,
        'staff_summary': build_staff_notification_summary(request.user),
    })


@login_required
@require_POST
def enquiry_mailbox_action(request, pk):
    thread = get_object_or_404(_thread_queryset_for_user(request.user), pk=pk)
    mailbox_state, _ = EnquiryMailboxState.objects.get_or_create(user=request.user, thread=thread)
    action = request.POST.get("action")
    if action == "archive":
        mailbox_state.folder = "archived"
        message = "Conversation archived."
    elif action == "delete":
        mailbox_state.folder = "deleted"
        message = "Conversation moved to Deleted Items."
    elif action == "restore":
        mailbox_state.folder = "active"
        message = "Conversation restored to the inbox."
    else:
        messages.error(request, "Unknown mailbox action.")
        return redirect("enquiry_inbox")

    mailbox_state.save(update_fields=["folder", "updated_at"])
    messages.success(request, message)
    next_url = request.POST.get("next") or reverse("enquiry_inbox")
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        next_url = reverse("enquiry_inbox")
    return redirect(next_url)


@login_required
def staff_communications(request):
    if request.user.role not in {"admin", "registrar"}:
        messages.error(request, "This communications area is only available to registrar and admin staff.")
        return redirect("enquiry_inbox")

    summary = build_staff_notification_summary(request.user)
    recent_threads = _thread_queryset_for_user(request.user)[:10]
    return render(request, "notifications/staff_communications.html", {
        "staff_summary": summary,
        "recent_threads": recent_threads,
    })


def _safe_link(label, url_name):
    try:
        return {'label': label, 'url': reverse(url_name)}
    except NoReverseMatch:
        return None


def _serialize_helpdesk_answer(answer, suggestions):
    links = [
        link for link in (_safe_link(label, url_name) for label, url_name in answer.links)
        if link
    ]
    return {
        'title': answer.title,
        'answer': answer.answer,
        'links': links,
        'suggestions': [item.title for item in suggestions[:4]],
    }


def helpdesk(request):
    if is_nursing_council_board_member(request.user):
        return redirect("board_nursing_dashboard")
    if getattr(request.user, "is_authenticated", False) and getattr(request.user, "role", "") in {"admin", "registrar"}:
        return redirect("staff_ai_assistant")
    answer = DEFAULT_ANSWER
    suggestions = []
    return render(request, 'notifications/helpdesk.html', {
        'initial_answer': _serialize_helpdesk_answer(answer, suggestions),
    })


@require_POST
def helpdesk_api(request):
    question = request.POST.get('question', '')
    session_id = request.POST.get('session_id', '')
    if not question and request.content_type == 'application/json':
        import json

        try:
            payload = json.loads(request.body.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {}
        question = payload.get('question', '')
        session_id = payload.get('session_id', session_id)
    if not request.session.session_key:
        request.session.save()
    if is_nursing_council_board_member(request.user):
        from apps.board_portal.services import build_board_ai_chat_response

        response = build_board_ai_chat_response(
            request.user,
            question,
            session_id=session_id,
            browser_session_key=request.session.session_key or "",
        )
        return JsonResponse(response)
    conversation, _created = get_or_create_assistant_conversation(
        session_id=session_id,
        assistant_kind="public_helpdesk",
        user=request.user if getattr(request.user, "is_authenticated", False) else None,
        browser_session_key=request.session.session_key or "",
        scope="public",
        role=getattr(request.user, "role", "") if getattr(request.user, "is_authenticated", False) else "",
    )
    answer, suggestions = get_helpdesk_response(question)
    local_payload = _serialize_helpdesk_answer(answer, suggestions)
    response = maybe_generate_live_helpdesk_response(
        question,
        local_payload,
        browser_session_key=request.session.session_key or "",
    )
    response["session_id"] = conversation.session_id
    record_assistant_turn(
        conversation=conversation,
        question=question,
        response=response,
        assistant_kind="public_helpdesk",
        user=request.user if getattr(request.user, "is_authenticated", False) else None,
        browser_session_key=request.session.session_key or "",
        scope="public",
    )
    return JsonResponse(response)


@login_required
def notification_history(request):
    Notification.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())
    notifications = Notification.objects.filter(user=request.user).order_by("-created_at")[:100]
    return render(request, "notifications/notification_history.html", {
        "notifications": notifications,
        "staff_summary": build_staff_notification_summary(request.user),
    })


@login_required
@require_POST
def notification_mark_read(request):
    updated = Notification.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())
    summary = build_user_notification_summary(request.user)
    return JsonResponse({"ok": True, "updated": updated, "count": summary.get("count", 0)})


def _application_status_recipient_email(application):
    professional = getattr(application, "professional", None)
    recipient = getattr(professional, "email", "") if professional else ""
    if recipient:
        return recipient.strip()

    payload = application.payload or {}
    for key in ("email", "email_address", "applicant_email", "contact_email"):
        recipient = payload.get(key)
        if recipient:
            return str(recipient).strip()
    return ""


def send_application_status_email(application):
    recipient = _application_status_recipient_email(application)
    if not recipient:
        return False
    subject = f"Application Update - {application.form_code}"
    message = f"Your application status is now: {application.status.upper()}\n\nNotes: {application.reviewer_notes}"
    return bool(send_mail(subject, message, 'no-reply@ndoh.gov.pg', [recipient], fail_silently=True))


def notify_approval(request, application_id):
    from .tasks import send_application_notification

    send_application_notification.delay(application_id)
    return redirect('advanced_dashboard')
