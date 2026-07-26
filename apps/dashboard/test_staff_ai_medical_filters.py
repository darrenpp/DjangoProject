from copy import deepcopy
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.dashboard.staff_ai import build_staff_ai_chat_response


MEDICAL_BASE_INTELLIGENCE = {
    "medical_intelligence": {
        "available": True,
        "status": "Live aggregate Medical Board registry intelligence.",
    },
    "medical_intelligence_filter_options": {
        "specialty": ["Cardiology"],
        "province": ["Western"],
        "district": [],
        "facility": [],
        "sector": [],
        "gender": [],
    },
    "medical_executive_metrics": {
        "registered_doctors": 10,
        "active_practitioners": 9,
        "specialists": 23,
        "pending_renewals": 0,
        "open_disciplinary_cases": 0,
    },
    "medical_specialty_distribution": [{"label": "Cardiology", "practitioner_count": 23}],
    "medical_province_distribution": [{"label": "Western", "practitioner_count": 1}],
    "medical_facility_accreditation": {
        "registered_facility_count": 0,
        "source": "approved records",
        "metric_definition": "Aggregate only.",
        "pending_application_count": 0,
    },
    "medical_credential_evidence": {"verified_credential_records": 0, "note": "Aggregate only."},
    "medical_clinical_privileges": {"active_privilege_count": 0, "note": "Aggregate only."},
}


@override_settings(
    AI_ASSISTANT_PROVIDER="local",
    AI_ASSISTANT_OLLAMA_ENABLED=False,
    AI_ASSISTANT_LOCALAI_ENABLED=False,
    AI_ASSISTANT_GOOGLE_ADK_ENABLED=False,
    AI_ASSISTANT_RAG_ENABLED=False,
)
class StaffAIMedicalAggregateFilterTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.medical_user = user_model.objects.create_user(
            username="medical.aggregate.filter",
            password="StrongPass123!",
            role="registrar",
            department="Medical Board",
        )
        self.nursing_user = user_model.objects.create_user(
            username="nursing.aggregate.filter",
            password="StrongPass123!",
            role="registrar",
            department="Nursing Council",
        )

    @mock.patch("apps.dashboard.staff_ai.maybe_generate_live_staff_response")
    @mock.patch("apps.dashboard.medical_intelligence.build_medical_board_intelligence_context")
    def test_cardiologists_in_western_use_exact_filtered_aggregate_answer(self, build_context, live_response):
        filtered = deepcopy(MEDICAL_BASE_INTELLIGENCE)
        filtered["medical_executive_metrics"]["specialists"] = 1
        filtered["medical_specialty_distribution"] = [{"label": "Cardiology", "practitioner_count": 1}]
        filtered["medical_province_distribution"] = [{"label": "Western", "practitioner_count": 1}]
        build_context.side_effect = [deepcopy(MEDICAL_BASE_INTELLIGENCE), filtered]

        response = build_staff_ai_chat_response(
            self.medical_user,
            "How many cardiologists are in Western?",
            persist=False,
        )

        self.assertEqual(response["title"], "Medical Regional Specialist Intelligence")
        self.assertIn("1 Cardiology specialist profile", response["answer"])
        self.assertIn("Western", response["answer"])
        self.assertTrue(response["citations_verified"])
        self.assertFalse(response["model_generated"])
        self.assertEqual(build_context.call_count, 2)
        self.assertEqual(build_context.call_args_list[1].args[0], {
            "specialty": "Cardiology",
            "province": "Western",
        })
        live_response.assert_not_called()
        self.assertNotIn("registration_no", str(response))
        self.assertNotIn("subject_name", str(response))

    @mock.patch("apps.dashboard.staff_ai.maybe_generate_live_staff_response")
    @mock.patch("apps.dashboard.medical_intelligence.build_medical_board_intelligence_context")
    def test_unknown_region_returns_data_gap_without_inventing_count(self, build_context, live_response):
        build_context.return_value = deepcopy(MEDICAL_BASE_INTELLIGENCE)

        response = build_staff_ai_chat_response(
            self.medical_user,
            "How many cardiologists are in Unknown Province?",
            persist=False,
        )

        self.assertEqual(response["title"], "Medical Specialist Intelligence Data Gap")
        self.assertIn("cannot give an exact regional specialist count", response["answer"])
        self.assertNotIn("23", response["answer"])
        self.assertTrue(response["citations_verified"])
        self.assertFalse(response["model_generated"])
        self.assertEqual(build_context.call_count, 1)
        live_response.assert_not_called()

    @mock.patch("apps.dashboard.staff_ai.maybe_generate_live_staff_response")
    @mock.patch("apps.dashboard.medical_intelligence.build_medical_board_intelligence_context")
    def test_nursing_staff_are_blocked_before_medical_aggregate_query(self, build_context, live_response):
        response = build_staff_ai_chat_response(
            self.nursing_user,
            "How many cardiologists are in Western?",
            persist=False,
        )

        self.assertEqual(response["title"], "Office Scope Boundary")
        self.assertIn("Medical Board clinical-regulation intelligence", response["answer"])
        self.assertFalse(response["model_generated"])
        build_context.assert_not_called()
        live_response.assert_not_called()
