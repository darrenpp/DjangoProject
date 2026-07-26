from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.complaints.models import DisciplinaryCase
from apps.dashboard import medical_intelligence
from apps.dashboard.medical_intelligence import (
    build_medical_board_intelligence_context,
    resolve_medical_board_aggregate_filters,
)
from apps.workforce.models import (
    Application,
    ClinicalPrivilege,
    CredentialVerification,
    EmploymentRecord,
    Facility,
    FacilityAccreditation,
    Location,
    MedicalDoctor,
    ProfessionalDocument,
    Qualification,
)


class MedicalBoardIntelligenceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.report_date = date(2026, 7, 24)
        self.location = Location.objects.create(
            province="National Capital District",
            district="Port Moresby",
        )
        self.facility = Facility.objects.create(
            name="Port Moresby General Hospital",
            type="Hospital",
            ownership="public",
            location=self.location,
        )
        self.cardiologist = MedicalDoctor.objects.create(
            first_name="Active",
            last_name="Cardiologist",
            registration_no="MB-001",
            specialty="Cardiology",
            province="National Capital District",
            applicant_type="overseas",
            gender="Female",
            license_expiry_date=self.report_date + timedelta(days=30),
            is_active=True,
        )
        self.expired_doctor = MedicalDoctor.objects.create(
            first_name="Expired",
            last_name="Generalist",
            registration_no="MB-002",
            province="Morobe",
            license_expiry_date=self.report_date - timedelta(days=1),
            is_active=True,
        )
        doctor_content_type = ContentType.objects.get_for_model(MedicalDoctor)
        facility_content_type = ContentType.objects.get_for_model(Facility)
        EmploymentRecord.objects.create(
            content_type=doctor_content_type,
            object_id=self.cardiologist.pk,
            facility=self.facility,
            province="National Capital District",
            district="Port Moresby",
            employment_sector="public",
            is_current=True,
        )
        Qualification.objects.create(
            content_type=doctor_content_type,
            object_id=self.cardiologist.pk,
            qualification_name="MBBS",
            certificate_attached=True,
        )
        ProfessionalDocument.objects.create(
            content_type=doctor_content_type,
            object_id=self.cardiologist.pk,
            document_label="Cardiology fellowship",
            file=SimpleUploadedFile("fellowship.pdf", b"verified evidence"),
            verification_signature="Registrar verification",
        )
        Application.objects.create(
            content_type=doctor_content_type,
            object_id=self.cardiologist.pk,
            form_code="MD2",
            pathway="medical_board",
            status="pending",
        )
        Application.objects.create(
            content_type=facility_content_type,
            object_id=self.facility.pk,
            form_code="MBAC",
            pathway="medical_facility",
            status="approved",
        )
        FacilityAccreditation.objects.create(
            facility=self.facility,
            accreditation_type="hospital",
            status="accredited",
            compliance_score=85,
        )
        CredentialVerification.objects.create(
            content_type=doctor_content_type,
            object_id=self.cardiologist.pk,
            credential_type="specialist_certificate",
            credential_title="Cardiology Fellowship",
            status="verified",
        )
        ClinicalPrivilege.objects.create(
            content_type=doctor_content_type,
            object_id=self.cardiologist.pk,
            privilege_name="Cardiology",
            facility=self.facility,
            status="approved",
        )
        DisciplinaryCase.objects.create(
            office_scope="medical",
            subject_name="Private identity not returned by intelligence",
            allegation_summary="Private disciplinary content",
            stage="investigation",
            status="open",
        )
        DisciplinaryCase.objects.create(
            office_scope="medical",
            subject_name="Closed identity not returned by intelligence",
            allegation_summary="Closed content",
            stage="closed",
            status="closed",
        )

    def test_builds_aggregate_executive_and_specialty_context(self):
        context = build_medical_board_intelligence_context(today=self.report_date)

        self.assertTrue(
            context["medical_intelligence"]["available"],
            context["medical_intelligence"]["status"],
        )
        self.assertEqual(context["medical_executive_metrics"]["registered_doctors"], 2)
        self.assertEqual(context["medical_executive_metrics"]["active_practitioners"], 1)
        self.assertEqual(context["medical_executive_metrics"]["specialists"], 1)
        self.assertEqual(context["medical_executive_metrics"]["expired_licences"], 1)
        self.assertEqual(context["medical_executive_metrics"]["pending_renewals"], 1)
        self.assertEqual(context["medical_executive_metrics"]["open_disciplinary_cases"], 1)
        self.assertEqual(context["medical_executive_metrics"]["accredited_facilities"], 1)
        self.assertEqual(context["medical_executive_metrics"]["overseas_practitioners"], 1)
        self.assertEqual(
            context["medical_specialty_distribution"],
            [{"label": "Cardiology", "practitioner_count": 1}],
        )
        self.assertEqual(context["medical_credential_evidence"]["qualification_records"], 1)
        self.assertEqual(context["medical_credential_evidence"]["signed_document_records"], 1)
        self.assertEqual(context["medical_credential_evidence"]["verified_credential_records"], 1)
        self.assertTrue(context["medical_clinical_privileges"]["supported"])
        self.assertEqual(context["medical_clinical_privileges"]["active_privilege_count"], 1)

    def test_filters_use_current_medical_employment_without_identity_output(self):
        context = build_medical_board_intelligence_context(
            {
                "specialty": "Cardiology",
                "province": "National Capital District",
                "district": "Port Moresby",
                "facility": "Port Moresby General Hospital",
                "sector": "public",
            },
            today=self.report_date,
        )

        self.assertEqual(context["medical_executive_metrics"]["registered_doctors"], 1)
        self.assertEqual(context["medical_province_distribution"], [
            {"label": "National Capital District", "practitioner_count": 1},
        ])
        self.assertEqual(context["medical_district_distribution"], [
            {"label": "Port Moresby", "practitioner_count": 1},
        ])
        self.assertEqual(context["medical_facility_distribution"], [
            {"label": "Port Moresby General Hospital", "practitioner_count": 1},
        ])
        self.assertEqual(context["medical_sector_distribution"], [
            {"label": "public", "practitioner_count": 1},
        ])
        self.assertNotIn("subject_name", repr(context))
        self.assertNotIn("Private disciplinary content", repr(context))

    def test_resolves_cardiologist_and_workplace_province_to_exact_aggregate_filter(self):
        doctor_content_type = ContentType.objects.get_for_model(MedicalDoctor)
        western_cardiologist = MedicalDoctor.objects.create(
            first_name="Western",
            last_name="Cardiology",
            registration_no="MB-003",
            specialty="Cardiology",
            is_active=True,
        )
        EmploymentRecord.objects.create(
            content_type=doctor_content_type,
            object_id=western_cardiologist.pk,
            province="Western",
            is_current=True,
        )

        base_context = build_medical_board_intelligence_context(today=self.report_date)
        resolution = resolve_medical_board_aggregate_filters(
            "How many cardiologists are in Western?",
            base_context["medical_intelligence_filter_options"],
        )
        filtered_context = build_medical_board_intelligence_context(
            resolution["filters"],
            today=self.report_date,
        )

        self.assertEqual(resolution["filters"], {
            "specialty": "Cardiology",
            "province": "Western",
        })
        self.assertFalse(resolution["unresolved_geography"])
        self.assertEqual(filtered_context["medical_executive_metrics"]["specialists"], 1)
        self.assertNotIn("MB-003", repr(filtered_context))
        self.assertNotIn("Western Cardiology", repr(filtered_context))

    def test_unmatched_regional_specialist_wording_is_marked_for_data_gap_response(self):
        context = build_medical_board_intelligence_context(today=self.report_date)

        resolution = resolve_medical_board_aggregate_filters(
            "How many cardiologists are in Unknown Province?",
            context["medical_intelligence_filter_options"],
        )

        self.assertEqual(resolution["filters"].get("specialty"), "Cardiology")
        self.assertTrue(resolution["geography_requested"])
        self.assertTrue(resolution["unresolved_geography"])

    def test_empty_database_returns_a_safe_zero_context(self):
        MedicalDoctor.objects.all().delete()
        Application.objects.all().delete()
        DisciplinaryCase.objects.all().delete()
        Facility.objects.all().delete()

        context = build_medical_board_intelligence_context(today=self.report_date)

        self.assertTrue(
            context["medical_intelligence"]["available"],
            context["medical_intelligence"]["status"],
        )
        self.assertEqual(context["medical_executive_metrics"]["registered_doctors"], 0)
        self.assertEqual(context["medical_specialty_distribution"], [])
        self.assertTrue(context["medical_clinical_privileges"]["supported"])
        self.assertEqual(context["medical_clinical_privileges"]["active_privilege_count"], 0)

    def test_short_cache_returns_independent_copies(self):
        with (
            patch.object(
                medical_intelligence,
                "_medical_intelligence_data_marker",
                return_value=("test-marker",),
            ),
            patch.object(
                medical_intelligence,
                "_context_is_cacheable",
                return_value=True,
            ),
            patch.object(
                medical_intelligence,
                "_build_live_medical_board_intelligence_context",
                wraps=medical_intelligence._build_live_medical_board_intelligence_context,
            ) as live_build,
        ):
            first = build_medical_board_intelligence_context(today=self.report_date)
            first["medical_executive_metrics"]["registered_doctors"] = 999
            second = build_medical_board_intelligence_context(today=self.report_date)

        self.assertEqual(live_build.call_count, 1)
        self.assertEqual(second["medical_executive_metrics"]["registered_doctors"], 2)

    def test_cache_key_changes_when_a_medical_profile_is_added(self):
        first = build_medical_board_intelligence_context(today=self.report_date)
        self.assertEqual(first["medical_executive_metrics"]["registered_doctors"], 2)

        MedicalDoctor.objects.create(
            first_name="New",
            last_name="Medical Profile",
            registration_no="MB-003",
            is_active=True,
        )

        refreshed = build_medical_board_intelligence_context(today=self.report_date)
        self.assertEqual(refreshed["medical_executive_metrics"]["registered_doctors"], 3)

    def test_does_not_cache_when_a_migration_marker_is_unavailable(self):
        with (
            patch.object(
                medical_intelligence,
                "_medical_intelligence_data_marker",
                return_value=None,
            ),
            patch.object(
                medical_intelligence,
                "_build_live_medical_board_intelligence_context",
                wraps=medical_intelligence._build_live_medical_board_intelligence_context,
            ) as live_build,
        ):
            build_medical_board_intelligence_context(today=self.report_date)
            build_medical_board_intelligence_context(today=self.report_date)

        self.assertEqual(live_build.call_count, 2)

    def test_does_not_cache_a_degraded_context(self):
        degraded_context = {
            "medical_intelligence": {"available": False},
            "medical_facility_accreditation": {"available": False},
            "medical_credential_evidence": {"available": False},
            "medical_clinical_privileges": {"available": False},
        }
        with (
            patch.object(
                medical_intelligence,
                "_medical_intelligence_data_marker",
                return_value=("safe-marker",),
            ),
            patch.object(
                medical_intelligence,
                "_build_live_medical_board_intelligence_context",
                return_value=degraded_context,
            ) as live_build,
        ):
            first = build_medical_board_intelligence_context(today=self.report_date)
            second = build_medical_board_intelligence_context(today=self.report_date)

        self.assertEqual(live_build.call_count, 2)
        self.assertIsNot(first, second)
