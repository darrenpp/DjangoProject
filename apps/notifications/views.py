from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import NoReverseMatch, reverse
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.dashboard.access import is_medical_board_user, is_nursing_council_user
from apps.workforce.models import Application

from .helpdesk import DEFAULT_ANSWER, get_helpdesk_response
from .models import EnquiryMessage, EnquiryThread
from .services import build_staff_notification_summary


def _office_for_user(user):
    if is_medical_board_user(user) and not is_nursing_council_user(user):
        return 'medical'
    if is_nursing_council_user(user):
        return 'nursing'
    return 'general'


def _thread_queryset_for_user(user):
    qs = EnquiryThread.objects.select_related('created_by', 'assigned_to').prefetch_related('messages')
    if user.role == 'admin':
        return qs
    if user.role == 'registrar':
        offices = ['general']
        if is_nursing_council_user(user):
            offices.append('nursing')
        if is_medical_board_user(user):
            offices.append('medical')
        return qs.filter(Q(office__in=offices) | Q(created_by=user) | Q(assigned_to=user)).distinct()
    return qs.filter(created_by=user)


def _notify_thread_participants(thread, message):
    recipients = set()
    if thread.created_by.email and thread.created_by_id != message.sender_id:
        recipients.add(thread.created_by.email)
    if thread.assigned_to and thread.assigned_to.email and thread.assigned_to_id != message.sender_id:
        recipients.add(thread.assigned_to.email)
    if not thread.assigned_to:
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
    send_mail(
        f"NDOH Registry enquiry: {thread.subject}",
        message.body,
        getattr(settings, 'DEFAULT_FROM_EMAIL', 'no-reply@ndoh.gov.pg'),
        list(recipients),
        fail_silently=True,
    )
    message.emailed = True
    message.save(update_fields=['emailed'])
    return True


@login_required
def enquiry_inbox(request):
    threads = _thread_queryset_for_user(request.user)
    return render(request, 'notifications/enquiry_inbox.html', {
        'threads': threads,
        'staff_summary': build_staff_notification_summary(request.user),
    })


@login_required
def enquiry_create(request):
    if request.method == 'POST':
        subject = request.POST.get('subject', '').strip()
        body = request.POST.get('body', '').strip()
        office = request.POST.get('office') or _office_for_user(request.user)
        if office not in {'general', 'nursing', 'medical'}:
            office = 'general'
        if subject and body:
            thread = EnquiryThread.objects.create(
                subject=subject,
                office=office,
                created_by=request.user,
            )
            message = EnquiryMessage.objects.create(thread=thread, sender=request.user, body=body)
            _notify_thread_participants(thread, message)
            messages.success(request, 'Your enquiry has been created and sent to the right team.')
            return redirect('enquiry_thread', pk=thread.pk)
        messages.error(request, 'Please enter both a subject and message.')
    return render(request, 'notifications/enquiry_form.html', {
        'default_office': _office_for_user(request.user),
    })


@login_required
def enquiry_thread(request, pk):
    thread = get_object_or_404(_thread_queryset_for_user(request.user), pk=pk)
    if request.method == 'POST':
        body = request.POST.get('body', '').strip()
        status = request.POST.get('status')
        if request.user.role in {'admin', 'registrar'} and status in {'open', 'pending', 'closed'}:
            thread.status = status
            thread.save(update_fields=['status', 'updated_at'])
        if body:
            message = EnquiryMessage.objects.create(thread=thread, sender=request.user, body=body)
            thread.status = 'pending' if request.user.role not in {'admin', 'registrar'} else 'open'
            thread.save(update_fields=['status', 'updated_at'])
            _notify_thread_participants(thread, message)
            messages.success(request, 'Message sent.')
            return redirect('enquiry_thread', pk=thread.pk)
        if not body and status:
            messages.success(request, 'Thread status updated.')
            return redirect('enquiry_thread', pk=thread.pk)
        messages.error(request, 'Please enter a message before sending.')
    return render(request, 'notifications/enquiry_thread.html', {
        'thread': thread,
        'staff_summary': build_staff_notification_summary(request.user),
    })


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
    if not question and request.content_type == 'application/json':
        import json

        try:
            payload = json.loads(request.body.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {}
        question = payload.get('question', '')
    answer, suggestions = get_helpdesk_response(question)
    return JsonResponse(_serialize_helpdesk_answer(answer, suggestions))


def send_application_status_email(application):
    subject = f"Application Update - {application.form_code}"
    message = f"Your application status is now: {application.status.upper()}\n\nNotes: {application.reviewer_notes}"
    send_mail(subject, message, 'no-reply@ndoh.gov.pg', [application.professional.email])


def notify_approval(request, application_id):
    from .tasks import send_application_notification

    send_application_notification.delay(application_id)
    return redirect('advanced_dashboard')
