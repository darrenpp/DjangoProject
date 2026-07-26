from apps.accounts.models import SecurityAuditEvent
from apps.workforce.models import AuditLog

from ..models import MobileSyncEvent, MobileSubmissionStatusHistory


def request_ip(request):
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def request_user_agent(request):
    if request is None:
        return ""
    return request.META.get("HTTP_USER_AGENT", "")


def log_security_event(action, request=None, user=None, username="", details=None):
    SecurityAuditEvent.objects.create(
        user=user if getattr(user, "is_authenticated", False) else None,
        username=username or getattr(user, "username", ""),
        action=action,
        ip_address=request_ip(request),
        user_agent=request_user_agent(request),
        path=getattr(request, "path", "") if request else "",
        details=details or {},
    )


def log_audit(action, entity, request=None, actor=None, old_values=None, new_values=None):
    AuditLog.objects.create(
        actor=actor or (request.user if request and getattr(request.user, "is_authenticated", False) else None),
        action=action,
        entity_type=entity.__class__.__name__ if entity is not None else "",
        entity_id=str(getattr(entity, "pk", "") or ""),
        old_values_json=old_values or {},
        new_values_json=new_values or {},
        ip_address=request_ip(request),
        user_agent=request_user_agent(request),
    )


def log_sync_event(submission=None, device=None, user=None, event_type="", status_before="", status_after="", message="", request=None):
    MobileSyncEvent.objects.create(
        submission=submission,
        device=device,
        user=user if getattr(user, "is_authenticated", False) else None,
        event_type=event_type,
        status_before=status_before or "",
        status_after=status_after or "",
        message=message or "",
        ip_address=request_ip(request),
        user_agent=request_user_agent(request),
    )


def record_status_change(submission, new_status, user=None, note="", metadata=None, request=None):
    old_status = submission.status
    if old_status == new_status:
        return submission
    submission.status = new_status
    submission.save(update_fields=["status", "updated_at"])
    MobileSubmissionStatusHistory.objects.create(
        submission=submission,
        old_status=old_status,
        new_status=new_status,
        changed_by=user if getattr(user, "is_authenticated", False) else None,
        note=note or "",
        metadata=metadata or {},
    )
    log_sync_event(
        submission=submission,
        device=submission.device,
        user=user,
        event_type="MOBILE_STATUS_CHANGED",
        status_before=old_status,
        status_after=new_status,
        message=note,
        request=request,
    )
    log_audit(
        "MOBILE_SUBMISSION_STATUS_CHANGED",
        submission,
        request=request,
        actor=user,
        old_values={"status": old_status},
        new_values={"status": new_status, "note": note, "metadata": metadata or {}},
    )
    return submission
