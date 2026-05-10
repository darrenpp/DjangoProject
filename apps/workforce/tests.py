from datetime import date

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from apps.competency.models import CompetencyAssessment
from apps.dashboard.models import Receipt
from apps.workforce.models import (
    Application,
    ApplicationChecklistItem,
    AuditLog,
    DeceasedNotification,
    EmployerVerificationRequest,
    ApplicationPathway,
    DeclarationTemplate,
    DocumentRequirement,
    DynamicFormDefinition,
    FeeSchedule,
    NursingProfessional,
    PracticingLicenseRecord,
    RegulatoryBody,
    SupervisorAssignment,
)
from apps.workforce.services.nursing_council_workflows import (
    NURSING_COUNCIL_CODE,
    NursingCouncilValidationService,
    approve_deceased_notification,
    approve_nursing_application,
    build_nursing_workflow_rows,
    build_public_form_guide,
    complete_supervisor_competency,
    create_deceased_notification,
    create_employer_verification_request,
    create_supervisor_assignment,
    ensure_nursing_council_configuration,
    generate_application_checklist,
    search_public_nursing_register,
)
from apps.workforce.services.ai_import_cleanser import cleanse_import_row


class AIImportCleanserTests(TestCase):
    def test_local_cleanser_normalizes_row_and_flags_review_items(self):
        result = cleanse_import_row(
            {
                "Full Name": "  maria   test  ",
                "Province": "Morob",
                "Registration No": " rn 100 ",
                "Payment Date": "2050-03-17",
            },
            row_number=1,
            source_label="sample.xlsx",
            scope="nursing",
        )

        self.assertEqual(result["provider"], "local")
        self.assertEqual(result["normalized_row"]["full_name"], "maria test")
        self.assertEqual(result["normalized_row"]["registration_no"], "RN 100")
        self.assertTrue(result["requires_human_review"])
        issue_types = {issue["issue_type"] for issue in result["issues"]}
        self.assertTrue({"province_fuzzy_match", "unknown_province"} & issue_types)
        self.assertIn("future_date", issue_types)


class NursingCouncilWorkflowConfigurationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_nursing_council_configuration()

    def test_configuration_seed_creates_expected_nursing_council_records(self):
        body = RegulatoryBody.objects.get(code=NURSING_COUNCIL_CODE)

        self.assertEqual(ApplicationPathway.objects.filter(regulatory_body=body).count(), 12)
        self.assertEqual(DynamicFormDefinition.objects.filter(regulatory_body=body).count(), 18)
        self.assertEqual(DocumentRequirement.objects.filter(pathway__regulatory_body=body).count(), 55)
        self.assertEqual(FeeSchedule.objects.filter(regulatory_body=body).count(), 10)
        self.assertEqual(DeclarationTemplate.objects.filter(regulatory_body=body).count(), 11)

    def test_public_form_guide_uses_configured_pathways_and_forms(self):
        guide = build_public_form_guide()
        graduate_pathway = "PNG Graduate Nurse Provisional Licence (PNG_NURSE_GRAD_PROV)"

        self.assertIn(graduate_pathway, guide)
        self.assertIn(("NC1", "Application for Provisional Licence to Practice"), guide[graduate_pathway])
        self.assertIn(("G4", "Statement of Competency for Graduate Nurses"), guide[graduate_pathway])
        self.assertFalse(any("DECEASED_NOTICE" in pathway for pathway in guide))

    def test_dashboard_workflow_rows_include_full_configured_pathways(self):
        rows = build_nursing_workflow_rows()
        codes = {row["code"] for row in rows}

        self.assertEqual(len(rows), 12)
        self.assertIn("OVERSEAS_TEMP", codes)
        self.assertIn("DECEASED_NOTICE", codes)
        self.assertIn("EMPLOYER_VERIFY", codes)

    def test_renewal_validation_blocks_missing_employment_status(self):
        professional = NursingProfessional.objects.create(
            first_name="Maria",
            last_name="Test",
            gender="Female",
            date_of_birth=date(1990, 1, 1),
            registration_no="RN-TEST-001",
        )
        application = Application.objects.create(
            content_type=ContentType.objects.get_for_model(professional),
            object_id=professional.pk,
            form_code="NC3",
            pathway="local_nursing_graduate",
            payload={"pathway_code": "PNG_RENEWAL"},
        )

        result = NursingCouncilValidationService(application).validate_for_status("submitted")

        self.assertFalse(result["can_proceed"])
        self.assertIn("Renewal applications must capture employment status.", result["errors"])

    def test_checklist_generator_creates_required_items_from_pathway_config(self):
        professional = NursingProfessional.objects.create(
            first_name="Lina",
            last_name="Graduate",
            gender="Female",
            date_of_birth=date(2001, 2, 3),
            registration_no="GRAD-TEST-001",
        )
        application = Application.objects.create(
            content_type=ContentType.objects.get_for_model(professional),
            object_id=professional.pk,
            form_code="NC1",
            pathway="local_nursing_graduate",
            payload={"pathway_code": "PNG_NURSE_GRAD_PROV"},
        )

        items = generate_application_checklist(application)
        labels = set(
            ApplicationChecklistItem.objects.filter(application=application).values_list(
                "document_requirement__label",
                flat=True,
            )
        )

        self.assertEqual(len(items), 5)
        self.assertIn("Academic award", labels)
        self.assertIn("G4 competency statement", labels)

    def test_approval_creates_licence_record_and_audit_log(self):
        professional = NursingProfessional.objects.create(
            first_name="Anna",
            last_name="Renewal",
            gender="Female",
            date_of_birth=date(1988, 5, 1),
            registration_no="RN-RENEW-001",
            registration_number="P-RENEW-001",
        )
        application = Application.objects.create(
            content_type=ContentType.objects.get_for_model(professional),
            object_id=professional.pk,
            form_code="NC3",
            pathway="local_nursing_graduate",
            payload={
                "pathway_code": "PNG_RENEWAL",
                "declaration_acceptance": True,
                "employment_status": "full_time",
                "employer_name": "Public Hospital",
                "facility_name": "Public Hospital",
                "province": "National Capital District",
                "position_title": "Nurse",
                "area_of_employment": "government",
                "start_date": "2026-01-01",
            },
        )
        for item in generate_application_checklist(application):
            item.status = "accepted"
            item.save(update_fields=["status"])
        Receipt.objects.create(
            receipt_number="",
            amount="70.00",
            status="completed",
            application=application,
        )

        result = approve_nursing_application(application)
        application.refresh_from_db()
        professional.refresh_from_db()

        self.assertTrue(result["approved"])
        self.assertEqual(application.status, "approved")
        self.assertEqual(professional.license_expiry_date, date(date.today().year, 12, 31))
        self.assertTrue(PracticingLicenseRecord.objects.filter(source_row=application.pk, record_type="practicing_license").exists())
        self.assertTrue(AuditLog.objects.filter(action="REGISTRAR_APPROVED", entity_id=str(application.pk)).exists())

    def test_public_register_search_returns_safe_fields_only(self):
        NursingProfessional.objects.create(
            first_name="Safe",
            last_name="Search",
            gender="Female",
            date_of_birth=date(1992, 8, 2),
            registration_no="RN-SAFE-001",
            registration_number="PN-SAFE-001",
            email="private@example.com",
            primary_phone="12345",
        )

        rows = search_public_nursing_register(query="Safe")

        self.assertEqual(rows[0]["full_name"], "Safe Search")
        self.assertIn("registration_number", rows[0])
        self.assertNotIn("email", rows[0])
        self.assertNotIn("date_of_birth", rows[0])
        self.assertNotIn("primary_phone", rows[0])

    def test_deceased_notification_approval_deactivates_practitioner(self):
        professional = NursingProfessional.objects.create(
            first_name="Late",
            last_name="Practitioner",
            gender="Female",
            date_of_birth=date(1975, 1, 1),
            registration_no="RN-LATE-001",
            is_active=True,
        )
        notification = create_deceased_notification(
            actor=None,
            name_at_report="Late Practitioner",
            date_of_death=date(2026, 5, 1),
            registration_number="RN-LATE-001",
        )

        approve_deceased_notification(notification)
        professional.refresh_from_db()

        self.assertFalse(professional.is_active)
        self.assertEqual(professional.license_expiry_date, date(2026, 5, 1))
        self.assertEqual(DeceasedNotification.objects.get(pk=notification.pk).verification_status, "approved")

    def test_employer_verification_returns_safe_snapshot(self):
        NursingProfessional.objects.create(
            first_name="Employer",
            last_name="Visible",
            gender="Female",
            date_of_birth=date(1990, 1, 1),
            registration_no="RN-EMP-001",
            email="hidden@example.com",
        )

        verification = create_employer_verification_request(
            actor=None,
            employer_name="Test Employer",
            registration_number="RN-EMP-001",
        )

        self.assertEqual(verification.status, "verified")
        self.assertEqual(verification.safe_result_json["full_name"], "Employer Visible")
        self.assertNotIn("email", verification.safe_result_json)
        self.assertTrue(EmployerVerificationRequest.objects.filter(pk=verification.pk).exists())

    def test_supervisor_assignment_completion_creates_competency_assessment(self):
        professional = NursingProfessional.objects.create(
            first_name="Competent",
            last_name="Applicant",
            gender="Female",
            date_of_birth=date(1995, 4, 4),
            registration_no="RN-COMP-001",
        )
        application = Application.objects.create(
            content_type=ContentType.objects.get_for_model(professional),
            object_id=professional.pk,
            form_code="NC2",
            pathway="local_nursing_graduate",
            payload={"pathway_code": "PNG_FULL_REG"},
        )

        assignment = create_supervisor_assignment(application=application, supervisor_name="Senior Nurse")
        assessment = complete_supervisor_competency(assignment=assignment, result="competent", comments="Ready for full practice.")
        assignment.refresh_from_db()

        self.assertEqual(assignment.status, "completed")
        self.assertTrue(assessment.is_passed)
        self.assertTrue(SupervisorAssignment.objects.filter(pk=assignment.pk).exists())
        self.assertTrue(CompetencyAssessment.objects.filter(pk=assessment.pk).exists())
