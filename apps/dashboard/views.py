from collections import defaultdict
from datetime import date
from datetime import timedelta
import json
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd
import sys
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Case, Count, DateField, F, IntegerField, OuterRef, Q, Subquery, Sum, Value, When
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import NoReverseMatch, reverse
from django.utils.html import conditional_escape, format_html
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.safestring import mark_safe
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from django.http import JsonResponse
from django.contrib.auth.decorators import user_passes_test
from django.views.decorators.http import require_POST
import subprocess
from django.conf import settings
from django.utils import timezone

from apps.common.models import DuplicateReviewQueue
from apps.dashboard.forms import ReceiptSubmissionForm
from apps.accounts.models import User
from apps.dashboard.access import (
    MEDICAL_BOARD_FORM_CODES,
    MEDICAL_BOARD_PROFESSIONAL_MODELS,
    NURSING_COUNCIL_PROFESSIONAL_MODELS,
    can_manage_regulatory_operations,
    can_access_staff_domain,
    is_data_quality_reviewer,
    is_finance_reviewer,
    is_medical_board_staff,
    is_medical_board_user,
    is_nursing_council_staff,
    is_nursing_council_user,
    is_staff_dashboard_user,
)
from apps.dashboard.models import Receipt, RegistrationGuideline
from apps.dashboard.reports import (
    build_monthly_analytics_excel,
    build_monthly_analytics_pdf,
    build_yearly_analytics_excel,
    build_yearly_analytics_pdf,
    build_financial_forecast_payload,
    build_financial_forecast_excel,
    build_financial_forecast_pdf,
    build_financial_forecast_docx,
)
from apps.dashboard.reference_breakdown import build_reference_breakdown
from apps.dashboard.platform_standards import build_platform_standards_context
from apps.dashboard.production_readiness import (
    build_production_readiness_context,
    build_production_readiness_review_queryset,
)
from apps.dashboard.staff_ai import build_staff_ai_chat_response, build_staff_ai_context
from apps.notifications.helpdesk import HELPDESK_KNOWLEDGE, get_helpdesk_response
from apps.workforce.services.data_quality import dashboard_review_context, quality_approved_import_records
from apps.workforce.services.medical_board_workbook_import import DEFAULT_MEDICAL_BOARD_WORKBOOK
from apps.workforce.services.nursing_council_workflows import build_nursing_workflow_rows
from apps.workforce.forms import MEDICAL_BOARD_SPECIALIST_CHOICES
from apps.workforce.models import (
    Application,
    Cadre,
    CommunityHealthWorker,
    DataImportBatch,
    DocumentType,
    EmploymentRecord,
    Facility,
    HealthStudent,
    ImportedWorkbookSheet,
    Location,
    MedicalDoctor,
    Midwife,
    MissingDataReview,
    NurseAide,
    NursingProfessional,
    PracticingLicenseRecord,
    AuditLog,
    ProfessionalDocument,
    ProfessionalPhoto,
    PostingHistory,
    Qualification,
    TrainingInstitution,
    WorkforceSnapshot,
)


ATP_WORKBOOK_PATH = Path(
    r"C:\Users\timhi\OneDrive\Desktop\ParotOs\NDOH_Database\ATP_LATEST\2026 Current ATP-DATA Statistics & Tracking latest.xlsx"
)
ATP_NURSING_TARGET_MODELS = ["nursingprofessional", "midwife", "nurseaide"]
NURSING_IMPORT_SOURCE_KINDS = ['nursing_license_workbook', 'ndata_workbook']
NURSING_IMPORT_TARGET_MODELS = ['nursingprofessional', 'midwife', 'nurseaide', 'healthstudent']
MEDICAL_IMPORT_SOURCE_KINDS = ['medical_board_workbook']
MEDICAL_IMPORT_TARGET_MODELS = ['medicaldoctor', 'communityhealthworker', 'other']
NURSING_FORM_CODES = ['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G7', 'NC1', 'NC2', 'NC3', 'NC4', 'NC5', 'NC6', 'NC7', 'NC8', 'NC9', 'NC10', 'NC11']
MEDICAL_RECEIPT_ROLES = {'doctor', 'chw'}
NURSING_RECEIPT_ROLES = {'nurse', 'nurse_aide', 'graduand', 'student'}
DASHBOARD_CACHE_TIMEOUT_SECONDS = 300
PROVISIONAL_LICENSE_TABLE_LIMIT = 300
PROFESSIONAL_PREVIEW_LIMIT = 25
INDIVIDUAL_RECORDS_PAGE_SIZE = 100
REGISTRAR_WORKER_ORIGIN_TABLE_LIMIT = 240
MEDICAL_SPECIALIST_VALUES = {value for value, _label in MEDICAL_BOARD_SPECIALIST_CHOICES}
MEDICAL_SPECIALIST_LABELS = dict(MEDICAL_BOARD_SPECIALIST_CHOICES)
GENERIC_MEDICAL_SPECIALTY_LABELS = {
    "",
    "general practice",
    "medical board practitioner",
    "medical doctor",
    "overseas medical board practitioner",
}
MEDICAL_SPECIALIST_KEYWORDS = (
    "specialist",
    "specialty",
    "paediatric",
    "peadiatric",
    "anaest",
    "radiolog",
    "cardio",
    "obstetric",
    "gynaec",
    "gynec",
    "surgeon",
    "surgery",
    "patholog",
    "microbiolog",
    "oncolog",
    "dermatolog",
    "psychiat",
)
ATP_CHURCH_KEYWORDS = (
    "catholic",
    "church",
    "mission",
    "adventist",
    "anglican",
    "lutheran",
    "nazareth",
    "wesleyan",
    "salvation army",
    "olsh",
    "st.",
    "saint ",
)
ATP_PRIVATE_KEYWORDS = (
    "medical centre",
    "medical center",
    "clinic",
    "private",
    "specialist centre",
    "specialist center",
    "surgery",
    "2k medical",
    "international hospital",
)
ATP_PUBLIC_KEYWORDS = (
    "provincial health authority",
    "national department of health",
    "general hospital",
    "district hospital",
    "rural hospital",
    "health centre",
    "health center",
    "health sub centre",
    "hospital",
    "health authority",
    "public health",
)
ATP_NGO_KEYWORDS = (
    "ngo",
    "non government",
    "non-government",
    "faith based",
    "faith-based",
    "mission",
    "church",
    "catholic",
    "adventist",
    "anglican",
    "lutheran",
    "nazareth",
    "wesleyan",
    "salvation army",
)
FREQUENT_NURSING_CATEGORY_ORDER = (
    "General Nurse",
    "Specialist Midwife",
    "Specialist Acute Care Nurse",
    "Nurse Aide",
    "Specialist Paediatric Nurse",
    "Specialist Mental Health Nurse",
    "Specialist Pediatric Nurse",
    "Specialist Maternal and Child Health Nurse",
    "Specialist Eye Care Nurse",
    "Specialist Midwife & Paediatric Nurse",
    "Dip in General Nursing",
    "Enrolled Nurse",
)
FREQUENT_NURSING_CATEGORY_LOOKUP = {
    label.lower(): label for label in FREQUENT_NURSING_CATEGORY_ORDER
}
INDIVIDUAL_RECORD_LIVE_MODELS = (
    (NursingProfessional, "nursingprofessional", "Nursing Professional", "nursing"),
    (Midwife, "midwife", "Midwife", "nursing"),
    (NurseAide, "nurseaide", "Nurse Aide", "nursing"),
    (HealthStudent, "graduand", "Graduand", "nursing"),
    (MedicalDoctor, "medicaldoctor", "Medical Doctor", "medical"),
    (CommunityHealthWorker, "communityhealthworker", "Community Health Worker", "medical"),
)
INCOMING_IMPORT_RECORD_TYPES = {"provisional", "full", "temporary", "workforce_listing"}


def _role_in(*roles):
    return lambda user: user.is_authenticated and user.role in roles


def _staff_portal_target(user):
    if is_medical_board_staff(user):
        return 'medical_board_portal'
    if is_nursing_council_staff(user):
        return 'nursing_council_portal'
    return None


def _analytics_scope_for_user(user, requested_office=None):
    if requested_office == "all":
        requested_office = None
    if requested_office not in {None, "nursing", "medical"}:
        raise Http404("Report not available")

    if getattr(user, 'role', '') == 'admin':
        return requested_office
    if is_finance_reviewer(user):
        raise Http404("Report not available")
    if is_medical_board_staff(user):
        if requested_office and requested_office != "medical":
            raise Http404("Report not available")
        return 'medical'
    if is_nursing_council_staff(user):
        if requested_office and requested_office != "nursing":
            raise Http404("Report not available")
        return 'nursing'
    raise Http404("Report not available")


def _analytics_export_scope(request):
    return (
        request.GET.get("office")
        or request.GET.get("scope")
        or request.POST.get("office")
        or request.POST.get("scope")
    )


def _workforce_scope_for_user(user):
    if getattr(user, 'role', '') == 'admin':
        return None
    if is_medical_board_staff(user):
        return 'medical'
    if is_nursing_council_staff(user):
        return 'nursing'
    return None


def _import_source_kinds_for_scope(scope):
    if scope == 'medical':
        return MEDICAL_IMPORT_SOURCE_KINDS
    return NURSING_IMPORT_SOURCE_KINDS


def _import_target_models_for_scope(scope):
    if scope == 'medical':
        return MEDICAL_IMPORT_TARGET_MODELS
    return NURSING_IMPORT_TARGET_MODELS


def _quality_approved_practicing_records():
    return quality_approved_import_records(PracticingLicenseRecord.objects.all())


def _review_severity_bucket():
    return {"high": 0, "medium": 0, "low": 0}


def _review_recent_date_from_record(record):
    if not record:
        return None
    if isinstance(record, dict):
        return record.get("payment_date") or record.get("issued_date")
    return record.payment_date or record.issued_date


def _quality_review_recent_date(review, record=None):
    source_date = _review_recent_date_from_record(record)
    if source_date:
        return source_date
    updated_at = getattr(review, "updated_at", None)
    if updated_at:
        return timezone.localtime(updated_at).date()
    return None


def _attach_quality_review_metadata(review, record=None):
    review.quality_year = getattr(record, "record_year", None) or "No source year"
    review.quality_recent_date = _quality_review_recent_date(review, record)
    return review


def _data_quality_statistics(queryset, scope_key):
    practicing_content_type = ContentType.objects.get_for_model(PracticingLicenseRecord)
    total_count = queryset.count()
    latest_updated = queryset.order_by("-updated_at").values_list("updated_at", flat=True).first()
    cache_key = (
        "data_quality_statistics_v1:"
        f"{scope_key}:{total_count}:"
        f"{latest_updated.isoformat() if latest_updated else 'none'}"
    )
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    import_reviews = list(
        queryset.filter(content_type=practicing_content_type).values(
            "object_id",
            "severity",
            "updated_at",
        )
    )
    import_record_ids = [row["object_id"] for row in import_reviews]
    import_record_map = {
        row["id"]: row
        for row in PracticingLicenseRecord.objects.filter(id__in=import_record_ids).values(
            "id",
            "record_year",
            "issued_date",
            "payment_date",
        )
    }

    year_groups = {}
    latest_source_date = None
    today = timezone.localdate()
    for review in import_reviews:
        record = import_record_map.get(review["object_id"])
        year_value = record["record_year"] if record and record["record_year"] else None
        key = year_value or "No source year"
        group = year_groups.setdefault(key, {
            "year": key,
            "sort_year": year_value or -1,
            "total": 0,
            **_review_severity_bucket(),
            "recent_date": None,
        })
        severity = review["severity"] if review["severity"] in group else "medium"
        group["total"] += 1
        group[severity] += 1
        source_date = _review_recent_date_from_record(record)
        if source_date and (group["recent_date"] is None or source_date > group["recent_date"]):
            group["recent_date"] = source_date
        if source_date and source_date <= today and (latest_source_date is None or source_date > latest_source_date):
            latest_source_date = source_date

    live_review_count = queryset.exclude(content_type=practicing_content_type).count()
    if live_review_count:
        live_group = year_groups.setdefault("Live register / no source year", {
            "year": "Live register / no source year",
            "sort_year": -2,
            "total": 0,
            **_review_severity_bucket(),
            "recent_date": None,
        })
        for row in queryset.exclude(content_type=practicing_content_type).values("severity", "updated_at"):
            severity = row["severity"] if row["severity"] in live_group else "medium"
            live_group["total"] += 1
            live_group[severity] += 1
            recent_date = timezone.localtime(row["updated_at"]).date() if row["updated_at"] else None
            if recent_date and (live_group["recent_date"] is None or recent_date > live_group["recent_date"]):
                live_group["recent_date"] = recent_date

    year_rows = sorted(
        year_groups.values(),
        key=lambda row: (row["sort_year"], row["recent_date"] or date.min),
        reverse=True,
    )
    high_count = queryset.filter(severity="high").count()
    medium_count = queryset.filter(severity="medium").count()
    low_count = queryset.filter(severity="low").count()
    statistics = {
        "data_quality_total_count": total_count,
        "data_quality_high_count": high_count,
        "data_quality_medium_count": medium_count,
        "data_quality_low_count": low_count,
        "data_quality_import_review_count": len(import_reviews),
        "data_quality_live_review_count": live_review_count,
        "data_quality_year_rows": year_rows,
        "data_quality_recent_review_date": timezone.localtime(latest_updated).date() if latest_updated else None,
        "data_quality_latest_source_date": latest_source_date,
    }
    cache.set(cache_key, statistics, DASHBOARD_CACHE_TIMEOUT_SECONDS)
    return statistics


def _data_quality_display_reviews(queryset, limit):
    practicing_content_type = ContentType.objects.get_for_model(PracticingLicenseRecord)
    import_review_ids = queryset.filter(content_type=practicing_content_type).values("object_id")
    record_queryset = PracticingLicenseRecord.objects.filter(id__in=Subquery(import_review_ids))
    records = list(
        record_queryset.filter(record_year__isnull=False)
        .order_by("-record_year", "-payment_date", "-issued_date", "-updated_at")
        [: max(limit * 2, limit)]
    )
    if len(records) < limit:
        records.extend(
            record_queryset.filter(record_year__isnull=True)
            .order_by("-payment_date", "-issued_date", "-updated_at")
            [: limit - len(records)]
        )

    object_ids = [record.id for record in records]
    reviews_by_object_id = {
        review.object_id: review
        for review in queryset.filter(
            content_type=practicing_content_type,
            object_id__in=object_ids,
        )
    }
    review_rows = []
    for record in records:
        review = reviews_by_object_id.get(record.id)
        if not review:
            continue
        review_rows.append(_attach_quality_review_metadata(review, record))
        if len(review_rows) >= limit:
            break

    if len(review_rows) < limit:
        live_reviews = queryset.exclude(content_type=practicing_content_type).order_by("-updated_at")[: limit - len(review_rows)]
        for review in live_reviews:
            review_rows.append(_attach_quality_review_metadata(review))

    return review_rows


def _data_quality_review_context(queryset, *, limit=20, scope_key="all"):
    statistics = _data_quality_statistics(queryset, scope_key)
    review_scope = ""
    if "nursing" in scope_key:
        review_scope = "nursing"
    elif "medical" in scope_key:
        review_scope = "medical"
    return {
        "missing_data_review_count": statistics["data_quality_total_count"],
        "high_priority_missing_data_count": statistics["data_quality_high_count"],
        "missing_data_reviews": _data_quality_display_reviews(queryset, limit),
        "data_quality_review_scope": review_scope,
        **statistics,
    }


def _data_quality_review_queryset_for_user(user, requested_scope=None):
    queryset = MissingDataReview.objects.exclude(status="resolved")
    if getattr(user, "role", "") == "admin":
        scope = requested_scope if requested_scope in {"medical", "nursing"} else None
    elif is_medical_board_staff(user):
        scope = "medical"
    elif is_nursing_council_staff(user):
        scope = "nursing"
    elif is_data_quality_reviewer(user):
        scope = None
    else:
        return queryset.none()

    if scope is None:
        return queryset

    practicing_content_type = ContentType.objects.get_for_model(PracticingLicenseRecord)
    allowed_models = _duplicate_review_models_for_scope(scope)
    allowed_import_ids = PracticingLicenseRecord.objects.filter(
        target_model__in=_import_target_models_for_scope(scope),
    ).values("id")
    return queryset.filter(
        Q(content_type__model__in=allowed_models)
        | Q(content_type=practicing_content_type, object_id__in=Subquery(allowed_import_ids))
    )


def _annotated_data_quality_review_queryset(queryset):
    practicing_content_type = ContentType.objects.get_for_model(PracticingLicenseRecord)
    practicing_record = PracticingLicenseRecord.objects.filter(id=OuterRef("object_id"))
    return queryset.select_related("content_type").annotate(
        quality_record_year=Case(
            When(
                content_type=practicing_content_type,
                then=Subquery(practicing_record.values("record_year")[:1]),
            ),
            default=Value(None),
            output_field=IntegerField(),
        ),
        quality_payment_date=Case(
            When(
                content_type=practicing_content_type,
                then=Subquery(practicing_record.values("payment_date")[:1]),
            ),
            default=Value(None),
            output_field=DateField(),
        ),
        quality_issued_date=Case(
            When(
                content_type=practicing_content_type,
                then=Subquery(practicing_record.values("issued_date")[:1]),
            ),
            default=Value(None),
            output_field=DateField(),
        ),
    )


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _quality_review_record_urls(review):
    slug = review.content_type.model
    urls = {}
    for key, route in {"detail": "record_detail", "edit": "record_update"}.items():
        try:
            urls[key] = reverse(route, args=[slug, review.object_id])
        except NoReverseMatch:
            urls[key] = ""
    return urls


def _quality_review_actions_html(review):
    urls = _quality_review_record_urls(review)
    actions = []
    if urls.get("detail"):
        actions.append(format_html('<a href="{}" class="btn btn-sm btn-info">View</a>', urls["detail"]))
    if urls.get("edit"):
        actions.append(format_html('<a href="{}" class="btn btn-sm btn-primary">Edit</a>', urls["edit"]))
    return format_html('<span class="text-nowrap">{}</span>', mark_safe(" ".join(str(action) for action in actions))) if actions else "-"


def _quality_review_badge_html(review):
    badge_class = "badge-danger" if review.severity == "high" else "badge-warning" if review.severity == "medium" else "badge-info"
    return format_html('<span class="badge {}">{}</span>', badge_class, review.severity.title())


def _quality_review_row_data(review, record=None):
    source_year = getattr(record, "record_year", None) if record else None
    recent_date = _quality_review_recent_date(review, record)
    source_label = review.source_label or "Live register"
    if review.source_label and review.source_row:
        source_label = f"{review.source_label}, row {review.source_row}"
    issues = ", ".join(str(value) for value in (review.missing_fields or [])) or "-"
    return {
        "source_year": source_year or "No source year",
        "recent_date": recent_date.strftime("%d %b %Y") if recent_date else "-",
        "name": conditional_escape(review.full_name or "-"),
        "type": conditional_escape(review.professional_type or "-"),
        "registration": conditional_escape(review.registration_no or "-"),
        "issues": conditional_escape(issues),
        "source": conditional_escape(source_label),
        "severity": _quality_review_badge_html(review),
        "status": conditional_escape(review.get_status_display()),
        "actions": _quality_review_actions_html(review),
    }


def _data_quality_review_default_ordering():
    return [
        F("quality_record_year").desc(nulls_last=True),
        F("quality_payment_date").desc(nulls_last=True),
        F("quality_issued_date").desc(nulls_last=True),
        "-updated_at",
        "-id",
    ]


def _cadre_queryset_for_scope(scope):
    queryset = Cadre.objects.order_by('name')
    if scope == 'medical':
        return queryset.filter(category__in=['medical', 'chw'])
    if scope == 'nursing':
        return queryset.filter(category__in=['nursing', 'midwifery'])
    return queryset


def _training_institution_queryset_for_scope(scope):
    queryset = TrainingInstitution.objects.order_by('name')
    if scope == 'medical':
        return queryset.filter(
            Q(type__icontains='chw')
            | Q(type__icontains='medical')
            | Q(name__icontains='chw')
            | Q(name__icontains='medical')
            | Q(name__icontains='community health')
        )
    return queryset


def _medical_receipt_filter():
    unlinked = Q(application__isnull=True)
    return (
        Q(application__form_code__in=MEDICAL_BOARD_FORM_CODES)
        | (unlinked & Q(user__role__in=MEDICAL_RECEIPT_ROLES))
        | (unlinked & Q(user__department__icontains='medical'))
        | (unlinked & Q(user__username__icontains='medical'))
        | (unlinked & Q(user__username__icontains='doctor'))
        | (unlinked & Q(user__username__icontains='chw'))
    )


def _nursing_receipt_filter():
    unlinked = Q(application__isnull=True)
    linked_nursing = Q(application__isnull=False) & ~Q(application__form_code__in=MEDICAL_BOARD_FORM_CODES)
    return (
        linked_nursing
        | (unlinked & Q(user__isnull=True))
        | (unlinked & Q(user__role__in=NURSING_RECEIPT_ROLES))
        | (unlinked & Q(user__department__icontains='nursing'))
        | (unlinked & Q(user__department__icontains='nurse'))
        | (unlinked & Q(user__username__icontains='nursing'))
        | (unlinked & Q(user__username__icontains='nurse'))
    )


def _receipt_queryset_for_scope(scope):
    queryset = Receipt.objects.select_related('user', 'application')
    if scope == 'medical':
        return queryset.filter(_medical_receipt_filter())
    if scope == 'nursing':
        return queryset.filter(_nursing_receipt_filter())
    return queryset


def _financial_scope_for_user(user, requested_office=None):
    if requested_office == "all":
        requested_office = None
    if requested_office not in {None, "nursing", "medical"}:
        raise Http404("Financial forecast not available")

    if getattr(user, 'role', '') == 'admin':
        return requested_office
    if is_finance_reviewer(user):
        return requested_office or "nursing"
    if is_medical_board_staff(user):
        if requested_office and requested_office != "medical":
            raise Http404("Financial forecast not available")
        return "medical"
    if is_nursing_council_staff(user):
        if requested_office and requested_office != "nursing":
            raise Http404("Financial forecast not available")
        return "nursing"
    raise Http404("Financial forecast not available")


def _financial_office_options_for_user(user, selected_scope):
    selected_key = selected_scope or "all"
    if getattr(user, 'role', '') == 'admin':
        allowed = [
            ("all", "All Regulatory Offices"),
            ("nursing", "Nursing Council Financial Forecast"),
            ("medical", "Medical Board Financial Forecast"),
        ]
    elif is_finance_reviewer(user):
        allowed = [
            ("nursing", "Nursing Council Financial Forecast"),
            ("medical", "Medical Board Financial Forecast"),
        ]
    elif selected_scope == "medical":
        allowed = [("medical", "Medical Board Financial Forecast")]
    else:
        allowed = [("nursing", "Nursing Council Financial Forecast")]
    return [
        {
            "office": office,
            "label": label,
            "active": office == selected_key,
        }
        for office, label in allowed
    ]


def _export_user_label(user):
    display_name = user.get_full_name() if hasattr(user, "get_full_name") else ""
    return display_name or getattr(user, "username", "") or "Unknown user"


def _request_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return forwarded_for.split(",")[0].strip() if forwarded_for else request.META.get("REMOTE_ADDR")


def _log_financial_export(request, export_format, scope):
    AuditLog.objects.create(
        actor=request.user,
        action="FINANCIAL_FORECAST_EXPORTED",
        entity_type="FinancialForecastReport",
        entity_id=export_format,
        new_values_json={
            "format": export_format,
            "scope": scope or "all_regulatory_offices",
            "exported_by": _export_user_label(request.user),
            "exported_at": timezone.localtime().isoformat(),
        },
        ip_address=_request_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
    )


def _staff_role_target(user):
    role = getattr(user, 'role', '')
    profile = " ".join(
        str(value or "")
        for value in [
            getattr(user, 'department', ''),
            getattr(user, 'username', ''),
            getattr(user, 'first_name', ''),
            getattr(user, 'last_name', ''),
        ]
    ).lower()
    if role == 'admin':
        return 'admin_dashboard'
    if role == 'registrar':
        return _staff_portal_target(user) or 'registrar_dashboard'
    if role == 'reviewer':
        if is_finance_reviewer(user):
            return 'financial_forecast_dashboard'
        if is_data_quality_reviewer(user):
            return 'duplicate_review_workflow'
        return _staff_portal_target(user) or 'viewer_dashboard'
    return None


def _apply_medical_overview_scope(context):
    medical_form_codes = ['MD1', 'MD2', 'CHW1', 'MBSP', 'MBRN', 'MBAC', 'MBPF', 'MBTC']
    context['dashboard_scope'] = 'medical'
    context['nursing_count'] = 0
    context['midwife_count'] = 0
    context['nurse_aide_count'] = 0
    context['graduand_count'] = 0
    context['student_count'] = 0
    context['allied_count'] = _medical_allied_count()
    context['registration_count'] = context.get('medical_count', 0) + context.get('chw_count', 0) + context.get('allied_count', 0)
    context['application_count'] = Application.objects.filter(status='pending', form_code__in=medical_form_codes).count()
    context['approved_applications'] = Application.objects.filter(status='approved', form_code__in=medical_form_codes).count()
    context['rejected_applications'] = Application.objects.filter(status='rejected', form_code__in=medical_form_codes).count()
    context['national_workers_table'] = [
        row for row in context.get('national_workers_table', [])
        if row.get('type') in {'Medical', 'CHW', 'Allied Health'}
    ]
    context['overseas_workers_table'] = [
        row for row in context.get('overseas_workers_table', [])
        if row.get('type') in {'Medical', 'CHW', 'Allied Health'}
    ]
    return context


def _duplicate_review_models_for_scope(scope):
    if scope == "medical":
        return sorted(MEDICAL_BOARD_PROFESSIONAL_MODELS)
    if scope == "nursing":
        return sorted(NURSING_COUNCIL_PROFESSIONAL_MODELS)
    return sorted(MEDICAL_BOARD_PROFESSIONAL_MODELS | NURSING_COUNCIL_PROFESSIONAL_MODELS)


def _duplicate_review_queryset_for_user(user):
    scope = _analytics_scope_for_user(user)
    queryset = DuplicateReviewQueue.objects.select_related("content_type", "reviewed_by").order_by(
        "-similarity_score",
        "-id",
    )
    if scope is None:
        return queryset

    allowed_models = _duplicate_review_models_for_scope(scope)
    practicing_content_type = ContentType.objects.get_for_model(PracticingLicenseRecord)
    practicing_record_ids = PracticingLicenseRecord.objects.filter(
        target_model__in=allowed_models
    ).values("id")
    return queryset.filter(
        Q(content_type__model__in=allowed_models)
        | Q(suspected_duplicate__target_model__in=allowed_models)
        | Q(content_type=practicing_content_type, object_id__in=Subquery(practicing_record_ids))
    )


def _can_access_production_readiness(user):
    return (
        getattr(user, 'is_authenticated', False)
        and (can_manage_regulatory_operations(user) or is_data_quality_reviewer(user))
    )


def _duplicate_review_target_model(review):
    payload = review.suspected_duplicate or {}
    if payload.get("target_model"):
        return str(payload["target_model"]).lower()
    record = getattr(review, "record", None)
    if record is not None and getattr(record, "target_model", None):
        return str(record.target_model).lower()
    return review.content_type.model


def _duplicate_review_target_label(model_key):
    choices = dict(PracticingLicenseRecord.TARGET_MODEL_CHOICES)
    return choices.get(model_key, str(model_key).replace("_", " ").title())


def _duplicate_review_rows(review_items):
    review_items = list(review_items)
    member_ids = set()
    for review in review_items:
        payload = review.suspected_duplicate or {}
        raw_member_ids = payload.get("member_ids")
        if isinstance(raw_member_ids, list) and raw_member_ids:
            member_ids.update(int(value) for value in raw_member_ids if str(value).isdigit())
        elif review.content_type.model == "practicinglicenserecord":
            member_ids.add(review.object_id)

    record_map = PracticingLicenseRecord.objects.in_bulk(member_ids) if member_ids else {}
    rows = []

    for review in review_items:
        payload = review.suspected_duplicate or {}
        target_model = _duplicate_review_target_model(review)
        member_id_list = payload.get("member_ids") if isinstance(payload.get("member_ids"), list) else [review.object_id]
        members = []
        for member_id in member_id_list:
            record = record_map.get(member_id)
            if not record:
                continue
            members.append({
                "id": record.id,
                "full_name": record.full_name,
                "registration_no": record.registration_no,
                "practitioner_number": record.practitioner_number,
                "record_type": record.get_record_type_display(),
                "record_year": record.record_year,
                "province": _normalize_province_label(record.province),
                "reference_number": record.reference_number or "-",
                "sheet_name": record.source_sheet_name,
                "source_row": record.source_row,
                "batch_name": record.batch.source_file_name,
            })

        identifier_field = payload.get("identifier_field") or (
            "registration_no" if any(member.get("registration_no") for member in members) else "practitioner_number"
        )
        identifier_value = payload.get("identifier_value")
        if not identifier_value and members:
            identifier_value = members[0].get(identifier_field) or "-"

        rows.append({
            "review": review,
            "target_model": target_model,
            "target_label": _duplicate_review_target_label(target_model),
            "full_name": payload.get("full_name") or (members[0]["full_name"] if members else f"Review #{review.id}"),
            "identifier_field": "Registration Number" if identifier_field == "registration_no" else "Practitioner / Licence Number",
            "identifier_value": identifier_value or "-",
            "record_type": payload.get("record_type") or (members[0]["record_type"] if members else review.content_type.model),
            "record_year": payload.get("record_year") or (members[0]["record_year"] if members else "-"),
            "member_count": payload.get("member_count") or len(members) or 1,
            "audit_type": payload.get("audit_type") or "duplicate_review",
            "audit_label": str(payload.get("audit_type") or "duplicate_review").replace("_", " ").title(),
            "members": members,
        })

    rows.sort(key=lambda item: (-int(item["member_count"]), -item["review"].id))
    return rows


def _find_professional(model, user):
    identifiers = [
        value for value in [
            getattr(user, 'registration_number', None),
            getattr(user, 'license_number', None),
            user.username,
        ]
        if value
    ]
    if not identifiers:
        return None
    return model.objects.filter(Q(registration_no__in=identifiers) | Q(email=user.email)).first()


def _applications_for(obj):
    if not obj:
        return Application.objects.none()
    from django.contrib.contenttypes.models import ContentType

    ct = ContentType.objects.get_for_model(obj)
    return Application.objects.filter(content_type=ct, object_id=obj.id)


def _receipt_queryset_for_user(user):
    return Receipt.objects.filter(user=user).select_related('application').order_by('-transaction_date')


def _financial_chart_context(office_data):
    monthly_rows = office_data.get("monthly_rows", [])
    yearly_rows = office_data.get("yearly_rows", [])
    category_rows = office_data.get("category_rows", [])

    def _decimal_to_float(value):
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    recent_months = monthly_rows[-12:]
    office_data["monthly_chart_labels"] = json.dumps([row["period"] for row in recent_months])
    office_data["monthly_manual_values"] = json.dumps([_decimal_to_float(row["manual_amount"]) for row in recent_months])
    office_data["monthly_imported_values"] = json.dumps([_decimal_to_float(row["imported_amount"]) for row in recent_months])
    office_data["monthly_total_values"] = json.dumps([_decimal_to_float(row["total_amount"]) for row in recent_months])
    office_data["monthly_pending_values"] = json.dumps([0 for _ in recent_months])

    office_data["yearly_chart_labels"] = json.dumps([str(row["period"]) for row in yearly_rows])
    office_data["yearly_total_values"] = json.dumps([_decimal_to_float(row["total_amount"]) for row in yearly_rows])

    office_data["category_chart_labels"] = json.dumps([row["label"] for row in category_rows])
    office_data["category_chart_values"] = json.dumps([_decimal_to_float(row["amount"]) for row in category_rows])

    current_year_row = yearly_rows[-1] if yearly_rows else None
    office_data["audit_flow_labels"] = json.dumps([
        "Completed Manual Receipts",
        "Imported Spreadsheet Receipts",
        "Pending Manual Receipts",
        "Current Year Combined",
    ])
    office_data["audit_flow_values"] = json.dumps([
        _decimal_to_float(office_data.get("manual_completed_total")),
        _decimal_to_float(office_data.get("imported_total")),
        int(office_data.get("manual_pending_count", 0)),
        _decimal_to_float(current_year_row["total_amount"]) if current_year_row else _decimal_to_float(office_data.get("combined_current_year_total")),
    ])
    office_data["outflow_note"] = (
        "Actual expenditure or money-out is not yet captured as a dedicated finance ledger in this platform. "
        "These charts currently show receipt inflows, imported payment history, and pending receipt workflow status for audit transparency."
    )
    return office_data


def _clean_facility_name(value):
    text = ' '.join(str(value or '').replace('\n', ' ').split())
    upper = text.upper()
    if not text:
        return 'Facility not captured'
    aliases = [
        (('POM GENERAL', 'PORT MORESBY GENERAL'), 'Port Moresby General Hospital'),
        (('ANGAU',), 'ANGAU Memorial Hospital'),
        (('MT HAGEN', 'MOUNT HAGEN'), 'Mt Hagen Provincial Hospital'),
        (('KUNDIAWA',), 'Kundiawa General Hospital'),
        (('NONGA',), 'Nonga General Hospital'),
        (('ENGA PROVINCIAL',), 'Enga Provincial Health Authority'),
        (('GOROKA',), 'Goroka Provincial Hospital'),
        (('MENDI',), 'Mendi Provincial Hospital'),
        (('ALOTAU',), 'Alotau Provincial Hospital'),
        (('KIMBE',), 'Kimbe General Hospital'),
    ]
    for tokens, label in aliases:
        if any(token in upper for token in tokens):
            return label
    for marker in [',', ' PO BOX', ' P O BOX', ' PMB', ' PRIVATE MAIL BAG', ' BOX ']:
        index = upper.find(marker)
        if index > 6:
            text = text[:index].strip()
            break
    return text[:120].title()


def _normalize_province_label(value):
    text = ' '.join(str(value or '').replace('\n', ' ').replace('.', ' ').split())
    upper = text.upper()
    if not text:
        return 'Province not captured'

    aliases = [
        (('NCD', 'NATIONAL CAPITAL DISTRICT', 'BOROKO NCD', 'BOROKO, NCD'), 'National Capital District'),
        (('MP', 'MOROBE', 'LAE MOROBE', 'LAE, MOROBE'), 'Morobe Province'),
        (('MBP', 'MILNE BAY'), 'Milne Bay Province'),
        (('EHP', 'EASTERN HIGHLANDS', 'GOROKA'), 'Eastern Highlands Province'),
        (('EASTERN HIGHLAND',), 'Eastern Highlands Province'),
        (('WHP', 'WESTERN HIGHLANDS', 'MT HAGEN', 'MOUNT HAGEN'), 'Western Highlands Province'),
        (('SHP', 'SOUTHERN HIGHLANDS', 'SOURTHERN HIGHLANDS', 'MENDI'), 'Southern Highlands Province'),
        (('SOUTHERN H P', 'SOUTHERN H/P', 'SOUTHERN HP'), 'Southern Highlands Province'),
        (('AROB', 'BOUGAINVILLE'), 'Autonomous Region of Bougainville'),
        (('ENBP', 'EAST NEW BRITAIN', 'KOKOPO', 'RABAUL'), 'East New Britain Province'),
        (('WNBP', 'WEST NEW BRITAIN', 'KIMBE'), 'West New Britain Province'),
        (('ESP', 'EAST SEPIK', 'WEWAK'), 'East Sepik Province'),
        (('WSP', 'WEST SEPIK', 'SANDAUN', 'SAUNDAUN', 'VANIMO'), 'Sandaun Province'),
        (('NIP', 'NEW IRELAND', 'KAVIENG'), 'New Ireland Province'),
        (('EP', 'ENGA', 'WABAG'), 'Enga Province'),
        (('WP', 'WESTERN PROVINCE', 'WESTERN PROV', 'WESTERN'), 'Western Province'),
        (('OP', 'ORO', 'NORTHERN', 'POPONDETTA'), 'Northern (Oro) Province'),
        (('SIMBU', 'CHIMBU', 'KUNDIAWA'), 'Simbu Province'),
        (('MADANG',), 'Madang Province'),
        (('CENTRAL',), 'Central Province'),
        (('GULF',), 'Gulf Province'),
        (('HELA',), 'Hela Province'),
        (('TARI',), 'Hela Province'),
        (('JIWAKA',), 'Jiwaka Province'),
        (('MANUS',), 'Manus Province'),
        (('NATIONAL CAPITAL PROVINCE',), 'National Capital District'),
    ]
    for tokens, label in aliases:
        if any(token == upper or token in upper for token in tokens):
            return label
    if upper.endswith(' PROVINCE'):
        return text.title()
    return f"{text.title()} Province" if len(text) > 2 and 'PROVINCE' not in upper else text.title()


def _display_category(record):
    if record.get('category'):
        return record['category']
    labels = dict(PracticingLicenseRecord.TARGET_MODEL_CHOICES)
    return labels.get(record.get('target_model'), record.get('target_model') or 'Uncategorised')


def _normalize_gender_label(value):
    text = str(value or '').strip().lower()
    if not text:
        return 'Not stated'
    if text in {'f', 'female', 'femele', 'femal', 'famale', 'femile'}:
        return 'Female'
    if text in {'m', 'male', 'mael'}:
        return 'Male'
    return 'Needs review'


def _individual_record_scope_for_user(user, requested_scope=None):
    if getattr(user, "role", "") == "admin":
        return requested_scope if requested_scope in {"nursing", "medical"} else None
    return _workforce_scope_for_user(user) or "nursing"


def _individual_scope_label(scope):
    if scope == "medical":
        return "Medical Board"
    if scope == "nursing":
        return "Nursing Council"
    return "All Regulatory Offices"


def _individual_import_target_models(scope):
    if scope in {"medical", "nursing"}:
        return _import_target_models_for_scope(scope)
    return sorted(set(MEDICAL_IMPORT_TARGET_MODELS) | set(NURSING_IMPORT_TARGET_MODELS))


def _individual_live_models(scope):
    return [
        item for item in INDIVIDUAL_RECORD_LIVE_MODELS
        if scope is None or item[3] == scope
    ]


def _record_identity_key(*values, fallback=""):
    for value in values:
        text = " ".join(str(value or "").split()).lower()
        if text:
            return text
    return fallback


def _applicant_type_key(applicant_type="", nationality=""):
    applicant_text = str(applicant_type or "").strip().lower()
    nationality_text = str(nationality or "").strip().lower()
    png_values = {"png", "papua new guinea", "papua new guinean", "national", "local"}
    if "overseas" in applicant_text or "foreign" in applicant_text:
        return "overseas"
    if applicant_text in {"national", "local", "png"}:
        return "national"
    if nationality_text:
        normalized = nationality_text.replace(".", "").strip()
        if normalized in png_values or "papua new guinea" in normalized:
            return "national"
        if normalized not in {"-", "not stated", "unknown"}:
            return "overseas"
    return "national"


def _applicant_type_label(applicant_type):
    return "Overseas" if applicant_type == "overseas" else "National"


def _import_movement_status(record, current_year):
    record_type = record.record_type
    if record_type == "provisional":
        return "incoming", "Incoming - provisional"
    if record_type in {"full", "temporary", "workforce_listing"}:
        return "incoming", "Incoming - registration"
    if record_type == "practicing_license":
        if record.record_year and record.record_year < current_year:
            return "outgoing", "Outgoing review - prior-year licence"
        return "current", "Current - practising licence"
    return "current", "Current - source record"


def _live_movement_status(obj, today):
    if not getattr(obj, "is_active", True):
        return "outgoing", "Outgoing - inactive"
    expiry = getattr(obj, "license_expiry_date", None)
    if expiry:
        if expiry < today:
            return "outgoing", "Outgoing - licence expired"
        if expiry <= today + timedelta(days=90):
            return "outgoing", "Outgoing - licence expiring"
    if isinstance(obj, HealthStudent) and not obj.is_graduate:
        return "incoming", "Incoming - graduand"
    return "current", "Current - active register"


def _record_type_display(record):
    return dict(PracticingLicenseRecord.RECORD_TYPE_CHOICES).get(record.record_type, record.record_type or "-")


def _imported_individual_row(record, current_year):
    applicant_type = _applicant_type_key(record.applicant_type, record.nationality)
    movement_key, movement_label = _import_movement_status(record, current_year)
    target_label = dict(PracticingLicenseRecord.TARGET_MODEL_CHOICES).get(record.target_model, record.target_model or "Imported Record")
    workplace = " ".join(str(record.workplace_address or "").split())
    facility_name = _clean_facility_name(workplace) if workplace else ""
    batch = record.batch
    source_detail = f"{batch.source_file_name} / {record.source_sheet_name} row {record.source_row}"
    return {
        "identity_key": _record_identity_key(
            record.registration_no,
            record.practitioner_number,
            record.full_name,
            fallback=f"import:{record.pk}",
        ),
        "source": "imported",
        "source_label": "Imported workbook",
        "source_detail": source_detail,
        "source_sort": 1,
        "detail_url": reverse("record_detail", args=["practicinglicenserecord", record.pk]),
        "name": record.full_name or "Imported record",
        "registration_no": record.registration_no or record.practitioner_number or "-",
        "professional_type": record.category or target_label,
        "applicant_type": applicant_type,
        "applicant_type_label": _applicant_type_label(applicant_type),
        "origin": record.nationality or ("Papua New Guinea" if applicant_type == "national" else "Overseas"),
        "training": record.institution_name or record.qualification_name or "-",
        "employment": workplace or "-",
        "facility": facility_name or "-",
        "province": _normalize_province_label(record.province) if record.province else "-",
        "movement": movement_key,
        "movement_label": movement_label,
        "record_year": record.record_year or "-",
        "record_type": _record_type_display(record),
        "latest_activity": record.payment_date or record.issued_date,
        "sort_year": record.record_year or 0,
    }


def _row_matches_filters(row, applicant_type_filter, movement_filter):
    if applicant_type_filter in {"national", "overseas"} and row["applicant_type"] != applicant_type_filter:
        return False
    if movement_filter in {"incoming", "current", "outgoing"} and row["movement"] != movement_filter:
        return False
    return True


def _build_imported_individual_rows(scope, applicant_type_filter, movement_filter, query):
    current_year = date.today().year
    queryset = (
        _quality_approved_practicing_records().select_related("batch")
        .filter(target_model__in=_individual_import_target_models(scope))
        .order_by("-record_year", "-payment_date", "-issued_date", "-id")
    )
    if query:
        queryset = queryset.filter(
            Q(full_name__icontains=query)
            | Q(registration_no__icontains=query)
            | Q(practitioner_number__icontains=query)
            | Q(category__icontains=query)
            | Q(nationality__icontains=query)
            | Q(institution_name__icontains=query)
            | Q(workplace_address__icontains=query)
            | Q(province__icontains=query)
            | Q(source_sheet_name__icontains=query)
            | Q(batch__source_file_name__icontains=query)
        )

    rows_by_identity = {}
    for record in queryset:
        row = _imported_individual_row(record, current_year)
        if not _row_matches_filters(row, applicant_type_filter, movement_filter):
            continue
        rows_by_identity.setdefault(row["identity_key"], row)
    return list(rows_by_identity.values())


def _first_relation_by_object(queryset):
    by_object = {}
    for item in queryset:
        by_object.setdefault(item.object_id, item)
    return by_object


def _employment_summary(employment):
    if not employment:
        return "-"
    parts = [
        employment.employer_name,
        employment.position_held,
        employment.get_employment_status_display() if employment.employment_status else "",
        employment.get_area_of_employment_display() if employment.area_of_employment else "",
    ]
    return " / ".join(part for part in parts if part) or "-"


def _employment_facility(employment, posting):
    if posting and posting.facility:
        return posting.facility.name
    if employment:
        return employment.place_of_work or employment.employer_name or "-"
    return "-"


def _qualification_training(qualification, obj):
    if isinstance(obj, HealthStudent) and obj.institution:
        return obj.institution.name
    if not qualification:
        return "-"
    return (
        getattr(qualification.institution, "name", "")
        or qualification.institution_name
        or qualification.qualification_name
        or "-"
    )


def _qualification_origin(qualification, obj):
    if getattr(obj, "nationality", ""):
        return obj.nationality
    if qualification and qualification.country:
        return qualification.country
    return "Papua New Guinea" if getattr(obj, "applicant_type", "national") == "national" else "Overseas"


def _merge_import_details(live_row, imported_row):
    if not imported_row:
        return live_row
    live_row["source_label"] = "Live register + import"
    live_row["source_detail"] = f"{live_row['source_detail']} | {imported_row['source_detail']}"
    for field in ["origin", "training", "employment", "facility", "province"]:
        if live_row.get(field) in {"", "-"} and imported_row.get(field):
            live_row[field] = imported_row[field]
    if live_row["applicant_type"] == "national" and imported_row["applicant_type"] == "overseas":
        live_row["applicant_type"] = "overseas"
        live_row["applicant_type_label"] = "Overseas"
    live_row["record_year"] = imported_row.get("record_year") or live_row["record_year"]
    live_row["record_type"] = imported_row.get("record_type") or live_row["record_type"]
    live_row["sort_year"] = max(live_row.get("sort_year") or 0, imported_row.get("sort_year") or 0)
    return live_row


def _build_live_individual_rows(scope, applicant_type_filter, movement_filter, query, imported_rows_by_identity=None):
    rows = []
    today = date.today()
    imported_rows_by_identity = imported_rows_by_identity if imported_rows_by_identity is not None else {}

    for model, slug, label, _domain in _individual_live_models(scope):
        queryset = model.objects.select_related("cadre").order_by("last_name", "first_name", "id")
        if model is HealthStudent:
            queryset = queryset.select_related("institution")
        if query:
            query_filter = (
                Q(first_name__icontains=query)
                | Q(last_name__icontains=query)
                | Q(registration_no__icontains=query)
                | Q(registration_number__icontains=query)
                | Q(nationality__icontains=query)
                | Q(province__icontains=query)
                | Q(email__icontains=query)
                | Q(cadre__name__icontains=query)
            )
            if model is HealthStudent:
                query_filter |= Q(institution__name__icontains=query)
            queryset = queryset.filter(query_filter)

        objects = list(queryset)
        if not objects:
            continue
        content_type = ContentType.objects.get_for_model(model)
        object_ids = [obj.pk for obj in objects]
        employments = _first_relation_by_object(
            EmploymentRecord.objects.filter(content_type=content_type, object_id__in=object_ids)
            .order_by("object_id", "-created_at", "-id")
        )
        postings = _first_relation_by_object(
            PostingHistory.objects.filter(content_type=content_type, object_id__in=object_ids, is_current=True)
            .select_related("facility", "facility__location")
            .order_by("object_id", "-start_date", "-id")
        )
        qualifications = _first_relation_by_object(
            Qualification.objects.filter(content_type=content_type, object_id__in=object_ids)
            .select_related("institution")
            .order_by("object_id", "-completion_year", "-id")
        )

        for obj in objects:
            movement_key, movement_label = _live_movement_status(obj, today)
            applicant_type = _applicant_type_key(obj.applicant_type, obj.nationality)
            qualification = qualifications.get(obj.pk)
            employment = employments.get(obj.pk)
            posting = postings.get(obj.pk)
            identity_key = _record_identity_key(
                obj.registration_no,
                getattr(obj, "registration_number", ""),
                f"{obj.first_name} {obj.last_name}",
                fallback=f"live:{slug}:{obj.pk}",
            )
            row = {
                "identity_key": identity_key,
                "source": "live",
                "source_label": "Live register",
                "source_detail": label,
                "source_sort": 0,
                "detail_url": reverse("record_detail", args=[slug, obj.pk]),
                "name": f"{obj.first_name} {obj.last_name}".strip() or str(obj),
                "registration_no": obj.registration_no or getattr(obj, "registration_number", "") or "-",
                "professional_type": getattr(obj.cadre, "name", "") or label,
                "applicant_type": applicant_type,
                "applicant_type_label": _applicant_type_label(applicant_type),
                "origin": _qualification_origin(qualification, obj),
                "training": _qualification_training(qualification, obj),
                "employment": _employment_summary(employment),
                "facility": _employment_facility(employment, posting),
                "province": _normalize_province_label(obj.province) if obj.province else "-",
                "movement": movement_key,
                "movement_label": movement_label,
                "record_year": "-",
                "record_type": "Live register",
                "latest_activity": getattr(obj, "updated_at", None),
                "sort_year": today.year,
            }
            row = _merge_import_details(row, imported_rows_by_identity.pop(identity_key, None))
            if _row_matches_filters(row, applicant_type_filter, movement_filter):
                rows.append(row)

    return rows


def _registrar_individual_record_context(request):
    query = request.GET.get("q", "").strip()
    applicant_type_filter = request.GET.get("applicant_type", "all")
    movement_filter = request.GET.get("movement", "all")
    source_filter = request.GET.get("source", "all")
    if applicant_type_filter not in {"all", "national", "overseas"}:
        applicant_type_filter = "all"
    if movement_filter not in {"all", "incoming", "current", "outgoing"}:
        movement_filter = "all"
    if source_filter not in {"all", "live", "imported"}:
        source_filter = "all"

    requested_scope = request.GET.get("scope")
    scope = _individual_record_scope_for_user(request.user, requested_scope)

    imported_rows = []
    if source_filter in {"all", "imported"}:
        imported_rows = _build_imported_individual_rows(scope, applicant_type_filter, movement_filter, query)
    imported_rows_by_identity = {
        row["identity_key"]: row
        for row in imported_rows
    } if source_filter == "all" else {}

    rows = []
    if source_filter in {"all", "live"}:
        rows.extend(
            _build_live_individual_rows(
                scope,
                applicant_type_filter,
                movement_filter,
                query,
                imported_rows_by_identity=imported_rows_by_identity,
            )
        )
    if source_filter == "all":
        rows.extend(imported_rows_by_identity.values())
    elif source_filter == "imported":
        rows.extend(imported_rows)

    movement_rank = {"incoming": 0, "current": 1, "outgoing": 2}
    rows.sort(key=lambda row: (
        movement_rank.get(row["movement"], 9),
        row["applicant_type_label"],
        -int(row.get("sort_year") or 0),
        row["name"].lower(),
    ))

    paginator = Paginator(rows, INDIVIDUAL_RECORDS_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    query_params = request.GET.copy()
    query_params.pop("page", None)

    summary = {
        "total": len(rows),
        "national": sum(1 for row in rows if row["applicant_type"] == "national"),
        "overseas": sum(1 for row in rows if row["applicant_type"] == "overseas"),
        "incoming": sum(1 for row in rows if row["movement"] == "incoming"),
        "current": sum(1 for row in rows if row["movement"] == "current"),
        "outgoing": sum(1 for row in rows if row["movement"] == "outgoing"),
    }
    return {
        "individual_records": page_obj.object_list,
        "page_obj": page_obj,
        "paginator": paginator,
        "summary": summary,
        "filters": {
            "q": query,
            "applicant_type": applicant_type_filter,
            "movement": movement_filter,
            "source": source_filter,
            "scope": scope or "all",
        },
        "query_string": query_params.urlencode(),
        "scope": scope,
        "scope_label": _individual_scope_label(scope),
        "scope_options": [
            ("all", "All Offices"),
            ("nursing", "Nursing Council"),
            ("medical", "Medical Board"),
        ],
        "applicant_type_options": [
            ("all", "All"),
            ("national", "National"),
            ("overseas", "Overseas"),
        ],
        "movement_options": [
            ("all", "All"),
            ("incoming", "Incoming"),
            ("current", "Current"),
            ("outgoing", "Outgoing"),
        ],
        "source_options": [
            ("all", "All"),
            ("live", "Live Register"),
            ("imported", "Imported Workbooks"),
        ],
    }


def _origin_import_applicant_filter(applicant_type):
    if applicant_type == "overseas":
        return (
            Q(applicant_type__iexact="overseas")
            | (
                (Q(applicant_type="") | Q(applicant_type__isnull=True))
                & ~Q(nationality__iexact="PNG")
                & ~Q(nationality__icontains="Papua New Guinea")
                & ~Q(nationality="")
                & Q(nationality__isnull=False)
            )
        )
    return (
        Q(applicant_type__iexact="national")
        | Q(nationality__iexact="PNG")
        | Q(nationality__icontains="Papua New Guinea")
        | (
            (Q(applicant_type="") | Q(applicant_type__isnull=True))
            & (Q(nationality="") | Q(nationality__isnull=True))
        )
    )


def _origin_import_queryset(scope):
    return _quality_approved_practicing_records().filter(target_model__in=_individual_import_target_models(scope))


def _distinct_imported_people_count(queryset):
    with_registration = (
        queryset.exclude(registration_no__isnull=True)
        .exclude(registration_no="")
        .values("registration_no")
        .distinct()
        .count()
    )
    with_practitioner = (
        queryset.filter(Q(registration_no__isnull=True) | Q(registration_no=""))
        .exclude(practitioner_number__isnull=True)
        .exclude(practitioner_number="")
        .values("practitioner_number")
        .distinct()
        .count()
    )
    with_name_only = (
        queryset.filter(Q(registration_no__isnull=True) | Q(registration_no=""))
        .filter(Q(practitioner_number__isnull=True) | Q(practitioner_number=""))
        .exclude(full_name__isnull=True)
        .exclude(full_name="")
        .values("full_name")
        .distinct()
        .count()
    )
    return with_registration + with_practitioner + with_name_only


def _live_origin_count(scope, applicant_type):
    return sum(
        model.objects.filter(applicant_type=applicant_type).count()
        for model, _slug, _label, _domain in _individual_live_models(scope)
    )


def _origin_import_preview_rows(scope, per_applicant_limit):
    rows = []
    current_year = date.today().year
    base_queryset = (
        _origin_import_queryset(scope)
        .select_related("batch")
        .order_by("-record_year", "-payment_date", "-issued_date", "-id")
    )

    for applicant_type in ["overseas", "national"]:
        seen = set()
        selected = 0
        queryset = base_queryset.filter(_origin_import_applicant_filter(applicant_type))
        for record in queryset[: per_applicant_limit * 3]:
            row = _imported_individual_row(record, current_year)
            if row["applicant_type"] != applicant_type:
                continue
            if row["identity_key"] in seen:
                continue
            seen.add(row["identity_key"])
            rows.append(row)
            selected += 1
            if selected >= per_applicant_limit:
                break
    return rows


def _live_origin_preview_rows(scope, per_applicant_limit):
    rows = []
    today = date.today()
    live_models = _individual_live_models(scope)
    if not live_models:
        return rows
    per_model_limit = max(2, per_applicant_limit // len(live_models))

    for model, slug, label, _domain in live_models:
        for applicant_type in ["overseas", "national"]:
            queryset = model.objects.filter(applicant_type=applicant_type).select_related("cadre").order_by("-updated_at", "last_name", "first_name")
            if model is HealthStudent:
                queryset = queryset.select_related("institution")
            objects = list(queryset[:per_model_limit])
            if not objects:
                continue

            content_type = ContentType.objects.get_for_model(model)
            object_ids = [obj.pk for obj in objects]
            employments = _first_relation_by_object(
                EmploymentRecord.objects.filter(content_type=content_type, object_id__in=object_ids)
                .order_by("object_id", "-created_at", "-id")
            )
            postings = _first_relation_by_object(
                PostingHistory.objects.filter(content_type=content_type, object_id__in=object_ids, is_current=True)
                .select_related("facility", "facility__location")
                .order_by("object_id", "-start_date", "-id")
            )
            qualifications = _first_relation_by_object(
                Qualification.objects.filter(content_type=content_type, object_id__in=object_ids)
                .select_related("institution")
                .order_by("object_id", "-completion_year", "-id")
            )

            for obj in objects:
                movement_key, movement_label = _live_movement_status(obj, today)
                qualification = qualifications.get(obj.pk)
                employment = employments.get(obj.pk)
                posting = postings.get(obj.pk)
                rows.append({
                    "identity_key": _record_identity_key(
                        obj.registration_no,
                        getattr(obj, "registration_number", ""),
                        f"{obj.first_name} {obj.last_name}",
                        fallback=f"live:{slug}:{obj.pk}",
                    ),
                    "source": "live",
                    "source_label": "Live register",
                    "source_detail": label,
                    "detail_url": reverse("record_detail", args=[slug, obj.pk]),
                    "name": f"{obj.first_name} {obj.last_name}".strip() or str(obj),
                    "registration_no": obj.registration_no or getattr(obj, "registration_number", "") or "-",
                    "professional_type": getattr(obj.cadre, "name", "") or label,
                    "applicant_type": applicant_type,
                    "applicant_type_label": _applicant_type_label(applicant_type),
                    "origin": _qualification_origin(qualification, obj),
                    "training": _qualification_training(qualification, obj),
                    "employment": _employment_summary(employment),
                    "facility": _employment_facility(employment, posting),
                    "province": _normalize_province_label(obj.province) if obj.province else "-",
                    "movement": movement_key,
                    "movement_label": movement_label,
                    "record_year": "-",
                    "record_type": "Live register",
                    "sort_year": today.year,
                })
    return rows


def _registrar_worker_origin_context(user, limit=REGISTRAR_WORKER_ORIGIN_TABLE_LIMIT):
    scope = _individual_record_scope_for_user(user)
    latest_batch = _latest_import_batch_for_scope(scope if scope in {"medical", "nursing"} else "nursing")
    cache_key = (
        "registrar_worker_origin_context_v3:"
        f"{scope or 'all'}:"
        f"{latest_batch.id if latest_batch else 'none'}:"
        f"{date.today().isoformat()}:{limit}"
    )
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    import_queryset = _origin_import_queryset(scope)
    imported_national_total = _distinct_imported_people_count(
        import_queryset.filter(_origin_import_applicant_filter("national"))
    )
    imported_overseas_total = _distinct_imported_people_count(
        import_queryset.filter(_origin_import_applicant_filter("overseas"))
    )
    live_national_total = _live_origin_count(scope, "national")
    live_overseas_total = _live_origin_count(scope, "overseas")

    per_applicant_limit = max(20, limit // 4)
    rows = []
    rows.extend(_origin_import_preview_rows(scope, per_applicant_limit))
    rows.extend(_live_origin_preview_rows(scope, max(8, limit // 12)))
    rows.sort(key=lambda row: (
        0 if row["applicant_type"] == "overseas" else 1,
        row["source_label"],
        str(row.get("name", "")).lower(),
    ))
    rows = rows[:limit]

    context = {
        "registrar_origin_scope": scope,
        "registrar_origin_scope_label": _individual_scope_label(scope),
        "registrar_worker_origin_rows": rows,
        "registrar_worker_origin_table_limit": limit,
        "registrar_worker_origin_summary": {
            "national_total": live_national_total + imported_national_total,
            "overseas_total": live_overseas_total + imported_overseas_total,
            "combined_total": live_national_total + imported_national_total + live_overseas_total + imported_overseas_total,
            "live_national_total": live_national_total,
            "live_overseas_total": live_overseas_total,
            "imported_national_total": imported_national_total,
            "imported_overseas_total": imported_overseas_total,
            "displayed_rows": len(rows),
        },
    }
    cache.set(cache_key, context, DASHBOARD_CACHE_TIMEOUT_SECONDS)
    return context


def _imported_facility_worker_context(latest_batch=None, target_models=None, limit=100):
    records = _quality_approved_practicing_records().exclude(workplace_address__isnull=True).exclude(workplace_address='')
    if latest_batch:
        records = records.filter(batch=latest_batch)
    if target_models:
        records = records.filter(target_model__in=target_models)

    total_workers = records.count()
    total_facilities = records.values('workplace_address').distinct().count() if total_workers else 0
    raw_rows = list(
        records.values('workplace_address')
        .annotate(total=Count('id'))
        .order_by('-total')[:500]
    )
    grouped = {}
    for row in raw_rows:
        label = _clean_facility_name(row['workplace_address'])
        grouped.setdefault(label, {'facility_name': label, 'raw_names': [], 'total': 0})
        grouped[label]['raw_names'].append(row['workplace_address'])
        grouped[label]['total'] += row['total']

    facility_rows = sorted(grouped.values(), key=lambda item: item['total'], reverse=True)[:limit]
    raw_to_facility = {
        raw_name: item['facility_name']
        for item in facility_rows
        for raw_name in item['raw_names']
    }
    for item in facility_rows:
        item['category_counts'] = defaultdict(int)
        item['workers'] = []

    rows_by_facility = {item['facility_name']: item for item in facility_rows}
    if raw_to_facility:
        facility_record_rows = records.filter(workplace_address__in=raw_to_facility.keys()).values(
            'workplace_address',
            'full_name',
            'registration_no',
            'practitioner_number',
            'category',
            'target_model',
            'record_year',
            'record_type',
        ).order_by('-record_year', 'full_name')
        for record in facility_record_rows:
            item = rows_by_facility[raw_to_facility[record['workplace_address']]]
            item['category_counts'][_display_category(record)] += 1
            if len(item['workers']) < 10:
                item['workers'].append(record)

    for item in facility_rows:
        item['categories'] = [
            {'name': name, 'count': count}
            for name, count in sorted(item['category_counts'].items(), key=lambda row: row[1], reverse=True)[:8]
        ]
        item.pop('category_counts', None)

    return {
        'imported_facility_workers': facility_rows,
        'imported_facility_count': total_facilities,
        'imported_facility_worker_count': total_workers,
        'imported_workplace_reference_count': total_facilities,
        'imported_workplace_worker_count': total_workers,
    }


def _receipt_form_for_user(user, application_queryset, *, data=None, files=None):
    if application_queryset is None or not hasattr(application_queryset, "all"):
        application_queryset = Application.objects.none()
    form = ReceiptSubmissionForm(data=data, files=files, application_queryset=application_queryset)
    form.fields['application'].label_from_instance = lambda app: (
        f"{app.form_code} - {app.professional or 'Application'} - {app.submitted_date:%d %b %Y}"
    )
    return form


def _default_registration_guidelines():
    return [
        {
            'code': 'GENERAL-01',
            'title': 'Use the Correct Form Code',
            'audience': 'general',
            'summary': 'Select the exact PNGNCRF form code before submitting so your application follows the right review pathway.',
            'required_fields': ['Correct applicant pathway', 'Matching form code', 'Supporting documents', 'Signature or declaration'],
            'action_url_name': 'nursing_forms_portal',
            'display_order': 1,
        },
        {
            'code': 'GENERAL-02',
            'title': 'Keep Receipt and Supporting Documents Ready',
            'audience': 'general',
            'summary': 'Upload payment evidence, passport or ID documents, qualifications, and employer references where required.',
            'required_fields': ['Official receipt number', 'Receipt image', 'ID or passport', 'Certificates or references'],
            'action_url_name': 'fee_structure',
            'display_order': 2,
        },
        {
            'code': 'G3',
            'title': 'Graduate Vitae',
            'audience': 'graduand',
            'summary': 'For graduands preparing their vitae before provisional or full licensure review.',
            'required_fields': ['Personal details', 'Education history', 'Program length', 'Clinical placements', 'Skills log summary'],
            'action_url_name': 'public_form_code_register',
            'display_order': 10,
        },
        {
            'code': 'NC1',
            'title': 'Application for Provisional Licence',
            'audience': 'graduand',
            'summary': 'Required for PNG and overseas provisional applicants after qualification completion.',
            'required_fields': ['Applicant details', 'Qualification details', 'Institute attended', 'Supporting documents checklist', 'Applicant signature'],
            'action_url_name': 'public_form_code_register',
            'display_order': 20,
        },
        {
            'code': 'NC2',
            'title': 'Application for Full Licence',
            'audience': 'nurse',
            'summary': 'Used when moving from provisional approval to full practice licence.',
            'required_fields': ['Applicant details', 'Provisional licence reference', 'Competency evidence', 'Employer details', 'Applicant signature'],
            'action_url_name': 'public_form_code_register',
            'display_order': 20,
        },
        {
            'code': 'NC3',
            'title': 'Renewal of Licence',
            'audience': 'nurse',
            'summary': 'Annual renewal for PNG and overseas practitioners with employment and continuing practice evidence.',
            'required_fields': ['Licence number', 'Applicant details', 'Employer details', 'Continuing practice evidence', 'Applicant signature'],
            'action_url_name': 'public_form_code_register',
            'display_order': 30,
        },
        {
            'code': 'NC6',
            'title': 'Competency for Full Licence Nursing',
            'audience': 'nurse',
            'summary': 'Supervisor-completed competency evidence for nursing applicants.',
            'required_fields': ['Applicant name', 'Clinical competencies', 'Ethical competencies', 'Communication competencies', 'Supervisor assessment', 'Signature and date'],
            'action_url_name': 'public_form_code_register',
            'display_order': 40,
        },
        {
            'code': 'PROFILE',
            'title': 'Keep Your Record Current',
            'audience': 'doctor',
            'summary': 'Ensure your personal details, registration details, and payment records stay current in the registry.',
            'required_fields': ['Professional information', 'Current contact details', 'Application references', 'Receipt records'],
            'action_url_name': 'public_doctor_register',
            'display_order': 10,
        },
        {
            'code': 'PROFILE',
            'title': 'Keep Your Registry File Complete',
            'audience': 'chw',
            'summary': 'Maintain your CHW profile, payment history, and supporting documentation for registry review.',
            'required_fields': ['Registration details', 'Training level', 'Contact details', 'Payment evidence'],
            'action_url_name': 'public_chw_register',
            'display_order': 10,
        },
        {
            'code': 'PROFILE',
            'title': 'Maintain Registration Readiness',
            'audience': 'nurse_aide',
            'summary': 'Keep employer details, payment records, and profile information up to date for applications and support requests.',
            'required_fields': ['Registration details', 'Employer details', 'Contact information', 'Receipt records'],
            'action_url_name': 'public_nurse_aide_register',
            'display_order': 10,
        },
    ]


def _ensure_registration_guidelines():
    for row in _default_registration_guidelines():
        RegistrationGuideline.objects.update_or_create(
            code=row['code'],
            audience=row['audience'],
            defaults={
                'title': row['title'],
                'summary': row['summary'],
                'required_fields': row['required_fields'],
                'action_url_name': row['action_url_name'],
                'display_order': row['display_order'],
                'is_active': True,
            },
        )


def _guidelines_for_audience(audience):
    _ensure_registration_guidelines()
    if audience == 'student':
        audience = 'graduand'
    return RegistrationGuideline.objects.filter(
        is_active=True,
        audience__in=['general', audience],
    ).order_by('display_order', 'code')


def _professional_assets(professional):
    if not professional:
        return {
            'documents': [],
            'photos': [],
            'license_label': 'No record found',
            'license_state': 'Unknown',
            'license_days_left': None,
            'recommended_application_url': 'public_nurse_provisional_register',
        }

    ct = ContentType.objects.get_for_model(professional)
    documents = ProfessionalDocument.objects.filter(content_type=ct).select_related('document_type').order_by('-uploaded_at')
    photos = ProfessionalPhoto.objects.filter(content_type=ct).order_by('-is_primary', '-uploaded_at')

    license_expiry = getattr(professional, 'license_expiry_date', None)
    license_days_left = None
    if license_expiry:
        license_days_left = (license_expiry - date.today()).days

    if license_expiry is None:
        license_state = 'No licence on file'
    elif license_days_left is not None and license_days_left < 0:
        license_state = 'Expired'
    elif license_days_left is not None and license_days_left <= 30:
        license_state = 'Expiring Soon'
    else:
        license_state = 'Active'

    recommended_application_url = 'public_nurse_renewal'
    last_provisional = Application.objects.filter(content_type=ct, form_code='NC1').order_by('-approved_date', '-submitted_date').first()
    if last_provisional and last_provisional.status != 'approved':
        recommended_application_url = 'public_nurse_provisional_register'
    elif last_provisional and last_provisional.status == 'approved' and not getattr(professional, 'license_expiry_date', None):
        recommended_application_url = 'public_nurse_full_license'

    return {
        'documents': documents,
        'photos': photos,
        'license_label': license_expiry.strftime('%d %b %Y') if license_expiry else 'Not set',
        'license_state': license_state,
        'license_days_left': license_days_left,
        'recommended_application_url': recommended_application_url,
    }


def _current_provisional_licenses(limit=PROVISIONAL_LICENSE_TABLE_LIMIT):
    cache_key = f"current_provisional_licenses_v2:{limit}:{date.today().isoformat()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    today = date.today()
    nursing_ct = ContentType.objects.get_for_model(NursingProfessional)
    provisional_apps = (
        Application.objects.filter(form_code='NC1', status='approved', content_type=nursing_ct)
        .select_related('content_type')
        .order_by('expiry_date', '-approved_date')
    )
    provisional_app_total = provisional_apps.count()
    provisional_app_rows = list(
        provisional_apps.values(
            'id',
            'object_id',
            'approved_date',
            'submitted_date',
            'expiry_date',
            'payload',
        )[:limit]
    )
    professional_map = NursingProfessional.objects.in_bulk(
        {
            row['object_id']
            for row in provisional_app_rows
            if row['object_id']
        }
    )

    rows = []
    for app in provisional_app_rows:
        professional = professional_map.get(app['object_id'])
        if not professional:
            continue

        issued_date = app['approved_date'] or app['submitted_date']
        expiry_date = app['expiry_date']
        if not expiry_date and issued_date:
            expiry_date = issued_date + timedelta(days=180)

        payload = app['payload'] or {}
        rows.append({
            'application_id': app['id'],
            'professional': professional,
            'full_name': f'{professional.first_name} {professional.last_name}'.strip(),
            'registration_no': getattr(professional, 'registration_no', '') or getattr(professional, 'registration_number', ''),
            'license_no': payload.get('license_no') or payload.get('provisional_licence_number') or getattr(professional, 'registration_no', ''),
            'year': issued_date.year if issued_date else None,
            'institution': getattr(professional, 'institution', None),
            'qualification': getattr(professional, 'qualification_level', '') or getattr(professional, 'program', '') or '',
            'issued_date': issued_date,
            'expiry_date': expiry_date,
            'days_left': (expiry_date - today).days if expiry_date else None,
            'status': 'Active' if expiry_date and expiry_date >= today else 'Expired' if expiry_date else 'Missing issued date',
            'source': 'NC1 Application',
        })

    imported_provisional = _quality_approved_practicing_records().filter(
        record_type='provisional',
        target_model='healthstudent',
    )
    imported_provisional_total = imported_provisional.count()

    seen = {row['registration_no'] or row['full_name'] for row in rows}
    remaining = max(limit - len(rows), 0)
    imported_records = imported_provisional.order_by('-record_year', '-issued_date', 'full_name').values(
        'full_name',
        'registration_no',
        'record_year',
        'institution_name',
        'qualification_name',
        'issued_date',
        'source_sheet_name',
    )[: max(remaining * 2, 50)]
    for record in imported_records:
        if not remaining:
            break
        if not record['record_year'] and not record['issued_date']:
            continue
        if 'listing starts here' in (record['full_name'] or '').lower():
            continue
        key = record['registration_no'] or record['full_name']
        if key in seen:
            continue
        seen.add(key)
        issued_date = record['issued_date']
        expiry_date = issued_date + timedelta(days=180) if issued_date else None
        rows.append({
            'application': None,
            'professional': None,
            'full_name': record['full_name'],
            'registration_no': record['registration_no'],
            'license_no': record['registration_no'],
            'year': record['record_year'],
            'institution': record['institution_name'],
            'qualification': record['qualification_name'],
            'issued_date': issued_date,
            'expiry_date': expiry_date,
            'days_left': (expiry_date - today).days if expiry_date else None,
            'status': 'Active' if expiry_date and expiry_date >= today else 'Expired' if expiry_date else 'Missing issued date',
            'source': record['source_sheet_name'],
        })
        remaining -= 1

    context = {
        'rows': rows,
        'display_count': len(rows),
        'total_count': provisional_app_total + imported_provisional_total,
        'limit': limit,
    }
    cache.set(cache_key, context, DASHBOARD_CACHE_TIMEOUT_SECONDS)
    return context


def _recent_nursing_applications(limit=15):
    nursing_ct = ContentType.objects.get_for_model(NursingProfessional)
    return (
        Application.objects.filter(
            content_type=nursing_ct,
            form_code__in=['NC1', 'NC2', 'NC3', 'NC5', 'NC6', 'NC7', 'NC8', 'NC9', 'NC10', 'NC11'],
        )
        .order_by('-submitted_date', '-id')[:limit]
    )


def _record_identity(record):
    return record.registration_no or record.practitioner_number or record.full_name


def _identity_count(records):
    return len({
        identity
        for identity in (_record_identity(record) for record in records)
        if identity
    })


def _specialist_record_filter():
    query = Q()
    for keyword in MEDICAL_SPECIALIST_KEYWORDS:
        query |= Q(qualification_name__icontains=keyword)
        query |= Q(category__icontains=keyword)
        query |= Q(source_sheet_name__icontains=keyword)
    return query


def _specialist_profile_label(value):
    text = str(value or "").strip()
    if not text:
        return ""
    return MEDICAL_SPECIALIST_LABELS.get(text, text)


def _is_specialist_profile_value(value):
    text = str(value or "").strip()
    if not text or text.lower() in GENERIC_MEDICAL_SPECIALTY_LABELS:
        return False
    if text in MEDICAL_SPECIALIST_VALUES:
        return True
    return any(keyword in text.lower() for keyword in MEDICAL_SPECIALIST_KEYWORDS)


def _medical_allied_count():
    records = _quality_approved_practicing_records().filter(
        batch__source_kind__in=MEDICAL_IMPORT_SOURCE_KINDS,
        target_model='other',
        record_type__in=['full', 'workforce_listing'],
    )
    return _identity_count(records)


def _document_types_for_scope(scope):
    queryset = DocumentType.objects.order_by('name')
    if scope not in {'medical', 'nursing'}:
        return queryset
    medical_filter = (
        Q(description__icontains='Medical Board')
        | Q(name__icontains='Medical Board')
        | Q(documentrequirement__pathway__regulatory_body__name__icontains='Medical Board')
        | Q(documentrequirement__pathway__regulatory_body__code__icontains='medical')
    )
    nursing_filter = (
        Q(description__icontains='Nursing Council')
        | Q(name__icontains='Nursing Council')
        | Q(documentrequirement__pathway__regulatory_body__name__icontains='Nursing Council')
        | Q(documentrequirement__pathway__regulatory_body__code__icontains='nursing')
    )
    if scope == 'medical':
        return queryset.filter(medical_filter).exclude(nursing_filter).distinct()
    return queryset.filter(nursing_filter).exclude(medical_filter).distinct()


PNG_NURSING_PROVINCES = [
    'National Capital District',
    'Central Province',
    'Gulf Province',
    'Milne Bay Province',
    'Northern (Oro) Province',
    'Western Province',
    'Enga Province',
    'Hela Province',
    'Jiwaka Province',
    'Simbu Province',
    'Eastern Highlands Province',
    'Southern Highlands Province',
    'Western Highlands Province',
    'Morobe Province',
    'Madang Province',
    'East Sepik Province',
    'Sandaun Province',
    'Manus Province',
    'New Ireland Province',
    'East New Britain Province',
    'West New Britain Province',
    'Autonomous Region of Bougainville',
]


def _nursing_record_queryset():
    current_year = date.today().year
    return _quality_approved_practicing_records().filter(
        target_model__in=['nursingprofessional', 'midwife', 'nurseaide', 'healthstudent'],
        record_year__isnull=False,
        record_year__lte=current_year,
    ).exclude(batch__source_file_name__icontains='ATP')


def _latest_atp_batch():
    cache_key = "latest_atp_batch_v1"
    sentinel = object()
    cached = cache.get(cache_key, sentinel)
    if cached is not sentinel:
        return cached or None

    batch = DataImportBatch.objects.filter(
        source_kind='ndata_workbook',
        status='completed',
        source_file_name__icontains='ATP',
    ).order_by('-started_at').first()
    cache.set(cache_key, batch or False, DASHBOARD_CACHE_TIMEOUT_SECONDS)
    return batch


def _workplace_ownership_label(value):
    text = str(value or '').lower()
    if not text.strip():
        return 'Other'
    if any(keyword in text for keyword in ATP_CHURCH_KEYWORDS):
        return 'Church'
    if any(keyword in text for keyword in ATP_PRIVATE_KEYWORDS):
        return 'Private'
    if any(keyword in text for keyword in ATP_PUBLIC_KEYWORDS):
        return 'Public'
    return 'Other'


def _frequent_nursing_category_label(value):
    text = " ".join(str(value or "").split())
    if not text:
        return ""
    return FREQUENT_NURSING_CATEGORY_LOOKUP.get(text.lower(), "")


def _facility_reporting_group(value, ownership):
    text = str(value or "").lower()
    if ownership == "Private":
        return "private"
    if ownership == "Church" or any(keyword in text for keyword in ATP_NGO_KEYWORDS):
        return "ngo"
    if ownership == "Public":
        return "pha"
    return "review"


def _facility_reporting_label(group):
    labels = {
        "pha": "Provincial Health Authority facilities",
        "private": "Private facilities",
        "ngo": "Non-government organizations",
        "review": "Facility ownership needs review",
    }
    return labels.get(group, group.title())


def _current_atp_record_queryset():
    batch = _latest_atp_batch()
    if not batch:
        return batch, None, PracticingLicenseRecord.objects.none()
    base_queryset = _quality_approved_practicing_records().filter(
        batch=batch,
        record_type='practicing_license',
        target_model__in=ATP_NURSING_TARGET_MODELS,
    )
    current_year = base_queryset.order_by('-record_year').values_list('record_year', flat=True).first()
    if not current_year:
        return batch, None, base_queryset.none()
    return batch, current_year, base_queryset.filter(record_year=current_year)


def _nursing_frequent_filter_options():
    category_options = [
        {"label": label, "url": f"{reverse('nursing_frequent_records')}?{urlencode({'category': label})}"}
        for label in FREQUENT_NURSING_CATEGORY_ORDER
    ]
    facility_options = [
        {"key": key, "label": _facility_reporting_label(key), "url": f"{reverse('nursing_frequent_records')}?{urlencode({'facility_group': key})}"}
        for key in ["pha", "private", "ngo", "review"]
    ]
    return category_options, facility_options


def _nursing_frequent_records_context(request):
    batch, current_year, queryset = _current_atp_record_queryset()
    category_filter = " ".join(request.GET.get("category", "").split())
    facility_group_filter = request.GET.get("facility_group", "")
    category_review_filter = request.GET.get("category_review") == "1"
    valid_facility_groups = {"pha", "private", "ngo", "review"}
    if facility_group_filter not in valid_facility_groups:
        facility_group_filter = ""

    records = list(
        queryset.select_related("batch")
        .order_by("-payment_date", "-issued_date", "full_name", "-id")
    )
    filtered_records = []
    for record in records:
        workplace_name = _clean_facility_name(record.workplace_address)
        ownership = _workplace_ownership_label(workplace_name)
        facility_group_key = _facility_reporting_group(workplace_name, ownership)
        standard_category = _frequent_nursing_category_label(record.category)

        if category_filter and record.category != category_filter:
            continue
        if facility_group_filter and facility_group_key != facility_group_filter:
            continue
        if category_review_filter and standard_category:
            continue

        record._frequent_workplace_name = workplace_name
        record._frequent_ownership = ownership
        record._frequent_facility_group_key = facility_group_key
        record._frequent_facility_group_label = _facility_reporting_label(facility_group_key)
        record._frequent_standard_category = standard_category
        filtered_records.append(record)

    records_by_identity = {}
    for record in filtered_records:
        identity = _record_identity(record) or f"record:{record.pk}"
        records_by_identity.setdefault(identity, record)

    selected_records = list(records_by_identity.values())
    record_ids = [record.pk for record in selected_records]
    practicing_content_type = ContentType.objects.get_for_model(PracticingLicenseRecord)
    reviews_by_object_id = {
        review.object_id: review
        for review in MissingDataReview.objects.filter(
            content_type=practicing_content_type,
            object_id__in=record_ids,
        ).exclude(status="resolved")
    }

    rows = []
    valid_count = 0
    needs_review_count = 0
    high_risk_count = 0
    for record in selected_records:
        review = reviews_by_object_id.get(record.pk)
        issues = list(getattr(review, "missing_fields", []) or [])
        if not record._frequent_standard_category:
            issues.append("Category label is not in the standard registrar list")
        if record._frequent_facility_group_key == "review":
            issues.append("Facility ownership needs review")
        issues = list(dict.fromkeys(issues))

        if review and review.severity == "high":
            status_label = "High risk review"
            status_class = "danger"
            high_risk_count += 1
        elif issues:
            status_label = "Needs review"
            status_class = "warning"
            needs_review_count += 1
        else:
            status_label = "Valid"
            status_class = "success"
            valid_count += 1

        rows.append({
            "record": record,
            "name": record.full_name or "-",
            "registration_no": record.registration_no or "-",
            "practitioner_number": record.practitioner_number or "-",
            "category": record.category or "-",
            "category_status": "Standard" if record._frequent_standard_category else "Review label",
            "facility": record._frequent_workplace_name,
            "facility_group": record._frequent_facility_group_label,
            "province": _normalize_province_label(record.province) if record.province else "-",
            "gender": record.gender or "-",
            "nationality": record.nationality or "-",
            "payment_date": record.payment_date,
            "issued_date": record.issued_date,
            "source_sheet": record.source_sheet_name,
            "source_row": record.source_row,
            "status_label": status_label,
            "status_class": status_class,
            "issues": issues,
            "detail_url": reverse("record_detail", args=["practicinglicenserecord", record.pk]),
            "edit_url": reverse("record_update", args=["practicinglicenserecord", record.pk]),
        })

    if category_filter:
        page_title = category_filter
        active_filter_label = f"Category: {category_filter}"
    elif category_review_filter:
        page_title = "Category Labels Requiring Cleanup"
        active_filter_label = "Only records with unlisted category labels"
    elif facility_group_filter:
        page_title = _facility_reporting_label(facility_group_filter)
        active_filter_label = f"Facility group: {page_title}"
    else:
        page_title = "All Current ATP Nurses"
        active_filter_label = "All current ATP people"

    category_options, facility_options = _nursing_frequent_filter_options()
    return {
        "atp_batch": batch,
        "atp_current_year": current_year,
        "page_title": page_title,
        "active_filter_label": active_filter_label,
        "category_filter": category_filter,
        "facility_group_filter": facility_group_filter,
        "category_review_filter": category_review_filter,
        "category_options": category_options,
        "facility_options": facility_options,
        "record_rows": rows,
        "record_total": len(rows),
        "valid_count": valid_count,
        "needs_review_count": needs_review_count,
        "high_risk_count": high_risk_count,
    }


def _year_band_label(year_value, current_year):
    if not year_value:
        return 'Past'
    if year_value == current_year:
        return 'Current'
    if year_value >= current_year - 2:
        return 'Recent'
    return 'Past'


def _nursing_province_distribution_context():
    cache_key = f"nursing_province_distribution_context_v2:{date.today().isoformat()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    province_counts = {province: 0 for province in PNG_NURSING_PROVINCES}

    for model in [NursingProfessional, Midwife, NurseAide, HealthStudent]:
        for value in model.objects.exclude(province__isnull=True).exclude(province='').values_list('province', flat=True):
            label = _normalize_province_label(value)
            if label in province_counts:
                province_counts[label] += 1

    if not any(province_counts.values()):
        imported_records = _nursing_record_queryset().exclude(province='')
        for value in imported_records.values_list('province', flat=True):
            label = _normalize_province_label(value)
            if label in province_counts:
                province_counts[label] += 1

    province_rows = [
        {'label': label, 'count': province_counts[label]}
        for label in PNG_NURSING_PROVINCES
    ]
    context = {
        'province_rows': province_rows,
        'province_labels': json.dumps([row['label'] for row in province_rows]),
        'province_values': json.dumps([row['count'] for row in province_rows]),
    }
    cache.set(cache_key, context, DASHBOARD_CACHE_TIMEOUT_SECONDS)
    return context


def _nursing_council_analytics_context():
    cache_key = f"nursing_council_analytics_context_v3:{date.today().isoformat()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    nursing_records = _nursing_record_queryset().filter(target_model__in=['nursingprofessional', 'midwife', 'nurseaide'])
    provisional_records = _nursing_record_queryset().filter(target_model='healthstudent', record_type='provisional')

    yearly_sets = defaultdict(lambda: {
        'provisional': set(),
        'full': set(),
        'temporary': set(),
        'practicing_license': set(),
        'workforce_listing': set(),
    })

    for record in provisional_records:
        if record.record_year:
            yearly_sets[record.record_year]['provisional'].add(_record_identity(record))

    for record in nursing_records.filter(record_type__in=['full', 'temporary', 'practicing_license', 'workforce_listing']):
        if record.record_year:
            yearly_sets[record.record_year][record.record_type].add(_record_identity(record))

    yearly_rows = []
    for year_value in sorted(yearly_sets.keys(), reverse=True):
        row_sets = yearly_sets[year_value]
        yearly_rows.append({
            'year': year_value,
            'graduand_count': len(row_sets['provisional']),
            'full_registration_count': len(row_sets['full']),
            'temporary_license_count': len(row_sets['temporary']),
            'practicing_license_count': len(row_sets['practicing_license']),
            'active_listing_count': len(row_sets['workforce_listing']),
        })

    chart_rows = list(reversed(yearly_rows[:18]))
    latest_year_row = yearly_rows[0] if yearly_rows else {}

    full_license_records = list(
        nursing_records.filter(record_type__in=['full', 'practicing_license'])
        .order_by('-record_year', '-issued_date', '-payment_date', 'full_name')[:60]
    )

    full_identities = {
        _record_identity(record)
        for record in nursing_records.filter(record_type='full')
        if _record_identity(record)
    }
    practicing_identities = {
        _record_identity(record)
        for record in nursing_records.filter(record_type='practicing_license')
        if _record_identity(record)
    }
    provisional_identities = {
        _record_identity(record)
        for record in provisional_records
        if _record_identity(record)
    }

    pipeline_totals = [
        {
            'stage': 'Graduands / Provisional Records',
            'count': len(provisional_identities) or HealthStudent.objects.count(),
            'description': 'Incoming graduands and provisional licence records imported for Nursing Council tracking.',
        },
        {
            'stage': 'Full Registration',
            'count': len(full_identities),
            'description': 'Nurses with imported NC2/full-registration history.',
        },
        {
            'stage': 'Practising Licence / Renewal',
            'count': len(practicing_identities),
            'description': 'Nurses with annual practising licence records.',
        },
        {
            'stage': 'Active Nursing Register',
            'count': NursingProfessional.objects.filter(is_active=True).count(),
            'description': 'Current normalized NursingProfessional records in the central database.',
        },
    ]

    context = {
        'nursing_yearly_rows': yearly_rows,
        'nursing_full_license_records': full_license_records,
        'nursing_pipeline_totals': pipeline_totals,
        'nursing_flow_year_labels': json.dumps([row['year'] for row in chart_rows]),
        'nursing_flow_graduand_values': json.dumps([row['graduand_count'] for row in chart_rows]),
        'nursing_flow_full_values': json.dumps([row['full_registration_count'] for row in chart_rows]),
        'nursing_flow_practicing_values': json.dumps([row['practicing_license_count'] for row in chart_rows]),
        'nursing_full_registration_total': len(full_identities),
        'nursing_practicing_license_total': len(practicing_identities),
        'nursing_provisional_pipeline_total': len(provisional_identities),
        'nursing_latest_year': latest_year_row.get('year'),
        'nursing_latest_full_count': latest_year_row.get('full_registration_count', 0),
        'nursing_latest_practicing_count': latest_year_row.get('practicing_license_count', 0),
        'nursing_analytics_batch': _latest_ndata_batch(),
    }
    cache.set(cache_key, context, DASHBOARD_CACHE_TIMEOUT_SECONDS)
    return context


def _latest_ndata_batch():
    cache_key = "latest_ndata_batch_v2"
    sentinel = object()
    cached = cache.get(cache_key, sentinel)
    if cached is not sentinel:
        return cached or None

    batch = DataImportBatch.objects.filter(
        source_kind='ndata_workbook',
        status='completed',
    ).exclude(source_file_name__icontains='ATP').order_by('-started_at').first()
    if batch:
        cache.set(cache_key, batch, DASHBOARD_CACHE_TIMEOUT_SECONDS)
        return batch

    batch = (
        DataImportBatch.objects.filter(
            status='completed',
            source_kind__in=NURSING_IMPORT_SOURCE_KINDS,
            records__target_model__in=NURSING_IMPORT_TARGET_MODELS,
        )
        .distinct()
        .order_by('-started_at')
        .first()
    )
    cache.set(cache_key, batch or False, DASHBOARD_CACHE_TIMEOUT_SECONDS)
    return batch


def _latest_medical_import_batch():
    cache_key = "latest_medical_import_batch_v1"
    sentinel = object()
    cached = cache.get(cache_key, sentinel)
    if cached is not sentinel:
        return cached or None

    batch = DataImportBatch.objects.filter(
        source_kind__in=MEDICAL_IMPORT_SOURCE_KINDS,
        status='completed',
    ).order_by('-started_at').first()
    cache.set(cache_key, batch or False, DASHBOARD_CACHE_TIMEOUT_SECONDS)
    return batch


def _latest_import_batch_for_scope(scope):
    if scope == 'medical':
        return _latest_medical_import_batch()
    return _latest_ndata_batch()


def _latest_nursing_import_batch_with(field_name):
    return _latest_import_batch_with(field_name, 'nursing')


def _latest_import_batch_with(field_name, scope):
    scope_key = scope or 'nursing'
    cache_key = f"latest_import_batch_with_v2:{scope_key}:{field_name}"
    sentinel = object()
    cached = cache.get(cache_key, sentinel)
    if cached is not sentinel:
        return cached or None

    target_models = _import_target_models_for_scope(scope_key)
    batch_ids = (
        _quality_approved_practicing_records().filter(
            target_model__in=target_models,
            **{f"{field_name}__isnull": False},
        )
        .exclude(**{field_name: ""})
        .values("batch_id")
    )
    batch = (
        DataImportBatch.objects.filter(
            status='completed',
            source_kind__in=_import_source_kinds_for_scope(scope_key),
            id__in=Subquery(batch_ids),
        )
        .order_by('-started_at')
        .first()
    )
    cache.set(cache_key, batch or False, DASHBOARD_CACHE_TIMEOUT_SECONDS)
    return batch


def _nursing_atp_context():
    configured_workflow_rows = build_nursing_workflow_rows()
    fallback_workflow_rows = [
        {
            'pathway': 'NC1 Provisional Licence',
            'who': 'Graduands and first-time provisional applicants',
            'summary': 'Start here for provisional approval after training completion and document screening.',
        },
        {
            'pathway': 'NC2 Full Registration and Licence',
            'who': 'Nurses and midwives moving from provisional status to full practice',
            'summary': 'Use after competency clearance, supporting documents, and registrar review are complete.',
        },
        {
            'pathway': 'NC3 Annual Renewal / Authority To Practice',
            'who': 'Registered nurses, midwives, and nurse aides',
            'summary': 'This is the yearly practising licence or ATP pathway and should be tracked with receipt and workplace data.',
        },
        {
            'pathway': 'NC8 Temporary Licence',
            'who': 'Temporary or special-case practice applicants',
            'summary': 'Use for temporary licensing where registrar screening and expiry tracking are required.',
        },
    ]
    default_context = {
        'atp_batch': None,
        'atp_current_year': None,
        'atp_current_record_total': 0,
        'atp_current_person_total': 0,
        'atp_current_png_total': 0,
        'atp_current_overseas_total': 0,
        'atp_current_public_total': 0,
        'atp_current_church_total': 0,
        'atp_current_private_total': 0,
        'atp_current_other_total': 0,
        'frequent_current_nurse_total': 0,
        'frequent_nursing_category_rows': [],
        'frequent_nursing_category_review_total': 0,
        'frequent_nursing_category_review_rows': [],
        'frequent_facility_ownership_rows': [],
        'frequent_pha_facility_total': 0,
        'frequent_private_facility_total': 0,
        'frequent_ngo_facility_total': 0,
        'frequent_review_facility_total': 0,
        'atp_year_rows': [],
        'atp_gender_rows': [],
        'atp_category_rows': [],
        'atp_workplace_rows': [],
        'atp_recent_record_rows': [],
        'atp_year_labels': json.dumps([]),
        'atp_year_values': json.dumps([]),
        'atp_gender_labels': json.dumps([]),
        'atp_gender_values': json.dumps([]),
        'atp_ownership_labels': json.dumps([]),
        'atp_ownership_values': json.dumps([]),
        'atp_category_labels': json.dumps([]),
        'atp_category_values': json.dumps([]),
        'nursing_workflow_rows': configured_workflow_rows or fallback_workflow_rows,
    }

    batch = _latest_atp_batch()
    if not batch:
        return default_context

    cache_key = f"nursing_atp_context_v3:{batch.id}:{batch.completed_at.isoformat() if batch.completed_at else 'pending'}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    practice_rows = list(
        _quality_approved_practicing_records().filter(
            batch=batch,
            record_type='practicing_license',
            target_model__in=ATP_NURSING_TARGET_MODELS,
        ).values(
            'record_year',
            'full_name',
            'registration_no',
            'practitioner_number',
            'gender',
            'category',
            'qualification_name',
            'workplace_address',
            'province',
            'payment_date',
            'renewal_fee',
            'overseas_fee',
            'late_fee',
            'payment_method',
            'nationality',
            'source_sheet_name',
        ).order_by('-record_year', '-payment_date', 'full_name')
    )
    if not practice_rows:
        context = default_context.copy()
        context['atp_batch'] = batch
        cache.set(cache_key, context, 300)
        return context

    current_year = max(row['record_year'] or 0 for row in practice_rows)
    yearly = defaultdict(lambda: {
        'people': set(),
        'records': 0,
        'png_total': 0,
        'overseas_total': 0,
        'late_total': 0,
        'province_set': set(),
    })
    current_people = set()
    current_gender = defaultdict(set)
    current_ownership = defaultdict(set)
    current_categories = defaultdict(set)
    frequent_categories = defaultdict(set)
    category_review = defaultdict(set)
    facility_groups = defaultdict(lambda: {
        'facilities': set(),
        'people': set(),
        'records': 0,
    })
    workplace_map = {}

    for row in practice_rows:
        identity = row['registration_no'] or row['practitioner_number'] or row['full_name']
        year_value = row['record_year'] or current_year
        workplace_name = _clean_facility_name(row['workplace_address'])
        province_label = _normalize_province_label(row['province'])
        if province_label not in PNG_NURSING_PROVINCES:
            province_label = 'Province not captured / review'
        ownership = _workplace_ownership_label(workplace_name)
        yearly_row = yearly[year_value]
        yearly_row['people'].add(identity)
        yearly_row['records'] += 1
        yearly_row['png_total'] += float(row['renewal_fee'] or 0)
        yearly_row['overseas_total'] += float(row['overseas_fee'] or 0)
        yearly_row['late_total'] += float(row['late_fee'] or 0)
        if row['province']:
            yearly_row['province_set'].add(province_label)

        if year_value != current_year:
            continue

        current_people.add(identity)
        gender_label = row['gender'] if row['gender'] in {'Male', 'Female'} else 'Not captured'
        current_gender[gender_label].add(identity)
        current_ownership[ownership].add(identity)
        raw_category = row['category'] or 'Uncategorised'
        current_categories[raw_category].add(identity)
        frequent_category = _frequent_nursing_category_label(raw_category)
        if frequent_category:
            frequent_categories[frequent_category].add(identity)
        else:
            category_review[raw_category].add(identity)
        facility_group_key = _facility_reporting_group(workplace_name, ownership)
        if workplace_name != 'Facility not captured':
            facility_groups[facility_group_key]['facilities'].add(workplace_name)
        facility_groups[facility_group_key]['people'].add(identity)
        facility_groups[facility_group_key]['records'] += 1

        workplace_entry = workplace_map.setdefault(workplace_name, {
            'name': workplace_name,
            'ownership': ownership,
            'records': 0,
            'people': set(),
            'provinces': set(),
            'categories': defaultdict(int),
            'recent_names': [],
        })
        workplace_entry['records'] += 1
        workplace_entry['people'].add(identity)
        workplace_entry['provinces'].add(province_label)
        workplace_entry['categories'][row['category'] or 'Uncategorised'] += 1
        if len(workplace_entry['recent_names']) < 4 and row['full_name'] not in workplace_entry['recent_names']:
            workplace_entry['recent_names'].append(row['full_name'])

    year_rows = []
    for year_value in sorted(yearly.keys(), reverse=True):
        year_rows.append({
            'year': year_value,
            'period_group': _year_band_label(year_value, current_year),
            'record_count': yearly[year_value]['records'],
            'people_count': len(yearly[year_value]['people']),
            'province_count': len(yearly[year_value]['province_set']),
            'png_total': yearly[year_value]['png_total'],
            'overseas_total': yearly[year_value]['overseas_total'],
            'late_total': yearly[year_value]['late_total'],
        })

    gender_order = ['Female', 'Male', 'Not captured']
    gender_rows = [
        {'label': label, 'count': len(current_gender.get(label, set()))}
        for label in gender_order
    ]
    ownership_order = ['Public', 'Church', 'Private', 'Other']
    ownership_rows = [
        {'label': label, 'count': len(current_ownership.get(label, set()))}
        for label in ownership_order
    ]
    category_rows = [
        {'label': label, 'count': len(people)}
        for label, people in sorted(current_categories.items(), key=lambda item: (-len(item[1]), item[0]))[:12]
    ]
    frequent_category_rows = [
        {'label': label, 'count': len(frequent_categories.get(label, set()))}
        for label in FREQUENT_NURSING_CATEGORY_ORDER
    ]
    frequent_category_review_rows = [
        {'label': label, 'count': len(people)}
        for label, people in sorted(category_review.items(), key=lambda item: (-len(item[1]), item[0]))[:12]
    ]
    frequent_category_people = set()
    for people in frequent_categories.values():
        frequent_category_people.update(people)
    frequent_category_review_people = current_people - frequent_category_people
    facility_ownership_rows = []
    for group_key in ['pha', 'private', 'ngo', 'review']:
        group = facility_groups.get(group_key, {})
        facility_ownership_rows.append({
            'key': group_key,
            'label': _facility_reporting_label(group_key),
            'facility_count': len(group.get('facilities', set())),
            'person_count': len(group.get('people', set())),
            'record_count': group.get('records', 0),
        })
    workplace_rows = []
    for row in sorted(workplace_map.values(), key=lambda item: (-len(item['people']), item['name']))[:40]:
        workplace_rows.append({
            'name': row['name'],
            'ownership': row['ownership'],
            'person_count': len(row['people']),
            'record_count': row['records'],
            'provinces': ', '.join(sorted(row['provinces'])) or '-',
            'category_summary': ', '.join(
                f"{name} ({count})"
                for name, count in sorted(row['categories'].items(), key=lambda item: (-item[1], item[0]))[:4]
            ) or '-',
            'recent_names': ', '.join(row['recent_names']) or '-',
        })

    recent_record_rows = []
    for row in practice_rows:
        if row['record_year'] != current_year:
            continue
        province_label = _normalize_province_label(row['province'])
        if province_label not in PNG_NURSING_PROVINCES:
            province_label = 'Province not captured / review'
        recent_record_rows.append({
            'full_name': row['full_name'],
            'gender': row['gender'] or '-',
            'registration_no': row['registration_no'] or '-',
            'practitioner_number': row['practitioner_number'] or '-',
            'category': row['category'] or '-',
            'qualification_name': row['qualification_name'] or '-',
            'workplace_name': _clean_facility_name(row['workplace_address']),
            'ownership': _workplace_ownership_label(_clean_facility_name(row['workplace_address'])),
            'province': province_label,
            'payment_date': row['payment_date'],
            'renewal_fee': row['renewal_fee'],
            'overseas_fee': row['overseas_fee'],
            'late_fee': row['late_fee'],
            'payment_method': row['payment_method'] or '-',
            'source_sheet_name': row['source_sheet_name'],
        })
        if len(recent_record_rows) >= 60:
            break

    context = {
        **default_context,
        'atp_batch': batch,
        'atp_current_year': current_year,
        'atp_current_record_total': sum(1 for row in practice_rows if row['record_year'] == current_year),
        'atp_current_person_total': len(current_people),
        'atp_current_png_total': sum(float(row['renewal_fee'] or 0) for row in practice_rows if row['record_year'] == current_year),
        'atp_current_overseas_total': sum(float(row['overseas_fee'] or 0) for row in practice_rows if row['record_year'] == current_year),
        'atp_current_public_total': len(current_ownership.get('Public', set())),
        'atp_current_church_total': len(current_ownership.get('Church', set())),
        'atp_current_private_total': len(current_ownership.get('Private', set())),
        'atp_current_other_total': len(current_ownership.get('Other', set())),
        'frequent_current_nurse_total': len(current_people),
        'frequent_nursing_category_rows': frequent_category_rows,
        'frequent_nursing_category_review_total': len(frequent_category_review_people),
        'frequent_nursing_category_review_rows': frequent_category_review_rows,
        'frequent_facility_ownership_rows': facility_ownership_rows,
        'frequent_pha_facility_total': next((row['facility_count'] for row in facility_ownership_rows if row['key'] == 'pha'), 0),
        'frequent_private_facility_total': next((row['facility_count'] for row in facility_ownership_rows if row['key'] == 'private'), 0),
        'frequent_ngo_facility_total': next((row['facility_count'] for row in facility_ownership_rows if row['key'] == 'ngo'), 0),
        'frequent_review_facility_total': next((row['facility_count'] for row in facility_ownership_rows if row['key'] == 'review'), 0),
        'atp_year_rows': year_rows,
        'atp_gender_rows': gender_rows,
        'atp_category_rows': category_rows,
        'atp_workplace_rows': workplace_rows,
        'atp_recent_record_rows': recent_record_rows,
        'atp_year_labels': json.dumps([row['year'] for row in reversed(year_rows)]),
        'atp_year_values': json.dumps([row['people_count'] for row in reversed(year_rows)]),
        'atp_gender_labels': json.dumps([row['label'] for row in gender_rows]),
        'atp_gender_values': json.dumps([row['count'] for row in gender_rows]),
        'atp_ownership_labels': json.dumps([row['label'] for row in ownership_rows]),
        'atp_ownership_values': json.dumps([row['count'] for row in ownership_rows]),
        'atp_category_labels': json.dumps([row['label'] for row in category_rows]),
        'atp_category_values': json.dumps([row['count'] for row in category_rows]),
    }
    cache.set(cache_key, context, 300)
    return context


def _import_batch_context(scope='nursing'):
    scope_key = scope if scope in {'medical', 'nursing'} else 'nursing'
    latest_batch = _latest_import_batch_for_scope(scope_key)
    cache_key = (
        "import_batch_context_v5:"
        f"{scope_key}:"
        f"{latest_batch.id if latest_batch else 'none'}:"
        f"{latest_batch.completed_at.isoformat() if latest_batch and latest_batch.completed_at else 'pending'}"
    )
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    recent_batches = list(DataImportBatch.objects.filter(
        source_kind__in=_import_source_kinds_for_scope(scope_key)
    ).order_by('-started_at')[:5])
    context = {
        'latest_import_batch': latest_batch,
        'recent_import_batches': recent_batches,
        'latest_import_sheets': [],
        'import_record_count': 0,
        'category_labels': [],
        'category_values': [],
        'province_labels': [],
        'province_values': [],
        'import_years': [],
        'import_year_counts': [],
        'import_gender_labels': [],
        'import_gender_values': [],
        'import_applicant_type_labels': [],
        'import_applicant_type_values': [],
        'import_workplace_rows': [],
        'import_sheet_rows': [],
        'import_record_type_labels': [],
        'import_record_type_values': [],
        'recent_import_batches_info': [],
        'latest_import_progress': 0,
        'import_latest_year': None,
        'import_province_source_batch': None,
        'import_gender_source_batch': None,
        'import_workplace_source_batch': None,
    }
    for batch in recent_batches:
        total_steps = batch.total_rows or batch.total_sheets or 0
        completed_steps = batch.processed_rows or batch.processed_sheets or 0
        progress = 100 if batch.status == 'completed' else int((completed_steps / total_steps) * 100) if total_steps else 0
        context['recent_import_batches_info'].append({
            'batch': batch,
            'progress': max(0, min(progress, 100)),
        })
    if not latest_batch:
        cache.set(cache_key, context, DASHBOARD_CACHE_TIMEOUT_SECONDS)
        return context

    latest_sheets = list(latest_batch.sheets.order_by('sheet_name')[:20])
    target_models = _import_target_models_for_scope(scope_key)
    records = list(
        _quality_approved_practicing_records().filter(batch=latest_batch, target_model__in=target_models)
        .order_by('source_sheet_name', 'source_row')
        .values(
            'registration_no',
            'practitioner_number',
            'full_name',
            'record_year',
            'category',
            'applicant_type',
            'record_type',
            'province',
            'gender',
            'workplace_address',
        )
    )
    context['latest_import_sheets'] = latest_sheets
    context['import_record_count'] = len(records)

    def records_for_field(field_name):
        if any(record.get(field_name) for record in records):
            return records, latest_batch
        fallback_batch = _latest_import_batch_with(field_name, scope_key)
        if not fallback_batch:
            return records, latest_batch
        return (
            list(
                _quality_approved_practicing_records().filter(batch=fallback_batch, target_model__in=target_models)
                .order_by('source_sheet_name', 'source_row')
                .values(
                    'registration_no',
                    'practitioner_number',
                    'full_name',
                    'record_year',
                    'category',
                    'applicant_type',
                    'record_type',
                    'province',
                    'gender',
                    'workplace_address',
                )
            ),
            fallback_batch,
        )

    province_records, province_source_batch = records_for_field('province')
    gender_records, gender_source_batch = records_for_field('gender')
    workplace_records, workplace_source_batch = records_for_field('workplace_address')
    context['import_province_source_batch'] = province_source_batch
    context['import_gender_source_batch'] = gender_source_batch
    context['import_workplace_source_batch'] = workplace_source_batch

    year_sets = {}
    category_counts = {}
    province_counts = {}
    gender_counts = {}
    applicant_type_counts = {}
    workplace_counts = {}
    record_type_counts = {}
    record_type_labels = dict(PracticingLicenseRecord.RECORD_TYPE_CHOICES)

    current_year = date.today().year
    for record in records:
        person_key = record['registration_no'] or record['practitioner_number'] or record['full_name']
        if record['record_year'] and 1900 <= record['record_year'] <= current_year:
            year_sets.setdefault(record['record_year'], set()).add(person_key)
        if record['category']:
            category_counts[record['category']] = category_counts.get(record['category'], 0) + 1

        if record['applicant_type']:
            applicant_type = record['applicant_type'].title()
            applicant_type_counts[applicant_type] = applicant_type_counts.get(applicant_type, 0) + 1

        record_type_label = record_type_labels.get(record['record_type'], record['record_type'])
        record_type_counts[record_type_label] = record_type_counts.get(record_type_label, 0) + 1

    for record in province_records:
        if record['province']:
            province_label = _normalize_province_label(record['province'])
            province_counts[province_label] = province_counts.get(province_label, 0) + 1

    for record in gender_records:
        if record['gender']:
            gender_label = _normalize_gender_label(record['gender'])
            gender_counts[gender_label] = gender_counts.get(gender_label, 0) + 1

    for record in workplace_records:
        if record['workplace_address']:
            workplace_counts[record['workplace_address']] = workplace_counts.get(record['workplace_address'], 0) + 1

    sorted_years = sorted(year_sets.keys())
    context['import_years'] = sorted_years
    context['import_year_counts'] = [len(year_sets[year]) for year in sorted_years]
    context['import_latest_year'] = sorted_years[-1] if sorted_years else None

    top_categories = sorted(category_counts.items(), key=lambda item: item[1], reverse=True)[:8]
    context['category_labels'] = [label for label, _ in top_categories]
    context['category_values'] = [value for _, value in top_categories]

    top_provinces = sorted(province_counts.items(), key=lambda item: item[1], reverse=True)[:10]
    context['province_labels'] = [label for label, _ in top_provinces]
    context['province_values'] = [value for _, value in top_provinces]

    context['import_gender_labels'] = list(gender_counts.keys())
    context['import_gender_values'] = list(gender_counts.values())
    context['import_applicant_type_labels'] = list(applicant_type_counts.keys())
    context['import_applicant_type_values'] = list(applicant_type_counts.values())

    top_workplaces = sorted(workplace_counts.items(), key=lambda item: item[1], reverse=True)[:15]
    context['import_workplace_rows'] = [
        {'workplace': workplace, 'count': count}
        for workplace, count in top_workplaces
    ]
    context['import_sheet_rows'] = latest_sheets
    top_record_types = sorted(record_type_counts.items(), key=lambda item: item[1], reverse=True)
    context['import_record_type_labels'] = [label for label, _ in top_record_types]
    context['import_record_type_values'] = [value for _, value in top_record_types]
    context['latest_import_progress'] = 100
    cache.set(cache_key, context, DASHBOARD_CACHE_TIMEOUT_SECONDS)
    return context


def _current_workforce_context(include_facility_workers=False, facility_target_models=None, scope=None):
    snapshots = list(WorkforceSnapshot.objects.order_by('year'))
    import_scope = scope if scope in {'medical', 'nursing'} else 'nursing'
    import_context = _import_batch_context(import_scope)
    reference_breakdown = build_reference_breakdown()
    cadre_queryset = _cadre_queryset_for_scope(scope)
    institution_queryset = _training_institution_queryset_for_scope(scope)
    if include_facility_workers:
        if facility_target_models is None and scope in {'medical', 'nursing'}:
            facility_target_models = _import_target_models_for_scope(scope)
        imported_workplace_context = _imported_facility_worker_context(
            import_context.get('latest_import_batch'),
            target_models=facility_target_models,
        )
    else:
        imported_workplace_context = {
            'imported_facility_workers': [],
            'imported_facility_count': 0,
            'imported_facility_worker_count': 0,
            'imported_workplace_reference_count': 0,
            'imported_workplace_worker_count': 0,
        }
    today = date.today()

    def get_age(dob):
        if not dob:
            return None
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

    if scope == 'medical':
        age_models = [MedicalDoctor, CommunityHealthWorker]
    else:
        age_models = [NursingProfessional, Midwife, NurseAide]
    nurse_birth_dates = []
    for model in age_models:
        nurse_birth_dates.extend(
            model.objects.filter(is_active=True).values_list('date_of_birth', flat=True)
        )
    nurse_ages = [age for age in (get_age(date_of_birth) for date_of_birth in nurse_birth_dates) if age is not None]
    if not nurse_ages and import_context['latest_import_batch']:
        imported_age_records = _quality_approved_practicing_records().filter(
            batch=import_context['latest_import_batch'],
            target_model__in=_import_target_models_for_scope(import_scope),
            date_of_birth__isnull=False,
        )
        nurse_ages = [
            today.year - record.date_of_birth.year - ((today.month, today.day) < (record.date_of_birth.month, record.date_of_birth.day))
            for record in imported_age_records
        ]

    students_by_institution = defaultdict(list)
    for student in HealthStudent.objects.select_related('institution').order_by(
        'institution__name',
        'last_name',
        'first_name',
    ):
        if student.institution:
            students_by_institution[student.institution].append(student)
    graduand_by_institution = [
        {
            'institution': institution,
            'students': graduands,
            'graduands': graduands,
            'count': len(graduands),
        }
        for institution, graduands in sorted(
            students_by_institution.items(),
            key=lambda item: item[0].name,
        )
    ]

    national_workers_table = []
    overseas_workers_table = []
    for model, label in [
        (NursingProfessional, 'Nursing'),
        (MedicalDoctor, 'Medical'),
        (Midwife, 'Midwife'),
        (CommunityHealthWorker, 'CHW'),
        (NurseAide, 'Nurse Aide'),
        (HealthStudent, 'Graduand'),
    ]:
        for applicant_type, target_table in [
            ('national', national_workers_table),
            ('overseas', overseas_workers_table),
        ]:
            for obj in model.objects.filter(applicant_type=applicant_type).order_by('last_name', 'first_name').values(
                'first_name',
                'last_name',
                'registration_no',
                'applicant_type',
            )[:PROFESSIONAL_PREVIEW_LIMIT]:
                target_table.append({
                    'name': f"{obj['first_name']} {obj['last_name']}",
                    'type': label,
                    'registration_no': obj['registration_no'],
                    'applicant_type': obj['applicant_type'],
                })

    workers_by_facility = []
    for facility in Facility.objects.select_related('location').order_by('name'):
        postings = list(
            PostingHistory.objects.filter(facility=facility, is_current=True)
            .select_related('content_type')
            .order_by('position_title', 'start_date')
        )
        workers_by_facility.append({
            'facility': facility,
            'postings': postings,
            'count': len(postings),
        })

    receipt_queryset = _receipt_queryset_for_scope(scope)
    completed_receipts = receipt_queryset.filter(status='completed')
    graduand_register_count = HealthStudent.objects.count()
    provisional_form_codes = ['NC1', 'NC4', 'G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G7']
    provisional_applicant_count = Application.objects.filter(form_code__in=provisional_form_codes).count()
    years = [s.year for s in snapshots]
    total_workers_by_year = [s.total_active_workers for s in snapshots]
    if import_context['import_years']:
        years = import_context['import_years']
        total_workers_by_year = import_context['import_year_counts']

    if scope == 'medical':
        medical_allied_count = _medical_allied_count()
        live_workforce_total = MedicalDoctor.objects.count() + CommunityHealthWorker.objects.count() + medical_allied_count
        flow_labels = ['Medical Doctors', 'Community Health Workers', 'Allied Health', 'Pending Renewals']
        flow_data = [
            MedicalDoctor.objects.count(),
            CommunityHealthWorker.objects.count(),
            medical_allied_count,
            Application.objects.filter(form_code__in=['MD2', 'MBRN'], status='pending').count(),
        ]
        workforce_flow_title = 'Medical Board Workforce Flow & Planning'
        import_record_label = 'Imported Medical Board Rows'
        import_workplace_heading = 'Top Workplaces From Latest Medical Board Workbook'
        if not import_context['import_years']:
            years = [today.year]
            total_workers_by_year = [live_workforce_total]
    else:
        live_workforce_total = (
            NursingProfessional.objects.count()
            + Midwife.objects.count()
            + NurseAide.objects.count()
            + HealthStudent.objects.count()
        )
        flow_labels = ['Incoming Graduands', 'New Graduates', 'Nearing Retirement', 'Young Workforce']
        flow_data = [
            HealthStudent.objects.filter(is_graduate=False).count(),
            Application.objects.filter(form_code__in=['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G7'], status='approved').count(),
            sum(1 for age in nurse_ages if age >= 55),
            sum(1 for age in nurse_ages if age <= 35),
        ]
        workforce_flow_title = 'Nursing Council Workforce Flow & Planning' if scope == 'nursing' else 'Workforce Flow & Planning'
        import_record_label = 'Imported Workbook Rows'
        import_workplace_heading = 'Top Workplaces From Latest Workplace Workbook'

    tracked_workforce_count = total_workers_by_year[-1] if total_workers_by_year else live_workforce_total
    incoming_graduands_count = 0 if scope == 'medical' else HealthStudent.objects.filter(is_graduate=False).count()
    graduates_entering_count = (
        Application.objects.filter(form_code__in=['MD1', 'CHW1', 'MBSP'], status='approved').count()
        if scope == 'medical'
        else Application.objects.filter(form_code__in=['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G7'], status='approved').count()
    )

    context = {
        'workforce_flow_title': workforce_flow_title,
        'import_record_label': import_record_label,
        'import_workplace_heading': import_workplace_heading,
        'tracked_workforce_count': tracked_workforce_count,
        'years': years,
        'total_workers_by_year': total_workers_by_year,
        'new_graduates_by_year': [s.new_graduates_joined for s in snapshots],
        'retirements_by_year': [s.retirements for s in snapshots],
        'latest_snapshot': snapshots[-1] if snapshots else None,
        'medical_count': MedicalDoctor.objects.count(),
        'nursing_count': NursingProfessional.objects.count(),
        'midwife_count': Midwife.objects.count(),
        'allied_count': _medical_allied_count() if scope == 'medical' else 0,
        'chw_count': CommunityHealthWorker.objects.count(),
        'nurse_aide_count': NurseAide.objects.count(),
        'graduand_count': provisional_applicant_count or graduand_register_count,
        'provisional_applicant_count': provisional_applicant_count,
        'graduand_register_count': graduand_register_count,
        'student_count': graduand_register_count,
        'facility_count': Facility.objects.count(),
        'verified_facility_count': Facility.objects.count(),
        'institution_count': institution_queryset.count() if scope == 'medical' else reference_breakdown['png_nursing_school_count'],
        'cadres': cadre_queryset,
        'facilities': Facility.objects.select_related('location').order_by('name'),
        'institutions': institution_queryset,
        'document_types': _document_types_for_scope(scope),
        'locations': Location.objects.order_by('province', 'district'),
        'duplicate_count': 0,
        'qualification_count': 0,
        'cpd_count': 0,
        'disciplinary_count': 0,
        'registration_count': (
            MedicalDoctor.objects.count()
            + NursingProfessional.objects.count()
            + Midwife.objects.count()
            + CommunityHealthWorker.objects.count()
            + NurseAide.objects.count()
        ),
        'application_count': Application.objects.filter(status='pending').count(),
        'approved_applications': Application.objects.filter(status='approved').count(),
        'rejected_applications': Application.objects.filter(status='rejected').count(),
        'posting_count': PostingHistory.objects.filter(is_current=True).count(),
        'document_type_count': _document_types_for_scope(scope).count(),
        'document_count': 0,
        'receipt_pending_count': receipt_queryset.filter(status='pending').count(),
        'receipt_completed_count': completed_receipts.count(),
        'receipt_failed_count': receipt_queryset.filter(status='failed').count(),
        'receipt_total_amount': completed_receipts.aggregate(total=Sum('amount'))['total'] or 0,
        'receipt_count': receipt_queryset.count(),
        'age_groups': ['Under 30', '30-40', '41-50', '51-55', '56+'],
        'age_counts': [
            sum(1 for age in nurse_ages if age < 30),
            sum(1 for age in nurse_ages if 30 <= age <= 40),
            sum(1 for age in nurse_ages if 41 <= age <= 50),
            sum(1 for age in nurse_ages if 51 <= age <= 55),
            sum(1 for age in nurse_ages if age > 55),
        ],
        'flow_labels': flow_labels,
        'flow_data': flow_data,
        'nurses_total': len(nurse_birth_dates),
        'nearing_retirement': sum(1 for age in nurse_ages if age >= 55),
        'young_workers': sum(1 for age in nurse_ages if age <= 35),
        'incoming_graduands': incoming_graduands_count,
        'incoming_students': incoming_graduands_count,
        'graduates_entering': graduates_entering_count,
        'graduand_by_institution': graduand_by_institution,
        'student_by_institution': graduand_by_institution,
        'national_workers_table': national_workers_table,
        'overseas_workers_table': overseas_workers_table,
        'workers_by_facility': workers_by_facility,
        'facility_reference_rows': imported_workplace_context['imported_facility_workers'],
        'recent_sync': None,
        'reference_breakdown': reference_breakdown,
    }
    context.update(import_context)
    context.update(imported_workplace_context)
    if import_context['latest_import_batch']:
        latest_batch_records = _quality_approved_practicing_records().filter(
            batch=import_context['latest_import_batch'],
            target_model__in=_import_target_models_for_scope(import_scope),
        )
        if scope == 'medical':
            doctor_records = latest_batch_records.filter(
                target_model='medicaldoctor',
                record_type__in=['full', 'workforce_listing'],
            )
            chw_records = latest_batch_records.filter(
                target_model='communityhealthworker',
                record_type__in=['full', 'workforce_listing'],
            )
            allied_records = latest_batch_records.filter(
                target_model='other',
                record_type__in=['full', 'workforce_listing'],
            )
            license_records = latest_batch_records.filter(record_type='practicing_license')
            context['flow_labels'] = ['Medical Doctors', 'Community Health Workers', 'Allied Health', 'Practising Licences']
            context['flow_data'] = [
                _identity_count(doctor_records),
                _identity_count(chw_records),
                _identity_count(allied_records),
                _identity_count(license_records),
            ]
        else:
            context['incoming_graduands'] = latest_batch_records.filter(record_type='provisional').count()
            context['graduates_entering'] = latest_batch_records.filter(record_type__in=['full', 'temporary']).count()
            context['flow_labels'] = ['Provisional', 'Full/Temporary', 'Renewals', 'Young Workforce']
            context['flow_data'] = [
                latest_batch_records.filter(record_type='provisional').count(),
                latest_batch_records.filter(record_type__in=['full', 'temporary']).count(),
                latest_batch_records.filter(record_type='practicing_license').count(),
                sum(1 for age in nurse_ages if age <= 35),
            ]
    return context


def _apply_nursing_overview_scope(context):
    context['dashboard_scope'] = 'nursing'
    context['medical_count'] = 0
    context['chw_count'] = 0
    context['allied_count'] = 0
    context['registration_count'] = (
        context.get('nursing_count', 0)
        + context.get('midwife_count', 0)
        + context.get('nurse_aide_count', 0)
    )
    context['application_count'] = Application.objects.filter(status='pending', form_code__in=NURSING_FORM_CODES).count()
    context['approved_applications'] = Application.objects.filter(status='approved', form_code__in=NURSING_FORM_CODES).count()
    context['rejected_applications'] = Application.objects.filter(status='rejected', form_code__in=NURSING_FORM_CODES).count()
    context['national_workers_table'] = [
        row for row in context.get('national_workers_table', [])
        if row.get('type') in {'Nursing', 'Midwife', 'Nurse Aide', 'Graduand'}
    ]
    context['overseas_workers_table'] = [
        row for row in context.get('overseas_workers_table', [])
        if row.get('type') in {'Nursing', 'Midwife', 'Nurse Aide', 'Graduand'}
    ]
    return context


def _medical_board_context():
    doctor_ct = ContentType.objects.get_for_model(MedicalDoctor)
    chw_ct = ContentType.objects.get_for_model(CommunityHealthWorker)
    facility_ct = ContentType.objects.get_for_model(Facility)
    medical_form_codes = ['MD1', 'MD2', 'CHW1', 'MBSP', 'MBRN', 'MBAC', 'MBPF', 'MBTC']
    recent_applications = (
        Application.objects.filter(form_code__in=medical_form_codes)
        .select_related('content_type')
        .order_by('-submitted_date')[:15]
    )
    doctors = list(MedicalDoctor.objects.order_by('last_name', 'first_name'))
    chws = list(CommunityHealthWorker.objects.order_by('last_name', 'first_name'))

    chw_province_counts = {}
    for chw in chws:
        label = _normalize_province_label(chw.province)
        chw_province_counts[label] = chw_province_counts.get(label, 0) + 1

    latest_medical_import = DataImportBatch.objects.filter(
        source_kind='medical_board_workbook',
        status='completed',
    ).order_by('-started_at').first()
    latest_import_sheets = latest_medical_import.sheets.all()[:8] if latest_medical_import else []

    current_year = date.today().year
    medical_records = _quality_approved_practicing_records().filter(
        batch__source_kind__in=MEDICAL_IMPORT_SOURCE_KINDS,
        target_model__in=['medicaldoctor', 'communityhealthworker', 'other'],
        record_year__isnull=False,
        record_year__lte=current_year,
    )
    specialist_records = medical_records.filter(target_model='medicaldoctor').filter(_specialist_record_filter())
    specialist_profile_count = sum(1 for doctor in doctors if _is_specialist_profile_value(doctor.specialty))
    specialist_import_count = _identity_count(specialist_records)
    specialty_counts = defaultdict(int)
    for doctor in doctors:
        if _is_specialist_profile_value(doctor.specialty):
            specialty_counts[_specialist_profile_label(doctor.specialty)] += 1
    seen_specialist_identities = set()
    for record in specialist_records:
        identity = _record_identity(record)
        if not identity:
            continue
        if identity in seen_specialist_identities:
            continue
        seen_specialist_identities.add(identity)
        label = _specialist_profile_label(record.category)
        if not _is_specialist_profile_value(label):
            label = record.qualification_name or record.category or "Unclassified specialist"
        specialty_counts[label[:80]] += 1
    if not specialty_counts:
        specialty_counts = {'No specialist data loaded': 0}

    yearly_sets = defaultdict(lambda: {
        'doctor_registration': set(),
        'doctor_practicing': set(),
        'chw_registration': set(),
        'chw_practicing': set(),
    })
    for record in medical_records:
        identity = _record_identity(record)
        if not identity:
            continue
        if record.target_model == 'medicaldoctor' and record.record_type in {'full', 'workforce_listing'}:
            yearly_sets[record.record_year]['doctor_registration'].add(identity)
        elif record.target_model == 'medicaldoctor' and record.record_type == 'practicing_license':
            yearly_sets[record.record_year]['doctor_practicing'].add(identity)
        elif record.target_model == 'communityhealthworker' and record.record_type in {'full', 'workforce_listing'}:
            yearly_sets[record.record_year]['chw_registration'].add(identity)
        elif record.target_model == 'communityhealthworker' and record.record_type == 'practicing_license':
            yearly_sets[record.record_year]['chw_practicing'].add(identity)

    medical_yearly_rows = []
    for year_value in sorted(yearly_sets.keys(), reverse=True):
        row_sets = yearly_sets[year_value]
        medical_yearly_rows.append({
            'year': year_value,
            'doctor_registration_count': len(row_sets['doctor_registration']),
            'doctor_practicing_count': len(row_sets['doctor_practicing']),
            'chw_registration_count': len(row_sets['chw_registration']),
            'chw_practicing_count': len(row_sets['chw_practicing']),
        })

    chart_rows = list(reversed(medical_yearly_rows[:18]))
    year_counts = {
        row['year']: row['chw_registration_count'] + row['chw_practicing_count']
        for row in medical_yearly_rows
    }

    medical_registration_records = (
        medical_records.filter(record_type__in=['full', 'workforce_listing', 'practicing_license'])
        .order_by('-record_year', '-issued_date', '-payment_date', 'full_name')[:60]
    )

    doctor_registration_total = len({
        _record_identity(record)
        for record in medical_records.filter(target_model='medicaldoctor', record_type__in=['full', 'workforce_listing'])
        if _record_identity(record)
    })
    doctor_practicing_total = len({
        _record_identity(record)
        for record in medical_records.filter(target_model='medicaldoctor', record_type='practicing_license')
        if _record_identity(record)
    })
    chw_registration_record_total = len({
        _record_identity(record)
        for record in medical_records.filter(target_model='communityhealthworker', record_type__in=['full', 'workforce_listing'])
        if _record_identity(record)
    })
    chw_registration_total = len(chws) or chw_registration_record_total
    chw_practicing_total = len({
        _record_identity(record)
        for record in medical_records.filter(target_model='communityhealthworker', record_type='practicing_license')
        if _record_identity(record)
    })

    medical_record_review_ids = list(
        medical_records.values_list('id', flat=True)[:50000]
    )
    medical_missing_reviews = MissingDataReview.objects.filter(
        Q(content_type=doctor_ct)
        | Q(content_type=chw_ct)
        | Q(
            content_type=ContentType.objects.get_for_model(PracticingLicenseRecord),
            object_id__in=medical_record_review_ids,
        )
    ).exclude(status='resolved')

    expiring_licenses = []
    today = date.today()
    for doctor in MedicalDoctor.objects.filter(license_expiry_date__isnull=False).order_by('license_expiry_date')[:10]:
        days_left = (doctor.license_expiry_date - today).days
        expiring_licenses.append({
            'name': str(doctor),
            'specialty': doctor.specialty or 'General Practice',
            'expires': doctor.license_expiry_date,
            'days_left': days_left,
        })

    medical_facility_forms = Application.objects.filter(content_type=facility_ct, form_code__in=['MBAC', 'MBPF', 'MBTC'])
    quality_context = _data_quality_review_context(medical_missing_reviews, limit=20, scope_key="medical")
    return {
        'recent_applications': recent_applications,
        'pending_applications': Application.objects.filter(form_code__in=medical_form_codes, status='pending').count(),
        'renewals_pending': Application.objects.filter(form_code__in=['MD2', 'MBRN'], status='pending').count(),
        'facilities_count': Facility.objects.count(),
        'medical_doctor_count': len(doctors),
        'medical_specialist_count': max(specialist_profile_count, specialist_import_count),
        'medical_chw_count': len(chws),
        'medical_allied_count': _medical_allied_count(),
        'medical_facility_application_count': medical_facility_forms.count(),
        'medical_specialty_labels': list(specialty_counts.keys())[:8],
        'medical_specialty_values': list(specialty_counts.values())[:8],
        'chw_province_labels': list(chw_province_counts.keys())[:10],
        'chw_province_values': list(chw_province_counts.values())[:10],
        'chw_year_labels': list(year_counts.keys())[-12:],
        'chw_year_values': list(year_counts.values())[-12:],
        'medical_yearly_rows': medical_yearly_rows,
        'medical_registration_records': medical_registration_records,
        'medical_doctor_registration_total': doctor_registration_total,
        'medical_doctor_practicing_total': doctor_practicing_total,
        'medical_chw_registration_total': chw_registration_total,
        'medical_chw_practicing_total': chw_practicing_total,
        'medical_flow_year_labels': json.dumps([row['year'] for row in chart_rows]),
        'medical_flow_doctor_values': json.dumps([row['doctor_registration_count'] for row in chart_rows]),
        'medical_flow_chw_values': json.dumps([row['chw_registration_count'] for row in chart_rows]),
        'medical_flow_practicing_values': json.dumps([
            row['doctor_practicing_count'] + row['chw_practicing_count']
            for row in chart_rows
        ]),
        **quality_context,
        'expiring_medical_licenses': expiring_licenses,
        'medical_registration_count': Application.objects.filter(form_code__in=['MD1', 'CHW1', 'MBSP']).count(),
        'medical_renewal_count': Application.objects.filter(form_code__in=['MD2', 'MBRN']).count(),
        'latest_medical_import': latest_medical_import,
        'latest_medical_import_sheets': latest_import_sheets,
        'medical_board_forms': [
            {'code': 'CHW1', 'title': 'CHW Registration', 'url': 'medical_board_form_register'},
            {'code': 'MBRN', 'title': 'Renewal Registration', 'url': 'medical_board_form_register'},
            {'code': 'MBSP', 'title': 'Specialist Application', 'url': 'medical_board_form_register'},
            {'code': 'MBAC', 'title': 'Facility Accreditation', 'url': 'medical_board_form_register'},
            {'code': 'MBPF', 'title': 'Private Facility Checklist', 'url': 'medical_board_form_register'},
            {'code': 'MBTC', 'title': 'Training College Facility', 'url': 'medical_board_form_register'},
        ],
    }


@login_required
def viewer_dashboard(request):
    role = request.user.role
    profile = " ".join(
        str(value or "")
        for value in [
            request.user.department,
            request.user.username,
            request.user.first_name,
            request.user.last_name,
        ]
    ).lower()
    if role == "reviewer":
        if is_finance_reviewer(request.user):
            available_dashboards = [
                {'label': 'Financial Forecast', 'url': 'financial_forecast_dashboard', 'description': 'Open separate Nursing Council and Medical Board finance views.'},
                {'label': 'Workforce Flow', 'url': 'workforce_flow', 'description': 'View high-level workforce movement without CRUD tools.'},
            ]
            role_note = "Finance Officers have read-only access to Workforce Flow and separated Financial Forecast views. CRUD and operational tools require Registrar/System Admin approval."
        elif is_data_quality_reviewer(request.user):
            available_dashboards = [
                {'label': 'Duplicate Review Workflow', 'url': 'duplicate_review_workflow', 'description': 'Clean duplicate and suspicious records.'},
                {'label': 'Records Hub', 'url': 'records_home', 'description': 'Open records for data correction.'},
                {'label': 'Staff AI Assistant', 'url': 'staff_ai_assistant', 'description': 'Ask data-quality questions.'},
            ]
            role_note = "Data Quality Officers review duplicate, missing, and suspicious source-data issues before reports are trusted."
        elif is_medical_board_staff(request.user):
            available_dashboards = [
                {'label': 'Medical Board Portal', 'url': 'medical_board_portal', 'description': 'Review Medical Board applications and workforce data.'},
                {'label': 'Workforce Flow', 'url': 'workforce_flow', 'description': 'View medical workforce planning flow.'},
                {'label': 'Staff AI Assistant', 'url': 'staff_ai_assistant', 'description': 'Ask Medical Board workflow questions.'},
            ]
            role_note = "Medical Reviewers check Medical Board applications, documents, and data quality before registrar decision."
        elif is_nursing_council_staff(request.user):
            available_dashboards = [
                {'label': 'Nursing Council Portal', 'url': 'nursing_council_portal', 'description': 'Review Nursing Council applications and operational data.'},
                {'label': 'Workforce Flow', 'url': 'workforce_flow', 'description': 'View Nursing Council workforce planning flow.'},
                {'label': 'Staff AI Assistant', 'url': 'staff_ai_assistant', 'description': 'Ask Nursing Council workflow questions.'},
            ]
            role_note = "Nursing Reviewers check Nursing Council applications, documents, and data quality before registrar decision."
        else:
            available_dashboards = []
            role_note = "Reviewer access is active, but this account has no office assignment yet."
    else:
        available_dashboards = [
            {'label': 'Registry Search Help', 'url': 'dashboard_search', 'description': 'Search public-facing registration help.'},
            {'label': 'Fee Structure & Guidelines', 'url': 'fee_structure', 'description': 'Review current application fees and guidance.'},
            {'label': 'Messages & Enquiries', 'url': 'enquiry_inbox', 'description': 'Send or review enquiries.'},
            {'label': 'My Profile', 'url': 'user_profile', 'description': 'View or update your own account information.'},
        ]
        role_note = "Viewer access is read-only and is used for safe help, enquiry, and profile access."
    context = {
        'role': role,
        'full_name': request.user.get_full_name() or request.user.username,
        'available_dashboards': available_dashboards,
        'role_note': role_note,
    }
    return render(request, 'dashboard/viewer_dashboard.html', context)

@login_required
@user_passes_test(_role_in('admin', 'registrar'))
def admin_dashboard(request):
    missing_queryset = MissingDataReview.objects.exclude(status='resolved')
    context = {
        'total_users': User.objects.count(),
        'pending_applications': Application.objects.filter(status='pending').count(),
        'recent_notifications': [],
    }
    context.update(_data_quality_review_context(missing_queryset, limit=15, scope_key="admin"))
    context.update(_current_workforce_context(include_facility_workers=True))
    return render(request, 'dashboard/admin_dashboard.html', context)


@login_required
@user_passes_test(_role_in('admin', 'registrar'))
def registrar_dashboard(request):
    portal_target = _staff_portal_target(request.user)
    if getattr(request.user, 'role', '') != 'admin' and portal_target:
        return redirect(portal_target)

    is_nursing_registrar = is_nursing_council_user(request.user) and not is_medical_board_user(request.user)
    is_medical_registrar = is_medical_board_user(request.user) and request.user.role != 'admin'
    pending_queryset = Application.objects.filter(status='pending').select_related('content_type')
    if is_nursing_registrar:
        pending_queryset = pending_queryset.filter(
            form_code__in=['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G7', 'NC1', 'NC2', 'NC3', 'NC4', 'NC5', 'NC6', 'NC7', 'NC8', 'NC9', 'NC10', 'NC11']
        )
    elif is_medical_registrar:
        pending_queryset = pending_queryset.filter(form_code__in=['MD1', 'MD2', 'CHW1', 'MBSP', 'MBRN', 'MBAC', 'MBPF', 'MBTC'])
    pending_applications = pending_queryset.order_by('-submitted_date')[:25]
    recent_approvals = Application.objects.filter(status='approved').select_related('content_type').order_by('-approved_date')[:10]
    expiring_licenses = []

    if not is_medical_registrar:
        for nurse in NursingProfessional.objects.filter(license_expiry_date__isnull=False).order_by('license_expiry_date')[:10]:
            expiring_licenses.append({
                'name': str(nurse),
                'license_type': 'Nursing',
                'expires': nurse.license_expiry_date,
            })

    if not is_nursing_registrar:
        for doctor in MedicalDoctor.objects.filter(license_expiry_date__isnull=False).order_by('license_expiry_date')[:10]:
            expiring_licenses.append({
                'name': str(doctor),
                'license_type': 'Medical',
                'expires': doctor.license_expiry_date,
            })

    expiring_licenses = sorted(expiring_licenses, key=lambda item: item['expires'])[:10]
    missing_queryset = MissingDataReview.objects.exclude(status='resolved')
    if is_nursing_registrar:
        missing_queryset = missing_queryset.filter(
            professional_type__in=['Nursing Professional', 'Midwife', 'Graduand', 'Nurse Aide', 'Practicing License Record']
        )
    elif is_medical_registrar:
        missing_queryset = missing_queryset.filter(
            professional_type__in=['Medical Doctor', 'Community Health Worker', 'Practicing License Record']
        )

    context = {
        'pending_reviews': pending_queryset.count(),
        'pending_applications': pending_applications,
        'recent_approvals': recent_approvals,
        'expiring_licenses': expiring_licenses,
    }
    context.update(_data_quality_review_context(
        missing_queryset,
        limit=15,
        scope_key="registrar_nursing" if is_nursing_registrar else "registrar_medical" if is_medical_registrar else "registrar_all",
    ))
    facility_target_models = None
    if request.user.role != 'admin':
        if is_nursing_registrar:
            facility_target_models = ['nursingprofessional', 'midwife', 'nurseaide', 'healthstudent']
        elif is_medical_registrar:
            facility_target_models = ['medicaldoctor', 'communityhealthworker']
    context.update(_current_workforce_context(include_facility_workers=True, facility_target_models=facility_target_models))
    if getattr(request.user, 'role', '') == 'admin' or is_nursing_registrar:
        context.update(_nursing_atp_context())
    context.update(_registrar_worker_origin_context(request.user))
    return render(request, 'dashboard/registrar_dashboard.html', context)


@login_required
@user_passes_test(_role_in('admin', 'registrar'))
def registrar_individual_records(request):
    target = 'registrar_dashboard'
    if getattr(request.user, 'role', '') != 'admin':
        target = _staff_portal_target(request.user) or target
    return redirect(f"{reverse(target)}#registrar-worker-origin-table")


@login_required
@user_passes_test(_role_in('admin', 'registrar', 'reviewer'))
def data_quality_reviews_table(request):
    requested_scope = request.GET.get("scope")
    queryset = _data_quality_review_queryset_for_user(request.user, requested_scope)
    records_total = queryset.count()
    queryset = _annotated_data_quality_review_queryset(queryset)

    search_value = " ".join((request.GET.get("search[value]") or "").split())
    if search_value:
        search_query = (
            Q(full_name__icontains=search_value)
            | Q(registration_no__icontains=search_value)
            | Q(email__icontains=search_value)
            | Q(professional_type__icontains=search_value)
            | Q(source_label__icontains=search_value)
            | Q(status__icontains=search_value)
            | Q(severity__icontains=search_value)
            | Q(missing_fields__icontains=search_value)
        )
        if search_value.isdigit():
            search_number = int(search_value)
            search_query |= (
                Q(source_row=search_number)
                | Q(object_id=search_number)
                | Q(quality_record_year=search_number)
            )
        queryset = queryset.filter(search_query)

    records_filtered = queryset.count()
    order_column = request.GET.get("order[0][column]", "")
    order_dir = request.GET.get("order[0][dir]", "desc")
    order_map = {
        "0": "quality_record_year",
        "1": "quality_payment_date",
        "2": "full_name",
        "3": "professional_type",
        "4": "registration_no",
        "6": "source_label",
        "7": "severity",
        "8": "status",
    }
    order_field = order_map.get(order_column)
    if order_field:
        order_expression = F(order_field)
        order_expression = order_expression.asc(nulls_last=True) if order_dir == "asc" else order_expression.desc(nulls_last=True)
        queryset = queryset.order_by(order_expression, "-updated_at", "-id")
    else:
        queryset = queryset.order_by(*_data_quality_review_default_ordering())

    start = max(_safe_int(request.GET.get("start"), 0), 0)
    length = _safe_int(request.GET.get("length"), 25)
    if length < 0:
        length = 100
    length = min(max(length, 10), 100)

    page_reviews = list(queryset[start:start + length])
    practicing_content_type = ContentType.objects.get_for_model(PracticingLicenseRecord)
    practicing_ids = [
        review.object_id
        for review in page_reviews
        if review.content_type_id == practicing_content_type.id
    ]
    practicing_records = PracticingLicenseRecord.objects.in_bulk(practicing_ids)
    data = [
        _quality_review_row_data(
            review,
            practicing_records.get(review.object_id)
            if review.content_type_id == practicing_content_type.id
            else None,
        )
        for review in page_reviews
    ]

    return JsonResponse({
        "draw": _safe_int(request.GET.get("draw"), 1),
        "recordsTotal": records_total,
        "recordsFiltered": records_filtered,
        "data": data,
    })


@login_required
@user_passes_test(_role_in('admin', 'registrar', 'reviewer'))
def platform_standards_alignment(request):
    return render(request, "dashboard/platform_standards_alignment.html", build_platform_standards_context())


class AdvancedDashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'dashboard/dashboard.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.role == 'reviewer':
            target = _staff_role_target(request.user)
            if target and target != 'viewer_dashboard':
                return redirect(target)
        if request.user.is_authenticated and request.user.role not in {'admin', 'registrar'}:
            role_target = {
                'nurse': 'nurse_dashboard',
                'chw': 'chw_dashboard',
                'nurse_aide': 'nurse_aide_dashboard',
                'doctor': 'doctor_dashboard',
                'graduand': 'student_dashboard',
                'student': 'student_dashboard',
                'viewer': 'viewer_dashboard',
            }.get(request.user.role, 'viewer_dashboard')
            return redirect(role_target)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        scope = _workforce_scope_for_user(self.request.user)
        context.update(_current_workforce_context(include_facility_workers=True, scope=scope))
        if scope == 'nursing':
            _apply_nursing_overview_scope(context)
        elif scope == 'medical':
            _apply_medical_overview_scope(context)
        else:
            context['dashboard_scope'] = 'global'
        return context


class WorkforceFlowDashboardView(AdvancedDashboardView):
    template_name = 'dashboard/workforce_flow.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if request.user.role not in {'admin', 'registrar', 'reviewer'}:
            role_target = {
                'nurse': 'nurse_dashboard',
                'chw': 'chw_dashboard',
                'nurse_aide': 'nurse_aide_dashboard',
                'doctor': 'doctor_dashboard',
                'graduand': 'student_dashboard',
                'student': 'student_dashboard',
                'viewer': 'viewer_dashboard',
            }.get(request.user.role, 'viewer_dashboard')
            return redirect(role_target)
        return super(AdvancedDashboardView, self).dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = TemplateView.get_context_data(self, **kwargs)
        scope = _workforce_scope_for_user(self.request.user)
        context.update(_current_workforce_context(include_facility_workers=True, scope=scope))
        if scope == 'nursing':
            _apply_nursing_overview_scope(context)
        elif scope == 'medical':
            _apply_medical_overview_scope(context)
        else:
            context['dashboard_scope'] = 'global'
        return context


@login_required
@user_passes_test(_role_in('admin', 'registrar'))
def generate_registered_nurses_pdf(request):
    if not can_access_staff_domain(request.user, 'nursing'):
        raise Http404("Report not available")
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="registered_nurses.pdf"'

    p = canvas.Canvas(response, pagesize=letter)
    p.drawString(100, 750, "Registered Nurses")

    y = 720
    for idx, nurse in enumerate(NursingProfessional.objects.order_by('last_name', 'first_name')[:30], start=1):
        p.drawString(100, y, f"{idx}. {nurse.first_name} {nurse.last_name} ({nurse.registration_no})")
        y -= 20
        if y < 60:
            p.showPage()
            y = 750

    p.save()
    return response


@login_required
@user_passes_test(_role_in('admin', 'registrar'))
def generate_csv_report(request, report_type):
    if report_type == 'registered_nurses':
        if not can_access_staff_domain(request.user, 'nursing'):
            raise Http404("Report not available")
        data = list(
            NursingProfessional.objects.values('first_name', 'last_name', 'registration_no', 'email', 'primary_phone')
        )
    elif report_type == 'workforce_summary':
        if getattr(request.user, 'role', '') != 'admin':
            raise Http404("Report not available")
        data = list(
            WorkforceSnapshot.objects.values(
                'year',
                'total_active_workers',
                'total_nurses',
                'total_doctors',
                'total_midwives',
                'total_chw',
            )
        )
    else:
        data = []

    df = pd.DataFrame(data)
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{report_type}.csv"'
    response.write(df.to_csv(index=False))
    return response


@login_required
@user_passes_test(_role_in('admin', 'registrar'))
def export_workforce_flow_pdf(request):
    scope = _analytics_scope_for_user(request.user, _analytics_export_scope(request))
    response = HttpResponse(content_type='application/pdf')
    filename = f'ndoh_{scope}_monthly_analytics_report.pdf' if scope else 'ndoh_monthly_analytics_report.pdf'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response.write(build_monthly_analytics_pdf(scope))
    return response


@login_required
@user_passes_test(_role_in('admin', 'registrar'))
def export_monthly_analytics_excel(request):
    scope = _analytics_scope_for_user(request.user, _analytics_export_scope(request))
    filename = f'ndoh_{scope}_monthly_analytics_report.xlsx' if scope else 'ndoh_monthly_analytics_report.xlsx'
    response = HttpResponse(
        build_monthly_analytics_excel(scope),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
@user_passes_test(_role_in('admin', 'registrar'))
def export_monthly_analytics_pdf(request):
    scope = _analytics_scope_for_user(request.user, _analytics_export_scope(request))
    response = HttpResponse(content_type='application/pdf')
    filename = f'ndoh_{scope}_monthly_analytics_report.pdf' if scope else 'ndoh_monthly_analytics_report.pdf'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response.write(build_monthly_analytics_pdf(scope))
    return response


@login_required
@user_passes_test(_role_in('admin', 'registrar'))
def export_yearly_analytics_excel(request):
    scope = _analytics_scope_for_user(request.user, _analytics_export_scope(request))
    filename = f'ndoh_{scope}_yearly_analytics_report.xlsx' if scope else 'ndoh_yearly_analytics_report.xlsx'
    response = HttpResponse(
        build_yearly_analytics_excel(scope),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
@user_passes_test(_role_in('admin', 'registrar'))
def export_yearly_analytics_pdf(request):
    scope = _analytics_scope_for_user(request.user, _analytics_export_scope(request))
    response = HttpResponse(content_type='application/pdf')
    filename = f'ndoh_{scope}_yearly_analytics_report.pdf' if scope else 'ndoh_yearly_analytics_report.pdf'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response.write(build_yearly_analytics_pdf(scope))
    return response


def _run_brief_generator(script_name):
    script_path = settings.BASE_DIR / 'docs' / script_name
    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=settings.BASE_DIR,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        error_output = result.stdout or result.stderr or "Brief generator failed."
        raise RuntimeError(error_output)


@login_required
@user_passes_test(_role_in('admin', 'registrar'))
def export_minister_brief_docx(request):
    _run_brief_generator('generate_minister_updated_brief_docx.py')
    file_path = settings.BASE_DIR / 'docs' / 'NDOH_Regulatory_Bodies_Online_Workforce_System_Brief_Minister_Updated.docx'
    with open(file_path, 'rb') as handle:
        response = HttpResponse(
            handle.read(),
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )
    response['Content-Disposition'] = 'attachment; filename="NDOH_Regulatory_Bodies_Online_Workforce_System_Brief_Minister_Updated.docx"'
    return response


@login_required
@user_passes_test(_role_in('admin', 'registrar'))
def export_registrar_secretary_brief_docx(request):
    _run_brief_generator('generate_full_system_brief_docx.py')
    file_path = settings.BASE_DIR / 'docs' / 'NDOH_Regulatory_Bodies_Online_Workforce_System_Brief.docx'
    with open(file_path, 'rb') as handle:
        response = HttpResponse(
            handle.read(),
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )
    response['Content-Disposition'] = 'attachment; filename="NDOH_Regulatory_Bodies_Online_Workforce_System_Brief.docx"'
    return response


@login_required
@user_passes_test(_role_in('admin', 'registrar', 'reviewer'))
def financial_forecast_dashboard(request):
    scope = _financial_scope_for_user(request.user, request.GET.get("office"))
    payload = build_financial_forecast_payload(
        scope,
        generated_by=_export_user_label(request.user),
    )
    payload["office_sections"] = [
        _financial_chart_context(payload["offices"][key])
        for key in payload["office_keys"]
    ]
    selected_office = scope or "all"
    payload["scope_label"] = (
        "All Regulatory Offices"
        if selected_office == "all"
        else ("Medical Board" if selected_office == "medical" else "Nursing Council")
    )
    payload["selected_finance_office"] = selected_office
    payload["finance_office_options"] = _financial_office_options_for_user(request.user, scope)
    payload["is_finance_officer_view"] = is_finance_reviewer(request.user)
    payload["financial_forecast_return_query"] = "" if selected_office == "all" else f"?office={selected_office}"
    return render(request, "dashboard/financial_forecast.html", payload)


@login_required
@user_passes_test(_role_in('admin', 'registrar', 'reviewer'))
def export_financial_forecast_excel_view(request):
    scope = _financial_scope_for_user(request.user, request.GET.get("office"))
    content = build_financial_forecast_excel(scope, generated_by=_export_user_label(request.user))
    _log_financial_export(request, "excel", scope)
    response = HttpResponse(
        content,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    filename_scope = scope or "all_regulatory_offices"
    response["Content-Disposition"] = f'attachment; filename="financial_forecast_{filename_scope}_report.xlsx"'
    return response


@login_required
@user_passes_test(_role_in('admin', 'registrar', 'reviewer'))
def export_financial_forecast_pdf_view(request):
    scope = _financial_scope_for_user(request.user, request.GET.get("office"))
    content = build_financial_forecast_pdf(scope, generated_by=_export_user_label(request.user))
    _log_financial_export(request, "pdf", scope)
    response = HttpResponse(content, content_type="application/pdf")
    filename_scope = scope or "all_regulatory_offices"
    response["Content-Disposition"] = f'attachment; filename="financial_forecast_{filename_scope}_report.pdf"'
    return response


@login_required
@user_passes_test(_role_in('admin', 'registrar', 'reviewer'))
def export_financial_forecast_docx_view(request):
    scope = _financial_scope_for_user(request.user, request.GET.get("office"))
    content = build_financial_forecast_docx(scope, generated_by=_export_user_label(request.user))
    _log_financial_export(request, "docx", scope)
    response = HttpResponse(
        content,
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    filename_scope = scope or "all_regulatory_offices"
    response["Content-Disposition"] = f'attachment; filename="financial_forecast_{filename_scope}_report.docx"'
    return response


@login_required
@user_passes_test(_role_in('admin', 'registrar', 'reviewer'))
def staff_ai_assistant(request):
    if is_finance_reviewer(request.user):
        messages.warning(request, "Finance Officer access is limited to Workforce Flow and Financial Forecast until elevated access is approved.")
        return redirect('financial_forecast_dashboard')
    context = build_staff_ai_context(request.user)
    return render(request, 'dashboard/staff_ai_assistant.html', context)


@login_required
@user_passes_test(_role_in('admin', 'registrar', 'reviewer'))
def duplicate_review_workflow(request):
    if is_finance_reviewer(request.user):
        raise Http404("Duplicate review is not available for Finance Officer accounts")
    scope = _analytics_scope_for_user(request.user)
    queryset = _duplicate_review_queryset_for_user(request.user)
    status_filter = request.GET.get("status", "pending")
    search_query = " ".join(request.GET.get("q", "").split())
    model_filter = request.GET.get("model", "all")

    if status_filter != "all":
        queryset = queryset.filter(status=status_filter)

    allowed_models = _duplicate_review_models_for_scope(scope)
    if model_filter != "all" and model_filter in allowed_models:
        practicing_content_type = ContentType.objects.get_for_model(PracticingLicenseRecord)
        practicing_record_ids = PracticingLicenseRecord.objects.filter(target_model=model_filter).values("id")
        queryset = queryset.filter(
            Q(content_type__model=model_filter)
            | Q(suspected_duplicate__target_model=model_filter)
            | Q(content_type=practicing_content_type, object_id__in=Subquery(practicing_record_ids))
        )

    if search_query:
        practicing_matches = PracticingLicenseRecord.objects.filter(
            Q(full_name__icontains=search_query)
            | Q(registration_no__icontains=search_query)
            | Q(practitioner_number__icontains=search_query)
            | Q(reference_number__icontains=search_query)
        ).values("id")
        queryset = queryset.filter(
            Q(suspected_duplicate__full_name__icontains=search_query)
            | Q(suspected_duplicate__identifier_value__icontains=search_query)
            | Q(suspected_duplicate__target_model__icontains=search_query)
            | Q(content_type__model__icontains=search_query)
            | Q(object_id__in=Subquery(practicing_matches))
        )

    paginator = Paginator(queryset, 25)
    page_obj = paginator.get_page(request.GET.get("page"))
    review_rows = _duplicate_review_rows(page_obj.object_list)
    pending_queryset = _duplicate_review_queryset_for_user(request.user).filter(status="pending")

    context = {
        "scope_label": "All Regulatory Offices" if scope is None else ("Medical Board" if scope == "medical" else "Nursing Council"),
        "status_filter": status_filter,
        "search_query": search_query,
        "model_filter": model_filter,
        "page_obj": page_obj,
        "review_rows": review_rows,
        "pending_total": pending_queryset.count(),
        "reviewed_total": _duplicate_review_queryset_for_user(request.user).filter(status="reviewed").count(),
        "merged_total": _duplicate_review_queryset_for_user(request.user).filter(status="merged").count(),
        "largest_group_size": max((row["member_count"] for row in review_rows), default=0),
        "model_options": [
            {"value": "all", "label": "All Practitioner Types"},
            *[
                {"value": value, "label": _duplicate_review_target_label(value)}
                for value in allowed_models
            ],
        ],
        "status_options": [
            ("pending", "Pending"),
            ("reviewed", "Reviewed"),
            ("merged", "Merged"),
            ("all", "All Statuses"),
        ],
        "query_string_without_page": request.GET.copy(),
    }
    if "page" in context["query_string_without_page"]:
        query_without_page = context["query_string_without_page"].copy()
        query_without_page.pop("page")
        context["query_string_without_page"] = query_without_page.urlencode()
    else:
        context["query_string_without_page"] = context["query_string_without_page"].urlencode()

    return render(request, "dashboard/duplicate_review_workflow.html", context)


@login_required
@user_passes_test(_role_in('admin', 'registrar'))
@require_POST
def duplicate_review_update(request, review_id):
    review = get_object_or_404(_duplicate_review_queryset_for_user(request.user), pk=review_id)
    action = request.POST.get("action", "reviewed")
    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or request.path
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        next_url = redirect("duplicate_review_workflow").url

    if action not in {"pending", "reviewed", "merged"}:
        messages.error(request, "Invalid duplicate-review action.")
        return redirect(next_url)

    review.status = action
    if action == "pending":
        review.reviewed_by = None
        review.review_date = None
    else:
        review.reviewed_by = request.user
        review.review_date = timezone.now()
    review.save(update_fields=["status", "reviewed_by", "review_date"])

    status_label = dict(DuplicateReviewQueue._meta.get_field("status").choices).get(action, action.title())
    messages.success(request, f"Duplicate review #{review.id} marked as {status_label.lower()}.")
    return redirect(next_url)


@login_required
@user_passes_test(_role_in('admin', 'registrar', 'reviewer'))
@require_POST
def staff_ai_chat(request):
    if is_finance_reviewer(request.user):
        return JsonResponse({'error': 'Finance Officer access is limited to Workforce Flow and Financial Forecast until elevated access is approved.'}, status=403)
    question = request.POST.get('question', '')
    if not question and request.content_type == 'application/json':
        try:
            payload = json.loads(request.body.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {}
        question = payload.get('question', '')
    return JsonResponse(build_staff_ai_chat_response(request.user, question))


@login_required
@user_passes_test(_role_in('nurse'))
def nurse_dashboard(request):
    nurse = _find_professional(NursingProfessional, request.user)
    from django.contrib.contenttypes.models import ContentType

    nursing_ct = ContentType.objects.get_for_model(NursingProfessional)
    recent_applications = (
        Application.objects.filter(form_code__in=['NC1', 'NC2', 'NC3'], content_type=nursing_ct)
        .select_related('content_type')
        .order_by('-submitted_date')[:10]
    )
    assets = _professional_assets(nurse)
    applications = _applications_for(nurse).order_by('-submitted_date') if nurse else Application.objects.none()
    receipt_form = _receipt_form_for_user(request.user, applications)
    renewals = [app for app in applications if app.form_code == 'NC3']
    pending_renewals = sum(1 for app in renewals if app.status == 'pending')
    approved_renewals = sum(1 for app in renewals if app.status == 'approved')
    context = {
        'nurse': nurse,
        'professional': nurse,
        'applications': applications,
        'recent_applications': recent_applications,
        'professional_documents': assets['documents'],
        'professional_photos': assets['photos'],
        'primary_photo': assets['photos'].first() if hasattr(assets['photos'], 'first') else None,
        'license_label': assets['license_label'],
        'license_state': assets['license_state'],
        'license_days_left': assets['license_days_left'],
        'recommended_application_url': assets['recommended_application_url'],
        'renewal_applications': renewals,
        'pending_renewals': pending_renewals,
        'approved_renewals': approved_renewals,
        'pending_applications': Application.objects.filter(status='pending', content_type=nursing_ct).count(),
        'today': date.today(),
        'receipts': _receipt_queryset_for_user(request.user),
        'receipt_form': receipt_form,
        'registration_guidelines': _guidelines_for_audience('nurse'),
        'registration_guideline_audience': 'nurse',
    }
    context.update(dashboard_review_context(nurse, request.user))
    return render(request, 'dashboard/nurse_dashboard.html', context)


@login_required
def nursing_council_portal(request):
    if not is_nursing_council_staff(request.user):
        return redirect('registrar_dashboard' if request.user.role == 'registrar' else 'main_dashboard')
    nursing_ct = ContentType.objects.get_for_model(NursingProfessional)
    provisional_license_context = _current_provisional_licenses()
    nursing_review_types = ['Nursing Professional', 'Midwife', 'Graduand', 'Practicing License Record']
    nursing_missing_reviews = MissingDataReview.objects.filter(
        professional_type__in=nursing_review_types,
    ).exclude(status='resolved')
    context = _current_workforce_context()
    context.update(_nursing_council_analytics_context())
    context.update({
        'can_manage_nursing_operations': can_manage_regulatory_operations(request.user),
        'nursing_count': NursingProfessional.objects.count(),
        'midwife_count': Midwife.objects.count(),
        'institutions_count': context['reference_breakdown']['png_nursing_school_count'],
        'pending_applications': Application.objects.filter(
            status='pending',
            content_type=nursing_ct,
            form_code__in=['NC1', 'NC2', 'NC3', 'NC5', 'NC6', 'NC7', 'NC8', 'NC9', 'NC10', 'NC11'],
        ).count(),
        'recent_applications': _recent_nursing_applications(),
        'current_provisional_licenses': provisional_license_context['rows'],
        'provisional_license_count': provisional_license_context['total_count'],
        'provisional_license_display_count': provisional_license_context['display_count'],
        'provisional_license_limit': provisional_license_context['limit'],
        'renewals_pending': sum(
            1 for row in provisional_license_context['rows']
            if row['days_left'] is not None and 0 <= row['days_left'] <= 30
        ),
    })
    context.update(_data_quality_review_context(nursing_missing_reviews, limit=20, scope_key="nursing"))
    context.update(_nursing_province_distribution_context())
    context.update(_nursing_atp_context())
    context.update(_registrar_worker_origin_context(request.user))
    return render(request, 'dashboard/nursing_council_portal.html', context)


@login_required
@user_passes_test(lambda user: getattr(user, "role", "") == "admin" or is_nursing_council_staff(user))
def nursing_frequent_records(request):
    context = _nursing_frequent_records_context(request)
    return render(request, "dashboard/nursing_frequent_records.html", context)


@login_required
@user_passes_test(_role_in('chw'))
def chw_dashboard(request):
    chw = _find_professional(CommunityHealthWorker, request.user)
    applications = _applications_for(chw).order_by('-submitted_date') if chw else Application.objects.none()
    context = {
        'chw': chw,
        'applications': applications,
        'receipts': _receipt_queryset_for_user(request.user),
        'receipt_form': _receipt_form_for_user(request.user, applications),
        'registration_guidelines': _guidelines_for_audience('chw'),
        'registration_guideline_audience': 'chw',
    }
    context.update(dashboard_review_context(chw, request.user))
    return render(request, 'dashboard/chw_dashboard.html', context)


@login_required
@user_passes_test(_role_in('nurse_aide'))
def nurse_aide_dashboard(request):
    nurse_aide = _find_professional(NurseAide, request.user)
    applications = _applications_for(nurse_aide).order_by('-submitted_date') if nurse_aide else Application.objects.none()
    context = {
        'nurse_aide': nurse_aide,
        'applications': applications,
        'receipts': _receipt_queryset_for_user(request.user),
        'receipt_form': _receipt_form_for_user(request.user, applications),
        'registration_guidelines': _guidelines_for_audience('nurse_aide'),
        'registration_guideline_audience': 'nurse_aide',
    }
    context.update(dashboard_review_context(nurse_aide, request.user))
    return render(request, 'dashboard/nurse_aide_dashboard.html', context)


@login_required
@user_passes_test(_role_in('doctor'))
def doctor_dashboard(request):
    doctor = _find_professional(MedicalDoctor, request.user)
    applications = _applications_for(doctor).order_by('-submitted_date') if doctor else Application.objects.none()
    receipt_form = _receipt_form_for_user(request.user, applications)
    context = {
        'doctor': doctor,
        'applications': applications,
        'license_expiry': doctor.license_expiry_date if doctor else None,
        'today': date.today(),
        'receipts': _receipt_queryset_for_user(request.user),
        'receipt_form': receipt_form,
        'registration_guidelines': _guidelines_for_audience('doctor'),
        'registration_guideline_audience': 'doctor',
    }
    context.update(dashboard_review_context(doctor, request.user))
    return render(request, 'dashboard/doctor_dashboard.html', context)


@login_required
@user_passes_test(_role_in('graduand', 'student'))
def student_dashboard(request):
    student = _find_professional(HealthStudent, request.user)
    applications = _applications_for(student).order_by('-submitted_date') if student else Application.objects.none()
    receipt_form = _receipt_form_for_user(request.user, applications)
    context = {
        'student': student,
        'applications': applications,
        'expected_graduation': student.expected_graduation_date if student else None,
        'receipts': _receipt_queryset_for_user(request.user),
        'receipt_form': receipt_form,
        'registration_guidelines': _guidelines_for_audience('graduand'),
        'registration_guideline_audience': 'graduand',
        'graduand_pathway_forms': ['G1', 'G2', 'G3', 'G4', 'NC1', 'NC6', 'NC2', 'NC3'],
    }
    context.update(dashboard_review_context(student, request.user))
    return render(request, 'dashboard/student_dashboard.html', context)


@login_required
def medical_board_portal(request):
    if not is_medical_board_staff(request.user):
        return redirect('registrar_dashboard' if request.user.role == 'registrar' else 'main_dashboard')
    context = _current_workforce_context(include_facility_workers=True, facility_target_models=['medicaldoctor', 'communityhealthworker'])
    context.update(_medical_board_context())
    context.update(_registrar_worker_origin_context(request.user))
    context['can_manage_medical_operations'] = can_manage_regulatory_operations(request.user)
    return render(request, 'dashboard/medical_board_portal.html', context)


@login_required
@user_passes_test(_role_in('nurse', 'doctor', 'graduand', 'student', 'chw', 'nurse_aide'))
def submit_receipt(request):
    if request.method != 'POST':
        return redirect('main_dashboard')

    professional = None
    for model in [NursingProfessional, MedicalDoctor, HealthStudent, CommunityHealthWorker, NurseAide]:
        professional = _find_professional(model, request.user)
        if professional:
            break

    applications = _applications_for(professional).order_by('-submitted_date') if professional else Application.objects.none()
    form = _receipt_form_for_user(request.user, applications, data=request.POST, files=request.FILES)
    redirect_name = {
        'nurse': 'nurse_dashboard',
        'doctor': 'doctor_dashboard',
        'graduand': 'student_dashboard',
        'student': 'student_dashboard',
        'chw': 'chw_dashboard',
        'nurse_aide': 'nurse_aide_dashboard',
    }.get(request.user.role, 'viewer_dashboard')

    if form.is_valid():
        receipt = form.save(commit=False)
        receipt.user = request.user
        receipt.status = 'completed'
        receipt.save()
        return redirect(redirect_name)

    context = {
        'receipts': _receipt_queryset_for_user(request.user),
        'receipt_form': form,
        'registration_guidelines': _guidelines_for_audience(request.user.role if request.user.role in {'nurse', 'doctor', 'graduand', 'student', 'chw', 'nurse_aide'} else 'general'),
    }
    context.update(dashboard_review_context(professional, request.user))
    if request.user.role == 'doctor':
        context.update({
            'doctor': professional,
            'applications': applications,
            'license_expiry': professional.license_expiry_date if professional else None,
        })
        return render(request, 'dashboard/doctor_dashboard.html', context)
    if request.user.role in {'graduand', 'student'}:
        context.update({
            'student': professional,
            'applications': applications,
            'expected_graduation': professional.expected_graduation_date if professional else None,
        })
        return render(request, 'dashboard/student_dashboard.html', context)
    if request.user.role == 'nurse':
        assets = _professional_assets(professional)
        renewals = [app for app in applications if app.form_code == 'NC3']
        context.update({
            'nurse': professional,
            'professional': professional,
            'applications': applications,
            'recent_applications': Application.objects.filter(
                form_code__in=['NC1', 'NC2', 'NC3'],
                content_type=ContentType.objects.get_for_model(NursingProfessional),
            ).select_related('content_type').order_by('-submitted_date')[:10],
            'professional_documents': assets['documents'],
            'professional_photos': assets['photos'],
            'primary_photo': assets['photos'].first() if hasattr(assets['photos'], 'first') else None,
            'license_label': assets['license_label'],
            'license_state': assets['license_state'],
            'license_days_left': assets['license_days_left'],
            'recommended_application_url': assets['recommended_application_url'],
            'renewal_applications': renewals,
            'pending_renewals': sum(1 for app in renewals if app.status == 'pending'),
            'approved_renewals': sum(1 for app in renewals if app.status == 'approved'),
            'pending_applications': Application.objects.filter(
                status='pending',
                content_type=ContentType.objects.get_for_model(NursingProfessional),
            ).count(),
            'today': date.today(),
        })
        return render(request, 'dashboard/nurse_dashboard.html', context)
    if request.user.role == 'chw':
        context.update({'chw': professional, 'applications': applications})
        return render(request, 'dashboard/chw_dashboard.html', context)
    if request.user.role == 'nurse_aide':
        context.update({'nurse_aide': professional, 'applications': applications})
        return render(request, 'dashboard/nurse_aide_dashboard.html', context)
    return redirect(redirect_name)


@login_required
def main_dashboard(request):
    """
    Main dashboard redirect based on user role and portal context
    """
    role = request.user.role

    # Admin gets full access
    if role == 'admin':
        return redirect('admin_dashboard')

    # Registrar gets registrar dashboard
    elif role == 'registrar':
        portal_target = _staff_portal_target(request.user)
        if portal_target:
            return redirect(portal_target)
        return redirect('registrar_dashboard')
    elif role == 'reviewer':
        return redirect(_staff_role_target(request.user) or 'viewer_dashboard')

    # Professional roles get their specific dashboards
    elif role == 'nurse':
        return redirect('nurse_dashboard')
    elif role == 'chw':
        return redirect('chw_dashboard')
    elif role == 'nurse_aide':
        return redirect('nurse_aide_dashboard')
    elif role == 'doctor':
        return redirect('doctor_dashboard')
    elif role in {'graduand', 'student'}:
        return redirect('student_dashboard')

    # Default fallback
    else:
        return redirect('viewer_dashboard')


@login_required
@require_POST
def execute_management_command(request):
    if not can_manage_regulatory_operations(request.user):
        return JsonResponse({'error': 'This command area is restricted to approved Registrar and System Admin staff.'}, status=403)

    command = request.POST.get('command')
    if not command and request.body:
        try:
            payload = json.loads(request.body.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {}
        command = payload.get('command')
    if not command:
        return JsonResponse({'error': 'No command specified'}, status=400)

    # Define allowed commands
    allowed_commands = {
        'import_provisional_licenses': [sys.executable, 'manage.py', 'import_provisional_licenses', '--file', str(settings.BASE_DIR / 'notebooks' / 'Provional_Cleansed_data2009_2026.xlsx')],
        'import_ndata_workbook': [sys.executable, 'manage.py', 'import_ndata_workbook', '--file', r'd:\2026 Current N-DATA Statistics & Tracking - SECTIONS (Autosaved).xlsx'],
        'import_current_atp_workbook': [sys.executable, 'manage.py', 'import_atp_workbook', '--file', str(ATP_WORKBOOK_PATH)],
        'import_medical_board_workbook': [sys.executable, 'manage.py', 'import_medical_board_workbook', '--file', str(DEFAULT_MEDICAL_BOARD_WORKBOOK)],
        'import_medical_board_legacy_workbooks': [sys.executable, 'manage.py', 'import_medical_board_legacy_workbooks'],
        'bootstrap_reference_data': [sys.executable, 'manage.py', 'bootstrap_reference_data'],
        'bootstrap_nursing_council_workflows': [sys.executable, 'manage.py', 'bootstrap_nursing_council_workflows'],
        'import_workforce_files': [sys.executable, 'manage.py', 'import_workforce_files', '--path', 'notebooks/csv_templates'],
        'generate_snapshot': [sys.executable, 'manage.py', 'generate_snapshot'],
        'audit_missing_data': [sys.executable, 'manage.py', 'audit_missing_data', '--audit-import-rows', '--latest-batch'],
    }
    background_commands = {'audit_missing_data', 'import_current_atp_workbook'}

    if command not in allowed_commands:
        return JsonResponse({'error': 'Invalid command'}, status=400)

    if request.user.role != 'admin':
        if is_medical_board_staff(request.user):
            allowed_for_user = {
                'import_medical_board_workbook',
                'import_medical_board_legacy_workbooks',
                'generate_snapshot',
                'audit_missing_data',
            }
        elif is_nursing_council_staff(request.user):
            allowed_for_user = {
                'import_provisional_licenses',
                'import_ndata_workbook',
                'import_current_atp_workbook',
                'bootstrap_reference_data',
                'bootstrap_nursing_council_workflows',
                'import_workforce_files',
                'generate_snapshot',
                'audit_missing_data',
            }
        else:
            return JsonResponse({'error': 'Command not available for this account'}, status=403)

        if command not in allowed_for_user:
            return JsonResponse({'error': 'Command not available for this office'}, status=403)

    try:
        if command in background_commands:
            log_dir = Path(settings.BASE_DIR) / 'docs' / 'command_logs'
            log_dir.mkdir(parents=True, exist_ok=True)
            timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
            log_path = log_dir / f'{command}_{timestamp}.log'
            with log_path.open('w', encoding='utf-8') as handle:
                process = subprocess.Popen(
                    allowed_commands[command],
                    cwd=settings.BASE_DIR,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    text=True,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                )
            return JsonResponse({
                'message': f'Command "{command}" started successfully in the background',
                'output': f'Background audit started. Log file: {log_path.name}',
                'returncode': 0,
                'background': True,
                'pid': process.pid,
                'log_file': log_path.name,
            })

        # Execute the command
        result = subprocess.run(
            allowed_commands[command],
            cwd=settings.BASE_DIR,
            capture_output=True,
            text=True,
            timeout=1800
        )

        output = result.stdout
        if result.stderr:
            output += "\nSTDERR:\n" + result.stderr

        if result.returncode != 0:
            return JsonResponse({
                'error': f'Command "{command}" failed',
                'output': output,
                'returncode': result.returncode
            }, status=500)

        return JsonResponse({
            'message': f'Command "{command}" executed successfully',
            'output': output,
            'returncode': result.returncode
        })

    except subprocess.TimeoutExpired:
        return JsonResponse({'error': 'Command timed out'}, status=500)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def fee_structure(request):
    """
    Fee structure and guidelines page
    """
    fee_scope = None
    if getattr(request.user, 'role', '') != 'admin':
        if is_medical_board_user(request.user):
            fee_scope = 'medical'
        elif is_nursing_council_user(request.user):
            fee_scope = 'nursing'
    return render(request, 'dashboard/fee_structure.html', {'fee_scope': fee_scope})


@login_required
def production_readiness_dashboard(request):
    if not _can_access_production_readiness(request.user):
        raise Http404("Production readiness dashboard not available")
    return render(
        request,
        "dashboard/production_readiness.html",
        build_production_readiness_context(request.user),
    )


@login_required
@require_POST
def production_readiness_missing_review_update(request, review_id):
    if not _can_access_production_readiness(request.user):
        raise Http404("Production readiness dashboard not available")

    review = get_object_or_404(
        build_production_readiness_review_queryset(request.user),
        pk=review_id,
    )
    new_status = request.POST.get("status")
    valid_statuses = {value for value, _label in MissingDataReview.STATUS_CHOICES}
    if new_status not in valid_statuses:
        messages.error(request, "That review status is not available.")
        return redirect("production_readiness_dashboard")

    old_status = review.status
    review.status = new_status
    if new_status == "resolved":
        review.resolved_at = timezone.now()
    else:
        review.resolved_at = None
    if new_status == "notified":
        review.notification_sent = True
        review.notified_at = review.notified_at or timezone.now()
    review.save(update_fields=[
        "status",
        "resolved_at",
        "notification_sent",
        "notified_at",
        "updated_at",
    ])

    AuditLog.objects.create(
        actor=request.user,
        action="MISSING_DATA_REVIEW_STATUS_CHANGED",
        entity_type="MissingDataReview",
        entity_id=str(review.pk),
        old_values_json={"status": old_status},
        new_values_json={
            "status": new_status,
            "full_name": review.full_name,
            "registration_no": review.registration_no,
            "professional_type": review.professional_type,
        },
        ip_address=_request_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
    )
    messages.success(request, f"Missing-data review updated to {review.get_status_display()}.")
    return redirect("production_readiness_dashboard")


@login_required
def dashboard_search(request):
    if is_finance_reviewer(request.user):
        messages.warning(request, "Finance Officer access is limited to Workforce Flow and separate Financial Forecast views until elevated access is approved.")
        return redirect("financial_forecast_dashboard")

    query = " ".join(request.GET.get("q", "").strip().split())
    scope = request.GET.get("scope", "all")
    staff_user = is_staff_dashboard_user(request.user)
    medical_staff = is_medical_board_staff(request.user)
    nursing_staff = is_nursing_council_staff(request.user) and not medical_staff
    results = {
        "professionals": [],
        "applications": [],
        "imported_records": [],
        "facilities": [],
        "guidance": [],
    }
    helpdesk_answer = None

    if query:
        if staff_user:
            professional_models = [
                ("Nursing Professional", NursingProfessional),
                ("Midwife", Midwife),
                ("Nurse Aide", NurseAide),
                ("Graduand", HealthStudent),
                ("Medical Doctor", MedicalDoctor),
                ("Community Health Worker", CommunityHealthWorker),
            ]
            if request.user.role != "admin":
                if nursing_staff:
                    professional_models = [
                        row for row in professional_models
                        if row[0] in {"Nursing Professional", "Midwife", "Nurse Aide", "Graduand"}
                    ]
                elif medical_staff:
                    professional_models = [
                        row for row in professional_models
                        if row[0] in {"Medical Doctor", "Community Health Worker"}
                    ]

            for label, model in professional_models:
                qs = model.objects.filter(
                    Q(first_name__icontains=query)
                    | Q(middle_name__icontains=query)
                    | Q(last_name__icontains=query)
                    | Q(registration_no__icontains=query)
                    | Q(registration_number__icontains=query)
                    | Q(email__icontains=query)
                    | Q(primary_phone__icontains=query)
                    | Q(province__icontains=query)
                )[:10]
                for item in qs:
                    results["professionals"].append({
                        "type": label,
                        "name": str(item),
                        "registration": item.registration_no or item.registration_number or "-",
                        "detail": item.email or item.primary_phone or item.province or "-",
                        "url": "record_detail",
                        "model_slug": item.__class__.__name__.lower(),
                        "pk": item.pk,
                    })

            application_qs = Application.objects.filter(
                Q(form_code__icontains=query)
                | Q(form_title__icontains=query)
                | Q(profession_track__icontains=query)
                | Q(status__icontains=query)
                | Q(reviewer_notes__icontains=query)
            ).select_related("content_type").order_by("-submitted_date")
            if medical_staff:
                application_qs = application_qs.filter(form_code__in=MEDICAL_BOARD_FORM_CODES)
            elif nursing_staff:
                application_qs = application_qs.exclude(form_code__in=MEDICAL_BOARD_FORM_CODES)
            application_qs = application_qs[:25]
            for app in application_qs:
                results["applications"].append({
                    "id": app.id,
                    "form_code": app.form_code,
                    "status": app.get_status_display(),
                    "professional": str(app.professional or "Unknown applicant"),
                    "submitted": app.submitted_date,
                    "url": "application_detail",
                    "pk": app.pk,
                })

            imported_records = _quality_approved_practicing_records().filter(
                Q(full_name__icontains=query)
                | Q(first_name__icontains=query)
                | Q(last_name__icontains=query)
                | Q(registration_no__icontains=query)
                | Q(practitioner_number__icontains=query)
                | Q(category__icontains=query)
                | Q(institution_name__icontains=query)
                | Q(workplace_address__icontains=query)
                | Q(province__icontains=query)
            ).order_by("-record_year", "full_name")
            if medical_staff:
                imported_records = imported_records.filter(target_model__in=MEDICAL_BOARD_PROFESSIONAL_MODELS)
            elif nursing_staff:
                imported_records = imported_records.filter(target_model__in=NURSING_COUNCIL_PROFESSIONAL_MODELS)
            imported_records = imported_records[:30]
            for record in imported_records:
                results["imported_records"].append({
                    "name": record.full_name,
                    "registration": record.registration_no or record.practitioner_number or "-",
                    "category": record.category or record.get_target_model_display(),
                    "year": record.record_year or "-",
                    "province": _normalize_province_label(record.province),
                    "record_type": record.get_record_type_display(),
                })

            facilities = Facility.objects.filter(
                Q(name__icontains=query)
                | Q(code__icontains=query)
                | Q(type__icontains=query)
                | Q(location__province__icontains=query)
                | Q(location__district__icontains=query)
            ).select_related("location")[:20]
            for facility in facilities:
                results["facilities"].append({
                    "name": facility.name,
                    "code": facility.code or "-",
                    "type": facility.type or "-",
                    "location": str(facility.location or "-"),
                })

        guidance = RegistrationGuideline.objects.filter(
            Q(code__icontains=query)
            | Q(title__icontains=query)
            | Q(summary__icontains=query),
            is_active=True,
        )
        if medical_staff:
            guidance = guidance.filter(audience__in=['general', 'doctor', 'chw'])
        elif nursing_staff:
            guidance = guidance.filter(audience__in=['general', 'nurse', 'nurse_aide', 'graduand'])
        guidance = guidance[:12]
        for item in guidance:
            results["guidance"].append({
                "title": f"{item.code} - {item.title}",
                "summary": item.summary,
                "audience": item.get_audience_display(),
                "url_name": item.action_url_name,
            })

        answer, suggestions = get_helpdesk_response(query)
        helpdesk_answer = {
            "title": answer.title,
            "answer": answer.answer,
            "suggestions": [item.title for item in suggestions],
        }
        if not results["guidance"]:
            for item in HELPDESK_KNOWLEDGE[:8]:
                if query.lower() in item.title.lower() or any(token in query.lower() for token in item.keywords):
                    results["guidance"].append({
                        "title": item.title,
                        "summary": item.answer,
                        "audience": "General",
                        "url_name": "",
                    })

    result_count = sum(len(value) for value in results.values())
    return render(request, "dashboard/search.html", {
        "query": query,
        "scope": scope,
        "staff_user": staff_user,
        "results": results,
        "result_count": result_count,
        "helpdesk_answer": helpdesk_answer,
    })
