from rest_framework.permissions import BasePermission

from apps.dashboard.access import (
    can_manage_regulatory_operations,
    is_data_quality_reviewer,
    is_finance_reviewer,
    is_medical_board_staff,
    is_nursing_council_staff,
    is_system_admin,
)

from .constants import OFFICE_SCOPE_GENERAL, OFFICE_SCOPE_MEDICAL, OFFICE_SCOPE_NURSING


def _profile_text(user):
    values = [
        getattr(user, "department", ""),
        getattr(user, "cadre_name", ""),
        getattr(user, "job_title", ""),
        getattr(user, "username", ""),
        getattr(user, "email", ""),
    ]
    return " ".join(str(value or "") for value in values).lower()


def user_mobile_office_scopes(user):
    if not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        return set()
    if is_system_admin(user):
        return {OFFICE_SCOPE_GENERAL, OFFICE_SCOPE_NURSING, OFFICE_SCOPE_MEDICAL}
    if is_finance_reviewer(user):
        return set()
    if is_medical_board_staff(user) or getattr(user, "role", "") in {"doctor", "chw"}:
        return {OFFICE_SCOPE_MEDICAL}
    if is_nursing_council_staff(user) or getattr(user, "role", "") in {"nurse", "nurse_aide", "graduand"}:
        return {OFFICE_SCOPE_NURSING}
    if getattr(user, "role", "") == "mobile_collector":
        profile = _profile_text(user)
        if any(token in profile for token in ("medical", "doctor", "chw", "community health")):
            return {OFFICE_SCOPE_MEDICAL}
        return {OFFICE_SCOPE_NURSING}
    return set()


def can_use_mobile_api(user):
    if not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        return False
    if is_system_admin(user):
        return True
    role = getattr(user, "role", "")
    if role == "registrar":
        return bool(getattr(user, "role_approved", False))
    if role == "reviewer":
        return bool(getattr(user, "operations_approved", False) or is_data_quality_reviewer(user))
    if role == "mobile_collector":
        return bool(getattr(user, "role_approved", False) or getattr(user, "operations_approved", False))
    return bool(getattr(user, "operations_approved", False) and user_mobile_office_scopes(user))


def can_review_mobile_intake(user, office_scope=None):
    if not can_use_mobile_api(user):
        return False
    if is_finance_reviewer(user):
        return False
    if not (can_manage_regulatory_operations(user) or is_data_quality_reviewer(user)):
        return False
    return not office_scope or office_scope in user_mobile_office_scopes(user)


def can_decide_mobile_submission(user, office_scope=None):
    if is_finance_reviewer(user):
        return False
    if is_system_admin(user):
        return True
    if getattr(user, "role", "") == "registrar" and getattr(user, "role_approved", False):
        return not office_scope or office_scope in user_mobile_office_scopes(user)
    return (
        getattr(user, "role", "") == "reviewer"
        and getattr(user, "operations_approved", False)
        and (not office_scope or office_scope in user_mobile_office_scopes(user))
    )


def can_access_submission(user, submission):
    return submission.office_scope in user_mobile_office_scopes(user)


class IsMobileApiUser(BasePermission):
    def has_permission(self, request, view):
        return can_use_mobile_api(request.user)


class CanReviewMobileIntake(BasePermission):
    def has_permission(self, request, view):
        return can_review_mobile_intake(request.user)
