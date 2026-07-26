from django.db.models import Q

from apps.dashboard.access import (
    can_access_staff_domain,
    is_medical_board_staff,
    is_nursing_council_staff,
    is_staff_dashboard_user,
    is_system_admin,
)

from .models import ComplaintCase, DisciplinaryCase, RegulatoryDecisionRecord


OPEN_CASE_STATUSES = ["new", "triage", "assigned", "investigating", "awaiting_response", "escalated"]


def staff_complaint_scope(user):
    if is_system_admin(user):
        return ""
    if is_medical_board_staff(user) and not is_nursing_council_staff(user):
        return "medical"
    if is_nursing_council_staff(user):
        return "nursing"
    return ""


def can_access_complaints_workspace(user):
    return getattr(user, "is_authenticated", False) and is_staff_dashboard_user(user)


def can_access_complaint_case(user, case):
    if not getattr(user, "is_authenticated", False):
        return False
    if is_system_admin(user):
        return True
    if case.created_by_id == user.id or case.complainant_user_id == user.id:
        return True
    if not is_staff_dashboard_user(user):
        return False
    if case.office_scope == "general" and getattr(user, "role", "") in {"registrar", "reviewer"}:
        return True
    return can_access_staff_domain(user, case.office_scope)


def can_access_disciplinary_case(user, case):
    if not getattr(user, "is_authenticated", False):
        return False
    if is_system_admin(user):
        return True
    if case.created_by_id == user.id:
        return True
    if not is_staff_dashboard_user(user):
        return False
    if case.office_scope == "general" and getattr(user, "role", "") in {"registrar", "reviewer"}:
        return True
    return can_access_staff_domain(user, case.office_scope)


def can_access_decision_record(user, decision):
    if not getattr(user, "is_authenticated", False):
        return False
    if is_system_admin(user):
        return True
    if decision.created_by_id == user.id or decision.decided_by_id == user.id:
        return True
    if not is_staff_dashboard_user(user):
        return False
    if decision.office_scope == "general" and getattr(user, "role", "") in {"registrar", "reviewer"}:
        return True
    return can_access_staff_domain(user, decision.office_scope)


def scoped_complaint_cases(user):
    queryset = ComplaintCase.objects.select_related(
        "assigned_to",
        "created_by",
        "complainant_user",
        "source_enquiry",
    ).prefetch_related("events")
    if is_system_admin(user):
        return queryset
    if is_staff_dashboard_user(user):
        scope = staff_complaint_scope(user)
        if scope:
            return queryset.filter(office_scope__in=["general", scope])
        return queryset.filter(office_scope="general")
    if getattr(user, "is_authenticated", False):
        return queryset.filter(Q(created_by=user) | Q(complainant_user=user))
    return queryset.none()


def scoped_disciplinary_cases(user):
    queryset = DisciplinaryCase.objects.select_related(
        "assigned_to",
        "created_by",
        "source_complaint",
        "decision_record",
    ).prefetch_related("events")
    if is_system_admin(user):
        return queryset
    if is_staff_dashboard_user(user):
        scope = staff_complaint_scope(user)
        if scope:
            return queryset.filter(office_scope__in=["general", scope])
        return queryset.filter(office_scope="general")
    return queryset.none()


def scoped_decision_records(user):
    queryset = RegulatoryDecisionRecord.objects.select_related(
        "created_by",
        "decided_by",
        "related_complaint",
    )
    if is_system_admin(user):
        return queryset
    if is_staff_dashboard_user(user):
        scope = staff_complaint_scope(user)
        if scope:
            return queryset.filter(office_scope__in=["general", scope])
        return queryset.filter(office_scope="general")
    return queryset.none()


def open_complaint_cases(user):
    return scoped_complaint_cases(user).filter(status__in=OPEN_CASE_STATUSES)


def open_disciplinary_cases(user):
    return scoped_disciplinary_cases(user).exclude(status__in=["closed", "withdrawn"])


def complaint_summary_for_user(user):
    open_qs = open_complaint_cases(user)
    return {
        "open_case_count": open_qs.count(),
        "critical_case_count": open_qs.filter(priority="critical").count(),
        "high_risk_case_count": open_qs.filter(risk_level__in=["high", "critical"]).count(),
        "unassigned_case_count": open_qs.filter(assigned_to__isnull=True).count(),
        "recent_cases": list(open_qs.order_by("-updated_at")[:5]),
    }


def discipline_summary_for_user(user):
    open_qs = open_disciplinary_cases(user)
    return {
        "open_discipline_count": open_qs.count(),
        "high_severity_count": open_qs.filter(severity__in=["high", "critical"]).count(),
        "hearing_count": open_qs.filter(stage="hearing").count(),
        "decision_stage_count": open_qs.filter(stage="decision").count(),
        "recent_disciplinary_cases": list(open_qs.order_by("-updated_at")[:5]),
    }
