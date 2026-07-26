from django.db.models import Q
from django.urls import NoReverseMatch, reverse

from apps.common.record_views import scoped_record_queryset
from apps.dashboard.access import (
    is_data_quality_reviewer,
    is_finance_reviewer,
    is_medical_board_staff,
    is_nursing_council_staff,
)
from apps.dashboard.registry_archive import active_import_record_queryset
from apps.workforce.models import PracticingLicenseRecord


MAX_STAFF_AI_RECORD_RESULTS = 8
MAX_STAFF_AI_QUERY_LENGTH = 160
ALLOWED_RECORD_TYPES = {
    choice[0]
    for choice in PracticingLicenseRecord.RECORD_TYPE_CHOICES
}
RECORD_TYPE_ALIASES = {
    "atp": "practicing_license",
    "authority to practice": "practicing_license",
    "practicing license": "practicing_license",
    "practising license": "practicing_license",
    "practicing licence": "practicing_license",
    "practising licence": "practicing_license",
    "full approved": "full_approved",
    "approved full": "full_approved",
    "approved full license": "full_approved",
    "approved full licence": "full_approved",
    "full license": "full",
    "full licence": "full",
    "full-license": "full",
    "full-licence": "full",
    "provisional": "provisional",
    "temporary": "temporary",
    "payment": "payment",
}
TARGET_MODEL_ALIASES = {
    "nurse": "nursingprofessional",
    "registered nurse": "nursingprofessional",
    "nursing professional": "nursingprofessional",
    "midwife": "midwife",
    "nurse aide": "nurseaide",
    "nurseaide": "nurseaide",
    "graduand": "healthstudent",
    "student": "healthstudent",
    "health student": "healthstudent",
    "doctor": "medicaldoctor",
    "medical doctor": "medicaldoctor",
    "chw": "communityhealthworker",
    "community health worker": "communityhealthworker",
}


def _clean_text(value, max_length=MAX_STAFF_AI_QUERY_LENGTH):
    return " ".join(str(value or "").strip().split())[:max_length]


def _staff_lookup_scope(user):
    if not getattr(user, "is_authenticated", False):
        return ""
    if is_finance_reviewer(user):
        return ""
    if getattr(user, "role", "") == "admin":
        return "all"
    if is_medical_board_staff(user):
        return "medical"
    if is_nursing_council_staff(user):
        return "nursing"
    if is_data_quality_reviewer(user):
        return "all"
    return ""


def _scope_label(scope):
    return {
        "all": "All Regulatory Offices",
        "medical": "Medical Board",
        "nursing": "Nursing Council",
    }.get(scope, "Restricted")


def _normalize_record_type(value):
    cleaned = _clean_text(value, max_length=80).lower().replace("_", " ")
    if not cleaned:
        return ""
    normalized = RECORD_TYPE_ALIASES.get(cleaned, cleaned.replace(" ", "_").replace("-", "_"))
    return normalized if normalized in ALLOWED_RECORD_TYPES else ""


def _normalize_target_model(value):
    cleaned = _clean_text(value, max_length=80).lower().replace("_", " ")
    if not cleaned:
        return ""
    normalized = TARGET_MODEL_ALIASES.get(cleaned, cleaned.replace(" ", "").replace("-", ""))
    allowed_targets = {
        choice[0]
        for choice in PracticingLicenseRecord.TARGET_MODEL_CHOICES
    }
    return normalized if normalized in allowed_targets else ""


def _normalize_year(value):
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    if 1900 <= year <= 2100:
        return year
    return None


def _normalize_limit(value):
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = 5
    return max(1, min(limit, MAX_STAFF_AI_RECORD_RESULTS))


def _record_display(record):
    try:
        record_url = reverse(
            "record_detail",
            kwargs={"model_slug": "practicinglicenserecord", "pk": record.id},
        )
    except NoReverseMatch:
        # The assistant can still return a safe reference if a deployment has
        # not mounted the Records Hub URL namespace.
        record_url = ""

    source_reference_parts = []
    if record.source_sheet_name:
        source_reference_parts.append(str(record.source_sheet_name))
    if record.source_row:
        source_reference_parts.append(f"row {record.source_row}")

    return {
        "id": record.id,
        # This URL is deliberately a normal Records Hub detail URL.  Its
        # permission checks run again when staff open it; it is not a bypass
        # around the role- and office-scoped queryset above.
        "record_url": record_url,
        "source_reference": " - ".join(source_reference_parts),
        "full_name": record.full_name,
        "record_type": record.get_record_type_display(),
        "record_type_code": record.record_type,
        "target": record.get_target_model_display(),
        "target_model": record.target_model,
        "registration_no": record.registration_no,
        "practitioner_number": record.practitioner_number,
        "record_year": record.record_year,
        "category": record.category,
        "province": record.province,
        "issued_date": record.issued_date.isoformat() if record.issued_date else "",
        "source_file_name": getattr(record.batch, "source_file_name", ""),
        "source_kind": getattr(record.batch, "source_kind", ""),
        "source_sheet_name": record.source_sheet_name,
        "source_row": record.source_row,
    }


def search_staff_registry_records_for_user(
    user,
    *,
    query="",
    record_type="",
    target_model="",
    year=0,
    province="",
    limit=5,
):
    scope = _staff_lookup_scope(user)
    if scope not in {"all", "medical", "nursing"}:
        return {
            "status": "denied",
            "scope": "restricted",
            "scope_label": _scope_label(scope),
            "total_matches": 0,
            "returned": 0,
            "records": [],
            "message": "This staff account is not authorised for live registry record lookup.",
        }

    cleaned_query = _clean_text(query)
    cleaned_province = _clean_text(province, max_length=80)
    normalized_record_type = _normalize_record_type(record_type)
    normalized_target_model = _normalize_target_model(target_model)
    normalized_year = _normalize_year(year)
    bounded_limit = _normalize_limit(limit)

    queryset = scoped_record_queryset(
        PracticingLicenseRecord,
        user,
        "practicinglicenserecord",
    ).select_related("batch", "sheet")
    queryset = active_import_record_queryset(queryset, scope=scope)

    if cleaned_query:
        query_filter = (
            Q(full_name__icontains=cleaned_query)
            | Q(registration_no__icontains=cleaned_query)
            | Q(practitioner_number__icontains=cleaned_query)
            | Q(reference_number__icontains=cleaned_query)
            | Q(category__icontains=cleaned_query)
            | Q(province__icontains=cleaned_query)
            | Q(qualification_name__icontains=cleaned_query)
            | Q(institution_name__icontains=cleaned_query)
            | Q(source_sheet_name__icontains=cleaned_query)
        )
        queryset = queryset.filter(query_filter)
    if normalized_record_type:
        queryset = queryset.filter(record_type=normalized_record_type)
    if normalized_target_model:
        queryset = queryset.filter(target_model=normalized_target_model)
    if normalized_year:
        queryset = queryset.filter(record_year=normalized_year)
    if cleaned_province:
        queryset = queryset.filter(province__icontains=cleaned_province)

    total_matches = queryset.count()
    records = [
        _record_display(record)
        for record in queryset.order_by("-record_year", "full_name", "-id")[:bounded_limit]
    ]
    return {
        "status": "ok",
        "scope": scope,
        "scope_label": _scope_label(scope),
        "filters": {
            "query": cleaned_query,
            "record_type": normalized_record_type,
            "target_model": normalized_target_model,
            "year": normalized_year,
            "province": cleaned_province,
            "limit": bounded_limit,
        },
        "total_matches": total_matches,
        "returned": len(records),
        "records": records,
        "redactions": [
            "date_of_birth",
            "contact_details",
            "full_address",
            "raw_payload",
            "payment_amounts",
        ],
    }


def build_staff_ai_record_lookup_tools(user):
    def search_staff_registry_records(
        query: str = "",
        record_type: str = "",
        target_model: str = "",
        year: int = 0,
        province: str = "",
        limit: int = 5,
    ) -> dict:
        """Search live registry and licence records within the signed-in staff user's Django permissions.

        Args:
            query: Name, registration number, practitioner number, category, province, or source-sheet text.
            record_type: Optional lifecycle filter such as provisional, full, full_approved, or atp.
            target_model: Optional practitioner type such as nurse, midwife, doctor, chw, nurse aide, or graduand.
            year: Optional record year.
            province: Optional province text filter.
            limit: Maximum records to return, capped by the platform.
        """
        return search_staff_registry_records_for_user(
            user,
            query=query,
            record_type=record_type,
            target_model=target_model,
            year=year,
            province=province,
            limit=limit,
        )

    return [search_staff_registry_records]
