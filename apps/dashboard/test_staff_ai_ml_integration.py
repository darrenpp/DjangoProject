from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.dashboard.staff_ai import build_staff_ai_chat_response, staff_ai_question_needs_knowledge_search


FORECAST_FIXTURE = {
    "horizon_years": 10,
    "nursing": {
        "retirement_projection": {
            "available": True,
            "projection_lower_bound": 160,
            "projection_upper_bound": 190,
            "age_coverage_percent": 94.0,
            "known_age_count": 940,
            "active_practitioner_count": 1000,
            "retirement_age": 60,
            "confidence": "moderate",
        },
        "approved_target_shortage_risk": {
            "available": True,
            "risk_level": "high",
            "approved_target_row_count": 2,
            "displayed_gap": 45,
            "displayed_target": 180,
            "displayed_gap_ratio": 0.25,
        },
    },
    "medical": {
        "planning_readiness": {
            "available": True,
            "aggregate_baseline": {
                "active_practitioners": 4920,
                "specialists": 721,
            },
            "reason": "Approved population and establishment baselines are not available.",
        },
    },
}


@override_settings(
    AI_ASSISTANT_PROVIDER="local",
    AI_ASSISTANT_OLLAMA_ENABLED=False,
    AI_ASSISTANT_LOCALAI_ENABLED=False,
    AI_ASSISTANT_GOOGLE_ADK_ENABLED=False,
    AI_ASSISTANT_RAG_ENABLED=False,
    REGULATORY_ML_ENABLED=True,
)
class StaffAIMLIntegrationTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.nursing_user = user_model.objects.create_user(
            username="ml.staff.nursing",
            password="StrongPass123!",
            role="registrar",
            department="Nursing Council",
        )
        self.medical_user = user_model.objects.create_user(
            username="ml.staff.medical",
            password="StrongPass123!",
            role="registrar",
            department="Medical Board",
        )

    @mock.patch("apps.dashboard.staff_ai.maybe_generate_live_staff_response")
    @mock.patch(
        "apps.dashboard.staff_ai._regulatory_ml_forecast_context",
        return_value=FORECAST_FIXTURE,
    )
    def test_nursing_ten_year_forecast_is_fast_cited_and_routed_to_workforce_agent(
        self, _forecast, live_response
    ):
        question = "For Nursing Council, forecast how many nurses may retire in the next 10 years, with sources."

        response = build_staff_ai_chat_response(self.nursing_user, question, persist=False)

        self.assertEqual(response["title"], "Nursing Workforce Retirement Planning Range")
        self.assertIn("160 to 190", response["answer"])
        self.assertIn("not a count", response["answer"])
        self.assertTrue(response["citations_verified"])
        self.assertFalse(response["model_generated"])
        self.assertFalse(staff_ai_question_needs_knowledge_search(question))
        route = response["regulatory_ai_route"]
        self.assertEqual(route["status"], "allowed")
        self.assertEqual(route["agent"]["id"], "workforce_analytics")
        self.assertFalse(route["direct_database_access"])
        self.assertFalse(route["direct_llm_access"])
        self.assertTrue(route["requires_citations"])
        self.assertNotIn("date_of_birth", str(response))
        self.assertNotIn("registration_no", str(response))
        live_response.assert_not_called()

    @mock.patch("apps.dashboard.staff_ai.maybe_generate_live_staff_response")
    @mock.patch(
        "apps.dashboard.staff_ai._regulatory_ml_forecast_context",
        return_value=FORECAST_FIXTURE,
    )
    def test_medical_forecast_withholds_a_shortage_claim_without_approved_need_inputs(
        self, _forecast, live_response
    ):
        response = build_staff_ai_chat_response(
            self.medical_user,
            "Forecast Medical Board doctor shortages over the next ten years.",
            persist=False,
        )

        self.assertEqual(response["title"], "Medical Board Workforce Forecast Readiness")
        self.assertIn("intentionally not issued", response["answer"])
        self.assertIn("4920", response["answer"])
        self.assertEqual(response["regulatory_ai_route"]["agent"]["id"], "workforce_analytics")
        self.assertTrue(all("Nursing Council" not in item["label"] for item in response["sources"]))
        self.assertFalse(response["model_generated"])
        live_response.assert_not_called()

    def test_cross_office_ml_question_is_blocked_before_a_forecast_service_is_called(self):
        with mock.patch("apps.dashboard.staff_ai._regulatory_ml_forecast_context") as forecast:
            response = build_staff_ai_chat_response(
                self.nursing_user,
                "Forecast Medical Board doctor shortages over the next ten years.",
                persist=False,
            )

        self.assertEqual(response["title"], "Office Scope Boundary")
        self.assertEqual(response["regulatory_ai_route"]["status"], "blocked")
        forecast.assert_not_called()
