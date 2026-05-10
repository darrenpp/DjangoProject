# apps/accounts/views.py
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.db.models import Q
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse_lazy
from django.contrib.auth import login, authenticate, logout
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
from django.contrib.contenttypes.models import ContentType
from rest_framework import permissions, generics
from rest_framework.response import Response
from rest_framework.views import APIView
from typing import cast

from .forms import (
    PublicUserRegistrationForm,
    StaffUserRegistrationForm,
    StyledPasswordResetForm,
    StyledSetPasswordForm,
    UserProfileUpdateForm,
)
from .models import OperationalAccessRequest, User
from .security import (
    audit_security_event,
    clear_staff_mfa_session,
    create_staff_mfa_challenge,
    session_has_valid_mfa,
    staff_mfa_required,
    verify_staff_mfa_code,
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
from apps.workforce.models import Application, HealthStudent, NursingProfessional, MedicalDoctor, CommunityHealthWorker, NurseAide
from .serializers import UserSerializer


STAFF_LOGIN_ROLES = {'admin', 'registrar', 'reviewer'}
APPLICANT_LOGIN_ROLES = {'viewer', 'nurse_aide', 'nurse', 'chw', 'doctor', 'graduand'}


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
    }
    target = portal_map.get(portal)
    if target:
        return target
    return None


def _create_professional_record(user, cleaned_data):
    if user.role in {'graduand', 'student', 'nurse_aide'}:
        registration_no = cleaned_data.get('registration_number') or user.username
    else:
        registration_no = cleaned_data.get('license_number') or user.username
    common = {
        'first_name': user.first_name,
        'last_name': user.last_name,
        'registration_no': registration_no,
        'email': user.email,
        'primary_phone': user.phone,
    }

    if user.role in {'graduand', 'student'}:
        return HealthStudent.objects.create(
            **common,
            program=cleaned_data.get('program', 'General Nursing'),
            applicant_type=cleaned_data.get('applicant_type', 'national'),
            passport_photo=user.passport_photo,
            id_document_image=user.id_document_image,
            is_graduate=user.role == 'graduand',
        )
    if user.role == 'nurse':
        return NursingProfessional.objects.create(
            **common,
            applicant_type=cleaned_data.get('applicant_type', 'national'),
            passport_photo=user.passport_photo,
            id_document_image=user.id_document_image,
            qualification_level=cleaned_data.get('qualification_level', ''),
        )
    if user.role == 'doctor':
        return MedicalDoctor.objects.create(
            **common,
            applicant_type=cleaned_data.get('applicant_type', 'national'),
            passport_photo=user.passport_photo,
            id_document_image=user.id_document_image,
            specialty=cleaned_data.get('specialty', ''),
        )
    if user.role == 'chw':
        return CommunityHealthWorker.objects.create(
            **common,
            applicant_type=cleaned_data.get('applicant_type', 'national'),
            passport_photo=user.passport_photo,
            id_document_image=user.id_document_image,
            community_id=cleaned_data.get('community_id', ''),
            training_level=cleaned_data.get('training_level', ''),
        )
    if user.role == 'nurse_aide':
        return NurseAide.objects.create(
            **common,
            applicant_type=cleaned_data.get('applicant_type', 'national'),
            passport_photo=user.passport_photo,
            id_document_image=user.id_document_image,
            training_level=cleaned_data.get('training_level', ''),
        )
    return None


# ====================== LOGIN ======================
def _login_view(request, auth_mode='applicant'):
    portal = request.GET.get('portal', '')
    next_url = request.GET.get('next', '')
    allowed_roles = STAFF_LOGIN_ROLES if auth_mode == 'staff' else APPLICANT_LOGIN_ROLES

    user = request.user
    if user.is_authenticated:
        if auth_mode == 'staff' and user.role not in STAFF_LOGIN_ROLES:
            return redirect(get_role_based_redirect(user))
        if auth_mode == 'applicant' and user.role in STAFF_LOGIN_ROLES:
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
            if user.role == 'admin' and not user.role_approved:
                messages.error(request, "This admin account is waiting for registrar approval.")
                return render(request, 'accounts/login.html', {
                    'portal': portal,
                    'login_mode': auth_mode,
                    'portal_name': 'Staff Login' if auth_mode == 'staff' else 'Applicant Login',
                })
            if user.role not in allowed_roles:
                messages.error(request, "This account must use the correct login page.")
                audit_security_event(
                    'LOGIN_FAILED',
                    user=user,
                    username=identifier or '',
                    request=request,
                    details={'reason': 'wrong_login_page', 'login_mode': auth_mode},
                )
                return render(request, 'accounts/login.html', {
                    'portal': portal,
                    'login_mode': auth_mode,
                    'portal_name': 'Staff Login' if auth_mode == 'staff' else 'Applicant Login',
                })
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

    context = {
        'portal': portal,
        'login_mode': auth_mode,
        'portal_name': {
            'nursing': 'Nursing Council Portal',
            'medical': 'Medical Board Portal',
            'graduand': 'Graduand Portal',
            'student': 'Graduand Portal',
            'staff': 'Medical Staff Portal'
        }.get(portal, 'NDOH Workforce Registry')
    }

    return render(request, 'accounts/login.html', context)


def login_view(request):
    return _login_view(request, auth_mode='applicant')


def staff_login_view(request):
    return _login_view(request, auth_mode='staff')


def applicant_login_view(request):
    return _login_view(request, auth_mode='applicant')


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
def public_register(request):
    if request.user.is_authenticated and request.user.role not in {'admin', 'registrar', 'reviewer'}:
        return redirect(get_role_based_redirect(request.user))

    if request.method == 'POST':
        form = PublicUserRegistrationForm(request.POST, request.FILES)
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
            user.last_name = form.cleaned_data.get('last_name', '')
            user.employee_details = form.cleaned_data.get('employee_details', '')
            user.profile_image = form.cleaned_data.get('profile_image')
            user.passport_photo = form.cleaned_data.get('passport_photo')
            user.id_document_image = form.cleaned_data.get('id_document_image')
            user.save()

            professional = _create_professional_record(user, form.cleaned_data)
            if professional:
                form_code_map = {
                    'graduand': 'G1',
                    'nurse': 'NC2',
                    'doctor': 'MD1',
                    'chw': 'CHW1',
                    'nurse_aide': 'NC2',
                }
                Application.objects.create(
                    content_type=ContentType.objects.get_for_model(professional),
                    object_id=professional.id,
                    form_code=form_code_map.get(user.role, 'NC2'),
                    status='pending',
                    reviewer_notes='New account created via public portal'
                )

            # Send welcome email
            send_mail(
                'Welcome to NDOH Workforce Registry',
                f'Dear {user.get_full_name() or user.username},\n\n'
                f'Your account has been created as a {user.role.title()}.\n'
                f'You can now log in and complete your profile.',
                'no-reply@ndoh.gov.pg',
                [user.email],
                fail_silently=True,
            )

            messages.success(request, "Account created successfully! Please log in.")
            return redirect('login')
        messages.error(request, "Registration was not completed. Please correct the highlighted fields below.")

    else:
        form = PublicUserRegistrationForm()

    return render(request, 'accounts/public_register.html', {'form': form})


def staff_register(request):
    if request.method == 'POST':
        form = StaffUserRegistrationForm(request.POST, request.FILES)
        if form.is_valid():
            user = form.save(commit=False)
            user.role = form.cleaned_data['role']
            user.department = form.cleaned_data.get('department', '')
            user.phone = form.cleaned_data.get('phone', '')
            user.profile_image = form.cleaned_data.get('profile_image')
            user.role_approved = user.role == 'registrar'
            user.is_active = user.role == 'registrar'
            user.is_staff = user.role == 'registrar'
            user.save()

            if user.role == 'admin':
                messages.success(request, "Admin request submitted. A registrar must approve it before login.")
            else:
                messages.success(request, "Registrar account created successfully.")
            return redirect('staff_login')
        messages.error(request, "Staff registration was not completed. Please correct the highlighted fields below.")
    else:
        form = StaffUserRegistrationForm()
    return render(request, 'accounts/staff_register.html', {'form': form})


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
    if request.method == 'POST':
        form = UserProfileUpdateForm(request.POST, request.FILES, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated successfully.")
            return redirect('user_profile')
        messages.error(request, "Please correct the profile form errors below.")
    else:
        form = UserProfileUpdateForm(instance=user)

    nursing_regulatory_alignment = None
    if user.role == "registrar" and is_nursing_council_staff(user):
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
        'show_settings_modal': request.GET.get('settings') == '1' or (request.method == 'POST' and not form.is_valid()),
        'profile_access': _role_access_profile(user),
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
    if user.role != "registrar" or not is_nursing_council_staff(user):
        messages.error(request, "This live regulatory statistics page is only available to Nursing Council registrar users.")
        return redirect("user_profile")

    return render(request, "accounts/nursing_regulatory_alignment_page.html", {
        "alignment": build_nursing_regulatory_alignment_context(),
    })


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
