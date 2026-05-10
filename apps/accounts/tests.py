from io import BytesIO

from PIL import Image
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import OperationalAccessRequest, SecurityAuditEvent, UserMFAChallenge
from apps.dashboard.access import can_manage_regulatory_operations
from apps.notifications.models import Notification

from .forms import PublicUserRegistrationForm


def make_image_file(name):
    buffer = BytesIO()
    Image.new('RGB', (1, 1), color='white').save(buffer, format='PNG')
    return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')


class PublicRegistrationTests(TestCase):
    def test_public_registration_form_accepts_images(self):
        form = PublicUserRegistrationForm(
            data={
                'first_name': 'Derick',
                'last_name': 'Aitsi',
                'username': 'Derick1',
                'email': 'derick1@gov.pg',
                'phone': '1234543',
                'employee_details': 'Port Moresby General Hospital',
                'role': 'nurse',
                'applicant_type': 'national',
                'license_number': 'GD-3434',
                'registration_number': '432345',
                'password1': 'StrongerPass123!',
                'password2': 'StrongerPass123!',
            },
            files={
                'profile_image': make_image_file('profile.png'),
                'passport_photo': make_image_file('passport.png'),
                'id_document_image': make_image_file('id.png'),
            },
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_blank_unique_fields_are_normalized_on_save(self):
        user_model = get_user_model()

        first_user = user_model(username='alpha', email='alpha@gov.pg', role='viewer')
        first_user.save()

        second_user = user_model(username='bravo', email='bravo@gov.pg', role='viewer')
        second_user.save()

        self.assertIsNone(first_user.license_number)
        self.assertIsNone(first_user.registration_number)
        self.assertIsNone(first_user.national_id)
        self.assertIsNone(second_user.license_number)
        self.assertIsNone(second_user.registration_number)
        self.assertIsNone(second_user.national_id)
        self.assertEqual(user_model.objects.count(), 2)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class PasswordResetTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.user = self.user_model.objects.create_user(
            username='nurse.reset',
            email='nurse.reset@gov.pg',
            password='OriginalPass123!',
            role='nurse',
        )

    def test_login_page_shows_forgotten_password_link(self):
        response = self.client.get(reverse('login'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('password_reset'))

    def test_password_reset_sends_email_for_matching_account(self):
        response = self.client.post(reverse('password_reset'), {'email': 'nurse.reset@gov.pg'})

        self.assertRedirects(response, reverse('password_reset_done'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('password reset', mail.outbox[0].subject.lower())

    def test_password_reset_does_not_disclose_missing_email(self):
        response = self.client.post(reverse('password_reset'), {'email': 'missing@gov.pg'})

        self.assertRedirects(response, reverse('password_reset_done'))
        self.assertEqual(len(mail.outbox), 0)


class ProfileRoleAccessTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.nursing_registrar = self.user_model.objects.create_user(
            username='nursing.registrar',
            email='registrar@nursing.gov.pg',
            password='StrongPass123!',
            role='registrar',
            department='Nursing Council',
        )
        self.nursing_reviewer = self.user_model.objects.create_user(
            username='nurse_reviewer',
            email='reviewer@nursing.gov.pg',
            password='StrongPass123!',
            role='reviewer',
            department='Nursing Council',
        )

    def test_nursing_reviewer_profile_explains_limited_access(self):
        self.client.force_login(self.nursing_reviewer)

        response = self.client.get(reverse('user_profile'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Reviewer - Nursing Council')
        self.assertContains(response, 'Limited Role-Based Access')
        self.assertContains(response, 'Nursing Council Operations or Medical Board Operations command buttons')
        self.assertContains(response, 'Request Registrar/System Admin Approval')

    def test_nursing_reviewer_request_notifies_registrar(self):
        self.client.force_login(self.nursing_reviewer)

        response = self.client.post(reverse('request_full_access'))

        self.assertRedirects(response, reverse('user_profile'))
        access_request = OperationalAccessRequest.objects.get(user=self.nursing_reviewer)
        self.assertEqual(access_request.status, 'pending')
        self.assertEqual(access_request.requested_office, 'nursing')
        notification = Notification.objects.get(user=self.nursing_registrar)
        self.assertIn('Full portal access request', notification.subject)
        self.assertIn('nurse_reviewer', notification.message)

    def test_registrar_can_view_and_approve_nursing_reviewer_request(self):
        OperationalAccessRequest.objects.create(
            user=self.nursing_reviewer,
            requested_office='nursing',
            reason='Needs temporary operational access.',
        )
        self.client.force_login(self.nursing_registrar)

        inbox_response = self.client.get(reverse('staff_communications'))
        access_request = OperationalAccessRequest.objects.get(user=self.nursing_reviewer)
        approve_response = self.client.post(
            reverse('decide_operational_access_request', args=[access_request.pk, 'approve'])
        )

        self.assertEqual(inbox_response.status_code, 200)
        self.assertContains(inbox_response, 'Operational Access Requests')
        self.assertContains(inbox_response, 'nurse_reviewer')
        self.assertRedirects(approve_response, reverse('staff_communications'))
        access_request.refresh_from_db()
        self.nursing_reviewer.refresh_from_db()
        self.assertEqual(access_request.status, 'approved')
        self.assertTrue(self.nursing_reviewer.operations_approved)
        self.assertTrue(can_manage_regulatory_operations(self.nursing_reviewer))

    def test_nursing_reviewer_sees_locked_operations_and_cannot_execute_commands(self):
        self.client.force_login(self.nursing_reviewer)

        portal_response = self.client.get(reverse('nursing_council_portal'))
        command_response = self.client.post(
            reverse('execute_management_command'),
            {'command': 'bootstrap_reference_data'},
        )

        self.assertEqual(portal_response.status_code, 200)
        self.assertContains(portal_response, 'Operations locked for reviewer accounts.')
        self.assertNotContains(portal_response, "onclick=\"executeCommand('bootstrap_reference_data')\"")
        self.assertEqual(command_response.status_code, 403)


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    REQUIRE_STAFF_MFA=True,
    STAFF_MFA_TIMEOUT_SECONDS=600,
)
class StaffMFATests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.registrar = self.user_model.objects.create_user(
            username='mfa.registrar',
            email='mfa.registrar@gov.pg',
            password='StrongPass123!',
            role='registrar',
            department='Nursing Council',
        )

    def test_registrar_login_requires_email_mfa_before_dashboard_access(self):
        response = self.client.post(
            reverse('staff_login'),
            {'username': 'mfa.registrar', 'password': 'StrongPass123!'},
        )

        self.assertRedirects(response, reverse('staff_mfa_verify'), fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(UserMFAChallenge.objects.filter(user=self.registrar).count(), 1)
        self.assertTrue(SecurityAuditEvent.objects.filter(user=self.registrar, action='LOGIN_SUCCESS').exists())
        self.assertTrue(SecurityAuditEvent.objects.filter(user=self.registrar, action='MFA_CHALLENGE_CREATED').exists())

        blocked_response = self.client.get(reverse('registrar_dashboard'))
        self.assertRedirects(blocked_response, reverse('staff_mfa_verify'), fetch_redirect_response=False)

        code = mail.outbox[0].body.split(' is ')[1].split('.')[0]
        verify_response = self.client.post(reverse('staff_mfa_verify'), {'code': code})

        self.assertRedirects(verify_response, reverse('registrar_dashboard'), fetch_redirect_response=False)
        self.assertTrue(SecurityAuditEvent.objects.filter(user=self.registrar, action='MFA_VERIFIED').exists())
