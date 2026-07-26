import io
import json
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings


PIPELINE_FIXTURE = {
    "nursing": {"retirement_projection": {"available": True}},
    "medical": {"planning_readiness": {"available": False}},
    "model_metadata": {"name": "Local Explainable Workforce Forecasting"},
}


class RegulatoryMLPipelineCommandTests(SimpleTestCase):
    @override_settings(REGULATORY_ML_ENABLED=True)
    @mock.patch(
        "apps.dashboard.management.commands.run_regulatory_ml_pipeline.build_nursing_workforce_intelligence_context",
        return_value={"scope": "nursing"},
    )
    @mock.patch(
        "apps.dashboard.management.commands.run_regulatory_ml_pipeline.build_workforce_forecast_context",
        return_value=PIPELINE_FIXTURE,
    )
    def test_scoped_pipeline_uses_only_nursing_context_and_emits_redacted_snapshot(
        self, forecast, _nursing
    ):
        output = io.StringIO()

        call_command("run_regulatory_ml_pipeline", "--scope", "nursing", "--json", stdout=output)

        payload = json.loads(output.getvalue())
        self.assertEqual(payload["requested_scope"], "nursing")
        self.assertTrue(payload["pipeline"]["read_only"])
        self.assertFalse(payload["pipeline"]["registry_writes"])
        self.assertFalse(payload["pipeline"]["raw_chat_training"])
        self.assertFalse(payload["pipeline"]["raw_registry_training"])
        self.assertEqual(forecast.call_args.kwargs["medical_context"], {})
        self.assertNotIn("raw_payload", json.dumps(payload))

    @override_settings(REGULATORY_ML_ENABLED=False)
    def test_disabled_ml_does_not_run_a_snapshot(self):
        with self.assertRaisesMessage(CommandError, "REGULATORY_ML_ENABLED is False"):
            call_command("run_regulatory_ml_pipeline")
