import json
from datetime import date
from importlib.util import find_spec
from unittest import skipUnless

from django.test import SimpleTestCase, override_settings

from apps.workforce.services.ml_data_quality import (
    assess_staged_record,
    build_optional_compliance_classifier,
    score_compliance_risk,
)


class BoundedDataQualityMLTests(SimpleTestCase):
    def test_duplicate_assessment_is_explainable_but_redacted(self):
        record = {
            "id": 101,
            "full_name": "Amina Kila",
            "registration_no": "RN-100-XY",
            "record_type": "full",
            "record_year": 2026,
            "province": "Morobe",
            "qualification_name": "Bachelor of Nursing",
            "issued_date": "2026-01-15",
        }
        candidate = {
            "id": 102,
            "full_name": "Amina Kila",
            "registration_no": "RN-100-XY",
            "record_type": "full",
            "record_year": 2026,
            "province": "Morobe",
        }

        assessment = assess_staged_record(record, candidates=[candidate], today=date(2026, 7, 25))

        self.assertEqual(assessment["duplicate_risk"]["level"], "high")
        self.assertIn("professional_identifier", assessment["duplicate_risk"]["strongest_match_fields"])
        self.assertTrue(assessment["requires_human_review"])
        self.assertTrue(assessment["advisory_only"])
        self.assertFalse(assessment["automatic_promotion_allowed"])
        self.assertFalse(assessment["automatic_decision_allowed"])
        self.assertFalse(assessment["privacy"]["raw_values_returned"])

        rendered = json.dumps(assessment).casefold()
        self.assertNotIn("amina kila", rendered)
        self.assertNotIn("rn-100-xy", rendered)
        self.assertNotIn("bachelor of nursing", rendered)

    def test_incomplete_summary_row_is_flagged_without_returning_its_values(self):
        record = {
            "full_name": "Spreadsheet Total",
            "record_type": "summary",
            "record_year": 2040,
        }

        assessment = assess_staged_record(record, today=date(2026, 7, 25))

        self.assertEqual(assessment["data_completeness"]["level"], "incomplete")
        self.assertIn("professional_identifier", assessment["data_completeness"]["missing_field_groups"])
        self.assertEqual(assessment["compliance_risk"]["level"], "high")
        self.assertIn(
            "summary_row_requires_human_confirmation",
            assessment["compliance_risk"]["reason_codes"],
        )
        self.assertIn("future_record_year", assessment["compliance_risk"]["reason_codes"])

        rendered = json.dumps(assessment).casefold()
        self.assertNotIn("spreadsheet total", rendered)
        self.assertNotIn("2040", rendered)

    def test_self_candidate_is_not_counted_as_a_duplicate(self):
        record = {
            "id": 11,
            "full_name": "Lina Example",
            "registration_no": "RN-011",
            "record_type": "workforce_listing",
            "record_year": 2026,
            "province": "Gulf",
            "category": "Registered Nurse",
            "nationality": "PNG",
        }

        assessment = assess_staged_record(record, candidates=[record], today=date(2026, 7, 25))

        self.assertEqual(assessment["duplicate_risk"]["candidate_count"], 0)
        self.assertEqual(assessment["duplicate_risk"]["score"], 0)
        self.assertFalse(assessment["requires_human_review"])

    def test_untrusted_classifier_is_ignored_and_rules_remain_available(self):
        record = {
            "record_type": "summary",
            "record_year": 2026,
        }

        result = score_compliance_risk(record, classifier=object(), today=date(2026, 7, 25))

        self.assertEqual(
            result["classifier_advisory"]["reason"],
            "untrusted_classifier_ignored",
        )
        self.assertGreater(result["rule_score"], 0)

    def test_optional_classifier_requires_explicit_approval_and_rejects_sensitive_features(self):
        blocked = build_optional_compliance_classifier(
            [{"features": {"missing_identity": 1}, "label": 1}],
            approved_for_training=False,
        )
        self.assertIsNone(blocked["classifier"])
        self.assertEqual(blocked["reason"], "explicit_approval_required")
        self.assertFalse(blocked["raw_values_accepted"])

        with override_settings(REGULATORY_ML_ALLOW_TRAINING=True):
            rejected = build_optional_compliance_classifier(
                [
                    {"features": {"full_name": "not-permitted"}, "label": 1},
                    {
                        "features": {"missing_identity": 1},
                        "label": 1,
                        "full_name": "also-not-permitted",
                    },
                ],
                approved_for_training=True,
                minimum_examples=2,
            )
        self.assertIsNone(rejected["classifier"])
        self.assertEqual(rejected["accepted_examples"], 0)
        self.assertEqual(rejected["rejected_examples"], 2)
        self.assertEqual(rejected["reason"], "insufficient_approved_redacted_examples")

    @skipUnless(find_spec("sklearn"), "scikit-learn is optional")
    @override_settings(REGULATORY_ML_ALLOW_TRAINING=True)
    def test_approved_redacted_classifier_can_add_an_advisory_signal(self):
        training_examples = [
            {"features": {"missing_identity": 0, "duplicate_score_bucket": 0}, "label": 0},
            {"features": {"missing_identifier": 0, "invalid_date_count": 0}, "label": 0},
            {"features": {"missing_identity": 1, "duplicate_score_bucket": 3}, "label": 1},
            {"features": {"invalid_date_count": 2, "summary_record": 1}, "label": 1},
        ]
        build_result = build_optional_compliance_classifier(
            training_examples,
            approved_for_training=True,
            minimum_examples=4,
        )

        self.assertTrue(build_result["available"])
        self.assertIsNotNone(build_result["classifier"])
        assessment = assess_staged_record(
            {"record_type": "summary", "record_year": 2026},
            classifier=build_result["classifier"],
            today=date(2026, 7, 25),
        )
        classifier_advisory = assessment["compliance_risk"]["classifier_advisory"]
        self.assertTrue(classifier_advisory["used"])
        self.assertIn("model_score", classifier_advisory)
