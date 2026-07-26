from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.dashboard.staff_ai import (
    build_staff_ai_chat_response,
    staff_ai_question_needs_knowledge_search,
)


NURSING_INTELLIGENCE_FIXTURE = {
    "practitioner_status": {
        "active_practitioner_count": 3241,
        "atp_current_person_count": 2890,
        "atp_current_year": 2026,
        "renewal_due_within_days": 60,
        "renewal_due_count": 87,
    },
    "age_and_retirement": {
        "available": True,
        "retirement_within_five_years_count": 415,
        "retirement_age_or_older_count": 72,
        "known_age_count": 3100,
        "age_band_rows": [
            {"band": "51-60", "count": 350},
            {"band": "60+", "count": 72},
        ],
        "note": "Aggregate, governed age data.",
    },
    "facility_staffing": {
        "rows": [
            {
                "facility": "Tari Hospital",
                "province": "Hela",
                "observed_staff_count": 63,
                "staffing_target": 120,
                "gap": 57,
                "gap_status": "reported",
            },
        ],
        "note": "Only approved staffing targets are used.",
    },
    "province_distribution": {"rows": [{"province": "Morobe", "count": 400}]},
}

MEDICAL_INTELLIGENCE_FIXTURE = {
    "medical_executive_metrics": {
        "registered_doctors": 5832,
        "active_practitioners": 4920,
        "specialists": 721,
        "pending_renewals": 87,
        "open_disciplinary_cases": 12,
    },
    "medical_specialty_distribution": [
        {"label": "Cardiology", "practitioner_count": 23},
    ],
    "medical_province_distribution": [
        {"label": "National Capital District", "practitioner_count": 23},
    ],
    "medical_intelligence_filter_options": {
        "specialty": ["Cardiology"],
        "province": ["National Capital District"],
        "district": [],
        "facility": [],
        "sector": [],
        "gender": [],
    },
    "medical_intelligence": {"available": True},
    "medical_facility_accreditation": {
        "registered_facility_count": 245,
        "source": "approved Medical Board accreditation records",
        "metric_definition": "Accredited or conditional records only.",
        "pending_application_count": 5,
    },
    "medical_credential_evidence": {
        "verified_credential_records": 721,
        "note": "Verified credential decisions only.",
    },
    "medical_clinical_privileges": {
        "active_privilege_count": 486,
        "note": "Explicit approved privilege records only.",
    },
}


@override_settings(
    AI_ASSISTANT_PROVIDER="local",
    AI_ASSISTANT_OLLAMA_ENABLED=False,
    AI_ASSISTANT_LOCALAI_ENABLED=False,
    AI_ASSISTANT_GOOGLE_ADK_ENABLED=False,
    AI_ASSISTANT_RAG_ENABLED=False,
)
class StaffAIIntelligenceFastPathTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        user_model = get_user_model()
        self.nursing_user = user_model.objects.create_user(
            username="staff.ai.nursing.intelligence",
            password="StrongPass123!",
            role="registrar",
            department="Nursing Council",
        )
        self.medical_user = user_model.objects.create_user(
            username="staff.ai.medical.intelligence",
            password="StrongPass123!",
            role="registrar",
            department="Medical Board",
        )
        self.admin_user = user_model.objects.create_user(
            username="staff.ai.admin.intelligence",
            password="StrongPass123!",
            role="admin",
            department="Administration",
        )

    @mock.patch("apps.dashboard.staff_ai.maybe_generate_live_staff_response")
    @mock.patch(
        "apps.dashboard.nursing_intelligence.build_nursing_workforce_intelligence_context",
        return_value=NURSING_INTELLIGENCE_FIXTURE,
    )
    def test_nursing_retirement_question_is_fast_aggregate_only_and_cited(self, _intelligence, live_response):
        question = "How many Nursing Council professionals will retire in the next five years?"

        response = build_staff_ai_chat_response(self.nursing_user, question, persist=False)

        self.assertEqual(response["title"], "Nursing Workforce Retirement Outlook")
        self.assertIn("415", response["answer"])
        self.assertIn("aggregate planning signal", " ".join(response["bullets"]).lower())
        self.assertTrue(response["citations_verified"])
        self.assertFalse(response["model_generated"])
        self.assertFalse(staff_ai_question_needs_knowledge_search(question))
        live_response.assert_not_called()
        self.assertNotIn("date_of_birth", str(response))
        self.assertNotIn("primary_phone", str(response))

    @mock.patch("apps.dashboard.staff_ai.maybe_generate_live_staff_response")
    @mock.patch(
        "apps.dashboard.nursing_intelligence.build_nursing_workforce_intelligence_context",
        return_value=NURSING_INTELLIGENCE_FIXTURE,
    )
    def test_nursing_province_shortage_question_is_an_aggregate_signal_not_a_record_lookup(
        self, _intelligence, live_response
    ):
        question = "show me provinces with nursing shortages"

        response = build_staff_ai_chat_response(self.nursing_user, question, persist=False)

        self.assertEqual(response["title"], "Nursing Province Staffing Signals")
        self.assertIn("planning signals", response["answer"])
        self.assertIn("Hela: 63 observed / 120 approved target / gap 57", " ".join(response["bullets"]))
        self.assertNotIn("record_lookup", response)
        self.assertEqual(response["regulatory_ai_route"]["agent"]["id"], "workforce_analytics")
        self.assertTrue(response["citations_verified"])
        self.assertFalse(response["model_generated"])
        self.assertFalse(staff_ai_question_needs_knowledge_search(question))
        live_response.assert_not_called()

    @mock.patch("apps.dashboard.staff_ai.maybe_generate_live_staff_response")
    @mock.patch(
        "apps.dashboard.nursing_intelligence.build_nursing_workforce_intelligence_context",
        return_value=NURSING_INTELLIGENCE_FIXTURE,
    )
    def test_rural_under_35_question_never_infers_a_rural_facility_classification(
        self, _intelligence, live_response
    ):
        question = "How many nurses under 35 are working in rural facilities? Include sources."

        response = build_staff_ai_chat_response(self.nursing_user, question, persist=False)

        self.assertEqual(response["title"], "Nursing Rural Under-35 Workforce Measure")
        self.assertIn("not available", response["answer"].lower())
        self.assertIn("will not infer rural status", response["answer"].lower())
        self.assertIn("does not join individual age and workplace records", " ".join(response["bullets"]).lower())
        self.assertTrue(response["citations_verified"])
        self.assertFalse(response["model_generated"])
        self.assertFalse(staff_ai_question_needs_knowledge_search(question))
        live_response.assert_not_called()
        self.assertNotIn("date_of_birth", str(response))
        self.assertNotIn("full_address", str(response))

    @mock.patch("apps.dashboard.staff_ai.maybe_generate_live_staff_response")
    @mock.patch(
        "apps.dashboard.medical_intelligence.build_medical_board_intelligence_context",
        return_value=MEDICAL_INTELLIGENCE_FIXTURE,
    )
    def test_medical_specialist_question_is_fast_aggregate_only_and_cited(self, _intelligence, live_response):
        question = "Show Medical Board specialist distribution and facility accreditation signals."

        response = build_staff_ai_chat_response(self.medical_user, question, persist=False)

        self.assertEqual(response["title"], "Medical Specialist Intelligence")
        self.assertIn("721", response["answer"])
        self.assertIn("Cardiology", " ".join(response["bullets"]))
        self.assertTrue(response["citations_verified"])
        self.assertFalse(response["model_generated"])
        self.assertFalse(staff_ai_question_needs_knowledge_search(question))
        live_response.assert_not_called()
        self.assertNotIn("disciplinary", str(response).lower())
        self.assertNotIn("subject_name", str(response))

    @mock.patch("apps.dashboard.staff_ai.maybe_generate_live_staff_response")
    @mock.patch(
        "apps.dashboard.medical_intelligence.build_medical_board_intelligence_context",
        return_value=MEDICAL_INTELLIGENCE_FIXTURE,
    )
    @mock.patch(
        "apps.dashboard.nursing_intelligence.build_nursing_workforce_intelligence_context",
        return_value=NURSING_INTELLIGENCE_FIXTURE,
    )
    def test_admin_comparison_keeps_nursing_and_medical_intelligence_separate(
        self, _nursing_intelligence, _medical_intelligence, live_response
    ):
        question = "Compare Nursing workforce retirement and Medical Board specialist distribution."

        response = build_staff_ai_chat_response(self.admin_user, question, persist=False)

        self.assertEqual(response["title"], "Separate Regulatory Intelligence Comparison")
        self.assertIn("remain separate regulatory workspaces", response["answer"])
        self.assertGreaterEqual(len(response["sources"]), 2)
        self.assertTrue(any("Nursing" in source["label"] for source in response["sources"]))
        self.assertTrue(any("Medical" in source["label"] for source in response["sources"]))
        self.assertTrue(response["citations_verified"])
        self.assertFalse(response["model_generated"])
        live_response.assert_not_called()
