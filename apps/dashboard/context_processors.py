from .access import (
    can_manage_regulatory_operations,
    can_access_nursing_board_portal,
    is_system_admin,
    is_data_quality_reviewer,
    is_finance_reviewer,
    is_medical_board_staff,
    is_medical_board_user,
    is_nursing_council_board_member,
    is_nursing_council_staff,
    is_nursing_council_user,
    is_staff_dashboard_user,
)
from apps.documents.access import can_access_document_repository
from .platform_standards import PLATFORM_STANDARD_BADGES, PLATFORM_STANDARDS_SUMMARY
from .platform_resilience import current_platform_status


OFFICIAL_NDOH_CONTACT = {
    'office_name': 'Ministry of Health / National Department of Health',
    'address_line_1': 'AOPI Building Centre, Waigani Drive',
    'address_line_2': 'Tower One',
    'postal_address': 'P.O. Box 807, Waigani 121',
    'city': 'Port Moresby',
    'province': 'National Capital District',
    'phone': '(+675) 301 3634',
    'phone_uri': '+6753013634',
    'email': 'health_ministry@health.gov.pg',
    'website': 'https://www.health.gov.pg/index.html',
    'nursing_council_url': 'https://www.health.gov.pg/subindex.php?health_ministry=7',
}

OFFICIAL_NURSING_COUNCIL_REFERENCES = [
    'Registration forms and approved fee references',
    'Graduate nurse and midwifery pathway checklists',
    'Overseas, temporary, and provisional-to-full registration guidance',
    'Code of Ethics and Code of Professional Conduct',
    'Employer responsibility and workforce-planning policy',
    'Education standards, competencies, accreditation, and public register references',
]


def _dashboard_platform_title(request, user):
    path = getattr(request, 'path', '') or ''
    role = getattr(user, 'role', '')
    account_name = getattr(user, 'account_display_name', '') or getattr(user, 'username', '') or 'User'

    if role in {'doctor', 'chw'} or '/medical-board/' in path:
        return f'Welcome, {account_name} To Your Medical Board Online Platform Dashboard'
    if role == 'board_member' or '/board/nursing/' in path or '/nursing-council/board/' in path:
        return f'Welcome, {account_name} To Your PNG Nursing Council Board Portal'
    if role in {'nurse', 'nurse_aide', 'graduand', 'student'} or '/nursing-council/' in path:
        return f'Welcome, {account_name} To Your PNG Nursing Council Online Platform Dashboard'
    if is_medical_board_user(user) and not is_nursing_council_user(user):
        return f'Welcome, {account_name} To Your Medical Board Online Platform Dashboard'
    if is_nursing_council_user(user) and not is_medical_board_user(user):
        return f'Welcome, {account_name} To Your PNG Nursing Council Online Platform Dashboard'
    return f'Welcome, {account_name} To Your PNG Regulatory Bodies Online Platform Dashboard'


def _dashboard_platform_header_variant(title):
    if 'PNG Nursing Council Online Platform Dashboard' in title:
        return 'nursing'
    if 'PNG Nursing Council Board Portal' in title:
        return 'nursing'
    if 'Medical Board Online Platform Dashboard' in title:
        return 'medical'
    return 'regulatory'


def portal_access(request):
    user = getattr(request, 'user', None)
    path = getattr(request, 'path', '') or ''
    is_board_portal_context = path.startswith('/board/nursing/') or path.startswith('/dashboard/nursing-council/board/')
    is_board_member = is_nursing_council_board_member(user)
    has_board_access = can_access_nursing_board_portal(user)
    dashboard_platform_title = _dashboard_platform_title(request, user)
    platform_resilience_status = current_platform_status()
    can_access_nursing_regulatory_alignment = (
        is_system_admin(user)
        or (getattr(user, 'role', '') == 'registrar' and is_nursing_council_staff(user))
    )
    return {
        'can_access_medical_board': is_medical_board_user(user),
        'can_access_nursing_council': is_nursing_council_user(user),
        'can_access_medical_board_portal': is_medical_board_staff(user),
        'can_access_nursing_council_portal': is_nursing_council_staff(user),
        'can_access_nursing_board_portal': has_board_access,
        'can_access_staff_dashboards': is_staff_dashboard_user(user),
        'is_board_portal_context': is_board_portal_context,
        'show_board_ai_assistant': has_board_access and (is_board_portal_context or is_board_member),
        'show_staff_ai_assistant': is_staff_dashboard_user(user) and not is_board_portal_context,
        'can_manage_regulatory_operations': can_manage_regulatory_operations(user),
        'is_system_admin': is_system_admin(user),
        'is_nursing_board_member': is_board_member,
        'can_access_nursing_regulatory_alignment': can_access_nursing_regulatory_alignment,
        'is_finance_reviewer': is_finance_reviewer(user),
        'is_data_quality_reviewer': is_data_quality_reviewer(user),
        'can_access_document_repository': can_access_document_repository(user),
        'official_ndoh_contact': OFFICIAL_NDOH_CONTACT,
        'official_nursing_council_references': OFFICIAL_NURSING_COUNCIL_REFERENCES,
        'platform_standard_badges': PLATFORM_STANDARD_BADGES,
        'platform_standards_summary': PLATFORM_STANDARDS_SUMMARY,
        'dashboard_platform_title': dashboard_platform_title,
        'dashboard_platform_header_variant': _dashboard_platform_header_variant(dashboard_platform_title),
        'dashboard_account_display_name': getattr(user, 'account_display_name', '') or getattr(user, 'username', '') or 'User',
        'platform_resilience_status': platform_resilience_status,
    }
