"""Read-only, aggregate Nursing Council workforce intelligence.

This module deliberately has no request or user-record interface.  It is a
workspace service for authorised Nursing Council views and returns only
aggregate, JSON-safe values.  Medical Board professionals, imported medical
workbooks, contact information, dates of birth, and other individual fields
are never returned.
"""

from collections import defaultdict
from copy import deepcopy
from datetime import date, timedelta
import hashlib

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db import DatabaseError
from django.db.models import Count, Max, Q
from django.utils import timezone

from apps.dashboard.models import NursingLifecycleFact
from apps.dashboard.nursing_analytics import active_nursing_analytics_snapshot
from apps.dashboard.registry_archive import active_import_record_queryset, active_professional_queryset
from apps.workforce.models import (
    Application,
    ApplicationPathway,
    EmploymentRecord,
    HealthStudent,
    Midwife,
    NurseAide,
    NursingProfessional,
    PostingHistory,
    PracticingLicenseRecord,
    TrainingInstitution,
)
from apps.workforce.services.data_quality import quality_approved_import_records
from apps.workforce.services.nursing_council_workflows import (
    NURSING_COUNCIL_CODE,
    NURSING_FORM_CODES,
)


NURSING_SCOPE = "nursing"
NURSING_TARGET_MODELS = ("nursingprofessional", "midwife", "nurseaide", "healthstudent")
NURSING_PRACTITIONER_TARGET_MODELS = NURSING_TARGET_MODELS[:3]
NURSING_REGISTRY_MODELS = (
    (NursingProfessional, "Registered Nurse", True),
    (Midwife, "Midwife", True),
    (NurseAide, "Nurse Aide", False),
)
ATP_STAGE_LABEL = "Authority to Practice"
RETIREMENT_AGE = 60
RENEWAL_DUE_DAYS = 90
AGE_BANDS = (
    ("20-30", 20, 30),
    ("31-40", 31, 40),
    ("41-50", 41, 50),
    ("51-60", 51, 60),
    ("60+", 61, None),
)
STAFFING_TARGET_KEYS = {
    "approvedstaffingtarget",
    "establishmenttarget",
    "minimumclinicalstaff",
    "minimumnurses",
    "nursingstaffrequired",
    "requirednurses",
    "requiredstaff",
    "staffingtarget",
    "targetnurses",
    "targetstaff",
}
WORKFORCE_INTELLIGENCE_CACHE_SECONDS = 60
WORKFORCE_INTELLIGENCE_CACHE_PREFIX = "dashboard:nursing-workforce-intelligence:v2"
WORKFORCE_FILTER_KEYS = ("province", "cadre", "year")


def _snapshot_cache_marker(snapshot):
    """Return only non-personal snapshot state needed to invalidate the cache."""
    if not snapshot:
        return "no-active-snapshot"
    activated_at = getattr(snapshot, "activated_at", None)
    created_at = getattr(snapshot, "created_at", None)
    timestamp = activated_at or created_at
    timestamp_marker = timestamp.isoformat() if timestamp else "no-timestamp"
    return ":".join([
        str(getattr(snapshot, "pk", "")),
        str(getattr(snapshot, "snapshot_id", "")),
        timestamp_marker,
        str(getattr(snapshot, "source_file_hash", "")),
    ])


def _normalise_filter_text(value, *, max_length):
    """Return a compact, display-safe aggregate-filter value."""
    return " ".join(str(value or "").split())[:max_length]


def _normalise_workforce_filters(filters):
    """Accept only the supported, non-personal Nursing aggregate filters."""
    filters = filters or {}
    try:
        get_value = filters.get
    except AttributeError:
        get_value = lambda _key, _default="": ""

    year_value = _normalise_filter_text(get_value("year", ""), max_length=8)
    try:
        year = int(year_value) if year_value else None
    except (TypeError, ValueError):
        year = None
    if year is not None and not 1900 <= year <= 2100:
        year = None

    return {
        "province": _normalise_filter_text(get_value("province", ""), max_length=120),
        "cadre": _normalise_filter_text(get_value("cadre", ""), max_length=150),
        "year": year,
    }


def _filter_cache_marker(filters):
    """Keep user-controlled filter values out of the readable cache key."""
    value = "\x1f".join(str(filters.get(key) or "") for key in WORKFORCE_FILTER_KEYS)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _workforce_intelligence_cache_key(snapshot, today, facility_limit, filters):
    """Use snapshot state plus a one-minute bucket for all live-source changes."""
    minute_bucket = timezone.localtime(timezone.now()).strftime("%Y%m%d%H%M")
    return ":".join([
        WORKFORCE_INTELLIGENCE_CACHE_PREFIX,
        _snapshot_cache_marker(snapshot),
        today.isoformat(),
        str(facility_limit),
        _filter_cache_marker(filters),
        minute_bucket,
    ])


def _note_unavailable(unavailable, section):
    if section not in unavailable:
        unavailable.append(section)


def _safe_query(callback, default, unavailable, section):
    """Return a neutral value if a deployment is temporarily behind migrations."""
    try:
        return callback()
    except DatabaseError:
        _note_unavailable(unavailable, section)
        return default


def _normalise_label(value, fallback="Not stated"):
    text = " ".join(str(value or "").split())
    return text or fallback


def _same_dimension(value, selected):
    """Case-insensitive exact matching for governed aggregate labels."""
    if not selected:
        return True
    return _normalise_label(value, "").casefold() == selected.casefold()


def _filter_registry_rows(rows, filters):
    """Apply only dimensions present in the active Nursing registry rows."""
    return [
        row for row in rows
        if _same_dimension(row.get("province"), filters["province"])
        and _same_dimension(row.get("cadre"), filters["cadre"])
    ]


def _filter_lifecycle_queryset(queryset, filters):
    """Apply source-backed snapshot dimensions before aggregation."""
    if filters["province"]:
        queryset = queryset.filter(province__iexact=filters["province"])
    if filters["cadre"]:
        queryset = queryset.filter(cadre__iexact=filters["cadre"])
    if filters["year"] is not None:
        queryset = queryset.filter(cycle_year=filters["year"])
    return queryset


def _filter_facility_metric_queryset(queryset, filters):
    """Apply the dimensions explicitly stored on facility/year metrics."""
    if filters["province"]:
        queryset = queryset.filter(province__iexact=filters["province"])
    if filters["cadre"]:
        queryset = queryset.filter(cadre__iexact=filters["cadre"])
    if filters["year"] is not None:
        queryset = queryset.filter(year=filters["year"])
    return queryset


def _filter_import_queryset(queryset, filters):
    """Apply dimensions explicitly present in approved imported records."""
    if filters["province"]:
        queryset = queryset.filter(province__iexact=filters["province"])
    if filters["cadre"]:
        queryset = queryset.filter(category__iexact=filters["cadre"])
    if filters["year"] is not None:
        queryset = queryset.filter(record_year=filters["year"])
    return queryset


def _age_on(value, today):
    if not value:
        return None
    age = today.year - value.year - ((today.month, today.day) < (value.month, value.day))
    # Invalid or implausible source dates must not influence workforce planning.
    return age if 16 <= age <= 90 else None


def _identity_key(row, *, identifier_keys, fallback_key):
    for key in identifier_keys:
        value = str(row.get(key) or "").strip().casefold()
        if value:
            return value
    return fallback_key


def _count_distinct_snapshot_people(queryset, unavailable):
    """Use the same grouped/ungrouped rule as the Nursing analytics dashboard."""
    aggregate = _safe_query(
        lambda: queryset.aggregate(
            grouped=Count("person_group_key", filter=~Q(person_group_key=""), distinct=True),
            ungrouped=Count("id", filter=Q(person_group_key="")),
        ),
        {"grouped": 0, "ungrouped": 0},
        unavailable,
        "Nursing analytics snapshot",
    )
    return int(aggregate.get("grouped") or 0) + int(aggregate.get("ungrouped") or 0)


def _nursing_registry_rows(unavailable):
    """Load only non-sensitive aggregate dimensions for Nursing registry records."""
    rows = []
    for model, cadre_label, has_licence_expiry in NURSING_REGISTRY_MODELS:
        fields = ["id", "registration_no", "province", "gender", "date_of_birth", "cadre__name"]
        if has_licence_expiry:
            fields.append("license_expiry_date")

        def archived_queryset_values():
            return list(
                active_professional_queryset(model, scope=NURSING_SCOPE).values(*fields)
            )

        try:
            model_rows = archived_queryset_values()
        except DatabaseError:
            # A partially migrated deployment can still show a truthful direct
            # registry count rather than failing the entire workspace.
            model_rows = _safe_query(
                lambda: list(model.objects.filter(is_active=True).values(*fields)),
                [],
                unavailable,
                "Nursing professional registry",
            )

        for row in model_rows:
            rows.append({
                "model": model._meta.model_name,
                "cadre": _normalise_label(row.get("cadre__name"), cadre_label),
                "registration_no": row.get("registration_no") or "",
                "province": row.get("province") or "",
                "gender": row.get("gender") or "",
                "date_of_birth": row.get("date_of_birth"),
                "license_expiry_date": row.get("license_expiry_date"),
                "row_id": row.get("id"),
            })
    return rows


def _registry_summary(registry_rows, today):
    by_cadre = defaultdict(int)
    licence_current = 0
    licence_expired = 0
    renewal_due = 0
    known_expiry = 0
    renewal_deadline = today + timedelta(days=RENEWAL_DUE_DAYS)

    for row in registry_rows:
        by_cadre[row["cadre"]] += 1
        expiry = row.get("license_expiry_date")
        if not expiry:
            continue
        known_expiry += 1
        if expiry < today:
            licence_expired += 1
        else:
            licence_current += 1
            if expiry <= renewal_deadline:
                renewal_due += 1

    return {
        "active_practitioner_count": len(registry_rows),
        "by_cadre": [
            {"cadre": cadre, "count": count}
            for cadre, count in sorted(by_cadre.items(), key=lambda item: (-item[1], item[0]))
        ],
        "known_licence_expiry_count": known_expiry,
        "licence_current_count": licence_current,
        "licence_expired_count": licence_expired,
        "renewal_due_within_days": RENEWAL_DUE_DAYS,
        "renewal_due_count": renewal_due,
    }


def _snapshot_atp_summary(snapshot, unavailable, filters):
    if not snapshot:
        return None

    all_facts = NursingLifecycleFact.objects.filter(
        snapshot=snapshot,
        lifecycle_stage=ATP_STAGE_LABEL,
    )
    available_latest_year = _safe_query(
        lambda: all_facts.aggregate(latest=Max("cycle_year"))["latest"],
        None,
        unavailable,
        "Nursing analytics snapshot",
    )
    if available_latest_year is None:
        return None

    facts = _filter_lifecycle_queryset(all_facts, filters)
    latest_year = filters["year"]
    if latest_year is None:
        latest_year = _safe_query(
            lambda: facts.aggregate(latest=Max("cycle_year"))["latest"],
            None,
            unavailable,
            "Nursing analytics snapshot",
        )
    current_facts = facts.filter(cycle_year=latest_year) if latest_year is not None else facts.none()
    return {
        "source": "active_nursing_analytics_snapshot",
        "latest_year": latest_year,
        "record_count": _safe_query(
            current_facts.count,
            0,
            unavailable,
            "Nursing analytics snapshot",
        ),
        "person_count": _count_distinct_snapshot_people(current_facts, unavailable),
        "queryset": current_facts,
    }


def _approved_nursing_import_records(unavailable):
    def get_queryset():
        records = PracticingLicenseRecord.objects.filter(
            batch__status="completed",
            target_model__in=NURSING_TARGET_MODELS,
        ).exclude(batch__source_kind="medical_board_workbook")
        records = active_import_record_queryset(records, scope=NURSING_SCOPE)
        return quality_approved_import_records(records)

    return _safe_query(
        get_queryset,
        PracticingLicenseRecord.objects.none(),
        unavailable,
        "Nursing imported registry records",
    )


def _imported_atp_summary(unavailable, filters):
    all_records = _approved_nursing_import_records(unavailable).filter(
        target_model__in=NURSING_PRACTITIONER_TARGET_MODELS,
        record_type="practicing_license",
    )
    available_latest_year = _safe_query(
        lambda: all_records.aggregate(latest=Max("record_year"))["latest"],
        None,
        unavailable,
        "Nursing imported registry records",
    )
    if available_latest_year is None:
        return None

    records = _filter_import_queryset(all_records, filters)
    latest_year = filters["year"]
    if latest_year is None:
        latest_year = _safe_query(
            lambda: records.aggregate(latest=Max("record_year"))["latest"],
            None,
            unavailable,
            "Nursing imported registry records",
        )
    current_records = records.filter(record_year=latest_year) if latest_year is not None else records.none()
    identity_rows = _safe_query(
        lambda: list(current_records.values("id", "registration_no", "practitioner_number")),
        [],
        unavailable,
        "Nursing imported registry records",
    )
    identities = {
        _identity_key(
            row,
            identifier_keys=("registration_no", "practitioner_number"),
            fallback_key=f"row:{row['id']}",
        )
        for row in identity_rows
    }
    return {
        "source": "quality_approved_import_records",
        "latest_year": latest_year,
        "record_count": _safe_query(
            current_records.count,
            0,
            unavailable,
            "Nursing imported registry records",
        ),
        "person_count": len(identities),
        "queryset": current_records,
    }


def _atp_summary(snapshot, unavailable, filters):
    summary = _snapshot_atp_summary(snapshot, unavailable, filters)
    if summary:
        return summary
    summary = _imported_atp_summary(unavailable, filters)
    if summary:
        return summary
    return {
        "source": "unavailable",
        "latest_year": None,
        "record_count": 0,
        "person_count": 0,
        "queryset": None,
    }


def _age_observations(registry_rows, atp_summary, today, unavailable):
    seen = set()
    ages = []
    for row in registry_rows:
        key = _identity_key(
            row,
            identifier_keys=("registration_no",),
            fallback_key=f"{row['model']}:{row['row_id']}",
        )
        if key in seen:
            continue
        seen.add(key)
        age = _age_on(row.get("date_of_birth"), today)
        if age is not None:
            ages.append(age)
    if ages:
        return ages, "active_nursing_registry"

    if atp_summary.get("source") == "active_nursing_analytics_snapshot":
        rows = _safe_query(
            lambda: list(atp_summary["queryset"].values(
                "id", "person_group_key", "registration_no", "practitioner_no", "age"
            )),
            [],
            unavailable,
            "Nursing analytics snapshot",
        )
        seen = set()
        for row in rows:
            key = _identity_key(
                row,
                identifier_keys=("person_group_key", "registration_no", "practitioner_no"),
                fallback_key=f"row:{row['id']}",
            )
            if key in seen:
                continue
            seen.add(key)
            try:
                age = int(row.get("age"))
            except (TypeError, ValueError):
                age = None
            if age is not None and 16 <= age <= 90:
                ages.append(age)
        if ages:
            return ages, "active_nursing_analytics_snapshot"

    if atp_summary.get("source") == "quality_approved_import_records":
        rows = _safe_query(
            lambda: list(atp_summary["queryset"].values(
                "id", "registration_no", "practitioner_number", "date_of_birth"
            )),
            [],
            unavailable,
            "Nursing imported registry records",
        )
        seen = set()
        for row in rows:
            key = _identity_key(
                row,
                identifier_keys=("registration_no", "practitioner_number"),
                fallback_key=f"row:{row['id']}",
            )
            if key in seen:
                continue
            seen.add(key)
            age = _age_on(row.get("date_of_birth"), today)
            if age is not None:
                ages.append(age)
        if ages:
            return ages, "quality_approved_import_records"

    return [], "unavailable"


def _age_summary(registry_rows, atp_summary, today, unavailable):
    ages, source = _age_observations(registry_rows, atp_summary, today, unavailable)
    rows = []
    for label, lower, upper in AGE_BANDS:
        count = sum(1 for age in ages if age >= lower and (upper is None or age <= upper))
        rows.append({"band": label, "count": count})
    retirement_next_five = sum(1 for age in ages if RETIREMENT_AGE - 5 <= age < RETIREMENT_AGE)
    return {
        "available": bool(ages),
        "source": source,
        "known_age_count": len(ages),
        "age_band_rows": rows,
        "retirement_age": RETIREMENT_AGE,
        "retirement_within_five_years_count": retirement_next_five,
        "retirement_age_or_older_count": sum(1 for age in ages if age >= RETIREMENT_AGE),
        "note": (
            "Age analysis is suppressed until valid dates of birth are available."
            if not ages
            else "Aggregate age bands only; individual dates of birth are not exposed."
        ),
    }


def _dimension_rows(queryset, field, unavailable, section):
    values = _safe_query(
        lambda: list(
            queryset.exclude(**{f"{field}__isnull": True})
            .exclude(**{field: ""})
            .values(field)
            .annotate(total=Count("id"))
        ),
        [],
        unavailable,
        section,
    )
    grouped = defaultdict(int)
    display_labels = {}
    for row in values:
        label = _normalise_label(row.get(field), "")
        if not label:
            continue
        key = label.casefold()
        grouped[key] += int(row.get("total") or 0)
        display_labels.setdefault(key, label)
    return [
        {"label": display_labels[key], "count": total}
        for key, total in sorted(
            grouped.items(), key=lambda item: (-item[1], display_labels[item[0]])
        )
    ]


def _province_distribution(registry_rows, atp_summary, unavailable):
    if atp_summary.get("source") == "active_nursing_analytics_snapshot":
        rows = _dimension_rows(
            atp_summary["queryset"], "province", unavailable, "Nursing analytics snapshot"
        )
        if rows:
            return {"source": atp_summary["source"], "rows": [
                {"province": row["label"], "count": row["count"]} for row in rows
            ]}
    elif atp_summary.get("source") == "quality_approved_import_records":
        rows = _dimension_rows(
            atp_summary["queryset"], "province", unavailable, "Nursing imported registry records"
        )
        if rows:
            return {"source": atp_summary["source"], "rows": [
                {"province": row["label"], "count": row["count"]} for row in rows
            ]}

    grouped = defaultdict(int)
    labels = {}
    for row in registry_rows:
        label = _normalise_label(row.get("province"), "")
        if not label:
            continue
        key = label.casefold()
        grouped[key] += 1
        labels.setdefault(key, label)
    return {
        "source": "active_nursing_registry" if grouped else "unavailable",
        "rows": [
            {"province": labels[key], "count": count}
            for key, count in sorted(grouped.items(), key=lambda item: (-item[1], labels[item[0]]))
        ],
    }


def _numeric_staffing_target(payload):
    if not isinstance(payload, dict):
        return None
    for key, value in payload.items():
        compact_key = "".join(character for character in str(key).lower() if character.isalnum())
        if compact_key not in STAFFING_TARGET_KEYS:
            continue
        try:
            target = int(value)
        except (TypeError, ValueError):
            continue
        if target >= 0:
            return target
    return None


def _format_staffing_rows(grouped, facility_limit):
    rows = []
    for values in grouped.values():
        target = values["staffing_target"]
        observed = values["observed_staff_count"]
        gap = max(target - observed, 0) if target is not None else None
        rows.append({
            "facility": values["facility"],
            "province": values["province"],
            "district": values["district"],
            "employment_sector": values["employment_sector"],
            "observed_staff_count": observed,
            "staffing_target": target,
            "gap": gap,
            "gap_status": "reported" if target is not None else "target_not_configured",
        })
    rows.sort(key=lambda row: (
        row["gap"] is None,
        -(row["gap"] or 0),
        -row["observed_staff_count"],
        row["facility"],
    ))
    return rows[:facility_limit] if facility_limit else rows


def _snapshot_facility_staffing(snapshot, facility_limit, unavailable, filters):
    if not snapshot:
        return None
    all_metrics = snapshot.facility_cadre_year_metrics.exclude(facility="")
    available_latest_year = _safe_query(
        lambda: all_metrics.aggregate(latest=Max("year"))["latest"],
        None,
        unavailable,
        "Nursing facility analytics",
    )
    if available_latest_year is None:
        return None
    metrics = _filter_facility_metric_queryset(all_metrics, filters)
    latest_year = filters["year"]
    if latest_year is None:
        latest_year = _safe_query(
            lambda: metrics.aggregate(latest=Max("year"))["latest"],
            None,
            unavailable,
            "Nursing facility analytics",
        )
    if latest_year is None:
        return {
            "available": False,
            "source": "active_nursing_analytics_snapshot",
            "latest_year": None,
            "total_facilities": 0,
            "target_configured_facilities": 0,
            "rows": [],
            "districts": [],
            "employment_sectors": [],
        }
    metric_rows = _safe_query(
        lambda: list(metrics.filter(year=latest_year).values(
            "facility", "province", "organization_type", "count", "raw_payload"
        )),
        [],
        unavailable,
        "Nursing facility analytics",
    )
    if not metric_rows:
        return None
    grouped = {}
    for row in metric_rows:
        facility = _normalise_label(row.get("facility"), "")
        if not facility:
            continue
        province = _normalise_label(row.get("province"), "")
        sector = _normalise_label(row.get("organization_type"), "")
        key = (facility.casefold(), province.casefold(), sector.casefold())
        group = grouped.setdefault(key, {
            "facility": facility,
            "province": province,
            "district": "",
            "employment_sector": sector,
            "observed_staff_count": 0,
            "staffing_target": None,
        })
        group["observed_staff_count"] += int(row.get("count") or 0)
        target = _numeric_staffing_target(row.get("raw_payload"))
        if target is not None:
            group["staffing_target"] = max(group["staffing_target"] or 0, target)
    if not grouped:
        return None
    rows = _format_staffing_rows(grouped, facility_limit)
    return {
        "available": True,
        "source": "active_nursing_analytics_snapshot",
        "latest_year": latest_year,
        "total_facilities": len(grouped),
        "target_configured_facilities": sum(1 for row in grouped.values() if row["staffing_target"] is not None),
        "rows": rows,
        "districts": [],
        "employment_sectors": sorted({row["employment_sector"] for row in grouped.values() if row["employment_sector"]}),
    }


def _nursing_content_type_ids(unavailable):
    return _safe_query(
        lambda: [
            ContentType.objects.get_for_model(model).pk
            for model, _label, _has_licence_expiry in NURSING_REGISTRY_MODELS
        ],
        [],
        unavailable,
        "Nursing facility staffing",
    )


def _employment_facility_staffing(facility_limit, unavailable, filters):
    # Current employment records have a governed facility province, but do
    # not have a comparable historical year or snapshot-cadre dimension.
    # Returning an unfiltered current value for either requested dimension
    # would be misleading, so leave this section unavailable instead.
    if filters["cadre"] or filters["year"] is not None:
        return None
    content_type_ids = _nursing_content_type_ids(unavailable)
    if not content_type_ids:
        return None

    def grouped_rows(model, include_sector):
        fields = [
            "facility__name",
            "facility__location__province",
            "facility__location__district",
        ]
        if include_sector:
            fields.append("employment_sector")
        rows = list(
            model.objects.filter(content_type_id__in=content_type_ids, is_current=True, facility__isnull=False)
            .filter(
                **({"facility__location__province__iexact": filters["province"]}
                   if filters["province"] else {})
            )
            .values(*fields)
            .annotate(total=Count("id"))
        )
        if not include_sector:
            for row in rows:
                row["employment_sector"] = ""
        return rows

    source = "current_employment_records"
    rows = _safe_query(
        lambda: grouped_rows(EmploymentRecord, True),
        [],
        unavailable,
        "Nursing facility staffing",
    )
    if not rows:
        source = "current_posting_history"
        rows = _safe_query(
            lambda: grouped_rows(PostingHistory, False),
            [],
            unavailable,
            "Nursing facility staffing",
        )
    if not rows:
        return None

    grouped = {}
    for row in rows:
        facility = _normalise_label(row.get("facility__name"), "")
        if not facility:
            continue
        province = _normalise_label(row.get("facility__location__province"), "")
        district = _normalise_label(row.get("facility__location__district"), "")
        sector = _normalise_label(row.get("employment_sector"), "")
        key = (facility.casefold(), province.casefold(), district.casefold(), sector.casefold())
        group = grouped.setdefault(key, {
            "facility": facility,
            "province": province,
            "district": district,
            "employment_sector": sector,
            "observed_staff_count": 0,
            "staffing_target": None,
        })
        group["observed_staff_count"] += int(row.get("total") or 0)
    formatted_rows = _format_staffing_rows(grouped, facility_limit)
    return {
        "available": bool(formatted_rows),
        "source": source,
        "latest_year": None,
        "total_facilities": len(grouped),
        "target_configured_facilities": 0,
        "rows": formatted_rows,
        "districts": sorted({row["district"] for row in grouped.values() if row["district"]}),
        "employment_sectors": sorted({row["employment_sector"] for row in grouped.values() if row["employment_sector"]}),
    }


def _imported_facility_staffing(atp_summary, facility_limit, unavailable):
    if atp_summary.get("source") != "quality_approved_import_records":
        return None
    records = atp_summary["queryset"].exclude(workplace_address="")
    rows = _safe_query(
        lambda: list(records.values("workplace_address", "province").annotate(total=Count("id"))),
        [],
        unavailable,
        "Nursing imported facility references",
    )
    if not rows:
        return None
    grouped = {}
    for row in rows:
        facility = _normalise_label(row.get("workplace_address"), "")
        if not facility:
            continue
        province = _normalise_label(row.get("province"), "")
        key = (facility.casefold(), province.casefold())
        group = grouped.setdefault(key, {
            "facility": facility,
            "province": province,
            "district": "",
            "employment_sector": "",
            "observed_staff_count": 0,
            "staffing_target": None,
        })
        group["observed_staff_count"] += int(row.get("total") or 0)
    formatted_rows = _format_staffing_rows(grouped, facility_limit)
    return {
        "available": bool(formatted_rows),
        "source": "quality_approved_imported_workplace_references",
        "latest_year": atp_summary.get("latest_year"),
        "total_facilities": len(grouped),
        "target_configured_facilities": 0,
        "rows": formatted_rows,
        "districts": [],
        "employment_sectors": [],
    }


def _facility_staffing_summary(snapshot, atp_summary, facility_limit, unavailable, filters):
    summary = _snapshot_facility_staffing(snapshot, facility_limit, unavailable, filters)
    if not summary:
        summary = _employment_facility_staffing(facility_limit, unavailable, filters)
    if not summary:
        summary = _imported_facility_staffing(atp_summary, facility_limit, unavailable)
    if summary:
        summary["note"] = (
            "A staffing gap is reported only where an approved target is present in the source. "
            "Observed workforce counts are not establishment requirements."
        )
        return summary
    return {
        "available": False,
        "source": "unavailable",
        "latest_year": None,
        "total_facilities": 0,
        "target_configured_facilities": 0,
        "rows": [],
        "districts": [],
        "employment_sectors": [],
        "note": "No Nursing Council facility workforce source is available yet.",
    }


def _pathway_and_education_summary(unavailable):
    pathways = _safe_query(
        lambda: list(
            ApplicationPathway.objects.filter(
                regulatory_body__code=NURSING_COUNCIL_CODE,
                active=True,
            ).order_by("sort_order", "pathway_code").values(
                "pathway_code",
                "pathway_name",
                "primary_form_code",
                "requires_payment",
                "requires_employer",
                "requires_institution",
                "requires_supervisor",
                "requires_registrar_approval",
                "creates_licence_type",
            )
        ),
        [],
        unavailable,
        "Nursing Council pathways",
    )
    application_rows = _safe_query(
        lambda: list(
            Application.objects.filter(form_code__in=NURSING_FORM_CODES)
            .values("form_code", "status")
            .annotate(total=Count("id"))
        ),
        [],
        unavailable,
        "Nursing Council applications",
    )
    application_counts = defaultdict(int)
    for row in application_rows:
        application_counts[(row.get("form_code") or "", row.get("status") or "")] += int(row.get("total") or 0)

    student_rows = _safe_query(
        lambda: list(
            HealthStudent.objects.filter(is_active=True)
            .values("institution__name", "is_graduate")
            .annotate(total=Count("id"))
        ),
        [],
        unavailable,
        "Nursing education records",
    )
    institution_counts = defaultdict(int)
    graduand_count = 0
    graduate_count = 0
    for row in student_rows:
        total = int(row.get("total") or 0)
        institution = _normalise_label(row.get("institution__name"), "Not linked to an institution")
        institution_counts[institution] += total
        if row.get("is_graduate"):
            graduate_count += total
        else:
            graduand_count += total

    recognised_count = _safe_query(
        lambda: TrainingInstitution.objects.filter(
            regulatory_body_name__icontains="nursing",
            is_active=True,
        ).count(),
        0,
        unavailable,
        "Nursing education institutions",
    )
    linked_institution_count = len({
        label for label in institution_counts
        if label != "Not linked to an institution"
    })
    return {
        "active_pathway_count": len(pathways),
        "pathways": pathways,
        "application_status_counts": [
            {"form_code": form_code, "status": status, "count": count}
            for (form_code, status), count in sorted(application_counts.items())
        ],
        "pending_renewal_count": application_counts.get(("NC3", "pending"), 0),
        "pending_provisional_count": application_counts.get(("NC1", "pending"), 0),
        "pending_full_licence_count": application_counts.get(("NC2", "pending"), 0),
        "graduand_count": graduand_count,
        "graduate_count": graduate_count,
        "recognised_institution_count": max(recognised_count, linked_institution_count),
        "institution_rows": [
            {"institution": label, "count": count}
            for label, count in sorted(institution_counts.items(), key=lambda item: (-item[1], item[0]))[:12]
        ],
    }


def _filter_metadata(snapshot, atp_summary, registry_rows, province_distribution, facility_summary, age_summary, unavailable):
    years = []
    cadres = set(row["cadre"] for row in registry_rows if row.get("cadre"))
    genders = set(row["gender"] for row in registry_rows if row.get("gender"))

    if atp_summary.get("source") == "active_nursing_analytics_snapshot":
        facts = NursingLifecycleFact.objects.filter(snapshot=snapshot)
        years = _safe_query(
            lambda: sorted({
                value for value in facts.values_list("cycle_year", flat=True) if value is not None
            }),
            [],
            unavailable,
            "Nursing analytics snapshot",
        )
        cadres.update(_safe_query(
            lambda: {
                _normalise_label(value, "")
                for value in facts.exclude(cadre="").values_list("cadre", flat=True)
                if _normalise_label(value, "")
            },
            set(),
            unavailable,
            "Nursing analytics snapshot",
        ))
        genders.update(_safe_query(
            lambda: {
                _normalise_label(value, "")
                for value in facts.exclude(sex="").values_list("sex", flat=True)
                if _normalise_label(value, "")
            },
            set(),
            unavailable,
            "Nursing analytics snapshot",
        ))
    elif atp_summary.get("source") == "quality_approved_import_records":
        records = _approved_nursing_import_records(unavailable)
        years = _safe_query(
            lambda: sorted({
                value for value in records.values_list("record_year", flat=True) if value is not None
            }),
            [],
            unavailable,
            "Nursing imported registry records",
        )
        cadres.update(_safe_query(
            lambda: {
                _normalise_label(value, "")
                for value in records.exclude(category="").values_list("category", flat=True)
                if _normalise_label(value, "")
            },
            set(),
            unavailable,
            "Nursing imported registry records",
        ))
        genders.update(_safe_query(
            lambda: {
                _normalise_label(value, "")
                for value in records.exclude(gender="").values_list("gender", flat=True)
                if _normalise_label(value, "")
            },
            set(),
            unavailable,
            "Nursing imported registry records",
        ))

    provinces = {
        row["province"] for row in province_distribution["rows"] if row.get("province")
    }
    provinces.update(row["province"] for row in registry_rows if row.get("province"))
    if snapshot:
        snapshot_provinces = _safe_query(
            lambda: {
                _normalise_label(value, "")
                for value in NursingLifecycleFact.objects.filter(
                    snapshot=snapshot,
                    lifecycle_stage=ATP_STAGE_LABEL,
                ).exclude(province="").values_list("province", flat=True)
                if _normalise_label(value, "")
            },
            set(),
            unavailable,
            "Nursing analytics snapshot",
        )
        provinces.update(snapshot_provinces)

    return {
        "time": {
            "years": years,
            "granularities": ["year", "quarter", "month"],
        },
        "geography": {
            "provinces": sorted(provinces),
            "districts": facility_summary.get("districts", []),
            "llgs": [],
            "llg_note": "LLG is not yet a governed Nursing workforce field in this source.",
        },
        "workforce": {
            "cadres": sorted(cadres),
            "genders": sorted(genders),
            "age_bands": [row["band"] for row in age_summary["age_band_rows"]],
        },
        "employment": {
            "sectors": facility_summary.get("employment_sectors", []),
            "facility_gap_statuses": ["reported", "target_not_configured"],
        },
        "registration": {
            "lifecycle_stages": ["Provisional Licence", "Full Licence", ATP_STAGE_LABEL],
            "statuses": ["active", "expired", "renewal_due"],
        },
    }


def _filter_state(filters):
    """Describe precisely which aggregate sections can honour each filter."""
    selected = {
        "province": filters["province"],
        "cadre": filters["cadre"],
        "year": filters["year"],
    }
    active = any(value not in (None, "") for value in selected.values())
    section_notes = [
        "Province and cadre filter active Nursing registry, ATP snapshot, and snapshot facility metrics when those governed fields are present.",
        "Year filters ATP and facility snapshot metrics; current registry and age profile counts have no historical-year field and remain clearly labelled as current aggregate evidence.",
        "Current employment fallback supports province only. It is not substituted when a cadre or year filter cannot be supported.",
    ]
    return {
        "active": active,
        "selected": selected,
        "supported_dimensions": list(WORKFORCE_FILTER_KEYS),
        "section_notes": section_notes,
    }


def build_nursing_workforce_intelligence_context(*, today=None, facility_limit=12, filters=None):
    """Build a safe, Nursing-only dashboard context.

    The caller is responsible for its normal Nursing Council staff permission
    check.  This service itself is intentionally hard-bound to the Nursing
    scope, uses archived-record exclusions where available, and never returns
    a professional name, registration number, contact field, DOB, raw payload,
    or any Medical Board data.
    """
    today = today or timezone.localdate()
    try:
        facility_limit = max(1, int(facility_limit or 12))
    except (TypeError, ValueError):
        facility_limit = 12
    filters = _normalise_workforce_filters(filters)
    unavailable = []
    snapshot = _safe_query(
        active_nursing_analytics_snapshot,
        None,
        unavailable,
        "Nursing analytics snapshot",
    )
    cache_key = _workforce_intelligence_cache_key(snapshot, today, facility_limit, filters)
    cached_context = cache.get(cache_key)
    if cached_context is not None:
        # LocMem cache can share object references within a process.  Context
        # processors and templates must never be able to mutate a cached
        # aggregate response for another staff request.
        return deepcopy(cached_context)

    all_registry_rows = _nursing_registry_rows(unavailable)
    registry_rows = _filter_registry_rows(all_registry_rows, filters)
    registry = _registry_summary(registry_rows, today)
    atp = _atp_summary(snapshot, unavailable, filters)
    age = _age_summary(registry_rows, atp, today, unavailable)
    province = _province_distribution(registry_rows, atp, unavailable)
    facility = _facility_staffing_summary(snapshot, atp, facility_limit, unavailable, filters)
    pathways = _pathway_and_education_summary(unavailable)
    filter_dimensions = _filter_metadata(
        snapshot, atp, all_registry_rows, province, facility, age, unavailable
    )
    filter_state = _filter_state(filters)

    notices = [
        "Read-only Nursing Council workforce intelligence; it does not disclose individual professional records.",
        "Use the figures as regulatory decision support, not as an automatic registration, ATP, employment, or staffing decision.",
    ]
    if facility["target_configured_facilities"] == 0:
        notices.append(
            "Facility gap values remain unavailable until approved staffing establishment targets are captured."
        )
    if unavailable:
        notices.append(
            "Some optional Nursing intelligence inputs are temporarily unavailable; displayed figures use the remaining governed sources."
        )
    if filter_state["active"]:
        notices.append(
            "Aggregate filters are applied only to sections that hold the selected governed dimension; see the filter note before comparing sections."
        )

    context = {
        "scope": NURSING_SCOPE,
        "scope_label": "PNG Nursing Council",
        "read_only": True,
        "generated_for_date": today.isoformat(),
        "data_sources": {
            "analytics_snapshot_available": bool(snapshot),
            "analytics_snapshot_source": getattr(snapshot, "source_file_name", "") if snapshot else "",
            "atp": atp["source"],
            "age": age["source"],
            "facility": facility["source"],
        },
        "practitioner_status": {
            **registry,
            "atp_current_year": atp["latest_year"],
            "atp_current_record_count": atp["record_count"],
            "atp_current_person_count": atp["person_count"],
            "atp_source": atp["source"],
        },
        "province_distribution": province,
        "age_and_retirement": age,
        "facility_staffing": facility,
        "pathway_and_education": pathways,
        "filter_dimensions": filter_dimensions,
        "filter_state": filter_state,
        "rural_under_35_measure": {
            "available": False,
            "note": (
                "A rural under-35 workforce count is unavailable until a governed rural/urban facility classification is linked to the same approved age and current-employment evidence. "
                "Province, district, facility name, or facility level are not treated as a rural classification."
            ),
        },
        "unavailable_sections": unavailable,
        "notices": notices,
    }
    # Do not retain a degraded source response: retry optional tables on the
    # next request instead of holding a temporary schema/connectivity failure.
    if not unavailable:
        cache.set(cache_key, deepcopy(context), timeout=WORKFORCE_INTELLIGENCE_CACHE_SECONDS)
    return deepcopy(context)
