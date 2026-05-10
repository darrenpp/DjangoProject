from datetime import timedelta

from django.test import TestCase, override_settings
from django.core.cache import cache
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils import timezone

from apps.common.models import DuplicateReviewQueue
from apps.dashboard.ai_provider import ai_provider_status
from apps.dashboard.models import Receipt
from apps.dashboard.reference_breakdown import build_reference_breakdown
from apps.dashboard.staff_ai import build_staff_ai_chat_response
from apps.workforce.models import (
    Application,
    AuditLog,
    DataImportBatch,
    MedicalDoctor,
    MissingDataReview,
    NursingProfessional,
    PracticingLicenseRecord,
    TrainingInstitution,
)


class ReferenceBreakdownTests(TestCase):
    def setUp(self):
        cache.clear()
        TrainingInstitution.objects.create(name='Pacific Adventist University', type='')
        TrainingInstitution.objects.create(name='PAU', type='')
        TrainingInstitution.objects.create(name='Lae School of Nursing', type='')
        TrainingInstitution.objects.create(name='APIASETS School of Nursing', type='')
        TrainingInstitution.objects.create(name='Rumginae CHW Training School', type='CHW Training School')
        TrainingInstitution.objects.create(name='Auckland University, New Zealand', type='')
        TrainingInstitution.objects.create(name='2016', type='CHW Training School')

        batch = DataImportBatch.objects.create(source_file_name='test.xlsx', status='completed')
        PracticingLicenseRecord.objects.create(
            batch=batch,
            record_type='workforce_listing',
            target_model='nursingprofessional',
            source_sheet_name='April 2026',
            source_row=1,
            full_name='Jane Doe',
            workplace_address='Port Moresby General Hospital, P O Box 1, Boroko',
        )
        PracticingLicenseRecord.objects.create(
            batch=batch,
            record_type='workforce_listing',
            target_model='nursingprofessional',
            source_sheet_name='April 2026',
            source_row=2,
            full_name='John Doe',
            workplace_address='Port Moresby General Hospital P O Box 1, Boroko',
        )

    def test_reference_breakdown_separates_png_nursing_school_categories(self):
        breakdown = build_reference_breakdown()

        self.assertEqual(breakdown['png_nursing_school_count'], 20)
        self.assertEqual(breakdown['mapped_nursing_reference_count'], 4)
        self.assertEqual(breakdown['chw_training_reference_count'], 1)
        self.assertEqual(breakdown['overseas_institution_reference_count'], 1)
        self.assertEqual(breakdown['legacy_institution_reference_count'], 1)
        self.assertEqual(breakdown['facility_grouped_reference_count'], 1)
        self.assertEqual(breakdown['facility_raw_reference_count'], 2)


class StaffAIProviderModeTests(TestCase):
    def test_staff_ai_defaults_to_local_offline_mode(self):
        user_model = get_user_model()
        user = user_model.objects.create_user(
            username='ai_registrar',
            password='StrongPass123!',
            role='registrar',
            department='Nursing Council',
        )

        status = ai_provider_status()
        response = build_staff_ai_chat_response(user, 'What should I review first today?')

        self.assertIn(status['mode'], {'local', 'local_fallback'})
        self.assertIn('ai_provider', response)
        self.assertIn(response['ai_provider']['mode'], {'local', 'local_fallback'})

    @override_settings(AI_ASSISTANT_PROVIDER='local_llm', AI_ASSISTANT_LOCAL_LLM_ENABLED=False)
    def test_private_llm_requires_explicit_enablement(self):
        status = ai_provider_status()

        self.assertEqual(status['mode'], 'local_fallback')
        self.assertIn('disabled', status['detail'])

    @override_settings(
        AI_ASSISTANT_PROVIDER='ollama',
        AI_ASSISTANT_OLLAMA_ENABLED=True,
        AI_OLLAMA_MODEL='llama3.2:3b',
        AI_OLLAMA_BASE_URL='http://127.0.0.1:11434',
    )
    def test_ollama_can_be_configured_as_free_local_gpt(self):
        status = ai_provider_status()

        self.assertEqual(status['mode'], 'ollama')
        self.assertTrue(status['ollama_ready'])
        self.assertEqual(status['ollama_model'], 'llama3.2:3b')

    @override_settings(
        AI_ASSISTANT_PROVIDER='ollama',
        AI_ASSISTANT_OLLAMA_ENABLED=False,
        AI_OLLAMA_MODEL='llama3.2:3b',
    )
    def test_ollama_falls_back_when_switch_is_disabled(self):
        status = ai_provider_status()

        self.assertEqual(status['mode'], 'local_fallback')
        self.assertIn('disabled', status['detail'])


class NursingCouncilAtpDashboardTests(TestCase):
    def setUp(self):
        cache.clear()
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username='romanah',
            password='StrongPass123!',
            role='registrar',
            department='Nursing Council',
        )
        self.client.force_login(self.user)

        general_batch = DataImportBatch.objects.create(
            source_file_name='2026 Current N-DATA Statistics & Tracking - SECTIONS (Autosaved).xlsx',
            source_kind='ndata_workbook',
            status='completed',
        )
        PracticingLicenseRecord.objects.create(
            batch=general_batch,
            record_type='practicing_license',
            target_model='nursingprofessional',
            source_sheet_name='ATP RECORD 2026',
            source_row=1,
            record_year=2026,
            full_name='General Nurse Example',
            registration_no='GD 100',
            practitioner_number='TBA',
            category='General Nurse',
            workplace_address='Port Moresby General Hospital',
            province='NCD',
        )

        atp_batch = DataImportBatch.objects.create(
            source_file_name='2026 Current ATP-DATA Statistics & Tracking latest.xlsx',
            source_kind='ndata_workbook',
            status='completed',
        )
        PracticingLicenseRecord.objects.create(
            batch=atp_batch,
            record_type='practicing_license',
            target_model='nursingprofessional',
            source_sheet_name='ATP RECORD 2026',
            source_row=1,
            record_year=2026,
            full_name='Alice Public',
            registration_no='GD 200',
            practitioner_number='ATP 1',
            gender='Female',
            category='General Nurse',
            workplace_address='Central Provincial Health Authority, Abau District Hospital',
            province='Central Province',
        )
        PracticingLicenseRecord.objects.create(
            batch=atp_batch,
            record_type='practicing_license',
            target_model='midwife',
            source_sheet_name='ATP RECORD 2026',
            source_row=2,
            record_year=2026,
            full_name='Mary Church',
            registration_no='MW 100',
            practitioner_number='ATP 2',
            gender='Female',
            category='Specialist Midwife',
            workplace_address='St. Mary Mission Hospital',
            province='Gulf Province',
        )
        PracticingLicenseRecord.objects.create(
            batch=atp_batch,
            record_type='practicing_license',
            target_model='nursingprofessional',
            source_sheet_name='ATP RECORD 2024',
            source_row=3,
            record_year=2024,
            full_name='Peter Private',
            registration_no='GD 300',
            practitioner_number='ATP 3',
            gender='Male',
            category='General Nurse',
            workplace_address='2K Medical Centre, Boroko',
            province='NCD',
        )

    def test_nursing_council_portal_shows_scoped_atp_summary(self):
        response = self.client.get(reverse('nursing_council_portal'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Import Current ATP Data')
        self.assertContains(response, 'Authority To Practice Trend by Year')
        self.assertContains(response, 'St. Mary Mission Hospital')
        self.assertEqual(response.context['atp_batch'].source_file_name, '2026 Current ATP-DATA Statistics & Tracking latest.xlsx')
        self.assertEqual(response.context['atp_current_year'], 2026)
        self.assertEqual(response.context['atp_current_person_total'], 2)
        self.assertEqual(response.context['atp_current_public_total'], 1)
        self.assertEqual(response.context['atp_current_church_total'], 1)


class FinanceOfficerAccessTests(TestCase):
    def setUp(self):
        cache.clear()
        user_model = get_user_model()
        self.finance_user = user_model.objects.create_user(
            username='financial_user',
            password='StrongPass123!',
            role='reviewer',
            department='Finance Office',
        )
        self.nursing_professional = NursingProfessional.objects.create(
            first_name='Nursing',
            last_name='Applicant',
            registration_no='NC-1001',
            email='nursing@app.pg',
        )
        self.medical_professional = MedicalDoctor.objects.create(
            first_name='Medical',
            last_name='Doctor',
            registration_no='MD-1001',
            email='medical@app.pg',
        )
        nursing_ct = ContentType.objects.get_for_model(NursingProfessional)
        medical_ct = ContentType.objects.get_for_model(MedicalDoctor)
        self.nursing_application = Application.objects.create(
            content_type=nursing_ct,
            object_id=self.nursing_professional.id,
            form_code='NC3',
            form_title='Nursing Renewal',
            status='approved',
        )
        self.medical_application = Application.objects.create(
            content_type=medical_ct,
            object_id=self.medical_professional.id,
            form_code='MD2',
            form_title='Medical Renewal',
            status='approved',
        )
        Receipt.objects.create(
            user=self.finance_user,
            application=self.nursing_application,
            official_receipt_no='NC-FIN-100',
            amount='150.00',
            status='completed',
            payment_method='office',
        )
        Receipt.objects.create(
            user=self.finance_user,
            application=self.medical_application,
            official_receipt_no='MB-FIN-100',
            amount='275.00',
            status='completed',
            payment_method='office',
        )
        nursing_batch = DataImportBatch.objects.create(
            source_file_name='nursing_finance.xlsx',
            source_kind='nursing_full_registration_2026',
            status='completed',
        )
        medical_batch = DataImportBatch.objects.create(
            source_file_name='medical_finance.xlsx',
            source_kind='medical_board_workbook',
            status='completed',
        )
        PracticingLicenseRecord.objects.create(
            batch=nursing_batch,
            record_type='payment',
            target_model='nursingprofessional',
            source_sheet_name='Nursing Payments',
            source_row=1,
            record_year=2026,
            full_name='Nursing Finance Row',
            payment_date='2026-04-20',
            amount='300.00',
            reference_number='NC-FIN-PAY',
        )
        PracticingLicenseRecord.objects.create(
            batch=medical_batch,
            record_type='payment',
            target_model='medicaldoctor',
            source_sheet_name='Medical Payments',
            source_row=1,
            record_year=2026,
            full_name='Medical Finance Row',
            payment_date='2026-04-25',
            amount='425.00',
            reference_number='MB-FIN-PAY',
        )

    def test_finance_user_default_forecast_is_nursing_only(self):
        self.client.force_login(self.finance_user)

        response = self.client.get(reverse('financial_forecast_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Current scope:</strong> Nursing Council')
        self.assertContains(response, 'NC-FIN-100')
        self.assertContains(response, 'NC-FIN-PAY')
        self.assertNotContains(response, 'MB-FIN-100')
        self.assertNotContains(response, 'MB-FIN-PAY')
        self.assertNotContains(response, 'Combined Manual Receipts')

    def test_finance_user_can_switch_to_medical_forecast_without_nursing_rows(self):
        self.client.force_login(self.finance_user)

        response = self.client.get(reverse('financial_forecast_dashboard') + '?office=medical')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Current scope:</strong> Medical Board')
        self.assertContains(response, 'MB-FIN-100')
        self.assertContains(response, 'MB-FIN-PAY')
        self.assertNotContains(response, 'NC-FIN-100')
        self.assertNotContains(response, 'NC-FIN-PAY')

    def test_finance_user_exports_follow_selected_office(self):
        self.client.force_login(self.finance_user)

        response = self.client.get(reverse('export_financial_forecast_excel') + '?office=medical')

        self.assertEqual(response.status_code, 200)
        self.assertIn('financial_forecast_medical_report.xlsx', response['Content-Disposition'])

    def test_finance_user_navigation_hides_crud_links(self):
        self.client.force_login(self.finance_user)

        response = self.client.get(reverse('financial_forecast_dashboard') + '?office=nursing')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Workforce Flow')
        self.assertContains(response, 'Financial Forecast')
        self.assertNotContains(response, 'Registry Search')
        self.assertNotContains(response, 'Nursing Forms')
        self.assertNotContains(response, 'Bulk Import')
        self.assertNotContains(response, 'Workforce Records')

    def test_finance_user_profile_explains_read_only_and_approval_request(self):
        self.client.force_login(self.finance_user)

        response = self.client.get(reverse('user_profile'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Finance Officer users have read-only finance oversight access')
        self.assertContains(response, 'Request Registrar/System Admin Approval')
        self.assertContains(response, 'Create, update, delete, or upload practitioner')
        self.assertNotContains(response, 'AI Registrar Assistant')

    def test_finance_user_cannot_access_crud_or_search_views(self):
        self.client.force_login(self.finance_user)

        professional_response = self.client.get(reverse('professional_detail', args=[self.nursing_professional.pk]))
        application_response = self.client.get(reverse('application_detail', args=[self.nursing_application.pk]))
        records_response = self.client.get(reverse('records_home'))
        search_response = self.client.get(reverse('dashboard_search') + '?q=Nursing')

        self.assertEqual(professional_response.status_code, 404)
        self.assertEqual(application_response.status_code, 404)
        self.assertEqual(records_response.status_code, 403)
        self.assertRedirects(search_response, reverse('financial_forecast_dashboard'))


class ProductionReadinessDashboardTests(TestCase):
    def setUp(self):
        cache.clear()
        user_model = get_user_model()
        self.admin_user = user_model.objects.create_user(
            username='system_admin',
            password='StrongPass123!',
            role='admin',
            is_superuser=True,
            is_staff=True,
        )
        self.data_quality_user = user_model.objects.create_user(
            username='data_quality_officer',
            password='StrongPass123!',
            role='reviewer',
            department='Data Quality Office',
        )
        self.finance_user = user_model.objects.create_user(
            username='financial_user_readiness',
            password='StrongPass123!',
            role='reviewer',
            department='Finance Office',
        )

        self.batch = DataImportBatch.objects.create(
            source_file_name='readiness.xlsx',
            source_kind='ndata_workbook',
            status='completed',
        )
        self.record = PracticingLicenseRecord.objects.create(
            batch=self.batch,
            record_type='payment',
            target_model='nursingprofessional',
            source_sheet_name='ATP RECORD 2026',
            source_row=5,
            record_year=2026,
            full_name='Future Date Nurse',
            registration_no='NC-READY-1',
            payment_date=timezone.localdate() + timedelta(days=30),
            issued_date='1995-01-01',
        )
        record_ct = ContentType.objects.get_for_model(PracticingLicenseRecord)
        self.review = MissingDataReview.objects.create(
            content_type=record_ct,
            object_id=self.record.pk,
            full_name='Future Date Nurse',
            registration_no='NC-READY-1',
            professional_type='Imported Nursing Record',
            missing_fields=['province', 'institution'],
            missing_count=2,
            severity='high',
            source_label='ATP RECORD 2026',
            source_row=5,
        )
        DuplicateReviewQueue.objects.create(
            content_type=record_ct,
            object_id=self.record.pk,
            suspected_duplicate={
                'target_model': 'nursingprofessional',
                'member_ids': [self.record.pk],
                'identifier_field': 'registration_no',
                'identifier_value': 'NC-READY-1',
            },
            similarity_score=0.98,
        )

    def test_dashboard_shows_remaining_data_issues_and_actions(self):
        self.client.force_login(self.admin_user)

        response = self.client.get(reverse('production_readiness_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Production Readiness Dashboard')
        self.assertContains(response, 'Current scope:</strong> All Regulatory Offices')
        self.assertContains(response, 'Future import payment dates')
        self.assertContains(response, 'Future Date Nurse')
        self.assertContains(response, 'Mark Resolved')
        self.assertContains(response, 'Duplicate Review Backlog')

    def test_data_quality_user_can_update_missing_review_status_with_audit_log(self):
        self.client.force_login(self.data_quality_user)

        response = self.client.post(
            reverse('production_readiness_missing_review_update', args=[self.review.pk]),
            {'status': 'resolved'},
        )

        self.assertRedirects(response, reverse('production_readiness_dashboard'))
        self.review.refresh_from_db()
        self.assertEqual(self.review.status, 'resolved')
        self.assertIsNotNone(self.review.resolved_at)
        self.assertTrue(AuditLog.objects.filter(
            action='MISSING_DATA_REVIEW_STATUS_CHANGED',
            entity_id=str(self.review.pk),
        ).exists())

    def test_finance_user_cannot_access_production_readiness_dashboard(self):
        self.client.force_login(self.finance_user)

        response = self.client.get(reverse('production_readiness_dashboard'))

        self.assertEqual(response.status_code, 404)
