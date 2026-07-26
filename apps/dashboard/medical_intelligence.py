"""Read-only aggregate intelligence for the Medical Board workspace.

This module intentionally returns *only* counts and grouped summaries.  It is
safe to add to a Medical Board dashboard after that view has already applied
its normal role/scope access check; it never returns practitioner, complainant
or disciplinary-case identities.

The existing live registry models are used as the baseline.  The three newer
clinical-regulation models are looked up dynamically so this service remains
usable while their migration is being rolled out.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date
import hashlib
import json
import re
from typing import Any, Mapping

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db import DatabaseError, transaction
from django.db.models import Avg, CharField, Count, F, Max, Q, Value
from django.db.models.functions import Coalesce, NullIf
from django.utils import timezone

from apps.complaints.models import DisciplinaryCase
from apps.workforce.models import (
    Application,
    EmploymentRecord,
    Facility,
    MedicalDoctor,
    ProfessionalDocument,
    Qualification,
)


MEDICAL_RENEWAL_FORM_CODES = ("MD2", "MBRN")
MEDICAL_APPLICATION_FORM_CODES = (
    "MD1",
    "MD2",
    "CHW1",
    "CHWP",
    "CHWF",
    "MBSP",
    "MBRN",
    "MBAC",
    "MBPF",
    "MBTC",
)
FACILITY_ACCREDITATION_FORM_CODES = ("MBAC", "MBPF", "MBTC")
SPECIALIST_APPLICATION_FORM_CODE = "MBSP"

FILTER_KEYS = ("specialty", "province", "district", "facility", "sector", "gender")
MAX_GROUP_ROWS = 25
MEDICAL_INTELLIGENCE_CACHE_TTL_SECONDS = 60
CACHE_KEY_VERSION = 1


# These are intentionally only *query words*.  They are matched against
# governed aggregate filter options below; they never turn a name,
# registration number, complaint, or document reference into a filter.
_SPECIALTY_WORD_ALIASES = {
    "surgery": ("surgeon", "surgeons"),
    "paediatrics": ("paediatrician", "paediatricians", "pediatrician", "pediatricians"),
    "pediatrics": ("pediatrician", "pediatricians", "paediatrician", "paediatricians"),
    "obstetrics and gynaecology": ("obstetrician", "obstetricians", "gynaecologist", "gynaecologists"),
    "obstetrics and gynecology": ("obstetrician", "obstetricians", "gynecologist", "gynecologists"),
}


def resolve_medical_board_aggregate_filters(
    question: str,
    filter_options: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Resolve only exact governed aggregate filters from a staff question.

    This is deliberately a small, deterministic parser rather than a record
    search.  It works only from the specialty, province, district, facility,
    sector, and gender labels already exposed as aggregate dashboard filter
    options.  If wording is ambiguous or does not match a governed label, the
    caller receives an explicit unresolved flag and must not guess a count.
    """

    normalized_question = _normalized_filter_text(question)
    options = filter_options or {}
    resolved: dict[str, str] = {}
    for key in FILTER_KEYS:
        values = options.get(key, []) if isinstance(options, Mapping) else []
        match = _match_question_filter_value(
            normalized_question,
            values,
            specialty=(key == "specialty"),
        )
        if match:
            resolved[key] = match

    specific_specialty_requested = bool(
        re.search(
            r"\b(?:cardiologist|cardiologists|surgeon|surgeons|radiologist|radiologists|"
            r"oncologist|oncologists|neurologist|neurologists|paediatrician|paediatricians|"
            r"pediatrician|pediatricians)\b",
            normalized_question,
        )
        or re.search(r"\b[a-z]+(?:ologist|ologists|iatrist|iatrists|surgeon|surgeons|physician|physicians)\b", normalized_question)
    ) or bool(resolved.get("specialty"))
    specialty_requested = bool(
        re.search(r"\b(?:specialist|specialists|specialty|specialties)\b", normalized_question)
    ) or specific_specialty_requested
    geography_requested = bool(
        re.search(r"\b(?:province|district|region)\b", normalized_question)
        or re.search(r"\b(?:in|within|across|at)\s+(?:the\s+)?[a-z]", normalized_question)
    )
    geographic_filters = {
        key: resolved[key]
        for key in ("province", "district", "facility")
        if resolved.get(key)
    }
    return {
        "filters": resolved,
        "specialty_requested": specialty_requested,
        "specific_specialty_requested": specific_specialty_requested,
        "geography_requested": geography_requested,
        "geographic_filters": geographic_filters,
        "unresolved_specialty": specific_specialty_requested and not bool(resolved.get("specialty")),
        "unresolved_geography": geography_requested and not bool(geographic_filters),
    }


def _normalized_filter_text(value: Any) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).split())


def _match_question_filter_value(
    normalized_question: str,
    values: Any,
    *,
    specialty: bool = False,
) -> str:
    """Return one unambiguous, exact option label present in ``question``."""

    matches: list[tuple[int, str]] = []
    for raw_value in values or []:
        value = str(raw_value or "").strip()
        normalized_value = _normalized_filter_text(value)
        if not normalized_value:
            continue
        search_terms = {normalized_value}
        if specialty:
            search_terms.update(_specialty_search_terms(normalized_value))
        if any(_question_contains_filter_term(normalized_question, term) for term in search_terms):
            matches.append((len(normalized_value), value))

    if not matches:
        return ""
    matches.sort(key=lambda item: (-item[0], item[1].casefold()))
    # A longer exact option is more specific (for example, Western Highlands
    # rather than Western).  Do not choose between equally specific labels.
    if len(matches) > 1 and matches[0][0] == matches[1][0]:
        return ""
    return matches[0][1]


def _specialty_search_terms(normalized_specialty: str) -> set[str]:
    terms = set(_SPECIALTY_WORD_ALIASES.get(normalized_specialty, ()))
    if normalized_specialty.endswith("ology"):
        terms.add(f"{normalized_specialty[:-1]}ist")
    if normalized_specialty.endswith("iatry"):
        terms.add(f"{normalized_specialty[:-1]}ist")
    # The label itself remains the authoritative match.  These forms simply
    # recognise common staff wording such as "cardiologists" for Cardiology.
    plural_terms = {f"{term}s" for term in terms if not term.endswith("s")}
    return terms | plural_terms


def _question_contains_filter_term(question: str, term: str) -> bool:
    if not term:
        return False
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", question))


def build_medical_board_intelligence_context(
    filters: Mapping[str, Any] | None = None,
    *,
    today: date | None = None,
    limit: int = 12,
) -> dict[str, Any]:
    """Build a fast, read-only Medical Board intelligence context.

    ``filters`` supports specialty, province, district, facility, sector, and
    gender.  They affect workforce-profile and specialist results, not the
    operational queues (renewals, disciplinary cases, or accreditation).  The
    caller must still enforce Medical Board staff access before rendering this
    context.

    A missing optional migration or an empty database returns a zero-value,
    explicit "not ready" context rather than failing the portal.  No operation
    in this function writes to the database.
    """

    normalized_filters = _normalize_filters(filters)
    report_date = today or timezone.localdate()
    group_limit = _normalize_limit(limit)
    data_marker = _medical_intelligence_data_marker()
    cache_key = _medical_intelligence_cache_key(
        normalized_filters,
        report_date,
        group_limit,
        data_marker,
    )
    if cache_key:
        cached_context = cache.get(cache_key)
        if cached_context is not None:
            return deepcopy(cached_context)

    context = _build_live_medical_board_intelligence_context(
        normalized_filters,
        report_date,
        group_limit,
    )
    if cache_key and _context_is_cacheable(context):
        # The cache must never share mutable lists/dicts with a template or
        # another caller.  Store and return independent copies.
        cache.set(
            cache_key,
            deepcopy(context),
            timeout=MEDICAL_INTELLIGENCE_CACHE_TTL_SECONDS,
        )
    return deepcopy(context)


def _build_live_medical_board_intelligence_context(
    normalized_filters: dict[str, str],
    report_date: date,
    group_limit: int,
) -> dict[str, Any]:
    """Build the uncached aggregate payload used by the short-lived cache."""

    context = _empty_context(normalized_filters, report_date)

    try:
        doctor_content_type = ContentType.objects.get_for_model(MedicalDoctor)
        facility_content_type = ContentType.objects.get_for_model(Facility)
        doctors, filtered_employment = _filtered_medical_doctors(
            normalized_filters,
            doctor_content_type,
        )

        facility_snapshot = _facility_accreditation_snapshot(
            facility_content_type,
            report_date,
            group_limit,
        )
        credential_evidence = _credential_evidence_snapshot(
            doctor_content_type,
            report_date,
        )
        clinical_privileges = _clinical_privilege_snapshot(
            doctor_content_type,
            report_date,
            group_limit,
        )

        metrics = {
            "registered_doctors": doctors.count(),
            "active_practitioners": doctors.filter(is_active=True)
            .filter(Q(license_expiry_date__isnull=True) | Q(license_expiry_date__gte=report_date))
            .count(),
            "specialists": _specialist_queryset(doctors).count(),
            "expired_licences": doctors.filter(license_expiry_date__lt=report_date).count(),
            "pending_renewals": Application.objects.filter(
                form_code__in=MEDICAL_RENEWAL_FORM_CODES,
                status="pending",
            ).count(),
            "pending_medical_applications": Application.objects.filter(
                form_code__in=MEDICAL_APPLICATION_FORM_CODES,
                status="pending",
            ).count(),
            "open_disciplinary_cases": DisciplinaryCase.objects.filter(
                office_scope="medical",
            )
            .exclude(status__in=("closed", "withdrawn"))
            .count(),
            "accredited_facilities": facility_snapshot["registered_facility_count"],
            "overseas_practitioners": doctors.filter(applicant_type="overseas").count(),
        }

        specialty_distribution = _grouped_doctor_distribution(
            _specialist_queryset(doctors),
            "specialty",
            group_limit,
        )
        province_distribution = _grouped_doctor_distribution(doctors, "province", group_limit)
        employment_distributions = _employment_distributions(filtered_employment, group_limit)
        filter_options = _filter_options(doctor_content_type)

        intelligence = {
            "available": True,
            "status": "Live aggregate Medical Board registry intelligence.",
            "generated_on": report_date,
            "filters": normalized_filters,
            "metric_definitions": {
                "active_practitioners": (
                    "Active profile with no recorded expired licence. A blank expiry date is not treated as expired."
                ),
                "accredited_facilities": facility_snapshot["metric_definition"],
                "open_disciplinary_cases": (
                    "Medical Board cases not closed or withdrawn; no case identities are included."
                ),
            },
            "privacy_notice": (
                "Aggregate decision support only. This context contains no practitioner, complaint, "
                "disciplinary, document, or clinical-detail identities."
            ),
        }
        context.update(
            {
                "medical_intelligence": intelligence,
                "medical_executive_metrics": metrics,
                "medical_specialty_distribution": specialty_distribution,
                "medical_province_distribution": province_distribution,
                "medical_district_distribution": employment_distributions["districts"],
                "medical_facility_distribution": employment_distributions["facilities"],
                "medical_sector_distribution": employment_distributions["sectors"],
                "medical_facility_accreditation": facility_snapshot,
                "medical_credential_evidence": credential_evidence,
                "medical_clinical_privileges": clinical_privileges,
                "medical_intelligence_filter_options": filter_options,
            }
        )
        return context
    except DatabaseError:
        # This includes a first deployment before a related migration has been
        # applied.  Returning a clearly empty state keeps the staff portal
        # usable and avoids silently substituting unscoped data.
        context["medical_intelligence"] = {
            **context["medical_intelligence"],
            "available": False,
            "status": "Medical intelligence is not ready until registry migrations and approved data are available.",
        }
        return context


def _empty_context(filters: dict[str, str], report_date: date) -> dict[str, Any]:
    metrics = {
        "registered_doctors": 0,
        "active_practitioners": 0,
        "specialists": 0,
        "expired_licences": 0,
        "pending_renewals": 0,
        "pending_medical_applications": 0,
        "open_disciplinary_cases": 0,
        "accredited_facilities": 0,
        "overseas_practitioners": 0,
    }
    facility_snapshot = {
        "available": False,
        "source": "No facility-accreditation data available",
        "registered_facility_count": 0,
        "approved_application_count": 0,
        "pending_application_count": 0,
        "rejected_application_count": 0,
        "average_compliance_score": None,
        "status_distribution": [],
        "metric_definition": "Approved Medical Board facility-accreditation records linked to a Facility master record.",
    }
    credential_evidence = {
        "available": False,
        "qualification_records": 0,
        "qualifications_with_certificate": 0,
        "uploaded_document_records": 0,
        "signed_document_records": 0,
        "verified_credential_records": 0,
        "pending_credential_records": 0,
        "specialist_applications_pending": 0,
        "specialist_applications_approved": 0,
        "note": "Credential evidence has not been loaded yet.",
    }
    privileges = {
        "supported": False,
        "available": False,
        "active_privilege_count": 0,
        "status_distribution": [],
        "facility_distribution": [],
        "note": (
            "Clinical privileges are not inferred from a specialty. A dedicated, approved privilege record is required."
        ),
    }
    return {
        "medical_intelligence": {
            "available": True,
            "status": "Live aggregate Medical Board registry intelligence.",
            "generated_on": report_date,
            "filters": filters,
            "metric_definitions": {},
            "privacy_notice": (
                "Aggregate decision support only. This context contains no practitioner, complaint, "
                "disciplinary, document, or clinical-detail identities."
            ),
        },
        "medical_executive_metrics": metrics,
        "medical_specialty_distribution": [],
        "medical_province_distribution": [],
        "medical_district_distribution": [],
        "medical_facility_distribution": [],
        "medical_sector_distribution": [],
        "medical_facility_accreditation": facility_snapshot,
        "medical_credential_evidence": credential_evidence,
        "medical_clinical_privileges": privileges,
        "medical_intelligence_filter_options": {key: [] for key in FILTER_KEYS},
    }


def _normalize_filters(filters: Mapping[str, Any] | None) -> dict[str, str]:
    source = filters or {}
    normalized: dict[str, str] = {}
    for key in FILTER_KEYS:
        try:
            raw_value = source.get(key, "")
        except AttributeError:
            raw_value = ""
        normalized[key] = str(raw_value or "").strip()[:120]
    return normalized


def _normalize_limit(limit: int) -> int:
    try:
        return max(1, min(int(limit), MAX_GROUP_ROWS))
    except (TypeError, ValueError):
        return 12


def _medical_intelligence_data_marker() -> tuple[Any, ...] | None:
    """Return a cheap aggregate-only change marker, or ``None`` when unsafe.

    A marker deliberately contains no names, registration numbers, document
    labels, or complaint data.  It catches common create/update paths quickly;
    the one-minute cache bucket remains the bound for legacy tables that lack
    an ``updated_at`` column.
    """

    model_specs = [
        (MedicalDoctor, ("updated_at",)),
        (EmploymentRecord, ("created_at",)),
        (Facility, ()),
        (Application, ("submitted_date", "approved_date")),
        (DisciplinaryCase, ("updated_at",)),
        (Qualification, ()),
        (ProfessionalDocument, ("uploaded_at",)),
    ]
    for model_name in ("FacilityAccreditation", "CredentialVerification", "ClinicalPrivilege"):
        optional_model = _optional_workforce_model(model_name)
        if optional_model is not None:
            model_specs.append((optional_model, ("updated_at",)))

    try:
        # Optional models can be loaded before their tables are migrated.  A
        # savepoint makes that a cache miss instead of breaking the outer view
        # transaction or accidentally caching a fallback/degraded response.
        with transaction.atomic():
            return tuple(
                _model_cache_marker(model, timestamp_fields)
                for model, timestamp_fields in model_specs
            )
    except DatabaseError:
        return None


def _model_cache_marker(model, timestamp_fields: tuple[str, ...]) -> tuple[Any, ...]:
    aggregates: dict[str, Any] = {
        "row_count": Count("pk"),
        "last_pk": Max("pk"),
    }
    included_timestamp_fields = []
    for field_name in timestamp_fields:
        if _has_field(model, field_name):
            aggregate_name = f"latest_{field_name}"
            aggregates[aggregate_name] = Max(field_name)
            included_timestamp_fields.append((field_name, aggregate_name))
    values = model._default_manager.aggregate(**aggregates)
    return (
        model._meta.label_lower,
        values["row_count"],
        values["last_pk"],
        tuple(
            (field_name, _marker_value(values.get(aggregate_name)))
            for field_name, aggregate_name in included_timestamp_fields
        ),
    )


def _marker_value(value: Any) -> str | int | float | bool | None:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _medical_intelligence_cache_key(
    filters: dict[str, str],
    report_date: date,
    group_limit: int,
    data_marker: tuple[Any, ...] | None,
) -> str | None:
    if data_marker is None:
        return None
    minute_bucket = timezone.localtime(timezone.now()).replace(second=0, microsecond=0).isoformat()
    payload = {
        "version": CACHE_KEY_VERSION,
        "filters": filters,
        "report_date": report_date.isoformat(),
        "minute": minute_bucket,
        "limit": group_limit,
        "marker": data_marker,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    return f"medical-intelligence:{CACHE_KEY_VERSION}:{digest}"


def _context_is_cacheable(context: Mapping[str, Any]) -> bool:
    intelligence = context.get("medical_intelligence") or {}
    if not intelligence.get("available"):
        return False

    # Do not cache a partial result produced while a registered optional model
    # is waiting for its migration.  (When the model is not installed at all,
    # the explicit unsupported state is a normal, cacheable capability state.)
    optional_sections = (
        ("FacilityAccreditation", "medical_facility_accreditation"),
        ("CredentialVerification", "medical_credential_evidence"),
        ("ClinicalPrivilege", "medical_clinical_privileges"),
    )
    for model_name, section_name in optional_sections:
        if _optional_workforce_model(model_name) is None:
            continue
        section = context.get(section_name) or {}
        if not section.get("available", False):
            return False
        if "migration is not ready" in str(section.get("note") or "").lower():
            return False
    return True


def _filtered_medical_doctors(
    filters: dict[str, str],
    doctor_content_type: ContentType,
):
    doctors = MedicalDoctor.objects.all()
    employment = EmploymentRecord.objects.filter(
        content_type=doctor_content_type,
        is_current=True,
    )

    specialty = filters["specialty"]
    if specialty:
        doctors = doctors.filter(specialty__iexact=specialty)
    gender = filters["gender"]
    if gender:
        doctors = doctors.filter(gender__iexact=gender)

    province = filters["province"]
    district = filters["district"]
    facility = filters["facility"]
    sector = filters["sector"]
    workplace_filters = bool(province or district or facility or sector)

    if province:
        employment = employment.filter(province__iexact=province)
    if district:
        employment = employment.filter(district__iexact=district)
    if facility:
        facility_filter = (
            Q(facility__name__iexact=facility)
            | Q(facility_name_raw__iexact=facility)
            | Q(place_of_work__iexact=facility)
            | Q(employer_name__iexact=facility)
        )
        if facility.isdigit():
            facility_filter |= Q(facility_id=int(facility))
        employment = employment.filter(facility_filter)
    if sector:
        employment = employment.filter(
            Q(employment_sector__iexact=sector) | Q(area_of_employment__iexact=sector)
        )

    if workplace_filters:
        matching_doctor_ids = employment.values("object_id")
        if province and not any((district, facility, sector)):
            doctors = doctors.filter(
                Q(province__iexact=province) | Q(pk__in=matching_doctor_ids)
            )
        else:
            doctors = doctors.filter(pk__in=matching_doctor_ids)

    doctors = doctors.distinct()
    return doctors, employment.filter(object_id__in=doctors.values("pk"))


def _specialist_queryset(doctors):
    return doctors.exclude(specialty__isnull=True).exclude(specialty__exact="")


def _grouped_doctor_distribution(queryset, field_name: str, limit: int) -> list[dict[str, Any]]:
    rows = queryset.values(field_name).annotate(
        practitioner_count=Count("pk"),
    ).order_by("-practitioner_count", field_name)
    return _merge_distribution_rows(rows, field_name, limit)


def _employment_distributions(employment, limit: int) -> dict[str, list[dict[str, Any]]]:
    expressions = {
        "districts": _first_nonblank("district"),
        "facilities": _first_nonblank("facility__name", "facility_name_raw", "place_of_work", "employer_name"),
        "sectors": _first_nonblank("employment_sector", "area_of_employment"),
    }
    results: dict[str, list[dict[str, Any]]] = {}
    for key, expression in expressions.items():
        rows = (
            employment.annotate(_medical_intelligence_label=expression)
            .values("_medical_intelligence_label")
            .annotate(practitioner_count=Count("object_id", distinct=True))
            .order_by("-practitioner_count", "_medical_intelligence_label")
        )
        results[key] = _merge_distribution_rows(rows, "_medical_intelligence_label", limit)
    return results


def _first_nonblank(*field_names: str):
    values = [NullIf(F(field_name), Value("")) for field_name in field_names]
    return Coalesce(*values, Value("Not recorded"), output_field=CharField())


def _merge_distribution_rows(rows, label_key: str, limit: int) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        label = str(row.get(label_key) or "").strip()
        if not label:
            continue
        key = label.casefold()
        item = grouped.setdefault(
            key,
            {"label": label, "practitioner_count": 0},
        )
        item["practitioner_count"] += int(row.get("practitioner_count") or 0)
    return sorted(
        grouped.values(),
        key=lambda item: (-item["practitioner_count"], item["label"].casefold()),
    )[:limit]


def _facility_accreditation_snapshot(
    facility_content_type: ContentType,
    report_date: date,
    limit: int,
) -> dict[str, Any]:
    """Use the dedicated model when available, otherwise safe form evidence."""

    model = _optional_workforce_model("FacilityAccreditation")
    if model is not None:
        try:
            # An optional model can be present in code before its migration is
            # deployed.  A savepoint prevents its failed query from poisoning
            # the surrounding request/test transaction.
            with transaction.atomic():
                queryset = model.objects.all()
                status_rows = _model_status_distribution(queryset, limit)
                active = queryset.filter(status__in=("accredited", "conditional"))
                if _has_field(model, "valid_until"):
                    active = active.filter(Q(valid_until__isnull=True) | Q(valid_until__gte=report_date))
                linked_facility_count = active.values("facility_id").distinct().count()
                average_score = (
                    queryset.exclude(compliance_score__isnull=True).aggregate(value=Avg("compliance_score"))["value"]
                )
                return {
                    "available": True,
                    "source": "FacilityAccreditation",
                    "registered_facility_count": linked_facility_count,
                    "approved_application_count": queryset.filter(status="accredited").count(),
                    "pending_application_count": queryset.filter(status__in=("draft", "under_review")).count(),
                    "rejected_application_count": queryset.filter(status="not_accredited").count(),
                    "average_compliance_score": float(average_score) if average_score is not None else None,
                    "status_distribution": status_rows,
                    "metric_definition": (
                        "Current accredited or conditional FacilityAccreditation records linked to a Facility master record."
                    ),
                }
        except DatabaseError:
            # The model may be registered before its migration reaches a node.
            pass

    applications = Application.objects.filter(form_code__in=FACILITY_ACCREDITATION_FORM_CODES)
    linked = applications.filter(content_type=facility_content_type).exclude(object_id__isnull=True)
    approved_linked = linked.filter(status="approved").values("object_id").distinct().count()
    return {
        "available": True,
        "source": "Medical Board facility-accreditation applications",
        "registered_facility_count": approved_linked,
        "approved_application_count": applications.filter(status="approved").count(),
        "pending_application_count": applications.filter(status="pending").count(),
        "rejected_application_count": applications.filter(status="rejected").count(),
        "average_compliance_score": None,
        "status_distribution": _model_status_distribution(applications, limit),
        "metric_definition": (
            "Approved Medical Board accreditation applications already linked to a Facility master record. "
            "Unlinked applications remain in the review queue and are not represented as registered facilities."
        ),
    }


def _credential_evidence_snapshot(
    doctor_content_type: ContentType,
    report_date: date,
) -> dict[str, Any]:
    qualifications = Qualification.objects.filter(content_type=doctor_content_type)
    documents = ProfessionalDocument.objects.filter(content_type=doctor_content_type)
    evidence = {
        "available": True,
        "qualification_records": qualifications.count(),
        "qualifications_with_certificate": qualifications.filter(certificate_attached=True).count(),
        "uploaded_document_records": documents.filter(is_attached=True).count(),
        "signed_document_records": documents.exclude(verification_signature="").count(),
        "verified_credential_records": 0,
        "pending_credential_records": 0,
        "specialist_applications_pending": Application.objects.filter(
            form_code=SPECIALIST_APPLICATION_FORM_CODE,
            status="pending",
        ).count(),
        "specialist_applications_approved": Application.objects.filter(
            form_code=SPECIALIST_APPLICATION_FORM_CODE,
            status="approved",
        ).count(),
        "note": "Existing qualification and document evidence; a signature alone is not treated as credential verification.",
    }

    model = _optional_workforce_model("CredentialVerification")
    if model is None:
        return evidence
    try:
        with transaction.atomic():
            queryset = _optional_generic_professional_queryset(model, doctor_content_type)
            if queryset is None:
                evidence["note"] = (
                    "CredentialVerification exists but cannot be safely scoped to MedicalDoctor records by this schema."
                )
                return evidence
            if _has_field(model, "expiry_date"):
                queryset = queryset.filter(Q(expiry_date__isnull=True) | Q(expiry_date__gte=report_date))
            evidence["verified_credential_records"] = queryset.filter(status="verified").count()
            evidence["pending_credential_records"] = queryset.filter(
            status__in=("pending", "institution_check")
            ).count()
            evidence["note"] = "CredentialVerification records are scoped to MedicalDoctor profiles."
    except DatabaseError:
        evidence["note"] = "Credential verification migration is not ready; existing evidence is shown without verification status."
    return evidence


def _clinical_privilege_snapshot(
    doctor_content_type: ContentType,
    report_date: date,
    limit: int,
) -> dict[str, Any]:
    model = _optional_workforce_model("ClinicalPrivilege")
    if model is None:
        return {
            "supported": False,
            "available": False,
            "active_privilege_count": 0,
            "status_distribution": [],
            "facility_distribution": [],
            "note": (
                "Clinical privileges are not inferred from a specialty. A dedicated, approved privilege record is required."
            ),
        }
    try:
        with transaction.atomic():
            queryset = _optional_generic_professional_queryset(model, doctor_content_type)
            if queryset is None:
                return {
                    "supported": False,
                    "available": True,
                    "active_privilege_count": 0,
                    "status_distribution": [],
                    "facility_distribution": [],
                    "note": "ClinicalPrivilege exists but cannot be safely scoped to MedicalDoctor records by this schema.",
                }
            active = queryset.filter(status__in=("approved", "conditional"))
            if _has_field(model, "expiry_date"):
                active = active.filter(Q(expiry_date__isnull=True) | Q(expiry_date__gte=report_date))
            facility_rows: list[dict[str, Any]] = []
            if _has_field(model, "facility"):
                facility_rows = _merge_distribution_rows(
                    active.annotate(
                        _medical_intelligence_label=_first_nonblank("facility__name")
                    )
                    .values("_medical_intelligence_label")
                    .annotate(practitioner_count=Count("object_id", distinct=True))
                    .order_by("-practitioner_count", "_medical_intelligence_label"),
                    "_medical_intelligence_label",
                    limit,
                )
            return {
                "supported": True,
                "available": True,
                "active_privilege_count": active.count(),
                "status_distribution": _model_status_distribution(queryset, limit),
                "facility_distribution": facility_rows,
                "note": "Only dedicated ClinicalPrivilege records are reported; specialty remains separate from authority to perform a procedure.",
            }
    except DatabaseError:
        return {
            "supported": False,
            "available": False,
            "active_privilege_count": 0,
            "status_distribution": [],
            "facility_distribution": [],
            "note": "Clinical privilege migration is not ready.",
        }


def _filter_options(doctor_content_type: ContentType) -> dict[str, list[str]]:
    doctors = MedicalDoctor.objects.all()
    employment = EmploymentRecord.objects.filter(content_type=doctor_content_type, is_current=True)
    return {
        "specialty": _distinct_nonblank_values(doctors, "specialty"),
        # Province filters legitimately cover either a recorded professional
        # province or a current Medical Board workplace province.  Include
        # both governed option sets so a staff question such as "in Western"
        # is not silently treated as an unknown location merely because the
        # doctor profile itself has no province field populated.
        "province": _combined_distinct_nonblank_values(
            (doctors, "province"),
            (employment, "province"),
        ),
        "district": _distinct_nonblank_values(employment, "district"),
        "facility": _distinct_nonblank_values(employment, "facility__name"),
        "sector": _distinct_nonblank_values(employment, "employment_sector"),
        "gender": _distinct_nonblank_values(doctors, "gender"),
    }


def _distinct_nonblank_values(queryset, field_name: str) -> list[str]:
    values = []
    for value in queryset.values_list(field_name, flat=True).distinct()[:MAX_GROUP_ROWS]:
        label = str(value or "").strip()
        if label:
            values.append(label)
    return sorted(set(values), key=str.casefold)


def _combined_distinct_nonblank_values(*querysets_and_fields) -> list[str]:
    values: set[str] = set()
    for queryset, field_name in querysets_and_fields:
        for value in queryset.values_list(field_name, flat=True).distinct()[:MAX_GROUP_ROWS]:
            label = str(value or "").strip()
            if label:
                values.add(label)
    return sorted(values, key=str.casefold)


def _optional_workforce_model(model_name: str):
    try:
        return apps.get_model("workforce", model_name)
    except LookupError:
        return None


def _has_field(model, field_name: str) -> bool:
    return any(field.name == field_name for field in model._meta.fields)


def _optional_generic_professional_queryset(model, doctor_content_type: ContentType):
    """Return only a MedicalDoctor-scoped generic queryset, never unscoped rows."""

    if not (_has_field(model, "content_type") and _has_field(model, "object_id")):
        return None
    # Generic relations do not get database-level cascades.  Restricting the
    # aggregate to extant MedicalDoctor records prevents an orphaned historic
    # evidence/privilege row from inflating clinical regulation metrics.
    return model.objects.filter(
        content_type=doctor_content_type,
        object_id__in=MedicalDoctor.objects.values("pk"),
    )


def _model_status_distribution(queryset, limit: int) -> list[dict[str, Any]]:
    model = queryset.model
    if not _has_field(model, "status"):
        return []
    rows = queryset.values("status").annotate(
        practitioner_count=Count("pk"),
    ).order_by("-practitioner_count", "status")
    return _merge_distribution_rows(rows, "status", limit)
