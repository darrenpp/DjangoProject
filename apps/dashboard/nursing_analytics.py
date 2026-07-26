import json

from django.db.models import Count, Max, Q, Sum

from apps.dashboard.models import NursingAnalyticsSnapshot, NursingLifecycleFact


STAGE_LABELS = ["Provisional Licence", "Full Licence", "Authority to Practice"]
ATP_STAGE_LABEL = "Authority to Practice"
PNG_PROVINCE_LABELS = {
    "Autonomous Region of Bougainville",
    "Central Province",
    "Chimbu Province",
    "East New Britain Province",
    "East Sepik Province",
    "Eastern Highlands Province",
    "Enga Province",
    "Gulf Province",
    "Hela Province",
    "Jiwaka Province",
    "Madang Province",
    "Manus Province",
    "Milne Bay Province",
    "Morobe Province",
    "National Capital District",
    "New Ireland Province",
    "Oro Province",
    "Southern Highlands Province",
    "West New Britain Province",
    "West Sepik Province",
    "Western Highlands Province",
    "Western Province",
}
DISPLAY_PROVINCE_LABELS = PNG_PROVINCE_LABELS | {"Overseas / Not PNG", "Unknown / Not Stated"}


def active_nursing_analytics_snapshot():
    return (
        NursingAnalyticsSnapshot.objects
        .select_related("source_batch")
        .filter(is_active=True)
        .order_by("-activated_at", "-created_at")
        .first()
    )


def _active_atp_queryset(snapshot):
    return NursingLifecycleFact.objects.filter(
        snapshot=snapshot,
        lifecycle_stage=ATP_STAGE_LABEL,
    )


def _distinct_people_count(queryset):
    counts = queryset.aggregate(
        grouped=Count("person_group_key", filter=~Q(person_group_key=""), distinct=True),
        ungrouped=Count("id", filter=Q(person_group_key="")),
    )
    return int(counts["grouped"] or 0) + int(counts["ungrouped"] or 0)


def _province_rows_from_active_atp(snapshot):
    rows = (
        _active_atp_queryset(snapshot)
        .filter(province__in=DISPLAY_PROVINCE_LABELS)
        .values("province")
        .annotate(total=Count("id"))
        .order_by("-total", "province")
    )
    return list(rows)


def _atp_live_summary(snapshot):
    atp_queryset = _active_atp_queryset(snapshot)
    latest_year = atp_queryset.aggregate(latest=Max("cycle_year"))["latest"]
    current_queryset = atp_queryset.filter(cycle_year=latest_year) if latest_year else atp_queryset.none()
    ownership_rows = (
        current_queryset
        .values("organization_type")
        .annotate(records=Count("id"))
        .order_by("-records", "organization_type")
    )
    return {
        "atp_current_year": latest_year,
        "atp_current_record_total": current_queryset.count(),
        "atp_current_person_total": _distinct_people_count(current_queryset),
        "atp_total_record_count": atp_queryset.count(),
        "atp_distinct_analytics_groups": _distinct_people_count(atp_queryset),
        "atp_current_ownership": list(ownership_rows),
        "province_rows": _province_rows_from_active_atp(snapshot),
    }


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


def metric_payload(snapshot=None):
    snapshot = snapshot or active_nursing_analytics_snapshot()
    if not snapshot:
        return {
            "has_snapshot": False,
            "kpis": {},
            "cards": [],
            "filters": {"stages": [], "years": [], "cadres": [], "provinces": []},
            "charts": {},
            "quality_rows": [],
            "facility_rows": [],
            "institution_rows": [],
            "live_statistics": {},
            "licence_cleanse_overlay": {},
        }

    kpis = snapshot.kpi_summary or {}
    stage_values = [
        int(kpis.get("clean_provisional_records") or 0),
        int(kpis.get("clean_full_licence_records") or 0),
        int(kpis.get("clean_atp_records") or 0),
    ]
    year_rows = list(snapshot.stage_year_metrics.order_by("year").values(
        "year",
        "year_label",
        "provisional_licence_count",
        "full_licence_count",
        "authority_to_practice_count",
        "grand_total",
    ))
    cadre_rows = list(snapshot.cadre_stage_metrics.order_by("-grand_total", "cadre").values(
        "cadre",
        "cadre_group",
        "provisional_licence_count",
        "full_licence_count",
        "authority_to_practice_count",
        "grand_total",
    )[:12])
    province_rows = _province_rows_from_active_atp(snapshot)
    quality_rows = list(snapshot.data_quality_metrics.order_by("lifecycle_stage").values(
        "lifecycle_stage",
        "high_count",
        "medium_count",
        "needs_review_count",
        "grand_total",
        "needs_review_percent",
    ))
    facility_rows = list(
        snapshot.facility_cadre_year_metrics
        .values("facility", "province", "organization_type")
        .annotate(total=Sum("count"))
        .order_by("-total", "facility")[:12]
    )
    institution_rows = list(
        snapshot.institution_cadre_year_metrics
        .values("institution")
        .annotate(total=Sum("count"))
        .order_by("-total", "institution")[:12]
    )

    filter_options = snapshot.filter_options or {"stages": [], "years": [], "cadres": [], "provinces": []}
    filter_options = {
        **filter_options,
        "provinces": [row["province"] for row in province_rows],
    }
    live_statistics = _atp_live_summary(snapshot)
    from apps.dashboard.nursing_catherine_breakdown import catherine_breakdown_overlay_payload

    licence_cleanse_overlay = catherine_breakdown_overlay_payload(snapshot)

    return {
        "has_snapshot": True,
        "snapshot": {
            "id": snapshot.pk,
            "snapshot_id": str(snapshot.snapshot_id),
            "source_file_name": snapshot.source_file_name,
            "source_file_hash": snapshot.source_file_hash,
            "workbook_generated_on": snapshot.workbook_generated_on.isoformat() if snapshot.workbook_generated_on else "",
            "created_at": snapshot.created_at.isoformat() if snapshot.created_at else "",
            "activated_at": snapshot.activated_at.isoformat() if snapshot.activated_at else "",
        },
        "kpis": kpis,
        "cards": [
            {"key": "total_lifecycle_records", "label": "Total Lifecycle Records", "value": int(kpis.get("total_lifecycle_records") or 0)},
            {"key": "clean_atp_records", "label": "Clean ATP Records", "value": int(kpis.get("clean_atp_records") or 0)},
            {"key": "clean_provisional_records", "label": "Clean Provisional Records", "value": int(kpis.get("clean_provisional_records") or 0)},
            {"key": "clean_full_licence_records", "label": "Clean Full-Licence Records", "value": int(kpis.get("clean_full_licence_records") or 0)},
            {"key": "data_quality_health_score", "label": "Data Quality Health Score", "value": float(kpis.get("data_quality_health_score") or 0), "suffix": "%"},
        ],
        "filters": filter_options,
        "charts": {
            "stage": {
                "labels": STAGE_LABELS,
                "values": stage_values,
            },
            "year": {
                "labels": [row["year"] if row["year"] is not None else row["year_label"] or "Unknown" for row in year_rows],
                "provisional": [row["provisional_licence_count"] for row in year_rows],
                "full_licence": [row["full_licence_count"] for row in year_rows],
                "authority_to_practice": [row["authority_to_practice_count"] for row in year_rows],
                "grand_total": [row["grand_total"] for row in year_rows],
            },
            "cadre": {
                "labels": [row["cadre"] for row in cadre_rows],
                "provisional": [row["provisional_licence_count"] for row in cadre_rows],
                "full_licence": [row["full_licence_count"] for row in cadre_rows],
                "authority_to_practice": [row["authority_to_practice_count"] for row in cadre_rows],
            },
            "province": {
                "labels": [row["province"] for row in province_rows],
                "values": [row["total"] for row in province_rows],
            },
            "quality": {
                "labels": [row["lifecycle_stage"] for row in quality_rows],
                "high": [row["high_count"] for row in quality_rows],
                "medium": [row["medium_count"] for row in quality_rows],
                "needs_review": [row["needs_review_count"] for row in quality_rows],
            },
            "facility": {
                "labels": [row["facility"] for row in facility_rows],
                "values": [row["total"] for row in facility_rows],
            },
            "institution": {
                "labels": [row["institution"] for row in institution_rows],
                "values": [row["total"] for row in institution_rows],
            },
        },
        "quality_rows": [
            {
                **row,
                "needs_review_percent": float(row["needs_review_percent"] or 0),
            }
            for row in quality_rows
        ],
        "facility_rows": facility_rows,
        "institution_rows": institution_rows,
        "live_statistics": live_statistics,
        "licence_cleanse_overlay": licence_cleanse_overlay,
    }


def dashboard_context():
    snapshot = active_nursing_analytics_snapshot()
    payload = metric_payload(snapshot)
    cards = payload.get("cards", [])
    return {
        "nursing_analytics_has_snapshot": bool(snapshot),
        "nursing_analytics_snapshot": snapshot,
        "nursing_analytics_payload": payload,
        "nursing_analytics_payload_json": json.dumps(payload, default=str),
        "nursing_analytics_kpi_cards": cards,
        "nursing_analytics_quality_rows": payload.get("quality_rows", []),
        "nursing_analytics_facility_rows": payload.get("facility_rows", []),
        "nursing_analytics_institution_rows": payload.get("institution_rows", []),
        "nursing_licence_cleanse_overlay": payload.get("licence_cleanse_overlay", {}),
        "nursing_analytics_stage_count": len(payload.get("charts", {}).get("stage", {}).get("labels", [])),
    }


def filtered_lifecycle_facts(snapshot, filters, search_value=""):
    queryset = NursingLifecycleFact.objects.filter(snapshot=snapshot)
    if filters.get("stage"):
        queryset = queryset.filter(lifecycle_stage=filters["stage"])
    if filters.get("year"):
        queryset = queryset.filter(cycle_year=filters["year"])
    if filters.get("cadre"):
        queryset = queryset.filter(cadre=filters["cadre"])
    if filters.get("province"):
        queryset = queryset.filter(province=filters["province"])
    if filters.get("institution"):
        queryset = queryset.filter(institution=filters["institution"])
    if filters.get("facility"):
        queryset = queryset.filter(facility=filters["facility"])
    if filters.get("quality"):
        queryset = queryset.filter(record_quality=filters["quality"])
    age_min = _to_non_negative_int(filters.get("age_min"))
    if age_min is not None:
        queryset = queryset.filter(age__gte=age_min)
    age_max = _to_non_negative_int(filters.get("age_max"))
    if age_max is not None:
        queryset = queryset.filter(age__lte=age_max)
    if search_value:
        from django.db.models import Q

        queryset = queryset.filter(
            Q(record_id__icontains=search_value)
            | Q(full_name__icontains=search_value)
            | Q(registration_no__icontains=search_value)
            | Q(practitioner_no__icontains=search_value)
            | Q(person_group_key__icontains=search_value)
            | Q(facility__icontains=search_value)
            | Q(institution__icontains=search_value)
        )
    return queryset
