import random
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.mail import send_mail
from django.utils import timezone

from .models import SecurityAuditEvent, UserMFAChallenge


def get_client_ip(request):
    forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR') or None


def audit_security_event(action, *, user=None, username='', request=None, details=None):
    return SecurityAuditEvent.objects.create(
        user=user if getattr(user, 'is_authenticated', False) else None,
        username=username or getattr(user, 'username', '') or '',
        action=action,
        ip_address=get_client_ip(request) if request else None,
        user_agent=request.META.get('HTTP_USER_AGENT', '') if request else '',
        path=request.path if request else '',
        details=details or {},
    )


def staff_mfa_enabled():
    return bool(getattr(settings, 'REQUIRE_STAFF_MFA', False))


def staff_mfa_required(user):
    if not staff_mfa_enabled():
        return False
    return (
        getattr(user, 'is_authenticated', False)
        and getattr(user, 'is_active', False)
        and getattr(user, 'role', '') in set(getattr(settings, 'STAFF_MFA_ROLES', ('admin', 'registrar')))
    )


def session_has_valid_mfa(request, user):
    return (
        request.session.get('staff_mfa_verified_user_id') == user.pk
        and bool(request.session.get('staff_mfa_verified_at'))
    )


def clear_staff_mfa_session(request):
    request.session.pop('staff_mfa_verified_user_id', None)
    request.session.pop('staff_mfa_verified_at', None)


def create_staff_mfa_challenge(user, *, request=None):
    timeout_seconds = int(getattr(settings, 'STAFF_MFA_TIMEOUT_SECONDS', 600))
    code = f"{random.SystemRandom().randint(0, 999999):06d}"
    challenge = UserMFAChallenge.objects.create(
        user=user,
        code_hash=make_password(code),
        sent_to=user.email or '',
        expires_at=timezone.now() + timedelta(seconds=timeout_seconds),
    )
    subject = 'Security verification code'
    message = (
        "Your security verification code for the NDOH Regulatory Bodies Online Workforce System is "
        f"{code}. This code expires in {timeout_seconds // 60} minutes. If you did not request this, "
        "contact the System Admin immediately."
    )

    if not user.email:
        raise ValueError('Staff MFA requires a registered email address.')

    try:
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)
    except Exception as exc:  # pragma: no cover - depends on deployment email service
        audit_security_event(
            'MFA_CHALLENGE_CREATED',
            user=user,
            request=request,
            details={'delivery': 'email_failed', 'error': str(exc)},
        )
        raise

    audit_security_event(
        'MFA_CHALLENGE_CREATED',
        user=user,
        request=request,
        details={'delivery': 'email', 'sent_to': user.email},
    )
    return challenge


def verify_staff_mfa_code(user, code, *, request=None):
    code = (code or '').strip()
    challenge = (
        UserMFAChallenge.objects
        .filter(user=user, purpose='login', verified_at__isnull=True)
        .order_by('-created_at')
        .first()
    )
    if not challenge:
        audit_security_event('MFA_FAILED', user=user, request=request, details={'reason': 'no_active_challenge'})
        return False, 'No active verification code was found. Please request a new code.'

    if challenge.is_expired:
        audit_security_event('MFA_FAILED', user=user, request=request, details={'reason': 'expired'})
        return False, 'This verification code has expired. Please request a new code.'

    if challenge.attempts >= 5:
        audit_security_event('MFA_FAILED', user=user, request=request, details={'reason': 'too_many_attempts'})
        return False, 'Too many incorrect attempts. Please request a new code.'

    challenge.attempts += 1
    challenge.save(update_fields=['attempts'])

    if not check_password(code, challenge.code_hash):
        audit_security_event(
            'MFA_FAILED',
            user=user,
            request=request,
            details={'reason': 'incorrect_code', 'attempts': challenge.attempts},
        )
        return False, 'The verification code is incorrect.'

    challenge.verified_at = timezone.now()
    challenge.save(update_fields=['verified_at'])
    audit_security_event('MFA_VERIFIED', user=user, request=request)
    return True, 'Security verification completed.'
