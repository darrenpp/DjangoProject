"""Bounded, local workforce forecasting from governed aggregate intelligence.

This service deliberately sits *above* the registry rather than querying it.
It consumes only the aggregate payloads returned by ``nursing_intelligence``
and ``medical_intelligence`` (or equivalent approved aggregate snapshots).  It
does not accept or return names, registration numbers, dates of birth,
workplaces, documents, complaints, or any other person-level record.

The first forecasting methods are intentionally explainable:

* a Nursing Council retirement-eligibility cohort range based on governed age
  bands; and
* a current approved-target staffing-risk signal, never an invented facility
  establishment requirement.

An optional in-memory linear-regression helper can forecast an explicitly
approved aggregate time series.  It uses scikit-learn when available and a
mathematically equivalent deterministic least-squares fallback otherwise.
Neither path trains, persists, nor exports a model.  All results remain
decision support requiring human review.
"""

from __future__ import annotations

from datetime import date
from importlib.util import find_spec
import math
from typing import Any, Mapping, Sequence


FORECAST_SERVICE_VERSION = "2026.07.25.1"
DEFAULT_HORIZON_YEARS = 10
MAX_HORIZON_YEARS = 10
MIN_AGE_COVERAGE_FOR_PROJECTION = 0.30
MIN_TREND_POINTS = 3

# The service rejects arbitrary metric names so a future caller cannot slip a
# person-level or ungoverned data series into the forecasting path.
APPROVED_AGGREGATE_SERIES_METRICS = (
    "nursing_active_practitioners",
    "nursing_approved_target_gap",
    "medical_active_practitioners",
    "medical_specialists",
)


def build_workforce_forecast_context(
    *,
    nursing_context: Mapping[str, Any] | None = None,
    medical_context: Mapping[str, Any] | None = None,
    historical_aggregate_series: Mapping[str, Any] | None = None,
    today: date | None = None,
    horizon_years: int = DEFAULT_HORIZON_YEARS,
) -> dict[str, Any]:
    """Return a local, read-only national workforce-planning context.

    ``nursing_context`` and ``medical_context`` should be the respective
    workspace intelligence dictionaries.  Passing them explicitly is useful
    for a pre-approved analytics snapshot and makes it impossible for this
    service to reach around the workspace boundary.  If omitted, the existing
    aggregate-only workspace services are called.

    ``historical_aggregate_series`` is optional and must use the strict form::

        {
            "nursing_active_practitioners": {
                "approved": True,
                "source": "Approved analytics snapshot",
                "points": [{"year": 2023, "value": 100}, ...],
            },
        }

    No caller-provided series is fitted unless it is explicitly marked
    approved.  The return value contains only summary numbers and governance
    metadata; it never includes the source contexts or their row data.
    """

    report_date = today if isinstance(today, date) else date.today()
    normalized_horizon, horizon_notice = _normalise_horizon(horizon_years)
    nursing_context, nursing_source_status = _resolve_nursing_context(nursing_context)
    medical_context, medical_source_status = _resolve_medical_context(medical_context)

    retirement = _nursing_retirement_projection(nursing_context, normalized_horizon)
    shortage = _nursing_shortage_risk_signal(nursing_context)
    medical_readiness = _medical_planning_readiness(medical_context)
    trend_forecasts = _approved_aggregate_trend_forecasts(
        historical_aggregate_series,
        normalized_horizon,
    )

    trend_used_sklearn = any(
        item.get("method") == "local_sklearn_linear_regression"
        for item in trend_forecasts.values()
    )
    notices = [
        "Read-only, aggregate-only workforce decision support. No individual professional, patient, complaint, document, or disciplinary record is used or returned.",
        "Forecasts and risk signals cannot approve, refuse, renew, suspend, employ, credential, accredit, or discipline anyone. A responsible officer must review the governed source evidence before action.",
        "The service does not train on chats, raw registry records, or feedback, and it does not send data to an external AI or analytics provider.",
    ]
    if horizon_notice:
        notices.append(horizon_notice)
    if not retirement["available"]:
        notices.append("Nursing retirement projection is unavailable until sufficient governed age coverage and consistent aggregate age bands are available.")
    if not shortage["available"]:
        notices.append("Nursing shortage risk is unavailable until approved staffing targets are present in governed aggregate facility metrics.")
    if not any(item.get("available") for item in trend_forecasts.values()):
        notices.append("Longitudinal ML trend forecasts remain unavailable until an authorised aggregate time series with at least three annual points is supplied.")

    return {
        "service": "National Health Workforce Forecasting",
        "version": FORECAST_SERVICE_VERSION,
        "generated_for_date": report_date.isoformat(),
        "horizon_years": normalized_horizon,
        "read_only": True,
        "automated_actions_allowed": False,
        "nursing": {
            "source_status": nursing_source_status,
            "retirement_projection": retirement,
            "approved_target_shortage_risk": shortage,
        },
        "medical": {
            "source_status": medical_source_status,
            "planning_readiness": medical_readiness,
        },
        "aggregate_trend_forecasts": trend_forecasts,
        "model_metadata": _model_metadata(
            uses_sklearn=trend_used_sklearn,
            historical_forecasts_available=any(
                item.get("available") for item in trend_forecasts.values()
            ),
        ),
        "governance": {
            "human_review_required": True,
            "automated_decisions_prohibited": True,
            "scope_boundary": (
                "Nursing and Medical aggregate contexts remain separate. This service never joins individual records across regulatory workspaces."
            ),
            "data_retention": "No input context, model fit, prediction history, chat, or feedback is persisted by this service.",
            "approved_data_requirement": (
                "Only approved aggregate intelligence contexts and aggregate time series explicitly marked approved may be used."
            ),
        },
        "notices": notices,
    }


def forecast_approved_aggregate_series(
    metric: str,
    series: Mapping[str, Any] | None,
    *,
    horizon_years: int = DEFAULT_HORIZON_YEARS,
) -> dict[str, Any]:
    """Forecast one allow-listed, approved aggregate annual time series.

    This public helper makes the ML boundary testable and reusable by a future
    authorised analytics worker.  It cannot query operational tables, and it
    will not fit data that lacks the explicit ``approved: True`` marker.
    """

    normalized_horizon, _notice = _normalise_horizon(horizon_years)
    return _forecast_approved_aggregate_series(metric, series, normalized_horizon)


def _resolve_nursing_context(context: Mapping[str, Any] | None) -> tuple[Mapping[str, Any], str]:
    if isinstance(context, Mapping):
        if str(context.get("scope") or "nursing").casefold() not in ("nursing", ""):
            return {}, "Rejected: supplied context is not Nursing Council aggregate intelligence."
        return context, "Supplied governed Nursing Council aggregate context."
    try:
        from apps.dashboard.nursing_intelligence import build_nursing_workforce_intelligence_context

        return build_nursing_workforce_intelligence_context(), "Live governed Nursing Council aggregate context."
    except Exception:
        # The underlying aggregate service already has migration-aware
        # fallbacks.  This final boundary protects an optional forecasting
        # enhancement from ever taking down the staff workspace.
        return {}, "Nursing aggregate intelligence is temporarily unavailable."


def _resolve_medical_context(context: Mapping[str, Any] | None) -> tuple[Mapping[str, Any], str]:
    if isinstance(context, Mapping):
        state = _mapping(context.get("medical_intelligence"))
        if context.get("scope") and str(context.get("scope")).casefold() not in ("medical", ""):
            return {}, "Rejected: supplied context is not Medical Board aggregate intelligence."
        if state and state.get("scope") and str(state.get("scope")).casefold() not in ("medical", ""):
            return {}, "Rejected: supplied context is not Medical Board aggregate intelligence."
        return context, "Supplied governed Medical Board aggregate context."
    try:
        from apps.dashboard.medical_intelligence import build_medical_board_intelligence_context

        return build_medical_board_intelligence_context(), "Live governed Medical Board aggregate context."
    except Exception:
        return {}, "Medical aggregate intelligence is temporarily unavailable."


def _nursing_retirement_projection(
    context: Mapping[str, Any],
    horizon_years: int,
) -> dict[str, Any]:
    """Create a transparent range rather than a false precise retirement count."""

    age = _mapping(context.get("age_and_retirement"))
    practitioner = _mapping(context.get("practitioner_status"))
    active_count = _non_negative_int(practitioner.get("active_practitioner_count")) or 0
    known_age_count = _non_negative_int(age.get("known_age_count")) or 0
    retirement_age = _bounded_int(age.get("retirement_age"), minimum=50, maximum=75) or 60
    near_five = _non_negative_int(age.get("retirement_within_five_years_count")) or 0
    at_or_above = _non_negative_int(age.get("retirement_age_or_older_count")) or 0
    age_band_count = _retirement_band_count(age.get("age_band_rows"), retirement_age)
    age_coverage = _ratio(known_age_count, active_count)

    quality_reasons = []
    if not age.get("available") or known_age_count == 0:
        quality_reasons.append("No governed aggregate age observations are available.")
    if active_count == 0:
        quality_reasons.append("No active-practitioner denominator is available for age-coverage assessment.")
    elif age_coverage is not None and age_coverage < MIN_AGE_COVERAGE_FOR_PROJECTION:
        quality_reasons.append(
            f"Governed age coverage is {_percent(age_coverage)}, below the {int(MIN_AGE_COVERAGE_FOR_PROJECTION * 100)}% minimum for a planning projection."
        )
    if near_five + at_or_above > known_age_count:
        quality_reasons.append("Retirement cohort totals exceed the governed age-observation count and require data-quality review.")
    if age_band_count is None:
        quality_reasons.append(
            f"The aggregate age-band context does not include the band containing retirement age {retirement_age}."
        )
    elif near_five > age_band_count:
        quality_reasons.append("The within-five-years cohort exceeds its containing age band and requires data-quality review.")

    base = {
        "available": False,
        "measure": "Retirement-eligibility cohort range",
        "horizon_years": horizon_years,
        "retirement_age": retirement_age,
        "known_age_count": known_age_count,
        "active_practitioner_count": active_count,
        "age_coverage_ratio": age_coverage,
        "age_coverage_percent": _percent(age_coverage),
        "within_five_years_count": near_five,
        "already_at_or_above_retirement_age_count": at_or_above,
        "retirement_age_band_count": age_band_count,
        "projection_lower_bound": None,
        "projection_upper_bound": None,
        "confidence": "unavailable",
        "method": "deterministic_age_band_cohort_range",
        "data_quality_reasons": quality_reasons,
        "assumptions": [
            "This measures age-based eligibility pressure, not a guaranteed retirement event.",
            "It assumes the configured retirement age remains unchanged during the requested horizon.",
            "It does not assume a professional will leave a facility, province, or the register on reaching retirement age.",
        ],
        "limitations": [
            "No individual dates of birth, names, registrations, or workplaces are used or returned.",
            "Age bands cannot identify the exact age-60 overlap between the retirement-age band and the age-or-older cohort, so the result is a range.",
            "Migration, mortality, new graduates, return-to-work, and policy changes are not modelled.",
        ],
    }
    if quality_reasons:
        return base

    # Ages 55--59 are a discrete, governed five-year pressure cohort.  For a
    # ten-year horizon, everyone in the 51--60 band may be eligible, but the
    # exact age-60 overlap with the 60+ band is unknown.  Reporting a range
    # makes that uncertainty explicit instead of double-counting it.
    if horizon_years <= 5:
        lower = at_or_above
        upper = at_or_above + near_five
    else:
        possible_overlap = min(at_or_above, max(age_band_count - near_five, 0))
        lower = age_band_count + at_or_above - possible_overlap
        upper = age_band_count + at_or_above

    base.update(
        {
            "available": True,
            "projection_lower_bound": lower,
            "projection_upper_bound": upper,
            "confidence": _age_projection_confidence(age_coverage),
            "data_quality_reasons": [],
        }
    )
    return base


def _nursing_shortage_risk_signal(context: Mapping[str, Any]) -> dict[str, Any]:
    """Classify only explicitly approved staffing-target rows.

    The Nursing intelligence service deliberately returns a limited display
    list.  This helper therefore never represents sums from that list as a
    national total or identifies a named facility.
    """

    facility = _mapping(context.get("facility_staffing"))
    rows = facility.get("rows") if isinstance(facility.get("rows"), Sequence) else ()
    valid_rows = []
    rejected_rows = 0
    for row in rows:
        row = _mapping(row)
        if str(row.get("gap_status") or "").casefold() != "reported":
            continue
        target = _non_negative_int(row.get("staffing_target"))
        observed = _non_negative_int(row.get("observed_staff_count"))
        gap = _non_negative_int(row.get("gap"))
        if target is None or observed is None or gap is None or gap != max(target - observed, 0):
            rejected_rows += 1
            continue
        valid_rows.append((target, observed, gap))

    base = {
        "available": False,
        "measure": "Current approved-target staffing risk signal",
        "risk_level": "unavailable",
        "approved_target_row_count": len(valid_rows),
        "gap_affected_row_count": sum(1 for _target, _observed, gap in valid_rows if gap > 0),
        "displayed_row_count": len(rows),
        "total_facilities_in_source": _non_negative_int(facility.get("total_facilities")),
        "target_configured_facilities_in_source": _non_negative_int(facility.get("target_configured_facilities")),
        "displayed_target": None,
        "displayed_observed_staff": None,
        "displayed_gap": None,
        "displayed_gap_ratio": None,
        "forecast_available": False,
        "method": "deterministic_approved_target_gap_classification",
        "data_quality_reasons": [],
        "limitations": [
            "This is a current risk signal, not a future staffing forecast.",
            "Only rows with an explicit approved staffing target are included.",
            "The intelligence context may limit displayed rows, so these values must not be presented as a national total.",
            "Facility, province, professional, and employment identities are intentionally omitted.",
        ],
    }
    if not facility.get("available"):
        base["data_quality_reasons"].append("No governed Nursing facility staffing aggregate is available.")
    if not valid_rows:
        base["data_quality_reasons"].append("No displayed facility row has a valid explicit approved staffing target and matching gap.")
    if rejected_rows:
        base["data_quality_reasons"].append(
            f"{rejected_rows} displayed approved-target row(s) had inconsistent aggregate values and were excluded pending review."
        )
    if not valid_rows:
        return base

    target_total = sum(row[0] for row in valid_rows)
    observed_total = sum(row[1] for row in valid_rows)
    gap_total = sum(row[2] for row in valid_rows)
    gap_ratio = _ratio(gap_total, target_total)
    base.update(
        {
            "available": True,
            "risk_level": _shortage_risk_level(gap_ratio),
            "displayed_target": target_total,
            "displayed_observed_staff": observed_total,
            "displayed_gap": gap_total,
            "displayed_gap_ratio": gap_ratio,
            "data_quality_reasons": base["data_quality_reasons"],
        }
    )
    return base


def _medical_planning_readiness(context: Mapping[str, Any]) -> dict[str, Any]:
    """State exactly what Medical Board aggregate data can and cannot support."""

    state = _mapping(context.get("medical_intelligence"))
    metrics = _mapping(context.get("medical_executive_metrics"))
    available = bool(state.get("available", bool(metrics)))
    baseline = {
        "registered_doctors": _non_negative_int(metrics.get("registered_doctors")) or 0,
        "active_practitioners": _non_negative_int(metrics.get("active_practitioners")) or 0,
        "specialists": _non_negative_int(metrics.get("specialists")) or 0,
        "accredited_facilities": _non_negative_int(metrics.get("accredited_facilities")) or 0,
    }
    return {
        "available": available,
        "aggregate_baseline": baseline,
        "shortage_projection_available": False,
        "reason": (
            "A Medical Board shortage projection needs an approved population denominator, complete facility establishment targets, "
            "and longitudinal aggregate workforce snapshots. The current Medical Board intelligence context does not provide those governed inputs."
        ),
        "limitations": [
            "Specialty and province distributions are not converted into a shortage claim without an approved need baseline.",
            "No clinical privilege, credential, complaint, disciplinary, or professional identity is used for a predictive score.",
            "Use the separate Medical Board aggregate trend series only after it has been approved for forecasting.",
        ],
    }


def _approved_aggregate_trend_forecasts(
    series_by_metric: Mapping[str, Any] | None,
    horizon_years: int,
) -> dict[str, dict[str, Any]]:
    series_by_metric = _mapping(series_by_metric)
    return {
        metric: _forecast_approved_aggregate_series(
            metric,
            _mapping(series_by_metric.get(metric)),
            horizon_years,
        )
        for metric in APPROVED_AGGREGATE_SERIES_METRICS
    }


def _forecast_approved_aggregate_series(
    metric: str,
    series: Mapping[str, Any] | None,
    horizon_years: int,
) -> dict[str, Any]:
    base = {
        "available": False,
        "metric": metric,
        "horizon_years": horizon_years,
        "method": "unavailable",
        "source_approved": False,
        "point_count": 0,
        "latest_observed_year": None,
        "latest_observed_value": None,
        "projected_year": None,
        "projected_value": None,
        "annual_change": None,
        "fit_r_squared": None,
        "confidence": "unavailable",
        "reason": "No approved aggregate historical series was supplied.",
        "limitations": [
            "Only annual aggregate counts are accepted; individual records and raw import rows are rejected by design.",
            "A linear trend is a planning scenario, not a causal forecast or an automatic policy recommendation.",
        ],
    }
    if metric not in APPROVED_AGGREGATE_SERIES_METRICS:
        base["reason"] = "Metric is not allow-listed for aggregate workforce forecasting."
        return base
    series = _mapping(series)
    if series.get("approved") is not True:
        base["reason"] = "The aggregate series is not explicitly marked approved for forecasting."
        return base
    base["source_approved"] = True
    points, point_reason = _normalise_series_points(series.get("points"))
    base["point_count"] = len(points)
    if point_reason:
        base["reason"] = point_reason
        return base
    if len(points) < MIN_TREND_POINTS:
        base["reason"] = f"At least {MIN_TREND_POINTS} approved annual aggregate points are required for a trend forecast."
        return base

    years = [year for year, _value in points]
    values = [value for _year, value in points]
    base["latest_observed_year"] = years[-1]
    base["latest_observed_value"] = values[-1]
    fitted = _fit_local_linear_trend(years, values, horizon_years)
    if fitted is None:
        base["reason"] = "The approved aggregate series could not be fitted safely."
        return base

    base.update(
        {
            "available": True,
            "method": fitted["method"],
            "projected_year": years[-1] + horizon_years,
            "projected_value": fitted["projected_value"],
            "annual_change": fitted["annual_change"],
            "fit_r_squared": fitted["r_squared"],
            "confidence": _trend_confidence(
                point_count=len(points),
                r_squared=fitted["r_squared"],
                has_year_gaps=_has_year_gaps(years),
            ),
            "reason": "Local aggregate trend projection from approved annual points.",
        }
    )
    return base


def _normalise_series_points(raw_points: Any) -> tuple[list[tuple[int, float]], str]:
    if not isinstance(raw_points, Sequence) or isinstance(raw_points, (str, bytes)):
        return [], "Approved aggregate series has no valid annual points."
    normalized: dict[int, float] = {}
    for raw_point in raw_points:
        point = _mapping(raw_point)
        year = _bounded_int(point.get("year"), minimum=1900, maximum=2100)
        value = _non_negative_number(point.get("value"))
        if year is None or value is None:
            return [], "Approved aggregate series contains an invalid year or non-negative value."
        if year in normalized:
            return [], "Approved aggregate series contains duplicate years and requires data-quality review."
        normalized[year] = value
    return sorted(normalized.items()), ""


def _fit_local_linear_trend(
    years: Sequence[int],
    values: Sequence[float],
    horizon_years: int,
) -> dict[str, Any] | None:
    """Fit locally, preferring sklearn but never depending on it at runtime."""

    x_values = [year - years[0] for year in years]
    model_class = _load_sklearn_linear_regression()
    try:
        if model_class is not None:
            model = model_class()
            model.fit([[value] for value in x_values], list(values))
            slope = float(model.coef_[0])
            intercept = float(model.intercept_)
            method = "local_sklearn_linear_regression"
        else:
            slope, intercept = _deterministic_least_squares(x_values, values)
            method = "deterministic_least_squares_fallback"
    except (ArithmeticError, TypeError, ValueError):
        return None

    target_x = x_values[-1] + horizon_years
    raw_projection = intercept + (slope * target_x)
    if not all(math.isfinite(value) for value in (slope, intercept, raw_projection)):
        return None
    fitted_values = [intercept + (slope * value) for value in x_values]
    return {
        "method": method,
        "annual_change": _round_number(slope),
        "projected_value": max(0, int(round(raw_projection))),
        "r_squared": _round_number(_r_squared(values, fitted_values), digits=3),
    }


def _load_sklearn_linear_regression():
    """Return sklearn's local estimator when installed, otherwise ``None``."""

    try:
        from django.conf import settings

        if not bool(getattr(settings, "REGULATORY_ML_USE_SCIKIT_LEARN", True)):
            return None
        from sklearn.linear_model import LinearRegression

        return LinearRegression
    except Exception:
        # scikit-learn is deliberately optional: deployments can use the same
        # deterministic aggregate algorithm without adding a heavy runtime.
        return None


def _deterministic_least_squares(
    x_values: Sequence[float], values: Sequence[float]
) -> tuple[float, float]:
    count = len(x_values)
    mean_x = sum(x_values) / count
    mean_y = sum(values) / count
    denominator = sum((value - mean_x) ** 2 for value in x_values)
    if denominator == 0:
        raise ValueError("Annual aggregate series requires distinct years.")
    slope = sum(
        (x_value - mean_x) * (y_value - mean_y)
        for x_value, y_value in zip(x_values, values)
    ) / denominator
    return slope, mean_y - (slope * mean_x)


def _r_squared(observed: Sequence[float], fitted: Sequence[float]) -> float:
    mean_observed = sum(observed) / len(observed)
    total = sum((value - mean_observed) ** 2 for value in observed)
    if total == 0:
        return 1.0
    residual = sum((actual - estimate) ** 2 for actual, estimate in zip(observed, fitted))
    return max(0.0, min(1.0, 1.0 - (residual / total)))


def _retirement_band_count(rows: Any, retirement_age: int) -> int | None:
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return None
    for raw_row in rows:
        row = _mapping(raw_row)
        label = str(row.get("band") or "").strip().replace(" ", "")
        if "-" not in label:
            continue
        lower_text, upper_text = label.split("-", 1)
        lower = _bounded_int(lower_text, minimum=0, maximum=120)
        upper = _bounded_int(upper_text, minimum=0, maximum=120)
        if lower is not None and upper is not None and lower <= retirement_age <= upper:
            return _non_negative_int(row.get("count"))
    return None


def _age_projection_confidence(age_coverage: float | None) -> str:
    if age_coverage is None or age_coverage < MIN_AGE_COVERAGE_FOR_PROJECTION:
        return "unavailable"
    if age_coverage >= 0.80:
        return "moderate"
    if age_coverage >= 0.50:
        return "limited"
    return "low"


def _shortage_risk_level(gap_ratio: float | None) -> str:
    if gap_ratio is None:
        return "unavailable"
    if gap_ratio >= 0.40:
        return "critical"
    if gap_ratio >= 0.25:
        return "high"
    if gap_ratio >= 0.10:
        return "moderate"
    return "low"


def _trend_confidence(*, point_count: int, r_squared: float, has_year_gaps: bool) -> str:
    if point_count >= 5 and r_squared >= 0.70 and not has_year_gaps:
        return "moderate"
    if point_count >= 4 and r_squared >= 0.40:
        return "limited"
    return "low"


def _has_year_gaps(years: Sequence[int]) -> bool:
    return any(next_year - year > 1 for year, next_year in zip(years, years[1:]))


def _model_metadata(*, uses_sklearn: bool, historical_forecasts_available: bool) -> dict[str, Any]:
    return {
        "name": "Local Explainable Workforce Forecasting",
        "version": FORECAST_SERVICE_VERSION,
        "execution": "In-process local service; no external AI, vector database, or model gateway is called.",
        "scikit_learn_available": _scikit_learn_available(),
        "scikit_learn_used": uses_sklearn,
        "historical_ml_forecasts_available": historical_forecasts_available,
        "training": (
            "No persistent model training occurs. Optional linear regression is fit in memory to a supplied approved aggregate annual series and discarded with the response."
        ),
        "features": (
            "Aggregate age-band cohorts, approved aggregate staffing targets and counts, and explicitly approved annual aggregate time series only."
        ),
        "excluded_features": (
            "Names, registrations, contact details, dates of birth, documents, clinical details, complaints, disciplinary data, raw imports, chats, and feedback."
        ),
        "validation_requirement": (
            "Evaluate forecast accuracy and source completeness on a reviewed aggregate test set before any model promotion or policy use."
        ),
    }


def _scikit_learn_available() -> bool:
    try:
        return find_spec("sklearn") is not None
    except (ImportError, ValueError):
        return False


def _normalise_horizon(value: Any) -> tuple[int, str]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_HORIZON_YEARS
    normalized = max(1, min(parsed, MAX_HORIZON_YEARS))
    if normalized != parsed:
        return normalized, (
            f"Requested horizon was limited to {MAX_HORIZON_YEARS} years because the initial cohort method is not validated beyond that interval."
        )
    return normalized, ""


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _non_negative_int(value: Any) -> int | None:
    numeric = _non_negative_number(value)
    if numeric is None or not float(numeric).is_integer():
        return None
    return int(numeric)


def _non_negative_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric) or numeric < 0 or numeric > 1_000_000_000:
        return None
    return numeric


def _bounded_int(value: Any, *, minimum: int, maximum: int) -> int | None:
    numeric = _non_negative_int(value)
    if numeric is None or not minimum <= numeric <= maximum:
        return None
    return numeric


def _ratio(numerator: int | float | None, denominator: int | float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return round(float(numerator) / float(denominator), 4)


def _percent(value: float | None) -> float | None:
    return None if value is None else round(value * 100, 1)


def _round_number(value: float, *, digits: int = 2) -> float:
    return round(float(value), digits)
