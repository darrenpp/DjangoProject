from django.contrib.auth import get_user_model
from django.utils import timezone

from ..constants import OFFICE_SCOPE_MEDICAL, OFFICE_SCOPE_NURSING
from ..models import MobileDevice
from ..permissions import user_mobile_office_scopes


def get_or_create_device(device_uuid, *, device_name="", platform="android", app_version="", user=None):
    if not device_uuid:
        return None
    device, created = MobileDevice.objects.get_or_create(
        device_uuid=device_uuid,
        defaults={
            "device_name": device_name or "",
            "platform": platform or "android",
            "app_version": app_version or "",
            "registered_by": user if getattr(user, "is_authenticated", False) else None,
        },
    )
    updates = {"last_seen_at": timezone.now()}
    if device_name and device.device_name != device_name:
        updates["device_name"] = device_name
    if app_version and device.app_version != app_version:
        updates["app_version"] = app_version
    if platform and device.platform != platform:
        updates["platform"] = platform
    for key, value in updates.items():
        setattr(device, key, value)
    device.save(update_fields=list(updates.keys()))
    return device


def primary_office_scope(user):
    scopes = user_mobile_office_scopes(user)
    if OFFICE_SCOPE_NURSING in scopes and len(scopes) == 1:
        return OFFICE_SCOPE_NURSING
    if OFFICE_SCOPE_MEDICAL in scopes and len(scopes) == 1:
        return OFFICE_SCOPE_MEDICAL
    if OFFICE_SCOPE_NURSING in scopes:
        return OFFICE_SCOPE_NURSING
    if scopes:
        return sorted(scopes)[0]
    return ""


def mobile_capabilities(user):
    scopes = user_mobile_office_scopes(user)
    role = getattr(user, "role", "")
    return {
        "can_submit_nursing": OFFICE_SCOPE_NURSING in scopes and role in {"admin", "registrar", "reviewer", "mobile_collector"},
        "can_submit_medical": OFFICE_SCOPE_MEDICAL in scopes and role in {"admin", "registrar", "reviewer", "mobile_collector"},
        "can_upload_attachments": bool(scopes),
        "can_create_local_accounts": role in {"admin", "registrar", "reviewer", "mobile_collector"},
    }


def create_backend_user_for_account_request(account_request, reviewer):
    User = get_user_model()
    user, created = User.objects.get_or_create(
        username=account_request.username,
        defaults={
            "first_name": account_request.full_name.split(" ", 1)[0],
            "last_name": account_request.full_name.split(" ", 1)[1] if " " in account_request.full_name else "",
            "email": account_request.email,
            "phone": account_request.phone,
            "role": "mobile_collector",
            "department": "Medical Board Mobile Intake" if account_request.office_scope == "medical" else "Nursing Council Mobile Intake",
            "cadre_name": account_request.requested_cadre,
            "role_approved": True,
            "approved_by": reviewer,
            "approved_at": timezone.now(),
        },
    )
    if created:
        user.set_unusable_password()
        user.save()
    account_request.linked_user = user
    account_request.status = "APPROVED"
    account_request.reviewed_by = reviewer
    account_request.reviewed_at = timezone.now()
    account_request.save(update_fields=["linked_user", "status", "reviewed_by", "reviewed_at", "updated_at"])
    return user
