from apps.dashboard.access import (
    can_manage_regulatory_operations,
    is_data_quality_reviewer,
    is_finance_reviewer,
    is_medical_board_staff,
    is_nursing_council_staff,
    is_system_admin,
)


def _profile_text(user):
    values = [
        getattr(user, "department", ""),
        getattr(user, "username", ""),
        getattr(user, "first_name", ""),
        getattr(user, "last_name", ""),
        getattr(user, "email", ""),
    ]
    return " ".join(str(value or "") for value in values).lower()


def can_access_document_repository(user):
    if not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        return False
    if is_finance_reviewer(user):
        return False
    return bool(
        is_system_admin(user)
        or can_manage_regulatory_operations(user)
        or is_data_quality_reviewer(user)
    )


def can_manage_document_repository(user):
    if not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        return False
    if is_finance_reviewer(user):
        return False
    return bool(is_system_admin(user) or can_manage_regulatory_operations(user))


def primary_document_scope_for_user(user):
    if is_system_admin(user):
        return ""
    if is_medical_board_staff(user):
        return "medical"
    if is_nursing_council_staff(user):
        return "nursing"
    if is_data_quality_reviewer(user):
        profile = _profile_text(user)
        if "medical" in profile or "doctor" in profile or "chw" in profile:
            return "medical"
        if "nursing" in profile or "nurse" in profile:
            return "nursing"
    return "general"


def visible_document_scopes_for_user(user):
    if is_system_admin(user):
        return ["general", "nursing", "medical"]
    scope = primary_document_scope_for_user(user)
    if scope in {"nursing", "medical"}:
        return ["general", scope]
    return ["general"]


def _policy_queryset_for(document):
    from .models import DocumentAccessPolicy

    folder_ids = []
    folder = document.folder
    while folder:
        folder_ids.append(folder.id)
        folder = folder.parent

    return DocumentAccessPolicy.objects.filter(document=document) | DocumentAccessPolicy.objects.filter(folder_id__in=folder_ids)


def _policy_allows(user, document, permission_field):
    policies = _policy_queryset_for(document)
    if not policies.exists():
        return True

    role = getattr(user, "role", "")
    for policy in policies:
        applies_to_user = policy.user_id and policy.user_id == getattr(user, "id", None)
        applies_to_role = policy.role and policy.role == role
        if (applies_to_user or applies_to_role) and getattr(policy, permission_field, False):
            return True
    return False


def can_view_document(user, document):
    return (
        can_access_document_repository(user)
        and document.office_scope in visible_document_scopes_for_user(user)
        and _policy_allows(user, document, "can_view")
    )


def can_download_document(user, document):
    return can_view_document(user, document) and _policy_allows(user, document, "can_download")


def can_edit_document(user, document):
    if not can_view_document(user, document):
        return False
    return can_manage_document_repository(user) or _policy_allows(user, document, "can_edit_metadata")


def can_upload_to_folder(user, folder=None, office_scope="general"):
    if not can_access_document_repository(user):
        return False
    scope = folder.office_scope if folder else office_scope
    if scope not in visible_document_scopes_for_user(user):
        return False
    if can_manage_document_repository(user):
        return True
    if not folder:
        return False

    policies = folder.access_policies.all()
    if not policies.exists():
        return False
    role = getattr(user, "role", "")
    return any(
        (policy.user_id == getattr(user, "id", None) or policy.role == role) and policy.can_upload
        for policy in policies
    )
