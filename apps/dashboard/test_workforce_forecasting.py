from copy import deepcopy
from unittest import mock

from django.test import SimpleTestCase, override_settings

from apps.dashboard.workforce_forecasting import (
    APPROVED_AGGREGATE_SERIES_METRICS,
    build_workforce_forecast_context,
    forecast_approved_aggregate_series,
)


NURSING_CONTEXT = {
    "scope": "nursing",
    "practitioner_status": {
        "active_practitioner_count": 1000,
    },
    "age_and_retirement": {
        "available": True,
        "retirement_age": 60,
        "known_age_count": 940,
        "retirement_within_five_years_count": 80,
        "retirement_age_or_older_count": 30,
        "age_band_rows": [
            {"band": "20-30", "count": 200},
            {"band": "31-40", "count": 300},
            {"band": "41-50", "count": 250},
            {"band": "51-60", "count": 160},
            {"band": "60+", "count": 30},
        ],
        # A hostile or accidental identity-bearing addition must never leak
        # through this service.
        "raw_private_example": "Jane Private RN-001 1980-01-01",
    },
    "facility_staffing": {
        "available": True,
        "total_facilities": 42,
        "target_configured_facilities": 7,
        "rows": [
            {
                "facility": "Tari Hospital",
                "province": "Hela",
                "staffing_target": 100,
                "observed_staff_count": 55,
                "gap": 45,
                "gap_status": "reported",
            },
            {
                "facility": "Private Clinic",
                "province": "NCD",
                "staffing_target": 80,
                "observed_staff_count": 80,
                "gap": 0,
                "gap_status": "reported",
            },
        ],
    },
}

MEDICAL_CONTEXT = {
    "scope": "medical",
    "medical_intelligence": {"available": True},
    "medical_executive_metrics": {
        "registered_doctors": 5832,
        "active_practitioners": 4920,
        "specialists": 721,
        "accredited_facilities": 245,
    },
    "medical_specialty_distribution": [
        {"label": "Cardiology", "practitioner_count": 23, "private_name": "Dr Private"},
    ],
    "disciplinary_private_detail": "must never be returned",
}


class WorkforceForecastingTests(SimpleTestCase):
    def test_retirement_projection_is_an_explainable_aggregate_range(self):
        context = build_workforce_forecast_context(
            nursing_context=NURSING_CONTEXT,
            medical_context=MEDICAL_CONTEXT,
            horizon_years=10,
        )

        projection = context["nursing"]["retirement_projection"]
        self.assertTrue(projection["available"])
        self.assertEqual(projection["projection_lower_bound"], 160)
        self.assertEqual(projection["projection_upper_bound"], 190)
        self.assertEqual(projection["age_coverage_percent"], 94.0)
        self.assertEqual(projection["confidence"], "moderate")
        self.assertEqual(projection["method"], "deterministic_age_band_cohort_range")
        self.assertIn("not a guaranteed retirement event", " ".join(projection["assumptions"]))

    def test_low_age_coverage_suppresses_retirement_projection_instead_of_guessing(self):
        nursing = deepcopy(NURSING_CONTEXT)
        nursing["age_and_retirement"]["known_age_count"] = 100

        context = build_workforce_forecast_context(
            nursing_context=nursing,
            medical_context=MEDICAL_CONTEXT,
        )

        projection = context["nursing"]["retirement_projection"]
        self.assertFalse(projection["available"])
        self.assertIsNone(projection["projection_lower_bound"])
        self.assertIn("below the 30% minimum", " ".join(projection["data_quality_reasons"]))

    def test_shortage_signal_uses_only_approved_target_rows_and_hides_facility_names(self):
        context = build_workforce_forecast_context(
            nursing_context=NURSING_CONTEXT,
            medical_context=MEDICAL_CONTEXT,
        )

        signal = context["nursing"]["approved_target_shortage_risk"]
        self.assertTrue(signal["available"])
        self.assertEqual(signal["risk_level"], "high")
        self.assertEqual(signal["approved_target_row_count"], 2)
        self.assertEqual(signal["gap_affected_row_count"], 1)
        self.assertEqual(signal["displayed_target"], 180)
        self.assertEqual(signal["displayed_gap"], 45)
        self.assertEqual(signal["displayed_gap_ratio"], 0.25)
        self.assertNotIn("Tari Hospital", repr(context))
        self.assertNotIn("Private Clinic", repr(context))

    def test_missing_approved_targets_returns_a_data_gap_not_a_shortage_estimate(self):
        nursing = deepcopy(NURSING_CONTEXT)
        nursing["facility_staffing"] = {
            "available": True,
            "total_facilities": 42,
            "target_configured_facilities": 0,
            "rows": [
                {
                    "facility": "Not a target",
                    "observed_staff_count": 55,
                    "gap_status": "target_not_configured",
                },
            ],
        }

        context = build_workforce_forecast_context(
            nursing_context=nursing,
            medical_context=MEDICAL_CONTEXT,
        )

        signal = context["nursing"]["approved_target_shortage_risk"]
        self.assertFalse(signal["available"])
        self.assertEqual(signal["risk_level"], "unavailable")
        self.assertIn("No displayed facility row", " ".join(signal["data_quality_reasons"]))

    def test_optional_local_ml_uses_approved_aggregate_series_only(self):
        forecast = forecast_approved_aggregate_series(
            "nursing_active_practitioners",
            {
                "approved": True,
                "source": "Approved annual Nursing analytics snapshot",
                "points": [
                    {"year": 2022, "value": 100},
                    {"year": 2023, "value": 110},
                    {"year": 2024, "value": 120},
                    {"year": 2025, "value": 130},
                ],
            },
            horizon_years=5,
        )

        self.assertTrue(forecast["available"])
        self.assertEqual(forecast["projected_year"], 2030)
        self.assertEqual(forecast["projected_value"], 180)
        self.assertEqual(forecast["annual_change"], 10.0)
        self.assertIn(
            forecast["method"],
            {"local_sklearn_linear_regression", "deterministic_least_squares_fallback"},
        )
        self.assertTrue(forecast["source_approved"])

    @mock.patch(
        "apps.dashboard.workforce_forecasting._load_sklearn_linear_regression",
        return_value=None,
    )
    def test_deterministic_fallback_does_not_depend_on_scikit_learn(self, _sklearn):
        forecast = forecast_approved_aggregate_series(
            "medical_specialists",
            {
                "approved": True,
                "points": [
                    {"year": 2022, "value": 20},
                    {"year": 2023, "value": 25},
                    {"year": 2024, "value": 30},
                ],
            },
            horizon_years=2,
        )

        self.assertTrue(forecast["available"])
        self.assertEqual(forecast["method"], "deterministic_least_squares_fallback")
        self.assertEqual(forecast["projected_value"], 40)

    @override_settings(REGULATORY_ML_USE_SCIKIT_LEARN=False)
    def test_deployment_can_force_the_deterministic_local_fallback(self):
        forecast = forecast_approved_aggregate_series(
            "medical_specialists",
            {
                "approved": True,
                "points": [
                    {"year": 2022, "value": 20},
                    {"year": 2023, "value": 25},
                    {"year": 2024, "value": 30},
                ],
            },
            horizon_years=2,
        )

        self.assertTrue(forecast["available"])
        self.assertEqual(forecast["method"], "deterministic_least_squares_fallback")

    def test_unapproved_or_non_allowlisted_series_is_rejected(self):
        unapproved = forecast_approved_aggregate_series(
            "nursing_active_practitioners",
            {"approved": False, "points": [{"year": 2024, "value": 100}]},
        )
        rejected_metric = forecast_approved_aggregate_series(
            "individual_staff_records",
            {"approved": True, "points": [{"year": 2022, "value": 1}] * 3},
        )

        self.assertFalse(unapproved["available"])
        self.assertIn("not explicitly marked approved", unapproved["reason"])
        self.assertFalse(rejected_metric["available"])
        self.assertIn("not allow-listed", rejected_metric["reason"])
        self.assertIn("medical_specialists", APPROVED_AGGREGATE_SERIES_METRICS)

    def test_medical_context_remains_aggregate_and_never_becomes_a_shortage_claim(self):
        context = build_workforce_forecast_context(
            nursing_context=NURSING_CONTEXT,
            medical_context=MEDICAL_CONTEXT,
        )

        readiness = context["medical"]["planning_readiness"]
        self.assertTrue(readiness["available"])
        self.assertEqual(readiness["aggregate_baseline"]["specialists"], 721)
        self.assertFalse(readiness["shortage_projection_available"])
        self.assertIn("population denominator", readiness["reason"])
        self.assertNotIn("Dr Private", repr(context))
        self.assertNotIn("disciplinary_private_detail", repr(context))
        self.assertNotIn("Jane Private", repr(context))

    def test_horizon_is_bounded_to_the_validated_cohort_interval(self):
        context = build_workforce_forecast_context(
            nursing_context=NURSING_CONTEXT,
            medical_context=MEDICAL_CONTEXT,
            horizon_years=25,
        )

        self.assertEqual(context["horizon_years"], 10)
        self.assertTrue(any("limited to 10 years" in note for note in context["notices"]))
