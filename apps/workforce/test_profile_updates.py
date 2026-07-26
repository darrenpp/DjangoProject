from datetime import date

from django.contrib.contenttypes.models import ContentType
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.workforce.models import (
    ClinicalPrivilege,
    CredentialVerification,
    EmploymentRecord,
    MedicalDoctor,
    NursingProfessional,
    ProfessionalProfileUpdateRequest,
    Qualification,
)
from apps.workforce.profile_updates import (
    ProfessionalProfileUpdateRequestForm,
    build_professional_identity_context,
    create_profile_update_request,
    review_profile_update_request,
)


User = get_user_model()


class ProfessionalProfileUpdateTests(TestCase):
    def setUp(self):
        self.nurse = NursingProfessional.objects.create(
            first_name="Nursing",
            last_name="Professional",
            registration_no="RN-PROFILE-001",
            primary_phone="70000001",
            province="Morobe",
            qualification_level="Bachelor of Nursing",
        )
        self.doctor = MedicalDoctor.objects.create(
            first_name="Medical",
            last_name="Professional",
            registration_no="MB-PROFILE-001",
            specialty="General Practice",
        )
        self.nurse_user = self._linked_user("nurse-profile", "nurse", self.nurse)
        self.doctor_user = self._linked_user("doctor-profile", "doctor", self.doctor)
        self.system_admin = User.objects.create_superuser(
            username="system-admin-profile",
            email="admin@example.test",
            password="test-pass",
            role="admin",
        )
        self.medical_registrar = User.objects.create_user(
            username="medical-registrar-profile",
            password="test-pass",
            role="registrar",
            department="Medical Board",
            role_approved=True,
            system_admin_approved=True,
        )

    def _linked_user(self, username, role, professional):
        user = User.objects.create_user(
            username=username,
            password="test-pass",
            role=role,
            registration_number=professional.registration_no,
        )
        user.professional_content_type = ContentType.objects.get_for_model(professional)
        user.professional_object_id = professional.pk
        user.professional_record_status = "linked"
        user.save()
        return user

    def _form(self, values):
        form = ProfessionalProfileUpdateRequestForm(values)
        self.assertTrue(form.is_valid(), form.errors)
        return form

    def test_contact_change_is_staged_then_approved_before_registry_changes(self):
        form = self._form({
            "update_type": "contact",
            "primary_phone": "79990001",
            "email": "nurse@example.test",
            "province": "Western",
        })
        request_obj = create_profile_update_request(
            professional=self.nurse,
            requested_by=self.nurse_user,
            form=form,
        )

        self.nurse.refresh_from_db()
        self.assertEqual(self.nurse.primary_phone, "70000001")
        self.assertEqual(request_obj.status, "submitted")
        self.assertEqual(request_obj.office_scope, "nursing")

        review_profile_update_request(
            request_id=request_obj.pk,
            actor=self.system_admin,
            approved=True,
            reviewer_note="Evidence checked against applicant account.",
        )
        self.nurse.refresh_from_db()
        request_obj.refresh_from_db()
        self.assertEqual(self.nurse.primary_phone, "79990001")
        self.assertEqual(self.nurse.email, "nurse@example.test")
        self.assertEqual(self.nurse.province, "Western")
        self.assertEqual(request_obj.status, "approved")
        self.assertIsNotNone(request_obj.applied_at)

    def test_approved_credential_and_clinical_privilege_create_explicit_regulatory_evidence(self):
        credential_form = self._form({
            "update_type": "qualification",
            "credential_type": "specialist_certificate",
            "qualification_name": "Fellowship in Cardiology",
            "institution_name": "Accredited College",
            "specialty": "Cardiology",
        })
        credential_request = create_profile_update_request(
            professional=self.doctor,
            requested_by=self.doctor_user,
            form=credential_form,
        )
        review_profile_update_request(
            request_id=credential_request.pk,
            actor=self.system_admin,
            approved=True,
        )
        doctor_ct = ContentType.objects.get_for_model(self.doctor)
        self.doctor.refresh_from_db()
        self.assertEqual(self.doctor.specialty, "Cardiology")
        self.assertTrue(Qualification.objects.filter(content_type=doctor_ct, object_id=self.doctor.pk).exists())
        self.assertTrue(CredentialVerification.objects.filter(
            content_type=doctor_ct,
            object_id=self.doctor.pk,
            status="verified",
        ).exists())

        privilege_form = self._form({
            "update_type": "clinical_privilege",
            "privilege_name": "Emergency Cardiology",
            "privilege_expiry_date": date(2027, 7, 24).isoformat(),
        })
        privilege_request = create_profile_update_request(
            professional=self.doctor,
            requested_by=self.doctor_user,
            form=privilege_form,
        )
        review_profile_update_request(
            request_id=privilege_request.pk,
            actor=self.system_admin,
            approved=True,
        )
        self.assertTrue(ClinicalPrivilege.objects.filter(
            content_type=doctor_ct,
            object_id=self.doctor.pk,
            privilege_name="Emergency Cardiology",
            status="approved",
        ).exists())

    def test_nursing_request_cannot_be_reviewed_from_medical_board_scope(self):
        request_obj = ProfessionalProfileUpdateRequest.objects.create(
            content_type=ContentType.objects.get_for_model(self.nurse),
            object_id=self.nurse.pk,
            office_scope="nursing",
            update_type="contact",
            proposed_changes={"province": "Simbu"},
            requested_by=self.nurse_user,
        )
        self.client.force_login(self.medical_registrar)
        response = self.client.post(
            reverse("review_professional_profile_update_request", args=[request_obj.pk]),
            {"action": "approve", "reviewer_note": "Attempted cross-office decision"},
        )
        self.assertEqual(response.status_code, 404)
        request_obj.refresh_from_db()
        self.assertEqual(request_obj.status, "submitted")

    def test_rejection_requires_a_review_reason(self):
        request_obj = ProfessionalProfileUpdateRequest.objects.create(
            content_type=ContentType.objects.get_for_model(self.nurse),
            object_id=self.nurse.pk,
            office_scope="nursing",
            update_type="contact",
            proposed_changes={"province": "Simbu"},
            requested_by=self.nurse_user,
        )
        self.client.force_login(self.system_admin)
        response = self.client.post(
            reverse("review_professional_profile_update_request", args=[request_obj.pk]),
            {"action": "reject", "reviewer_note": ""},
        )

        self.assertEqual(response.status_code, 302)
        request_obj.refresh_from_db()
        self.assertEqual(request_obj.status, "submitted")

    def test_linked_professional_can_open_the_staged_update_page(self):
        self.client.force_login(self.nurse_user)
        response = self.client.get(reverse("professional_profile_update_request"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Request a verified profile update")
        self.assertContains(response, "does not directly change the official register")

    def test_identity_context_has_completion_signal_without_contact_or_date_of_birth(self):
        EmploymentRecord.objects.create(
            content_type=ContentType.objects.get_for_model(self.nurse),
            object_id=self.nurse.pk,
            employer_name="Angau Memorial Hospital",
            is_current=True,
            review_status="promoted",
        )
        context = build_professional_identity_context(self.nurse)
        identity = context["professional_identity"]
        self.assertGreater(identity["profile_completeness"], 0)
        self.assertEqual(identity["workplace"], "Angau Memorial Hospital")
        self.assertNotIn("primary_phone", identity)
        self.assertNotIn("email", identity)
        self.assertNotIn("date_of_birth", identity)
