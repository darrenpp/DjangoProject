"""Bounded, explainable data-quality scoring for staged registry data.

This module intentionally has no database queries and no write operations.  It is
designed for use *before* a row is promoted from an import/staging workflow, and
returns advisory signals only.  In particular, it never returns source values
such as names, registration numbers, dates of birth, email addresses, or raw
payloads.

The optional scikit-learn classifier is deliberately opt-in.  It accepts only
reviewed, redacted numeric feature vectors, and can only raise a review signal;
it cannot clear a record or make an approval decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
import re
from typing import Any, Iterable, Mapping


SERVICE_NAME = "bounded_data_quality_ml"
SERVICE_VERSION = "1.0"

# These are the only values an optional classifier is allowed to receive.  They
# are derived counts/flags, rather than direct or quasi-identifying data.
SAFE_CLASSIFIER_FEATURES = (
    "missing_identity",
    "missing_identifier",
    "missing_required_dates",
    "invalid_date_count",
    "future_date_count",
    "duplicate_score_bucket",
    "summary_record",
    "invalid_target_model",
    "origin_conflict",
    "expired_or_expiring_licence",
)

_SENSITIVE_TRAINING_KEYS = frozenset(
    {
        "name",
        "full_name",
        "first_name",
        "middle_name",
        "last_name",
        "registration_no",
        "registration_number",
        "practitioner_number",
        "licence_number",
        "license_number",
        "date_of_birth",
        "email",
        "phone",
        "primary_phone",
        "address",
        "workplace_address",
        "raw_payload",
    }
)

_PLACEHOLDER_VALUES = frozenset(
    {
        "",
        "-",
        "--",
        "n/a",
        "na",
        "none",
        "null",
        "unknown",
        "tba",
        "tbd",
        "not available",
    }
)

_VALID_RECORD_TYPES = frozenset(
    {
        "provisional",
        "full",
        "full_approved",
        "temporary",
        "practicing_license",
        "payment",
        "workforce_listing",
        "summary",
    }
)

_VALID_TARGET_MODELS = frozenset(
    {
        "nursingprofessional",
        "midwife",
        "medicaldoctor",
        "communityhealthworker",
        "nurseaide",
        "healthstudent",
        "other",
    }
)

_IDENTIFIER_FIELDS = (
    "registration_no",
    "registration_number",
    "practitioner_number",
    "licence_number",
    "license_number",
)

_RECORD_FIELD_ALIASES = {
    "full_name": ("full_name", "name", "fullname"),
    "first_name": ("first_name", "given_name"),
    "middle_name": ("middle_name",),
    "last_name": ("last_name", "surname", "family_name"),
    "registration_no": ("registration_no", "registration_number"),
    "practitioner_number": ("practitioner_number",),
    "record_type": ("record_type",),
    "target_model": ("target_model",),
    "record_year": ("record_year", "year"),
    "province": ("province",),
    "category": ("category", "cadre"),
    "qualification_name": ("qualification_name", "qualification"),
    "applicant_type": ("applicant_type",),
    "nationality": ("nationality",),
    "date_of_birth": ("date_of_birth", "dob"),
    "issued_date": ("issued_date", "date_issued", "registration_date"),
    "payment_date": ("payment_date",),
    "license_expiry_date": ("license_expiry_date", "licence_expiry_date"),
}


def _value(record: Mapping[str, Any] | Any, field: str, default: Any = "") -> Any:
    """Read a conventional field name from a mapping or model-like object."""
    for alias in _RECORD_FIELD_ALIASES.get(field, (field,)):
        if isinstance(record, Mapping):
            value = record.get(alias, None)
        else:
            value = getattr(record, alias, None)
        if value is not None:
            return value
    return default


def _normalise_text(value: Any) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).strip().split())
    if text.casefold() in _PLACEHOLDER_VALUES:
        return ""
    return text.casefold()


def _normalise_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _normalise_text(value)).strip()


def _is_present(value: Any) -> bool:
    if isinstance(value, str):
        return bool(_normalise_text(value))
    return value is not None


def _record_name(record: Mapping[str, Any] | Any) -> str:
    full_name = _value(record, "full_name")
    if _is_present(full_name):
        return _normalise_name(full_name)
    return _normalise_name(
        " ".join(
            str(_value(record, field, ""))
            for field in ("first_name", "middle_name", "last_name")
            if _is_present(_value(record, field, ""))
        )
    )


def _identifier_values(record: Mapping[str, Any] | Any) -> dict[str, str]:
    values: dict[str, str] = {}
    for field in _IDENTIFIER_FIELDS:
        value = _value(record, field, "")
        normalised = re.sub(r"\s+", "", _normalise_text(value)).upper()
        if normalised:
            values[field] = normalised
    return values


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _normalise_text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _normalise_choice(record: Mapping[str, Any] | Any, field: str) -> str:
    return _normalise_text(_value(record, field, ""))


def _score_level(score: int, *, low: int = 25, medium: int = 55, high: int = 85) -> str:
    if score >= high:
        return "high"
    if score >= medium:
        return "medium"
    if score >= low:
        return "low"
    return "none"


def _completeness_level(score: int) -> str:
    if score >= 85:
        return "complete"
    if score >= 60:
        return "partially_complete"
    return "incomplete"


def _record_requirements(record: Mapping[str, Any] | Any) -> list[tuple[str, bool, int]]:
    """Return the field groups expected for a staged/imported row.

    The result deliberately contains field-group names rather than values so it
    can be included in an advisory response without exposing personal data.
    """
    record_type = _normalise_choice(record, "record_type")
    requirements = [
        ("person_name", bool(_record_name(record)), 25),
        ("professional_identifier", bool(_identifier_values(record)), 30),
        ("record_year", _is_present(_value(record, "record_year", None)), 15),
        ("province", _is_present(_value(record, "province", None)), 10),
    ]
    if record_type in {"provisional", "full", "full_approved", "temporary"}:
        requirements.extend(
            [
                ("qualification", _is_present(_value(record, "qualification_name", None)), 10),
                ("issued_date", _is_present(_value(record, "issued_date", None)), 10),
            ]
        )
    elif record_type in {"practicing_license", "payment"}:
        requirements.extend(
            [
                ("payment_date", _is_present(_value(record, "payment_date", None)), 20),
                (
                    "applicant_origin",
                    _is_present(_value(record, "applicant_type", None))
                    or _is_present(_value(record, "nationality", None)),
                    10,
                ),
            ]
        )
    else:
        requirements.extend(
            [
                ("category", _is_present(_value(record, "category", None)), 10),
                (
                    "applicant_origin",
                    _is_present(_value(record, "applicant_type", None))
                    or _is_present(_value(record, "nationality", None)),
                    10,
                ),
            ]
        )
    return requirements


def score_data_completeness(record: Mapping[str, Any] | Any) -> dict[str, Any]:
    """Score whether a staged/imported record has expected field groups.

    The response contains only field names and aggregate score data; source
    values are intentionally omitted.
    """
    requirements = _record_requirements(record)
    total_weight = sum(weight for _field, _present, weight in requirements)
    present_weight = sum(weight for _field, present, weight in requirements if present)
    score = int(round((100 * present_weight / total_weight) if total_weight else 0))
    missing_fields = [field for field, present, _weight in requirements if not present]
    return {
        "score": score,
        "level": _completeness_level(score),
        "missing_field_groups": missing_fields,
        "assessed_field_groups": [field for field, _present, _weight in requirements],
    }


def _record_id(record: Mapping[str, Any] | Any) -> Any:
    if isinstance(record, Mapping):
        return record.get("pk", record.get("id"))
    return getattr(record, "pk", getattr(record, "id", None))


def _same_record(source: Mapping[str, Any] | Any, candidate: Mapping[str, Any] | Any) -> bool:
    source_id = _record_id(source)
    candidate_id = _record_id(candidate)
    return source_id is not None and candidate_id is not None and source_id == candidate_id


def _candidate_duplicate_score(source: Mapping[str, Any] | Any, candidate: Mapping[str, Any] | Any) -> tuple[int, list[str], list[str]]:
    """Compare two rows internally and return redacted evidence labels only."""
    score = 0
    matched_fields: list[str] = []
    reason_codes: list[str] = []

    source_identifiers = _identifier_values(source)
    candidate_identifiers = _identifier_values(candidate)
    exact_identifier_match = False
    for source_field, source_value in source_identifiers.items():
        for candidate_field, candidate_value in candidate_identifiers.items():
            if source_value and source_value == candidate_value:
                exact_identifier_match = True
                score += 80
                matched_fields.append("professional_identifier")
                reason_codes.append("exact_professional_identifier_match")
                break
        if exact_identifier_match:
            break

    source_name = _record_name(source)
    candidate_name = _record_name(candidate)
    if source_name and candidate_name:
        similarity = SequenceMatcher(None, source_name, candidate_name).ratio()
        if similarity == 1.0:
            score += 40
            matched_fields.append("person_name")
            reason_codes.append("exact_name_match")
        elif similarity >= 0.92:
            score += 35
            matched_fields.append("person_name")
            reason_codes.append("strong_name_similarity")
        elif similarity >= 0.82:
            score += 22
            matched_fields.append("person_name")
            reason_codes.append("moderate_name_similarity")

    source_dob = _parse_date(_value(source, "date_of_birth", None))
    candidate_dob = _parse_date(_value(candidate, "date_of_birth", None))
    if source_dob and candidate_dob and source_dob == candidate_dob:
        score += 15
        matched_fields.append("date_of_birth")
        reason_codes.append("matching_date_of_birth")

    for field, points in (("province", 5), ("category", 5), ("target_model", 4)):
        source_value = _normalise_choice(source, field)
        candidate_value = _normalise_choice(candidate, field)
        if source_value and candidate_value and source_value == candidate_value:
            score += points
            matched_fields.append(field)
            reason_codes.append(f"matching_{field}")

    return min(score, 100), list(dict.fromkeys(matched_fields)), list(dict.fromkeys(reason_codes))


def score_duplicate_risk(
    record: Mapping[str, Any] | Any,
    candidates: Iterable[Mapping[str, Any] | Any] = (),
) -> dict[str, Any]:
    """Return an explainable duplicate-risk signal without candidate identities."""
    candidate_count = 0
    strongest_score = 0
    strongest_fields: list[str] = []
    strongest_reasons: list[str] = []
    for candidate in candidates:
        if _same_record(record, candidate):
            continue
        candidate_count += 1
        score, fields, reasons = _candidate_duplicate_score(record, candidate)
        if score > strongest_score:
            strongest_score = score
            strongest_fields = fields
            strongest_reasons = reasons

    return {
        "score": strongest_score,
        "level": _score_level(strongest_score),
        "candidate_count": candidate_count,
        "strongest_match_fields": strongest_fields,
        "reason_codes": strongest_reasons,
    }


def _date_validation_codes(record: Mapping[str, Any] | Any, today: date) -> list[str]:
    codes: list[str] = []
    date_fields = ("date_of_birth", "issued_date", "payment_date", "license_expiry_date")
    for field in date_fields:
        raw_value = _value(record, field, None)
        if not _is_present(raw_value):
            continue
        parsed = _parse_date(raw_value)
        if not parsed:
            codes.append(f"unparseable_{field}")
            continue
        if field != "license_expiry_date" and parsed > today:
            codes.append(f"future_{field}")
        if field == "date_of_birth":
            age = today.year - parsed.year - ((today.month, today.day) < (parsed.month, parsed.day))
            if age < 16:
                codes.append("date_of_birth_below_minimum_practice_age")
            elif age > 90:
                codes.append("date_of_birth_above_expected_practice_age")
        if field == "license_expiry_date":
            if parsed < today:
                codes.append("licence_expired")
            elif parsed <= today + timedelta(days=30):
                codes.append("licence_expiring_soon")
    return list(dict.fromkeys(codes))


def _record_validation_codes(record: Mapping[str, Any] | Any, today: date) -> list[str]:
    codes = _date_validation_codes(record, today)
    record_type = _normalise_choice(record, "record_type")
    if record_type == "summary":
        codes.append("summary_row_requires_human_confirmation")
    elif record_type and record_type not in _VALID_RECORD_TYPES:
        codes.append("invalid_record_type")

    target_model = _normalise_choice(record, "target_model")
    if target_model and target_model not in _VALID_TARGET_MODELS:
        codes.append("invalid_target_model")

    raw_year = _value(record, "record_year", None)
    if _is_present(raw_year):
        try:
            record_year = int(raw_year)
        except (TypeError, ValueError):
            codes.append("invalid_record_year")
        else:
            if record_year > today.year + 1:
                codes.append("future_record_year")
            elif record_year < 1950:
                codes.append("record_year_before_supported_range")

    applicant_type = _normalise_choice(record, "applicant_type")
    nationality = _normalise_choice(record, "nationality")
    if applicant_type and applicant_type not in {"national", "overseas"}:
        codes.append("invalid_applicant_type")
    is_png_nationality = nationality in {"png", "papua new guinea"} or "papua new guinea" in nationality
    if applicant_type == "national" and nationality and not is_png_nationality:
        codes.append("applicant_origin_conflict")
    elif applicant_type == "overseas" and is_png_nationality:
        codes.append("applicant_origin_conflict")
    return list(dict.fromkeys(codes))


def _safe_feature_vector(
    completeness: Mapping[str, Any],
    duplicate_risk: Mapping[str, Any],
    validation_codes: Iterable[str],
) -> dict[str, float]:
    codes = set(validation_codes)
    missing = set(completeness.get("missing_field_groups", ()))
    invalid_date_codes = {code for code in codes if "date" in code or "licence_" in code}
    future_date_codes = {code for code in codes if code.startswith("future_") and code != "future_record_year"}
    return {
        "missing_identity": float("person_name" in missing),
        "missing_identifier": float("professional_identifier" in missing),
        "missing_required_dates": float(len({"issued_date", "payment_date"} & missing)),
        "invalid_date_count": float(min(3, len(invalid_date_codes))),
        "future_date_count": float(min(3, len(future_date_codes))),
        "duplicate_score_bucket": float(min(4, int(duplicate_risk.get("score", 0)) // 25)),
        "summary_record": float("summary_row_requires_human_confirmation" in codes),
        "invalid_target_model": float("invalid_target_model" in codes),
        "origin_conflict": float("applicant_origin_conflict" in codes),
        "expired_or_expiring_licence": float(
            bool({"licence_expired", "licence_expiring_soon"} & codes)
        ),
    }


@dataclass(frozen=True)
class OptionalComplianceClassifier:
    """A wrapper around an approved sklearn estimator and redacted features."""

    estimator: Any
    feature_names: tuple[str, ...] = SAFE_CLASSIFIER_FEATURES

    def predict_risk(self, safe_features: Mapping[str, float]) -> int:
        vector = [[float(safe_features.get(field, 0.0)) for field in self.feature_names]]
        if hasattr(self.estimator, "predict_proba"):
            probability = float(self.estimator.predict_proba(vector)[0][-1])
            return max(0, min(100, int(round(probability * 100))))
        prediction = self.estimator.predict(vector)[0]
        return 100 if bool(prediction) else 0


def _normalise_classifier_label(value: Any) -> int | None:
    if value is True or value == 1 or value in ("1", "high_risk", "review_required", "yes"):
        return 1
    if value is False or value == 0 or value in ("0", "low_risk", "no_review", "no"):
        return 0
    return None


def _training_configuration() -> tuple[bool, int]:
    """Read deployment controls without coupling scoring to Django models."""

    try:
        from django.conf import settings

        enabled = bool(getattr(settings, "REGULATORY_ML_ALLOW_TRAINING", False))
        minimum = int(getattr(settings, "REGULATORY_ML_MIN_TRAINING_OBSERVATIONS", 12) or 12)
    except Exception:
        enabled = False
        minimum = 12
    return enabled, max(2, minimum)


def build_optional_compliance_classifier(
    training_examples: Iterable[Mapping[str, Any]],
    *,
    approved_for_training: bool = False,
    minimum_examples: int | None = None,
) -> dict[str, Any]:
    """Build an optional sklearn model from explicitly approved redacted data.

    ``training_examples`` must contain a ``features`` mapping using *only*
    :data:`SAFE_CLASSIFIER_FEATURES` and a binary ``label``.  Raw records,
    chat logs, and personal fields are rejected.  The returned model remains
    advisory-only and is never persisted by this service.
    """
    base_result: dict[str, Any] = {
        "classifier": None,
        "available": False,
        "approved_for_training": bool(approved_for_training),
        "feature_names": list(SAFE_CLASSIFIER_FEATURES),
        "accepted_examples": 0,
        "rejected_examples": 0,
        "advisory_only": True,
        "raw_values_accepted": False,
    }
    training_enabled, configured_minimum = _training_configuration()
    if not approved_for_training:
        return {**base_result, "reason": "explicit_approval_required"}
    if not training_enabled:
        return {**base_result, "reason": "deployment_training_disabled"}

    vectors: list[list[float]] = []
    labels: list[int] = []
    rejected = 0
    for example in training_examples:
        if not isinstance(example, Mapping):
            rejected += 1
            continue
        # The reviewed dataset itself must be redacted as well as the feature
        # vector.  No provenance, record reference, chat text, or raw row is
        # accepted by this deliberately narrow training interface.
        if set(example) - {"features", "label"}:
            rejected += 1
            continue
        features = example.get("features")
        label = _normalise_classifier_label(example.get("label"))
        if not isinstance(features, Mapping) or label is None:
            rejected += 1
            continue
        keys = {str(key) for key in features}
        if keys & _SENSITIVE_TRAINING_KEYS or not keys.issubset(SAFE_CLASSIFIER_FEATURES):
            rejected += 1
            continue
        try:
            vector = [float(features.get(field, 0.0)) for field in SAFE_CLASSIFIER_FEATURES]
        except (TypeError, ValueError):
            rejected += 1
            continue
        vectors.append(vector)
        labels.append(label)

    base_result["accepted_examples"] = len(vectors)
    base_result["rejected_examples"] = rejected
    minimum_examples = configured_minimum if minimum_examples is None else max(2, int(minimum_examples))
    if len(vectors) < minimum_examples:
        return {**base_result, "reason": "insufficient_approved_redacted_examples"}
    if len(set(labels)) < 2:
        return {**base_result, "reason": "both_outcome_classes_required"}

    try:
        from sklearn.ensemble import RandomForestClassifier
    except (ImportError, ModuleNotFoundError):
        return {**base_result, "reason": "sklearn_unavailable"}

    try:
        estimator = RandomForestClassifier(
            n_estimators=48,
            random_state=17,
            max_depth=4,
            class_weight="balanced",
        )
        estimator.fit(vectors, labels)
    except Exception:
        # Training cannot be allowed to block an import review.  Do not expose
        # the exception because it may contain implementation details.
        return {**base_result, "reason": "classifier_training_unavailable"}

    return {
        **base_result,
        "classifier": OptionalComplianceClassifier(estimator=estimator),
        "available": True,
        "reason": "approved_redacted_classifier_ready",
    }


def _classifier_advisory(
    classifier: Any,
    safe_features: Mapping[str, float],
) -> dict[str, Any]:
    if classifier is None:
        return {"used": False, "reason": "deterministic_rules"}
    if not isinstance(classifier, OptionalComplianceClassifier):
        return {"used": False, "reason": "untrusted_classifier_ignored"}
    try:
        score = classifier.predict_risk(safe_features)
    except Exception:
        return {"used": False, "reason": "classifier_prediction_unavailable"}
    return {
        "used": True,
        "model_score": score,
        "reason": "approved_redacted_classifier_advisory",
    }


def score_compliance_risk(
    record: Mapping[str, Any] | Any,
    *,
    completeness: Mapping[str, Any] | None = None,
    duplicate_risk: Mapping[str, Any] | None = None,
    classifier: OptionalComplianceClassifier | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Score compliance-review risk using rules plus an optional safe model.

    A classifier can only contribute an additional review signal.  Rule-based
    flags always remain visible and no score is treated as clearance or an
    approval.
    """
    today = today or date.today()
    completeness = completeness or score_data_completeness(record)
    duplicate_risk = duplicate_risk or score_duplicate_risk(record)
    validation_codes = _record_validation_codes(record, today)
    missing = set(completeness.get("missing_field_groups", ()))

    rule_score = 0
    reason_codes: list[str] = []
    if "person_name" in missing:
        rule_score += 28
        reason_codes.append("missing_person_name")
    if "professional_identifier" in missing:
        rule_score += 28
        reason_codes.append("missing_professional_identifier")
    if "issued_date" in missing or "payment_date" in missing:
        rule_score += 12
        reason_codes.append("missing_required_legal_date")
    if completeness.get("score", 100) < 60:
        rule_score += 12
        reason_codes.append("low_data_completeness")

    for code in validation_codes:
        if code == "summary_row_requires_human_confirmation":
            rule_score += 55
        elif code in {"invalid_record_type", "invalid_target_model", "invalid_record_year"}:
            rule_score += 25
        elif code in {"future_record_year", "record_year_before_supported_range"}:
            rule_score += 20
        elif code == "applicant_origin_conflict":
            rule_score += 20
        elif code == "licence_expired":
            rule_score += 22
        elif code == "licence_expiring_soon":
            rule_score += 8
        elif code.startswith("unparseable_"):
            rule_score += 15
        elif code.startswith("future_") or code.startswith("date_of_birth_"):
            rule_score += 20
        reason_codes.append(code)

    duplicate_score = int(duplicate_risk.get("score", 0) or 0)
    if duplicate_score >= 85:
        rule_score += 35
        reason_codes.append("high_duplicate_risk")
    elif duplicate_score >= 55:
        rule_score += 18
        reason_codes.append("possible_duplicate")

    safe_features = _safe_feature_vector(completeness, duplicate_risk, validation_codes)
    classifier_advisory = _classifier_advisory(classifier, safe_features)
    model_score = classifier_advisory.get("model_score")
    score = min(100, max(rule_score, int(model_score) if model_score is not None else 0))
    return {
        "score": score,
        "level": _score_level(score, low=20, medium=45, high=70),
        "rule_score": min(100, rule_score),
        "reason_codes": list(dict.fromkeys(reason_codes)),
        "classifier_advisory": classifier_advisory,
    }


def assess_staged_record(
    record: Mapping[str, Any] | Any,
    *,
    candidates: Iterable[Mapping[str, Any] | Any] = (),
    classifier: OptionalComplianceClassifier | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Produce a fully redacted, advisory-only review assessment.

    ``candidates`` are supplied by the caller's already-authorised staging
    query.  This function never queries a live registry, mutates records,
    queues workflow work, or returns candidate/record identity data.
    """
    completeness = score_data_completeness(record)
    duplicate_risk = score_duplicate_risk(record, candidates)
    compliance_risk = score_compliance_risk(
        record,
        completeness=completeness,
        duplicate_risk=duplicate_risk,
        classifier=classifier,
        today=today,
    )
    recommendations: list[str] = []
    if completeness["missing_field_groups"]:
        recommendations.append("complete_missing_field_groups")
    if duplicate_risk["level"] in {"medium", "high"}:
        recommendations.append("review_possible_duplicate")
    if compliance_risk["level"] in {"medium", "high"}:
        recommendations.append("review_compliance_flags")
    if not recommendations:
        recommendations.append("retain_standard_registrar_review")

    return {
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "advisory_only": True,
        "automatic_promotion_allowed": False,
        "automatic_decision_allowed": False,
        "data_completeness": completeness,
        "duplicate_risk": duplicate_risk,
        "compliance_risk": compliance_risk,
        "review_recommendations": recommendations,
        "requires_human_review": bool(
            completeness["missing_field_groups"]
            or duplicate_risk["level"] in {"medium", "high"}
            or compliance_risk["level"] in {"medium", "high"}
        ),
        "privacy": {
            "raw_values_returned": False,
            "candidate_identities_returned": False,
            "raw_payload_accessed": False,
            "classifier_input": "derived_redacted_features_only",
        },
    }
