# apps/accounts/views.py
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.db.models import Q
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import NoReverseMatch, reverse, reverse_lazy
from django.contrib.auth import login, authenticate, logout, update_session_auth_hash
from django.contrib.auth.views import (
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView,
)
from django.contrib import messages
from django.http import Http404
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.core.mail import send_mail
from datetime import date
from urllib.parse import urlencode
from rest_framework import permissions, generics
from rest_framework.response import Response
from rest_framework.views import APIView
from typing import cast

from .forms import (
    PublicUserRegistrationForm,
    StaffUserRegistrationForm,
    BoardMemberRegistrationForm,
    StyledPasswordChangeForm,
    StyledPasswordResetForm,
    StyledSetPasswordForm,
    UserProfileUpdateForm,
)
from .models import OperationalAccessRequest, User
from .professional_linking import link_or_create_professional_record
from .security import (
    audit_security_event,
    clear_staff_mfa_session,
    create_staff_mfa_challenge,
    session_has_valid_mfa,
    staff_mfa_required,
    verify_staff_mfa_code,
)
from .staff_approval import (
    can_registrar_approve_staff_account,
    can_system_admin_approve_staff_account,
    notify_staff_account_approval_request,
)
from apps.dashboard.access import is_medical_board_staff, is_nursing_council_staff
from apps.dashboard.access import (
    can_manage_regulatory_operations,
    is_data_quality_reviewer,
    is_finance_reviewer,
    is_system_admin,
)
from apps.dashboard.regulatory_alignment import (
    build_nursing_regulatory_alignment_context,
    build_nursing_regulatory_alignment_summary_context,
)
from apps.dashboard.staff_ai import build_staff_ai_context
from apps.notifications.services import build_staff_notification_summary
from apps.notifications.models import Notification
from .serializers import UserSerializer


STAFF_LOGIN_ROLES = {'admin', 'registrar', 'reviewer'}
BOARD_LOGIN_ROLES = {'board_member'}
APPLICANT_LOGIN_ROLES = {'viewer', 'nurse_aide', 'nurse', 'chw', 'doctor', 'graduand'}
PUBLIC_SIGNUP_SCOPES = {
    'nursing': {
        'roles': ('graduand', 'nurse', 'nurse_aide'),
        'login_portal': 'nursing',
        'title': 'Nursing Council Account Registration',
        'page_title': 'Nursing Council Account Registration',
        'brand_title': 'Nursing Council',
        'intro': 'Create a Nursing Council applicant account for nurses, nurse aides, and graduands.',
        'help': 'This page is for Nursing Council accounts only.',
        'bullets': [
            'Nursing Council professional and graduand account access',
            'Nursing, nurse aide, and graduand pathway routing',
            'Registrar review before new Nursing Council records become active',
        ],
        'license_note': 'Required for registered nurses who already hold a Nursing Council licence.',
        'registration_note': 'Required for nurse aides. Graduands without a provisional number can leave this blank.',
        'submit_label': 'Create Nursing Council Account',
    },
    'medical': {
        'roles': ('doctor', 'chw'),
        'login_portal': 'medical',
        'title': 'Medical Board Account Registration',
        'page_title': 'Medical Board Account Registration',
        'brand_title': 'Medical Board',
        'intro': 'Create a Medical Board applicant account for doctors and Community Health Workers.',
        'help': 'This page is for Medical Board accounts only.',
        'bullets': [
            'Medical Board practitioner account access',
            'Doctor and Community Health Worker pathway routing',
            'Registrar review before new Medical Board records become active',
        ],
        'license_note': 'Required for doctors and CHWs who already hold a Medical Board licence or practitioner number.',
        'registration_note': 'Use this only if the Medical Board has issued a separate registration reference.',
        'submit_label': 'Create Medical Board Account',
    },
}
LOGIN_PORTAL_CONTEXT = {
    'nursing': {
        'title': 'Nursing Council Portal Sign In',
        'heading': 'Nursing Council Portal',
        'subtitle': 'Online account access for Nursing Council registration, licensing, renewal, and graduand pathways.',
        'audience_note': 'Nursing Council sign in is for nurses, nurse aides, and graduands only.',
        'agency_class': 'auth-nursing',
        'agency_badge': 'Nursing Council workforce access',
        'agency_icon': 'fas fa-user-nurse',
        'create_account_url_name': 'public_nursing_account_register',
        'create_account_label': 'Create Nursing Council account',
        'account_guides': [
            {
                'icon': 'fas fa-user-nurse',
                'title': 'Nursing workforce account',
                'audience': 'For registered nurses, nurse aides, and graduands.',
                'detail': 'Register with your legal name and any Nursing Council licence or registration number you already hold. Graduands without a provisional number may still create an account.',
                'url_name': 'public_nursing_account_register',
                'action_label': 'Create Nursing Council account',
            },
            {
                'icon': 'fas fa-user-shield',
                'title': 'Regulatory staff account',
                'audience': 'For authorised Registrar, reviewer, finance, data-quality, and system-support staff.',
                'detail': 'Request staff access using your work details. Registrar and System Admin approval are required before staff sign-in becomes available.',
                'url_name': 'staff_register',
                'action_label': 'Request staff account',
            },
        ],
    },
    'medical': {
        'title': 'Medical Board Portal Sign In',
        'heading': 'Medical Board Portal',
        'subtitle': 'Online account access for Medical Board practitioner registration, renewal, and CHW pathways.',
        'audience_note': 'Medical Board sign in is for doctors and Community Health Workers only.',
        'agency_class': 'auth-medical',
        'agency_badge': 'Medical Board practitioner access',
        'agency_icon': 'fas fa-user-doctor',
        'create_account_url_name': 'public_medical_board_account_register',
        'create_account_label': 'Create Medical Board account',
        'account_guides': [
            {
                'icon': 'fas fa-user-doctor',
                'title': 'Medical workforce account',
                'audience': 'For doctors, medical specialists, and Community Health Workers.',
                'detail': 'Doctors and specialists use the Medical Board practitioner account. Register with your legal name and any practitioner, licence, or registration number you already hold.',
                'url_name': 'public_medical_board_account_register',
                'action_label': 'Create Medical Board account',
            },
            {
                'icon': 'fas fa-user-shield',
                'title': 'Regulatory staff account',
                'audience': 'For authorised Registrar, reviewer, finance, data-quality, and system-support staff.',
                'detail': 'Request staff access using your work details. Registrar and System Admin approval are required before staff sign-in becomes available.',
                'url_name': 'staff_register',
                'action_label': 'Request staff account',
            },
        ],
    },
    'graduand': {
        'title': 'Nursing Council Graduand Sign In',
        'heading': 'Nursing Council Graduand Portal',
        'subtitle': 'Online account access for Nursing Council graduand and provisional registration pathways.',
        'audience_note': 'Graduand sign in is for Nursing Council graduands and students only.',
        'agency_class': 'auth-nursing',
        'create_account_url_name': 'public_nursing_account_register',
        'create_account_label': 'Create Nursing Council account',
    },
    'student': {
        'title': 'Nursing Council Graduand Sign In',
        'heading': 'Nursing Council Graduand Portal',
        'subtitle': 'Online account access for Nursing Council graduand and provisional registration pathways.',
        'audience_note': 'Graduand sign in is for Nursing Council graduands and students only.',
        'agency_class': 'auth-nursing',
        'create_account_url_name': 'public_nursing_account_register',
        'create_account_label': 'Create Nursing Council account',
    },
    'staff': {
        'title': 'Community Health Worker Sign In',
        'heading': 'Community Health Worker Portal',
        'subtitle': 'Online account access for Community Health Worker registration and renewal pathways.',
        'audience_note': 'Community Health Worker sign in is for CHW applicant accounts only.',
        'agency_class': 'auth-medical',
        'create_account_url_name': 'public_medical_board_account_register',
        'create_account_label': 'Create Medical Board account',
    },
}


def _staff_login_approval_error(user):
    if getattr(user, "role", "") not in User.STAFF_LOGIN_APPROVAL_ROLES:
        return ""
    if user.has_required_staff_login_approvals():
        return ""
    pending = []
    if not getattr(user, "role_approved", False):
        pending.append("Registrar")
    if not getattr(user, "system_admin_approved", False):
        pending.append("System Admin")
    if not pending:
        pending.append("authorised staff")
    if len(pending) == 1:
        pending_text = pending[0]
    else:
        pending_text = " and ".join(pending)
    return f"This staff account is waiting for {pending_text} approval before login."


def _allowed_roles_for_login_mode(auth_mode):
    if auth_mode == 'staff':
        return STAFF_LOGIN_ROLES
    if auth_mode == 'board':
        return BOARD_LOGIN_ROLES
    return APPLICANT_LOGIN_ROLES


def _login_template_for_mode(auth_mode):
    if auth_mode == 'board':
        return 'accounts/board_login.html'
    return 'accounts/login.html'


def _portal_name(portal, auth_mode):
    if auth_mode == 'staff':
        return 'Staff Login'
    if auth_mode == 'board':
        return 'Nursing Council Board Portal'
    return {
        'nursing': 'Nursing Council Portal',
        'medical': 'Medical Board Portal',
        'graduand': 'Graduand Portal',
        'student': 'Graduand Portal',
        'staff': 'Medical Staff Portal',
        'board': 'Nursing Council Board Portal',
    }.get(portal, 'NDOH Workforce Registry')


def _login_context(portal, auth_mode):
    portal_context = LOGIN_PORTAL_CONTEXT.get(portal, {})
    if auth_mode == 'staff':
        portal_context = {
            'title': 'Staff Sign In',
            'heading': 'Staff Sign In',
            'subtitle': 'Secure access for authorised Registrar, Admin, and Reviewer accounts.',
            'audience_note': 'Staff sign in is for Registrar, Admin, and Reviewer accounts only.',
            'agency_class': 'auth-staff',
            'create_account_url_name': 'staff_register',
            'create_account_label': 'Create staff account',
        }
    create_account_url = ''
    create_account_url_name = portal_context.get('create_account_url_name')
    if create_account_url_name:
        try:
            create_account_url = reverse(create_account_url_name)
        except NoReverseMatch:
            create_account_url = ''
    account_guides = []
    for guide in portal_context.get('account_guides', []):
        guide_row = dict(guide)
        try:
            guide_row['url'] = reverse(guide_row['url_name'])
        except (KeyError, NoReverseMatch):
            guide_row['url'] = ''
        account_guides.append(guide_row)
    return {
        'portal': portal,
        'login_mode': auth_mode,
        'portal_name': _portal_name(portal, auth_mode),
        'login_page_title': portal_context.get('title', 'Applicant Portal Sign In'),
        'login_heading': portal_context.get('heading', _portal_name(portal, auth_mode)),
        'login_subtitle': portal_context.get('subtitle', 'Choose the correct agency sign in for your account.'),
        'login_audience_note': portal_context.get('audience_note', 'Applicant sign in is for public applicant accounts.'),
        'auth_agency_class': portal_context.get('agency_class', 'auth-general'),
        'login_agency_badge': portal_context.get('agency_badge', ''),
        'login_agency_icon': portal_context.get('agency_icon', 'fas fa-right-to-bracket'),
        'create_account_url': create_account_url,
        'create_account_label': portal_context.get('create_account_label', ''),
        'login_account_guides': account_guides,
    }


def _role_access_profile(user):
    can_manage = can_manage_regulatory_operations(user)
    role_title = user.get_role_display() if hasattr(user, "get_role_display") else user.role.title()
    domain = "General Registry"
    if is_nursing_council_staff(user):
        domain = "Nursing Council"
    elif is_medical_board_staff(user):
        domain = "Medical Board"
    elif user.role in {"nurse", "nurse_aide", "graduand"}:
        domain = "Nursing Council applicant"
    elif user.role in {"doctor", "chw"}:
        domain = "Medical Board applicant"

    if user.role == "admin":
        if can_manage:
            summary = "System Admin users manage the platform configuration, security, user access, records, imports, reports, and both regulatory workspaces."
            can_access = [
                "Secure Administration Console and platform configuration",
                "Nursing Council and Medical Board dashboards",
                "Records Hub, imports, exports, reports, and data-quality tools",
                "User-access approval and operational oversight",
            ]
            cannot_access = [
                "Routine registrar decisions should still be performed by the responsible regulatory office unless delegated.",
            ]
        else:
            summary = "This Admin account is not fully approved yet, so platform administration remains locked."
            can_access = ["Basic profile access while approval is pending"]
            cannot_access = ["System Admin tools, Secure Administration Console, imports, exports, and registrar operations"]
    elif user.role == "registrar":
        summary = f"{domain} Registrar users manage official regulatory work for their office."
        can_access = [
            f"{domain} dashboard and operational workflows",
            "Approve, reject, and update official application status",
            "Run approved imports, audits, reports, and workflow tools",
            "Review documents, enquiries, and data-quality issues in their office scope",
        ]
        cannot_access = [
            "The other regulatory body's private workspace unless explicitly authorised",
            "System Admin-only platform configuration",
        ]
    elif is_finance_reviewer(user):
        summary = "Finance Officer users have read-only finance oversight access. This role can view Workforce Flow and separate Nursing Council or Medical Board Financial Forecast pages, but cannot edit registry records or run regulatory operations."
        can_access = [
            "Workforce Flow dashboard for high-level planning context",
            "Nursing Council Financial Forecast as a separate finance view",
            "Medical Board Financial Forecast as a separate finance view",
            "Finance exports for the selected office scope only",
        ]
        cannot_access = [
            "Create, update, delete, or upload practitioner, application, document, receipt, or registry records",
            "Nursing Council Operations and Medical Board Operations command buttons",
            "Registrar approvals, imports, workflow configuration, duplicate review actions, and System Admin tools",
            "Full operational access unless the Registrar and System Admin approve an elevated-access request",
        ]
    elif is_data_quality_reviewer(user):
        summary = "Data Quality Officer users help clean records and review duplicate or missing-data issues before official reporting."
        can_access = [
            "Duplicate Review workflow",
            "Records Hub for controlled data-quality review and correction",
            "Staff AI Assistant and data-quality guidance",
        ]
        cannot_access = [
            "Registrar approvals, imports, workflow configuration, and management report generation",
            "Nursing Council Operations and Medical Board Operations command buttons",
            "Secure Administration Console and System Admin tools",
        ]
    elif user.role == "reviewer":
        summary = f"{domain} Reviewer users can inspect assigned information and support registrar review, but they cannot run registrar-only operations."
        can_access = [
            f"{domain} dashboard read/review view",
            "Assigned review queues and safe dashboard statistics",
            "Staff Inbox & Chat and AI Staff Assistant",
        ]
        cannot_access = [
            "Nursing Council Operations or Medical Board Operations command buttons",
            "Imports, workflow configuration, audit commands, report generation, and bulk exports",
            "Approve/reject applications, verify payments, create official licence changes, or access the Secure Administration Console",
            "Full portal CRUD unless the Registrar and System Admin approve a role change or elevated access",
        ]
    elif user.role in {"nurse", "nurse_aide", "graduand"}:
        summary = "This applicant/professional account is for managing only the user's own Nursing Council record."
        can_access = [
            "Own dashboard, applications, receipts, profile, messages, and helpdesk",
            "Public-facing registration forms and guidance",
        ]
        cannot_access = [
            "Staff dashboards, other practitioners' records, imports, exports, and registrar operations",
        ]
    elif user.role in {"doctor", "chw"}:
        summary = "This applicant/professional account is for managing only the user's own Medical Board record."
        can_access = [
            "Own dashboard, applications, receipts, profile, messages, and helpdesk",
            "Public-facing registration forms and guidance",
        ]
        cannot_access = [
            "Staff dashboards, other practitioners' records, imports, exports, and registrar operations",
        ]
    else:
        summary = "Viewer accounts have safe read-only access to profile, help, fee guidance, and enquiries."
        can_access = ["Profile, fee guidance, helpdesk, and enquiries"]
        cannot_access = ["Staff dashboards, Records Hub, imports, exports, approvals, and regulatory operations"]

    return {
        "role_title": role_title,
        "domain": domain,
        "summary": summary,
        "can_access": can_access,
        "cannot_access": cannot_access,
        "can_request_full_access": user.role == "reviewer",
        "can_manage_operations": can_manage,
    }


def _profile_completion(user):
    required_fields = [
        "first_name",
        "last_name",
        "email",
        "phone",
        "profile_image",
        "job_title",
        "workplace_name",
        "work_status",
        "professional_bio",
        "qualification_summary",
        "specialty_area",
        "practice_country",
    ]
    completed = sum(1 for field_name in required_fields if getattr(user, field_name, None))
    total = len(required_fields)
    return {
        "completed": completed,
        "total": total,
        "percent": round((completed / total) * 100) if total else 0,
    }


def _operational_request_office(user):
    if is_finance_reviewer(user):
        return "finance"
    if is_medical_board_staff(user):
        return "medical"
    if is_nursing_council_staff(user):
        return "nursing"
    return "general"


def _operational_request_recipients(office):
    candidates = User.objects.filter(Q(role="admin", is_superuser=True) | Q(role="registrar")).filter(is_active=True)
    if office == "nursing":
        return [
            recipient
            for recipient in candidates
            if recipient.role == "admin" or is_nursing_council_staff(recipient)
        ]
    if office == "medical":
        return [
            recipient
            for recipient in candidates
            if recipient.role == "admin" or is_medical_board_staff(recipient)
        ]
    return list(candidates)


def _can_decide_operational_request(actor, access_request):
    if is_system_admin(actor):
        return True
    if getattr(actor, "role", "") != "registrar" or not can_manage_regulatory_operations(actor):
        return False
    if access_request.requested_office == "nursing":
        return is_nursing_council_staff(actor)
    if access_request.requested_office == "medical":
        return is_medical_board_staff(actor)
    return True


def get_role_based_redirect(user):
    """Helper function to get the appropriate dashboard URL based on user role."""
    if user.role == 'board_member':
        return 'board_nursing_dashboard'
    if user.role in ['admin']:
        return 'admin_dashboard'
    elif user.role == 'registrar':
        return 'registrar_dashboard'
    elif user.role == 'reviewer':
        department = " ".join(
            str(value or "")
            for value in [user.department, user.username, user.first_name, user.last_name]
        ).lower()
        if 'finance' in department:
            return 'financial_forecast_dashboard'
        if 'data quality' in department:
            return 'duplicate_review_workflow'
        if is_medical_board_staff(user):
            return 'medical_board_portal'
        if is_nursing_council_staff(user):
            return 'nursing_council_portal'
        return 'viewer_dashboard'
    elif user.role == 'nurse':
        return 'nurse_dashboard'
    elif user.role == 'chw':
        return 'chw_dashboard'
    elif user.role == 'doctor':
        return 'doctor_dashboard'
    elif user.role in {'graduand', 'student'}:
        return 'student_dashboard'
    elif user.role == 'nurse_aide':
        return 'nurse_aide_dashboard'
    else:
        return 'viewer_dashboard'


def get_portal_based_redirect(portal):
    portal_map = {
        'nursing': ('nurse_dashboard', {'nurse'}),
        'medical': ('doctor_dashboard', {'doctor'}),
        'graduand': ('student_dashboard', {'graduand', 'student'}),
        'student': ('student_dashboard', {'graduand', 'student'}),
        'staff': ('chw_dashboard', {'chw'}),
        'registrar': ('registrar_dashboard', {'registrar'}),
        'admin': ('admin_dashboard', {'admin'}),
        'board': ('board_nursing_dashboard', BOARD_LOGIN_ROLES),
    }
    target = portal_map.get(portal)
    if target:
        return target
    return None


# ====================== LOGIN ======================
def _login_view(request, auth_mode='applicant'):
    portal = request.GET.get('portal', '')
    if auth_mode == 'board':
        portal = portal or 'board'
    next_url = request.GET.get('next', '')
    allowed_roles = _allowed_roles_for_login_mode(auth_mode)
    login_template = _login_template_for_mode(auth_mode)

    user = request.user
    if user.is_authenticated:
        if auth_mode == 'staff' and user.role not in STAFF_LOGIN_ROLES:
            return redirect(get_role_based_redirect(user))
        if auth_mode == 'board' and user.role not in BOARD_LOGIN_ROLES:
            return redirect(get_role_based_redirect(user))
        if auth_mode == 'applicant' and user.role in STAFF_LOGIN_ROLES.union(BOARD_LOGIN_ROLES):
            return redirect(get_role_based_redirect(user))

        portal_redirect = get_portal_based_redirect(portal)
        if portal_redirect:
            target, allowed_roles = portal_redirect
            if not allowed_roles or user.role in allowed_roles:
                return redirect(target)
        return redirect(get_role_based_redirect(user))

    if request.method == 'POST':
        identifier = request.POST.get('username')
        password = request.POST.get('password')
        matched_user = User.objects.filter(
            Q(username=identifier) |
            Q(license_number=identifier) |
            Q(registration_number=identifier)
        ).first()
        user = authenticate(request, username=matched_user.username if matched_user else identifier, password=password)

        if user is not None:
            approval_error = _staff_login_approval_error(user) if auth_mode in {'staff', 'board'} else ""
            if approval_error:
                messages.error(request, approval_error)
                audit_security_event(
                    'LOGIN_FAILED',
                    user=user,
                    username=identifier or '',
                    request=request,
                    details={'reason': 'staff_pending_dual_approval', 'login_mode': auth_mode},
                )
                return render(request, login_template, _login_context(portal, auth_mode))
            if user.role not in allowed_roles:
                messages.error(request, "This account must use the correct login page.")
                audit_security_event(
                    'LOGIN_FAILED',
                    user=user,
                    username=identifier or '',
                    request=request,
                    details={'reason': 'wrong_login_page', 'login_mode': auth_mode},
                )
                return render(request, login_template, _login_context(portal, auth_mode))
            login(request, user)
            audit_security_event('LOGIN_SUCCESS', user=user, request=request, details={'login_mode': auth_mode})

            if staff_mfa_required(user):
                clear_staff_mfa_session(request)
                try:
                    create_staff_mfa_challenge(user, request=request)
                    request.session['staff_mfa_next_url'] = next_url or ''
                    messages.info(request, "A security verification code has been sent to your registered email address.")
                    return redirect('staff_mfa_verify')
                except Exception:
                    logout(request)
                    messages.error(
                        request,
                        "Security verification could not be sent. Please contact the System Admin to confirm your email configuration.",
                    )
                    return redirect('staff_login')

            if next_url and url_has_allowed_host_and_scheme(
                next_url,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):
                return redirect(next_url)

            portal_redirect = get_portal_based_redirect(portal)
            if portal_redirect:
                target, allowed_roles = portal_redirect
                if not allowed_roles or user.role in allowed_roles:
                    return redirect(target)

            return redirect(get_role_based_redirect(user))
        else:
            messages.error(request, "Invalid username or password.")
            audit_security_event(
                'LOGIN_FAILED',
                username=identifier or '',
                request=request,
                details={'reason': 'invalid_credentials', 'login_mode': auth_mode},
            )

    return render(request, login_template, _login_context(portal, auth_mode))


def login_view(request):
    return _login_view(request, auth_mode='applicant')


def staff_login_view(request):
    return _login_view(request, auth_mode='staff')


def applicant_login_view(request):
    return _login_view(request, auth_mode='applicant')


def board_login_view(request):
    return _login_view(request, auth_mode='board')


def board_register_view(request):
    if request.user.is_authenticated:
        if request.user.role == 'board_member':
            return redirect('board_nursing_dashboard')
        messages.error(request, "Only board members should use this registration page. Please sign in using your assigned portal.")
        return redirect(get_role_based_redirect(request.user))

    if request.method == 'POST':
        form = BoardMemberRegistrationForm(request.POST, request.FILES)
        if form.is_valid():
            user = form.save(commit=False)
            form.apply_board_member_group(user)
            user.save()
            notify_staff_account_approval_request(user, BoardMemberRegistrationForm.BOARD_MEMBER_ROLE_CONFIG)
            messages.success(
                request,
                (
                    f"{BoardMemberRegistrationForm.BOARD_MEMBER_ROLE_CONFIG['message']} "
                    f"Board request token: {user.board_registration_token}."
                ),
            )
            return redirect('board_login')
        messages.error(request, "Board account request was not completed. Please correct the highlighted fields below.")
    else:
        form = BoardMemberRegistrationForm()
    return render(request, 'accounts/board_register.html', {
        'form': form,
        'board_member_role_config': BoardMemberRegistrationForm.BOARD_MEMBER_ROLE_CONFIG,
    })


# ====================== LOGOUT ======================
def logout_view(request):
    if request.user.is_authenticated:
        audit_security_event('LOGOUT', user=request.user, request=request)
    clear_staff_mfa_session(request)
    logout(request)
    messages.info(request, "You have been logged out successfully.")
    return redirect('login')


@login_required
def staff_mfa_verify(request):
    user = cast(User, request.user)
    if not staff_mfa_required(user) or session_has_valid_mfa(request, user):
        return redirect(get_role_based_redirect(user))

    if request.method == 'POST':
        success, message = verify_staff_mfa_code(user, request.POST.get('code', ''), request=request)
        if success:
            request.session['staff_mfa_verified_user_id'] = user.pk
            request.session['staff_mfa_verified_at'] = timezone.now().isoformat()
            next_url = request.session.pop('staff_mfa_next_url', '')
            messages.success(request, message)
            if next_url and url_has_allowed_host_and_scheme(
                next_url,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):
                return redirect(next_url)
            return redirect(get_role_based_redirect(user))
        messages.error(request, message)

    return render(request, 'accounts/mfa_verify.html', {
        'system_title': 'PNG Regulatory Bodies The Medical Board & Nursing Council',
        'email_address': user.email,
        'timeout_minutes': max(1, int(getattr(settings, 'STAFF_MFA_TIMEOUT_SECONDS', 600) / 60)),
    })


@login_required
@require_POST
def staff_mfa_resend(request):
    user = cast(User, request.user)
    if not staff_mfa_required(user):
        return redirect(get_role_based_redirect(user))
    try:
        create_staff_mfa_challenge(user, request=request)
        messages.success(request, "A new security verification code has been sent.")
    except Exception:
        messages.error(request, "Security verification could not be resent. Please contact the System Admin.")
    return redirect('staff_mfa_verify')


# ====================== PUBLIC REGISTRATION ======================
def _public_register(request, signup_scope=''):
    if request.user.is_authenticated and request.user.role not in {'admin', 'registrar', 'reviewer'}:
        return redirect(get_role_based_redirect(request.user))

    scope_config = PUBLIC_SIGNUP_SCOPES.get(signup_scope)
    form_kwargs = {}
    if scope_config:
        form_kwargs = {
            'allowed_roles': scope_config['roles'],
            'signup_scope': signup_scope,
        }

    if request.method == 'POST':
        form = PublicUserRegistrationForm(request.POST, request.FILES, **form_kwargs)
        if form.is_valid():
            user = form.save(commit=False)
            user.role = form.cleaned_data.get('role', 'graduand')
            user.applicant_type = form.cleaned_data.get('applicant_type', 'national')
            license_number = form.cleaned_data.get('license_number')
            registration_number = form.cleaned_data.get('registration_number')

            if user.role in {'graduand', 'student', 'nurse_aide'}:
                user.registration_number = registration_number
                user.license_number = None
                if registration_number:
                    user.username = registration_number
            elif user.role in {'nurse', 'chw', 'doctor'}:
                user.license_number = license_number
                user.registration_number = None
                if license_number:
                    user.username = license_number
            else:
                user.license_number = None
                user.registration_number = None

            user.first_name = form.cleaned_data.get('first_name', '')
            user.middle_name = form.cleaned_data.get('middle_name', '')
            user.last_name = form.cleaned_data.get('last_name', '')
            user.cadre_name = form.cleaned_data.get('cadre_name', '')
            user.employee_details = form.cleaned_data.get('employee_details', '')
            user.profile_image = form.cleaned_data.get('profile_image')
            user.passport_photo = form.cleaned_data.get('passport_photo')
            user.id_document_image = form.cleaned_data.get('id_document_image')
            user.save()

            link_outcome = link_or_create_professional_record(user, form.cleaned_data)

            # Send welcome email
            send_mail(
                'Welcome to NDOH Workforce Registry',
                f'Dear {user.get_full_name() or user.username},\n\n'
                f'Your account has been created as a {user.role.title()}.\n'
                f'{link_outcome.message or "You can now log in and complete your profile."}\n\n'
                f'Use the portal dashboard to continue the correct registration or renewal pathway.',
                'no-reply@ndoh.gov.pg',
                [user.email],
                fail_silently=True,
            )

            if link_outcome.status == 'linked':
                messages.success(request, "Account created and linked to your existing professional record. Please log in.")
            elif link_outcome.professional:
                messages.success(request, "Account created. Your professional record is waiting for registrar review and approval.")
            else:
                messages.warning(request, link_outcome.message or "Account created. Registrar review is required before your professional record can be linked.")

            login_url = reverse('login')
            if scope_config:
                login_query = {
                    'portal': scope_config['login_portal'],
                }
                if link_outcome.next_url_name:
                    try:
                        login_query['next'] = reverse(link_outcome.next_url_name)
                    except NoReverseMatch:
                        pass
                login_url = f"{login_url}?{urlencode(login_query)}"
            elif link_outcome.next_url_name:
                try:
                    login_url = f"{login_url}?next={reverse(link_outcome.next_url_name)}"
                except NoReverseMatch:
                    pass
            return redirect(login_url)
        messages.error(request, "Registration was not completed. Please correct the highlighted fields below.")

    else:
        form = PublicUserRegistrationForm(**form_kwargs)

    context = {
        'form': form,
        'signup_scope': signup_scope,
        'signup_title': scope_config['title'] if scope_config else 'Register',
        'signup_page_title': scope_config['page_title'] if scope_config else 'Applicant Account Registration',
        'signup_brand_title': scope_config['brand_title'] if scope_config else 'PNG Regulatory Bodies The Medical Board & Nursing Council',
        'signup_intro': scope_config['intro'] if scope_config else 'Create your account first. The portal will link it to an existing professional record or start the correct registrar-review pathway.',
        'signup_help': scope_config['help'] if scope_config else 'Register with your legal name and professional number if you already have one. New graduands can create an account first and complete the graduand forms after login.',
        'signup_bullets': scope_config['bullets'] if scope_config else [
            'Matching by name, professional number, and cadre',
            'Registration, renewal, and graduand pathway routing',
            'Registrar review before new records become active',
        ],
        'license_number_note': scope_config['license_note'] if scope_config else 'Required for nurses, doctors, and CHWs who already hold a professional licence.',
        'registration_number_note': scope_config['registration_note'] if scope_config else 'Required for nurse aides. New graduands without a provisional number can leave this blank.',
        'signup_submit_label': scope_config['submit_label'] if scope_config else 'Register',
        'signup_login_url': f"{reverse('login')}?{urlencode({'portal': scope_config['login_portal']})}" if scope_config else reverse('login'),
    }

    return render(request, 'accounts/public_register.html', context)


def public_register(request):
    return _public_register(request)


def public_nursing_account_register(request):
    return _public_register(request, signup_scope='nursing')


def public_medical_board_account_register(request):
    return _public_register(request, signup_scope='medical')


def staff_register(request):
    if request.method == 'POST':
        form = StaffUserRegistrationForm(request.POST, request.FILES)
        if form.is_valid():
            user = form.save(commit=False)
            form.apply_staff_group(user)
            user.save()
            notify_staff_account_approval_request(user, form.selected_group_config())

            messages.success(request, form.selected_group_config()['message'])
            return redirect('staff_login')
        messages.error(request, "Staff registration was not completed. Please correct the highlighted fields below.")
    else:
        form = StaffUserRegistrationForm()
    return render(request, 'accounts/staff_register.html', {
        'form': form,
        'staff_access_guide': StaffUserRegistrationForm.staff_access_guide(),
        'non_staff_access_groups': StaffUserRegistrationForm.NON_STAFF_ACCESS_GROUPS,
    })


@login_required
@require_POST
def decide_staff_account_approval(request, user_id, approval_type):
    if approval_type not in {"registrar", "system-admin"}:
        raise Http404("Staff account approval action not found")
    target_user = get_object_or_404(User, pk=user_id, role__in=User.STAFF_LOGIN_APPROVAL_ROLES)

    if approval_type == "registrar":
        if not can_registrar_approve_staff_account(request.user, target_user):
            raise Http404("Staff account approval action not found")
        target_user.role_approved = True
        target_user.approved_by = request.user
        target_user.approved_at = timezone.now()
        approval_label = "Registrar approval"
    else:
        if not can_system_admin_approve_staff_account(request.user, target_user):
            raise Http404("Staff account approval action not found")
        target_user.system_admin_approved = True
        target_user.system_admin_approved_by = request.user
        target_user.system_admin_approved_at = timezone.now()
        approval_label = "System Admin approval"

    target_user.is_active = True
    target_user.save()
    Notification.objects.filter(
        user=request.user,
        subject=f"Staff account approval required: {target_user.username}",
        read_at__isnull=True,
    ).update(read_at=timezone.now())

    if target_user.has_required_staff_login_approvals():
        Notification.objects.create(
            user=target_user,
            subject="Staff account approved",
            message=(
                "Your staff account has Registrar and System Admin approval. "
                "You can now sign in through the staff login page."
            ),
        )
        messages.success(request, f"{target_user.username} now has both approvals and can log in.")
    else:
        Notification.objects.create(
            user=target_user,
            subject=f"{approval_label} recorded",
            message=(
                f"{approval_label} was recorded for your staff account. "
                "The account still needs both Registrar and System Admin approval before login opens."
            ),
        )
        messages.success(request, f"{approval_label} recorded for {target_user.username}.")
    return redirect("staff_communications")


class UserPasswordResetView(PasswordResetView):
    form_class = StyledPasswordResetForm
    email_template_name = 'accounts/password_reset_email.txt'
    subject_template_name = 'accounts/password_reset_subject.txt'
    success_url = reverse_lazy('password_reset_done')
    template_name = 'accounts/password_reset_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['system_title'] = 'PNG Regulatory Bodies The Medical Board & Nursing Council'
        return context


class UserPasswordResetDoneView(PasswordResetDoneView):
    template_name = 'accounts/password_reset_done.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['system_title'] = 'PNG Regulatory Bodies The Medical Board & Nursing Council'
        return context


class UserPasswordResetConfirmView(PasswordResetConfirmView):
    form_class = StyledSetPasswordForm
    success_url = reverse_lazy('password_reset_complete')
    template_name = 'accounts/password_reset_confirm.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['system_title'] = 'PNG Regulatory Bodies The Medical Board & Nursing Council'
        return context


class UserPasswordResetCompleteView(PasswordResetCompleteView):
    template_name = 'accounts/password_reset_complete.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['system_title'] = 'PNG Regulatory Bodies The Medical Board & Nursing Council'
        return context


# ====================== PROFILE ======================
@login_required
def user_profile(request):
    user = cast(User, request.user)
    active_profile_tab = request.GET.get("tab", "professional")
    if request.method == 'POST':
        profile_action = request.POST.get("profile_action", "profile")
        if profile_action == "password":
            form = UserProfileUpdateForm(instance=user)
            password_form = StyledPasswordChangeForm(user, request.POST)
            active_profile_tab = "security"
            if password_form.is_valid():
                password_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, "Password updated successfully.")
                return redirect('user_profile')
            messages.error(request, "Please correct the password form errors below.")
        else:
            form = UserProfileUpdateForm(request.POST, request.FILES, instance=user)
            password_form = StyledPasswordChangeForm(user)
            active_profile_tab = request.POST.get("active_profile_tab", "professional")
            if form.is_valid():
                form.save()
                messages.success(request, "Profile updated successfully.")
                return redirect('user_profile')
            messages.error(request, "Please correct the profile form errors below.")
    else:
        form = UserProfileUpdateForm(instance=user)
        password_form = StyledPasswordChangeForm(user)

    nursing_regulatory_alignment = None
    if _can_view_nursing_regulatory_alignment(user):
        nursing_regulatory_alignment = build_nursing_regulatory_alignment_summary_context()
    staff_ai_context = (
        build_staff_ai_context(user, detailed=False)
        if user.role in {"admin", "registrar"} or (user.role == "reviewer" and not is_finance_reviewer(user))
        else None
    )

    return render(request, 'accounts/profile.html', {
        'user': request.user,
        'form': form,
        'staff_summary': build_staff_notification_summary(user),
        'nursing_regulatory_alignment': nursing_regulatory_alignment,
        'staff_ai_context': staff_ai_context,
        'show_settings_modal': request.GET.get('settings') == '1' or request.method == 'POST',
        'profile_completion': _profile_completion(user),
        'profile_access': _role_access_profile(user),
        'profile_form': form,
        'password_form': password_form,
        'active_profile_tab': active_profile_tab,
    })


@login_required
@require_POST
def request_full_access(request):
    user = cast(User, request.user)
    if user.role != "reviewer":
        messages.info(request, "Your current role does not require a reviewer access upgrade request.")
        return redirect("user_profile")
    if user.operations_approved:
        messages.info(request, "This account already has approved operational access.")
        return redirect("user_profile")

    office_key = _operational_request_office(user)
    office_label = dict(OperationalAccessRequest.OFFICE_CHOICES).get(office_key, "General Registry")
    access_request, created_request = OperationalAccessRequest.objects.get_or_create(
        user=user,
        status="pending",
        defaults={
            "requested_office": office_key,
            "reason": request.POST.get("reason", "").strip()
            or "Reviewer requested full operational access from the Profile Overview page.",
        },
    )
    if not created_request and access_request.requested_office != office_key:
        access_request.requested_office = office_key
        access_request.save(update_fields=["requested_office"])

    subject = f"Full portal access request from {user.get_full_name() or user.username}"
    message = (
        f"{user.get_full_name() or user.username} ({user.username}) requested elevated access for {office_label}. "
        "Open Staff Inbox & Chat to approve or reject the operational access request. "
        "Approve only if this user should be allowed to run restricted operational functions."
    )
    recipients = _operational_request_recipients(office_key)

    created = 0
    for recipient in recipients:
        exists = Notification.objects.filter(user=recipient, subject=subject, message=message).exists()
        if exists:
            continue
        Notification.objects.create(user=recipient, subject=subject, message=message)
        created += 1

    if created_request:
        messages.success(request, "Your full-access request was sent to the Registrar/System Admin for review.")
    elif created:
        messages.info(request, "Your existing full-access request was re-sent to the Registrar/System Admin for review.")
    else:
        messages.info(request, "A full-access request is already waiting for Registrar/System Admin review.")
    return redirect("user_profile")


@login_required
@require_POST
def decide_operational_access_request(request, pk, decision):
    if decision not in {"approve", "reject"}:
        raise Http404("Access decision not found")
    access_request = get_object_or_404(OperationalAccessRequest.objects.select_related("user"), pk=pk)
    if not _can_decide_operational_request(request.user, access_request):
        raise Http404("Access request not found")
    if access_request.status != "pending":
        messages.info(request, "This access request has already been decided.")
        return redirect("staff_communications")

    target_user = access_request.user
    access_request.status = "approved" if decision == "approve" else "rejected"
    access_request.decided_by = request.user
    access_request.decided_at = timezone.now()
    access_request.decision_note = request.POST.get("decision_note", "").strip()
    access_request.save(update_fields=["status", "decided_by", "decided_at", "decision_note"])

    if decision == "approve":
        target_user.operations_approved = True
        target_user.operations_approved_by = request.user
        target_user.operations_approved_at = access_request.decided_at
        target_user.is_active = True
        target_user.is_staff = True
        target_user.save(update_fields=["operations_approved", "operations_approved_by", "operations_approved_at", "is_active", "is_staff"])
        Notification.objects.create(
            user=target_user,
            subject="Operational access approved",
            message=(
                f"Your restricted operational access request was approved by "
                f"{request.user.get_full_name() or request.user.username}. Please log out and log back in if locked menu items do not refresh immediately."
            ),
        )
        messages.success(request, f"Operational access approved for {target_user.username}.")
    else:
        target_user.operations_approved = False
        target_user.operations_approved_by = None
        target_user.operations_approved_at = None
        target_user.save(update_fields=["operations_approved", "operations_approved_by", "operations_approved_at"])
        Notification.objects.create(
            user=target_user,
            subject="Operational access request rejected",
            message=(
                f"Your restricted operational access request was rejected by "
                f"{request.user.get_full_name() or request.user.username}."
            ),
        )
        messages.success(request, f"Operational access request rejected for {target_user.username}.")

    return redirect("staff_communications")


@login_required
def nursing_regulatory_alignment_view(request):
    user = cast(User, request.user)
    if not _can_view_nursing_regulatory_alignment(user):
        messages.error(request, "This live regulatory statistics page is only available to System Admin and Nursing Council registrar users.")
        return redirect("user_profile")

    return render(request, "accounts/nursing_regulatory_alignment_page.html", {
        "alignment": build_nursing_regulatory_alignment_context(),
    })


def _can_view_nursing_regulatory_alignment(user):
    return is_system_admin(user) or (
        getattr(user, "role", "") == "registrar"
        and is_nursing_council_staff(user)
    )


# ====================== DRF API Views ======================
class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [permissions.AllowAny]


class UserProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return cast(User, self.request.user)


class LogoutAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        # Blacklist current token (optional with SimpleJWT)
        return Response({"message": "Successfully logged out"})
