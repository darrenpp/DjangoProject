from datetime import date
from unittest.mock import patch

from django.core.cache import cache
from django.db import OperationalError
from django.test import TestCase

from apps.dashboard.models import NursingAnalyticsSnapshot, NursingFacilityCadreYearMetric, NursingLifecycleFact
from apps.dashboard.nursing_intelligence import build_nursing_workforce_intelligence_context
from apps.workforce.models import (
    Application,
    ApplicationPathway,
    Cadre,
    DataImportBatch,
    Facility,
    HealthStudent,
    Location,
    MedicalDoctor,
    Midwife,
    NursingProfessional,
    PracticingLicenseRecord,
    RegulatoryBody,
    TrainingInstitution,
)


class NursingWorkforceIntelligenceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.today = date(2026, 7, 24)
        nursing_cadre = Cadre.objects.create(name="Registered Nurse", category="nursing")
        midwife_cadre = Cadre.objects.create(name="Midwife", category="midwifery")
        Location.objects.create(province="Morobe", district="Lae")
        self.location = Location.objects.get(province="Morobe", district="Lae")
        self.facility = Facility.objects.create(
            name="Angau Memorial Hospital",
            type="Hospital",
            ownership="public",
            location=self.location,
        )
        self.institution = TrainingInstitution.objects.create(
            name="Lae School of Nursing",
            type="Nursing School",
            regulatory_body_name="PNG Nursing Council",
            is_active=True,
        )
        NursingProfessional.objects.create(
            first_name="Nursing",
            last_name="One",
            registration_no="RN-NURSING-001",
            province="Morobe",
            gender="Female",
            date_of_birth=date(1970, 7, 24),
            license_expiry_date=date(2026, 8, 20),
            cadre=nursing_cadre,
        )
        Midwife.objects.create(
            first_name="Nursing",
            last_name="Two",
            registration_no="MW-NURSING-002",
            province="Morobe",
            gender="Female",
            date_of_birth=date(1990, 7, 24),
            license_expiry_date=date(2026, 7, 1),
            cadre=midwife_cadre,
        )
        # This proves that the service does not blend Medical Board data into
        # a Nursing Council intelligence result.
        MedicalDoctor.objects.create(
            first_name="Medical",
            last_name="Only",
            registration_no="MB-MEDICAL-001",
            province="Western",
            date_of_birth=date(1960, 1, 1),
            license_expiry_date=date(2027, 1, 1),
        )
        HealthStudent.objects.create(
            first_name="Future",
            last_name="Nurse",
            registration_no="GD-NURSING-001",
            program="Diploma in Nursing",
            institution=self.institution,
            expected_graduation_date=date(2026, 11, 30),
        )

        body = RegulatoryBody.objects.create(code="PNG_NURSING_COUNCIL", name="PNG Nursing Council")
        ApplicationPathway.objects.create(
            regulatory_body=body,
            pathway_code="PNG_RENEWAL",
            pathway_name="PNG Licence Renewal",
            primary_form_code="NC3",
            active=True,
            requires_payment=True,
        )
        Application.objects.create(form_code="NC3", status="pending")
        Application.objects.create(form_code="MD2", status="pending")

        self.snapshot = NursingAnalyticsSnapshot.objects.create(
            source_file_name="nursing-intelligence.xlsx",
            source_file_hash="nursing-intelligence-snapshot",
            is_active=True,
        )
        NursingLifecycleFact.objects.create(
            snapshot=self.snapshot,
            record_id="ATP-NURSING-001",
            lifecycle_stage="Authority to Practice",
            cycle_year=2026,
            person_group_key="NURSING ONE",
            province="Morobe",
            cadre="Registered Nurse",
            sex="Female",
            age=56,
        )
        NursingLifecycleFact.objects.create(
            snapshot=self.snapshot,
            record_id="ATP-NURSING-002",
            lifecycle_stage="Authority to Practice",
            cycle_year=2026,
            person_group_key="NURSING TWO",
            province="Morobe",
            cadre="Midwife",
            sex="Female",
            age=36,
        )
        NursingLifecycleFact.objects.create(
            snapshot=self.snapshot,
            record_id="ATP-NURSING-003",
            lifecycle_stage="Authority to Practice",
            cycle_year=2025,
            person_group_key="NURSING HISTORICAL",
            province="Western",
            cadre="Registered Nurse",
            sex="Female",
            age=25,
        )
        NursingFacilityCadreYearMetric.objects.create(
            snapshot=self.snapshot,
            facility=self.facility.name,
            province="Morobe",
            organization_type="Public",
            cadre="Registered Nurse",
            year=2026,
            count=63,
            raw_payload={"required_nurses": 120},
        )
        NursingFacilityCadreYearMetric.objects.create(
            snapshot=self.snapshot,
            facility="Western Rural Health Centre",
            province="Western",
            organization_type="Public",
            cadre="Registered Nurse",
            year=2025,
            count=10,
            raw_payload={"required_nurses": 20},
        )

    def test_context_is_nursing_only_aggregate_and_filter_ready(self):
        context = build_nursing_workforce_intelligence_context(today=self.today)

        self.assertEqual(context["scope"], "nursing")
        self.assertTrue(context["read_only"])
        self.assertEqual(context["practitioner_status"]["active_practitioner_count"], 2)
        self.assertEqual(context["practitioner_status"]["atp_current_person_count"], 2)
        self.assertEqual(context["practitioner_status"]["renewal_due_count"], 1)
        self.assertEqual(context["practitioner_status"]["licence_expired_count"], 1)
        self.assertEqual(context["province_distribution"]["rows"], [{"province": "Morobe", "count": 2}])
        self.assertNotIn("MB-MEDICAL-001", str(context))
        self.assertNotIn("Medical Only", str(context))
        self.assertEqual(context["age_and_retirement"]["known_age_count"], 2)
        self.assertEqual(context["age_and_retirement"]["retirement_within_five_years_count"], 1)
        self.assertEqual(context["facility_staffing"]["rows"][0]["gap"], 57)
        self.assertEqual(context["facility_staffing"]["rows"][0]["gap_status"], "reported")
        self.assertEqual(context["pathway_and_education"]["pending_renewal_count"], 1)
        self.assertEqual(context["pathway_and_education"]["graduand_count"], 1)
        self.assertIn("Morobe", context["filter_dimensions"]["geography"]["provinces"])
        self.assertIn("Registered Nurse", context["filter_dimensions"]["workforce"]["cadres"])

        # The reusable context must never act as an individual record API.
        rendered = str(context)
        self.assertNotIn("RN-NURSING-001", rendered)
        self.assertNotIn("Nursing One", rendered)
        self.assertNotIn("1970-07-24", rendered)

    def test_falls_back_to_quality_approved_nursing_atp_without_age_disclosure(self):
        self.snapshot.delete()
        NursingProfessional.objects.all().delete()
        Midwife.objects.all().delete()
        batch = DataImportBatch.objects.create(
            source_file_name="nursing-atp.xlsx",
            source_kind="nursing_atp_workbook",
            status="completed",
        )
        PracticingLicenseRecord.objects.create(
            batch=batch,
            record_type="practicing_license",
            target_model="nursingprofessional",
            source_sheet_name="ATP 2026",
            source_row=2,
            record_year=2026,
            full_name="Imported Nurse",
            registration_no="RN-IMPORTED-001",
            province="Morobe",
            workplace_address="Angau Memorial Hospital",
        )

        context = build_nursing_workforce_intelligence_context(today=self.today)

        self.assertEqual(context["practitioner_status"]["atp_source"], "quality_approved_import_records")
        self.assertEqual(context["practitioner_status"]["atp_current_person_count"], 1)
        self.assertFalse(context["age_and_retirement"]["available"])
        self.assertEqual(context["age_and_retirement"]["known_age_count"], 0)
        self.assertEqual(
            context["facility_staffing"]["source"],
            "quality_approved_imported_workplace_references",
        )
        self.assertEqual(context["facility_staffing"]["rows"][0]["gap_status"], "target_not_configured")

    def test_missing_optional_snapshot_table_degrades_to_registry_counts(self):
        with patch(
            "apps.dashboard.nursing_intelligence.active_nursing_analytics_snapshot",
            side_effect=OperationalError("analytics table is not available"),
        ):
            context = build_nursing_workforce_intelligence_context(today=self.today)

        self.assertFalse(context["data_sources"]["analytics_snapshot_available"])
        self.assertEqual(context["practitioner_status"]["active_practitioner_count"], 2)
        self.assertIn("Nursing analytics snapshot", context["unavailable_sections"])

    def test_cached_context_is_copied_before_each_return(self):
        first_context = build_nursing_workforce_intelligence_context(today=self.today)
        first_context["practitioner_status"]["active_practitioner_count"] = 999
        first_context["filter_dimensions"]["workforce"]["cadres"].append("Mutated caller value")

        second_context = build_nursing_workforce_intelligence_context(today=self.today)

        self.assertEqual(second_context["practitioner_status"]["active_practitioner_count"], 2)
        self.assertNotIn(
            "Mutated caller value",
            second_context["filter_dimensions"]["workforce"]["cadres"],
        )

    def test_governed_snapshot_filters_apply_to_province_cadre_and_year_without_cache_leakage(self):
        filtered_context = build_nursing_workforce_intelligence_context(
            today=self.today,
            filters={
                "province": "Western",
                "cadre": "Registered Nurse",
                "year": "2025",
            },
        )

        self.assertTrue(filtered_context["filter_state"]["active"])
        self.assertEqual(filtered_context["filter_state"]["selected"]["province"], "Western")
        self.assertEqual(filtered_context["filter_state"]["selected"]["cadre"], "Registered Nurse")
        self.assertEqual(filtered_context["filter_state"]["selected"]["year"], 2025)
        self.assertEqual(filtered_context["practitioner_status"]["atp_current_year"], 2025)
        self.assertEqual(filtered_context["practitioner_status"]["atp_current_person_count"], 1)
        self.assertEqual(
            filtered_context["province_distribution"]["rows"],
            [{"province": "Western", "count": 1}],
        )
        self.assertEqual(filtered_context["facility_staffing"]["latest_year"], 2025)
        self.assertEqual(filtered_context["facility_staffing"]["rows"][0]["province"], "Western")
        self.assertEqual(filtered_context["facility_staffing"]["rows"][0]["observed_staff_count"], 10)

        # A different filter state must never reuse this cached aggregate.
        unfiltered_context = build_nursing_workforce_intelligence_context(today=self.today)
        self.assertEqual(unfiltered_context["practitioner_status"]["atp_current_year"], 2026)
        self.assertEqual(unfiltered_context["practitioner_status"]["atp_current_person_count"], 2)
        self.assertEqual(unfiltered_context["filter_state"]["selected"]["province"], "")

    def test_rural_under_35_measure_is_explicitly_unavailable_without_a_governed_classification(self):
        context = build_nursing_workforce_intelligence_context(today=self.today)

        measure = context["rural_under_35_measure"]
        self.assertFalse(measure["available"])
        self.assertIn("not treated as a rural classification", measure["note"])
        self.assertNotIn("Western Rural Health Centre", str(context))
