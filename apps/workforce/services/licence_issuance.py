from datetime import date
from io import BytesIO

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.core.mail import EmailMessage
from django.db.models import Q
from django.utils import timezone

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from apps.accounts.models import User
from apps.dashboard.access import MEDICAL_BOARD_FORM_CODES
from apps.notifications.models import (
    EnquiryMailboxState,
    EnquiryMessage,
    EnquiryMessageAttachment,
    EnquiryThread,
    Notification,
)
from apps.notifications.services import mark_thread_read_for_user
from apps.workforce.models import IssuedLicenceDocument, PracticingLicenseRecord
from apps.workforce.services.nursing_council_workflows import (
    NursingCouncilValidationService,
    audit_action,
    is_nursing_council_application,
)


DOCUMENT_PREFIXES = {
    'authority_to_practice': 'ATP',
    'full_licence': 'FULL',
    'provisional_licence': 'PROV',
    'temporary_licence': 'TEMP',
}


def issue_application_licence_document(application, *, issuer, delivery_channel='both', request=None):
    if application.status != 'approved':
        raise ValueError("Only approved applications can have official practice documents issued.")

    practicing_record = _latest_practicing_record(application)
    document_type = _document_type_for_application(application, practicing_record)
    recipient = _recipient_details(application)
    actual_delivery, delivery_note = _resolve_delivery_channel(delivery_channel, recipient)

    issued = IssuedLicenceDocument(
        application=application,
        practicing_record=practicing_record,
        document_type=document_type,
        document_number=_next_document_number(application, document_type),
        issued_by=issuer,
        recipient_user=recipient["user"],
        recipient_name=recipient["name"],
        recipient_email=recipient["email"],
        delivery_channel=actual_delivery,
        notes=delivery_note,
    )
    pdf_bytes = _render_licence_pdf(issued, application, practicing_record, recipient)
    filename = _document_filename(issued)
    issued.file.save(filename, ContentFile(pdf_bytes), save=False)
    issued.save()

    subject = f"{issued.get_document_type_display()} issued - {application.form_code}"
    body = _delivery_body(issued, application, recipient)

    mailbox_thread = None
    mailbox_sent = False
    if actual_delivery in {'mailbox', 'both'}:
        mailbox_thread = _create_mailbox_delivery(
            issued,
            subject=subject,
            body=body,
            sender=issuer,
            recipient=recipient,
            pdf_bytes=pdf_bytes,
            filename=filename,
        )
        mailbox_sent = True

    email_sent = False
    if actual_delivery in {'email', 'both'}:
        email_sent = _send_email_delivery(
            recipient["email"],
            subject=subject,
            body=body,
            pdf_bytes=pdf_bytes,
            filename=filename,
        )

    issued.mailbox_thread = mailbox_thread
    issued.mailbox_sent = mailbox_sent
    issued.email_sent = email_sent
    issued.sent_at = timezone.now() if mailbox_sent or email_sent else None
    issued.status = 'sent' if mailbox_sent or email_sent else 'failed'
    if actual_delivery in {'email', 'both'} and not email_sent:
        issued.notes = f"{issued.notes}\nEmail delivery failed or no email backend accepted the message.".strip()
    issued.save(update_fields=[
        'mailbox_thread',
        'mailbox_sent',
        'email_sent',
        'sent_at',
        'status',
        'notes',
    ])

    audit_action(
        "LICENCE_DOCUMENT_ISSUED",
        application,
        actor=issuer,
        request=request,
        new_values={
            "issued_document_id": issued.pk,
            "document_type": issued.document_type,
            "delivery_channel": issued.delivery_channel,
            "email_sent": issued.email_sent,
            "mailbox_sent": issued.mailbox_sent,
        },
    )
    return issued


def _latest_practicing_record(application):
    return PracticingLicenseRecord.objects.filter(
        source_sheet_name="Live workflow approvals",
        source_row=application.pk,
    ).order_by("-created_at", "-pk").first()


def _document_type_for_application(application, practicing_record=None):
    record_type = getattr(practicing_record, "record_type", "")
    if record_type == "provisional":
        return "provisional_licence"
    if record_type == "temporary":
        return "temporary_licence"
    if record_type in {"full", "full_approved"}:
        return "full_licence"
    if record_type == "practicing_license":
        return "authority_to_practice"

    form_code = (application.form_code or "").upper()
    if form_code in {"NC1", "NC4"}:
        return "provisional_licence"
    if form_code in {"NC8", "NC9"}:
        return "temporary_licence"
    if form_code in {"NC3", "MD2", "MBRN"}:
        return "authority_to_practice"
    if form_code in {"NC2", "NC5", "NC6", "NC7", "NC10", "NC11", "MD1", "CHW1", "MBSP"}:
        return "full_licence"

    pathway = _resolved_pathway(application)
    licence_type = getattr(pathway, "creates_licence_type", "") if pathway else ""
    if licence_type == "provisional":
        return "provisional_licence"
    if licence_type == "temporary":
        return "temporary_licence"
    if licence_type == "renewal":
        return "authority_to_practice"
    return "full_licence"


def _resolved_pathway(application):
    if not is_nursing_council_application(application):
        return None
    try:
        return NursingCouncilValidationService(application)._resolve_pathway(application)
    except Exception:
        return None


def _recipient_details(application):
    professional = getattr(application, "professional", None)
    payload = application.payload or {}
    email = _first_nonempty(
        getattr(professional, "email", "") if professional else "",
        payload.get("email"),
        payload.get("email_address"),
        payload.get("applicant_email"),
        payload.get("contact_email"),
    )
    name = _first_nonempty(
        getattr(professional, "full_name", "") if professional else "",
        _join_name(getattr(professional, "first_name", ""), getattr(professional, "last_name", "")) if professional else "",
        payload.get("full_name"),
        _join_name(payload.get("first_name", ""), payload.get("last_name", "")),
        "Client",
    )
    user = _linked_user_for_application(application, professional, email)
    if user:
        email = email or user.email or ""
        name = _first_nonempty(user.get_full_name(), name)

    content_type = ContentType.objects.get_for_model(professional) if professional else None
    return {
        "user": user,
        "email": (email or "").strip(),
        "name": name,
        "professional": professional,
        "content_type": content_type,
        "object_id": getattr(professional, "pk", None),
    }


def _linked_user_for_application(application, professional, email):
    if professional:
        content_type = ContentType.objects.get_for_model(professional)
        user = User.objects.filter(
            professional_content_type=content_type,
            professional_object_id=professional.pk,
        ).order_by("-professional_linked_at", "pk").first()
        if user:
            return user

    if email:
        user = User.objects.filter(email__iexact=email).order_by("pk").first()
        if user:
            return user

    identifiers = [
        getattr(professional, "registration_no", "") if professional else "",
        getattr(professional, "registration_number", "") if professional else "",
        (application.payload or {}).get("registration_number", ""),
        (application.payload or {}).get("practitioner_number", ""),
    ]
    identifiers = [str(value).strip() for value in identifiers if value]
    if identifiers:
        return User.objects.filter(_identifier_query(identifiers)).order_by("pk").first()
    return None


def _identifier_query(identifiers):
    query = Q()
    for identifier in identifiers:
        query |= Q(username__iexact=identifier)
        query |= Q(license_number__iexact=identifier)
        query |= Q(registration_number__iexact=identifier)
    return query


def _resolve_delivery_channel(requested, recipient):
    requested = requested if requested in {'mailbox', 'email', 'both'} else 'both'
    has_mailbox = bool(recipient["user"])
    has_email = bool(recipient["email"])

    if requested == 'mailbox':
        if not has_mailbox:
            raise ValueError("This client is not linked to a portal mailbox. Link their user account or choose email delivery.")
        return 'mailbox', ''
    if requested == 'email':
        if not has_email:
            raise ValueError("This client does not have an email address on file. Add an email or choose mailbox delivery.")
        return 'email', ''

    if has_mailbox and has_email:
        return 'both', ''
    if has_mailbox:
        return 'mailbox', 'No client email was found, so the document was delivered through the platform mailbox only.'
    if has_email:
        return 'email', 'No linked client mailbox was found, so the document was delivered by email only.'
    raise ValueError("This client needs either a linked portal mailbox or an email address before the document can be issued.")


def _next_document_number(application, document_type):
    prefix = DOCUMENT_PREFIXES[document_type]
    timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
    base = f"{prefix}-{application.pk}-{timestamp}"
    document_number = base
    suffix = 1
    while IssuedLicenceDocument.objects.filter(document_number=document_number).exists():
        suffix += 1
        document_number = f"{base}-{suffix}"
    return document_number


def _document_filename(issued):
    label = issued.get_document_type_display().lower().replace(" ", "_")
    return f"{label}_{issued.document_number}.pdf"


def _render_licence_pdf(issued, application, practicing_record, recipient):
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    y = height - 70

    office = _office_title(application, recipient["professional"])
    document_label = issued.get_document_type_display()
    professional = recipient["professional"]

    pdf.setTitle(f"{document_label} - {recipient['name']}")
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawCentredString(width / 2, y, office)
    y -= 24
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawCentredString(width / 2, y, document_label.upper())
    y -= 38

    pdf.setFont("Helvetica", 10)
    _draw_kv(pdf, "Document Number", issued.document_number, 70, y)
    _draw_kv(pdf, "Application", f"{application.form_code} - {application.form_title or application.get_form_code_display()}", 320, y)
    y -= 28
    _draw_kv(pdf, "Issued Date", _date_text(timezone.localdate()), 70, y)
    _draw_kv(pdf, "Valid Until", _date_text(application.expiry_date), 320, y)
    y -= 46

    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(70, y, "Practitioner")
    y -= 20
    pdf.setFont("Helvetica", 10)
    _draw_kv(pdf, "Name", recipient["name"], 70, y)
    y -= 18
    _draw_kv(pdf, "Registration No.", _first_nonempty(getattr(professional, "registration_no", ""), getattr(practicing_record, "registration_no", "")), 70, y)
    _draw_kv(pdf, "Practitioner No.", _first_nonempty(getattr(professional, "registration_number", ""), getattr(practicing_record, "practitioner_number", "")), 320, y)
    y -= 18
    _draw_kv(pdf, "Cadre / Category", _first_nonempty(_cadre_name(professional), getattr(practicing_record, "category", ""), application.profession_track), 70, y)
    _draw_kv(pdf, "Province", _first_nonempty(getattr(professional, "province", ""), getattr(practicing_record, "province", "")), 320, y)
    y -= 44

    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(70, y, "Authority Statement")
    y -= 20
    pdf.setFont("Helvetica", 10)
    statement = (
        f"This document confirms that {recipient['name']} has been screened and approved by the registrar "
        f"for the above {document_label.lower()} under the NDOH Regulatory Bodies Online Workforce System."
    )
    y = _draw_wrapped(pdf, statement, 70, y, width - 140)
    y -= 20
    y = _draw_wrapped(
        pdf,
        "The recipient may present this document as official evidence of the issued authority, subject to the licence conditions, expiry date, and any applicable legislation or council policy.",
        70,
        y,
        width - 140,
    )
    y -= 46

    pdf.line(70, y, 250, y)
    pdf.setFont("Helvetica", 9)
    pdf.drawString(70, y - 14, "Registrar / Authorized Officer")
    pdf.drawRightString(width - 70, y - 14, f"Generated: {_date_text(timezone.localdate())}")
    y -= 62

    pdf.setFont("Helvetica-Oblique", 8)
    _draw_wrapped(
        pdf,
        "This document was generated from the approved application record and archived issuance history. Verify against the official registry if authenticity is in question.",
        70,
        y,
        width - 140,
        line_height=10,
    )
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def _create_mailbox_delivery(issued, *, subject, body, sender, recipient, pdf_bytes, filename):
    thread = EnquiryThread.objects.create(
        subject=subject,
        office=_office_key(issued.application, recipient["professional"]),
        created_by=sender,
        recipient_user=recipient["user"],
        recipient_content_type=recipient["content_type"],
        recipient_object_id=recipient["object_id"],
        recipient_name=recipient["name"],
        recipient_email=recipient["email"],
        delivery_channel='mailbox' if issued.delivery_channel == 'mailbox' else 'both',
    )
    message = EnquiryMessage.objects.create(thread=thread, sender=sender, body=body)
    attachment = EnquiryMessageAttachment(
        message=message,
        original_filename=filename,
        content_type='application/pdf',
        file_size=len(pdf_bytes),
    )
    attachment.file.save(filename, ContentFile(pdf_bytes), save=True)

    EnquiryMailboxState.objects.get_or_create(user=recipient["user"], thread=thread)
    mark_thread_read_for_user(thread, sender)
    Notification.objects.create(
        user=recipient["user"],
        subject=subject,
        message=body,
        sent=issued.delivery_channel in {'email', 'both'},
    )
    return thread


def _send_email_delivery(recipient_email, *, subject, body, pdf_bytes, filename):
    if not recipient_email:
        return False
    email = EmailMessage(
        f"NDOH Regulatory Bodies: {subject}",
        body,
        getattr(settings, 'DEFAULT_FROM_EMAIL', 'no-reply@ndoh.gov.pg'),
        [recipient_email],
    )
    email.attach(filename, pdf_bytes, 'application/pdf')
    return bool(email.send(fail_silently=True))


def _delivery_body(issued, application, recipient):
    expiry = _date_text(application.expiry_date)
    return (
        f"Dear {recipient['name']},\n\n"
        f"Your {issued.get_document_type_display()} has been issued after registrar screening and approval.\n\n"
        f"Document number: {issued.document_number}\n"
        f"Application: {application.form_code}\n"
        f"Valid until: {expiry or 'See attached document'}\n\n"
        "Please keep the attached document for your records."
    )


def _office_key(application, professional=None):
    if (application.form_code or "").upper() in MEDICAL_BOARD_FORM_CODES:
        return 'medical'
    if getattr(professional, "_meta", None) and professional._meta.model_name in {"medicaldoctor", "communityhealthworker"}:
        return 'medical'
    return 'nursing'


def _office_title(application, professional=None):
    if _office_key(application, professional) == 'medical':
        return "The Medical Board of Papua New Guinea"
    return "PNG Nursing Council"


def _draw_kv(pdf, label, value, x, y):
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(x, y, f"{label}:")
    pdf.setFont("Helvetica", 9)
    pdf.drawString(x + 92, y, str(value or "-")[:60])


def _draw_wrapped(pdf, text, x, y, max_width, line_height=13):
    words = str(text or "").split()
    line = ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if pdf.stringWidth(candidate, "Helvetica", 10) <= max_width:
            line = candidate
            continue
        pdf.drawString(x, y, line)
        y -= line_height
        line = word
    if line:
        pdf.drawString(x, y, line)
        y -= line_height
    return y


def _date_text(value):
    if isinstance(value, date):
        return value.strftime("%d %b %Y")
    return ""


def _first_nonempty(*values):
    for value in values:
        if value:
            return str(value).strip()
    return ""


def _join_name(first_name, last_name):
    return f"{first_name or ''} {last_name or ''}".strip()


def _cadre_name(professional):
    cadre = getattr(professional, "cadre", None)
    return getattr(cadre, "name", "") if cadre else ""
