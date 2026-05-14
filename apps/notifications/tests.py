from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from apps.common.models import DuplicateReviewQueue
from apps.dashboard.models import Receipt
from apps.documents.models import Document, DocumentFolder
from apps.notifications.models import EnquiryThread
from apps.workforce.models import (
    Application,
    CommunityHealthWorker,
    DataImportBatch,
    MedicalDoctor,
    MissingDataReview,
    NursingProfessional,
    PracticingLicenseRecord,
)


class StaffCommunicationsTests(TestCase):
    def setUp(self):
        cache.clear()
        user_model = get_user_model()
        self.registrar = user_model.objects.create_user(
            username="registrar.nursing",
            password="testpass123",
            role="registrar",
            department="Nursing Council",
        )
        self.applicant = user_model.objects.create_user(
            username="nurse.user",
            password="testpass123",
            role="nurse",
            email="nurse@example.com",
        )
        self.medical_registrar = user_model.objects.create_user(
            username="registrar.medical",
            password="testpass123",
            role="registrar",
            department="Medical Board",
        )
        self.admin_user = user_model.objects.create_user(
            username="platform.admin",
            password="testpass123",
            role="admin",
            department="Administration",
        )

        self.nursing_professional = NursingProfessional.objects.create(
            first_name="Nursing",
            last_name="Applicant",
            registration_no="NC-1001",
            email="nursing@app.pg",
        )
        self.medical_professional = MedicalDoctor.objects.create(
            first_name="Medical",
            last_name="Doctor",
            registration_no="MD-1001",
            email="medical@app.pg",
        )

        nursing_ct = ContentType.objects.get_for_model(NursingProfessional)
        medical_ct = ContentType.objects.get_for_model(MedicalDoctor)
        Application.objects.create(
            content_type=nursing_ct,
            object_id=self.nursing_professional.id,
            form_code="NC2",
            form_title="Nursing Full Licence",
            status="pending",
        )
        Application.objects.create(
            content_type=medical_ct,
            object_id=self.medical_professional.id,
            form_code="MD1",
            form_title="Medical Registration",
            status="pending",
        )
        self.nursing_application = Application.objects.create(
            content_type=nursing_ct,
            object_id=self.nursing_professional.id,
            form_code="NC3",
            form_title="Nursing Renewal",
            status="approved",
        )
        self.medical_application = Application.objects.create(
            content_type=medical_ct,
            object_id=self.medical_professional.id,
            form_code="MD2",
            form_title="Medical Renewal",
            status="approved",
        )

        Receipt.objects.create(
            user=self.registrar,
            application=self.nursing_application,
            official_receipt_no="NC-REC-100",
            amount="150.00",
            status="completed",
            payment_method="office",
        )
        Receipt.objects.create(
            user=self.medical_registrar,
            application=self.medical_application,
            official_receipt_no="MB-REC-100",
            amount="275.00",
            status="completed",
            payment_method="office",
        )

        nursing_folder = DocumentFolder.objects.create(
            office_scope="nursing",
            name="Nursing Queue",
        )
        medical_folder = DocumentFolder.objects.create(
            office_scope="medical",
            name="Medical Queue",
        )
        Document.objects.create(
            office_scope="nursing",
            title="Nursing Draft Document",
            folder=nursing_folder,
            status="draft",
        )
        Document.objects.create(
            office_scope="medical",
            title="Medical Draft Document",
            folder=medical_folder,
            status="draft",
        )

        EnquiryThread.objects.create(
            subject="Nursing Follow Up",
            office="nursing",
            created_by=self.registrar,
            status="open",
        )
        EnquiryThread.objects.create(
            subject="Medical Follow Up",
            office="medical",
            created_by=self.applicant,
            status="open",
        )

        self.import_batch = DataImportBatch.objects.create(
            source_file_name="duplicate_scope_test.xlsx",
            source_kind="nursing_full_registration_2026",
            status="completed",
        )
        self.medical_import_batch = DataImportBatch.objects.create(
            source_file_name="medical_finance_scope_test.xlsx",
            source_kind="medical_board_workbook",
            status="completed",
        )
        self.nursing_duplicate_record = PracticingLicenseRecord.objects.create(
            batch=self.import_batch,
            record_type="full",
            target_model="midwife",
            source_sheet_name="April 2026",
            source_row=10,
            record_year=2026,
            full_name="Anna Duplicate",
            registration_no="MID-100",
            practitioner_number="LIC-100",
        )
        self.medical_duplicate_record = PracticingLicenseRecord.objects.create(
            batch=self.import_batch,
            record_type="practicing_license",
            target_model="communityhealthworker",
            source_sheet_name="Medical CHW",
            source_row=20,
            record_year=2026,
            full_name="Brian Duplicate",
            registration_no="CHW-100",
            practitioner_number="ML-100",
        )
        self.nursing_duplicate_review = DuplicateReviewQueue.objects.create(
            content_type=ContentType.objects.get_for_model(PracticingLicenseRecord),
            object_id=self.nursing_duplicate_record.id,
            suspected_duplicate={
                "audit_type": "same_name_same_registration_no_same_year_type",
                "target_model": "midwife",
                "record_type": "full",
                "record_year": 2026,
                "full_name": "Anna Duplicate",
                "identifier_field": "registration_no",
                "identifier_value": "MID-100",
                "member_ids": [self.nursing_duplicate_record.id],
                "member_count": 1,
            },
            similarity_score=1.0,
        )

        PracticingLicenseRecord.objects.create(
            batch=self.import_batch,
            record_type="payment",
            target_model="other",
            source_sheet_name="Nursing Payments",
            source_row=30,
            record_year=2026,
            full_name="Nursing Finance Row",
            payment_date="2026-04-20",
            amount="300.00",
            reference_number="NC-PAY-1",
            payment_method="Imported ATP Payment",
        )
        PracticingLicenseRecord.objects.create(
            batch=self.medical_import_batch,
            record_type="payment",
            target_model="communityhealthworker",
            source_sheet_name="Medical Payments",
            source_row=40,
            record_year=2026,
            full_name="Medical Finance Row",
            payment_date="2026-04-25",
            amount="425.00",
            reference_number="MB-PAY-1",
            payment_method="Imported Medical Payment",
        )
        self.medical_duplicate_review = DuplicateReviewQueue.objects.create(
            content_type=ContentType.objects.get_for_model(PracticingLicenseRecord),
            object_id=self.medical_duplicate_record.id,
            suspected_duplicate={
                "audit_type": "same_name_same_practitioner_no_same_year_type",
                "target_model": "communityhealthworker",
                "record_type": "practicing_license",
                "record_year": 2026,
                "full_name": "Brian Duplicate",
                "identifier_field": "practitioner_number",
                "identifier_value": "ML-100",
                "member_ids": [self.medical_duplicate_record.id],
                "member_count": 1,
            },
            similarity_score=1.0,
        )

    def test_staff_communications_is_scoped_for_nursing_registrar(self):
        self.client.force_login(self.registrar)
        response = self.client.get(reverse("staff_communications"))

        self.assertEqual(response.status_code, 200)
        summary = response.context["staff_summary"]
        self.assertEqual(summary["pending_application_count"], 1)
        self.assertEqual(summary["document_review_count"], 1)
        self.assertEqual(summary["open_thread_count"], 1)

    def test_profile_shows_staff_queue_panel_for_registrar(self):
        self.client.force_login(self.registrar)
        response = self.client.get(reverse("user_profile"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Inbox, Chat & Review Queue")
        self.assertContains(response, "Open Communications Hub")
        self.assertContains(response, "Statutory Context and Mandate of the PNG Nursing Council")
        self.assertContains(response, "AI Registrar Assistant")
        self.assertContains(response, "Monthly Excel Report")
        self.assertContains(response, "Yearly PDF Report")
        self.assertContains(response, "Minister Brief")

    def test_profile_hides_nursing_regulatory_alignment_for_medical_registrar(self):
        self.client.force_login(self.medical_registrar)
        response = self.client.get(reverse("user_profile"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Statutory Context and Mandate of the PNG Nursing Council")

    def test_medical_registrar_profile_counts_medical_board_missing_reviews(self):
        chw = CommunityHealthWorker.objects.create(
            first_name="Medical",
            last_name="CHW",
            registration_no="CHW-MISSING-1",
        )
        MissingDataReview.objects.create(
            content_type=ContentType.objects.get_for_model(CommunityHealthWorker),
            object_id=chw.pk,
            full_name="Medical CHW",
            registration_no="CHW-MISSING-1",
            professional_type="Community Health Worker",
            missing_fields=["Email address", "Phone number"],
            missing_count=2,
        )
        MissingDataReview.objects.create(
            content_type=ContentType.objects.get_for_model(NursingProfessional),
            object_id=self.nursing_professional.pk,
            full_name="Nursing Applicant",
            registration_no="NC-1001",
            professional_type="Nursing Professional",
            missing_fields=["Email address"],
            missing_count=1,
        )
        self.client.force_login(self.medical_registrar)

        response = self.client.get(reverse("user_profile"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["staff_ai_context"]["missing_review_count"], 1)
        self.assertContains(response, "Missing Data Reviews")

    def test_profile_hides_nursing_regulatory_alignment_for_admin(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("user_profile"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Statutory Context and Mandate of the PNG Nursing Council")
        self.assertContains(response, "AI Registrar Assistant")

    def test_profile_hides_staff_ai_controls_for_applicant(self):
        self.client.force_login(self.applicant)
        response = self.client.get(reverse("user_profile"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "AI Registrar Assistant")

    def test_staff_communications_redirects_non_staff_user(self):
        self.client.force_login(self.applicant)
        response = self.client.get(reverse("staff_communications"))

        self.assertEqual(response.status_code, 302)

    def test_staff_ai_assistant_is_available_to_registrar(self):
        self.client.force_login(self.registrar)
        response = self.client.get(reverse("staff_ai_assistant"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Applicant Screening Queue")
        self.assertContains(response, "Staff AI Chat")
        self.assertContains(response, "Duplicate Review Workflow")

    def test_staff_ai_assistant_redirects_non_staff_user(self):
        self.client.force_login(self.applicant)
        response = self.client.get(reverse("staff_ai_assistant"))

        self.assertEqual(response.status_code, 302)

    def test_helpdesk_redirects_staff_user_to_staff_ai_assistant(self):
        self.client.force_login(self.registrar)
        response = self.client.get(reverse("helpdesk"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("staff_ai_assistant"))

    def test_helpdesk_stays_available_for_applicant(self):
        self.client.force_login(self.applicant)
        response = self.client.get(reverse("helpdesk"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "AI Helpdesk")

    def test_import_page_redirects_non_staff_user(self):
        self.client.force_login(self.applicant)
        response = self.client.get(reverse("import_data"))

        self.assertEqual(response.status_code, 302)

    def test_nursing_regulatory_alignment_page_is_available_to_nursing_registrar(self):
        self.client.force_login(self.registrar)
        response = self.client.get(reverse("nursing_regulatory_alignment"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Document-To-Database Comparison Summary")

    def test_nursing_regulatory_alignment_page_redirects_medical_registrar(self):
        self.client.force_login(self.medical_registrar)
        response = self.client.get(reverse("nursing_regulatory_alignment"))

        self.assertEqual(response.status_code, 302)

    def test_duplicate_review_workflow_is_scoped_for_nursing_registrar(self):
        self.client.force_login(self.registrar)
        response = self.client.get(reverse("duplicate_review_workflow"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Anna Duplicate")
        self.assertNotContains(response, "Brian Duplicate")

    def test_duplicate_review_workflow_is_scoped_for_medical_registrar(self):
        self.client.force_login(self.medical_registrar)
        response = self.client.get(reverse("duplicate_review_workflow"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Brian Duplicate")
        self.assertNotContains(response, "Anna Duplicate")

    def test_duplicate_review_update_marks_case_reviewed(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.registrar)
        csrf_client.get(reverse("duplicate_review_workflow"))
        csrf_token = csrf_client.cookies["csrftoken"].value

        response = csrf_client.post(
            reverse("duplicate_review_update", args=[self.nursing_duplicate_review.id]),
            {"action": "reviewed", "next": reverse("duplicate_review_workflow")},
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, 302)
        self.nursing_duplicate_review.refresh_from_db()
        self.assertEqual(self.nursing_duplicate_review.status, "reviewed")
        self.assertEqual(self.nursing_duplicate_review.reviewed_by, self.registrar)

    def test_financial_forecast_is_scoped_for_nursing_registrar(self):
        self.client.force_login(self.registrar)
        response = self.client.get(reverse("financial_forecast_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nursing Council")
        self.assertContains(response, "NC-REC-100")
        self.assertNotContains(response, "MB-REC-100")
        self.assertNotContains(response, "MB-PAY-1")

    def test_financial_forecast_export_excel_is_available_to_registrar(self):
        self.client.force_login(self.registrar)
        response = self.client.get(reverse("export_financial_forecast_excel"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def test_helpdesk_api_requires_csrf_token(self):
        csrf_client = Client(enforce_csrf_checks=True)
        response = csrf_client.post(
            reverse("helpdesk_api"),
            data='{"question":"How do I renew?"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)

    def test_helpdesk_api_accepts_valid_csrf_token(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.get(reverse("helpdesk"))
        csrf_token = csrf_client.cookies["csrftoken"].value

        response = csrf_client.post(
            reverse("helpdesk_api"),
            data='{"question":"How do I renew?"}',
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("answer", response.json())

    def test_staff_ai_chat_accepts_valid_csrf_token_for_registrar(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.registrar)
        csrf_client.get(reverse("staff_ai_assistant"))
        csrf_token = csrf_client.cookies["csrftoken"].value

        response = csrf_client.post(
            reverse("staff_ai_chat"),
            data='{"question":"How many pending applications do I need to review?"}',
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("title", payload)
        self.assertIn("answer", payload)

    def test_staff_ai_chat_returns_live_midwife_total(self):
        self.client.force_login(self.registrar)
        response = self.client.post(
            reverse("staff_ai_chat"),
            data='{"question":"what is the total for Midwives?"}',
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self.client.get(reverse("staff_ai_assistant")).cookies["csrftoken"].value,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("Midwives", payload["title"])
        self.assertIn("current total", payload["answer"].lower())

    def test_staff_ai_chat_returns_latest_source_answer(self):
        self.client.force_login(self.registrar)
        response = self.client.post(
            reverse("staff_ai_chat"),
            data='{"question":"Where did the latest data come from?"}',
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self.client.get(reverse("staff_ai_assistant")).cookies["csrftoken"].value,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("Latest Source Import", payload["title"])

    def test_staff_ai_chat_requires_csrf_token(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.registrar)
        response = csrf_client.post(
            reverse("staff_ai_chat"),
            data='{"question":"How many pending applications?"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)

    @patch("apps.dashboard.views.subprocess.run")
    def test_execute_management_command_requires_csrf_token(self, run_mock):
        run_mock.return_value.returncode = 0
        run_mock.return_value.stdout = "ok"
        run_mock.return_value.stderr = ""

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.registrar)
        response = csrf_client.post(
            reverse("execute_management_command"),
            data='{"command":"generate_snapshot"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        run_mock.assert_not_called()

    def test_profile_post_without_csrf_redirects_back_cleanly(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.registrar)

        response = csrf_client.post(
            reverse("user_profile"),
            {"first_name": "Updated"},
            HTTP_REFERER=reverse("user_profile"),
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("user_profile"))

    @patch("apps.dashboard.views.subprocess.run")
    def test_execute_management_command_accepts_valid_csrf_token_for_registrar(self, run_mock):
        run_mock.return_value.returncode = 0
        run_mock.return_value.stdout = "snapshot complete"
        run_mock.return_value.stderr = ""

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.registrar)
        csrf_client.get(reverse("user_profile"))
        csrf_token = csrf_client.cookies["csrftoken"].value

        response = csrf_client.post(
            reverse("execute_management_command"),
            data='{"command":"generate_snapshot"}',
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["returncode"], 0)
        run_mock.assert_called_once()

    @patch("apps.dashboard.views.subprocess.Popen")
    @patch("apps.dashboard.views.subprocess.run")
    def test_execute_management_command_runs_audit_in_background(self, run_mock, popen_mock):
        popen_mock.return_value.pid = 4321

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.registrar)
        csrf_client.get(reverse("user_profile"))
        csrf_token = csrf_client.cookies["csrftoken"].value

        response = csrf_client.post(
            reverse("execute_management_command"),
            data='{"command":"audit_missing_data"}',
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["background"])
        self.assertEqual(payload["pid"], 4321)
        run_mock.assert_not_called()
        popen_mock.assert_called_once()

    @patch("apps.dashboard.views.subprocess.run")
    def test_execute_management_command_rejects_non_staff_even_with_csrf(self, run_mock):
        run_mock.return_value.returncode = 0
        run_mock.return_value.stdout = "ok"
        run_mock.return_value.stderr = ""

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.applicant)
        csrf_client.get(reverse("user_profile"))
        csrf_token = csrf_client.cookies["csrftoken"].value

        response = csrf_client.post(
            reverse("execute_management_command"),
            data='{"command":"generate_snapshot"}',
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, 403)
        run_mock.assert_not_called()
