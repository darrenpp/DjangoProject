import json

from django.test import SimpleTestCase, override_settings

from apps.workforce.services.ai_import_cleanser import local_cleanse_import_row


class ImportCleansingMLIntegrationTests(SimpleTestCase):
    @override_settings(REGULATORY_ML_ENABLED=True)
    def test_local_cleansing_attaches_a_redacted_advisory_without_changing_promotion(self):
        result = local_cleanse_import_row(
            {
                "Full Name": "Amina Kila",
                "Registration No": "RN-100-XY",
                "Record Type": "full",
                "Record Year": "2026",
                "Province": "Morobe",
                "Qualification": "Bachelor of Nursing",
                "Issued Date": "2026-01-15",
            },
            row_number=4,
            source_label="review.xlsx",
        )

        advisory = result["ml_data_quality_advisory"]
        self.assertTrue(advisory["advisory_only"])
        self.assertFalse(advisory["automatic_promotion_allowed"])
        self.assertFalse(advisory["automatic_decision_allowed"])
        self.assertFalse(advisory["privacy"]["raw_values_returned"])
        self.assertTrue(result["ready_for_staging"])
        self.assertNotIn("amina kila", json.dumps(advisory).casefold())
        self.assertNotIn("rn-100-xy", json.dumps(advisory).casefold())
        self.assertNotIn("bachelor of nursing", json.dumps(advisory).casefold())

    @override_settings(REGULATORY_ML_ENABLED=False)
    def test_ml_advisory_can_be_disabled_without_disabling_rule_based_cleansing(self):
        result = local_cleanse_import_row({"Full Name": "Amina Kila"})

        self.assertEqual(result["provider"], "local")
        self.assertNotIn("ml_data_quality_advisory", result)
        self.assertTrue(result["requires_human_review"])
