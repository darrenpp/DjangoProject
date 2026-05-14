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
from apps.dashboard.views import _registrar_worker_origin_context
from apps.workforce.models import (
    Application,
    AuditLog,
    Cadre,
    CommunityHealthWorker,
    DataImportBatch,
    EmploymentRecord,
    Facility,
    HealthStudent,
    Location,
    MedicalDoctor,
    MissingDataReview,
    Midwife,
    NurseAide,
    NursingProfessional,
    PostingHistory,
    PracticingLicenseRecord,
    TrainingInstitution,
    WorkforceSnapshot,
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
        TrainingInstitution.objects.create(name='Ackland University, New Zealnd', type='National Institution')
        TrainingInstitution.objects.create(name='Adventist U/Philippine', type='National Institution')
        TrainingInstitution.objects.create(name='America', type='National Institution')
        TrainingInstitution.objects.create(name="St Mary's SON Chitradurga, India", type='National Institution')
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
        self.assertEqual(breakdown['overseas_institution_reference_count'], 5)
        self.assertEqual(breakdown['national_institution_reference_count'], 4)
        self.assertEqual(breakdown['legacy_institution_reference_count'], 1)
        self.assertEqual(breakdown['facility_grouped_reference_count'], 1)
        self.assertEqual(breakdown['facility_raw_reference_count'], 2)

    def test_overall_dashboard_does_not_count_workplace_refs_as_facilities(self):
        user_model = get_user_model()
        user = user_model.objects.create_user(
            username='facility_admin',
            password='StrongPass123!',
            role='admin',
            is_staff=True,
        )
        Application.objects.create(form_code='NC1', status='pending')
        self.client.force_login(user)

        response = self.client.get(reverse('advanced_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['facility_count'], 0)
        self.assertEqual(response.context['provisional_applicant_count'], 1)
        self.assertEqual(response.context['graduand_count'], 1)
        self.assertEqual(response.context['reference_breakdown']['facility_grouped_reference_count'], 1)
        self.assertContains(response, 'Graduands / Provisional Applicants')
        self.assertContains(response, 'Verified Facilities')
        self.assertContains(response, 'Imported workplace references, cleaned names')


class PlatformStandardsAlignmentTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin_user = get_user_model().objects.create_user(
            username='standards_admin',
            password='StrongPass123!',
            role='admin',
            is_superuser=True,
            is_staff=True,
        )

    def test_public_home_shows_government_workforce_standards(self):
        response = self.client.get(reverse('portal_home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Government Health Workforce Registry Standards')
        self.assertContains(response, 'NHWA primary model')
        self.assertContains(response, 'FHIR-ready practitioner roles')
        self.assertContains(response, 'DHIS2/HMIS integration path')
        self.assertContains(response, 'id="page-top"')
        self.assertContains(response, 'data-page-section-navigator')
        self.assertContains(response, 'data-page-scroll="top"')
        self.assertContains(response, 'data-page-scroll="previous"')
        self.assertContains(response, 'data-page-scroll="next"')
        self.assertContains(response, 'data-page-scroll="bottom"')
        self.assertContains(response, 'page-section-navigation.js')

    def test_staff_dashboard_shell_links_to_standards_alignment(self):
        self.client.force_login(self.admin_user)

        response = self.client.get(reverse('advanced_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Government Health Workforce Registry Standards')
        self.assertContains(response, reverse('platform_standards_alignment'))
        self.assertContains(response, 'Standards &amp; Compliance')
        self.assertContains(response, 'id="page-top"')
        self.assertContains(response, 'data-page-section-navigator')
        self.assertContains(response, 'data-page-scroll="top"')
        self.assertContains(response, 'data-page-scroll="previous"')
        self.assertContains(response, 'data-page-scroll="next"')
        self.assertContains(response, 'data-page-scroll="bottom"')
        self.assertContains(response, 'page-section-navigation.js')

    def test_standards_alignment_page_maps_nhwa_hmis_and_fhir(self):
        self.client.force_login(self.admin_user)
        DataImportBatch.objects.create(
            source_file_name='standards-source.xlsx',
            source_kind='ndata_workbook',
            status='completed',
        )
        Facility.objects.create(name='Standards Facility', type='Hospital', ownership='public')
        NursingProfessional.objects.create(
            first_name='Standards',
            last_name='Nurse',
            registration_no='STD-NURSE-1',
        )

        response = self.client.get(reverse('platform_standards_alignment'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'NHWA Alignment Map')
        self.assertContains(response, 'WHO National Health Workforce Accounts handbook')
        self.assertContains(response, 'HL7 FHIR PractitionerRole')
        self.assertContains(response, 'DHIS2 HMIS platform')
        self.assertContains(response, 'Active workforce stock')
        self.assertContains(response, 'Standards Facility', count=0)


class WorkforceFlowImportStatsTests(TestCase):
    def setUp(self):
        cache.clear()
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username='flow_registrar',
            password='StrongPass123!',
            role='registrar',
            department='Nursing Council',
        )
        self.client.force_login(self.user)

    def test_flow_uses_latest_nursing_license_import_when_no_ndata_batch_exists(self):
        current_year = timezone.localdate().year
        atp_batch = DataImportBatch.objects.create(
            source_file_name='2026 Current ATP-DATA Statistics & Tracking latest.xlsx',
            source_kind='ndata_workbook',
            status='completed',
            total_sheets=23,
            processed_sheets=23,
            total_rows=1,
            processed_rows=1,
        )
        atp_batch.started_at = timezone.now() - timedelta(days=1)
        atp_batch.save(update_fields=['started_at'])
        PracticingLicenseRecord.objects.create(
            batch=atp_batch,
            record_type='practicing_license',
            target_model='nursingprofessional',
            source_sheet_name='ATP RECORD 2026',
            source_row=1,
            record_year=current_year,
            full_name='Current Workforce Nurse',
            registration_no='NC-ATP-1',
            gender='Female',
            category='General Nurse',
            province='National Capital District',
            workplace_address='Port Moresby General Hospital, P O Box 1, Boroko',
        )

        batch = DataImportBatch.objects.create(
            source_file_name='Pro and full license continue 2024 - 2025.xlsx',
            source_kind='nursing_license_workbook',
            status='completed',
            total_sheets=2,
            processed_sheets=2,
            total_rows=2,
            processed_rows=2,
        )
        PracticingLicenseRecord.objects.create(
            batch=batch,
            record_type='provisional',
            target_model='nursingprofessional',
            source_sheet_name='PROV REGO',
            source_row=1,
            record_year=current_year,
            full_name='Graduand Applicant',
            registration_no='NC-PROV-1',
        )
        PracticingLicenseRecord.objects.create(
            batch=batch,
            record_type='full',
            target_model='nursingprofessional',
            source_sheet_name='FULL LICENSE',
            source_row=2,
            record_year=current_year + 1,
            full_name='Full Licence Applicant',
            registration_no='NC-FULL-1',
        )

        response = self.client.get(reverse('workforce_flow'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['latest_import_batch'], batch)
        self.assertEqual(response.context['import_record_count'], 2)
        self.assertEqual(response.context['import_latest_year'], current_year)
        self.assertEqual(response.context['flow_labels'], ['Provisional', 'Full/Temporary', 'Renewals', 'Young Workforce'])
        self.assertEqual(response.context['flow_data'][:3], [1, 1, 0])
        self.assertEqual(response.context['import_workplace_source_batch'], atp_batch)
        self.assertEqual(response.context['province_labels'], ['National Capital District'])
        self.assertEqual(response.context['import_gender_labels'], ['Female'])
        self.assertEqual(response.context['import_workplace_rows'][0]['workplace'], 'Port Moresby General Hospital, P O Box 1, Boroko')
        self.assertContains(response, '2</h3><p>Imported Workbook Rows')

    def test_medical_board_flow_uses_medical_import_and_receipts_only(self):
        cache.clear()
        current_year = timezone.localdate().year
        medical_user = get_user_model().objects.create_user(
            username='medical_flow_registrar',
            password='StrongPass123!',
            role='registrar',
            department='Medical Board',
        )
        medical_batch = DataImportBatch.objects.create(
            source_file_name='medical-board.xlsx',
            source_kind='medical_board_workbook',
            status='completed',
            total_sheets=1,
            processed_sheets=1,
            total_rows=3,
            processed_rows=3,
        )
        medical_batch.sheets.create(
            sheet_name='CHW',
            sheet_type='medical_board_chw',
            status='completed',
            imported_rows=3,
        )
        PracticingLicenseRecord.objects.create(
            batch=medical_batch,
            record_type='full',
            target_model='medicaldoctor',
            source_sheet_name='CHW',
            source_row=1,
            record_year=current_year,
            full_name='Medical Doctor One',
            registration_no='MD-FLOW-1',
            gender='Male',
            category='Medical Doctor',
            province='National Capital District',
            workplace_address='Medical Board Clinic',
        )
        PracticingLicenseRecord.objects.create(
            batch=medical_batch,
            record_type='workforce_listing',
            target_model='communityhealthworker',
            source_sheet_name='CHW',
            source_row=2,
            record_year=current_year,
            full_name='Community Health Worker One',
            registration_no='CHW-FLOW-1',
            gender='Female',
            category='Community Health Worker',
            province='Morobe Province',
            workplace_address='Medical Board Clinic',
        )
        PracticingLicenseRecord.objects.create(
            batch=medical_batch,
            record_type='practicing_license',
            target_model='communityhealthworker',
            source_sheet_name='CHW',
            source_row=3,
            record_year=current_year,
            full_name='Community Health Worker One',
            registration_no='CHW-FLOW-1',
            gender='Female',
            category='Community Health Worker',
            province='Morobe Province',
            workplace_address='Medical Board Clinic',
        )

        nursing_batch = DataImportBatch.objects.create(
            source_file_name='nursing-latest.xlsx',
            source_kind='ndata_workbook',
            status='completed',
            total_sheets=1,
            processed_sheets=1,
            total_rows=1,
            processed_rows=1,
        )
        nursing_batch.started_at = timezone.now() + timedelta(days=1)
        nursing_batch.save(update_fields=['started_at'])
        nursing_batch.sheets.create(
            sheet_name='PROV REGO',
            sheet_type='provisional',
            status='completed',
            imported_rows=1,
        )
        PracticingLicenseRecord.objects.create(
            batch=nursing_batch,
            record_type='provisional',
            target_model='nursingprofessional',
            source_sheet_name='PROV REGO',
            source_row=1,
            record_year=current_year,
            full_name='Nursing Applicant One',
            registration_no='NC-FLOW-1',
            workplace_address='Nursing Council Hospital',
        )

        medical_application = Application.objects.create(form_code='MD2', pathway='medical_board', status='pending')
        nursing_application = Application.objects.create(form_code='NC3', pathway='other', status='pending')
        Receipt.objects.create(
            user=medical_user,
            application=medical_application,
            receipt_number='MB-FLOW-RCT',
            amount='100.00',
            status='completed',
        )
        Receipt.objects.create(
            user=self.user,
            application=nursing_application,
            receipt_number='NC-FLOW-RCT',
            amount='50.00',
            status='pending',
        )

        self.client.force_login(medical_user)
        response = self.client.get(reverse('workforce_flow'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['dashboard_scope'], 'medical')
        self.assertEqual(response.context['latest_import_batch'], medical_batch)
        self.assertEqual(response.context['import_record_count'], 3)
        self.assertEqual(response.context['flow_labels'], ['Medical Doctors', 'Community Health Workers', 'Allied Health', 'Practising Licences'])
        self.assertEqual(response.context['flow_data'], [1, 1, 0, 1])
        self.assertEqual(response.context['receipt_completed_count'], 1)
        self.assertEqual(response.context['receipt_pending_count'], 0)
        self.assertEqual(response.context['latest_import_sheets'][0].sheet_name, 'CHW')
        self.assertEqual(response.context['import_workplace_rows'][0]['workplace'], 'Medical Board Clinic')
        self.assertEqual(response.context['workforce_flow_title'], 'Medical Board Workforce Flow & Planning')
        self.assertContains(response, 'Imported Medical Board Rows')
        self.assertContains(response, 'CHW')
        self.assertNotContains(response, 'PROV REGO')
        self.assertNotContains(response, 'Nursing Council Hospital')


class RegistrarIndividualRecordsTests(TestCase):
    def setUp(self):
        cache.clear()
        user_model = get_user_model()
        self.nursing_registrar = user_model.objects.create_user(
            username='individual_nursing_registrar',
            password='StrongPass123!',
            role='registrar',
            department='Nursing Council',
        )
        self.medical_registrar = user_model.objects.create_user(
            username='individual_medical_registrar',
            password='StrongPass123!',
            role='registrar',
            department='Medical Board',
        )
        self.admin = user_model.objects.create_user(
            username='individual_admin',
            password='StrongPass123!',
            role='admin',
            is_superuser=True,
            is_staff=True,
        )

    def test_individual_records_show_national_overseas_employment_and_facility_details(self):
        current_year = timezone.localdate().year
        batch = DataImportBatch.objects.create(
            source_file_name='nursing-individuals.xlsx',
            source_kind='nursing_license_workbook',
            status='completed',
            total_rows=2,
            processed_rows=2,
        )
        PracticingLicenseRecord.objects.create(
            batch=batch,
            record_type='full',
            target_model='nursingprofessional',
            source_sheet_name='FULL',
            source_row=1,
            record_year=current_year,
            full_name='National Source Nurse',
            registration_no='NC-IND-1',
            applicant_type='national',
            nationality='Papua New Guinea',
            institution_name='Lae School of Nursing',
            workplace_address='Port Moresby General Hospital, P O Box 1, Boroko',
            province='NCD',
        )
        PracticingLicenseRecord.objects.create(
            batch=batch,
            record_type='temporary',
            target_model='nursingprofessional',
            source_sheet_name='TEMP',
            source_row=2,
            record_year=current_year,
            full_name='Overseas Source Nurse',
            registration_no='NC-IND-2',
            applicant_type='overseas',
            nationality='Fiji',
            institution_name='Fiji Nursing School',
            workplace_address='Kundiawa General Hospital',
            province='Simbu',
        )
        live_nurse = NursingProfessional.objects.create(
            first_name='Live',
            last_name='Facility Nurse',
            registration_no='NC-LIVE-1',
            applicant_type='national',
            nationality='Papua New Guinea',
            province='Morobe',
        )
        content_type = ContentType.objects.get_for_model(NursingProfessional)
        EmploymentRecord.objects.create(
            content_type=content_type,
            object_id=live_nurse.pk,
            employer_name='Angau Hospital',
            position_held='Registered Nurse',
            employment_status='full_time',
            area_of_employment='government',
            place_of_work='ANGAU Memorial Hospital',
        )
        location = Location.objects.create(province='Morobe', district='Lae')
        facility = Facility.objects.create(
            name='ANGAU Memorial Hospital',
            type='Hospital',
            ownership='public',
            location=location,
        )
        PostingHistory.objects.create(
            content_type=content_type,
            object_id=live_nurse.pk,
            facility=facility,
            position_title='Ward Nurse',
            start_date=timezone.localdate(),
            is_current=True,
        )

        self.client.force_login(self.admin)
        response = self.client.get(reverse('registrar_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(response.context['registrar_worker_origin_summary']['national_total'], 2)
        self.assertGreaterEqual(response.context['registrar_worker_origin_summary']['overseas_total'], 1)
        self.assertContains(response, 'National and Overseas Workers')
        self.assertContains(response, 'National Individuals')
        self.assertContains(response, 'Overseas Individuals')
        self.assertContains(response, 'National Source Nurse')
        self.assertContains(response, 'Overseas Source Nurse')
        self.assertContains(response, 'Fiji Nursing School')
        self.assertContains(response, 'ANGAU Memorial Hospital')
        self.assertContains(response, 'Incoming - registration')

    def test_medical_registrar_scope_excludes_nursing_individual_records(self):
        current_year = timezone.localdate().year
        nursing_batch = DataImportBatch.objects.create(
            source_file_name='nursing-source.xlsx',
            source_kind='nursing_license_workbook',
            status='completed',
        )
        medical_batch = DataImportBatch.objects.create(
            source_file_name='medical-source.xlsx',
            source_kind='medical_board_workbook',
            status='completed',
        )
        PracticingLicenseRecord.objects.create(
            batch=nursing_batch,
            record_type='full',
            target_model='nursingprofessional',
            source_sheet_name='NC',
            source_row=1,
            record_year=current_year,
            full_name='Nursing Scoped Person',
            registration_no='NC-SCOPE-IND',
            applicant_type='national',
        )
        PracticingLicenseRecord.objects.create(
            batch=medical_batch,
            record_type='full',
            target_model='medicaldoctor',
            source_sheet_name='MB',
            source_row=1,
            record_year=current_year,
            full_name='Medical Scoped Person',
            registration_no='MD-SCOPE-IND',
            applicant_type='national',
        )

        cache.clear()
        context = _registrar_worker_origin_context(self.medical_registrar)
        names = {row['name'] for row in context['registrar_worker_origin_rows']}

        self.assertEqual(context['registrar_origin_scope'], 'medical')
        self.assertIn('Medical Scoped Person', names)
        self.assertNotIn('Nursing Scoped Person', names)

    def test_frequent_nursing_records_drilldown_shows_individuals_and_edit_actions(self):
        current_year = timezone.localdate().year
        batch = DataImportBatch.objects.create(
            source_file_name='2026 ATP current.xlsx',
            source_kind='ndata_workbook',
            status='completed',
        )
        valid_record = PracticingLicenseRecord.objects.create(
            batch=batch,
            record_type='practicing_license',
            target_model='nursingprofessional',
            source_sheet_name='ATP',
            source_row=10,
            record_year=current_year,
            full_name='Valid General Nurse',
            registration_no='ATP-GN-1',
            category='General Nurse',
            workplace_address='Western Provincial Health Authority',
            province='Western Province',
            payment_date=timezone.localdate(),
        )
        review_record = PracticingLicenseRecord.objects.create(
            batch=batch,
            record_type='practicing_license',
            target_model='nursingprofessional',
            source_sheet_name='ATP',
            source_row=11,
            record_year=current_year,
            full_name='Review General Nurse',
            registration_no='ATP-GN-2',
            category='General Nurse',
            workplace_address='Paradise Private Hospital',
            province='National Capital District',
            payment_date=timezone.localdate(),
        )
        typo_record = PracticingLicenseRecord.objects.create(
            batch=batch,
            record_type='practicing_license',
            target_model='nursingprofessional',
            source_sheet_name='ATP',
            source_row=12,
            record_year=current_year,
            full_name='Typo Category Nurse',
            registration_no='ATP-TYPO-1',
            category='Specialsit Midwife',
            workplace_address='Unknown Aid Post',
            province='Madang Province',
            payment_date=timezone.localdate(),
        )
        MissingDataReview.objects.create(
            content_type=ContentType.objects.get_for_model(PracticingLicenseRecord),
            object_id=review_record.pk,
            full_name=review_record.full_name,
            registration_no=review_record.registration_no,
            professional_type='Practicing License Record',
            missing_fields=['Province needs verification'],
            missing_count=1,
            source_label=review_record.source_sheet_name,
            source_row=review_record.source_row,
            severity='low',
        )

        self.client.force_login(self.nursing_registrar)
        response = self.client.get(reverse('nursing_frequent_records'), {'category': 'General Nurse'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['record_total'], 2)
        self.assertContains(response, 'Valid General Nurse')
        self.assertContains(response, 'Review General Nurse')
        self.assertNotContains(response, 'Typo Category Nurse')
        self.assertContains(response, reverse('record_update', args=['practicinglicenserecord', valid_record.pk]))
        self.assertContains(response, 'Validity')
        self.assertContains(response, 'Needs review')

        response = self.client.get(reverse('nursing_frequent_records'), {'category_review': '1'})
        self.assertEqual(response.context['record_total'], 1)
        self.assertContains(response, typo_record.full_name)
        self.assertContains(response, 'Category label is not in the standard registrar list')

        response = self.client.get(reverse('nursing_frequent_records'), {'facility_group': 'private'})
        self.assertEqual(response.context['record_total'], 1)
        self.assertContains(response, review_record.full_name)
        self.assertNotContains(response, valid_record.full_name)

    def test_data_quality_reviews_table_uses_server_side_datatable(self):
        current_year = timezone.localdate().year
        payment_date = timezone.localdate()
        batch = DataImportBatch.objects.create(
            source_file_name='quality-review-atp.xlsx',
            source_kind='ndata_workbook',
            status='completed',
        )
        record = PracticingLicenseRecord.objects.create(
            batch=batch,
            record_type='practicing_license',
            target_model='nursingprofessional',
            source_sheet_name='ATP QUALITY',
            source_row=21,
            record_year=current_year,
            full_name='Quality Table Nurse',
            registration_no='NC-QUALITY-1',
            category='General Nurse',
            payment_date=payment_date,
        )
        MissingDataReview.objects.create(
            content_type=ContentType.objects.get_for_model(PracticingLicenseRecord),
            object_id=record.pk,
            full_name=record.full_name,
            registration_no=record.registration_no,
            professional_type='Practicing License Record',
            missing_fields=['Suspected misinformation in workplace facility'],
            missing_count=1,
            source_label=record.source_sheet_name,
            source_row=record.source_row,
            severity='high',
        )

        self.client.force_login(self.nursing_registrar)
        portal_response = self.client.get(reverse('nursing_council_portal'))
        self.assertContains(portal_response, 'data-quality-review-datatable')
        self.assertContains(portal_response, 'data-server-side="1"')
        self.assertContains(portal_response, reverse('data_quality_reviews_table'))

        response = self.client.get(reverse('data_quality_reviews_table'), {
            'draw': '3',
            'start': '0',
            'length': '10',
            'search[value]': 'Quality Table Nurse',
            'order[0][column]': '0',
            'order[0][dir]': 'desc',
        })

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['draw'], 3)
        self.assertEqual(payload['recordsTotal'], 1)
        self.assertEqual(payload['recordsFiltered'], 1)
        self.assertEqual(len(payload['data']), 1)
        row = payload['data'][0]
        self.assertEqual(row['source_year'], current_year)
        self.assertEqual(row['recent_date'], payment_date.strftime('%d %b %Y'))
        self.assertIn('Quality Table Nurse', row['name'])
        self.assertIn('Suspected misinformation', row['issues'])
        self.assertIn('ATP QUALITY, row 21', row['source'])
        self.assertIn('badge-danger', row['severity'])
        self.assertIn(reverse('record_update', args=['practicinglicenserecord', record.pk]), row['actions'])

    def test_nursing_council_portal_has_shortcut_links_to_key_sections(self):
        current_year = timezone.localdate().year
        batch = DataImportBatch.objects.create(
            source_file_name='shortcut-atp.xlsx',
            source_kind='ndata_workbook',
            status='completed',
        )
        record = PracticingLicenseRecord.objects.create(
            batch=batch,
            record_type='practicing_license',
            target_model='nursingprofessional',
            source_sheet_name='ATP SHORTCUT',
            source_row=1,
            record_year=current_year,
            full_name='Shortcut Nurse',
            registration_no='NC-SHORTCUT-1',
            category='General Nurse',
            payment_date=timezone.localdate(),
        )
        MissingDataReview.objects.create(
            content_type=ContentType.objects.get_for_model(PracticingLicenseRecord),
            object_id=record.pk,
            full_name=record.full_name,
            registration_no=record.registration_no,
            professional_type='Practicing License Record',
            missing_fields=['Facility needs verification'],
            missing_count=1,
            severity='medium',
        )

        self.client.force_login(self.nursing_registrar)
        response = self.client.get(reverse('nursing_council_portal'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Dashboard Shortcuts')
        for anchor in [
            'nursing-summary',
            'institution-facility-breakdown',
            'registrar-worker-origin-table',
            'nursing-operations',
            'workflow-pathways',
            'missing-data-reviews',
            'atp-current-summary',
            'frequent-nursing-totals',
            'atp-charts',
            'atp-workplace-breakdown',
            'current-atp-records',
            'workforce-flow',
            'provisional-licence-tracking',
            'recent-nursing-applications',
            'nursing-statistics',
        ]:
            self.assertContains(response, f'href="#{anchor}"')
            self.assertContains(response, f'id="{anchor}"')


class MedicalBoardScreenScopeTests(TestCase):
    def setUp(self):
        cache.clear()
        user_model = get_user_model()
        self.medical_user = user_model.objects.create_user(
            username='medical_scope_registrar',
            password='StrongPass123!',
            role='registrar',
            department='Medical Board',
        )
        Cadre.objects.create(name='Nursing', category='nursing')
        Cadre.objects.create(name='Midwifery', category='midwifery')
        Cadre.objects.create(name='Community Health Worker', category='chw')
        TrainingInstitution.objects.create(name='Lae School of Nursing', type='Nursing School')
        TrainingInstitution.objects.create(name='CHW Training College', type='CHW Training School')
        CommunityHealthWorker.objects.create(
            first_name='Medical',
            last_name='CHW',
            registration_no='CHW-SCOPE-1',
            email='chw.scope@example.test',
        )
        NursingProfessional.objects.create(
            first_name='Nursing',
            last_name='Professional',
            registration_no='NC-SCOPE-1',
            email='nurse.scope@example.test',
        )
        Midwife.objects.create(
            first_name='Nursing',
            last_name='Midwife',
            registration_no='MW-SCOPE-1',
            email='midwife.scope@example.test',
        )
        NurseAide.objects.create(
            first_name='Nursing',
            last_name='Aide',
            registration_no='NA-SCOPE-1',
            email='aide.scope@example.test',
        )
        HealthStudent.objects.create(
            first_name='Nursing',
            last_name='Graduand',
            registration_no='HS-SCOPE-1',
            email='graduand.scope@example.test',
            program='Nursing',
        )

    def test_medical_board_overall_dashboard_hides_nursing_council_sections(self):
        self.client.force_login(self.medical_user)

        response = self.client.get(reverse('advanced_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['dashboard_scope'], 'medical')
        self.assertContains(response, 'Medical Board Dashboard')
        self.assertContains(response, 'Community Health Workers')
        self.assertContains(response, 'Medical Training Institutions')
        self.assertNotContains(response, 'Nursing Professionals')
        self.assertNotContains(response, 'Midwives')
        self.assertNotContains(response, 'Nurse Aides')
        self.assertNotContains(response, 'Graduands / Provisional Applicants')
        self.assertNotContains(response, 'PNG Nursing Schools')
        self.assertNotContains(response, 'Training Institution Breakdown')
        self.assertNotContains(response, 'Lae School of Nursing')

    def test_medical_board_workforce_flow_uses_live_medical_total_without_global_snapshot(self):
        WorkforceSnapshot.objects.create(year=2026, total_active_workers=1661)
        self.client.force_login(self.medical_user)

        response = self.client.get(reverse('workforce_flow'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['dashboard_scope'], 'medical')
        self.assertEqual(response.context['tracked_workforce_count'], 1)
        self.assertEqual(response.context['total_workers_by_year'], [1])
        self.assertContains(response, 'Imported Medical Board Rows')
        self.assertNotContains(response, 'Reference Tables')
        self.assertNotContains(response, 'Training Institutions')

    def test_medical_board_portal_separates_specialists_chw_licences_and_missing_reviews(self):
        current_year = timezone.localdate().year
        doctor = MedicalDoctor.objects.create(
            first_name='Medical',
            last_name='Generalist',
            registration_no='MD-SCOPE-1',
            specialty='Overseas Medical Board Practitioner',
        )
        specialist = MedicalDoctor.objects.create(
            first_name='Medical',
            last_name='Specialist',
            registration_no='MD-SCOPE-2',
            specialty='',
        )
        chw_batch = DataImportBatch.objects.create(
            source_file_name='chw.xlsx',
            source_kind='medical_board_workbook',
            status='completed',
        )
        chw_batch.started_at = timezone.now() - timedelta(days=2)
        chw_batch.save(update_fields=['started_at'])
        PracticingLicenseRecord.objects.create(
            batch=chw_batch,
            record_type='practicing_license',
            target_model='communityhealthworker',
            source_sheet_name='CHW ATP',
            source_row=1,
            record_year=current_year,
            full_name='Medical CHW',
            registration_no='CHW-SCOPE-1',
        )
        latest_medical_batch = DataImportBatch.objects.create(
            source_file_name='legacy.xlsx',
            source_kind='medical_board_workbook',
            status='completed',
        )
        latest_medical_batch.started_at = timezone.now()
        latest_medical_batch.save(update_fields=['started_at'])
        PracticingLicenseRecord.objects.create(
            batch=latest_medical_batch,
            record_type='workforce_listing',
            target_model='medicaldoctor',
            source_sheet_name='ALL OVERSEAS MEMBERS MB',
            source_row=1,
            record_year=current_year,
            full_name='Medical Generalist',
            registration_no=doctor.registration_no,
            qualification_name='MBBS',
        )
        specialist_record = PracticingLicenseRecord.objects.create(
            batch=latest_medical_batch,
            record_type='workforce_listing',
            target_model='medicaldoctor',
            source_sheet_name='ALL OVERSEAS MEMBERS MB',
            source_row=2,
            record_year=current_year,
            full_name='Medical Specialist',
            registration_no=specialist.registration_no,
            qualification_name='SPECIALIST (MP/DP/AHW)',
        )
        MissingDataReview.objects.create(
            content_type=ContentType.objects.get_for_model(CommunityHealthWorker),
            object_id=self._get_chw().pk,
            full_name='Medical CHW',
            professional_type='Community Health Worker',
            missing_fields=['Email address'] * 5,
            missing_count=5,
            severity='high',
        )
        MissingDataReview.objects.create(
            content_type=ContentType.objects.get_for_model(PracticingLicenseRecord),
            object_id=specialist_record.pk,
            full_name='Medical Specialist',
            professional_type='Practicing License Record',
            missing_fields=['Payment date'],
            missing_count=1,
            severity='low',
        )
        self.client.force_login(self.medical_user)

        response = self.client.get(reverse('medical_board_portal'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['medical_doctor_count'], 2)
        self.assertEqual(response.context['medical_specialist_count'], 1)
        self.assertEqual(response.context['medical_chw_practicing_total'], 1)
        self.assertEqual(response.context['missing_data_review_count'], 2)
        self.assertEqual(response.context['high_priority_missing_data_count'], 1)

    def _get_chw(self):
        return CommunityHealthWorker.objects.get(registration_no='CHW-SCOPE-1')

    def test_medical_board_fee_structure_hides_nursing_fee_sections(self):
        self.client.force_login(self.medical_user)

        response = self.client.get(reverse('fee_structure'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['fee_scope'], 'medical')
        self.assertContains(response, 'PAPUA NEW GUINEA MEDICAL BOARD')
        self.assertContains(response, 'Medical Board Fees')
        self.assertContains(response, 'Community Health Worker Fees')
        self.assertNotContains(response, 'PAPUA NEW GUINEA NURSING COUNCIL')
        self.assertNotContains(response, 'Renewals for Nurse Aides')
        self.assertNotContains(response, 'Category: C Nursing Council Other Fees')
        self.assertNotContains(response, 'Graduand Registration Fees')


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
