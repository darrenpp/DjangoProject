from datetime import date, timedelta

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.mail import send_mail
from django.utils import timezone

from apps.accounts.models import User
from apps.notifications.models import Notification
from apps.workforce.models import (
    CommunityHealthWorker,
    HealthStudent,
    MedicalDoctor,
    Midwife,
    MissingDataReview,
    NurseAide,
    NursingProfessional,
    PracticingLicenseRecord,
)


PROFILE_REQUIRED_FIELDS = {
    NursingProfessional: [
        ('first_name', 'First name'),
        ('last_name', 'Last name'),
        ('registration_no', 'Registration number'),
        ('email', 'Email address'),
        ('primary_phone', 'Phone number'),
        ('gender', 'Gender'),
        ('date_of_birth', 'Date of birth'),
        ('province', 'Province'),
        ('qualification_level', 'Qualification'),
        ('license_expiry_date', 'Licence expiry date'),
    ],
    Midwife: [
        ('first_name', 'First name'),
        ('last_name', 'Last name'),
        ('registration_no', 'Registration number'),
        ('email', 'Email address'),
        ('primary_phone', 'Phone number'),
        ('gender', 'Gender'),
        ('date_of_birth', 'Date of birth'),
        ('province', 'Province'),
        ('qualification_level', 'Qualification'),
        ('license_expiry_date', 'Licence expiry date'),
    ],
    MedicalDoctor: [
        ('first_name', 'First name'),
        ('last_name', 'Last name'),
        ('registration_no', 'Registration number'),
        ('email', 'Email address'),
        ('primary_phone', 'Phone number'),
        ('gender', 'Gender'),
        ('date_of_birth', 'Date of birth'),
        ('province', 'Province'),
        ('specialty', 'Specialty or practice area'),
        ('license_expiry_date', 'Licence expiry date'),
    ],
    CommunityHealthWorker: [
        ('first_name', 'First name'),
        ('last_name', 'Last name'),
        ('registration_no', 'Registration number'),
        ('email', 'Email address'),
        ('primary_phone', 'Phone number'),
        ('gender', 'Gender'),
        ('date_of_birth', 'Date of birth'),
        ('province', 'Province'),
        ('community_id', 'Community ID'),
        ('training_level', 'Training level'),
    ],
    NurseAide: [
        ('first_name', 'First name'),
        ('last_name', 'Last name'),
        ('registration_no', 'Registration number'),
        ('email', 'Email address'),
        ('primary_phone', 'Phone number'),
        ('gender', 'Gender'),
        ('date_of_birth', 'Date of birth'),
        ('province', 'Province'),
        ('training_level', 'Training level'),
        ('employer', 'Employer'),
    ],
    HealthStudent: [
        ('first_name', 'First name'),
        ('last_name', 'Last name'),
        ('registration_no', 'Registration number'),
        ('email', 'Email address'),
        ('primary_phone', 'Phone number'),
        ('gender', 'Gender'),
        ('date_of_birth', 'Date of birth'),
        ('province', 'Province'),
        ('program', 'Program'),
        ('institution', 'Training institution'),
        ('expected_graduation_date', 'Expected graduation date'),
    ],
}

LICENSE_RENEWAL_MODELS = (NursingProfessional, Midwife, MedicalDoctor)
MIN_VALID_SOURCE_DATE = date(2000, 1, 1)


def _is_missing(value):
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip() or value.strip().upper() in {'N/A', 'NA', 'NONE', 'UNKNOWN', 'TBA', '-'}
    return False


def _record_name(obj):
    if isinstance(obj, PracticingLicenseRecord):
        return obj.full_name or ''
    return f"{getattr(obj, 'first_name', '')} {getattr(obj, 'last_name', '')}".strip()


def _record_email(obj):
    return getattr(obj, 'email', '') or ''


def _record_registration(obj):
    return getattr(obj, 'registration_no', '') or getattr(obj, 'practitioner_number', '') or ''


def _professional_type(obj):
    return obj._meta.verbose_name.title()


def _severity(missing_count):
    if missing_count >= 5:
        return 'high'
    if missing_count >= 3:
        return 'medium'
    return 'low'


def _invalid_source_date(value):
    if not value:
        return ''
    today = timezone.localdate()
    if value > today:
        return f'Future source date ({value.isoformat()})'
    if value < MIN_VALID_SOURCE_DATE:
        return f'Invalid old source date ({value.isoformat()})'
    return ''


def _find_user_for_record(obj):
    email = _record_email(obj)
    registration_no = _record_registration(obj)
    filters = []
    if email:
        filters.append({'email__iexact': email})
    if registration_no:
        filters.extend([
            {'registration_number__iexact': registration_no},
            {'license_number__iexact': registration_no},
            {'username__iexact': registration_no},
        ])
    for lookup in filters:
        user = User.objects.filter(**lookup).first()
        if user:
            return user
    return None


def _create_notification(user, subject, message):
    if not user:
        return None
    existing = Notification.objects.filter(user=user, subject=subject, message=message).first()
    if existing:
        return existing
    return Notification.objects.create(user=user, subject=subject, message=message)


def _send_email(email, subject, message):
    if not email:
        return False
    try:
        send_mail(
            subject,
            message,
            getattr(settings, 'DEFAULT_FROM_EMAIL', 'no-reply@ndoh.gov.pg'),
            [email],
            fail_silently=True,
        )
    except Exception:
        return False
    return True


def _upsert_review(obj, missing_fields, *, source_label='', source_row=None, send_notifications=False):
    content_type = ContentType.objects.get_for_model(obj)
    missing_count = len(missing_fields)
    defaults = {
        'full_name': _record_name(obj)[:255],
        'registration_no': _record_registration(obj)[:100],
        'email': _record_email(obj),
        'professional_type': _professional_type(obj)[:80],
        'missing_fields': missing_fields,
        'missing_count': missing_count,
        'source_label': source_label[:255],
        'source_row': source_row,
        'status': 'under_review',
        'severity': _severity(missing_count),
        'resolved_at': None,
    }
    review, created = MissingDataReview.objects.update_or_create(
        content_type=content_type,
        object_id=obj.pk,
        defaults=defaults,
    )

    if send_notifications and (created or not review.notification_sent):
        user = _find_user_for_record(obj)
        fields_text = ', '.join(missing_fields)
        subject = 'Profile information required'
        message = (
            f"Dear {_record_name(obj) or 'Registry user'},\n\n"
            f"Your workforce registry profile is under review because important information is missing: {fields_text}.\n\n"
            "Please sign in and update your profile or contact the registry office so your record can be completed."
        )
        notification = _create_notification(user, subject, message)
        email_sent = _send_email(_record_email(obj) or getattr(user, 'email', ''), subject, message)
        review.notification_sent = bool(notification)
        review.email_sent = email_sent
        review.notified_at = timezone.now()
        review.status = 'notified' if notification or email_sent else 'under_review'
        review.save(update_fields=['notification_sent', 'email_sent', 'notified_at', 'status', 'updated_at'])

    return review, created


def _resolve_review(obj):
    content_type = ContentType.objects.get_for_model(obj)
    MissingDataReview.objects.filter(
        content_type=content_type,
        object_id=obj.pk,
    ).exclude(status='resolved').update(
        status='resolved',
        missing_fields=[],
        missing_count=0,
        resolved_at=timezone.now(),
    )


def audit_professional_profiles(*, send_notifications=False):
    created = 0
    updated = 0
    resolved = 0
    reviewed = 0

    for model, fields in PROFILE_REQUIRED_FIELDS.items():
        for obj in model.objects.all().iterator():
            reviewed += 1
            missing = [label for field_name, label in fields if _is_missing(getattr(obj, field_name, None))]
            if missing:
                _review, was_created = _upsert_review(
                    obj,
                    missing,
                    send_notifications=send_notifications,
                )
                if was_created:
                    created += 1
                else:
                    updated += 1
            else:
                before = MissingDataReview.objects.filter(
                    content_type=ContentType.objects.get_for_model(obj),
                    object_id=obj.pk,
                ).exclude(status='resolved').count()
                _resolve_review(obj)
                resolved += before

    return {
        'reviewed': reviewed,
        'created': created,
        'updated': updated,
        'resolved': resolved,
        'open_reviews': MissingDataReview.objects.exclude(status='resolved').count(),
    }


def audit_imported_license_rows(*, batch=None):
    queryset = PracticingLicenseRecord.objects.all()
    if batch:
        queryset = queryset.filter(batch=batch)

    created = 0
    updated = 0
    reviewed = 0
    for record in queryset.iterator():
        reviewed += 1
        missing = []
        if _is_missing(record.full_name):
            missing.append('Full name')
        if _is_missing(record.registration_no) and _is_missing(record.practitioner_number):
            missing.append('Registration or practitioner number')
        if _is_missing(record.record_year):
            missing.append('Record year')
        if record.record_type in {'full', 'temporary', 'provisional'} and _is_missing(record.issued_date):
            missing.append('Issued date')
        if record.record_type in {'practicing_license', 'payment'} and _is_missing(record.payment_date):
            missing.append('Payment date')
        issued_date_issue = _invalid_source_date(record.issued_date)
        if issued_date_issue:
            missing.append(issued_date_issue)
        payment_date_issue = _invalid_source_date(record.payment_date)
        if payment_date_issue:
            missing.append(payment_date_issue)
        if missing:
            _review, was_created = _upsert_review(
                record,
                missing,
                source_label=record.source_sheet_name,
                source_row=record.source_row,
                send_notifications=False,
            )
            if was_created:
                created += 1
            else:
                updated += 1

    return {
        'reviewed': reviewed,
        'created': created,
        'updated': updated,
    }


def notify_expiring_licenses(*, days=30):
    today = date.today()
    threshold = today + timedelta(days=days)
    notified = 0
    for model in LICENSE_RENEWAL_MODELS:
        for obj in model.objects.filter(license_expiry_date__isnull=False, license_expiry_date__gte=today, license_expiry_date__lte=threshold):
            user = _find_user_for_record(obj)
            subject = 'Licence renewal reminder'
            message = (
                f"Dear {_record_name(obj) or 'Registry user'},\n\n"
                f"Your licence expires on {obj.license_expiry_date:%d %b %Y}. "
                "Please submit your renewal application before the expiry date."
            )
            notification = _create_notification(user, subject, message)
            email_sent = _send_email(_record_email(obj) or getattr(user, 'email', ''), subject, message)
            if notification or email_sent:
                notified += 1
    return {'notified': notified, 'days': days}


def dashboard_review_context(professional, user=None):
    reviews = MissingDataReview.objects.none()
    if professional:
        reviews = MissingDataReview.objects.filter(
            content_type=ContentType.objects.get_for_model(professional),
            object_id=professional.pk,
        ).exclude(status='resolved')
    notifications = Notification.objects.none()
    if user and user.is_authenticated:
        notifications = Notification.objects.filter(user=user).order_by('-created_at')[:10]
    return {
        'missing_data_reviews': reviews,
        'profile_notifications': notifications,
    }
