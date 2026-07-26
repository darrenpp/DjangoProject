from collections import Counter, defaultdict

from django.core.cache import cache

from apps.dashboard.models import NursingAnalyticsSnapshot, NursingLifecycleFact, NursingPractitionerIndex


CURRENT_ATP_YEAR = 2026
DECADE_ORDER = [
    "Before 1960",
    "1960s",
    "1970s",
    "1980s",
    "1990s",
    "2000s",
    "2010s",
    "2020s",
    "Unknown",
]


def _to_non_negative_int(value):
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return None
    return parsed


def _lifecycle_age_by_person_group(snapshot, person_group_keys):
    person_group_keys = [key for key in set(person_group_keys) if key]
    if not person_group_keys:
        return {}

    age_lookup = {}
    rows = NursingLifecycleFact.objects.filter(
        snapshot=snapshot,
        person_group_key__in=person_group_keys,
    ).exclude(age__isnull=True).order_by(
        "-cycle_year",
        "-event_date",
        "record_id",
    ).values("person_group_key", "age")
    for row in rows:
        key = row["person_group_key"]
        if key and key not in age_lookup:
            age_lookup[key] = row["age"]
    return age_lookup


def _age_filter_for_row(row, age_min, age_max):
    age = getattr(row, "age", None)
    if age is None:
        return False
    if age_min is not None and age < age_min:
        return False
    if age_max is not None and age > age_max:
        return False
    return True


def _lapsed_age_label(age_min, age_max):
    if age_min is None and age_max is None:
        return ""
    if age_min is not None and age_max is not None:
        return f"Age {age_min}-{age_max}"
    if age_min is not None:
        return f"Age >= {age_min}"
    return f"Age <= {age_max}"


def active_lapsed_snapshot():
    return (
        NursingAnalyticsSnapshot.objects
        .filter(is_active=True)
        .order_by("-activated_at", "-created_at")
        .first()
    )


def decade_label(year):
    if not year:
        return "Unknown"
    if year < 1960:
        return "Before 1960"
    if 1960 <= year <= 2029:
        return f"{(year // 10) * 10}s"
    return "After 2029"


def lapse_bucket(row):
    latest_atp = row.latest_atp_year
    latest_year = row.latest_year
    if latest_atp == CURRENT_ATP_YEAR:
        return "Current ATP 2026"
    if latest_atp == CURRENT_ATP_YEAR - 1:
        return "Lapsed 1 year"
    if latest_atp and 2021 <= latest_atp <= 2024:
        return "Lapsed 2-5 years"
    if latest_atp and latest_atp <= 2020:
        return "Long-lapsed ATP"
    if not latest_atp and latest_year and latest_year <= 2020:
        return "No ATP and old last record"
    if not latest_atp:
        return "No ATP but recent non-ATP"
    return "Other"


def risk_bucket(row):
    latest_atp = row.latest_atp_year
    latest_year = row.latest_year
    first_year = row.first_year
    if latest_atp == CURRENT_ATP_YEAR:
        return "Current"
    if latest_atp and latest_atp >= 2021:
        return "Renewal follow-up"
    if latest_atp and latest_atp <= 2015:
        return "High priority deceased/inactive review"
    if latest_atp and latest_atp <= 2020:
        return "Medium priority lapsed review"
    if not latest_atp and latest_year and latest_year <= 2015:
        return "High priority deceased/inactive review"
    if not latest_atp and latest_year and latest_year <= 2020:
        return "Medium priority lapsed review"
    if first_year and first_year <= 1999 and not latest_atp:
        return "High priority no-ATP review"
    return "Low priority identity/renewal review"


def _row_dict(row):
    return {
        "name": row.representative_name,
        "age": getattr(row, "age", None),
        "registration_nos": row.registration_nos,
        "practitioner_nos": row.practitioner_nos,
        "first_year": row.first_year,
        "latest_year": row.latest_year,
        "latest_atp_year": row.latest_atp_year,
        "latest_cadre": row.latest_cadre,
        "latest_facility": row.latest_facility,
        "latest_province": row.latest_province,
        "record_count": row.record_count,
        "stages_present": row.stages_present,
        "needs_manual_review": row.needs_manual_review,
        "dq_flag_count": row.dq_flag_count,
        "risk_bucket": risk_bucket(row),
        "lapse_bucket": lapse_bucket(row),
    }


def lapsed_renewal_review_context(limit=25, age_min=None, age_max=None):
    age_min = _to_non_negative_int(age_min)
    age_max = _to_non_negative_int(age_max)
    snapshot = active_lapsed_snapshot()
    if not snapshot:
        return {
            "nursing_lapsed_has_snapshot": False,
            "nursing_lapsed_cards": [],
            "nursing_lapsed_decade_rows": [],
            "nursing_lapsed_lapse_rows": [],
            "nursing_lapsed_risk_rows": [],
            "nursing_lapsed_cross_rows": [],
            "nursing_lapsed_candidate_rows": [],
            "nursing_lapsed_source": "",
            "nursing_lapsed_age_min": None,
            "nursing_lapsed_age_max": None,
            "nursing_lapsed_active_filter_label": "",
            "nursing_lapsed_review_note": "No active Nursing analytics snapshot is available.",
        }

    cache_key = f"nursing-lapsed-review:{snapshot.pk}:{limit}:{age_min}:{age_max}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    rows = list(
        NursingPractitionerIndex.objects
        .filter(snapshot=snapshot)
        .only(
            "person_group_key",
            "representative_name",
            "registration_nos",
            "practitioner_nos",
            "first_year",
            "latest_year",
            "latest_atp_year",
            "latest_cadre",
            "latest_facility",
            "latest_province",
            "record_count",
            "stages_present",
            "needs_manual_review",
            "dq_flag_count",
        )
        .iterator(chunk_size=2000)
    )

    age_by_group = _lifecycle_age_by_person_group(snapshot, [row.person_group_key for row in rows])
    for row in rows:
        row.age = age_by_group.get(row.person_group_key)

    if age_min is not None or age_max is not None:
        rows = [row for row in rows if _age_filter_for_row(row, age_min, age_max)]

    total = len(rows)
    current = sum(1 for row in rows if row.latest_atp_year == CURRENT_ATP_YEAR)
    non_current = total - current
    manual_review = sum(1 for row in rows if row.needs_manual_review)

    decade_counts = Counter(decade_label(row.first_year) for row in rows)
    lapse_counts = Counter(lapse_bucket(row) for row in rows)
    risk_counts = Counter(risk_bucket(row) for row in rows)
    cross = defaultdict(Counter)
    for row in rows:
        cross[decade_label(row.first_year)][lapse_bucket(row)] += 1

    high_priority = [
        row for row in rows
        if risk_bucket(row).startswith("High priority")
    ]
    high_priority.sort(key=lambda row: (row.first_year or 9999, row.latest_year or 9999, row.representative_name or ""))

    context = {
        "nursing_lapsed_has_snapshot": True,
        "nursing_lapsed_source": snapshot.source_file_name,
        "nursing_lapsed_snapshot": snapshot,
        "nursing_lapsed_review_note": (
            "These are lapsed-renewal and possible deceased/inactive review signals only. "
            "Do not mark a practitioner deceased until the registrar confirms evidence."
        ),
        "nursing_lapsed_cards": [
            {"label": "Practitioner index rows", "value": total, "tone": "primary"},
            {"label": "Current ATP 2026", "value": current, "tone": "success"},
            {"label": "Not current ATP 2026", "value": non_current, "tone": "warning"},
            {"label": "Manual review flagged", "value": manual_review, "tone": "danger"},
        ],
        "nursing_lapsed_decade_rows": [
            {"label": label, "count": decade_counts.get(label, 0)}
            for label in DECADE_ORDER
            if decade_counts.get(label, 0)
        ],
        "nursing_lapsed_lapse_rows": [
            {"label": label, "count": count}
            for label, count in lapse_counts.most_common()
        ],
        "nursing_lapsed_risk_rows": [
            {"label": label, "count": count}
            for label, count in risk_counts.most_common()
        ],
        "nursing_lapsed_cross_rows": [
            {"decade": decade, "bucket": bucket, "count": count}
            for decade in DECADE_ORDER
            for bucket, count in cross.get(decade, Counter()).most_common()
        ],
        "nursing_lapsed_candidate_rows": [_row_dict(row) for row in high_priority[:limit]],
        "nursing_lapsed_age_min": age_min,
        "nursing_lapsed_age_max": age_max,
        "nursing_lapsed_active_filter_label": _lapsed_age_label(age_min, age_max),
    }
    cache.set(cache_key, context, 300)
    return context


def lapsed_renewal_assistant_summary():
    context = lapsed_renewal_review_context(limit=5)
    if not context.get("nursing_lapsed_has_snapshot"):
        return {
            "summary": context["nursing_lapsed_review_note"],
            "sources": [],
        }
    cards = {card["label"]: card["value"] for card in context["nursing_lapsed_cards"]}
    risk = {row["label"]: row["count"] for row in context["nursing_lapsed_risk_rows"]}
    return {
        "summary": (
            f"Nursing lapsed-renewal review uses {context['nursing_lapsed_source']}. "
            f"Current ATP 2026: {cards.get('Current ATP 2026', 0)}. "
            f"Not current ATP 2026: {cards.get('Not current ATP 2026', 0)}. "
            f"High priority deceased/inactive review: {risk.get('High priority deceased/inactive review', 0)}."
        ),
        "sources": [
            {
                "label": "Nursing practitioner lifecycle index",
                "detail": context["nursing_lapsed_source"],
                "url": "",
            },
            {
                "label": "Registrar review rule",
                "detail": context["nursing_lapsed_review_note"],
                "url": "",
            },
        ],
    }
