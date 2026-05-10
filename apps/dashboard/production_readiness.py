from datetime import date
from pathlib import Path

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Q, Subquery
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from apps.common.models import DuplicateReviewQueue
from apps.dashboard.access import (
    MEDICAL_BOARD_FORM_CODES,
    MEDICAL_BOARD_PROFESSIONAL_MODELS,
    NURSING_COUNCIL_PROFESSIONAL_MODELS,
    is_data_quality_reviewer,
    is_medical_board_staff,
    is_nursing_council_staff,
)
from apps.dashboard.models import Receipt
from apps.workforce.models import (
    CommunityHealthWorker,
    DataImportBatch,
    HealthStudent,
    MedicalDoctor,
    Midwife,
    MissingDataReview,
    NurseAide,
    NursingProfessional,
    PracticingLicenseRecord,
)


MODEL_CONFIG = {
    "nursingprofessional": {
        "model": NursingProfessional,
        "scope": "nursing",
        "slug": "nursingprofessional",
        "label": "Registered Nurses",
    },
    "midwife": {
        "model": Midwife,
        "scope": "nursing",
        "slug": "midwife",
        "label": "Midwives",
    },
    "nurseaide": {
        "model": NurseAide,
        "scope": "nursing",
        "slug": "nurseaide",
        "label": "Nurse Aides",
    },
    "healthstudent": {
        "model": HealthStudent,
        "scope": "nursing",
        "slug": "graduand",
        "label": "Graduands / Health Students",
    },
    "medicaldoctor": {
        "model": MedicalDoctor,
        "scope": "medical",
        "slug": "medicaldoctor",
        "label": "Medical Doctors",
    },
    "communityhealthworker": {
        "model": CommunityHealthWorker,
        "scope": "medical",
        "slug": "communityhealthworker",
        "label": "Community Health Workers",
    },
}
DIRTY_IDENTIFIER_TOKENS = {"address", "unknown", "none", "nil", "n/a", "na", "tba", "tbc", "-"}


def _scope_for_user(user):
    if getattr(user, "role", "") == "admin" or is_data_quality_reviewer(user):
        return None
    if is_medical_board_staff(user):
        return "medical"
    if is_nursing_council_staff(user):
        return "nursing"
    return None


def _scope_label(scope):
    if scope == "medical":
        return "Medical Board"
    if scope == "nursing":
        return "Nursing Council"
    return "All Regulatory Offices"


def _allowed_model_keys(scope):
    if scope == "medical":
        return set(MEDICAL_BOARD_PROFESSIONAL_MODELS)
    if scope == "nursing":
        return set(NURSING_COUNCIL_PROFESSIONAL_MODELS)
    return set(MEDICAL_BOARD_PROFESSIONAL_MODELS) | set(NURSING_COUNCIL_PROFESSIONAL_MODELS)


def _professional_configs(scope):
    allowed = _allowed_model_keys(scope)
    return [
        config
        for key, config in MODEL_CONFIG.items()
        if key in allowed
    ]


def _model_has_field(model, field_name):
    return any(field.name == field_name for field in model._meta.fields)


def _record_name(record):
    full_name = str(getattr(record, "full_name", "") or "").strip()
    if full_name:
        return full_name
    first_name = str(getattr(record, "first_name", "") or "").strip()
    last_name = str(getattr(record, "last_name", "") or getattr(record, "surname", "") or "").strip()
    combined = f"{first_name} {last_name}".strip()
    return combined or str(record)


def _record_identifier(record):
    for attr in (
        "registration_no",
        "registration_number",
        "practitioner_number",
        "official_receipt_no",
        "receipt_number",
        "reference_number",
    ):
        value = str(getattr(record, attr, "") or "").strip()
        if value:
            return value
    return f"Record #{record.pk}"


def _source_label(record):
    if isinstance(record, Receipt):
        return "Manual receipt table"
    sheet_name = getattr(record, "source_sheet_name", "") or ""
    row_number = getattr(record, "source_row", "") or ""
    batch_name = getattr(getattr(record, "batch", None), "source_file_name", "") or ""
    if sheet_name and row_number:
        return f"{sheet_name}, row {row_number}"
    return sheet_name or batch_name or "No source label"


def _record_update_url(model_key, object_id):
    config = MODEL_CONFIG.get(model_key)
    if not config:
        return ""
    try:
        return reverse("record_update", args=[config["slug"], object_id])
    except NoReverseMatch:
        return ""


def _receipt_queryset(scope):
    queryset = Receipt.objects.select_related("application", "application__content_type")
    if scope == "medical":
        return queryset.filter(
            Q(application__form_code__in=MEDICAL_BOARD_FORM_CODES)
            | Q(application__content_type__model__in=MEDICAL_BOARD_PROFESSIONAL_MODELS)
        )
    if scope == "nursing":
        return queryset.filter(
            Q(application__content_type__model__in=NURSING_COUNCIL_PROFESSIONAL_MODELS)
            | Q(application__form_code__istartswith="NC")
            | Q(application__form_code__istartswith="G")
        )
    return queryset


def _practicing_license_queryset(scope):
    queryset = PracticingLicenseRecord.objects.select_related("batch")
    if scope:
        queryset = queryset.filter(target_model__in=_allowed_model_keys(scope))
    return queryset


def _missing_reviews_queryset(scope, include_resolved=False):
    queryset = MissingDataReview.objects.select_related("content_type")
    if not include_resolved:
        queryset = queryset.exclude(status="resolved")
    if scope is None:
        return queryset

    practicing_content_type = ContentType.objects.get_for_model(PracticingLicenseRecord)
    scoped_import_ids = _practicing_license_queryset(scope).values("id")
    return queryset.filter(
        Q(content_type__model__in=_allowed_model_keys(scope))
        | Q(content_type=practicing_content_type, object_id__in=Subquery(scoped_import_ids))
    )


def _duplicate_reviews_queryset(scope):
    queryset = DuplicateReviewQueue.objects.select_related("content_type", "reviewed_by")
    if scope is None:
        return queryset

    practicing_content_type = ContentType.objects.get_for_model(PracticingLicenseRecord)
    scoped_import_ids = _practicing_license_queryset(scope).values("id")
    return queryset.filter(
        Q(content_type__model__in=_allowed_model_keys(scope))
        | Q(suspected_duplicate__target_model__in=_allowed_model_keys(scope))
        | Q(content_type=practicing_content_type, object_id__in=Subquery(scoped_import_ids))
    )


def build_production_readiness_review_queryset(user):
    return _missing_reviews_queryset(_scope_for_user(user), include_resolved=True)


def _duplicate_identifier_rows(scope, limit=10):
    rows = []
    for config in _professional_configs(scope):
        model = config["model"]
        for field_name in ("registration_no", "registration_number"):
            if not _model_has_field(model, field_name):
                continue
            groups = (
                model.objects
                .exclude(**{f"{field_name}__isnull": True})
                .exclude(**{field_name: ""})
                .values(field_name)
                .annotate(total=Count("id"))
                .filter(total__gt=1)
                .order_by("-total", field_name)[:limit]
            )
            for group in groups:
                rows.append({
                    "model": config["label"],
                    "field": field_name.replace("_", " ").title(),
                    "value": group[field_name],
                    "total": group["total"],
                })
    rows.sort(key=lambda item: (-item["total"], item["model"], item["field"]))
    return rows[:limit]


def _unique_conflict_samples(scope, limit=10):
    rows = []
    for config in _professional_configs(scope):
        model = config["model"]
        for field_name in ("registration_no", "registration_number"):
            if not _model_has_field(model, field_name):
                continue
            filters = Q()
            for token in DIRTY_IDENTIFIER_TOKENS:
                filters |= Q(**{f"{field_name}__iexact": token})
            queryset = model.objects.filter(filters)
            for obj in queryset.order_by("id")[:limit]:
                rows.append({
                    "model": config["label"],
                    "field": field_name.replace("_", " ").title(),
                    "value": getattr(obj, field_name, ""),
                    "name": _record_name(obj),
                    "id": obj.pk,
                    "record_url": _record_update_url(next(key for key, value in MODEL_CONFIG.items() if value["model"] == model), obj.pk),
                })
    receipt_queryset = _receipt_queryset(scope).filter(
        Q(receipt_number__iexact="unknown")
        | Q(receipt_number__iexact="n/a")
        | Q(receipt_number__iexact="na")
        | Q(official_receipt_no__iexact="unknown")
        | Q(official_receipt_no__iexact="n/a")
        | Q(official_receipt_no__iexact="na")
    ).order_by("id")[:limit]
    for receipt in receipt_queryset:
        rows.append({
            "model": "Receipt",
            "field": "Receipt Number",
            "value": receipt.official_receipt_no or receipt.receipt_number,
            "name": receipt.receipt_number,
            "id": receipt.pk,
            "record_url": "",
        })
    return rows[:limit]


def _date_issue_samples(queryset, date_attr, limit):
    rows = []
    for record in queryset[:limit]:
        rows.append({
            "name": _record_name(record),
            "identifier": _record_identifier(record),
            "date_value": getattr(record, date_attr, None),
            "source": _source_label(record),
        })
    return rows


def _date_issue_rows(scope, limit=10):
    today = timezone.localdate()
    cutoff = date(2000, 1, 1)
    records = _practicing_license_queryset(scope)
    receipts = _receipt_queryset(scope)
    future_issued = records.filter(issued_date__gt=today).order_by("issued_date", "source_sheet_name", "source_row")
    future_payment = records.filter(payment_date__gt=today).order_by("payment_date", "source_sheet_name", "source_row")
    old_issued = records.filter(issued_date__lt=cutoff).order_by("issued_date", "source_sheet_name", "source_row")
    old_payment = records.filter(payment_date__lt=cutoff).order_by("payment_date", "source_sheet_name", "source_row")
    future_receipts = receipts.filter(receipt_date__date__gt=today).order_by("receipt_date")
    issues = [
        {
            "label": "Future import issued dates",
            "count": future_issued.count(),
            "records": _date_issue_samples(future_issued, "issued_date", limit),
            "date_attr": "issued_date",
            "risk": "The issued date is later than today and can distort licence activity trends.",
        },
        {
            "label": "Future import payment dates",
            "count": future_payment.count(),
            "records": _date_issue_samples(future_payment, "payment_date", limit),
            "date_attr": "payment_date",
            "risk": "The payment date is later than today and can distort financial forecast totals.",
        },
        {
            "label": "Old import issued dates before 2000",
            "count": old_issued.count(),
            "records": _date_issue_samples(old_issued, "issued_date", limit),
            "date_attr": "issued_date",
            "risk": "The issued date may be a parsing error, legacy placeholder, or source-data problem.",
        },
        {
            "label": "Old import payment dates before 2000",
            "count": old_payment.count(),
            "records": _date_issue_samples(old_payment, "payment_date", limit),
            "date_attr": "payment_date",
            "risk": "The payment date may be a parsing error or historical source issue.",
        },
        {
            "label": "Future manual receipt dates",
            "count": future_receipts.count(),
            "records": _date_issue_samples(future_receipts, "receipt_date", limit),
            "date_attr": "receipt_date",
            "risk": "The receipt date is in the future and needs finance verification.",
        },
    ]
    return issues


def _missing_review_row(review):
    model_key = review.content_type.model
    missing_fields = review.missing_fields if isinstance(review.missing_fields, list) else []
    return {
        "id": review.id,
        "full_name": review.full_name or "Unnamed record",
        "professional_type": review.professional_type or review.content_type.name,
        "registration_no": review.registration_no or "-",
        "missing_fields": ", ".join(str(field) for field in missing_fields) or "-",
        "missing_count": review.missing_count,
        "severity": review.severity,
        "status": review.status,
        "status_label": review.get_status_display(),
        "source_label": review.source_label or "No source label",
        "source_row": review.source_row,
        "record_url": _record_update_url(model_key, review.object_id),
    }


def _missing_data_summary(scope):
    queryset = _missing_reviews_queryset(scope)
    by_severity = {
        row["severity"]: row["total"]
        for row in (
            queryset
            .values("severity")
            .annotate(total=Count("id"))
        )
    }
    by_type = list(
        queryset
        .values("professional_type")
        .annotate(total=Count("id"))
        .order_by("-total", "professional_type")[:10]
    )
    recent = queryset.order_by("-updated_at")[:12]
    return {
        "open": queryset.count(),
        "high": by_severity.get("high", 0),
        "medium": by_severity.get("medium", 0),
        "low": by_severity.get("low", 0),
        "by_type": by_type,
        "recent": [_missing_review_row(review) for review in recent],
    }


def _latest_readiness_reports(limit=5):
    report_dir = Path("docs") / "reports"
    if not report_dir.exists():
        return []
    reports = sorted(
        report_dir.glob("production_data_readiness_*.md"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )[:limit]
    return [
        {
            "name": path.name,
            "path": str(path),
            "size": path.stat().st_size,
            "modified_at": timezone.datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.get_current_timezone()),
        }
        for path in reports
    ]


def _import_batches(scope):
    queryset = DataImportBatch.objects.all()
    if scope == "medical":
        queryset = queryset.filter(
            Q(source_kind__icontains="medical")
            | Q(source_file_name__icontains="medical")
            | Q(source_file_name__icontains="doctor")
            | Q(source_file_name__icontains="chw")
        )
    elif scope == "nursing":
        queryset = queryset.filter(
            Q(source_kind__icontains="nursing")
            | Q(source_kind__icontains="ndata")
            | Q(source_kind__icontains="atp")
            | Q(source_file_name__icontains="nursing")
            | Q(source_file_name__icontains="n-data")
            | Q(source_file_name__icontains="atp")
            | Q(source_file_name__icontains="provisional")
            | Q(source_file_name__icontains="full registration")
        )
    return queryset.order_by("-started_at", "-id")


def build_production_readiness_context(user):
    scope = _scope_for_user(user)
    date_issues = _date_issue_rows(scope)
    missing_data = _missing_data_summary(scope)
    duplicate_review_open = _duplicate_reviews_queryset(scope).filter(status="pending").count()
    import_batches = _import_batches(scope)[:8]
    import_status_rows = list(
        _import_batches(scope).values("status").annotate(total=Count("id")).order_by("status")
    )
    duplicate_identifier_rows = _duplicate_identifier_rows(scope)
    conflict_rows = _unique_conflict_samples(scope)
    total_date_issues = sum(row["count"] for row in date_issues)
    critical_total = total_date_issues + missing_data["high"] + duplicate_review_open + len(conflict_rows)

    return {
        "generated_at": timezone.localtime(),
        "scope_label": _scope_label(scope),
        "readiness_status": "Needs Data Review" if critical_total else "Ready For UAT Review",
        "critical_total": critical_total,
        "total_date_issues": total_date_issues,
        "date_issues": date_issues,
        "missing_data": missing_data,
        "duplicate_review_open": duplicate_review_open,
        "duplicate_identifier_rows": duplicate_identifier_rows,
        "unique_conflict_rows": conflict_rows,
        "import_batches": import_batches,
        "import_status_rows": import_status_rows,
        "latest_reports": _latest_readiness_reports(),
        "production_rule": (
            "Imported rows are not automatically trusted. They are staged, validated, cleansed, "
            "reviewed, approved, then promoted into live registry records."
        ),
    }
