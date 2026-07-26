def _profile_text(user):
    values = [
        getattr(user, 'department', ''),
        getattr(user, 'job_title', ''),
        getattr(user, 'cadre_name', ''),
        getattr(user, 'employee_details', ''),
        getattr(user, 'username', ''),
        getattr(user, 'first_name', ''),
        getattr(user, 'last_name', ''),
        getattr(user, 'email', ''),
    ]
    return ' '.join(str(value or '') for value in values).lower()


def is_system_admin(user):
    return (
        getattr(user, 'is_authenticated', False)
        and getattr(user, 'is_active', False)
        and getattr(user, 'role', '') == 'admin'
        and getattr(user, 'is_superuser', False)
    )


def is_finance_reviewer(user):
    return (
        getattr(user, 'is_authenticated', False)
        and getattr(user, 'role', '') == 'reviewer'
        and 'finance' in _profile_text(user)
    )


def is_data_quality_reviewer(user):
    return (
        getattr(user, 'is_authenticated', False)
        and getattr(user, 'role', '') == 'reviewer'
        and 'data quality' in _profile_text(user)
    )


def can_manage_regulatory_operations(user):
    if not getattr(user, 'is_authenticated', False) or not getattr(user, 'is_active', False):
        return False
    if is_system_admin(user):
        return True
    has_staff_login_approvals = getattr(user, 'has_required_staff_login_approvals', lambda: True)()
    if not has_staff_login_approvals:
        return False
    if getattr(user, 'role', '') == 'reviewer' and getattr(user, 'operations_approved', False):
        return True
    return getattr(user, 'role', '') == 'registrar' and getattr(user, 'role_approved', False)


MEDICAL_BOARD_PROFILE_TOKENS = (
    'medical board',
    'medical',
    'doctor',
    'chw',
    'community health',
)
MEDICAL_BOARD_FORM_CODES = {
    'MD1',
    'MD2',
    'CHW1',
    'CHWP',
    'CHWF',
    'MBSP',
    'MBRN',
    'MBAC',
    'MBPF',
    'MBTC',
}
MEDICAL_BOARD_PROFESSIONAL_MODELS = {'medicaldoctor', 'communityhealthworker'}
NURSING_COUNCIL_PROFESSIONAL_MODELS = {
    'nursingprofessional',
    'midwife',
    'nurseaide',
    'healthstudent',
}


def _profile_matches_medical_board(user):
    profile = _profile_text(user)
    return any(token in profile for token in MEDICAL_BOARD_PROFILE_TOKENS)


def _model_name(value):
    if value is None:
        return ''
    if isinstance(value, str):
        return ''.join(character for character in value.lower() if character.isalnum())
    return value.__class__.__name__.lower()


def is_medical_board_staff(user):
    if not getattr(user, 'is_authenticated', False):
        return False
    if is_finance_reviewer(user):
        return False
    if getattr(user, 'role', '') == 'admin':
        return True
    if getattr(user, 'role', '') not in {'registrar', 'reviewer'}:
        return False
    return _profile_matches_medical_board(user)


def is_nursing_council_staff(user):
    if not getattr(user, 'is_authenticated', False):
        return False
    if is_finance_reviewer(user):
        return False
    if getattr(user, 'role', '') == 'admin':
        return True
    role = getattr(user, 'role', '')
    if role not in {'registrar', 'reviewer'}:
        return False
    if role == 'reviewer':
        profile = _profile_text(user)
        return 'nursing' in profile or 'nurse' in profile
    return not _profile_matches_medical_board(user)


def is_nursing_council_board_member(user):
    return (
        getattr(user, 'is_authenticated', False)
        and getattr(user, 'is_active', False)
        and getattr(user, 'role', '') == 'board_member'
        and bool(getattr(user, 'has_required_staff_login_approvals', lambda: True)())
    )


def can_access_nursing_board_portal(user):
    return is_system_admin(user) or is_nursing_council_board_member(user)


def is_medical_board_user(user):
    if not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'role', '') == 'admin':
        return True
    if getattr(user, 'role', '') in {'doctor', 'chw'}:
        return True
    return is_medical_board_staff(user)


def is_nursing_council_user(user):
    if not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'role', '') == 'admin':
        return True
    if getattr(user, 'role', '') in {'nurse', 'nurse_aide', 'graduand'}:
        return True
    return is_nursing_council_staff(user)


def is_medical_board_form_code(form_code):
    return (form_code or '').upper() in MEDICAL_BOARD_FORM_CODES


def professional_domain(value):
    model_name = _model_name(value)
    if model_name in MEDICAL_BOARD_PROFESSIONAL_MODELS:
        return 'medical'
    if model_name in NURSING_COUNCIL_PROFESSIONAL_MODELS:
        return 'nursing'
    return ''


def application_domain(application):
    form_code = getattr(application, 'form_code', '')
    if is_medical_board_form_code(form_code):
        return 'medical'

    professional = getattr(application, 'professional', None)
    domain = professional_domain(professional)
    if domain:
        return domain

    if form_code:
        return 'nursing'
    return ''


def imported_record_domain(record):
    target_model = record if isinstance(record, str) else getattr(record, 'target_model', '')
    return professional_domain(target_model)


def user_matches_professional_record(user, professional):
    if not getattr(user, 'is_authenticated', False) or professional is None:
        return False

    identifiers = {
        str(value).strip().lower()
        for value in [
            getattr(user, 'registration_number', None),
            getattr(user, 'license_number', None),
            getattr(user, 'username', None),
        ]
        if value
    }
    professional_identifiers = {
        str(value).strip().lower()
        for value in [
            getattr(professional, 'registration_no', None),
            getattr(professional, 'registration_number', None),
        ]
        if value
    }
    if identifiers & professional_identifiers:
        return True

    user_email = str(getattr(user, 'email', '') or '').strip().lower()
    professional_email = str(getattr(professional, 'email', '') or '').strip().lower()
    return bool(user_email and professional_email and user_email == professional_email)


def can_access_staff_domain(user, domain):
    if not getattr(user, 'is_authenticated', False) or not domain:
        return False
    if getattr(user, 'role', '') == 'admin':
        return True
    department = _profile_text(user)
    if getattr(user, 'role', '') == 'reviewer' and 'finance' in department:
        return False
    if getattr(user, 'role', '') == 'reviewer' and 'data quality' in department:
        return True
    if domain == 'medical':
        return is_medical_board_staff(user)
    if domain == 'nursing':
        return is_nursing_council_staff(user)
    return False


def can_access_professional_record(user, professional):
    domain = professional_domain(professional)
    if not domain:
        return False
    if can_access_staff_domain(user, domain):
        return True

    if domain == 'medical' and getattr(user, 'role', '') not in {'doctor', 'chw'}:
        return False
    if domain == 'nursing' and getattr(user, 'role', '') not in {'nurse', 'nurse_aide', 'graduand', 'student'}:
        return False
    return user_matches_professional_record(user, professional)


def can_access_application_record(user, application):
    domain = application_domain(application)
    if not domain:
        return False
    if can_access_staff_domain(user, domain):
        return True

    professional = getattr(application, 'professional', None)
    return can_access_professional_record(user, professional) if professional else False


def is_staff_dashboard_user(user):
    return getattr(user, 'is_authenticated', False) and getattr(user, 'role', '') in {'admin', 'registrar', 'reviewer'}
