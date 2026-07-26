from io import BytesIO
from pathlib import Path

from PIL import Image
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import OperationalAccessRequest, SecurityAuditEvent, UserMFAChallenge
from apps.dashboard.access import (
    can_manage_regulatory_operations,
    is_data_quality_reviewer,
    is_finance_reviewer,
    is_medical_board_staff,
)
from apps.notifications.models import Notification
from apps.workforce.models import Application, Cadre, HealthStudent, NursingProfessional

from .forms import PublicUserRegistrationForm, StaffUserRegistrationForm


def make_image_file(name):
    buffer = BytesIO()
    Image.new('RGB', (1, 1), color='white').save(buffer, format='PNG')
    return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')


def contrast_ratio(foreground_hex, background_hex):
    def channel(value):
        normalized = value / 255
        if normalized <= 0.03928:
            return normalized / 12.92
        return ((normalized + 0.055) / 1.055) ** 2.4

    def luminance(hex_color):
        hex_color = hex_color.lstrip('#')
        red = channel(int(hex_color[0:2], 16))
        green = channel(int(hex_color[2:4], 16))
        blue = channel(int(hex_color[4:6], 16))
        return 0.2126 * red + 0.7152 * green + 0.0722 * blue

    foreground_luminance = luminance(foreground_hex)
    background_luminance = luminance(background_hex)
    lighter = max(foreground_luminance, background_luminance)
    darker = min(foreground_luminance, background_luminance)
    return (lighter + 0.05) / (darker + 0.05)


class LoginPageContrastTests(TestCase):
    def test_staff_login_keeps_sign_in_button_text_clear(self):
        response = self.client.get(reverse('staff_login'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Sign In')
        self.assertContains(response, '20260623-font-contrast-4')
        self.assertContains(response, 'body.auth-page .btn-primary:hover, body.auth-page .btn-primary:focus, body.auth-page .btn-primary:active')
        self.assertContains(response, '-webkit-text-fill-color: #fff !important;')
        self.assertContains(response, '.btn-outline-secondary:hover, .btn-outline-secondary:focus, .btn-outline-secondary:active')
        self.assertContains(response, '-webkit-text-fill-color: #15293d !important;')

    def test_staff_login_button_color_pairs_meet_readability_ratio(self):
        clear_text_threshold = 4.5
        color_pairs = (
            ('#ffffff', '#18324a'),  # sign-in gradient navy
            ('#ffffff', '#2f5f53'),  # sign-in gradient green
            ('#ffffff', '#102033'),  # sign-in hover gradient navy
            ('#ffffff', '#224a40'),  # sign-in hover gradient green
            ('#15293d', '#ffffff'),  # outline secondary default
            ('#ffffff', '#334155'),  # outline secondary hover
            ('#334155', '#ffffff'),  # muted field notes
            ('#ffffff', '#1d4f7a'),  # shared primary/info button
            ('#ffffff', '#17634f'),  # shared success button
            ('#111827', '#b7791f'),  # shared warning button
            ('#ffffff', '#991b1b'),  # shared danger button
            ('#ffffff', '#0a1e31'),  # shared secondary/dark button
            ('#ffffff', '#16705f'),  # Nursing Council primary
            ('#ffffff', '#0f4b40'),  # Nursing Council primary hover
            ('#ffffff', '#15558b'),  # Medical Board primary
            ('#ffffff', '#0b365d'),  # Medical Board primary hover
        )

        for foreground, background in color_pairs:
            with self.subTest(foreground=foreground, background=background):
                self.assertGreaterEqual(
                    contrast_ratio(foreground, background),
                    clear_text_threshold,
                )

    def test_nursing_login_page_uses_nursing_council_only_wording(self):
        response = self.client.get(f"{reverse('login')}?portal=nursing")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<h1>Nursing Council Portal</h1>')
        self.assertContains(response, 'Nursing Council sign in is for nurses, nurse aides, and graduands only.')
        self.assertContains(response, reverse('public_nursing_account_register'))
        self.assertContains(response, 'New here? Choose your account')
        self.assertContains(response, 'Nursing workforce account')
        self.assertContains(response, 'For registered nurses, nurse aides, and graduands.')
        self.assertContains(response, 'Regulatory staff account')
        self.assertContains(response, 'Request staff account')
        self.assertContains(response, reverse('staff_register'))
        self.assertContains(response, 'auth-nursing')
        self.assertContains(response, '--agency-primary: #16705f;')
        self.assertNotContains(response, 'PNG Regulatory Bodies:The Medical Board')
        self.assertNotContains(response, 'Medical Board')
        self.assertNotContains(response, 'Create Medical Board account')

    def test_medical_login_page_uses_medical_board_only_wording(self):
        response = self.client.get(f"{reverse('login')}?portal=medical")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<h1>Medical Board Portal</h1>')
        self.assertContains(response, 'Medical Board sign in is for doctors and Community Health Workers only.')
        self.assertContains(response, reverse('public_medical_board_account_register'))
        self.assertContains(response, 'New here? Choose your account')
        self.assertContains(response, 'Medical workforce account')
        self.assertContains(response, 'For doctors, medical specialists, and Community Health Workers.')
        self.assertContains(response, 'Regulatory staff account')
        self.assertContains(response, 'Request staff account')
        self.assertContains(response, reverse('staff_register'))
        self.assertContains(response, 'auth-medical')
        self.assertContains(response, '--agency-primary: #15558b;')
        self.assertNotContains(response, 'Medical Board &amp; Nursing Council')
        self.assertNotContains(response, 'Nursing Council')
        self.assertNotContains(response, 'Create Nursing Council account')


class BoardLoginTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.board_user = self.user_model.objects.create_user(
            username='board.login',
            email='board.login@gov.pg',
            password='StrongPass123!',
            role='board_member',
            first_name='Board',
            last_name='Member',
        )
        self.nurse_user = self.user_model.objects.create_user(
            username='nurse.login',
            email='nurse.login@gov.pg',
            password='StrongPass123!',
            role='nurse',
        )

    def test_board_login_page_is_separate_sign_in_surface(self):
        response = self.client.get(reverse('board_login'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/board_login.html')
        self.assertContains(response, '20260707-board-login-contrast-1')
        self.assertContains(response, 'Nursing Council Board Portal')
        self.assertContains(response, 'Board member sign in')
        self.assertContains(response, 'Sign In To Board Portal')
        self.assertContains(response, 'authorised board account credentials')
        self.assertNotContains(response, 'Applicant sign in is for')
        self.assertNotContains(response, 'Staff sign in is for')

    def test_board_login_text_contrast_guards_are_in_shared_css(self):
        css_path = Path(__file__).resolve().parents[2] / 'static' / 'css' / 'government-enterprise.css'
        css = css_path.read_text(encoding='utf-8')

        self.assertIn('Nursing Council Board sign-in contrast guard', css)
        self.assertIn('body.board-auth-page .board-auth-panel', css)
        self.assertIn('-webkit-text-fill-color: #ffffff !important;', css)
        self.assertIn('body.board-auth-page .form-control', css)
        self.assertIn('-webkit-text-fill-color: #111827 !important;', css)

    def test_board_login_color_pairs_meet_readability_ratio(self):
        clear_text_threshold = 4.5
        color_pairs = (
            ('#ffffff', '#102033'),  # dark board panel text
            ('#f4c95d', '#102033'),  # dark board panel icons
            ('#102033', '#ffffff'),  # form headings and labels
            ('#334155', '#ffffff'),  # explanatory copy
            ('#111827', '#ffffff'),  # input text and placeholders
            ('#164866', '#ffffff'),  # forgotten-password link
            ('#17443b', '#eef6f3'),  # board portal pill
            ('#ffffff', '#18324a'),  # primary board button
        )

        for foreground, background in color_pairs:
            with self.subTest(foreground=foreground, background=background):
                self.assertGreaterEqual(
                    contrast_ratio(foreground, background),
                    clear_text_threshold,
                )

    def test_board_login_authenticates_board_member_to_board_portal(self):
        response = self.client.post(reverse('board_login'), {
            'username': 'board.login',
            'password': 'StrongPass123!',
        })

        self.assertRedirects(response, reverse('board_nursing_dashboard'), fetch_redirect_response=False)

    def test_board_login_rejects_non_board_account(self):
        response = self.client.post(reverse('board_login'), {
            'username': 'nurse.login',
            'password': 'StrongPass123!',
        })

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/board_login.html')
        self.assertContains(response, 'This account must use the correct login page.')
        self.assertContains(response, 'Board member sign in')

    def test_board_register_page_renders_for_board_access_requests(self):
        response = self.client.get(reverse('board_register'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/board_register.html')
        self.assertContains(response, 'This request creates an account for board-only access.')
        self.assertContains(response, 'Board account request')
        self.assertContains(response, 'username / official email alias')
        self.assertContains(response, 'Board Request Token is generated after submission')
        self.assertNotContains(response, 'Board membership registration token')
        self.assertNotContains(response, 'registration_token')

    def test_board_register_rejects_existing_authenticated_users(self):
        self.client.force_login(self.board_user)

        response = self.client.get(reverse('board_register'))

        self.assertRedirects(response, reverse('board_nursing_dashboard'))

        normal_user = self.user_model.objects.create_user(
            username='normal.nonboard',
            password='StrongPass123!',
            role='nurse',
            first_name='Normal',
            last_name='Staff',
        )
        self.client.force_login(normal_user)
        response = self.client.get(reverse('board_register'))

        self.assertRedirects(response, reverse('nurse_dashboard'))

    def test_board_register_page_can_create_board_member_request(self):
        registrar = self.user_model.objects.create_user(
            username='nursing.approver',
            password='StrongPass123!',
            role='registrar',
            department='Nursing Council',
            role_approved=True,
            system_admin_approved=True,
        )
        admin_user = self.user_model.objects.create_superuser(
            username='board.approver.admin',
            email='board.approver.admin@gov.pg',
            password='StrongPass123!',
            role='admin',
        )
        board_registration_payload = {
            'first_name': 'New',
            'last_name': 'Board',
            'username': 'new.board',
            'email': 'new.board@gov.pg',
            'phone': '+675 700 700',
            'department': 'Nursing Council Board',
            'job_title': 'Board Member',
            'employee_details': 'Board member from governance secretariat.',
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
        }
        response = self.client.post(reverse('board_register'), board_registration_payload, follow=True)

        self.assertRedirects(response, reverse('board_login'))
        created_user = self.user_model.objects.get(username='new.board')

        self.assertEqual(created_user.role, 'board_member')
        self.assertTrue(created_user.is_active)
        self.assertFalse(created_user.role_approved)
        self.assertFalse(created_user.system_admin_approved)
        self.assertEqual(created_user.department, 'Nursing Council Board')
        self.assertEqual(created_user.job_title, 'Board Member')
        self.assertRegex(created_user.board_registration_token, r'^NCB-\d{8}-[A-Z0-9]{8}$')
        self.assertIsNotNone(created_user.board_registration_token_created_at)
        self.assertContains(response, f'Board request token: {created_user.board_registration_token}.')
        self.assertTrue(
            Notification.objects.filter(
                user=registrar,
                subject='Staff account approval required: new.board',
                message__contains=f'Board request token: {created_user.board_registration_token}.',
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                user=admin_user,
                subject='Staff account approval required: new.board',
                message__contains=f'Board request token: {created_user.board_registration_token}.',
            ).exists()
        )

    def test_board_register_generates_unique_request_tokens(self):
        first_payload = {
            'first_name': 'First',
            'last_name': 'Board',
            'username': 'first.generated.board',
            'email': 'first.generated.board@gov.pg',
            'phone': '+675 700 701',
            'department': 'Nursing Council Board',
            'job_title': 'Board Member',
            'employee_details': 'First generated token request.',
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
        }
        second_payload = {
            'first_name': 'Second',
            'last_name': 'Board',
            'username': 'second.generated.board',
            'email': 'second.generated.board@gov.pg',
            'phone': '+675 700 702',
            'department': 'Nursing Council Board',
            'job_title': 'Board Member',
            'employee_details': 'Second generated token request.',
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
        }

        first_response = self.client.post(reverse('board_register'), first_payload)
        second_response = self.client.post(reverse('board_register'), second_payload)

        self.assertRedirects(first_response, reverse('board_login'), fetch_redirect_response=False)
        self.assertRedirects(second_response, reverse('board_login'), fetch_redirect_response=False)
        first_user = self.user_model.objects.get(username='first.generated.board')
        second_user = self.user_model.objects.get(username='second.generated.board')

        self.assertRegex(first_user.board_registration_token, r'^NCB-\d{8}-[A-Z0-9]{8}$')
        self.assertRegex(second_user.board_registration_token, r'^NCB-\d{8}-[A-Z0-9]{8}$')
        self.assertNotEqual(first_user.board_registration_token, second_user.board_registration_token)
        self.assertFalse(first_user.has_required_staff_login_approvals())
        self.assertFalse(second_user.has_required_staff_login_approvals())


class AdminUserNavigationTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.admin_user = self.user_model.objects.create_superuser(
            username='admin.navigator',
            email='admin.navigator@gov.pg',
            password='StrongPass123!',
            role='admin',
        )
        self.target_user = self.user_model.objects.create_user(
            username='nurse.navigator',
            email='nurse.navigator@gov.pg',
            password='StrongPass123!',
            role='nurse',
        )

    def test_user_changelist_has_clear_open_links_to_change_page(self):
        self.client.force_login(self.admin_user)

        response = self.client.get(reverse('admin:accounts_user_changelist'))

        self.assertEqual(response.status_code, 200)
        change_url = reverse('admin:accounts_user_change', args=[self.target_user.pk])
        self.assertContains(response, change_url)
        self.assertContains(response, '>Open</a>')

        change_response = self.client.get(change_url)
        self.assertEqual(change_response.status_code, 200)
        self.assertContains(change_response, 'id_username')


class PublicRegistrationTests(TestCase):
    def test_public_register_page_uses_cadre_dropdown_and_emblem_background(self):
        Cadre.objects.create(name='Emergency Nursing', category='nursing')
        Cadre.objects.create(name='Medical Doctor', category='medical')

        response = self.client.get(reverse('public_register'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'body.auth-page::before')
        self.assertContains(response, '.auth-brand::before')
        self.assertContains(response, 'background-position: center bottom 20px;')
        self.assertContains(response, 'National_emblem_of_Papua_New_Guinea_(variant).svg.png')
        self.assertContains(response, '<select name="cadre_name"')
        self.assertContains(response, 'Nursing Council - Emergency Nursing')
        self.assertContains(response, 'Medical Board - Medical Doctor (Full License)')
        self.assertContains(response, 'Medical Board - CHW Provisional Registration')
        self.assertContains(response, 'Medical Board - CHW Full License')
        self.assertContains(response, 'Nursing Council - Midwifery (Full License)')
        self.assertContains(response, 'Nursing Council - Nursing Graduand')
        self.assertNotContains(response, 'placeholder="e.g. General Nursing, CHW, Medical Doctor"')

    def test_nursing_account_register_limits_roles_and_cadres_to_nursing_council(self):
        Cadre.objects.create(name='Emergency Nursing', category='nursing')
        Cadre.objects.create(name='Medical Doctor', category='medical')
        Cadre.objects.create(name='Community Health Worker (CHW)', category='nursing')
        Cadre.objects.create(name='Allied Health Professional', category='nursing')

        response = self.client.get(reverse('public_nursing_account_register'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Nursing Council Account Registration')
        self.assertContains(response, 'value="graduand"')
        self.assertContains(response, 'value="nurse"')
        self.assertContains(response, 'value="nurse_aide"')
        self.assertContains(response, 'Nursing Council - Emergency Nursing')
        self.assertContains(response, 'Create Nursing Council Account')
        self.assertNotContains(response, 'Medical Board')
        self.assertNotContains(response, 'Community Health Worker')
        self.assertNotContains(response, 'Allied Health')
        self.assertNotContains(response, 'value="doctor"')
        self.assertNotContains(response, 'value="chw"')

    def test_medical_board_account_register_limits_roles_and_cadres_to_medical_board(self):
        Cadre.objects.create(name='Emergency Nursing', category='nursing')
        Cadre.objects.create(name='Medical Doctor', category='medical')
        Cadre.objects.create(name='General Nursing', category='medical')
        Cadre.objects.create(name='Allied Health Professional', category='medical')

        response = self.client.get(reverse('public_medical_board_account_register'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Medical Board Account Registration')
        self.assertContains(response, 'value="doctor"')
        self.assertContains(response, 'value="chw"')
        self.assertContains(response, 'Medical Board - Medical Doctor (Full License)')
        self.assertContains(response, 'Create Medical Board Account')
        self.assertNotContains(response, 'Nursing Council')
        self.assertNotContains(response, 'General Nursing')
        self.assertNotContains(response, 'Allied Health')
        self.assertNotContains(response, 'value="graduand"')
        self.assertNotContains(response, 'value="nurse"')
        self.assertNotContains(response, 'value="nurse_aide"')

    def test_scoped_account_register_rejects_cross_board_role_submission(self):
        response = self.client.post(reverse('public_nursing_account_register'), {
            'first_name': 'Cross',
            'middle_name': '',
            'last_name': 'Scope',
            'username': 'cross.scope',
            'email': 'cross.scope@gov.pg',
            'phone': '70000009',
            'employee_details': 'Medical account submitted on nursing route',
            'role': 'doctor',
            'applicant_type': 'national',
            'cadre_name': 'Medical Doctor',
            'license_number': 'MD-CROSS-001',
            'registration_number': '',
            'password1': 'StrongerPass123!',
            'password2': 'StrongerPass123!',
        })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(username='cross.scope').exists())
        self.assertContains(response, 'Registration was not completed')

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
                'cadre_name': 'General Nursing',
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
    def test_public_registration_links_existing_professional_record(self):
        cadre = Cadre.objects.create(name='General Nursing', category='nursing')
        professional = NursingProfessional.objects.create(
            first_name='Martha',
            middle_name='Ana',
            last_name='Kila',
            registration_no='RN-2026-001',
            email='martha.registry@gov.pg',
            cadre=cadre,
        )

        response = self.client.post(reverse('public_register'), {
            'first_name': 'Martha',
            'middle_name': 'Ana',
            'last_name': 'Kila',
            'username': 'martha.kila',
            'email': 'martha.portal@gov.pg',
            'phone': '70000001',
            'employee_details': 'Port Moresby General Hospital',
            'role': 'nurse',
            'applicant_type': 'national',
            'cadre_name': 'General Nursing',
            'license_number': 'RN-2026-001',
            'registration_number': '',
            'password1': 'StrongerPass123!',
            'password2': 'StrongerPass123!',
        })

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response['Location'])
        user = get_user_model().objects.get(username='RN-2026-001')
        self.assertEqual(user.professional_record_status, 'linked')
        self.assertEqual(user.professional_record, professional)
        self.assertEqual(NursingProfessional.objects.count(), 1)
        self.assertEqual(Application.objects.count(), 0)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_new_graduand_without_provisional_number_gets_pending_record_and_pathway(self):
        response = self.client.post(reverse('public_register'), {
            'first_name': 'Lina',
            'middle_name': '',
            'last_name': 'Toma',
            'username': 'lina.toma',
            'email': 'lina.toma@gov.pg',
            'phone': '70000002',
            'employee_details': 'New graduand',
            'role': 'graduand',
            'applicant_type': 'national',
            'cadre_name': 'Graduand',
            'license_number': '',
            'registration_number': '',
            'password1': 'StrongerPass123!',
            'password2': 'StrongerPass123!',
        })

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response['Location'])
        self.assertIn(reverse('public_graduand_register'), response['Location'])
        user = get_user_model().objects.get(username='lina.toma')
        self.assertEqual(user.professional_record_status, 'pending_review')
        self.assertIsInstance(user.professional_record, HealthStudent)
        self.assertIsNone(user.professional_record.registration_no)
        application = Application.objects.get()
        self.assertEqual(application.professional, user.professional_record)
        self.assertEqual(application.form_code, 'G3')
        self.assertEqual(application.status, 'pending')


class StaffRegistrationRoleTests(TestCase):
    def _staff_payload(self, username, staff_group, **overrides):
        payload = {
            'first_name': 'Staff',
            'last_name': 'Member',
            'username': username,
            'email': f'{username}@gov.pg',
            'phone': '70000000',
            'staff_group': staff_group,
            'department': '',
            'job_title': '',
            'employee_details': '',
            'password1': 'StrongerPass123!',
            'password2': 'StrongerPass123!',
        }
        payload.update(overrides)
        return payload

    def _assert_pending_staff_login(self, user):
        self.assertFalse(user.role_approved)
        self.assertFalse(user.system_admin_approved)
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.has_required_staff_login_approvals())

    def test_staff_register_page_lists_staff_groups_and_non_staff_routes(self):
        response = self.client.get(reverse('staff_register'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<select name="staff_group"')
        self.assertContains(response, 'All staff requests require Registrar and System Admin approval before login.')
        for item in StaffUserRegistrationForm.staff_access_guide():
            self.assertContains(response, item['label'])
            self.assertContains(response, item['privacy_position'])
        self.assertContains(response, 'Professional user')
        self.assertContains(response, 'Graduand / Student user')
        self.assertContains(response, 'Public user')
        self.assertContains(response, reverse('public_nursing_account_register'))
        self.assertContains(response, reverse('public_medical_board_account_register'))
        self.assertContains(response, reverse('public_graduand_register'))
        self.assertContains(response, reverse('public_nursing_register_search_root'))
        self.assertContains(response, reverse('public_medical_board_register_search_root'))

    def test_medical_board_staff_registration_maps_to_medical_registrar_scope(self):
        response = self.client.post(
            reverse('staff_register'),
            self._staff_payload('medical.staff.registration', 'medical_board_staff'),
        )

        self.assertRedirects(response, reverse('staff_login'))
        user = get_user_model().objects.get(username='medical.staff.registration')
        self.assertEqual(user.role, 'registrar')
        self.assertEqual(user.department, 'Medical Board')
        self.assertEqual(user.job_title, 'Medical Board Registrar / Staff')
        self._assert_pending_staff_login(user)
        self.assertTrue(is_medical_board_staff(user))

    def test_medical_board_staff_registration_notifies_medical_registrar_and_system_admin(self):
        user_model = get_user_model()
        medical_registrar = user_model.objects.create_user(
            username='medical.registrar.approver',
            email='medical.registrar.approver@gov.pg',
            password='StrongPass123!',
            role='registrar',
            department='Medical Board',
        )
        nursing_registrar = user_model.objects.create_user(
            username='nursing.registrar.approver',
            email='nursing.registrar.approver@gov.pg',
            password='StrongPass123!',
            role='registrar',
            department='Nursing Council',
        )
        system_admin = user_model.objects.create_superuser(
            username='system.admin.approver',
            email='system.admin.approver@gov.pg',
            password='StrongPass123!',
            role='admin',
        )

        response = self.client.post(
            reverse('staff_register'),
            self._staff_payload('medical.approval.request', 'medical_board_staff'),
        )

        self.assertRedirects(response, reverse('staff_login'))
        pending_user = user_model.objects.get(username='medical.approval.request')
        subject = 'Staff account approval required: medical.approval.request'
        self.assertTrue(Notification.objects.filter(user=medical_registrar, subject=subject).exists())
        self.assertTrue(Notification.objects.filter(user=system_admin, subject=subject).exists())
        self.assertFalse(Notification.objects.filter(user=nursing_registrar, subject=subject).exists())
        notification = Notification.objects.get(user=medical_registrar, subject=subject)
        self.assertIn('Medical Board Registrar / Staff access', notification.message)
        self.assertIn(pending_user.department, notification.message)
        self._assert_pending_staff_login(pending_user)

    def test_data_quality_officer_registration_maps_to_limited_reviewer(self):
        response = self.client.post(
            reverse('staff_register'),
            self._staff_payload('data.quality.registration', 'data_quality_officer'),
        )

        self.assertRedirects(response, reverse('staff_login'))
        user = get_user_model().objects.get(username='data.quality.registration')
        self.assertEqual(user.role, 'reviewer')
        self.assertEqual(user.department, 'Data Quality Office')
        self.assertEqual(user.job_title, 'Data Quality Officer')
        self._assert_pending_staff_login(user)
        self.assertFalse(user.operations_approved)
        self.assertFalse(can_manage_regulatory_operations(user))
        self.assertTrue(is_data_quality_reviewer(user))

    def test_finance_officer_registration_maps_to_read_only_reviewer(self):
        response = self.client.post(
            reverse('staff_register'),
            self._staff_payload('finance.registration', 'finance_officer'),
        )

        self.assertRedirects(response, reverse('staff_login'))
        user = get_user_model().objects.get(username='finance.registration')
        self.assertEqual(user.role, 'reviewer')
        self.assertEqual(user.department, 'Finance Office')
        self.assertEqual(user.job_title, 'Finance Officer')
        self._assert_pending_staff_login(user)
        self.assertFalse(user.operations_approved)
        self.assertFalse(can_manage_regulatory_operations(user))
        self.assertTrue(is_finance_reviewer(user))

    def test_system_admin_registration_is_pending_and_not_superuser(self):
        response = self.client.post(
            reverse('staff_register'),
            self._staff_payload('system.admin.request', 'system_admin'),
        )

        self.assertRedirects(response, reverse('staff_login'))
        user = get_user_model().objects.get(username='system.admin.request')
        self.assertEqual(user.role, 'admin')
        self.assertEqual(user.department, 'System Administration')
        self.assertEqual(user.job_title, 'System Admin')
        self._assert_pending_staff_login(user)
        self.assertFalse(user.is_superuser)

    def test_staff_account_cannot_login_until_registrar_and_system_admin_approve(self):
        self.client.post(
            reverse('staff_register'),
            self._staff_payload('dual.approval.reviewer', 'data_quality_officer'),
        )
        user = get_user_model().objects.get(username='dual.approval.reviewer')

        pending_response = self.client.post(
            reverse('staff_login'),
            {'username': 'dual.approval.reviewer', 'password': 'StrongerPass123!'},
        )
        self.assertEqual(pending_response.status_code, 200)
        self.assertContains(pending_response, 'waiting for Registrar and System Admin approval')
        self.assertNotIn('_auth_user_id', self.client.session)

        user.role_approved = True
        user.approved_at = timezone.now()
        user.save()
        registrar_only_response = self.client.post(
            reverse('staff_login'),
            {'username': 'dual.approval.reviewer', 'password': 'StrongerPass123!'},
        )
        self.assertEqual(registrar_only_response.status_code, 200)
        self.assertContains(registrar_only_response, 'waiting for System Admin approval')
        self.assertNotIn('_auth_user_id', self.client.session)

        user.system_admin_approved = True
        user.system_admin_approved_at = timezone.now()
        user.save()
        approved_response = self.client.post(
            reverse('staff_login'),
            {'username': 'dual.approval.reviewer', 'password': 'StrongerPass123!'},
        )
        self.assertEqual(approved_response.status_code, 302)
        self.assertIn('_auth_user_id', self.client.session)
        user.refresh_from_db()
        self.assertTrue(user.is_staff)
        self.assertTrue(user.has_required_staff_login_approvals())

    def test_medical_registrar_and_system_admin_can_approve_staff_account_from_inbox(self):
        user_model = get_user_model()
        medical_registrar = user_model.objects.create_user(
            username='medical.registrar.ui',
            email='medical.registrar.ui@gov.pg',
            password='StrongPass123!',
            role='registrar',
            department='Medical Board',
        )
        system_admin = user_model.objects.create_superuser(
            username='system.admin.ui',
            email='system.admin.ui@gov.pg',
            password='StrongPass123!',
            role='admin',
        )
        self.client.post(
            reverse('staff_register'),
            self._staff_payload('medical.approval.ui', 'medical_board_staff'),
        )
        pending_user = user_model.objects.get(username='medical.approval.ui')

        self.client.force_login(medical_registrar)
        inbox_response = self.client.get(reverse('staff_communications'))
        self.assertEqual(inbox_response.status_code, 200)
        self.assertContains(inbox_response, 'Staff Account Approval Requests')
        self.assertContains(inbox_response, 'medical.approval.ui')
        self.assertContains(inbox_response, 'Registrar Approve')
        self.assertNotContains(inbox_response, 'System Admin Approve')

        registrar_response = self.client.post(
            reverse('decide_staff_account_approval', args=[pending_user.pk, 'registrar'])
        )
        self.assertRedirects(registrar_response, reverse('staff_communications'))
        pending_user.refresh_from_db()
        self.assertTrue(pending_user.role_approved)
        self.assertFalse(pending_user.system_admin_approved)
        self.assertFalse(pending_user.is_staff)

        self.client.force_login(system_admin)
        system_admin_inbox_response = self.client.get(reverse('staff_communications'))
        self.assertContains(system_admin_inbox_response, 'medical.approval.ui')
        self.assertContains(system_admin_inbox_response, 'System Admin Approve')

        system_admin_response = self.client.post(
            reverse('decide_staff_account_approval', args=[pending_user.pk, 'system-admin'])
        )
        self.assertRedirects(system_admin_response, reverse('staff_communications'))
        pending_user.refresh_from_db()
        self.assertTrue(pending_user.role_approved)
        self.assertTrue(pending_user.system_admin_approved)
        self.assertTrue(pending_user.is_staff)
        self.assertTrue(pending_user.has_required_staff_login_approvals())


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
        self.nurse_user = self.user_model.objects.create_user(
            username='clinical.nurse',
            email='clinical.nurse@gov.pg',
            password='StrongPass123!',
            role='nurse',
            first_name='Clinical',
            last_name='Nurse',
        )

    def test_nursing_reviewer_profile_explains_limited_access(self):
        self.client.force_login(self.nursing_reviewer)

        response = self.client.get(reverse('user_profile'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'My Professional Profile')
        self.assertContains(response, 'profileSettingsModal')
        self.assertContains(response, 'data-bs-target="#profileSettingsModal"')
        self.assertContains(response, 'title="Open profile settings"')
        self.assertContains(response, 'profile-settings-dialog')
        self.assertContains(response, 'profile-settings-overview')
        self.assertContains(response, 'profile-settings-form')
        self.assertContains(response, 'profile-photo-upload')
        self.assertContains(response, 'Use a clear head-and-shoulders photo')
        self.assertContains(response, 'Complete your professional profile.')
        self.assertContains(response, 'Profile Settings')
        self.assertContains(response, 'Work Status & Facility')
        self.assertContains(response, 'Professional Bio')
        self.assertContains(response, 'Privacy Settings')
        self.assertContains(response, 'Password & Security')
        rendered = response.content.decode()
        self.assertGreater(
            rendered.index('id="profileSettingsModal"'),
            rendered.index('class="app-footer'),
        )
        self.assertNotContains(response, 'id="profile-settings"')
        self.assertNotContains(response, 'id="account-security"')
        self.assertContains(response, 'Reviewer - Nursing Council')
        self.assertContains(response, 'Limited Role-Based Access')
        self.assertContains(response, 'Nursing Council Operations or Medical Board Operations command buttons')
        self.assertContains(response, 'Request Registrar/System Admin Approval')

    def test_profile_settings_query_opens_hidden_settings_modal(self):
        self.client.force_login(self.nurse_user)

        response = self.client.get(f"{reverse('user_profile')}?settings=1")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'profileSettingsModal')
        self.assertContains(response, 'new window.bootstrap.Modal(modalNode).show()')

    def test_profile_settings_modal_styles_keep_settings_readable(self):
        css_path = Path(__file__).resolve().parents[2] / 'static' / 'css' / 'government-enterprise.css'
        css = css_path.read_text(encoding='utf-8')

        self.assertIn('.profile-settings-dialog', css)
        self.assertIn('.profile-settings-overview', css)
        self.assertIn('.profile-photo-upload', css)
        self.assertIn('.profile-settings-form .modal-form-footer', css)
        self.assertIn('-webkit-text-fill-color: #0f172a !important;', css)
        self.assertIn('.modal-backdrop', css)
        self.assertIn('z-index: 5000 !important;', css)
        self.assertIn('.modal {\n    z-index: 5010 !important;', css)
        self.assertIn('body.modal-open .helpdesk-launcher', css)
        self.assertIn('body.modal-open .helpdesk-widget', css)
        self.assertIn('body.modal-open .page-section-navigator', css)

    def test_clinical_user_updates_professional_profile_and_privacy_settings(self):
        self.client.force_login(self.nurse_user)

        response = self.client.post(reverse('user_profile'), {
            'profile_action': 'profile',
            'first_name': 'Clinical',
            'last_name': 'Nurse',
            'email': 'clinical.nurse.updated@gov.pg',
            'phone': '70000001',
            'secondary_email': 'clinical.backup@gov.pg',
            'postal_address': 'PO Box 1, Port Moresby',
            'applicant_type': 'national',
            'license_number': 'NC-PROFILE-001',
            'registration_number': '',
            'national_id': 'NID-PROFILE-001',
            'department': 'Emergency Department',
            'job_title': 'Senior General Nurse',
            'workplace_name': 'Port Moresby General Hospital',
            'workplace_location': 'Waigani',
            'practice_country': 'Papua New Guinea',
            'practice_province': 'National Capital District',
            'practice_district': 'Port Moresby',
            'work_status': 'practicing',
            'professional_bio': 'Experienced nurse supporting acute care and ward coordination.',
            'qualification_summary': 'Diploma in General Nursing',
            'specialty_area': 'Acute Care',
            'professional_memberships': 'PNG Nursing Council',
            'employee_details': 'Shift lead for emergency intake.',
            'primary_contact_method': 'portal',
            'profile_visibility': 'regulatory_staff',
            'show_email_on_profile': 'on',
            'allow_profile_contact': 'on',
        })

        self.assertRedirects(response, reverse('user_profile'))
        self.nurse_user.refresh_from_db()
        self.assertEqual(self.nurse_user.email, 'clinical.nurse.updated@gov.pg')
        self.assertEqual(self.nurse_user.job_title, 'Senior General Nurse')
        self.assertEqual(self.nurse_user.workplace_name, 'Port Moresby General Hospital')
        self.assertEqual(self.nurse_user.qualification_summary, 'Diploma in General Nursing')
        self.assertTrue(self.nurse_user.show_email_on_profile)
        self.assertFalse(self.nurse_user.show_phone_on_profile)
        self.assertTrue(self.nurse_user.allow_profile_contact)
        self.assertIsNotNone(self.nurse_user.profile_updated_at)

    def test_user_can_change_password_from_profile_security_panel(self):
        self.client.force_login(self.nurse_user)

        response = self.client.post(reverse('user_profile'), {
            'profile_action': 'password',
            'old_password': 'StrongPass123!',
            'new_password1': 'NewStrongPass123!',
            'new_password2': 'NewStrongPass123!',
        })

        self.assertRedirects(response, reverse('user_profile'))
        self.nurse_user.refresh_from_db()
        self.assertTrue(self.nurse_user.check_password('NewStrongPass123!'))
        profile_response = self.client.get(reverse('user_profile'))
        self.assertEqual(profile_response.status_code, 200)

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
