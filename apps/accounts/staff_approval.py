from django.db.models import Q

from apps.dashboard.access import is_medical_board_staff, is_nursing_council_staff, is_system_admin
from apps.notifications.models import Notification

from .models import User


def is_staff_account_pending_approval(user):
    return (
        getattr(user, "role", "") in User.STAFF_LOGIN_APPROVAL_ROLES
        and (
            not getattr(user, "role_approved", False)
            or not getattr(user, "system_admin_approved", False)
        )
    )


def staff_account_scope(user):
    if getattr(user, "role", "") == "admin":
        return "general"
    if is_medical_board_staff(user):
        return "medical"
    if is_nursing_council_staff(user):
        return "nursing"
    return "general"


def staff_account_scope_label(user):
    return {
        "medical": "Medical Board",
        "nursing": "Nursing Council",
        "general": "General / Cross-office",
    }.get(staff_account_scope(user), "General / Cross-office")


def can_registrar_approve_staff_account(actor, target_user):
    if not getattr(actor, "is_authenticated", False):
        return False
    if getattr(actor, "role", "") != "registrar":
        return False
    if not getattr(actor, "role_approved", False) or not getattr(actor, "system_admin_approved", False):
        return False
    if not is_staff_account_pending_approval(target_user):
        return False
    if getattr(target_user, "role_approved", False):
        return False

    target_scope = staff_account_scope(target_user)
    if target_scope == "medical":
        return is_medical_board_staff(actor)
    if target_scope == "nursing":
        return is_nursing_council_staff(actor)
    return is_medical_board_staff(actor) or is_nursing_council_staff(actor)


def can_system_admin_approve_staff_account(actor, target_user):
    return (
        is_system_admin(actor)
        and is_staff_account_pending_approval(target_user)
        and not getattr(target_user, "system_admin_approved", False)
    )


def pending_staff_accounts_for_approver(user):
    if not getattr(user, "is_authenticated", False):
        return User.objects.none()
    if getattr(user, "role", "") not in {"admin", "registrar"}:
        return User.objects.none()

    queryset = (
        User.objects.filter(role__in=User.STAFF_LOGIN_APPROVAL_ROLES, is_active=True)
        .filter(Q(role_approved=False) | Q(system_admin_approved=False))
        .order_by("date_joined", "username")
    )
    if is_system_admin(user):
        return queryset
    if getattr(user, "role", "") != "registrar":
        return queryset.none()

    visible_ids = []
    for pending_user in queryset:
        scope = staff_account_scope(pending_user)
        if scope == "medical" and is_medical_board_staff(user):
            visible_ids.append(pending_user.pk)
        elif scope == "nursing" and is_nursing_council_staff(user):
            visible_ids.append(pending_user.pk)
        elif scope == "general" and (is_medical_board_staff(user) or is_nursing_council_staff(user)):
            visible_ids.append(pending_user.pk)
    return queryset.filter(pk__in=visible_ids)


def approved_staff_approval_recipients(pending_user):
    system_admins = list(
        User.objects.filter(
            role="admin",
            is_superuser=True,
            is_active=True,
            role_approved=True,
            system_admin_approved=True,
        )
    )
    registrars = User.objects.filter(
        role="registrar",
        is_active=True,
        role_approved=True,
        system_admin_approved=True,
    )

    scope = staff_account_scope(pending_user)
    if scope == "medical":
        scoped_registrars = [registrar for registrar in registrars if is_medical_board_staff(registrar)]
    elif scope == "nursing":
        scoped_registrars = [registrar for registrar in registrars if is_nursing_council_staff(registrar)]
    else:
        scoped_registrars = list(registrars)

    recipients = []
    seen = set()
    for recipient in [*scoped_registrars, *system_admins]:
        if recipient.pk in seen or recipient.pk == pending_user.pk:
            continue
        recipients.append(recipient)
        seen.add(recipient.pk)
    return recipients


def notify_staff_account_approval_request(pending_user, group_config):
    subject = f"Staff account approval required: {pending_user.username}"
    display_name = pending_user.get_full_name() or pending_user.username
    token_text = ""
    if getattr(pending_user, "role", "") == "board_member" and getattr(pending_user, "board_registration_token", ""):
        token_text = f" Board request token: {pending_user.board_registration_token}."
    message = (
        f"{display_name} requested {group_config['label']} access. "
        f"Username: {pending_user.username}. Department: {pending_user.department or 'Not supplied'}. "
        f"{token_text}"
        "Registrar approval and System Admin approval are both required before this staff account can log in."
    )

    created = 0
    for recipient in approved_staff_approval_recipients(pending_user):
        _, was_created = Notification.objects.get_or_create(
            user=recipient,
            subject=subject,
            message=message,
        )
        if was_created:
            created += 1
    return created
