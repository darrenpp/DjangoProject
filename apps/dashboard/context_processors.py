from .access import (
    can_manage_regulatory_operations,
    is_data_quality_reviewer,
    is_finance_reviewer,
    is_medical_board_staff,
    is_medical_board_user,
    is_nursing_council_staff,
    is_nursing_council_user,
    is_staff_dashboard_user,
)
from apps.documents.access import can_access_document_repository


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


def portal_access(request):
    user = getattr(request, 'user', None)
    return {
        'can_access_medical_board': is_medical_board_user(user),
        'can_access_nursing_council': is_nursing_council_user(user),
        'can_access_medical_board_portal': is_medical_board_staff(user),
        'can_access_nursing_council_portal': is_nursing_council_staff(user),
        'can_access_staff_dashboards': is_staff_dashboard_user(user),
        'can_manage_regulatory_operations': can_manage_regulatory_operations(user),
        'is_finance_reviewer': is_finance_reviewer(user),
        'is_data_quality_reviewer': is_data_quality_reviewer(user),
        'can_access_document_repository': can_access_document_repository(user),
        'official_ndoh_contact': OFFICIAL_NDOH_CONTACT,
        'official_nursing_council_references': OFFICIAL_NURSING_COUNCIL_REFERENCES,
    }
