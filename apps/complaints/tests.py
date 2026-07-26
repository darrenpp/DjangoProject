from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.notifications.models import EnquiryThread

from .models import ComplaintCase, ComplaintCaseEvent, DisciplinaryCase, DisciplinaryCaseEvent, RegulatoryDecisionRecord


class ComplaintCaseModuleTests(TestCase):
    def setUp(self):
        self.registrar = User.objects.create_user(
            username="nursing_registrar",
            password="pass12345",
            role="registrar",
            department="Nursing Council",
        )
        self.medical_registrar = User.objects.create_user(
            username="medical_registrar",
            password="pass12345",
            role="registrar",
            department="Medical Board",
        )

    def test_public_submission_creates_formal_case_and_intake_event(self):
        response = self.client.post(reverse("complaint_public_submit"), {
            "office_scope": "nursing",
            "case_type": "service_quality",
            "title": "Complaint about registration delay",
            "description": "I need the Council to review my registration delay.",
            "complainant_name": "Public User",
            "complainant_email": "public@example.com",
            "consent_to_contact": "on",
        })

        self.assertEqual(response.status_code, 200)
        case = ComplaintCase.objects.get()
        self.assertTrue(case.case_number.startswith("ICMS-NC-"))
        self.assertTrue(case.is_public_submission)
        self.assertEqual(case.source, "public_portal")
        self.assertEqual(case.status, "new")
        self.assertContains(response, case.case_number)
        self.assertTrue(ComplaintCaseEvent.objects.filter(case=case, action_type="intake").exists())

    def test_staff_can_open_case_from_enquiry_thread(self):
        self.client.force_login(self.registrar)
        enquiry = EnquiryThread.objects.create(
            subject="Conduct concern",
            office="nursing",
            created_by=self.registrar,
        )

        response = self.client.post(
            f"{reverse('complaint_case_create')}?enquiry={enquiry.pk}",
            {
                "source_enquiry_id": enquiry.pk,
                "office_scope": "nursing",
                "case_type": "professional_conduct",
                "source": "enquiry",
                "priority": "high",
                "risk_level": "high",
                "title": "Conduct concern",
                "description": "Escalated from enquiry.",
                "complainant_name": "Nursing Registrar",
            },
        )

        case = ComplaintCase.objects.get()
        self.assertRedirects(response, reverse("complaint_case_detail", args=[case.case_uuid]))
        self.assertEqual(case.source_enquiry, enquiry)
        self.assertEqual(case.source, "enquiry")
        self.assertEqual(case.priority, "high")

    def test_medical_staff_cannot_see_nursing_only_case(self):
        ComplaintCase.objects.create(
            office_scope="nursing",
            case_type="complaint",
            title="Nursing-only case",
            description="Scoped to Nursing Council.",
            created_by=self.registrar,
        )
        self.client.force_login(self.medical_registrar)

        response = self.client.get(reverse("complaint_case_list"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Nursing-only case")

    def test_status_update_records_case_event_and_closure(self):
        self.client.force_login(self.registrar)
        case = ComplaintCase.objects.create(
            office_scope="nursing",
            case_type="complaint",
            title="Closeable case",
            description="Ready for closure.",
            created_by=self.registrar,
        )

        response = self.client.post(reverse("complaint_case_detail", args=[case.case_uuid]), {
            "form_name": "update",
            "status": "resolved",
            "priority": "normal",
            "risk_level": "medium",
            "assigned_to": "",
            "due_at": "",
            "acknowledged_at": "",
            "closure_summary": "Resolved after review.",
        })

        self.assertRedirects(response, reverse("complaint_case_detail", args=[case.case_uuid]))
        case.refresh_from_db()
        self.assertEqual(case.status, "resolved")
        self.assertIsNotNone(case.closed_at)
        self.assertTrue(
            ComplaintCaseEvent.objects.filter(
                case=case,
                action_type="status_change",
                from_status="new",
                to_status="resolved",
            ).exists()
        )

    def test_staff_can_escalate_complaint_to_disciplinary_case(self):
        self.client.force_login(self.registrar)
        complaint = ComplaintCase.objects.create(
            office_scope="nursing",
            case_type="professional_conduct",
            title="Conduct complaint",
            description="Conduct allegation.",
            subject_name="Nurse Subject",
            subject_identifier="RN-100",
            risk_level="high",
            created_by=self.registrar,
        )

        response = self.client.post(
            f"{reverse('disciplinary_case_create')}?complaint={complaint.case_uuid}",
            {
                "source_complaint_uuid": complaint.case_uuid,
                "office_scope": "nursing",
                "subject_name": "Nurse Subject",
                "subject_identifier": "RN-100",
                "allegation_summary": "Conduct allegation.",
                "statutory_basis": "Council professional conduct SOP.",
                "stage": "preliminary_assessment",
                "status": "open",
                "severity": "high",
                "assigned_to": "",
                "committee_reference": "",
                "hearing_date": "",
                "notice_served_at": "",
                "response_due_at": "",
            },
        )

        case = DisciplinaryCase.objects.get()
        self.assertRedirects(response, reverse("disciplinary_case_detail", args=[case.discipline_uuid]))
        self.assertEqual(case.source_complaint, complaint)
        self.assertTrue(case.discipline_number.startswith("DISC-NC-"))
        self.assertTrue(DisciplinaryCaseEvent.objects.filter(case=case, action_type="intake").exists())
        complaint.refresh_from_db()
        self.assertEqual(complaint.status, "escalated")

    def test_disciplinary_case_decision_creates_decision_register_record(self):
        self.client.force_login(self.registrar)
        case = DisciplinaryCase.objects.create(
            office_scope="nursing",
            subject_name="Nurse Subject",
            subject_identifier="RN-100",
            allegation_summary="Conduct allegation.",
            created_by=self.registrar,
        )

        response = self.client.post(reverse("disciplinary_case_detail", args=[case.discipline_uuid]), {
            "form_name": "decision",
            "office_scope": "nursing",
            "decision_type": "discipline",
            "status": "final",
            "title": f"Decision for {case.discipline_number}",
            "subject_name": "Nurse Subject",
            "subject_identifier": "RN-100",
            "decision_text": "Warning issued.",
            "rationale": "Evidence supports a formal warning.",
            "authority_reference": "Council conduct SOP.",
            "evidence_summary": "Reviewed complaint and response.",
            "conditions": "Complete remediation.",
            "appeal_rights": "Appeal may be lodged through Council process.",
            "effective_date": "",
            "expiry_date": "",
            "decided_by": self.registrar.pk,
        })

        decision = RegulatoryDecisionRecord.objects.get()
        self.assertRedirects(response, reverse("disciplinary_case_detail", args=[case.discipline_uuid]))
        self.assertTrue(decision.decision_number.startswith("DEC-NC-"))
        self.assertEqual(decision.status, "final")
        self.assertIsNotNone(decision.decided_at)
        case.refresh_from_db()
        self.assertEqual(case.decision_record, decision)
        self.assertEqual(case.stage, "decision")
        self.assertEqual(case.status, "decided")

    def test_medical_staff_cannot_see_nursing_disciplinary_case(self):
        DisciplinaryCase.objects.create(
            office_scope="nursing",
            subject_name="Nursing subject",
            allegation_summary="Scoped to Nursing Council.",
            created_by=self.registrar,
        )
        self.client.force_login(self.medical_registrar)

        response = self.client.get(reverse("disciplinary_case_list"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Nursing subject")
