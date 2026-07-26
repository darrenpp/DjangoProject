from collections import defaultdict
from datetime import date
from datetime import timedelta
import json
from pathlib import Path
import re
from urllib.parse import urlencode

import pandas as pd
import sys
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.core.files.storage import FileSystemStorage
from django.core.paginator import Paginator
from django.db.models import Case, Count, DateField, F, IntegerField, Max, OuterRef, Q, Subquery, Sum, Value, When
from django.http import Http404, HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import NoReverseMatch, reverse
from django.utils.html import conditional_escape, format_html
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.safestring import mark_safe
from django.utils.dateparse import parse_date
from django.utils.text import get_valid_filename, slugify
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
from apps.common.record_views import (
    _can_create_records,
    _can_delete_records,
    _record_action_buttons,
    scoped_record_queryset,
)
from apps.dashboard.forms import ReceiptSubmissionForm
from apps.accounts.models import SecurityAuditEvent, User
from apps.dashboard.access import (
    MEDICAL_BOARD_FORM_CODES,
    MEDICAL_BOARD_PROFESSIONAL_MODELS,
    NURSING_COUNCIL_PROFESSIONAL_MODELS,
    can_access_nursing_board_portal,
    can_manage_regulatory_operations,
    can_access_staff_domain,
    is_data_quality_reviewer,
    is_finance_reviewer,
    is_system_admin,
    is_medical_board_staff,
    is_medical_board_user,
    is_nursing_council_board_member,
    is_nursing_council_staff,
    is_nursing_council_user,
    is_staff_dashboard_user,
)
from apps.dashboard.ai_provider import ai_provider_status
from apps.dashboard.models import (
    AssistantConversation,
    AssistantFeedback,
    FAQCategory,
    FAQEntry,
    ForumCategory,
    ForumModerationLog,
    ForumPost,
    ForumTopic,
    MappedEntity,
    NursingCouncilBoardActionItem,
    NursingCouncilBoardAgendaItem,
    NursingCouncilBoardAttendance,
    NursingCouncilBoardMeeting,
    NursingCouncilBoardPaper,
    NursingLifecycleFact,
    NursingPractitionerIndex,
    Receipt,
    RegistrationGuideline,
)
from apps.dashboard.nursing_analytics import (
    active_nursing_analytics_snapshot,
    dashboard_context as nursing_analytics_dashboard_context,
    filtered_lifecycle_facts,
    metric_payload as nursing_analytics_metric_payload,
)
from apps.dashboard.nursing_lapsed_renewal import lapsed_renewal_review_context
from apps.dashboard.nursing_intelligence import build_nursing_workforce_intelligence_context
from apps.dashboard.medical_intelligence import build_medical_board_intelligence_context
from apps.dashboard.workforce_forecasting import build_workforce_forecast_context
from apps.dashboard.reports import (
    build_registered_nurses_excel,
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
from apps.dashboard.platform_resilience import current_platform_status, refresh_platform_connectivity
from apps.dashboard.nhwa_toolkit import build_nhwa_toolkit_context
from apps.dashboard.production_readiness import (
    build_production_readiness_context,
    build_production_readiness_review_queryset,
)
from apps.dashboard.report_freshness import mark_report_data_changed, mark_report_generated
from apps.dashboard.staff_ai import (
    build_staff_ai_chat_response,
    build_staff_ai_context,
    staff_ai_question_needs_knowledge_search,
)
from apps.complaints.services import open_complaint_cases, open_disciplinary_cases, scoped_decision_records
from apps.complaints.models import RegulatoryDecisionRecord
from apps.documents.models import Document
from apps.mobile_intake.models import MobileLocalAccountRequest, MobileSubmission
from apps.notifications.helpdesk import HELPDESK_KNOWLEDGE, get_helpdesk_response
from apps.accounts.professional_linking import get_next_url_name_for_role
from apps.workforce.services.data_quality import dashboard_review_context, quality_approved_import_records
from apps.workforce.services.medical_board_workbook_import import DEFAULT_MEDICAL_BOARD_WORKBOOK
from apps.workforce.services.nursing_council_workflows import build_nursing_workflow_rows
from apps.workforce.forms import MEDICAL_BOARD_SPECIALIST_CHOICES
from apps.workforce.profile_updates import build_professional_identity_context
from apps.workforce.models import (
    Application,
    Cadre,
    CommunityHealthWorker,
    CPDRecord,
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


NURSING_WORKBOOK_UPLOAD_EXTENSIONS = {".xlsx", ".xlsm"}
NURSING_WORKBOOK_UPLOAD_MAX_BYTES = 100 * 1024 * 1024
NURSING_SELECTED_WORKBOOK_IMPORTS = {
    "atp": {
        "label": "ATP",
        "command": "import_atp_workbook",
        "storage_folder": "atp",
        "log_prefix": "import_selected_atp_workbook",
        "all_sheets_label": "All supported ATP sheets",
        "field_name": "atp_workbook",
        "multiple_sheets": True,
    },
    "full_licence": {
        "label": "Full-licence",
        "command": "import_full_registrations",
        "storage_folder": "full_licence",
        "log_prefix": "import_selected_full_licence_workbook",
        "all_sheets_label": "Command default full-licence sheet",
        "field_name": "workbook",
        "multiple_sheets": False,
    },
    "provisional": {
        "label": "Provisional",
        "command": "import_provisional_licenses",
        "storage_folder": "provisional",
        "log_prefix": "import_selected_provisional_workbook",
        "all_sheets_label": "Command default provisional sheet",
        "field_name": "workbook",
        "multiple_sheets": False,
    },
}
ATP_NURSING_TARGET_MODELS = ["nursingprofessional", "midwife", "nurseaide"]
NURSING_IMPORT_SOURCE_KINDS = ['nursing_license_workbook', 'ndata_workbook']
NURSING_IMPORT_TARGET_MODELS = ['nursingprofessional', 'midwife', 'nurseaide', 'healthstudent']
MEDICAL_IMPORT_SOURCE_KINDS = ['medical_board_workbook']
MEDICAL_IMPORT_TARGET_MODELS = ['medicaldoctor', 'communityhealthworker', 'other']
# Facility workforce reporting is about people and their licence pathway.  Payment
# and workbook-summary rows can contain an employer/facility column, but are not
# people working at that facility and must never be included in cadre totals.
FACILITY_WORKER_RECORD_TYPES = (
    'provisional',
    'full',
    'full_approved',
    'temporary',
    'practicing_license',
    'workforce_listing',
)
NURSING_FORM_CODES = ['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G7', 'NC1', 'NC2', 'NC3', 'NC4', 'NC5', 'NC6', 'NC7', 'NC8', 'NC9', 'NC10', 'NC11']
MEDICAL_BOARD_CADRE_NAME_FILTER = (
    Q(name__icontains='medical doctor')
    | Q(name__iexact='medical specialist')
    | Q(name__icontains='community health worker')
    | Q(name__iexact='chw')
    | Q(name__icontains='allied health')
)
MEDICAL_RECEIPT_ROLES = {'doctor', 'chw'}
NURSING_RECEIPT_ROLES = {'nurse', 'nurse_aide', 'graduand', 'student'}
DASHBOARD_CACHE_TIMEOUT_SECONDS = 300
PROVISIONAL_LICENSE_TABLE_LIMIT = 300


ANALYTICS_SEARCH_STOP_WORDS = {
    "and",
    "full",
    "licence",
    "license",
    "nursing",
    "school",
    "province",
    "provincial",
    "health",
    "authority",
    "diploma",
    "general",
    "yes",
    "no",
}


def _plain_text(value):
    return str(value or "").strip()


def _user_is_practitioner(user):
    return getattr(user, "is_authenticated", False) and getattr(user, "role", "") in {
        "nurse",
        "nurse_aide",
        "graduand",
        "student",
        "doctor",
        "chw",
    }


def _forum_category_visible_for_user(category, user):
    visibility = category.visibility
    if visibility == "public":
        return True
    if not getattr(user, "is_authenticated", False):
        return False
    if is_system_admin(user):
        return True
    if visibility == "staff":
        return is_staff_dashboard_user(user)
    if visibility == "nursing_staff":
        return is_nursing_council_staff(user)
    if visibility == "medical_staff":
        return is_medical_board_staff(user)
    if visibility == "practitioner":
        return _user_is_practitioner(user)
    role = getattr(user, "role", "")
    if visibility == "registered_nurse":
        return role == "nurse" or is_nursing_council_staff(user)
    if visibility == "provisional":
        return role in {"graduand", "student"} or is_nursing_council_staff(user)
    if visibility == "full_applicant":
        return role in {"nurse", "graduand", "student", "nurse_aide"} or is_nursing_council_staff(user)
    if visibility == "full_approved":
        return role in {"nurse", "nurse_aide"} or is_nursing_council_staff(user)
    return False


def _visible_forum_categories(user):
    categories = ForumCategory.objects.filter(is_active=True)
    return [
        category
        for category in categories
        if _forum_category_visible_for_user(category, user)
    ]


def _forum_post_status_for_user(category, user):
    if getattr(user, "is_authenticated", False) and is_staff_dashboard_user(user):
        return "approved"
    if not category.requires_moderation:
        return "approved"
    return "pending"


def _unique_topic_slug(category, title):
    base_slug = slugify(title)[:210] or "topic"
    slug = base_slug
    counter = 2
    while ForumTopic.objects.filter(category=category, slug=slug).exists():
        suffix = f"-{counter}"
        slug = f"{base_slug[:240 - len(suffix)]}{suffix}"
        counter += 1
    return slug


def _forum_topic_queryset_for_user(category, user):
    queryset = category.topics.select_related("author", "category").annotate(post_count=Count("posts"))
    if getattr(user, "is_authenticated", False) and is_staff_dashboard_user(user):
        return queryset
    return queryset.filter(status="approved")


def _forum_posts_for_user(topic, user):
    queryset = topic.posts.select_related("author").order_by("created_at")
    if getattr(user, "is_authenticated", False) and is_staff_dashboard_user(user):
        return queryset
    return queryset.filter(status="approved")


def _office_scope_label(value):
    return {
        "nursing": "Nursing Council",
        "medical": "Medical Board",
        "shared": "Shared",
    }.get(value or "shared", "Shared")


def _mapped_entities_queryset(request):
    office = request.GET.get("office", "all")
    entity_type = request.GET.get("type", "all")
    province = request.GET.get("province", "")
    query = request.GET.get("q", "").strip()
    queryset = MappedEntity.objects.filter(is_active=True).order_by("name")
    if office in {"nursing", "medical"}:
        queryset = queryset.filter(office_scope__in=[office, "shared"])
    elif office == "shared":
        queryset = queryset.filter(office_scope="shared")
    if entity_type and entity_type != "all":
        queryset = queryset.filter(entity_type=entity_type)
    if province:
        queryset = queryset.filter(province=province)
    if query:
        queryset = queryset.filter(
            Q(name__icontains=query)
            | Q(normalized_name__icontains=query)
            | Q(province__icontains=query)
            | Q(district__icontains=query)
            | Q(address__icontains=query)
        )
    return queryset


def _staff_reference_scope(user, requested_scope=None):
    if is_finance_reviewer(user) or not is_staff_dashboard_user(user):
        raise Http404("Report not available")
    return _individual_record_scope_for_user(user, requested_scope)


def _mapped_entity_detail_url(entity):
    entity_type = entity.entity_type
    source_model = str(entity.source_model or "").lower()
    source_object_id = str(entity.source_object_id or "").strip()

    if entity_type in {"facility", "hospital", "pha", "private_clinic"}:
        if "facility" in source_model and source_object_id.isdigit():
            return reverse("facility_worker_detail", args=[int(source_object_id)])
        facility = Facility.objects.filter(name__iexact=entity.name).order_by("id").first()
        if facility:
            return reverse("facility_worker_detail", args=[facility.pk])
        return reverse("imported_facility_worker_detail") + "?" + urlencode({"name": entity.name})

    if entity_type in {"institution", "school"}:
        if "traininginstitution" in source_model and source_object_id.isdigit():
            return reverse("institution_graduand_detail", args=[int(source_object_id)])
        institution = TrainingInstitution.objects.filter(name__iexact=entity.name).order_by("id").first()
        if institution:
            return reverse("institution_graduand_detail", args=[institution.pk])

    return ""


def _mapped_entity_payload(entity):
    return {
        "id": entity.pk,
        "name": entity.name,
        "entity_type": entity.get_entity_type_display(),
        "entity_type_key": entity.entity_type,
        "office_scope": _office_scope_label(entity.office_scope),
        "office_scope_key": entity.office_scope,
        "province": entity.province,
        "district": entity.district,
        "address": entity.address,
        "latitude": float(entity.latitude) if entity.latitude is not None else None,
        "longitude": float(entity.longitude) if entity.longitude is not None else None,
        "verification_status": entity.get_verification_status_display(),
        "active_workforce_count": entity.active_workforce_count,
        "detail_url": getattr(entity, "detail_url", "") or _mapped_entity_detail_url(entity),
    }
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
DASHBOARD_LICENSE_MODEL_SLUG = "practicinglicenserecord"
DASHBOARD_LICENSE_RECORD_TABLES = (
    {
        "key": "atp",
        "record_type": "practicing_license",
        "title": "ATP Records",
        "short_label": "ATP",
        "description": "Authority to Practice and practising licence rows imported into the registry.",
    },
    {
        "key": "full-license",
        "record_type": "full",
        "title": "Full-License Applicant Records",
        "short_label": "Full Applicant",
        "description": "Applicants acquiring a full licence after screening. These rows are not approved full licences until the registrar approves them.",
    },
    {
        "key": "full-approved",
        "record_type": "full_approved",
        "title": "Full-License Approved Records",
        "short_label": "Full Approved",
        "description": "Registrar-approved full licences. These practitioners can later apply for ATP / Authority to Practice renewal cycles.",
    },
    {
        "key": "provisional",
        "record_type": "provisional",
        "title": "Provisional Records",
        "short_label": "Provisional",
        "description": "Provisional registration rows for graduands and new applicants.",
    },
)
DASHBOARD_LICENSE_RECORD_TABLE_MAP = {
    config["key"]: config
    for config in DASHBOARD_LICENSE_RECORD_TABLES
}
DASHBOARD_LICENSE_ORDER_FIELDS = {
    "full_name": "full_name",
    "registration_no": "registration_no",
    "practitioner_number": "practitioner_number",
    "category": "category",
    "target_model": "target_model",
    "record_year": "record_year",
    "issued_date": "issued_date",
    "payment_date": "payment_date",
    "source_sheet_name": "source_sheet_name",
    "source_row": "source_row",
}
DASHBOARD_LICENSE_SEARCH_FIELDS = (
    "full_name",
    "registration_no",
    "practitioner_number",
    "category",
    "applicant_type",
    "nationality",
    "qualification_name",
    "institution_name",
    "workplace_address",
    "province",
    "source_sheet_name",
    "target_model",
)


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
    if is_data_quality_reviewer(user):
        return requested_office
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
    elif is_data_quality_reviewer(user):
        scope = requested_scope if requested_scope in {"medical", "nursing"} else None
    elif is_medical_board_staff(user):
        scope = "medical"
    elif is_nursing_council_staff(user):
        scope = "nursing"
    else:
        return queryset.none()

    if scope is None:
        return queryset

    practicing_content_type = ContentType.objects.get_for_model(PracticingLicenseRecord)
    receipt_content_type = ContentType.objects.get_for_model(Receipt)
    allowed_models = _duplicate_review_models_for_scope(scope)
    allowed_import_ids = PracticingLicenseRecord.objects.filter(
        target_model__in=_import_target_models_for_scope(scope),
    ).values("id")
    allowed_receipt_ids = _receipt_queryset_for_scope(scope).values("id")
    return queryset.filter(
        Q(content_type__model__in=allowed_models)
        | Q(content_type=practicing_content_type, object_id__in=Subquery(allowed_import_ids))
        | Q(content_type=receipt_content_type, object_id__in=Subquery(allowed_receipt_ids))
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
    try:
        message_url = reverse("enquiry_create") + "?" + urlencode({
            "recipient": f"record:{review.content_type_id}:{review.object_id}",
            "review": review.pk,
        })
        actions.append(format_html('<a href="{}" class="btn btn-sm btn-outline-warning">Message</a>', message_url))
    except NoReverseMatch:
        pass
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
        return queryset.filter(Q(category__in=['medical', 'chw']) | MEDICAL_BOARD_CADRE_NAME_FILTER)
    if scope == 'nursing':
        return queryset.filter(category__in=['nursing', 'midwifery']).exclude(MEDICAL_BOARD_CADRE_NAME_FILTER)
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
    if getattr(user, 'role', '') == 'reviewer' and can_manage_regulatory_operations(user):
        if is_medical_board_staff(user):
            if requested_office and requested_office != "medical":
                raise Http404("Financial forecast not available")
            return "medical"
        if is_nursing_council_staff(user):
            if requested_office and requested_office != "nursing":
                raise Http404("Financial forecast not available")
            return "nursing"
        return requested_office
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
    elif getattr(user, 'role', '') == 'reviewer' and can_manage_regulatory_operations(user):
        if is_medical_board_staff(user):
            allowed = [("medical", "Medical Board Financial Forecast")]
        elif is_nursing_council_staff(user):
            allowed = [("nursing", "Nursing Council Financial Forecast")]
        else:
            allowed = [
                ("all", "All Regulatory Offices"),
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
    medical_form_codes = sorted(MEDICAL_BOARD_FORM_CODES)
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


def _application_review_queryset_for_scope(scope=None):
    queryset = Application.objects.filter(status="pending").order_by("-submitted_date", "-id")
    if scope == "medical":
        return queryset.filter(form_code__in=MEDICAL_BOARD_FORM_CODES)
    if scope == "nursing":
        return queryset.filter(form_code__in=NURSING_FORM_CODES)
    return queryset


def _duplicate_review_queryset_for_scope(scope=None):
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


def _mobile_review_queryset_for_scope(scope=None):
    queryset = MobileSubmission.objects.exclude(
        status__in=["ACCEPTED", "PROMOTED", "REJECTED", "SUPERSEDED"]
    ).select_related("submitted_by", "device", "reviewed_by").order_by("-updated_at", "-received_at")
    if scope:
        queryset = queryset.filter(office_scope=scope)
    return queryset


def _mobile_account_request_queryset_for_scope(scope=None):
    queryset = MobileLocalAccountRequest.objects.filter(status="PENDING").select_related(
        "device",
        "linked_user",
        "reviewed_by",
    ).order_by("-updated_at", "-created_at")
    if scope:
        queryset = queryset.filter(office_scope=scope)
    return queryset


def _receipt_review_queryset_for_scope(scope=None):
    queryset = Receipt.objects.filter(status="pending").select_related("application", "user").order_by(
        "-transaction_date",
        "-id",
    )
    if scope == "medical":
        return queryset.filter(application__form_code__in=MEDICAL_BOARD_FORM_CODES)
    if scope == "nursing":
        return queryset.filter(application__form_code__in=NURSING_FORM_CODES)
    return queryset


def _review_scope_options_for_user(user):
    if getattr(user, "role", "") == "admin" or is_data_quality_reviewer(user):
        return [
            ("all", "All review work"),
            ("nursing", "Nursing Council"),
            ("medical", "Medical Board"),
        ]
    if is_medical_board_staff(user):
        return [("medical", "Medical Board")]
    if is_nursing_council_staff(user):
        return [("nursing", "Nursing Council")]
    return []


def _review_link_query(scope, key="scope"):
    if not scope:
        return ""
    return "?" + urlencode({key: scope})


def _review_centre_context(user, requested_scope=None):
    scope = _analytics_scope_for_user(user, requested_scope)
    scope_label = {
        None: "All review work",
        "nursing": "Nursing Council",
        "medical": "Medical Board",
    }[scope]

    application_reviews = _application_review_queryset_for_scope(scope)
    missing_reviews = _data_quality_review_queryset_for_user(user, requested_scope=scope)
    duplicate_reviews = _duplicate_review_queryset_for_scope(scope).filter(status="pending")
    mobile_reviews = _mobile_review_queryset_for_scope(scope)
    mobile_account_requests = _mobile_account_request_queryset_for_scope(scope)
    receipt_reviews = _receipt_review_queryset_for_scope(scope)
    complaint_reviews = open_complaint_cases(user)
    discipline_reviews = open_disciplinary_cases(user)
    if scope:
        complaint_reviews = complaint_reviews.filter(office_scope=scope)
        discipline_reviews = discipline_reviews.filter(office_scope=scope)

    counts = {
        "pending_applications": application_reviews.count(),
        "missing_data": missing_reviews.count(),
        "high_missing_data": missing_reviews.filter(severity="high").count(),
        "duplicate_reviews": duplicate_reviews.count(),
        "mobile_reviews": mobile_reviews.count(),
        "mobile_duplicate_risk": mobile_reviews.filter(status="DUPLICATE_RISK").count(),
        "mobile_needs_correction": mobile_reviews.filter(status="NEEDS_CORRECTION").count(),
        "mobile_account_requests": mobile_account_requests.count(),
        "receipt_reviews": receipt_reviews.count(),
        "complaint_cases": complaint_reviews.count(),
        "high_risk_complaint_cases": complaint_reviews.filter(risk_level__in=["high", "critical"]).count(),
        "disciplinary_cases": discipline_reviews.count(),
        "high_severity_disciplinary_cases": discipline_reviews.filter(severity__in=["high", "critical"]).count(),
    }
    counts["total_open"] = (
        counts["pending_applications"]
        + counts["missing_data"]
        + counts["duplicate_reviews"]
        + counts["mobile_reviews"]
        + counts["mobile_account_requests"]
        + counts["receipt_reviews"]
        + counts["complaint_cases"]
        + counts["disciplinary_cases"]
    )

    review_cards = [
        {
            "title": "Pending Applications",
            "count": counts["pending_applications"],
            "subtitle": "Registrar application decisions awaiting action.",
            "icon": "fas fa-clipboard-check",
            "theme": "primary",
            "href": reverse("nursing_council_portal") if scope != "medical" else reverse("medical_board_portal"),
        },
        {
            "title": "Data Quality Reviews",
            "count": counts["missing_data"],
            "subtitle": f"{counts['high_missing_data']} high-priority missing-data reviews.",
            "icon": "fas fa-exclamation-triangle",
            "theme": "warning",
            "href": reverse("production_readiness_dashboard") + _review_link_query(scope),
        },
        {
            "title": "Duplicate Reviews",
            "count": counts["duplicate_reviews"],
            "subtitle": "Possible duplicate people or repeated identifiers.",
            "icon": "fas fa-clone",
            "theme": "danger",
            "href": reverse("duplicate_review_workflow"),
        },
        {
            "title": "Mobile Intake Reviews",
            "count": counts["mobile_reviews"],
            "subtitle": f"{counts['mobile_duplicate_risk']} duplicate-risk and {counts['mobile_needs_correction']} correction items.",
            "icon": "fas fa-mobile-screen-button",
            "theme": "info",
            "href": reverse("mobile_intake_queue") + _review_link_query(scope, key="office_scope"),
        },
        {
            "title": "Mobile Account Requests",
            "count": counts["mobile_account_requests"],
            "subtitle": "Local Android account requests waiting for approval.",
            "icon": "fas fa-user-plus",
            "theme": "success",
            "href": reverse("mobile_intake_queue") + _review_link_query(scope, key="office_scope"),
        },
        {
            "title": "Pending Receipt Reviews",
            "count": counts["receipt_reviews"],
            "subtitle": "Payment rows that still need finance or registrar review.",
            "icon": "fas fa-receipt",
            "theme": "secondary",
            "href": reverse("financial_forecast_dashboard") + _review_link_query(scope),
        },
        {
            "title": "Complaints and ICMS",
            "count": counts["complaint_cases"],
            "subtitle": f"{counts['high_risk_complaint_cases']} high-risk complaint or incident cases.",
            "icon": "fas fa-scale-balanced",
            "theme": "danger",
            "href": reverse("complaint_case_list") + _review_link_query(scope, key="office"),
        },
        {
            "title": "Disciplinary Cases",
            "count": counts["disciplinary_cases"],
            "subtitle": f"{counts['high_severity_disciplinary_cases']} high-severity disciplinary matters.",
            "icon": "fas fa-gavel",
            "theme": "danger",
            "href": reverse("disciplinary_case_list") + _review_link_query(scope, key="office"),
        },
    ]

    return {
        "review_scope": scope or "all",
        "review_scope_label": scope_label,
        "review_scope_options": _review_scope_options_for_user(user),
        "review_counts": counts,
        "review_cards": review_cards,
        "recent_applications": application_reviews[:10],
        "recent_missing_reviews": missing_reviews.select_related("content_type").order_by(
            "-updated_at",
            "-missing_count",
        )[:10],
        "recent_duplicate_reviews": duplicate_reviews[:10],
        "recent_mobile_submissions": mobile_reviews.prefetch_related("attachments")[:10],
        "recent_mobile_account_requests": mobile_account_requests[:10],
        "recent_receipt_reviews": receipt_reviews[:10],
        "recent_complaint_cases": complaint_reviews[:10],
        "recent_disciplinary_cases": discipline_reviews[:10],
    }


WORKFLOW_TASK_TYPE_OPTIONS = [
    ("all", "All tasks"),
    ("application", "Applications"),
    ("missing_data", "Missing data"),
    ("duplicate", "Duplicates"),
    ("receipt", "Receipts"),
    ("document", "Documents"),
    ("import", "Imports"),
]
WORKFLOW_PRIORITY_OPTIONS = [
    ("all", "All priorities"),
    ("high", "High"),
    ("medium", "Medium"),
    ("low", "Low"),
]
WORKFLOW_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}


def _workflow_scope_from_request(user, request):
    scope = _workforce_scope_for_user(user)
    if getattr(user, "role", "") != "admin":
        return scope
    requested_scope = request.GET.get("scope")
    if requested_scope in {"nursing", "medical"}:
        return requested_scope
    return None


def _workflow_scope_label(scope):
    return {
        None: "All regulatory offices",
        "global": "All regulatory offices",
        "nursing": "Nursing Council",
        "medical": "Medical Board",
    }.get(scope, "All regulatory offices")


def _workflow_scope_options_for_user(user, selected_scope, request):
    if getattr(user, "role", "") == "admin":
        options = [
            ("all", "All offices", None),
            ("nursing", "Nursing Council", "nursing"),
            ("medical", "Medical Board", "medical"),
        ]
    elif is_medical_board_staff(user):
        options = [("medical", "Medical Board", "medical")]
    elif is_nursing_council_staff(user):
        options = [("nursing", "Nursing Council", "nursing")]
    else:
        options = [("all", "All offices", None)]

    selected_key = selected_scope or "all"
    scope_options = []
    for key, label, scope_value in options:
        params = request.GET.copy()
        if scope_value:
            params["scope"] = scope_value
        else:
            params.pop("scope", None)
        encoded = params.urlencode()
        scope_options.append({
            "key": key,
            "label": label,
            "selected": key == selected_key,
            "url": f"{request.path}?{encoded}" if encoded else request.path,
        })
    return scope_options


def _workflow_form_codes_for_scope(scope):
    if scope == "medical":
        return sorted(MEDICAL_BOARD_FORM_CODES)
    if scope == "nursing":
        return list(NURSING_FORM_CODES)
    return list(NURSING_FORM_CODES) + sorted(MEDICAL_BOARD_FORM_CODES)


def _workflow_import_source_kinds_for_scope(scope):
    if scope == "medical":
        return MEDICAL_IMPORT_SOURCE_KINDS
    if scope == "nursing":
        return NURSING_IMPORT_SOURCE_KINDS
    return NURSING_IMPORT_SOURCE_KINDS + MEDICAL_IMPORT_SOURCE_KINDS


def _workflow_pathway_definitions(scope):
    nursing_definitions = [
        {
            "key": "nursing_provisional",
            "office": "nursing",
            "label": "NC1 / Provisional licence",
            "description": "Graduand and first-time provisional licence pathway.",
            "form_codes": ["NC1", "NC4", "G1", "G2", "G3", "G4", "G5", "G6", "G7"],
        },
        {
            "key": "nursing_full",
            "office": "nursing",
            "label": "NC2 / Full licence",
            "description": "Progression from provisional record to full registration and licence.",
            "form_codes": ["NC2", "NC5", "NC6", "NC7", "NC10", "NC11"],
        },
        {
            "key": "nursing_atp",
            "office": "nursing",
            "label": "NC3 / ATP renewal",
            "description": "Annual practising licence and authority-to-practice renewal work.",
            "form_codes": ["NC3"],
        },
        {
            "key": "nursing_temporary",
            "office": "nursing",
            "label": "NC8 / Temporary licence",
            "description": "Temporary and special-case licence applications.",
            "form_codes": ["NC8", "NC9"],
        },
    ]
    medical_definitions = [
        {
            "key": "medical_registration",
            "office": "medical",
            "label": "Medical practitioner registration",
            "description": "Doctor registration, specialist, and renewal pathways.",
            "form_codes": ["MD1", "MD2", "MBSP", "MBRN"],
        },
        {
            "key": "medical_chw",
            "office": "medical",
            "label": "CHW registration and licence",
            "description": "Community Health Worker provisional, full, and registration work.",
            "form_codes": ["CHW1", "CHWP", "CHWF"],
        },
        {
            "key": "medical_facility_training",
            "office": "medical",
            "label": "Facilities and training accreditation",
            "description": "Medical Board facility and training college accreditation forms.",
            "form_codes": ["MBAC", "MBPF", "MBTC"],
        },
    ]
    if scope == "medical":
        return medical_definitions
    if scope == "nursing":
        return nursing_definitions
    return nursing_definitions + medical_definitions


def _workflow_pathway_for_form(form_code, pathway_definitions):
    form_code = str(form_code or "").upper()
    for definition in pathway_definitions:
        if form_code in definition["form_codes"]:
            return definition
    return {
        "key": "operations",
        "office": "general",
        "label": "Cross-cutting operations",
        "description": "Shared review and registry operations.",
        "form_codes": [],
    }


def _workflow_age_days(value):
    if not value:
        return 0
    if hasattr(value, "date") and hasattr(value, "hour"):
        value = timezone.localtime(value).date() if timezone.is_aware(value) else value.date()
    return max((timezone.localdate() - value).days, 0)


def _workflow_age_label(age_days):
    if age_days <= 0:
        return "Today"
    if age_days == 1:
        return "1 day"
    return f"{age_days} days"


def _workflow_priority_for_age(age_days, *, high_days=14, medium_days=7):
    if age_days >= high_days:
        return "high"
    if age_days >= medium_days:
        return "medium"
    return "low"


def _workflow_task_row(
    *,
    type_key,
    type_label,
    title,
    detail,
    priority,
    status,
    age_days,
    pathway,
    pathway_key,
    action_label,
    action_url,
    source="",
):
    return {
        "type_key": type_key,
        "type_label": type_label,
        "title": title,
        "detail": detail,
        "priority": priority,
        "priority_label": priority.title(),
        "priority_rank": WORKFLOW_PRIORITY_RANK.get(priority, 3),
        "status": status,
        "age_days": age_days,
        "age_label": _workflow_age_label(age_days),
        "pathway": pathway,
        "pathway_key": pathway_key,
        "action_label": action_label,
        "action_url": action_url,
        "source": source,
    }


def _workflow_application_label(application):
    payload = application.payload or {}
    for key in ["full_name", "applicant_name", "name", "student_name", "practitioner_name"]:
        value = payload.get(key)
        if value:
            return str(value)
    professional = getattr(application, "professional", None)
    if professional:
        return str(professional)
    return "Applicant not linked"


def _workflow_document_queryset_for_scope(scope):
    queryset = Document.objects.filter(status="draft").order_by("-updated_at", "-id")
    if scope in {"medical", "nursing"}:
        return queryset.filter(office_scope__in=["general", scope])
    return queryset


def _workflow_action_url_for_scope(scope):
    if scope == "medical":
        return reverse("medical_board_portal")
    if scope == "nursing":
        return reverse("nursing_council_portal")
    return reverse("advanced_dashboard")


def _workflow_task_queryset_counts(rows):
    type_counts = defaultdict(int)
    priority_counts = defaultdict(int)
    for row in rows:
        type_counts[row["type_key"]] += 1
        priority_counts[row["priority"]] += 1
    return type_counts, priority_counts


def _workflow_pathway_rows(scope, pathway_definitions, task_rows):
    application_queryset = Application.objects.all()
    form_codes = _workflow_form_codes_for_scope(scope)
    if form_codes:
        application_queryset = application_queryset.filter(form_code__in=form_codes)
    today = timezone.localdate()
    stale_cutoff = today - timedelta(days=14)
    pathway_task_counts = defaultdict(int)
    for row in task_rows:
        pathway_task_counts[row["pathway_key"]] += 1

    rows = []
    for definition in pathway_definitions:
        queryset = application_queryset.filter(form_code__in=definition["form_codes"])
        pending_count = queryset.filter(status="pending").count()
        approved_count = queryset.filter(status="approved").count()
        rejected_count = queryset.filter(status="rejected").count()
        rows.append({
            **definition,
            "form_codes_label": ", ".join(definition["form_codes"]),
            "pending_count": pending_count,
            "approved_count": approved_count,
            "rejected_count": rejected_count,
            "total_count": pending_count + approved_count + rejected_count,
            "aged_pending_count": queryset.filter(status="pending", submitted_date__lte=stale_cutoff).count(),
            "task_count": pathway_task_counts.get(definition["key"], 0),
            "action_url": _workflow_action_url_for_scope(definition.get("office")),
        })
    return rows


def _workflow_task_context(request, scope, base_context):
    pathway_definitions = _workflow_pathway_definitions(scope)
    form_codes = _workflow_form_codes_for_scope(scope)
    operations_pathway = {
        "key": "operations",
        "label": "Cross-cutting operations",
    }
    rows = []

    applications = Application.objects.filter(status="pending", form_code__in=form_codes).order_by("-submitted_date", "-id")[:40]
    for application in applications:
        pathway = _workflow_pathway_for_form(application.form_code, pathway_definitions)
        age_days = _workflow_age_days(application.submitted_date)
        rows.append(_workflow_task_row(
            type_key="application",
            type_label="Application",
            title=f"{application.form_code} pending application",
            detail=_workflow_application_label(application),
            priority=_workflow_priority_for_age(age_days),
            status=application.get_status_display(),
            age_days=age_days,
            pathway=pathway["label"],
            pathway_key=pathway["key"],
            action_label="Review",
            action_url=reverse("application_detail", args=[application.pk]),
            source=application.form_title or application.get_form_code_display(),
        ))

    missing_reviews = _data_quality_review_queryset_for_user(
        request.user,
        requested_scope=scope,
    ).select_related("content_type").order_by("-severity", "-missing_count", "-updated_at")[:40]
    for review in missing_reviews:
        missing_fields = ", ".join(str(value) for value in (review.missing_fields or [])[:3])
        if review.missing_count > 3:
            missing_fields = f"{missing_fields}, +{review.missing_count - 3} more" if missing_fields else f"{review.missing_count} fields"
        message_url = reverse("enquiry_create") + "?" + urlencode({
            "recipient": f"record:{review.content_type_id}:{review.object_id}",
            "review": review.pk,
        })
        rows.append(_workflow_task_row(
            type_key="missing_data",
            type_label="Missing data",
            title=review.full_name or review.registration_no or "Record missing required data",
            detail=missing_fields or "Missing data review needs registrar attention.",
            priority=review.severity if review.severity in WORKFLOW_PRIORITY_RANK else "medium",
            status=review.get_status_display(),
            age_days=_workflow_age_days(review.updated_at),
            pathway=operations_pathway["label"],
            pathway_key=operations_pathway["key"],
            action_label="Message",
            action_url=message_url,
            source=review.professional_type or (review.content_type.model_class().__name__ if review.content_type.model_class() else review.content_type.model),
        ))

    duplicates = _duplicate_review_queryset_for_scope(scope).filter(status="pending")[:40]
    for duplicate in duplicates:
        priority = "high" if duplicate.similarity_score >= 0.9 else "medium"
        rows.append(_workflow_task_row(
            type_key="duplicate",
            type_label="Duplicate",
            title="Possible duplicate record",
            detail=f"{duplicate.content_type.model.title()} similarity {duplicate.similarity_score:.0%}",
            priority=priority,
            status="Pending",
            age_days=0,
            pathway=operations_pathway["label"],
            pathway_key=operations_pathway["key"],
            action_label="Open queue",
            action_url=reverse("duplicate_review_workflow"),
            source="Duplicate review",
        ))

    receipts = _receipt_queryset_for_scope(scope).filter(
        Q(status="pending") | Q(payer_match_confidence__in=["unlinked", "ambiguous"])
    ).order_by("-transaction_date", "-id")[:40]
    for receipt in receipts:
        age_days = _workflow_age_days(receipt.transaction_date)
        amount = receipt.amount or 0
        priority = "high" if receipt.payer_match_confidence in {"unlinked", "ambiguous"} or amount >= 200 else _workflow_priority_for_age(age_days)
        rows.append(_workflow_task_row(
            type_key="receipt",
            type_label="Receipt",
            title=f"Receipt {receipt.receipt_number}",
            detail=f"K{amount} - {receipt.get_payer_match_confidence_display()}",
            priority=priority,
            status=receipt.get_status_display(),
            age_days=age_days,
            pathway=operations_pathway["label"],
            pathway_key=operations_pathway["key"],
            action_label="Finance",
            action_url=reverse("financial_forecast_dashboard") + _review_link_query(scope, key="office"),
            source=receipt.description or "Payment review",
        ))

    documents = _workflow_document_queryset_for_scope(scope)[:25]
    for document in documents:
        age_days = _workflow_age_days(document.updated_at)
        rows.append(_workflow_task_row(
            type_key="document",
            type_label="Document",
            title=document.title,
            detail=f"{document.get_office_scope_display()} repository draft",
            priority=_workflow_priority_for_age(age_days, high_days=30, medium_days=14),
            status=document.get_status_display(),
            age_days=age_days,
            pathway=operations_pathway["label"],
            pathway_key=operations_pathway["key"],
            action_label="Repository",
            action_url=reverse("repository_search"),
            source="Document repository",
        ))

    latest_import_batch = base_context.get("latest_import_batch")
    if latest_import_batch is None:
        latest_import_batch = DataImportBatch.objects.filter(
            source_kind__in=_workflow_import_source_kinds_for_scope(scope),
        ).order_by("-started_at").first()
    if latest_import_batch:
        priority = "high" if latest_import_batch.status == "failed" else "medium" if latest_import_batch.status in {"pending", "running"} else "low"
        rows.append(_workflow_task_row(
            type_key="import",
            type_label="Import",
            title=latest_import_batch.source_file_name,
            detail=f"{latest_import_batch.processed_rows} of {latest_import_batch.total_rows} rows processed",
            priority=priority,
            status=latest_import_batch.get_status_display(),
            age_days=_workflow_age_days(latest_import_batch.started_at),
            pathway=operations_pathway["label"],
            pathway_key=operations_pathway["key"],
            action_label="Import",
            action_url=reverse("import_data"),
            source="Latest workbook batch",
        ))

    rows.sort(key=lambda row: (row["priority_rank"], -row["age_days"], row["title"]))
    all_rows = rows
    type_filter = request.GET.get("task_type", "all")
    priority_filter = request.GET.get("priority", "all")
    pathway_filter = request.GET.get("pathway", "all")
    valid_types = {key for key, _label in WORKFLOW_TASK_TYPE_OPTIONS}
    valid_priorities = {key for key, _label in WORKFLOW_PRIORITY_OPTIONS}
    valid_pathways = {"all", "operations"} | {definition["key"] for definition in pathway_definitions}
    if type_filter not in valid_types:
        type_filter = "all"
    if priority_filter not in valid_priorities:
        priority_filter = "all"
    if pathway_filter not in valid_pathways:
        pathway_filter = "all"

    if type_filter != "all":
        rows = [row for row in rows if row["type_key"] == type_filter]
    if priority_filter != "all":
        rows = [row for row in rows if row["priority"] == priority_filter]
    if pathway_filter != "all":
        rows = [row for row in rows if row["pathway_key"] == pathway_filter]

    type_counts, priority_counts = _workflow_task_queryset_counts(all_rows)
    pathway_options = [
        {"key": "all", "label": "All pathways"},
        *[
            {"key": definition["key"], "label": definition["label"]}
            for definition in pathway_definitions
        ],
        {"key": "operations", "label": operations_pathway["label"]},
    ]
    return {
        "workflow_scope": scope or "all",
        "workflow_scope_label": _workflow_scope_label(scope),
        "workflow_scope_options": _workflow_scope_options_for_user(request.user, scope, request),
        "workflow_task_rows": rows[:50],
        "workflow_task_total_count": len(all_rows),
        "workflow_filtered_task_count": len(rows),
        "workflow_high_priority_count": priority_counts.get("high", 0),
        "workflow_medium_priority_count": priority_counts.get("medium", 0),
        "workflow_pending_application_count": type_counts.get("application", 0),
        "workflow_missing_data_count": type_counts.get("missing_data", 0),
        "workflow_duplicate_count": type_counts.get("duplicate", 0),
        "workflow_receipt_count": type_counts.get("receipt", 0),
        "workflow_task_type_options": [
            {
                "key": key,
                "label": label,
                "count": len(all_rows) if key == "all" else type_counts.get(key, 0),
            }
            for key, label in WORKFLOW_TASK_TYPE_OPTIONS
        ],
        "workflow_priority_options": [
            {
                "key": key,
                "label": label,
                "count": len(all_rows) if key == "all" else priority_counts.get(key, 0),
            }
            for key, label in WORKFLOW_PRIORITY_OPTIONS
        ],
        "workflow_pathway_options": pathway_options,
        "workflow_task_filters": {
            "task_type": type_filter,
            "priority": priority_filter,
            "pathway": pathway_filter,
        },
        "workflow_pathway_rows": _workflow_pathway_rows(scope, pathway_definitions, all_rows),
        "workflow_quick_links": [
            {"label": "Staff AI", "url": reverse("staff_ai_assistant"), "icon": "fas fa-robot"},
            {"label": "Duplicate Review", "url": reverse("duplicate_review_workflow"), "icon": "fas fa-clone"},
            {"label": "Import Data", "url": reverse("import_data"), "icon": "fas fa-file-import"},
            {"label": "Repository", "url": reverse("repository_search"), "icon": "fas fa-folder-open"},
        ],
    }


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
    if getattr(user, "professional_record_status", "") != "linked":
        return None

    linked_professional = getattr(user, "professional_record", None)
    if linked_professional:
        if isinstance(linked_professional, model):
            return linked_professional
        if model is NursingProfessional and isinstance(linked_professional, Midwife):
            return linked_professional
    identifiers = [
        value for value in [
            getattr(user, 'registration_number', None),
            getattr(user, 'license_number', None),
            user.username,
        ]
        if value
    ]
    email = str(getattr(user, "email", "") or "").strip()
    if not identifiers and not email:
        return None

    query = Q()
    if identifiers:
        query |= Q(registration_no__in=identifiers)
    if email:
        query |= Q(email__iexact=email)
    if not query:
        return None
    return model.objects.filter(query).first()


def _account_record_link_context(user):
    return {
        'professional_record_status': getattr(user, 'professional_record_status', 'unmatched'),
        'professional_link_review_note': getattr(user, 'professional_link_review_note', ''),
        'next_registration_url_name': get_next_url_name_for_role(getattr(user, 'role', '')),
    }


def _nursing_user_link_identifiers(user):
    identifiers = []
    for value in [
        getattr(user, "registration_number", ""),
        getattr(user, "license_number", ""),
        getattr(user, "national_id", ""),
    ]:
        value = str(value or "").strip()
        if value and value not in identifiers:
            identifiers.append(value)
    return identifiers


def _nursing_unlinked_candidate_matches(user, *, limit=6):
    identifiers = _nursing_user_link_identifiers(user)
    email = str(getattr(user, "email", "") or "").strip()
    first_name = str(getattr(user, "first_name", "") or "").strip()
    last_name = str(getattr(user, "last_name", "") or "").strip()
    candidates = []
    seen = set()

    for model, category in [
        (NursingProfessional, "Registered Nurse"),
        (Midwife, "Midwife"),
        (NurseAide, "Nurse Aide"),
    ]:
        query = Q()
        for identifier in identifiers:
            query |= Q(registration_no__iexact=identifier) | Q(registration_number__iexact=identifier)
        if email:
            query |= Q(email__iexact=email)
        if first_name and last_name:
            query |= Q(first_name__iexact=first_name, last_name__iexact=last_name)
        if not query:
            continue
        for professional in model.objects.filter(query).order_by("last_name", "first_name")[:limit]:
            key = (model._meta.label_lower, professional.pk)
            if key in seen:
                continue
            seen.add(key)
            candidates.append({
                "source": "Operational register",
                "name": f"{professional.first_name} {professional.last_name}".strip(),
                "registration": professional.registration_no or "-",
                "practitioner": professional.registration_number or "-",
                "category": category,
                "status": "Can be linked after registrar review",
                "confidence": "Strong",
            })
            if len(candidates) >= limit:
                return candidates

    analytics_query = Q()
    for identifier in identifiers:
        analytics_query |= Q(registration_nos__icontains=identifier) | Q(practitioner_nos__icontains=identifier)
    if first_name and last_name:
        analytics_query |= Q(representative_name__icontains=first_name) & Q(representative_name__icontains=last_name)
    if analytics_query:
        analytics_rows = (
            NursingPractitionerIndex.objects.filter(analytics_query, snapshot__is_active=True)
            .order_by("-latest_year", "representative_name")[:limit]
        )
        for row in analytics_rows:
            key = ("analytics", row.pk)
            if key in seen:
                continue
            seen.add(key)
            candidates.append({
                "source": "Read-only analytics index",
                "name": row.representative_name or row.person_group_key or "-",
                "registration": row.registration_nos or "-",
                "practitioner": row.practitioner_nos or "-",
                "category": row.latest_cadre or "Nursing",
                "status": "Registrar verification required",
                "confidence": row.identity_confidence or ("Review" if row.needs_manual_review else "Possible"),
            })
            if len(candidates) >= limit:
                return candidates

    return candidates


def _nursing_unlinked_portal_context(user):
    identifiers = _nursing_user_link_identifiers(user)
    supplied_identifier = identifiers[0] if identifiers else ""
    status = getattr(user, "professional_record_status", "unmatched") or "unmatched"
    status_label = str(status).replace("_", " ").title()
    if status == "unmatched":
        status_label = "Not linked"
    elif status == "pending_review":
        status_label = "Pending registrar review"

    registration_url = reverse("nursing_forms_portal")
    next_url_name = get_next_url_name_for_role(getattr(user, "role", ""))
    if next_url_name:
        try:
            registration_url = reverse(next_url_name)
        except NoReverseMatch:
            registration_url = reverse("nursing_forms_portal")

    role = getattr(user, "role", "")
    role_setup = {
        "nurse": {
            "title": "PNG Nursing Council Account Setup",
            "primary_label": "Continue Nursing Forms",
            "primary_detail": "NC1 provisional, NC2 full licence, NC3 renewal, and supporting evidence.",
            "pathway_label": "NC1 provisional, NC2 full licence, and NC3 ATP / renewal.",
        },
        "nurse_aide": {
            "title": "Nurse Aide Account Setup",
            "primary_label": "Continue Nurse Aide Form",
            "primary_detail": "Nurse aide registration, training evidence, employer details, and receipts.",
            "pathway_label": "Nurse aide registration and ongoing learning evidence.",
        },
        "graduand": {
            "title": "Graduand Account Setup",
            "primary_label": "Continue Graduand Forms",
            "primary_detail": "G1-G4 evidence, graduate vitae, competency evidence, and NC1 provisional licence.",
            "pathway_label": "Graduand record, competency evidence, and provisional licence pathway.",
        },
        "student": {
            "title": "Graduand Account Setup",
            "primary_label": "Continue Graduand Forms",
            "primary_detail": "G1-G4 evidence, graduate vitae, competency evidence, and NC1 provisional licence.",
            "pathway_label": "Graduand record, competency evidence, and provisional licence pathway.",
        },
    }.get(role, {
        "title": "Nursing Council Account Setup",
        "primary_label": "Continue Nursing Forms",
        "primary_detail": "Complete the correct Nursing Council pathway and supporting evidence.",
        "pathway_label": "Nursing Council registration pathway.",
    })
    candidate_matches = _nursing_unlinked_candidate_matches(user)
    account_name = f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip() or getattr(user, "username", "")
    return {
        "nursing_unlinked_title": role_setup["title"],
        "nursing_unlinked_pathway_label": role_setup["pathway_label"],
        "nursing_unlinked_account": {
            "name": account_name,
            "email": getattr(user, "email", "") or "-",
            "identifier": supplied_identifier or "-",
            "status": status_label,
            "candidate_count": len(candidate_matches),
        },
        "nursing_unlinked_actions": [
            {
                "label": role_setup["primary_label"],
                "href": registration_url,
                "icon": "fas fa-file-signature",
                "detail": role_setup["primary_detail"],
            },
            {
                "label": "Search Public Register",
                "href": reverse("public_nursing_register_search_root"),
                "icon": "fas fa-search",
                "detail": "Check the public-safe register before requesting a correction.",
            },
            {
                "label": "Request Record Link",
                "href": reverse("enquiry_create"),
                "icon": "fas fa-envelope",
                "detail": "Ask the registrar to review existing registration or ATP details.",
            },
            {
                "label": "Update Profile",
                "href": reverse("user_profile"),
                "icon": "fas fa-user-cog",
                "detail": "Confirm contact details, registration number, and licence number.",
            },
        ],
        "nursing_unlinked_checklist": [
            {"label": "Account created", "complete": True},
            {"label": "Registration or licence number supplied", "complete": bool(supplied_identifier)},
            {"label": "Possible existing match found", "complete": bool(candidate_matches)},
            {"label": "Professional record linked", "complete": False},
        ],
        "nursing_candidate_matches": candidate_matches,
        "nursing_public_verification_url": reverse("public_nursing_register_search_root"),
        "nursing_forms_url": reverse("nursing_forms_portal"),
        "nursing_help_actions": [
            {"label": "Create enquiry", "href": reverse("enquiry_create"), "icon": "fas fa-envelope", "detail": "Ask the Nursing Council team to review your record."},
            {"label": "Helpdesk", "href": reverse("helpdesk"), "icon": "fas fa-headset", "detail": "Get account, form, or document guidance."},
            {"label": "FAQs", "href": reverse("public_faqs"), "icon": "fas fa-circle-question", "detail": "Open public Nursing Council guidance."},
            {"label": "My profile", "href": reverse("user_profile"), "icon": "fas fa-user-cog", "detail": "Update account and contact details."},
        ],
    }


def _medical_user_link_identifiers(user):
    identifiers = []
    for value in [
        getattr(user, "registration_number", ""),
        getattr(user, "license_number", ""),
        getattr(user, "national_id", ""),
    ]:
        value = str(value or "").strip()
        if value and value not in identifiers:
            identifiers.append(value)
    return identifiers


def _medical_unlinked_candidate_matches(user, *, limit=6):
    identifiers = _medical_user_link_identifiers(user)
    email = str(getattr(user, "email", "") or "").strip()
    first_name = str(getattr(user, "first_name", "") or "").strip()
    last_name = str(getattr(user, "last_name", "") or "").strip()
    candidates = []
    seen = set()

    for model, category in [
        (MedicalDoctor, "Medical Doctor / Specialist"),
        (CommunityHealthWorker, "Community Health Worker"),
    ]:
        query = Q()
        for identifier in identifiers:
            query |= Q(registration_no__iexact=identifier) | Q(registration_number__iexact=identifier)
        if email:
            query |= Q(email__iexact=email)
        if first_name and last_name:
            query |= Q(first_name__iexact=first_name, last_name__iexact=last_name)
        if not query:
            continue
        for professional in model.objects.filter(query).order_by("last_name", "first_name")[:limit]:
            key = (model._meta.label_lower, professional.pk)
            if key in seen:
                continue
            seen.add(key)
            candidates.append({
                "source": "Operational Medical Board register",
                "name": f"{professional.first_name} {professional.last_name}".strip(),
                "registration": professional.registration_no or "-",
                "practitioner": (
                    getattr(professional, "registration_number", "")
                    or getattr(professional, "community_id", "")
                    or "-"
                ),
                "category": category,
                "status": "Can be linked after registrar review",
                "confidence": "Strong",
            })
            if len(candidates) >= limit:
                return candidates
    return candidates


def _medical_unlinked_portal_context(user):
    identifiers = _medical_user_link_identifiers(user)
    supplied_identifier = identifiers[0] if identifiers else ""
    status = getattr(user, "professional_record_status", "unmatched") or "unmatched"
    status_label = str(status).replace("_", " ").title()
    if status == "unmatched":
        status_label = "Not linked"
    elif status == "pending_review":
        status_label = "Pending registrar review"

    registration_url = reverse("medical_board_register")
    next_url_name = get_next_url_name_for_role(getattr(user, "role", ""))
    if next_url_name:
        try:
            registration_url = reverse(next_url_name)
        except NoReverseMatch:
            registration_url = reverse("medical_board_register")

    role = getattr(user, "role", "")
    role_setup = {
        "doctor": {
            "title": "Medical Board Account Setup",
            "primary_label": "Continue Doctor Form",
            "primary_detail": "Medical registration, scope/specialty details, documents, and payment evidence.",
            "pathway_label": "Medical Board registration and practising certificate pathway.",
        },
        "chw": {
            "title": "CHW Account Setup",
            "primary_label": "Continue CHW Form",
            "primary_detail": "Community Health Worker registration, training evidence, and payment evidence.",
            "pathway_label": "CHW registration and Medical Board review pathway.",
        },
    }.get(role, {
        "title": "Medical Board Account Setup",
        "primary_label": "Continue Medical Board Forms",
        "primary_detail": "Complete the correct Medical Board pathway and supporting evidence.",
        "pathway_label": "Medical Board registration pathway.",
    })
    candidate_matches = _medical_unlinked_candidate_matches(user)
    account_name = f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip() or getattr(user, "username", "")
    return {
        "medical_unlinked_title": role_setup["title"],
        "medical_unlinked_pathway_label": role_setup["pathway_label"],
        "medical_unlinked_account": {
            "name": account_name,
            "email": getattr(user, "email", "") or "-",
            "identifier": supplied_identifier or "-",
            "status": status_label,
            "candidate_count": len(candidate_matches),
        },
        "medical_unlinked_actions": [
            {
                "label": role_setup["primary_label"],
                "href": registration_url,
                "icon": "fas fa-file-medical",
                "detail": role_setup["primary_detail"],
            },
            {
                "label": "Search Public Register",
                "href": reverse("public_medical_board_register_search_root"),
                "icon": "fas fa-search",
                "detail": "Check the public-safe Medical Board register before requesting a correction.",
            },
            {
                "label": "Request Record Link",
                "href": reverse("enquiry_create"),
                "icon": "fas fa-envelope",
                "detail": "Ask the Medical Board registrar to review existing registration details.",
            },
            {
                "label": "Update Profile",
                "href": reverse("user_profile"),
                "icon": "fas fa-user-cog",
                "detail": "Confirm contact details, registration number, and licence number.",
            },
        ],
        "medical_unlinked_checklist": [
            {"label": "Account created", "complete": True},
            {"label": "Registration or licence number supplied", "complete": bool(supplied_identifier)},
            {"label": "Possible existing match found", "complete": bool(candidate_matches)},
            {"label": "Professional record linked", "complete": False},
        ],
        "medical_candidate_matches": candidate_matches,
        "medical_help_actions": [
            {"label": "Create enquiry", "href": reverse("enquiry_create"), "icon": "fas fa-envelope", "detail": "Ask the Medical Board team to review your record."},
            {"label": "Helpdesk", "href": reverse("helpdesk"), "icon": "fas fa-headset", "detail": "Get account, form, or document guidance."},
            {"label": "FAQs", "href": reverse("public_faqs"), "icon": "fas fa-circle-question", "detail": "Open public registration guidance."},
            {"label": "My profile", "href": reverse("user_profile"), "icon": "fas fa-user-cog", "detail": "Update account and contact details."},
        ],
        "medical_public_verification_url": reverse("public_medical_board_register_search_root"),
        "medical_board_forms_url": reverse("medical_board_register"),
    }


def _applications_for(obj):
    if not obj:
        return Application.objects.none()
    from django.contrib.contenttypes.models import ContentType

    ct = ContentType.objects.get_for_model(obj)
    return Application.objects.filter(content_type=ct, object_id=obj.id)


def _receipt_queryset_for_user(user):
    query = Q(user=user)
    professional = getattr(user, "professional_record", None)
    if professional:
        professional_ct = ContentType.objects.get_for_model(professional)
        query |= Q(application__content_type=professional_ct, application__object_id=professional.pk)
        query |= Q(payer_content_type=professional_ct, payer_object_id=professional.pk)

        identifiers = [
            getattr(professional, "registration_no", ""),
            getattr(professional, "registration_number", ""),
            getattr(user, "registration_number", ""),
            getattr(user, "license_number", ""),
            getattr(user, "national_id", ""),
        ]
        identifiers = [str(value).strip() for value in identifiers if str(value or "").strip()]
        record_query = Q()
        for value in identifiers:
            record_query |= Q(registration_no__iexact=value) | Q(practitioner_number__iexact=value)

        full_name = f"{getattr(professional, 'first_name', '')} {getattr(professional, 'last_name', '')}".strip()
        if full_name and getattr(professional, "date_of_birth", None):
            record_query |= Q(full_name__iexact=full_name, date_of_birth=professional.date_of_birth)

        if record_query:
            imported_record_ids = PracticingLicenseRecord.objects.filter(record_query).values("id")
            imported_ct = ContentType.objects.get_for_model(PracticingLicenseRecord)
            query |= Q(payer_content_type=imported_ct, payer_object_id__in=Subquery(imported_record_ids))

    return (
        Receipt.objects
        .filter(query)
        .select_related("application", "payer_content_type")
        .distinct()
        .order_by("-transaction_date")
    )


def _medical_professional_identity_query(professional):
    query = Q()
    values = [
        getattr(professional, "registration_no", ""),
        getattr(professional, "registration_number", ""),
        getattr(professional, "community_id", ""),
    ]
    for value in values:
        value = str(value or "").strip()
        if value:
            query |= Q(registration_no__iexact=value) | Q(practitioner_number__iexact=value)
    full_name = f"{getattr(professional, 'first_name', '')} {getattr(professional, 'last_name', '')}".strip()
    if full_name:
        query |= Q(full_name__iexact=full_name)
    return query


def _medical_professional_import_records(professional, target_model):
    identity_query = _medical_professional_identity_query(professional)
    if not identity_query:
        return PracticingLicenseRecord.objects.none()
    return _quality_approved_practicing_records().filter(
        identity_query,
        batch__source_kind__in=MEDICAL_IMPORT_SOURCE_KINDS,
        target_model=target_model,
    )


def _medical_professional_active_conditions(professional):
    content_type = ContentType.objects.get_for_model(professional)
    registration_number = str(getattr(professional, "registration_no", "") or "").strip()
    query = Q(subject_content_type=content_type, subject_object_id=professional.pk)
    if registration_number:
        query |= Q(subject_identifier__iexact=registration_number)
    return RegulatoryDecisionRecord.objects.filter(
        query,
        office_scope="medical",
        status="final",
    ).exclude(conditions="").filter(
        Q(expiry_date__isnull=True) | Q(expiry_date__gte=date.today())
    ).order_by("-decided_at", "-updated_at")


def _medical_professional_status_context(professional, applications, *, audience):
    if not professional:
        return {
            "medical_status": None,
            "medical_assurance_cards": [],
            "medical_readiness_items": [],
            "medical_condition_decisions": [],
            "medical_recent_cpd": [],
        }

    today = date.today()
    is_doctor = isinstance(professional, MedicalDoctor)
    target_model = "medicaldoctor" if is_doctor else "communityhealthworker"
    expiry = getattr(professional, "license_expiry_date", None)
    days_left = (expiry - today).days if expiry else None
    import_records = _medical_professional_import_records(professional, target_model)
    latest_practicing_record = import_records.filter(record_type="practicing_license").order_by("-record_year", "-issued_date").first()
    latest_register_record = import_records.filter(record_type__in=["full", "full_approved", "workforce_listing"]).order_by("-record_year", "-issued_date").first()

    if not getattr(professional, "is_active", True):
        status_label = "Inactive"
        status_theme = "secondary"
    elif expiry and expiry < today:
        status_label = "Expired"
        status_theme = "danger"
    elif expiry and days_left is not None and days_left <= 90:
        status_label = "Expiring"
        status_theme = "warning"
    elif expiry:
        status_label = "Active"
        status_theme = "success"
    elif latest_practicing_record:
        status_label = "Practising certificate recorded"
        status_theme = "success"
    elif latest_register_record or isinstance(professional, CommunityHealthWorker):
        status_label = "Registered"
        status_theme = "success"
    else:
        status_label = "Registration pending verification"
        status_theme = "warning"

    content_type = ContentType.objects.get_for_model(professional)
    cpd_records = CPDRecord.objects.filter(content_type=content_type, object_id=professional.pk).order_by("-start_date")
    cpd_total = cpd_records.aggregate(total=Sum("hours_credits")).get("total") or 0
    receipts = _receipt_queryset_for_user(getattr(professional, "user", None)) if getattr(professional, "user", None) else Receipt.objects.none()
    has_completed_receipt = Receipt.objects.filter(application__in=applications, status="completed").exists()
    condition_decisions = list(_medical_professional_active_conditions(professional)[:5])
    latest_application = applications.order_by("-submitted_date").first() if hasattr(applications, "order_by") else None

    qualification_value = getattr(professional, "specialty", "") if is_doctor else getattr(professional, "training_level", "")
    readiness_items = [
        {"label": "Identity", "complete": bool(getattr(professional, "registration_no", "") and getattr(professional, "first_name", "") and getattr(professional, "last_name", ""))},
        {"label": "Qualification / scope", "complete": bool(qualification_value or getattr(professional, "cadre_id", None) or latest_register_record)},
        {"label": "Practising certificate", "complete": bool(status_label in {"Active", "Expiring", "Practising certificate recorded", "Registered"} and status_label != "Expired")},
        {"label": "CPD / CME", "complete": bool(cpd_total or not is_doctor)},
        {"label": "Payment receipt", "complete": bool(has_completed_receipt)},
        {"label": "Conditions reviewed", "complete": not condition_decisions},
    ]
    complete_count = sum(1 for item in readiness_items if item["complete"])
    readiness_percent = round((complete_count / len(readiness_items)) * 100)

    assurance_cards = [
        {
            "label": "Register status",
            "value": status_label,
            "theme": status_theme,
            "detail": f"Expiry {expiry:%d %b %Y}" if expiry else "No expiry date captured",
        },
        {
            "label": "Renewal readiness",
            "value": f"{readiness_percent}%",
            "theme": "success" if readiness_percent >= 80 else "warning" if readiness_percent >= 50 else "danger",
            "detail": f"{complete_count} of {len(readiness_items)} checks complete",
        },
        {
            "label": "CPD / CME",
            "value": f"{cpd_total:g}",
            "theme": "success" if cpd_total else "secondary",
            "detail": "Recorded hours / credits",
        },
        {
            "label": "Conditions",
            "value": len(condition_decisions),
            "theme": "danger" if condition_decisions else "success",
            "detail": "Active final decision conditions",
        },
    ]

    category = "Medical Doctor / Specialist" if is_doctor else "Community Health Worker"
    public_register_preview = {
        "full_name": f"{getattr(professional, 'first_name', '')} {getattr(professional, 'last_name', '')}".strip(),
        "registration_number": getattr(professional, "registration_no", "") or "",
        "practitioner_number": (
            getattr(professional, "registration_number", "")
            or getattr(professional, "community_id", "")
            or ""
        ),
        "professional_category": category,
        "licence_status": status_label,
        "licence_expiry_date": expiry,
        "eligible_to_practice": status_label in {"Active", "Expiring", "Practising certificate recorded", "Registered"},
        "conditions_summary": "Active conditions recorded" if condition_decisions else "No active public conditions recorded",
    }
    primary_action = {
        "label": "Open Medical Board Forms",
        "url": reverse("medical_board_register"),
        "theme": "primary",
        "detail": "Submit registration, renewal, or supporting Medical Board evidence.",
    }
    if is_doctor:
        primary_action.update({
            "label": "Renew / Update Registration",
            "url": reverse("medical_board_register"),
            "detail": "Maintain registration, practising certificate, CME, documents, and receipts.",
        })
        if status_label == "Expired":
            primary_action.update({"label": "Renew Now", "theme": "danger", "detail": "Your licence has expired or is not current."})
        elif status_label == "Expiring":
            primary_action.update({"label": "Renew Before Expiry", "theme": "warning", "detail": f"{days_left} days remaining" if days_left is not None else "Renewal window is open."})
    else:
        primary_action.update({
            "label": "Update CHW Registration",
            "url": reverse("public_chw_register"),
            "theme": "success",
            "detail": "Keep CHW registration, training evidence, and payment records current.",
        })

    return {
        "medical_status": {
            "label": status_label,
            "theme": status_theme,
            "expiry": expiry,
            "days_left": days_left,
            "latest_application": latest_application,
            "latest_practicing_record": latest_practicing_record,
            "latest_register_record": latest_register_record,
            "audience": audience,
        },
        "medical_assurance_cards": assurance_cards,
        "medical_readiness_items": readiness_items,
        "medical_readiness_percent": readiness_percent,
        "medical_condition_decisions": condition_decisions,
        "medical_recent_cpd": list(cpd_records[:5]),
        "medical_cpd_total": cpd_total,
        "medical_public_register_preview": public_register_preview,
        "medical_primary_action": primary_action,
        "medical_help_actions": [
            {"label": "Create enquiry", "href": reverse("enquiry_create"), "icon": "fas fa-envelope", "detail": "Ask the Medical Board team to review your record."},
            {"label": "Helpdesk", "href": reverse("helpdesk"), "icon": "fas fa-headset", "detail": "Get account, form, or document guidance."},
            {"label": "FAQs", "href": reverse("public_faqs"), "icon": "fas fa-circle-question", "detail": "Open public registration guidance."},
            {"label": "My profile", "href": reverse("user_profile"), "icon": "fas fa-user-cog", "detail": "Update account and contact details."},
        ],
        "medical_public_verification_url": reverse("public_medical_board_register_search_root"),
        "medical_board_forms_url": reverse("medical_board_register"),
    }


def _medical_public_licence_status_for_dashboard(professional):
    expiry = getattr(professional, "license_expiry_date", None)
    if not getattr(professional, "is_active", True):
        return "Inactive"
    if expiry and expiry < date.today():
        return "Expired"
    if expiry:
        return "Active"
    return "Registered"


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
    cleaned = text[:120].title()
    return re.sub(r"\bNgo\b", "NGO", cleaned)


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
    record_type = record.get("record_type") if isinstance(record, dict) else getattr(record, "record_type", "")
    return dict(PracticingLicenseRecord.RECORD_TYPE_CHOICES).get(record_type, record_type or "-")


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


def _imported_facility_worker_context(latest_batch=None, target_models=None, limit=100, scope=None):
    records = _quality_approved_practicing_records().exclude(workplace_address__isnull=True).exclude(workplace_address='')
    if latest_batch:
        records = records.filter(batch=latest_batch)
    elif scope in {'medical', 'nursing'}:
        # A target model alone is not an office boundary: legacy Nursing rows can
        # be stored as ``other``.  Always bind a scoped facility report to its
        # own workbook source before calculating facility or cadre totals.
        records = records.filter(batch__source_kind__in=_import_source_kinds_for_scope(scope))
    if target_models:
        records = records.filter(target_model__in=target_models)
    records = records.filter(record_type__in=FACILITY_WORKER_RECORD_TYPES)

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
        item['pipeline_identities'] = defaultdict(set)
        item['identities'] = set()

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
            'province',
            'issued_date',
        ).order_by('-record_year', 'full_name')
        for record in facility_record_rows:
            item = rows_by_facility[raw_to_facility[record['workplace_address']]]
            item['category_counts'][_display_category(record)] += 1
            identity = _record_identity_key(
                record.get('registration_no'),
                record.get('practitioner_number'),
                record.get('full_name'),
                fallback=f"{record['workplace_address']}:{record.get('full_name')}",
            )
            item['identities'].add(identity)
            if record['record_type'] == 'provisional':
                item['pipeline_identities']['provisional'].add(identity)
            elif record['record_type'] == 'full':
                item['pipeline_identities']['full'].add(identity)
            elif record['record_type'] == 'full_approved':
                item['pipeline_identities']['full_approved'].add(identity)
            item.setdefault('licence_counts', defaultdict(int))
            licence_status_key = _imported_record_licence_status(record)['licence_status_key']
            item['licence_counts'][licence_status_key] += 1
            item.setdefault('province_counts', defaultdict(int))
            province_label = _normalize_province_label(record.get('province'))
            if province_label in PNG_NURSING_PROVINCES:
                item['province_counts'][province_label] += 1
            if len(item['workers']) < 10:
                item['workers'].append(record)

    for item in facility_rows:
        item['categories'] = [
            {'name': name, 'count': count}
            for name, count in sorted(item['category_counts'].items(), key=lambda row: row[1], reverse=True)[:8]
        ]
        item['cadre_breakdown'] = [
            {'label': name, 'count': count}
            for name, count in sorted(item['category_counts'].items(), key=lambda row: row[1], reverse=True)[:8]
        ]
        licence_counts = item.get('licence_counts') or {}
        item['current_licence_count'] = licence_counts.get('current', 0)
        item['expired_licence_count'] = licence_counts.get('expired', 0)
        item['under_review_licence_count'] = licence_counts.get('under_review', 0)
        item['individual_count'] = len(item.get('identities') or set())
        pipeline_identities = item.get('pipeline_identities') or {}
        item['provisional_competency_count'] = len(pipeline_identities.get('provisional', set()))
        item['full_licence_applicant_count'] = len(pipeline_identities.get('full', set()))
        item['full_licence_approved_count'] = len(pipeline_identities.get('full_approved', set()))
        province_counts = item.get('province_counts') or {}
        item['province_summary'] = ', '.join(
            f"{name} ({count})"
            for name, count in sorted(province_counts.items(), key=lambda row: (-row[1], row[0]))[:3]
        ) or 'Province not captured / review'
        item['primary_province'] = next(
            (name for name, _count in sorted(province_counts.items(), key=lambda row: (-row[1], row[0]))),
            'Province not captured / review',
        )
        item.pop('category_counts', None)
        item.pop('licence_counts', None)
        item.pop('province_counts', None)
        item.pop('pipeline_identities', None)
        item.pop('identities', None)

    return {
        'imported_facility_workers': facility_rows,
        'imported_facility_count': total_facilities,
        'imported_facility_worker_count': total_workers,
        'imported_workplace_reference_count': total_facilities,
        'imported_workplace_worker_count': total_workers,
    }


def _normal_reference_text(value):
    return " ".join(str(value or "").split()).casefold()


def _row_contains_query(row, query, fields):
    if not query:
        return True
    text = " ".join(str(row.get(field, "") or "") for field in fields).casefold()
    return query.casefold() in text


def _live_model_config_for_professional(professional):
    for model, slug, label, domain in INDIVIDUAL_RECORD_LIVE_MODELS:
        if isinstance(professional, model):
            return slug, label, domain
    return "", "Professional", ""


def _professional_matches_scope(professional, scope):
    if professional is None:
        return False
    return any(
        isinstance(professional, model)
        for model, _slug, _label, _domain in _individual_live_models(scope)
    )


def _professional_display_name(professional):
    if professional is None:
        return "Unknown worker"
    full_name = f"{getattr(professional, 'first_name', '')} {getattr(professional, 'last_name', '')}".strip()
    return full_name or str(professional)


def _professional_registration(professional):
    if professional is None:
        return "-"
    return (
        getattr(professional, "registration_no", "")
        or getattr(professional, "registration_number", "")
        or "-"
    )


AGE_BAND_LABELS = ["Under 30", "30-40", "41-50", "51-55", "56+", "Age not captured"]


def _age_from_birth_date(date_of_birth, today=None):
    if not date_of_birth:
        return None
    today = today or timezone.localdate()
    return today.year - date_of_birth.year - ((today.month, today.day) < (date_of_birth.month, date_of_birth.day))


def _age_band_label(age):
    if age is None:
        return "Age not captured"
    if age < 30:
        return "Under 30"
    if age <= 40:
        return "30-40"
    if age <= 50:
        return "41-50"
    if age <= 55:
        return "51-55"
    return "56+"


def _age_payload(date_of_birth):
    age = _age_from_birth_date(date_of_birth)
    return {
        "age": age,
        "age_label": str(age) if age is not None else "-",
        "age_band": _age_band_label(age),
    }


def _age_breakdown_rows(rows):
    counts = {label: 0 for label in AGE_BAND_LABELS}
    for row in rows:
        label = row.get("age_band") or "Age not captured"
        counts[label if label in counts else "Age not captured"] += 1
    return [
        {"label": label, "count": counts[label]}
        for label in AGE_BAND_LABELS
        if counts[label]
    ]


def _safe_province_label(value):
    label = _normalize_province_label(value)
    if label in PNG_NURSING_PROVINCES:
        return label
    return ""


def _facility_accreditation_payload(facility=None, facility_name=""):
    if facility is None:
        return {
            "status_key": "not_linked",
            "status_label": "Imported workplace reference",
            "detail": "No verified Facility master or accreditation record is linked to this workplace reference yet.",
            "application_count": 0,
            "latest_url": "",
        }

    facility_ct = ContentType.objects.get_for_model(Facility)
    applications = (
        Application.objects
        .filter(content_type=facility_ct, object_id=facility.pk, form_code__in=["MBAC", "MBPF", "MBTC"])
        .order_by("-submitted_date", "-id")
    )
    latest = applications.first()
    if latest:
        status_label = latest.get_status_display() if hasattr(latest, "get_status_display") else latest.status.title()
        return {
            "status_key": latest.status or "pending",
            "status_label": status_label,
            "detail": latest.form_title or latest.get_form_code_display(),
            "application_count": applications.count(),
            "latest_url": reverse("application_detail", args=[latest.pk]),
        }

    ownership = facility.get_ownership_display() if hasattr(facility, "get_ownership_display") else facility.ownership
    return {
        "status_key": "not_captured",
        "status_label": "Accreditation evidence not captured",
        "detail": f"{facility.type or 'Facility'} / {ownership or 'ownership not captured'} / level {facility.level or 'not captured'}",
        "application_count": 0,
        "latest_url": "",
    }


def _institution_accreditation_payload(institution):
    metadata = institution.source_metadata if isinstance(institution.source_metadata, dict) else {}
    status = (
        institution.registration_status
        or metadata.get("registration_status")
        or metadata.get("accreditation_status")
        or metadata.get("status")
        or ""
    )
    detail_parts = [
        institution.regulatory_body_name,
        metadata.get("source") or metadata.get("source_reference") or institution.source_reference,
    ]
    return {
        "status_label": status or "Accreditation or registration status not captured",
        "detail": " / ".join(part for part in detail_parts if part) or "Use institution registration metadata once verified.",
        "source_reference": institution.source_reference or metadata.get("source_reference") or "",
    }


def _licence_status_payload(key, label, detail):
    return {
        "licence_status_key": key,
        "licence_status": label,
        "licence_detail": detail,
    }


def _imported_record_licence_status(record):
    if isinstance(record, dict):
        record_type = record.get("record_type") or ""
        record_year = record.get("record_year")
        issued_date = record.get("issued_date")
    else:
        record_type = getattr(record, "record_type", "") or ""
        record_year = getattr(record, "record_year", None)
        issued_date = getattr(record, "issued_date", None)
    current_year = timezone.localdate().year
    record_label = _record_type_display(record)

    if record_type in {"provisional", "temporary"}:
        if issued_date:
            expiry = issued_date + timedelta(days=183)
            if expiry < timezone.localdate():
                return _licence_status_payload("expired", "Expired", f"{record_label} expired {expiry:%d %b %Y}")
            return _licence_status_payload("current", "Current", f"{record_label} issued {issued_date:%d %b %Y}")
        if record_year and record_year < current_year:
            return _licence_status_payload("expired", "Expired", f"{record_label} {record_year}")
        return _licence_status_payload("under_review", "Under review", f"{record_label} pending expiry verification")

    if record_type in {"practicing_license", "full_approved"}:
        if record_year and record_year < current_year:
            return _licence_status_payload("expired", "Expired", f"{record_label} {record_year}")
        year_detail = f" {record_year}" if record_year else ""
        return _licence_status_payload("current", "Current", f"{record_label}{year_detail}")

    return _licence_status_payload("under_review", "Under review", f"{record_label} pending board or registrar completion")


def _professional_licence_status(professional):
    if professional is None:
        return _licence_status_payload("under_review", "Under review", "No linked professional record")

    expiry = getattr(professional, "license_expiry_date", None)
    today = timezone.localdate()
    if expiry:
        if expiry < today:
            return _licence_status_payload("expired", "Expired", f"Expired {expiry:%d %b %Y}")
        return _licence_status_payload("current", "Current", f"Expires {expiry:%d %b %Y}")

    registration = _professional_registration(professional)
    if registration and registration != "-":
        imported_record = (
            _quality_approved_practicing_records()
            .filter(Q(registration_no__iexact=registration) | Q(practitioner_number__iexact=registration))
            .order_by("-record_year", "-issued_date", "-id")
            .first()
        )
        if imported_record:
            return _imported_record_licence_status(imported_record)

    return _licence_status_payload("under_review", "Under review", "No current licence expiry or approved practising licence captured")


def _licence_status_rank(status_key):
    return {"current": 3, "expired": 2, "under_review": 1}.get(status_key or "", 0)


def _latest_professional_qualification(professional):
    if professional is None:
        return None
    content_type = ContentType.objects.get_for_model(professional.__class__)
    return (
        Qualification.objects.filter(content_type=content_type, object_id=professional.pk)
        .select_related("institution")
        .order_by(F("completion_year").desc(nulls_last=True), F("date_completed").desc(nulls_last=True), "-id")
        .first()
    )


def _qualification_year(qualification):
    if not qualification:
        return 0
    if qualification.completion_year:
        return qualification.completion_year
    if qualification.date_completed:
        return qualification.date_completed.year
    return 0


def _professional_institution_summary(professional, qualification=None):
    if isinstance(professional, HealthStudent) and professional.institution:
        return professional.institution.name
    if qualification is None:
        qualification = _latest_professional_qualification(professional)
    if not qualification:
        return "-"
    return (
        getattr(qualification.institution, "name", "")
        or qualification.institution_name
        or qualification.qualification_name
        or "-"
    )


def _professional_detail_url(professional):
    if professional is None:
        return ""
    slug, _label, _domain = _live_model_config_for_professional(professional)
    if not slug:
        return ""
    return reverse("record_detail", args=[slug, professional.pk])


def _professional_identity_key(professional, fallback):
    if professional is None:
        return fallback
    return _record_identity_key(
        getattr(professional, "registration_no", ""),
        getattr(professional, "registration_number", ""),
        _professional_display_name(professional),
        fallback=fallback,
    )


def _add_or_merge_reference_row(rows_by_key, row):
    key = row["identity_key"]
    existing = rows_by_key.get(key)
    if existing is None:
        rows_by_key[key] = row
        return

    existing["source_label"] = " + ".join(
        dict.fromkeys(
            part
            for part in [existing.get("source_label"), row.get("source_label")]
            if part
        )
    )
    source_detail = " | ".join(
        dict.fromkeys(
            part
            for part in [existing.get("source_detail"), row.get("source_detail")]
            if part
        )
    )
    existing["source_detail"] = source_detail
    for field in ["registration_no", "cadre", "institution", "position", "employment", "facility", "province", "year_label", "licence_detail", "age_label", "age_band"]:
        if existing.get(field) in {"", "-", "No year captured"} and row.get(field):
            existing[field] = row[field]
    if existing.get("age") is None and row.get("age") is not None:
        existing["age"] = row["age"]
    if _licence_status_rank(row.get("licence_status_key")) > _licence_status_rank(existing.get("licence_status_key")):
        existing["licence_status_key"] = row.get("licence_status_key")
        existing["licence_status"] = row.get("licence_status")
        existing["licence_detail"] = row.get("licence_detail")
    existing["sort_year"] = max(existing.get("sort_year") or 0, row.get("sort_year") or 0)
    if not existing.get("detail_url") and row.get("detail_url"):
        existing["detail_url"] = row["detail_url"]


def _facility_live_worker_rows(facility, scope):
    rows_by_key = {}
    if facility is None:
        return rows_by_key

    posting_queryset = (
        PostingHistory.objects.filter(facility=facility)
        .select_related("content_type", "facility")
        .order_by("-is_current", "-start_date", "position_title", "id")
    )
    for posting in posting_queryset:
        professional = posting.professional
        if not _professional_matches_scope(professional, scope):
            continue
        qualification = _latest_professional_qualification(professional)
        slug, label, _domain = _live_model_config_for_professional(professional)
        year_value = _qualification_year(qualification)
        licence_status = _professional_licence_status(professional)
        row = {
            "identity_key": _professional_identity_key(professional, f"posting:{posting.pk}"),
            "source_label": "Live posting",
            "source_detail": "Current posting" if posting.is_current else "Posting history",
            "name": _professional_display_name(professional),
            "registration_no": _professional_registration(professional),
            "cadre": getattr(getattr(professional, "cadre", None), "name", "") or label,
            "institution": _professional_institution_summary(professional, qualification),
            "position": posting.position_title or "-",
            "employment": "Current" if posting.is_current else "Historical",
            "facility": facility.name,
            "province": getattr(getattr(facility, "location", None), "province", "") or getattr(professional, "province", "") or "-",
            "year_label": year_value or "No year captured",
            "sort_year": year_value,
            "detail_url": reverse("record_detail", args=[slug, professional.pk]) if slug else "",
            **_age_payload(getattr(professional, "date_of_birth", None)),
            **licence_status,
        }
        _add_or_merge_reference_row(rows_by_key, row)

    employment_queryset = (
        EmploymentRecord.objects.filter(facility=facility)
        .select_related("content_type", "facility")
        .order_by("-is_current", "-start_date", "-created_at", "id")
    )
    for employment in employment_queryset:
        professional = employment.professional
        if not _professional_matches_scope(professional, scope):
            continue
        qualification = _latest_professional_qualification(professional)
        year_value = _qualification_year(qualification)
        _slug, label, _domain = _live_model_config_for_professional(professional)
        licence_status = _professional_licence_status(professional)
        row = {
            "identity_key": _professional_identity_key(professional, f"employment:{employment.pk}"),
            "source_label": "Employment record",
            "source_detail": employment.source_file or employment.source_type or "Live employment",
            "name": _professional_display_name(professional),
            "registration_no": _professional_registration(professional),
            "cadre": getattr(getattr(professional, "cadre", None), "name", "") or label,
            "institution": _professional_institution_summary(professional, qualification),
            "position": employment.position_title or employment.position_held or employment.occupation or "-",
            "employment": _employment_summary(employment),
            "facility": facility.name,
            "province": employment.province or getattr(getattr(facility, "location", None), "province", "") or "-",
            "year_label": year_value or "No year captured",
            "sort_year": year_value,
            "detail_url": _professional_detail_url(professional),
            **_age_payload(getattr(professional, "date_of_birth", None)),
            **licence_status,
        }
        _add_or_merge_reference_row(rows_by_key, row)

    return rows_by_key


def _imported_records_for_scope(scope):
    source_kinds = (
        _import_source_kinds_for_scope(scope)
        if scope in {"medical", "nursing"}
        else NURSING_IMPORT_SOURCE_KINDS + MEDICAL_IMPORT_SOURCE_KINDS
    )
    queryset = (
        _quality_approved_practicing_records()
        .select_related("batch")
        .filter(
            batch__source_kind__in=source_kinds,
            target_model__in=_individual_import_target_models(scope),
        )
    )
    return queryset


def _imported_facility_worker_rows(facility_name, scope):
    target_name = _clean_facility_name(facility_name)
    target_key = _normal_reference_text(target_name)
    if not target_key:
        return []

    target_labels = dict(PracticingLicenseRecord.TARGET_MODEL_CHOICES)
    rows = []
    queryset = (
        _imported_records_for_scope(scope)
        .filter(record_type__in=FACILITY_WORKER_RECORD_TYPES)
        .exclude(workplace_address__isnull=True)
        .exclude(workplace_address="")
        .only(
            "id",
            "batch",
            "workplace_address",
            "full_name",
            "registration_no",
            "practitioner_number",
            "category",
            "target_model",
            "record_year",
            "record_type",
            "institution_name",
            "qualification_name",
            "province",
            "source_sheet_name",
            "source_row",
            "issued_date",
            "payment_date",
            "date_of_birth",
        )
        .order_by("-record_year", "full_name", "id")
    )
    for record in queryset.iterator():
        cleaned_facility = _clean_facility_name(record.workplace_address)
        cleaned_key = _normal_reference_text(cleaned_facility)
        if cleaned_key != target_key and target_key not in cleaned_key and cleaned_key not in target_key:
            continue
        year_value = record.record_year or (record.issued_date.year if record.issued_date else 0) or (record.payment_date.year if record.payment_date else 0)
        licence_status = _imported_record_licence_status(record)
        rows.append({
            "identity_key": _record_identity_key(
                record.registration_no,
                record.practitioner_number,
                record.full_name,
                fallback=f"imported:{record.pk}",
            ),
            "source_label": "Imported workbook",
            "source_detail": f"{record.source_sheet_name} row {record.source_row}",
            "name": record.full_name or "Imported worker",
            "registration_no": record.registration_no or record.practitioner_number or "-",
            "cadre": record.category or target_labels.get(record.target_model, record.target_model or "-"),
            "record_type": record.record_type,
            "institution": record.institution_name or record.qualification_name or "-",
            "position": _record_type_display(record),
            "employment": record.workplace_address or "-",
            "facility": cleaned_facility,
            "province": _normalize_province_label(record.province) if record.province else "-",
            "year_label": year_value or "No year captured",
            "sort_year": year_value,
            "detail_url": reverse("record_detail", args=["practicinglicenserecord", record.pk]),
            **_age_payload(record.date_of_birth),
            **licence_status,
        })
    return rows


def _breakdown_rows(rows, field, empty_label="Not captured"):
    counts = defaultdict(int)
    for row in rows:
        counts[row.get(field) or empty_label] += 1
    return [
        {"label": label, "count": count}
        for label, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _licence_breakdown_rows(rows):
    labels = {
        "current": "Current",
        "expired": "Expired",
        "under_review": "Under review",
    }
    counts = {key: 0 for key in labels}
    for row in rows:
        key = row.get("licence_status_key") or "under_review"
        counts[key if key in counts else "under_review"] += 1
    return [
        {"key": key, "label": label, "count": counts[key]}
        for key, label in labels.items()
    ]


def _cadre_licence_breakdown_rows(rows):
    grouped = {}
    for row in rows:
        cadre = row.get("cadre") or "Not captured"
        status = row.get("licence_status_key") or "under_review"
        grouped.setdefault(cadre, {"cadre": cadre, "total": 0, "current": 0, "expired": 0, "under_review": 0})
        grouped[cadre]["total"] += 1
        grouped[cadre][status if status in {"current", "expired", "under_review"} else "under_review"] += 1
    return sorted(grouped.values(), key=lambda item: (-item["total"], item["cadre"]))


def _facility_worker_summary_from_rows(rows):
    licence_breakdown = _licence_breakdown_rows(rows)
    counts = {item["key"]: item["count"] for item in licence_breakdown}
    pathway_identities = {
        "provisional": set(),
        "full": set(),
        "full_approved": set(),
    }
    for row in rows:
        record_type = row.get("record_type")
        if record_type not in pathway_identities:
            continue
        pathway_identities[record_type].add(row.get("identity_key") or row.get("name"))
    return {
        "worker_count": len(rows),
        "current_licence_count": counts.get("current", 0),
        "expired_licence_count": counts.get("expired", 0),
        "under_review_licence_count": counts.get("under_review", 0),
        "licence_breakdown": licence_breakdown,
        "cadre_breakdown": _breakdown_rows(rows, "cadre"),
        "cadre_licence_breakdown": _cadre_licence_breakdown_rows(rows),
        "provisional_competency_count": len(pathway_identities["provisional"]),
        "full_licence_applicant_count": len(pathway_identities["full"]),
        "full_licence_approved_count": len(pathway_identities["full_approved"]),
    }


def _facility_worker_summary_for_search(facility=None, facility_name="", scope=None):
    rows_by_key = _facility_live_worker_rows(facility, scope)
    lookup_name = facility.name if facility else facility_name
    for row in _imported_facility_worker_rows(lookup_name, scope):
        _add_or_merge_reference_row(rows_by_key, row)
    return _facility_worker_summary_from_rows(list(rows_by_key.values()))


def _imported_facility_search_results(query, scope=None, excluded_names=None, limit=20):
    search_text = " ".join(str(query or "").split())
    if not search_text:
        return []
    excluded_keys = {
        _normal_reference_text(name)
        for name in (excluded_names or [])
        if name
    }
    records = (
        _imported_records_for_scope(scope)
        .filter(record_type__in=FACILITY_WORKER_RECORD_TYPES)
        .exclude(workplace_address__isnull=True)
        .exclude(workplace_address="")
        .filter(workplace_address__icontains=search_text)
        .values("workplace_address")
        .annotate(total=Count("id"))
        .order_by("-total", "workplace_address")[:500]
    )
    grouped = {}
    for row in records:
        facility_name = _clean_facility_name(row["workplace_address"])
        key = _normal_reference_text(facility_name)
        if not key or key in excluded_keys:
            continue
        grouped.setdefault(key, {"name": facility_name, "total": 0})
        grouped[key]["total"] += row["total"]

    results = []
    for item in sorted(grouped.values(), key=lambda row: (-row["total"], row["name"]))[:limit]:
        summary = _facility_worker_summary_for_search(facility_name=item["name"], scope=scope)
        results.append({
            "name": item["name"],
            "code": "Imported workplace reference",
            "type": "Imported facility/workplace",
            "location": "Workbook workplace address",
            "detail_url": reverse("imported_facility_worker_detail") + "?" + urlencode({
                "name": item["name"],
                **({"scope": scope} if scope else {}),
            }),
            **summary,
        })
    return results


def _facility_worker_context(request, facility=None):
    scope = _staff_reference_scope(request.user, request.GET.get("scope"))
    workplace_name = request.GET.get("name", "").strip()
    facility_name = facility.name if facility else _clean_facility_name(workplace_name)
    query = " ".join(request.GET.get("q", "").strip().split())
    sort = request.GET.get("sort", "name")
    if sort not in {"name", "year", "cadre", "institution"}:
        sort = "name"

    rows_by_key = _facility_live_worker_rows(facility, scope)
    for row in _imported_facility_worker_rows(facility_name, scope):
        _add_or_merge_reference_row(rows_by_key, row)

    all_rows = list(rows_by_key.values())
    rows = [
        row for row in all_rows
        if _row_contains_query(row, query, ["name", "registration_no", "cadre", "institution", "employment", "province"])
    ]
    if sort == "year":
        rows.sort(key=lambda row: (-(row.get("sort_year") or 0), row["name"].casefold()))
    elif sort == "cadre":
        rows.sort(key=lambda row: (str(row.get("cadre") or "").casefold(), row["name"].casefold()))
    elif sort == "institution":
        rows.sort(key=lambda row: (str(row.get("institution") or "").casefold(), row["name"].casefold()))
    else:
        rows.sort(key=lambda row: row["name"].casefold())

    paginator = Paginator(rows, 100)
    page_obj = paginator.get_page(request.GET.get("page"))
    query_params = request.GET.copy()
    query_params.pop("page", None)

    summary = _facility_worker_summary_from_rows(all_rows)
    facility_accreditation = _facility_accreditation_payload(facility, facility_name)
    province_label = ""
    if facility and facility.location:
        province_label = _safe_province_label(facility.location.province)
    if not province_label:
        province_label = next(
            (
                _safe_province_label(row.get("province"))
                for row in all_rows
                if _safe_province_label(row.get("province"))
            ),
            "",
        )

    facility_sector_key = ""
    facility_sector_label = ""
    if scope == "medical":
        facility_sector_key = _medical_facility_sector_key(
            facility_name,
            getattr(facility, "ownership", ""),
            getattr(facility, "type", ""),
        )
        facility_sector_label = _medical_facility_sector_label(facility_sector_key)

    return {
        "facility": facility,
        "facility_name": facility_name,
        "province_label": province_label or "Province not captured / review",
        "pha_label": f"{province_label} PHA" if province_label else "PHA not captured / review",
        "facility_sector_key": facility_sector_key,
        "facility_sector_label": facility_sector_label,
        "facility_accreditation": facility_accreditation,
        "worker_rows": page_obj.object_list,
        "page_obj": page_obj,
        "paginator": paginator,
        "query_string": query_params.urlencode(),
        "total_worker_count": len(all_rows),
        "filtered_worker_count": len(rows),
        "current_licence_count": summary["current_licence_count"],
        "expired_licence_count": summary["expired_licence_count"],
        "under_review_licence_count": summary["under_review_licence_count"],
        "provisional_competency_count": summary["provisional_competency_count"],
        "full_licence_applicant_count": summary["full_licence_applicant_count"],
        "full_licence_approved_count": summary["full_licence_approved_count"],
        "licence_breakdown": summary["licence_breakdown"],
        "cadre_breakdown": summary["cadre_breakdown"],
        "cadre_licence_breakdown": summary["cadre_licence_breakdown"],
        "age_breakdown": _age_breakdown_rows(all_rows),
        "institution_breakdown": _breakdown_rows(all_rows, "institution"),
        "scope": scope,
        "scope_label": _individual_scope_label(scope),
        "filters": {"q": query, "sort": sort},
        "sort_options": [
            ("name", "Name"),
            ("year", "Year"),
            ("cadre", "Cadre"),
            ("institution", "Institution"),
        ],
    }


def _imported_institution_graduand_rows(institution, scope):
    target_name = institution.name
    target_key = _normal_reference_text(target_name)
    target_labels = dict(PracticingLicenseRecord.TARGET_MODEL_CHOICES)
    rows = []
    queryset = (
        _imported_records_for_scope(scope)
        .exclude(institution_name__isnull=True)
        .exclude(institution_name="")
        .filter(Q(target_model="healthstudent") | Q(record_type="provisional") | Q(record_type="full"))
        .only(
            "id",
            "batch",
            "institution_name",
            "full_name",
            "registration_no",
            "practitioner_number",
            "category",
            "target_model",
            "record_year",
            "record_type",
            "qualification_name",
            "source_sheet_name",
            "source_row",
            "issued_date",
            "payment_date",
            "date_of_birth",
        )
        .order_by("-record_year", "full_name", "id")
    )
    for record in queryset.iterator():
        institution_key = _normal_reference_text(record.institution_name)
        if institution_key != target_key and target_key not in institution_key and institution_key not in target_key:
            continue
        year_value = record.record_year or (record.issued_date.year if record.issued_date else 0) or (record.payment_date.year if record.payment_date else 0)
        rows.append({
            "identity_key": _record_identity_key(
                record.registration_no,
                record.practitioner_number,
                record.full_name,
                fallback=f"imported:{record.pk}",
            ),
            "source_label": "Imported workbook",
            "source_detail": f"{record.source_sheet_name} row {record.source_row}",
            "name": record.full_name or "Imported graduand",
            "registration_no": record.registration_no or record.practitioner_number or "-",
            "cadre": record.category or record.qualification_name or target_labels.get(record.target_model, record.target_model or "Graduand"),
            "year": year_value,
            "year_label": year_value or "No year captured",
            "status": _record_type_display(record),
            "qualification": record.qualification_name or "-",
            "detail_url": reverse("record_detail", args=["practicinglicenserecord", record.pk]),
            **_age_payload(record.date_of_birth),
        })
    return rows


def _live_institution_graduand_rows(institution):
    rows = []
    students = (
        HealthStudent.objects.filter(institution=institution)
        .select_related("cadre", "institution")
        .order_by("last_name", "first_name", "id")
    )
    for student in students:
        qualification = _latest_professional_qualification(student)
        year_value = (
            student.expected_graduation_date.year
            if student.expected_graduation_date
            else _qualification_year(qualification)
        )
        rows.append({
            "identity_key": _professional_identity_key(student, f"graduand:{student.pk}"),
            "source_label": "Live graduand register",
            "source_detail": student.program or "Graduand profile",
            "name": _professional_display_name(student),
            "registration_no": _professional_registration(student),
            "cadre": getattr(getattr(student, "cadre", None), "name", "") or student.program or "Graduand",
            "year": year_value,
            "year_label": year_value or "No year captured",
            "status": "Graduate" if student.is_graduate else "Graduand / provisional",
            "qualification": student.program or _professional_institution_summary(student, qualification),
            "detail_url": reverse("record_detail", args=["graduand", student.pk]),
            **_age_payload(student.date_of_birth),
        })
    return rows


def _year_cadre_breakdown(rows):
    grouped = defaultdict(lambda: defaultdict(int))
    for row in rows:
        year_label = row.get("year_label") or "No year captured"
        grouped[year_label][row.get("cadre") or "Cadre not captured"] += 1

    def sort_key(item):
        year = item[0]
        if isinstance(year, int):
            return (0, -year)
        return (1, str(year))

    return [
        {
            "year": year,
            "cadres": [
                {"label": label, "count": count}
                for label, count in sorted(cadre_counts.items(), key=lambda item: (-item[1], item[0]))
            ],
            "total": sum(cadre_counts.values()),
        }
        for year, cadre_counts in sorted(grouped.items(), key=sort_key)
    ]


def _institution_graduand_context(request, institution):
    scope = _staff_reference_scope(request.user, request.GET.get("scope"))
    query = " ".join(request.GET.get("q", "").strip().split())
    sort = request.GET.get("sort", "year_desc")
    year_filter = request.GET.get("year", "")
    cadre_filter = request.GET.get("cadre", "")
    if sort not in {"year_desc", "year_asc", "cadre", "name"}:
        sort = "year_desc"

    rows_by_key = {}
    for row in _live_institution_graduand_rows(institution):
        _add_or_merge_reference_row(rows_by_key, row)
    for row in _imported_institution_graduand_rows(institution, scope):
        _add_or_merge_reference_row(rows_by_key, row)

    all_rows = list(rows_by_key.values())
    year_options = sorted(
        {row.get("year") for row in all_rows if row.get("year")},
        reverse=True,
    )
    cadre_options = [
        row["label"] for row in _breakdown_rows(all_rows, "cadre")
    ]

    rows = []
    for row in all_rows:
        if year_filter and str(row.get("year") or "") != year_filter:
            continue
        if cadre_filter and row.get("cadre") != cadre_filter:
            continue
        if not _row_contains_query(row, query, ["name", "registration_no", "cadre", "qualification", "status", "source_detail"]):
            continue
        rows.append(row)

    if sort == "year_asc":
        rows.sort(key=lambda row: (row.get("year") or 0, row["name"].casefold()))
    elif sort == "cadre":
        rows.sort(key=lambda row: (str(row.get("cadre") or "").casefold(), -(row.get("year") or 0), row["name"].casefold()))
    elif sort == "name":
        rows.sort(key=lambda row: row["name"].casefold())
    else:
        rows.sort(key=lambda row: (-(row.get("year") or 0), row["name"].casefold()))

    paginator = Paginator(rows, 100)
    page_obj = paginator.get_page(request.GET.get("page"))
    query_params = request.GET.copy()
    query_params.pop("page", None)

    return {
        "institution": institution,
        "institution_accreditation": _institution_accreditation_payload(institution),
        "graduand_rows": page_obj.object_list,
        "page_obj": page_obj,
        "paginator": paginator,
        "query_string": query_params.urlencode(),
        "total_graduand_count": len(all_rows),
        "filtered_graduand_count": len(rows),
        "cadre_breakdown": _breakdown_rows(all_rows, "cadre"),
        "age_breakdown": _age_breakdown_rows(all_rows),
        "year_cadre_breakdown": _year_cadre_breakdown(all_rows),
        "year_options": year_options,
        "cadre_options": cadre_options,
        "scope": scope,
        "scope_label": _individual_scope_label(scope),
        "filters": {
            "q": query,
            "sort": sort,
            "year": year_filter,
            "cadre": cadre_filter,
        },
        "sort_options": [
            ("year_desc", "Newest year"),
            ("year_asc", "Oldest year"),
            ("cadre", "Cadre"),
            ("name", "Name"),
        ],
    }


def _school_row_institution_match(row, institutions):
    target_names = [row.get("name", "")]
    target_names.extend(row.get("examples", []))
    target_keys = {
        _normal_reference_text(value)
        for value in target_names
        if _normal_reference_text(value)
    }
    if not target_keys:
        return None

    for institution in institutions:
        institution_key = _normal_reference_text(institution.name)
        if institution_key in target_keys:
            return institution

    canonical_key = _normal_reference_text(row.get("name", ""))
    for institution in institutions:
        institution_key = _normal_reference_text(institution.name)
        if canonical_key and (canonical_key in institution_key or institution_key in canonical_key):
            return institution
    return None


def _nursing_pha_breakdown_rows(facility_rows, imported_rows, school_rows):
    grouped = defaultdict(lambda: {
        "province": "",
        "pha": "",
        "facility_count": 0,
        "imported_facility_count": 0,
        "institution_count": 0,
        "practitioner_count": 0,
        "current_count": 0,
        "expired_count": 0,
        "under_review_count": 0,
        "accreditation_captured_count": 0,
        "accreditation_review_count": 0,
        "cadres": defaultdict(int),
        "facility_examples": [],
        "institution_examples": [],
    })

    def group_for(province):
        label = province if province in PNG_NURSING_PROVINCES else "Province not captured / review"
        item = grouped[label]
        item["province"] = label
        item["pha"] = f"{label} PHA" if label in PNG_NURSING_PROVINCES else label
        return item

    for row in facility_rows:
        group = group_for(row.get("province"))
        group["facility_count"] += 1
        group["practitioner_count"] += row.get("worker_count", 0)
        group["current_count"] += row.get("current_licence_count", 0)
        group["expired_count"] += row.get("expired_licence_count", 0)
        group["under_review_count"] += row.get("under_review_licence_count", 0)
        accreditation = row.get("accreditation") or {}
        if accreditation.get("application_count"):
            group["accreditation_captured_count"] += 1
        else:
            group["accreditation_review_count"] += 1
        for cadre in row.get("cadre_breakdown", [])[:4]:
            group["cadres"][cadre["label"]] += cadre["count"]
        if len(group["facility_examples"]) < 4:
            group["facility_examples"].append(row)

    for row in imported_rows:
        group = group_for(row.get("primary_province"))
        group["imported_facility_count"] += 1
        group["practitioner_count"] += row.get("individual_count") or row.get("total", 0)
        group["accreditation_review_count"] += 1
        for cadre in row.get("categories", [])[:4]:
            group["cadres"][cadre["name"]] += cadre["count"]
        if len(group["facility_examples"]) < 4:
            group["facility_examples"].append({
                "name": row.get("facility_name"),
                "detail_url": row.get("detail_url"),
                "worker_count": row.get("individual_count") or row.get("total", 0),
                "type": "Imported workplace reference",
            })

    for row in school_rows:
        group = group_for(row.get("province"))
        group["institution_count"] += 1
        accreditation = row.get("accreditation") or {}
        if accreditation.get("status_label") and "not captured" not in accreditation.get("status_label", "").lower():
            group["accreditation_captured_count"] += 1
        else:
            group["accreditation_review_count"] += 1
        if len(group["institution_examples"]) < 4:
            group["institution_examples"].append(row)

    rows = []
    for item in grouped.values():
        cadre_summary = [
            {"label": label, "count": count}
            for label, count in sorted(item["cadres"].items(), key=lambda row: (-row[1], row[0]))[:5]
        ]
        rows.append({
            **item,
            "cadre_summary": cadre_summary,
        })
    return sorted(rows, key=lambda row: (-row["practitioner_count"], row["province"]))


def _medical_facility_sector_breakdown_rows(facility_rows, imported_rows, institution_rows):
    grouped = {
        key: {
            "key": key,
            "label": _medical_facility_sector_label(key),
            "facility_count": 0,
            "imported_facility_count": 0,
            "institution_count": 0,
            "practitioner_count": 0,
            "current_count": 0,
            "expired_count": 0,
            "under_review_count": 0,
            "provisional_competency_count": 0,
            "full_licence_applicant_count": 0,
            "full_licence_approved_count": 0,
            "accreditation_captured_count": 0,
            "accreditation_review_count": 0,
            "cadres": defaultdict(int),
            "facility_examples": [],
            "institution_examples": [],
        }
        for key in MEDICAL_FACILITY_SECTOR_ORDER
    }

    def group_for(key):
        return grouped.get(key) or grouped["review"]

    def add_accreditation(group, accreditation):
        status_label = str((accreditation or {}).get("status_label") or "").lower()
        has_application = bool((accreditation or {}).get("application_count"))
        if has_application or (status_label and "not captured" not in status_label and "not linked" not in status_label):
            group["accreditation_captured_count"] += 1
        else:
            group["accreditation_review_count"] += 1

    for row in facility_rows:
        group = group_for(row.get("sector_key"))
        group["facility_count"] += 1
        group["practitioner_count"] += row.get("worker_count", 0)
        group["current_count"] += row.get("current_licence_count", 0)
        group["expired_count"] += row.get("expired_licence_count", 0)
        group["under_review_count"] += row.get("under_review_licence_count", 0)
        group["provisional_competency_count"] += row.get("provisional_competency_count", 0)
        group["full_licence_applicant_count"] += row.get("full_licence_applicant_count", 0)
        group["full_licence_approved_count"] += row.get("full_licence_approved_count", 0)
        add_accreditation(group, row.get("accreditation"))
        for cadre in row.get("cadre_breakdown", [])[:5]:
            group["cadres"][cadre["label"]] += cadre["count"]
        if len(group["facility_examples"]) < 4:
            group["facility_examples"].append(row)

    for row in imported_rows:
        group = group_for(row.get("sector_key"))
        group["imported_facility_count"] += 1
        group["practitioner_count"] += row.get("worker_count") or row.get("individual_count") or row.get("total", 0)
        group["current_count"] += row.get("current_licence_count", 0)
        group["expired_count"] += row.get("expired_licence_count", 0)
        group["under_review_count"] += row.get("under_review_licence_count", 0)
        group["provisional_competency_count"] += row.get("provisional_competency_count", 0)
        group["full_licence_applicant_count"] += row.get("full_licence_applicant_count", 0)
        group["full_licence_approved_count"] += row.get("full_licence_approved_count", 0)
        group["accreditation_review_count"] += 1
        for cadre in row.get("cadre_breakdown", [])[:5]:
            group["cadres"][cadre["label"]] += cadre["count"]
        if not row.get("cadre_breakdown"):
            for cadre in row.get("categories", [])[:5]:
                group["cadres"][cadre["name"]] += cadre["count"]
        if len(group["facility_examples"]) < 4:
            group["facility_examples"].append({
                "name": row.get("facility_name"),
                "detail_url": row.get("detail_url"),
                "worker_count": row.get("worker_count") or row.get("individual_count") or row.get("total", 0),
                "type": "Imported workplace reference",
                "province": row.get("primary_province") or row.get("province_summary"),
            })

    for row in institution_rows:
        group = group_for(row.get("sector_key"))
        group["institution_count"] += 1
        add_accreditation(group, row.get("accreditation"))
        if len(group["institution_examples"]) < 4:
            group["institution_examples"].append(row)

    rows = []
    for key in MEDICAL_FACILITY_SECTOR_ORDER:
        item = grouped[key]
        item["cadre_summary"] = [
            {"label": label, "count": count}
            for label, count in sorted(item["cadres"].items(), key=lambda row: (-row[1], row[0]))[:6]
        ]
        rows.append(item)
    return rows


def _medical_training_reference_rows(limit=30):
    queryset = (
        TrainingInstitution.objects.filter(
            Q(type__icontains="CHW")
            | Q(name__icontains="CHW")
            | Q(type__icontains="medical")
            | Q(name__icontains="medical")
            | Q(regulatory_body_name__icontains="Medical Board")
        )
        .order_by("name")[:limit]
    )
    rows = []
    for institution in queryset:
        sector_key = _medical_facility_sector_key(
            institution.name,
            institution.ownership,
            institution.type,
        )
        rows.append({
            "name": institution.name,
            "type": institution.type or "Training institution",
            "sector_key": sector_key,
            "sector_label": _medical_facility_sector_label(sector_key),
            "province": _safe_province_label(institution.location_name) or "Province not captured / review",
            "accreditation": _institution_accreditation_payload(institution),
            "detail_url": reverse("institution_graduand_detail", args=[institution.pk]) + "?scope=medical",
            "map_url": reverse("workforce_map") + "?" + urlencode({
                "office": "medical",
                "type": "school",
                "q": institution.name,
            }),
        })
    return rows


def _medical_facility_institution_breakdown_context():
    latest_batch = _latest_medical_import_batch()
    cache_key = (
        "medical_facility_institution_breakdown_v2:"
        f"{latest_batch.id if latest_batch else 'none'}:"
        f"{latest_batch.completed_at.isoformat() if latest_batch and latest_batch.completed_at else 'pending'}:"
        f"{Facility.objects.count()}:"
        f"{TrainingInstitution.objects.count()}:"
        f"{Application.objects.filter(form_code__in=['MBAC', 'MBPF', 'MBTC']).count()}:"
        f"{PostingHistory.objects.count()}:"
        f"{EmploymentRecord.objects.count()}"
    )
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    facility_rows = []
    for facility in Facility.objects.select_related("location").order_by("name")[:40]:
        summary = _facility_worker_summary_for_search(facility=facility, scope="medical")
        sector_key = _medical_facility_sector_key(facility.name, facility.ownership, facility.type)
        accreditation = _facility_accreditation_payload(facility)
        facility_rows.append({
            "name": facility.name,
            "type": facility.type or "-",
            "ownership": facility.get_ownership_display() if hasattr(facility, "get_ownership_display") else facility.ownership,
            "ownership_key": facility.ownership,
            "sector_key": sector_key,
            "sector_label": _medical_facility_sector_label(sector_key),
            "location": str(facility.location or "-"),
            "province": _safe_province_label(facility.location.province if facility.location else "") or "Province not captured / review",
            "worker_count": summary["worker_count"],
            "current_licence_count": summary["current_licence_count"],
            "expired_licence_count": summary["expired_licence_count"],
            "under_review_licence_count": summary["under_review_licence_count"],
            "provisional_competency_count": summary["provisional_competency_count"],
            "full_licence_applicant_count": summary["full_licence_applicant_count"],
            "full_licence_approved_count": summary["full_licence_approved_count"],
            "cadre_breakdown": summary["cadre_breakdown"],
            "accreditation": accreditation,
            "detail_url": reverse("facility_worker_detail", args=[facility.pk]) + "?scope=medical",
        })

    imported_context = _imported_facility_worker_context(
        target_models=MEDICAL_IMPORT_TARGET_MODELS,
        limit=30,
        scope="medical",
    )
    imported_rows = []
    for row in imported_context["imported_facility_workers"]:
        sector_key = _medical_facility_sector_key(row["facility_name"])
        imported_rows.append({
            **row,
            "sector_key": sector_key,
            "sector_label": _medical_facility_sector_label(sector_key),
            "worker_count": row.get("individual_count") or row.get("total", 0),
            "current_licence_count": row.get("current_licence_count", 0),
            "expired_licence_count": row.get("expired_licence_count", 0),
            "under_review_licence_count": row.get("under_review_licence_count", 0),
            "provisional_competency_count": row.get("provisional_competency_count", 0),
            "full_licence_applicant_count": row.get("full_licence_applicant_count", 0),
            "full_licence_approved_count": row.get("full_licence_approved_count", 0),
            "cadre_breakdown": row.get("cadre_breakdown", []),
            "detail_url": reverse("imported_facility_worker_detail") + "?" + urlencode({
                "name": row["facility_name"],
                "scope": "medical",
            }),
        })

    institution_rows = _medical_training_reference_rows()
    context = {
        "medical_facility_sector_rows": _medical_facility_sector_breakdown_rows(
            facility_rows,
            imported_rows,
            institution_rows,
        ),
        "medical_facility_reference_rows": facility_rows,
        "medical_imported_facility_reference_rows": imported_rows,
        "medical_training_reference_rows": institution_rows,
        "medical_facility_reference_display_count": len(facility_rows),
        "medical_imported_facility_reference_display_count": len(imported_rows),
    }
    cache.set(cache_key, context, 300)
    return context


def _nursing_reference_detail_context(reference_breakdown=None):
    reference_breakdown = reference_breakdown or build_reference_breakdown()
    institutions = list(TrainingInstitution.objects.order_by("name"))
    ownership_labels = {
        "government": "Government",
        "non_government": "Non-government",
        "needs_review": "Needs review",
    }
    school_rows = []
    for row in reference_breakdown.get("nursing_school_rows", []):
        institution = _school_row_institution_match(row, institutions)
        accreditation = _institution_accreditation_payload(institution) if institution else {
            "status_label": "Institution master record not matched",
            "detail": "Open map/reference cleanup before accreditation status can be shown.",
            "source_reference": "",
        }
        province = ""
        if institution:
            province = _safe_province_label(institution.location_name)
        school_rows.append({
            "name": row.get("name", ""),
            "ownership": ownership_labels.get(row.get("ownership"), row.get("ownership") or "-"),
            "raw_reference_count": row.get("raw_reference_count", 0),
            "examples": row.get("examples", []),
            "province": province or "Province not captured / review",
            "accreditation": accreditation,
            "detail_url": reverse("institution_graduand_detail", args=[institution.pk]) + "?scope=nursing" if institution else "",
            "map_url": reverse("workforce_map") + "?" + urlencode({
                "office": "nursing",
                "type": "school",
                "q": row.get("name", ""),
            }),
        })

    facility_rows = []
    for facility in Facility.objects.select_related("location").order_by("name")[:30]:
        summary = _facility_worker_summary_for_search(facility=facility, scope="nursing")
        accreditation = _facility_accreditation_payload(facility)
        facility_rows.append({
            "name": facility.name,
            "type": facility.type or "-",
            "ownership": facility.get_ownership_display() if hasattr(facility, "get_ownership_display") else facility.ownership,
            "ownership_key": facility.ownership,
            "sector_key": _medical_facility_sector_key(facility.name, facility.ownership, facility.type),
            "location": str(facility.location or "-"),
            "province": _safe_province_label(facility.location.province if facility.location else "") or "Province not captured / review",
            "worker_count": summary["worker_count"],
            "current_licence_count": summary["current_licence_count"],
            "expired_licence_count": summary["expired_licence_count"],
            "under_review_licence_count": summary["under_review_licence_count"],
            "provisional_competency_count": summary["provisional_competency_count"],
            "full_licence_applicant_count": summary["full_licence_applicant_count"],
            "full_licence_approved_count": summary["full_licence_approved_count"],
            "cadre_breakdown": summary["cadre_breakdown"],
            "accreditation": accreditation,
            "detail_url": reverse("facility_worker_detail", args=[facility.pk]) + "?scope=nursing",
        })

    imported_context = _imported_facility_worker_context(
        target_models=NURSING_IMPORT_TARGET_MODELS,
        limit=20,
        scope="nursing",
    )
    imported_rows = []
    for row in imported_context["imported_facility_workers"]:
        sector_key = _medical_facility_sector_key(row["facility_name"])
        imported_rows.append({
            **row,
            "sector_key": sector_key,
            "sector_label": _medical_facility_sector_label(sector_key),
            "detail_url": reverse("imported_facility_worker_detail") + "?" + urlencode({
                "name": row["facility_name"],
                "scope": "nursing",
            }),
        })

    return {
        "nursing_school_reference_rows": school_rows,
        "facility_master_reference_rows": facility_rows,
        "imported_facility_reference_rows": imported_rows,
        "nursing_pha_breakdown_rows": _nursing_pha_breakdown_rows(facility_rows, imported_rows, school_rows),
        "facility_master_reference_display_count": len(facility_rows),
        "imported_facility_reference_display_count": len(imported_rows),
    }


def _is_png_national_institution(institution, scope):
    """Return whether a matched master institution is a PNG institution for this office."""
    if not institution:
        return False
    country = _normal_reference_text(institution.country)
    if country and country not in {"png", "papua new guinea", "papua new guinea png"}:
        return False
    office_text = _normal_reference_text(institution.regulatory_body_name)
    type_text = _normal_reference_text(institution.type)
    if scope == "medical":
        return not office_text or "medical" in office_text or "chw" in type_text
    return not office_text or "nursing" in office_text or "nurse" in type_text


def _national_institution_workforce_rows(scope, limit=30):
    """Rank recognised PNG institutions by distinct people in the scoped registry."""
    institutions = [
        institution
        for institution in TrainingInstitution.objects.order_by("name")
        if _is_png_national_institution(institution, scope)
    ]
    by_name = {_normal_reference_text(institution.name): institution for institution in institutions}
    grouped = {}

    def group_for(institution):
        return grouped.setdefault(institution.pk, {
            "institution": institution,
            "identities": set(),
            "provisional_identities": set(),
            "provisional_placement_identities": set(),
            "full_identities": set(),
            "full_approved_identities": set(),
            "facilities": set(),
            "cadres": defaultdict(int),
        })

    records = (
        _imported_records_for_scope(scope)
        .filter(record_type__in=FACILITY_WORKER_RECORD_TYPES)
        .exclude(institution_name__isnull=True)
        .exclude(institution_name="")
        .values(
            "institution_name",
            "full_name",
            "registration_no",
            "practitioner_number",
            "record_type",
            "category",
            "workplace_address",
            "source_sheet_name",
            "source_row",
        )
    )
    for record in records.iterator():
        institution = by_name.get(_normal_reference_text(record["institution_name"]))
        if not institution:
            continue
        item = group_for(institution)
        identity = _record_identity_key(
            record["registration_no"],
            record["practitioner_number"],
            record["full_name"],
            fallback=f"{institution.pk}:{record['source_sheet_name']}:{record['source_row']}",
        )
        item["identities"].add(identity)
        if record["category"]:
            item["cadres"][record["category"]] += 1
        facility_name = _clean_facility_name(record["workplace_address"])
        if facility_name:
            item["facilities"].add(facility_name)
        if record["record_type"] == "provisional":
            item["provisional_identities"].add(identity)
            if facility_name:
                item["provisional_placement_identities"].add(identity)
        elif record["record_type"] == "full":
            item["full_identities"].add(identity)
        elif record["record_type"] == "full_approved":
            item["full_approved_identities"].add(identity)

    # Imported workbooks are not the whole registry.  Include people whose
    # live profile is linked to a recognised PNG institution so the ranking is
    # genuinely "within the system", while retaining imported pathway counts
    # for provisional competency and full-licence progression.
    institution_by_id = {institution.pk: institution for institution in institutions}
    for model, _slug, fallback_cadre, _domain in _individual_live_models(scope):
        content_type = ContentType.objects.get_for_model(model)
        qualification_rows = list(
            Qualification.objects.filter(
                content_type=content_type,
                institution_id__in=institution_by_id,
            ).values_list("object_id", "institution_id")
        )
        if not qualification_rows:
            continue
        institution_ids_by_profile = defaultdict(set)
        for object_id, institution_id in qualification_rows:
            institution_ids_by_profile[object_id].add(institution_id)
        professionals = model.objects.filter(pk__in=institution_ids_by_profile).select_related("cadre")
        for professional in professionals:
            identity = _professional_identity_key(professional, f"live:{model._meta.label_lower}:{professional.pk}")
            cadre = getattr(getattr(professional, "cadre", None), "name", "") or fallback_cadre
            for institution_id in institution_ids_by_profile[professional.pk]:
                item = group_for(institution_by_id[institution_id])
                item["identities"].add(identity)
                item["cadres"][cadre] += 1

    if scope == "nursing":
        for graduand in HealthStudent.objects.filter(institution_id__in=institution_by_id).select_related("institution", "cadre"):
            identity = _professional_identity_key(graduand, f"live:healthstudent:{graduand.pk}")
            item = group_for(institution_by_id[graduand.institution_id])
            item["identities"].add(identity)
            item["cadres"][getattr(getattr(graduand, "cadre", None), "name", "") or "Graduand"] += 1

    rows = []
    for item in grouped.values():
        institution = item["institution"]
        rows.append({
            "name": institution.name,
            "individual_count": len(item["identities"]),
            "provisional_competency_count": len(item["provisional_identities"]),
            "provisional_placement_count": len(item["provisional_placement_identities"]),
            "full_licence_applicant_count": len(item["full_identities"]),
            "full_licence_approved_count": len(item["full_approved_identities"]),
            "facility_count": len(item["facilities"]),
            "facility_examples": sorted(item["facilities"])[:4],
            "cadre_summary": [
                {"label": label, "count": count}
                for label, count in sorted(item["cadres"].items(), key=lambda pair: (-pair[1], pair[0]))[:4]
            ],
            "detail_url": reverse("institution_graduand_detail", args=[institution.pk]) + f"?scope={scope}",
        })
    return sorted(rows, key=lambda row: (-row["individual_count"], row["name"]))[:limit]


def _facility_directory_context(scope):
    if scope == "medical":
        detail_context = _medical_facility_institution_breakdown_context()
        facility_rows = detail_context["medical_facility_reference_rows"]
        imported_rows = detail_context["medical_imported_facility_reference_rows"]
        institution_rows = detail_context["medical_training_reference_rows"]
        sector_rows = detail_context["medical_facility_sector_rows"]
    else:
        detail_context = _nursing_reference_detail_context()
        facility_rows = detail_context["facility_master_reference_rows"]
        imported_rows = detail_context["imported_facility_reference_rows"]
        institution_rows = []
        for row in detail_context["nursing_school_reference_rows"]:
            institution_row = dict(row)
            sector_key = _medical_facility_sector_key(
                institution_row.get("name"),
                institution_row.get("ownership"),
                institution_row.get("type"),
            )
            institution_row.update({
                "sector_key": sector_key,
                "sector_label": _medical_facility_sector_label(sector_key),
            })
            institution_rows.append(institution_row)
        sector_rows = _medical_facility_sector_breakdown_rows(
            facility_rows,
            imported_rows,
            institution_rows,
        )

    return {
        "facility_scope": scope,
        "facility_scope_label": _individual_scope_label(scope),
        "facility_sector_rows": sector_rows,
        "facility_reference_rows": facility_rows,
        "imported_facility_reference_rows": imported_rows,
        "facility_institution_rows": institution_rows,
        "national_institution_workforce_rows": _national_institution_workforce_rows(scope),
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


def _nursing_professional_target_model(professional):
    if isinstance(professional, Midwife):
        return "midwife"
    if isinstance(professional, NurseAide):
        return "nurseaide"
    if isinstance(professional, HealthStudent):
        return "healthstudent"
    return "nursingprofessional"


def _nursing_professional_identity_query(professional):
    query = Q()
    for value in [
        getattr(professional, "registration_no", ""),
        getattr(professional, "registration_number", ""),
        getattr(professional, "national_id", ""),
    ]:
        value = str(value or "").strip()
        if value:
            query |= Q(registration_no__iexact=value) | Q(practitioner_number__iexact=value)
    full_name = f"{getattr(professional, 'first_name', '')} {getattr(professional, 'last_name', '')}".strip()
    if full_name:
        query |= Q(full_name__iexact=full_name)
    return query


def _nursing_professional_import_records(professional):
    identity_query = _nursing_professional_identity_query(professional)
    if not identity_query:
        return PracticingLicenseRecord.objects.none()
    return _quality_approved_practicing_records().filter(
        identity_query,
        batch__source_kind__in=NURSING_IMPORT_SOURCE_KINDS,
        target_model=_nursing_professional_target_model(professional),
    )


def _nursing_professional_active_conditions(professional):
    content_type = ContentType.objects.get_for_model(professional)
    registration_number = str(getattr(professional, "registration_no", "") or "").strip()
    query = Q(subject_content_type=content_type, subject_object_id=professional.pk)
    if registration_number:
        query |= Q(subject_identifier__iexact=registration_number)
    return RegulatoryDecisionRecord.objects.filter(
        query,
        office_scope="nursing",
        status="final",
    ).exclude(conditions="").filter(
        Q(expiry_date__isnull=True) | Q(expiry_date__gte=date.today())
    ).order_by("-decided_at", "-updated_at")


def _nursing_professional_status_context(professional, applications, *, audience):
    if not professional:
        return {
            "nursing_status": None,
            "nursing_assurance_cards": [],
            "nursing_readiness_items": [],
            "nursing_condition_decisions": [],
            "nursing_recent_cpd": [],
            "nursing_employment_records": [],
            "nursing_posting_history": [],
            "nursing_public_register_preview": {},
            "nursing_renewal_steps": [],
        }

    today = date.today()
    expiry = getattr(professional, "license_expiry_date", None)
    days_left = (expiry - today).days if expiry else None
    import_records = _nursing_professional_import_records(professional)
    latest_practicing_record = import_records.filter(record_type="practicing_license").order_by("-record_year", "-issued_date").first()
    latest_full_record = import_records.filter(record_type__in=["full", "full_approved", "workforce_listing"]).order_by("-record_year", "-issued_date").first()
    latest_provisional_record = import_records.filter(record_type="provisional").order_by("-record_year", "-issued_date").first()

    if not getattr(professional, "is_active", True):
        status_label = "Inactive"
        status_theme = "secondary"
    elif expiry and expiry < today:
        status_label = "Expired"
        status_theme = "danger"
    elif expiry and days_left is not None and days_left <= 90:
        status_label = "Expiring"
        status_theme = "warning"
    elif expiry:
        status_label = "Active"
        status_theme = "success"
    elif latest_practicing_record:
        status_label = "ATP / practising authority recorded"
        status_theme = "success"
    elif latest_full_record:
        status_label = "Full licence recorded"
        status_theme = "success"
    elif latest_provisional_record or isinstance(professional, HealthStudent):
        status_label = "Provisional pathway"
        status_theme = "info"
    elif isinstance(professional, NurseAide):
        status_label = "Registered"
        status_theme = "success"
    else:
        status_label = "Registration pending verification"
        status_theme = "warning"

    content_type = ContentType.objects.get_for_model(professional)
    cpd_records = CPDRecord.objects.filter(content_type=content_type, object_id=professional.pk).order_by("-start_date")
    cpd_total = cpd_records.aggregate(total=Sum("hours_credits")).get("total") or 0
    has_completed_receipt = Receipt.objects.filter(application__in=applications, status="completed").exists()
    condition_decisions = list(_nursing_professional_active_conditions(professional)[:5])
    latest_application = applications.order_by("-submitted_date").first() if hasattr(applications, "order_by") else None
    documents = ProfessionalDocument.objects.filter(content_type=content_type, object_id=professional.pk).select_related("document_type").order_by("-uploaded_at")
    employment_records = EmploymentRecord.objects.filter(content_type=content_type, object_id=professional.pk).select_related("facility").order_by("-is_current", "-start_date", "-created_at")
    posting_history = PostingHistory.objects.filter(content_type=content_type, object_id=professional.pk).select_related("facility").order_by("-is_current", "-start_date")
    current_employment = employment_records.filter(is_current=True).first() or employment_records.first()
    current_posting = posting_history.filter(is_current=True).first() or posting_history.first()

    qualification_value = (
        getattr(professional, "qualification_level", "")
        or getattr(professional, "training_level", "")
        or getattr(professional, "program", "")
        or getattr(professional, "cadre_id", None)
    )
    pathway_codes = {getattr(app, "form_code", "") for app in applications} if applications is not None else set()
    has_provisional_or_full = bool(
        latest_full_record
        or latest_provisional_record
        or {"NC1", "NC2", "G1", "G2", "G3", "G4", "G5", "G6", "G7"} & pathway_codes
    )
    has_atp_or_renewal = bool(
        latest_practicing_record
        or expiry
        or "NC3" in pathway_codes
        or status_label in {"Active", "Expiring", "ATP / practising authority recorded", "Registered"}
    )
    cpd_required = isinstance(professional, (NursingProfessional, Midwife))
    readiness_items = [
        {"label": "Identity", "complete": bool(getattr(professional, "registration_no", "") and getattr(professional, "first_name", "") and getattr(professional, "last_name", ""))},
        {"label": "Qualification / scope", "complete": bool(qualification_value or latest_full_record or latest_provisional_record)},
        {"label": "Provisional to full pathway", "complete": has_provisional_or_full or isinstance(professional, NurseAide)},
        {"label": "ATP / renewal authority", "complete": has_atp_or_renewal},
        {"label": "CPD / learning", "complete": bool(cpd_total or not cpd_required)},
        {"label": "Payment receipt", "complete": bool(has_completed_receipt)},
        {"label": "Conditions reviewed", "complete": not condition_decisions},
    ]
    complete_count = sum(1 for item in readiness_items if item["complete"])
    readiness_percent = round((complete_count / len(readiness_items)) * 100)

    assurance_cards = [
        {
            "label": "Register status",
            "value": status_label,
            "theme": status_theme,
            "detail": f"Expiry {expiry:%d %b %Y}" if expiry else "No expiry date captured",
        },
        {
            "label": "Renewal readiness",
            "value": f"{readiness_percent}%",
            "theme": "success" if readiness_percent >= 80 else "warning" if readiness_percent >= 50 else "danger",
            "detail": f"{complete_count} of {len(readiness_items)} checks complete",
        },
        {
            "label": "CPD / learning",
            "value": f"{cpd_total:g}",
            "theme": "success" if cpd_total else ("secondary" if not cpd_required else "warning"),
            "detail": "Recorded hours / credits",
        },
        {
            "label": "Conditions",
            "value": len(condition_decisions),
            "theme": "danger" if condition_decisions else "success",
            "detail": "Active final Nursing Council conditions",
        },
    ]
    register_category = "Midwife" if isinstance(professional, Midwife) else "Nurse Aide" if isinstance(professional, NurseAide) else "Graduand" if isinstance(professional, HealthStudent) else "Registered Nurse"
    public_register_preview = {
        "full_name": f"{getattr(professional, 'first_name', '')} {getattr(professional, 'last_name', '')}".strip(),
        "registration_number": getattr(professional, "registration_no", "") or "",
        "practitioner_number": getattr(professional, "registration_number", "") or "",
        "professional_category": register_category,
        "licence_status": status_label,
        "licence_expiry_date": expiry,
        "eligible_to_practice": status_label in {"Active", "Expiring", "ATP / practising authority recorded", "Full licence recorded", "Registered"},
        "conditions_summary": "Active conditions recorded" if condition_decisions else "No active public conditions recorded",
    }
    primary_action = {
        "label": "Renew Licence",
        "url": reverse("public_nurse_renewal"),
        "theme": "primary",
        "detail": "Complete NC3 renewal and ATP/practising authority evidence.",
    }
    if status_label == "Expired":
        primary_action.update({"label": "Renew Now", "theme": "danger", "detail": "Your licence has expired or is not current."})
    elif status_label == "Expiring":
        primary_action.update({"label": "Renew Before Expiry", "theme": "warning", "detail": f"{days_left} days remaining" if days_left is not None else "Renewal window is open."})
    elif not latest_full_record and not isinstance(professional, NurseAide):
        primary_action.update({"label": "Apply For Full Licence", "url": reverse("public_nurse_full_license"), "theme": "success", "detail": "Complete NC2 after the provisional pathway is ready."})

    renewal_steps = [
        {
            "number": 1,
            "label": "Confirm identity",
            "detail": "Name, registration number, and contact profile.",
            "complete": readiness_items[0]["complete"],
            "href": reverse("user_profile"),
        },
        {
            "number": 2,
            "label": "Update practice details",
            "detail": "Employer, facility, province, position, and current practice setting.",
            "complete": bool(current_employment or current_posting),
            "href": reverse("public_nurse_renewal") + "#employment",
        },
        {
            "number": 3,
            "label": "Record CPD / learning",
            "detail": "Continuing competence evidence for the renewal cycle.",
            "complete": bool(cpd_total or not cpd_required),
            "href": reverse("public_nurse_renewal") + "#cpd",
        },
        {
            "number": 4,
            "label": "Attach documents",
            "detail": "Identity, qualification, employer, or renewal evidence where required.",
            "complete": documents.exists(),
            "href": reverse("public_nurse_renewal") + "#documents",
        },
        {
            "number": 5,
            "label": "Add payment receipt",
            "detail": "Official receipt number, amount, date, and receipt image.",
            "complete": has_completed_receipt,
            "href": "#receipts",
        },
        {
            "number": 6,
            "label": "Declarations and submit",
            "detail": "Confirm practice, conduct, and public-register declarations.",
            "complete": bool(latest_application and latest_application.status in {"pending", "approved"}),
            "href": reverse("public_nurse_renewal") + "#declarations",
        },
    ]

    return {
        "nursing_status": {
            "label": status_label,
            "theme": status_theme,
            "expiry": expiry,
            "days_left": days_left,
            "latest_application": latest_application,
            "latest_practicing_record": latest_practicing_record,
            "latest_full_record": latest_full_record,
            "latest_provisional_record": latest_provisional_record,
            "audience": audience,
        },
        "nursing_assurance_cards": assurance_cards,
        "nursing_readiness_items": readiness_items,
        "nursing_readiness_percent": readiness_percent,
        "nursing_condition_decisions": condition_decisions,
        "nursing_recent_cpd": list(cpd_records[:20]),
        "nursing_cpd_total": cpd_total,
        "nursing_document_count": documents.count(),
        "nursing_employment_records": list(employment_records[:10]),
        "nursing_posting_history": list(posting_history[:10]),
        "nursing_current_employment": current_employment,
        "nursing_current_posting": current_posting,
        "nursing_public_register_preview": public_register_preview,
        "nursing_primary_action": primary_action,
        "nursing_renewal_steps": renewal_steps,
        "nursing_help_actions": [
            {"label": "Create enquiry", "href": reverse("enquiry_create"), "icon": "fas fa-envelope", "detail": "Ask the Nursing Council team to review your record."},
            {"label": "Helpdesk", "href": reverse("helpdesk"), "icon": "fas fa-headset", "detail": "Get account, form, or document guidance."},
            {"label": "FAQs", "href": reverse("public_faqs"), "icon": "fas fa-circle-question", "detail": "Open public Nursing Council guidance."},
            {"label": "My profile", "href": reverse("user_profile"), "icon": "fas fa-user-cog", "detail": "Update account and contact details."},
        ],
        "nursing_public_verification_url": reverse("public_nursing_register_search_root"),
        "nursing_forms_url": reverse("nursing_forms_portal"),
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


MEDICAL_FACILITY_SECTOR_ORDER = ("public", "pha", "church", "catholic", "private", "ngo", "review")
MEDICAL_FACILITY_SECTOR_LABELS = {
    "public": "Public / National Facilities",
    "pha": "Provincial Health Authority (PHA)",
    "church": "Church Health Services",
    "catholic": "Catholic Health Services",
    "private": "Private facilities",
    "ngo": "NGO facilities",
    "review": "Ownership needs review",
}
MEDICAL_CATHOLIC_KEYWORDS = (
    "catholic",
    "diocese",
    "caritas",
    "olsh",
    "st mary",
    "st. mary",
    "saint mary",
    "st joseph",
    "st. joseph",
    "saint joseph",
)
MEDICAL_CHURCH_KEYWORDS = (
    "church",
    "christian",
    "mission",
    "adventist",
    "anglican",
    "lutheran",
    "nazarene",
    "nazareth",
    "wesleyan",
    "salvation army",
    "faith based",
    "faith-based",
)
MEDICAL_NGO_KEYWORDS = ("ngo", "non government", "non-government", "foundation", "association", "aid post")


def _medical_facility_sector_key(name="", ownership="", facility_type=""):
    text = " ".join(str(part or "") for part in [name, facility_type]).lower()
    ownership_key = str(ownership or "").lower()
    if "pha" in text or "provincial health authority" in text:
        return "pha"
    if ownership_key == "faith_based" and any(keyword in text for keyword in MEDICAL_CATHOLIC_KEYWORDS):
        return "catholic"
    if any(keyword in text for keyword in MEDICAL_CATHOLIC_KEYWORDS):
        return "catholic"
    if ownership_key == "faith_based" or any(keyword in text for keyword in MEDICAL_CHURCH_KEYWORDS):
        return "church"
    if ownership_key == "private" or any(keyword in text for keyword in ATP_PRIVATE_KEYWORDS):
        return "private"
    if ownership_key in {"ngo", "non-government", "non_government"} or any(keyword in text for keyword in MEDICAL_NGO_KEYWORDS):
        return "ngo"
    if ownership_key in {"public", "government", "national"} or any(keyword in text for keyword in ATP_PUBLIC_KEYWORDS):
        return "public"
    return "review"


def _medical_facility_sector_label(key):
    return MEDICAL_FACILITY_SECTOR_LABELS.get(key or "review", MEDICAL_FACILITY_SECTOR_LABELS["review"])


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
    snapshot = active_nursing_analytics_snapshot()
    if snapshot:
        return _nursing_snapshot_frequent_records_context(request, snapshot)

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


def _nursing_snapshot_frequent_records_context(request, snapshot):
    payload = nursing_analytics_metric_payload(snapshot)
    snapshot_context = _nursing_snapshot_live_context(snapshot, payload)
    current_year = snapshot_context.get('atp_current_year')
    category_filter = " ".join(request.GET.get("category", "").split())
    facility_group_filter = request.GET.get("facility_group", "")
    category_review_filter = request.GET.get("category_review") == "1"
    valid_facility_groups = {"pha", "private", "ngo", "review"}
    if facility_group_filter not in valid_facility_groups:
        facility_group_filter = ""

    queryset = snapshot.lifecycle_facts.filter(
        lifecycle_stage=SNAPSHOT_ATP_STAGE,
        cycle_year=current_year,
    ).order_by('-event_date', 'full_name', 'record_id')
    records = list(queryset.values(
        'record_id',
        'event_date',
        'full_name',
        'person_group_key',
        'sex',
        'cadre',
        'formal_qualification',
        'registration_no',
        'practitioner_no',
        'facility',
        'province',
        'organization_type',
        'nationality_group',
        'record_quality',
        'data_quality_flags',
        'source_sheet',
        'source_row',
    ))

    rows = []
    valid_count = 0
    needs_review_count = 0
    high_risk_count = 0
    for record in records:
        cadre = record.get('cadre') or 'Unclassified / Missing Cadre'
        facility_group_key = _snapshot_facility_group(record.get('organization_type'))
        if category_filter and cadre != category_filter:
            continue
        if facility_group_filter and facility_group_key != facility_group_filter:
            continue
        if category_review_filter and not _snapshot_category_needs_review(cadre):
            continue

        status_label, status_class, issues = _snapshot_quality_status(
            record.get('record_quality'),
            record.get('data_quality_flags'),
        )
        if _snapshot_category_needs_review(cadre):
            issues.append("Cadre label needs review")
        if facility_group_key == "review":
            issues.append("Facility ownership needs review")
        issues = list(dict.fromkeys(issues))

        if status_class == "danger":
            high_risk_count += 1
        elif issues or status_class == "warning":
            needs_review_count += 1
        else:
            valid_count += 1

        rows.append({
            "name": record.get('full_name') or "-",
            "registration_no": record.get('registration_no') or "-",
            "practitioner_number": record.get('practitioner_no') or "-",
            "category": cadre,
            "category_status": "Review label" if _snapshot_category_needs_review(cadre) else "Standard",
            "facility": record.get('facility') or "Facility not captured",
            "facility_group": _facility_reporting_label(facility_group_key),
            "province": record.get('province') or "-",
            "gender": _snapshot_gender_label(record.get('sex')),
            "nationality": record.get('nationality_group') or "-",
            "payment_date": record.get('event_date'),
            "issued_date": record.get('event_date'),
            "source_sheet": record.get('source_sheet') or "-",
            "source_row": record.get('source_row') or "-",
            "status_label": status_label,
            "status_class": status_class,
            "issues": issues,
            "detail_url": "",
            "edit_url": "",
        })

    if category_filter:
        page_title = category_filter
        active_filter_label = f"Cadre: {category_filter}"
    elif category_review_filter:
        page_title = "Cadre Labels Requiring Cleanup"
        active_filter_label = "Only snapshot rows with unclassified cadre labels"
    elif facility_group_filter:
        page_title = _facility_reporting_label(facility_group_filter)
        active_filter_label = f"Facility group: {page_title}"
    else:
        page_title = "Current ATP Snapshot Records"
        active_filter_label = "Current-year ATP records from the active analytics snapshot"

    facility_options = [
        {"key": key, "label": _facility_reporting_label(key), "url": f"{reverse('nursing_frequent_records')}?{urlencode({'facility_group': key})}"}
        for key in ["pha", "private", "ngo", "review"]
    ]
    category_options = [
        {"label": row["label"], "url": f"{reverse('nursing_frequent_records')}?{urlencode({'category': row['label']})}"}
        for row in snapshot_context.get("frequent_nursing_category_rows", [])
    ]
    return {
        "atp_batch": snapshot.source_batch,
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
        "snapshot_read_only": True,
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
    cache_key = f"nursing_council_analytics_context_v4:{date.today().isoformat()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    nursing_records = _nursing_record_queryset().filter(target_model__in=['nursingprofessional', 'midwife', 'nurseaide'])
    provisional_records = _nursing_record_queryset().filter(target_model='healthstudent', record_type='provisional')

    yearly_sets = defaultdict(lambda: {
        'provisional': set(),
        'full': set(),
        'full_approved': set(),
        'temporary': set(),
        'practicing_license': set(),
        'workforce_listing': set(),
    })

    for record in provisional_records:
        if record.record_year:
            yearly_sets[record.record_year]['provisional'].add(_record_identity(record))

    for record in nursing_records.filter(record_type__in=['full', 'full_approved', 'temporary', 'practicing_license', 'workforce_listing']):
        if record.record_year:
            yearly_sets[record.record_year][record.record_type].add(_record_identity(record))

    yearly_rows = []
    for year_value in sorted(yearly_sets.keys(), reverse=True):
        row_sets = yearly_sets[year_value]
        yearly_rows.append({
            'year': year_value,
            'graduand_count': len(row_sets['provisional']),
            'full_registration_count': len(row_sets['full']),
            'full_approved_count': len(row_sets['full_approved']),
            'temporary_license_count': len(row_sets['temporary']),
            'practicing_license_count': len(row_sets['practicing_license']),
            'active_listing_count': len(row_sets['workforce_listing']),
        })

    chart_rows = list(reversed(yearly_rows[:18]))
    latest_year_row = yearly_rows[0] if yearly_rows else {}

    full_license_records = list(
        nursing_records.filter(record_type__in=['full', 'full_approved', 'practicing_license'])
        .order_by('-record_year', '-issued_date', '-payment_date', 'full_name')[:60]
    )

    full_identities = {
        _record_identity(record)
        for record in nursing_records.filter(record_type='full')
        if _record_identity(record)
    }
    full_approved_identities = {
        _record_identity(record)
        for record in nursing_records.filter(record_type='full_approved')
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
            'stage': 'Full-Licence Applicants',
            'count': len(full_identities),
            'description': 'Applicants acquiring a full licence after screening. These are not approved full licences yet.',
        },
        {
            'stage': 'Full-Licence Approved',
            'count': len(full_approved_identities),
            'description': 'Registrar-approved full licences. Approved practitioners can then apply for ATP cycles.',
        },
        {
            'stage': 'ATP / Authority to Practice',
            'count': len(practicing_identities),
            'description': 'Authority to Practice records after full-licence approval, used for renewal cycles.',
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
        'nursing_flow_full_approved_values': json.dumps([row['full_approved_count'] for row in chart_rows]),
        'nursing_flow_practicing_values': json.dumps([row['practicing_license_count'] for row in chart_rows]),
        'nursing_full_registration_total': len(full_identities),
        'nursing_full_approved_total': len(full_approved_identities),
        'nursing_practicing_license_total': len(practicing_identities),
        'nursing_provisional_pipeline_total': len(provisional_identities),
        'nursing_latest_year': latest_year_row.get('year'),
        'nursing_latest_full_count': latest_year_row.get('full_registration_count', 0),
        'nursing_latest_full_approved_count': latest_year_row.get('full_approved_count', 0),
        'nursing_latest_practicing_count': latest_year_row.get('practicing_license_count', 0),
        'nursing_analytics_batch': _latest_ndata_batch(),
    }
    cache.set(cache_key, context, DASHBOARD_CACHE_TIMEOUT_SECONDS)
    return context


def _latest_ndata_batch():
    cache_key = "latest_ndata_batch_v3"
    sentinel = object()
    cached = cache.get(cache_key, sentinel)
    if cached is not sentinel:
        return cached or None

    batch = DataImportBatch.objects.filter(
        source_kind='ndata_workbook',
        status='completed',
        records__target_model__in=NURSING_IMPORT_TARGET_MODELS,
    ).exclude(source_file_name__icontains='ATP').distinct().order_by('-started_at').first()
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
    cache_key = "latest_medical_import_batch_v2"
    sentinel = object()
    cached = cache.get(cache_key, sentinel)
    if cached is not sentinel:
        return cached or None

    batch = DataImportBatch.objects.filter(
        source_kind__in=MEDICAL_IMPORT_SOURCE_KINDS,
        status='completed',
        records__target_model__in=MEDICAL_IMPORT_TARGET_MODELS,
    ).distinct().order_by('-started_at').first()
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


SNAPSHOT_ATP_STAGE = 'Authority to Practice'
SNAPSHOT_FULL_STAGE = 'Full Licence'
SNAPSHOT_PROVISIONAL_STAGE = 'Provisional Licence'
SNAPSHOT_PATHWAY_STAGES = (SNAPSHOT_PROVISIONAL_STAGE, SNAPSHOT_FULL_STAGE, SNAPSHOT_ATP_STAGE)
SNAPSHOT_STAGE_ORDER = {
    SNAPSHOT_PROVISIONAL_STAGE: 1,
    SNAPSHOT_FULL_STAGE: 2,
    SNAPSHOT_ATP_STAGE: 3,
}
SNAPSHOT_PUBLIC_ORGANIZATIONS = {'Provincial Health Authority (PHA)'}
SNAPSHOT_CHURCH_ORGANIZATIONS = {'Christian Health Services', 'Catholic Health Services'}
SNAPSHOT_PRIVATE_ORGANIZATIONS = {'Private Organization'}


def _snapshot_identity(row):
    return (
        row.get('person_group_key')
        or row.get('registration_no')
        or row.get('practitioner_no')
        or row.get('full_name')
        or row.get('record_id')
    )


def _snapshot_row_value(row, key, default=None):
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def _snapshot_stage_sort_key(stage):
    return (SNAPSHOT_STAGE_ORDER.get(stage, 99), stage or "")


def _snapshot_ordered_stages(stages):
    present = {stage for stage in stages if stage}
    return sorted(present, key=_snapshot_stage_sort_key)


def _snapshot_stages_from_text(value):
    text = " ".join(str(value or "").replace("|", ";").split())
    stages = []
    for stage in SNAPSHOT_PATHWAY_STAGES:
        if stage.lower() in text.lower():
            stages.append(stage)
    for item in text.split(";"):
        stage = item.strip()
        if stage and stage not in stages:
            stages.append(stage)
    return _snapshot_ordered_stages(stages)


def _snapshot_pathway_summary(stages):
    return " / ".join(_snapshot_ordered_stages(stages)) or "-"


def _snapshot_has_complete_pathway(stages):
    present = set(stages)
    return all(stage in present for stage in SNAPSHOT_PATHWAY_STAGES)


def _snapshot_pathway_stats_from_index(index_row):
    stages = set(_snapshot_stages_from_text(index_row.stages_present))
    if index_row.has_provisional:
        stages.add(SNAPSHOT_PROVISIONAL_STAGE)
    if index_row.has_full_licence:
        stages.add(SNAPSHOT_FULL_STAGE)
    if index_row.has_atp:
        stages.add(SNAPSHOT_ATP_STAGE)
    stages = _snapshot_ordered_stages(stages)
    record_count = index_row.record_count or len(stages) or 1
    return {
        "person_group_key": index_row.person_group_key,
        "representative_name": index_row.representative_name,
        "identity_confidence": index_row.identity_confidence,
        "record_count": record_count,
        "stages": stages,
        "stage_summary": _snapshot_pathway_summary(stages),
        "is_complete": _snapshot_has_complete_pathway(stages),
        "first_year": index_row.first_year,
        "latest_year": index_row.latest_year,
        "latest_atp_year": index_row.latest_atp_year,
        "latest_cadre": index_row.latest_cadre,
        "latest_facility": index_row.latest_facility,
        "latest_province": index_row.latest_province,
        "registration_nos": index_row.registration_nos,
        "practitioner_nos": index_row.practitioner_nos,
        "needs_manual_review": index_row.needs_manual_review,
    }


def _snapshot_pathway_stats_from_facts(facts, person_group_key=""):
    stages = []
    years = []
    atp_years = []
    registrations = []
    practitioners = []
    latest_fact = None
    for fact in facts:
        stage = _snapshot_row_value(fact, "lifecycle_stage", "")
        if stage:
            stages.append(stage)
        year = _snapshot_row_value(fact, "cycle_year")
        if year:
            years.append(year)
            if stage == SNAPSHOT_ATP_STAGE:
                atp_years.append(year)
        registration_no = _snapshot_row_value(fact, "registration_no", "")
        practitioner_no = _snapshot_row_value(fact, "practitioner_no", "")
        if registration_no and registration_no not in registrations:
            registrations.append(registration_no)
        if practitioner_no and practitioner_no not in practitioners:
            practitioners.append(practitioner_no)
        if not latest_fact or (year or 0) >= (_snapshot_row_value(latest_fact, "cycle_year") or 0):
            latest_fact = fact

    stages = _snapshot_ordered_stages(stages)
    return {
        "person_group_key": person_group_key,
        "representative_name": _snapshot_row_value(latest_fact, "full_name", "") if latest_fact else "",
        "identity_confidence": _snapshot_row_value(latest_fact, "identity_confidence", "") if latest_fact else "",
        "record_count": len(facts),
        "stages": stages,
        "stage_summary": _snapshot_pathway_summary(stages),
        "is_complete": _snapshot_has_complete_pathway(stages),
        "first_year": min(years) if years else None,
        "latest_year": max(years) if years else None,
        "latest_atp_year": max(atp_years) if atp_years else None,
        "latest_cadre": _snapshot_row_value(latest_fact, "cadre", "") if latest_fact else "",
        "latest_facility": _snapshot_row_value(latest_fact, "facility", "") if latest_fact else "",
        "latest_province": _snapshot_row_value(latest_fact, "province", "") if latest_fact else "",
        "registration_nos": "; ".join(registrations),
        "practitioner_nos": "; ".join(practitioners),
        "needs_manual_review": False,
    }


def _snapshot_pathway_stats_by_key(snapshot, person_group_keys):
    keys = {key for key in person_group_keys if key}
    if not keys:
        return {}

    stats_by_key = {}
    for index_row in snapshot.practitioner_index_rows.filter(person_group_key__in=keys):
        if index_row.person_group_key and index_row.person_group_key not in stats_by_key:
            stats_by_key[index_row.person_group_key] = _snapshot_pathway_stats_from_index(index_row)

    missing_keys = keys - set(stats_by_key)
    if missing_keys:
        facts_by_key = defaultdict(list)
        for fact in snapshot.lifecycle_facts.filter(person_group_key__in=missing_keys).values(
            "person_group_key",
            "lifecycle_stage",
            "cycle_year",
            "full_name",
            "identity_confidence",
            "cadre",
            "facility",
            "province",
            "registration_no",
            "practitioner_no",
        ):
            facts_by_key[fact["person_group_key"]].append(fact)
        for key, facts in facts_by_key.items():
            stats_by_key[key] = _snapshot_pathway_stats_from_facts(facts, key)
    return stats_by_key


def _snapshot_pathway_year_label(stats):
    if not stats:
        return "-"
    first_year = stats.get("first_year")
    latest_year = stats.get("latest_year")
    if first_year and latest_year and first_year != latest_year:
        return f"{first_year}-{latest_year}"
    return latest_year or first_year or "-"


def _snapshot_pathway_detail_url(fact_id, stats=None):
    if stats and stats.get("record_count", 0) > 1:
        return reverse("nursing_analytics_pathway_detail", args=[fact_id])
    return reverse("nursing_analytics_fact_detail", args=[fact_id])


def _snapshot_gender_label(value):
    text = " ".join(str(value or "").split()).lower()
    if text.startswith('f'):
        return 'Female'
    if text.startswith('m'):
        return 'Male'
    return 'Not captured'


def _snapshot_ownership_label(organization_type):
    if organization_type in SNAPSHOT_PUBLIC_ORGANIZATIONS:
        return 'Public'
    if organization_type in SNAPSHOT_CHURCH_ORGANIZATIONS:
        return 'Church'
    if organization_type in SNAPSHOT_PRIVATE_ORGANIZATIONS:
        return 'Private'
    return 'Other'


def _snapshot_facility_group(organization_type):
    if organization_type in SNAPSHOT_PUBLIC_ORGANIZATIONS:
        return 'pha'
    if organization_type in SNAPSHOT_PRIVATE_ORGANIZATIONS:
        return 'private'
    if organization_type in SNAPSHOT_CHURCH_ORGANIZATIONS:
        return 'ngo'
    return 'review'


def _snapshot_category_needs_review(cadre):
    text = " ".join(str(cadre or "").split()).lower()
    return not text or text.startswith('unclassified')


def _snapshot_quality_status(record_quality, data_quality_flags):
    quality = " ".join(str(record_quality or "").split()) or "Not scored"
    flags = [item.strip() for item in str(data_quality_flags or "").replace('|', ';').split(';') if item.strip()]
    if quality.lower() == 'high' and not flags:
        return 'Valid', 'success', flags
    if quality.lower() in {'needs review', 'low'}:
        return 'High risk review', 'danger', flags
    if flags:
        return 'Needs review', 'warning', flags
    if quality.lower() == 'medium':
        return 'Needs review', 'warning', flags
    return quality, 'secondary', flags


def _snapshot_origin_movement(lifecycle_stage, cycle_year, current_year):
    if lifecycle_stage == SNAPSHOT_PROVISIONAL_STAGE:
        return 'incoming', 'Incoming - provisional'
    if lifecycle_stage == SNAPSHOT_FULL_STAGE:
        return 'incoming', 'Incoming - registration'
    if lifecycle_stage == SNAPSHOT_ATP_STAGE:
        if cycle_year and current_year and cycle_year < current_year:
            return 'outgoing', 'Outgoing review - prior-year ATP'
        return 'current', 'Current - practising licence'
    return 'current', 'Current - snapshot record'


def _snapshot_origin_context(snapshot, current_year, limit=REGISTRAR_WORKER_ORIGIN_TABLE_LIMIT):
    origin_queryset = snapshot.lifecycle_facts.filter(
        nationality_group__in=['National', 'Overseas'],
    )
    origin_summary = {}
    for applicant_type, nationality_group in [('national', 'National'), ('overseas', 'Overseas')]:
        subset = origin_queryset.filter(nationality_group=nationality_group)
        grouped = subset.exclude(person_group_key='').values('person_group_key').distinct().count()
        ungrouped = subset.filter(person_group_key='').count()
        origin_summary[applicant_type] = grouped + ungrouped

    per_applicant_limit = max(20, limit // 2)
    preview_rows = []
    for applicant_type, nationality_group in [('overseas', 'Overseas'), ('national', 'National')]:
        seen = set()
        selected = 0
        facts = list(
            origin_queryset
            .filter(nationality_group=nationality_group)
            .values(
                'id',
                'record_id',
                'lifecycle_stage',
                'cycle_year',
                'event_date',
                'full_name',
                'person_group_key',
                'identity_confidence',
                'cadre',
                'formal_qualification',
                'registration_no',
                'practitioner_no',
                'institution',
                'facility',
                'province',
                'organization_type',
                'nationality_group',
                'country',
                'source_workbook',
                'source_sheet',
                'source_row',
                'source_lineage',
            )
            .order_by('-cycle_year', '-event_date', 'full_name', 'record_id')[: per_applicant_limit * 3]
        )
        pathway_stats_by_key = _snapshot_pathway_stats_by_key(
            snapshot,
            {fact.get('person_group_key') for fact in facts if fact.get('person_group_key')},
        )
        for fact in facts:
            identity = _snapshot_identity(fact)
            if identity in seen:
                continue
            seen.add(identity)
            pathway_stats = pathway_stats_by_key.get(fact.get('person_group_key'))
            movement_key, movement_label = _snapshot_origin_movement(
                fact.get('lifecycle_stage'),
                fact.get('cycle_year'),
                current_year,
            )
            source_workbook = fact.get('source_workbook') or snapshot.source_file_name
            source_detail_parts = [source_workbook]
            if fact.get('source_lineage'):
                source_detail_parts.append(fact['source_lineage'])
            elif fact.get('source_sheet'):
                source_detail_parts.append(
                    f"{fact['source_sheet']} row {fact['source_row']}"
                    if fact.get('source_row') else fact['source_sheet']
                )
            has_linked_pathway = bool(pathway_stats and pathway_stats.get('record_count', 0) > 1)
            preview_rows.append({
                'identity_key': identity,
                'source': 'analytics_snapshot',
                'source_label': 'Analytics snapshot pathway' if has_linked_pathway else 'Analytics snapshot',
                'source_detail': ' / '.join(part for part in source_detail_parts if part),
                'detail_url': _snapshot_pathway_detail_url(fact['id'], pathway_stats),
                'name': fact.get('full_name') or 'Snapshot record',
                'registration_no': fact.get('registration_no') or fact.get('practitioner_no') or '-',
                'professional_type': fact.get('cadre') or 'Unclassified / Missing Cadre',
                'applicant_type': applicant_type,
                'applicant_type_label': _applicant_type_label(applicant_type),
                'origin': fact.get('country') or fact.get('nationality_group') or _applicant_type_label(applicant_type),
                'training': fact.get('institution') or fact.get('formal_qualification') or '-',
                'employment': fact.get('organization_type') or '-',
                'facility': fact.get('facility') or '-',
                'province': fact.get('province') or '-',
                'movement': movement_key,
                'movement_label': movement_label,
                'record_year': _snapshot_pathway_year_label(pathway_stats) if has_linked_pathway else fact.get('cycle_year') or '-',
                'record_type': (
                    f"Linked pathway: {pathway_stats['stage_summary']}"
                    if has_linked_pathway else fact.get('lifecycle_stage') or 'Analytics snapshot'
                ),
                'pathway_stage_summary': pathway_stats.get('stage_summary') if pathway_stats else '',
                'pathway_record_count': pathway_stats.get('record_count') if pathway_stats else 0,
                'pathway_complete': bool(pathway_stats and pathway_stats.get('is_complete')),
                'sort_year': (
                    pathway_stats.get('latest_year') or fact.get('cycle_year') or 0
                    if has_linked_pathway else fact.get('cycle_year') or 0
                ),
            })
            selected += 1
            if selected >= per_applicant_limit:
                break

    preview_rows.sort(key=lambda row: (
        0 if row['applicant_type'] == 'overseas' else 1,
        -int(row.get('sort_year') or 0),
        str(row.get('name', '')).lower(),
    ))
    preview_rows = preview_rows[:limit]
    return {
        'registrar_origin_scope': 'nursing',
        'registrar_origin_scope_label': 'Nursing Council',
        'registrar_worker_origin_rows': preview_rows,
        'registrar_worker_origin_table_limit': limit,
        'registrar_worker_origin_summary': {
            'national_total': origin_summary['national'],
            'overseas_total': origin_summary['overseas'],
            'combined_total': origin_summary['national'] + origin_summary['overseas'],
            'snapshot_national_total': origin_summary['national'],
            'snapshot_overseas_total': origin_summary['overseas'],
            'displayed_rows': len(preview_rows),
        },
    }


def _nursing_snapshot_live_context(snapshot, payload):
    cache_key = (
        f"nursing_snapshot_live_context_v5:{snapshot.pk}:"
        f"{snapshot.activated_at.isoformat() if snapshot.activated_at else snapshot.created_at.isoformat()}"
    )
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    kpis = payload.get('kpis', {})
    charts = payload.get('charts', {})
    year_chart = charts.get('year', {})
    live_statistics = payload.get('live_statistics', {})
    atp_queryset = snapshot.lifecycle_facts.filter(lifecycle_stage=SNAPSHOT_ATP_STAGE)
    current_year = live_statistics.get('atp_current_year') or atp_queryset.aggregate(latest=Max('cycle_year'))['latest']
    current_queryset = atp_queryset.filter(cycle_year=current_year) if current_year else atp_queryset.none()
    current_facts = list(
        current_queryset.values(
            'record_id',
            'cycle_year',
            'event_date',
            'full_name',
            'person_group_key',
            'sex',
            'cadre',
            'formal_qualification',
            'registration_no',
            'practitioner_no',
            'facility',
            'province',
            'organization_type',
            'nationality_group',
            'record_quality',
            'data_quality_flags',
            'source_sheet',
            'source_row',
            'source_lineage',
        ).order_by('-event_date', 'full_name', 'record_id')
    )

    yearly_rows = []
    atp_year_rows = []
    atp_year_lookup = {
        row['cycle_year']: row
        for row in atp_queryset.exclude(cycle_year=None).values('cycle_year').annotate(
            record_count=Count('id'),
            people_count=Count('person_group_key', filter=~Q(person_group_key=''), distinct=True),
            province_count=Count('province', filter=~Q(province=''), distinct=True),
        )
    }
    stage_year_rows = list(snapshot.stage_year_metrics.order_by(F('year').desc(nulls_last=True)).values(
        'year',
        'year_label',
        'provisional_licence_count',
        'full_licence_count',
        'authority_to_practice_count',
        'grand_total',
    ))
    for row in stage_year_rows:
        atp_row = atp_year_lookup.get(row['year'], {})
        yearly_rows.append({
            'year': row['year'],
            'graduand_count': row['provisional_licence_count'],
            'full_registration_count': row['full_licence_count'],
            'full_approved_count': 0,
            'temporary_license_count': 0,
            'practicing_license_count': row['authority_to_practice_count'],
            'active_listing_count': 0,
        })
        atp_at_year = row['authority_to_practice_count']
        if atp_at_year:
            atp_year_rows.append({
                'year': row['year'],
                'period_group': _year_band_label(row['year'], current_year or row['year']),
                'record_count': atp_at_year,
                'people_count': atp_row.get('people_count') or atp_at_year,
                'province_count': atp_row.get('province_count') or 0,
                'png_total': 0,
                'overseas_total': 0,
                'late_total': 0,
            })

    current_people = set()
    current_gender = defaultdict(set)
    current_ownership = defaultdict(set)
    current_categories = defaultdict(set)
    category_review = defaultdict(set)
    facility_groups = defaultdict(lambda: {
        'facilities': set(),
        'people': set(),
        'records': 0,
    })
    workplace_map = {}

    for row in current_facts:
        identity = _snapshot_identity(row)
        current_people.add(identity)
        gender_label = _snapshot_gender_label(row.get('sex'))
        current_gender[gender_label].add(identity)
        ownership = _snapshot_ownership_label(row.get('organization_type'))
        current_ownership[ownership].add(identity)
        category = row.get('cadre') or 'Unclassified / Missing Cadre'
        current_categories[category].add(identity)
        if _snapshot_category_needs_review(category):
            category_review[category].add(identity)

        facility_name = row.get('facility') or 'Facility not captured'
        facility_group_key = _snapshot_facility_group(row.get('organization_type'))
        if facility_name != 'Facility not captured':
            facility_groups[facility_group_key]['facilities'].add(facility_name)
        facility_groups[facility_group_key]['people'].add(identity)
        facility_groups[facility_group_key]['records'] += 1

        workplace_entry = workplace_map.setdefault(facility_name, {
            'name': facility_name,
            'ownership': ownership,
            'records': 0,
            'people': set(),
            'provinces': set(),
            'categories': defaultdict(int),
            'recent_names': [],
        })
        workplace_entry['records'] += 1
        workplace_entry['people'].add(identity)
        if row.get('province'):
            workplace_entry['provinces'].add(row['province'])
        workplace_entry['categories'][category] += 1
        if len(workplace_entry['recent_names']) < 4 and row.get('full_name') not in workplace_entry['recent_names']:
            workplace_entry['recent_names'].append(row.get('full_name') or '-')

    gender_order = ['Female', 'Male', 'Not captured']
    gender_rows = [
        {'label': label, 'count': len(current_gender.get(label, set()))}
        for label in gender_order
        if current_gender.get(label)
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
        {'label': label, 'count': len(people)}
        for label, people in sorted(current_categories.items(), key=lambda item: (-len(item[1]), item[0]))
        if not _snapshot_category_needs_review(label)
    ][:12]
    frequent_category_review_rows = [
        {'label': label, 'count': len(people)}
        for label, people in sorted(category_review.items(), key=lambda item: (-len(item[1]), item[0]))[:12]
    ]
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
    for row in current_facts[:60]:
        recent_record_rows.append({
            'full_name': row.get('full_name') or '-',
            'gender': _snapshot_gender_label(row.get('sex')),
            'registration_no': row.get('registration_no') or '-',
            'practitioner_number': row.get('practitioner_no') or '-',
            'category': row.get('cadre') or '-',
            'qualification_name': row.get('formal_qualification') or '-',
            'workplace_name': row.get('facility') or 'Facility not captured',
            'ownership': _snapshot_ownership_label(row.get('organization_type')),
            'province': row.get('province') or 'Province not captured / review',
            'payment_date': row.get('event_date'),
            'renewal_fee': 0,
            'overseas_fee': 0,
            'late_fee': 0,
            'payment_method': 'Analytics snapshot',
            'source_sheet_name': row.get('source_sheet') or '-',
        })

    provisional_rows = []
    for fact in snapshot.lifecycle_facts.filter(lifecycle_stage=SNAPSHOT_PROVISIONAL_STAGE).order_by('-cycle_year', 'full_name').values(
        'record_id',
        'cycle_year',
        'event_date',
        'full_name',
        'registration_no',
        'institution',
        'formal_qualification',
        'record_quality',
        'source_lineage',
    )[:60]:
        provisional_rows.append({
            'full_name': fact.get('full_name') or '-',
            'registration_no': fact.get('registration_no') or '-',
            'license_no': fact.get('record_id') or '-',
            'year': fact.get('cycle_year'),
            'institution': fact.get('institution') or '-',
            'qualification': fact.get('formal_qualification') or '-',
            'issued_date': fact.get('event_date'),
            'expiry_date': None,
            'days_left': None,
            'status': fact.get('record_quality') or 'Snapshot',
            'source': fact.get('source_lineage') or '-',
        })

    full_license_records = []
    full_record_queryset = snapshot.lifecycle_facts.filter(
        lifecycle_stage__in=[SNAPSHOT_FULL_STAGE, SNAPSHOT_ATP_STAGE],
    ).order_by('-cycle_year', '-event_date', 'full_name')
    for fact in full_record_queryset.values(
        'cycle_year',
        'event_date',
        'full_name',
        'registration_no',
        'practitioner_no',
        'lifecycle_stage',
        'institution',
        'facility',
        'source_sheet',
    )[:60]:
        full_license_records.append({
            'record_year': fact.get('cycle_year'),
            'full_name': fact.get('full_name') or '-',
            'registration_no': fact.get('registration_no') or '-',
            'practitioner_number': fact.get('practitioner_no') or '-',
            'get_record_type_display': fact.get('lifecycle_stage') or '-',
            'issued_date': fact.get('event_date'),
            'payment_date': fact.get('event_date'),
            'institution_name': fact.get('institution') or '',
            'workplace_address': fact.get('facility') or '',
            'source_sheet_name': fact.get('source_sheet') or '-',
        })

    province_rows = [
        {
            'label': row['province'],
            'province': row['province'],
            'count': row['total'],
            'total': row['total'],
        }
        for row in payload.get('charts', {}).get('province', {}).get('labels') and [
            {'province': label, 'total': value}
            for label, value in zip(
                payload.get('charts', {}).get('province', {}).get('labels', []),
                payload.get('charts', {}).get('province', {}).get('values', []),
            )
        ] or []
    ]

    institution_reference_count = snapshot.institution_aliases.count()
    facility_reference_count = snapshot.facility_aliases.count()
    facility_grouped_count = atp_queryset.exclude(facility='').values('facility').distinct().count()
    reference_breakdown = {
        **build_reference_breakdown(),
        'snapshot_institution_alias_count': institution_reference_count,
        'snapshot_facility_alias_count': facility_reference_count,
        'snapshot_distinct_facility_count': facility_grouped_count,
    }
    midwife_total = atp_queryset.filter(cadre='Midwife').count()
    nurse_aide_total = atp_queryset.filter(cadre='Nurse Aide').count()
    latest_stage_row = next((row for row in yearly_rows if row['year'] == current_year), None) or {}
    origin_context = _snapshot_origin_context(snapshot, current_year)

    context = {
        'nursing_count': kpis.get('clean_atp_records', 0),
        'midwife_count': midwife_total,
        'nurse_aide_count': nurse_aide_total,
        'institutions_count': reference_breakdown['png_nursing_school_count'],
        'current_provisional_licenses': provisional_rows,
        'provisional_license_count': kpis.get('clean_provisional_records', 0),
        'provisional_license_display_count': len(provisional_rows),
        'provisional_license_limit': len(provisional_rows),
        'reference_breakdown': reference_breakdown,
        'nursing_latest_year': current_year,
        'nursing_latest_full_count': latest_stage_row.get('full_registration_count', 0),
        'nursing_latest_full_approved_count': latest_stage_row.get('full_approved_count', 0),
        'nursing_latest_practicing_count': latest_stage_row.get('practicing_license_count', 0),
        'nursing_yearly_rows': yearly_rows,
        'nursing_full_license_records': full_license_records,
        'nursing_flow_year_labels': json.dumps(year_chart.get('labels', [])),
        'nursing_flow_graduand_values': json.dumps(year_chart.get('provisional', [])),
        'nursing_flow_full_values': json.dumps(year_chart.get('full_licence', [])),
        'nursing_flow_full_approved_values': json.dumps([0 for _value in year_chart.get('labels', [])]),
        'nursing_flow_practicing_values': json.dumps(year_chart.get('authority_to_practice', [])),
        'province_rows': province_rows,
        'province_labels': json.dumps([row['label'] for row in province_rows]),
        'province_values': json.dumps([row['count'] for row in province_rows]),
        'atp_batch': snapshot.source_batch,
        'atp_current_year': current_year,
        'atp_current_record_total': len(current_facts),
        'atp_current_person_total': len(current_people),
        'atp_current_public_total': len(current_ownership.get('Public', set())),
        'atp_current_church_total': len(current_ownership.get('Church', set())),
        'atp_current_private_total': len(current_ownership.get('Private', set())),
        'atp_current_other_total': len(current_ownership.get('Other', set())),
        'frequent_current_nurse_total': len(current_people),
        'frequent_nursing_category_rows': frequent_category_rows,
        'frequent_nursing_category_review_total': sum(len(people) for people in category_review.values()),
        'frequent_nursing_category_review_rows': frequent_category_review_rows,
        'frequent_facility_ownership_rows': facility_ownership_rows,
        'frequent_pha_facility_total': next((row['facility_count'] for row in facility_ownership_rows if row['key'] == 'pha'), 0),
        'frequent_private_facility_total': next((row['facility_count'] for row in facility_ownership_rows if row['key'] == 'private'), 0),
        'frequent_ngo_facility_total': next((row['facility_count'] for row in facility_ownership_rows if row['key'] == 'ngo'), 0),
        'frequent_review_facility_total': next((row['facility_count'] for row in facility_ownership_rows if row['key'] == 'review'), 0),
        'atp_year_rows': atp_year_rows,
        'atp_category_rows': category_rows,
        'atp_gender_rows': gender_rows,
        'atp_workplace_rows': workplace_rows,
        'atp_recent_record_rows': recent_record_rows,
        'atp_year_labels': json.dumps([row['year'] for row in reversed(atp_year_rows)]),
        'atp_year_values': json.dumps([row['people_count'] for row in reversed(atp_year_rows)]),
        'atp_gender_labels': json.dumps([row['label'] for row in gender_rows]),
        'atp_gender_values': json.dumps([row['count'] for row in gender_rows]),
        'atp_ownership_labels': json.dumps([row['label'] for row in ownership_rows]),
        'atp_ownership_values': json.dumps([row['count'] for row in ownership_rows]),
    }
    context.update(origin_context)
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
            scope=scope if scope in {'medical', 'nursing'} else import_scope,
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
            provisional_count = latest_batch_records.filter(record_type='provisional').count()
            full_temporary_count = latest_batch_records.filter(record_type__in=['full', 'temporary']).count()
            renewal_count = latest_batch_records.filter(record_type='practicing_license').count()
            context['incoming_graduands'] = provisional_count
            context['graduates_entering'] = full_temporary_count
            context['flow_labels'] = ['Provisional', 'Full/Temporary', 'Renewals', 'Young Workforce']
            context['flow_data'] = [
                provisional_count,
                full_temporary_count,
                renewal_count,
                context.get('young_workers', 0),
            ]
    return context


def _apply_nursing_overview_scope(context):
    context['dashboard_scope'] = 'nursing'
    snapshot = active_nursing_analytics_snapshot()
    if snapshot:
        payload = nursing_analytics_metric_payload(snapshot)
        snapshot_context = _nursing_snapshot_live_context(snapshot, payload)
        snapshot_references = snapshot_context.get('reference_breakdown', {})
        context['nursing_count'] = snapshot_context.get('nursing_count', context.get('nursing_count', 0))
        context['midwife_count'] = snapshot_context.get('midwife_count', context.get('midwife_count', 0))
        context['nurse_aide_count'] = snapshot_context.get('nurse_aide_count', context.get('nurse_aide_count', 0))
        context['graduand_count'] = snapshot_context.get('provisional_license_count', context.get('graduand_count', 0))
        context['provisional_applicant_count'] = snapshot_context.get(
            'provisional_license_count',
            context.get('provisional_applicant_count', 0),
        )
        context['student_count'] = context['graduand_count']
        context['incoming_graduands'] = context['graduand_count']
        context['incoming_students'] = context['graduand_count']
        context['graduates_entering'] = payload.get('kpis', {}).get(
            'clean_full_licence_records',
            context.get('graduates_entering', 0),
        )
        context['facility_count'] = snapshot_references.get(
            'facility_grouped_reference_count',
            context.get('facility_count', 0),
        )
        context['nursing_analytics_snapshot'] = snapshot
        context['nursing_analytics_payload'] = payload
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


def _payload_has_any(payload, keys):
    for key in keys:
        value = payload.get(key)
        if isinstance(value, bool):
            if value:
                return True
        elif value:
            return True
    return False


def _medical_board_application_display(application):
    professional = getattr(application, "professional", None)
    if professional:
        return str(professional)
    payload = application.payload or {}
    for key in ("full_name", "applicant_name", "doctor_name", "chw_name", "facility_name", "training_college_name", "name"):
        if payload.get(key):
            return str(payload[key])
    return "Medical Board Application"


def _medical_board_application_readiness(application):
    payload = application.payload or {}
    professional = getattr(application, "professional", None)
    has_receipt = Receipt.objects.filter(application=application, status="completed").exists()
    has_cpd = False
    if application.content_type_id and application.object_id:
        has_cpd = CPDRecord.objects.filter(
            content_type=application.content_type,
            object_id=application.object_id,
        ).exists()
    is_renewal = application.form_code in {"MD2", "MBRN", "CHWP", "CHWF"}
    checks = [
        {
            "key": "identity",
            "label": "Identity",
            "complete": bool(
                professional
                or _payload_has_any(payload, ["full_name", "applicant_name", "doctor_name", "chw_name", "registration_no", "licence_number"])
            ),
        },
        {
            "key": "qualification",
            "label": "Qualification",
            "complete": bool(
                _payload_has_any(payload, ["qualification", "qualification_name", "degree", "training_level", "institution_name"])
                or (professional and getattr(professional, "cadre_id", None))
            ),
        },
        {
            "key": "good_standing",
            "label": "Good Standing",
            "complete": _payload_has_any(payload, ["good_standing", "certificate_good_standing", "cogs", "registration_status"]),
        },
        {
            "key": "cpd",
            "label": "CPD/CME",
            "complete": bool(
                has_cpd
                or _payload_has_any(payload, ["cpd", "cme", "cpd_points", "cme_points", "professional_development"])
                or not is_renewal
            ),
        },
        {
            "key": "receipt",
            "label": "Receipt",
            "complete": bool(has_receipt or _payload_has_any(payload, ["receipt_number", "payment_reference", "payment_receipt"])),
        },
        {
            "key": "practice_setting",
            "label": "Facility/Supervisor",
            "complete": _payload_has_any(payload, ["facility", "facility_name", "workplace", "employer", "supervisor", "practice_setting", "training_site"]),
        },
        {
            "key": "decision",
            "label": "Decision",
            "complete": application.status in {"approved", "rejected"},
        },
    ]
    complete_count = sum(1 for check in checks if check["complete"])
    percent = round((complete_count / len(checks)) * 100) if checks else 0
    if percent >= 80:
        status = "Ready"
        badge = "success"
    elif percent >= 50:
        status = "Review"
        badge = "warning"
    else:
        status = "Incomplete"
        badge = "danger"
    return {
        "application": application,
        "display_name": _medical_board_application_display(application),
        "checks": checks,
        "complete_count": complete_count,
        "total_count": len(checks),
        "percent": percent,
        "status": status,
        "badge": badge,
    }


def _nursing_council_public_protection_context(user=None):
    professional_cts = [
        ContentType.objects.get_for_model(model)
        for model in (NursingProfessional, Midwife, NurseAide, HealthStudent)
    ]
    nursing_applications = Application.objects.filter(form_code__in=NURSING_FORM_CODES)
    nursing_decisions = RegulatoryDecisionRecord.objects.filter(office_scope="nursing")
    nursing_records = _quality_approved_practicing_records().filter(
        batch__source_kind__in=NURSING_IMPORT_SOURCE_KINDS,
        target_model__in=NURSING_IMPORT_TARGET_MODELS,
    )
    active_atp_identities = {
        _record_identity(record)
        for record in nursing_records.filter(record_type="practicing_license")
        if _record_identity(record)
    }
    reference_breakdown = build_reference_breakdown()
    open_complaints = open_complaint_cases(user).filter(office_scope="nursing") if user else RegulatoryDecisionRecord.objects.none()
    open_discipline = open_disciplinary_cases(user).filter(office_scope="nursing") if user else RegulatoryDecisionRecord.objects.none()
    current_year = date.today().year
    current_atp_records = nursing_records.filter(record_type="practicing_license", record_year=current_year)
    if current_atp_records.exists():
        current_atp_count = _identity_count(current_atp_records)
    else:
        current_atp_count = len(active_atp_identities)

    assurance_lanes = [
        {
            "label": "Public register",
            "count": NursingProfessional.objects.count() + Midwife.objects.count() + NurseAide.objects.count(),
            "detail": "Nurses, midwives, and nurse aides available for public-safe verification.",
            "icon": "fas fa-search",
            "href": reverse("public_nursing_register_search_root"),
        },
        {
            "label": "Current ATP / APC",
            "count": current_atp_count,
            "detail": "Current-year authority-to-practise identities from approved imports.",
            "icon": "fas fa-id-card",
            "href": reverse("nursing_frequent_records"),
        },
        {
            "label": "Recognised schools",
            "count": reference_breakdown.get("png_nursing_school_count", 0),
            "detail": "PNG nursing schools separated from CHW and Medical Board training references.",
            "icon": "fas fa-school",
            "href": reverse("workforce_map") + "?office=nursing&type=school",
        },
        {
            "label": "Fitness to practise",
            "count": open_complaints.count() + open_discipline.count(),
            "detail": "Open complaints and discipline matters under Nursing Council scope.",
            "icon": "fas fa-scale-balanced",
            "href": reverse("complaint_case_list") + "?office=nursing",
        },
        {
            "label": "Decision register",
            "count": nursing_decisions.filter(status="final").count(),
            "detail": "Final registration, licence, renewal, and conduct decisions.",
            "icon": "fas fa-file-signature",
            "href": reverse("regulatory_decision_list") + "?office=nursing",
        },
        {
            "label": "CPD evidence",
            "count": CPDRecord.objects.filter(content_type__in=professional_cts).count(),
            "detail": "Continuing professional development records linked to Nursing Council profiles.",
            "icon": "fas fa-graduation-cap",
            "href": reverse("record_list", args=["cpdrecord"]),
        },
    ]
    public_trust_actions = [
        {"label": "Verify Public Register", "detail": "Public-safe name and registration lookup.", "href": reverse("public_nursing_register_search_root"), "icon": "fas fa-search"},
        {"label": "Nursing Forms", "detail": "NC1, NC2, NC3, overseas and competency pathways.", "href": reverse("nursing_forms_portal"), "icon": "fas fa-file-signature"},
        {"label": "Schools and Facilities Map", "detail": "Recognised schools and reviewed facility references.", "href": reverse("workforce_map") + "?office=nursing", "icon": "fas fa-map-location-dot"},
        {"label": "ICMS and Discipline", "detail": "Complaints, discipline, conditions, and final decisions.", "href": reverse("complaint_case_list") + "?office=nursing", "icon": "fas fa-scale-balanced"},
        {"label": "Standards Alignment", "detail": "Government health workforce standards and interoperability.", "href": reverse("platform_standards_alignment"), "icon": "fas fa-building-columns"},
    ]
    return {
        "nursing_assurance_lanes": assurance_lanes,
        "nursing_public_trust_actions": public_trust_actions,
        "nursing_formal_decision_count": nursing_decisions.filter(status="final").count(),
        "nursing_draft_decision_count": nursing_decisions.filter(status="draft").count(),
        "nursing_open_complaint_count": open_complaints.count(),
        "nursing_open_discipline_count": open_discipline.count(),
        "nursing_cpd_evidence_count": CPDRecord.objects.filter(content_type__in=professional_cts).count(),
        "nursing_evidence_document_count": ProfessionalDocument.objects.filter(content_type__in=professional_cts).count(),
    }


def _choice_or_default(value, choices, default):
    allowed = {choice_value for choice_value, _label in choices}
    return value if value in allowed else default


def _board_role_for_user(meeting, user):
    if meeting and meeting.chair_id == getattr(user, "id", None):
        return "chair"
    if meeting and meeting.secretary_id == getattr(user, "id", None):
        return "secretary"
    return "member" if is_nursing_council_board_member(user) else "observer"


def _nursing_board_decision_queue(user):
    queue = []
    pending_applications = (
        Application.objects.filter(status="pending", form_code__in=NURSING_FORM_CODES)
        .select_related("content_type")
        .order_by("-submitted_date", "-id")[:8]
    )
    for application in pending_applications:
        professional = getattr(application, "professional", None)
        queue.append({
            "source": "Registration",
            "title": f"{application.form_code} application #{application.pk}",
            "subject": str(professional or application.payload.get("full_name") or "Applicant pending review"),
            "status": application.get_status_display() if hasattr(application, "get_status_display") else application.status,
            "priority": "Decision",
            "committee": "Registration Committee",
            "confidentiality": "Private",
            "href": reverse("application_detail", args=[application.pk]),
        })

    draft_decisions = (
        scoped_decision_records(user)
        .filter(office_scope="nursing", status="draft")
        .select_related("subject_content_type")
        .order_by("-updated_at")[:6]
    )
    for decision in draft_decisions:
        queue.append({
            "source": "Decision Register",
            "title": decision.title,
            "subject": decision.subject_name or decision.subject_identifier or "Decision subject",
            "status": decision.get_status_display(),
            "priority": decision.get_decision_type_display(),
            "committee": "Board / Registrar",
            "confidentiality": "Private",
            "href": reverse("regulatory_decision_detail", args=[decision.decision_uuid]),
        })

    for complaint in open_complaint_cases(user).filter(office_scope="nursing").order_by("-updated_at")[:5]:
        queue.append({
            "source": "ICMS",
            "title": complaint.title,
            "subject": complaint.subject_name or complaint.complainant_display,
            "status": complaint.get_status_display(),
            "priority": complaint.get_risk_level_display(),
            "committee": "Conduct Committee",
            "confidentiality": "Confidential",
            "href": reverse("complaint_case_detail", args=[complaint.case_uuid]),
        })

    for case in open_disciplinary_cases(user).filter(office_scope="nursing").order_by("-updated_at")[:5]:
        queue.append({
            "source": "Discipline",
            "title": case.allegation_summary[:120] or case.subject_name,
            "subject": case.subject_name,
            "status": case.get_stage_display(),
            "priority": case.get_severity_display(),
            "committee": "Professional Conduct",
            "confidentiality": "Confidential",
            "href": reverse("disciplinary_case_detail", args=[case.discipline_uuid]),
        })

    return queue[:18]


def _nursing_board_committee_rows(user):
    reference_breakdown = build_reference_breakdown()
    nursing_records = _quality_approved_practicing_records().filter(
        batch__source_kind__in=NURSING_IMPORT_SOURCE_KINDS,
        target_model__in=NURSING_IMPORT_TARGET_MODELS,
    )
    professional_cts = [
        ContentType.objects.get_for_model(model)
        for model in (NursingProfessional, Midwife, NurseAide, HealthStudent)
    ]
    pending_application_count = Application.objects.filter(status="pending", form_code__in=NURSING_FORM_CODES).count()
    missing_review_count = MissingDataReview.objects.filter(
        professional_type__in=["Nursing Professional", "Midwife", "Graduand", "Practicing License Record"],
    ).exclude(status="resolved").count()
    open_complaint_count = open_complaint_cases(user).filter(office_scope="nursing").count()
    open_discipline_count = open_disciplinary_cases(user).filter(office_scope="nursing").count()
    draft_decision_count = scoped_decision_records(user).filter(office_scope="nursing", status="draft").count()

    return [
        {
            "committee": "Registration Committee",
            "icon": "fas fa-id-card",
            "status": "Decision workload",
            "metrics": [
                ("Pending applications", pending_application_count),
                ("Full licence rows", nursing_records.filter(record_type__in=["full", "full_approved"]).count()),
                ("ATP rows", nursing_records.filter(record_type="practicing_license").count()),
            ],
            "href": reverse("nursing_council_portal") + "#nursing-pathways",
        },
        {
            "committee": "Education Committee",
            "icon": "fas fa-school",
            "status": "Accreditation and graduate lists",
            "metrics": [
                ("Recognised schools", reference_breakdown.get("png_nursing_school_count", 0)),
                ("Training institutions", TrainingInstitution.objects.count()),
                ("Mapped nursing entities", MappedEntity.objects.filter(is_active=True, office_scope__in=["nursing", "shared"]).count()),
            ],
            "href": reverse("workforce_map") + "?office=nursing&type=school",
        },
        {
            "committee": "Standards Committee",
            "icon": "fas fa-book-medical",
            "status": "Standards, CPD and policy",
            "metrics": [
                ("CPD evidence", CPDRecord.objects.filter(content_type__in=professional_cts).count()),
                ("Policy documents", Document.objects.filter(office_scope__in=["nursing", "general"], status__in=["active", "draft"]).count()),
                ("Data reviews", missing_review_count),
            ],
            "href": reverse("platform_standards_alignment"),
        },
        {
            "committee": "Conduct Committee",
            "icon": "fas fa-scale-balanced",
            "status": "Public protection",
            "metrics": [
                ("Open complaints", open_complaint_count),
                ("Open discipline", open_discipline_count),
                ("Draft decisions", draft_decision_count),
            ],
            "href": reverse("complaint_case_list") + "?office=nursing",
        },
    ]


def _nursing_board_portal_context(request):
    user = request.user
    now = timezone.now()
    meetings = NursingCouncilBoardMeeting.objects.select_related("chair", "secretary").exclude(
        status="cancelled"
    ).order_by("scheduled_for")
    current_meeting = meetings.filter(scheduled_for__gte=now).first() or meetings.order_by("-scheduled_for").first()
    agenda_items = []
    board_papers = []
    attendance_records = []
    user_attendance = None
    action_items = []
    present_count = 0
    apology_count = 0
    conflict_count = 0
    quorum_required = 5

    if current_meeting:
        agenda_items = list(
            current_meeting.agenda_items.select_related("presenter", "related_decision", "related_document").order_by("order", "id")
        )
        board_papers = list(
            current_meeting.papers.select_related("agenda_item", "document", "prepared_by").order_by("agenda_item__order", "title")
        )
        attendance_records = list(
            current_meeting.attendance_records.select_related("member").order_by("role_on_board", "member__last_name", "member__first_name")
        )
        action_items = list(
            current_meeting.action_items.select_related("owner", "agenda_item", "source_decision").order_by("status", "due_date", "priority", "title")
        )
        user_attendance = next((item for item in attendance_records if item.member_id == user.id), None)
        present_count = sum(1 for item in attendance_records if item.attendance_status == "present")
        apology_count = sum(1 for item in attendance_records if item.attendance_status == "apology")
        conflict_count = sum(1 for item in attendance_records if item.conflict_declared)
        quorum_required = current_meeting.quorum_required

    recent_meetings = list(meetings.order_by("-scheduled_for")[:6])
    decision_queue = _nursing_board_decision_queue(user)
    committee_rows = _nursing_board_committee_rows(user)
    recent_documents = list(
        Document.objects.filter(office_scope__in=["nursing", "general"], status__in=["active", "draft"])
        .select_related("folder")
        .order_by("-updated_at")[:8]
    )

    board_metrics = [
        {"label": "Decision queue", "value": len(decision_queue), "icon": "fas fa-list-check", "theme": "navy"},
        {"label": "Board papers", "value": len(board_papers) if current_meeting else len(recent_documents), "icon": "fas fa-folder-open", "theme": "green"},
        {"label": "Open actions", "value": sum(1 for item in action_items if item.status not in {"completed", "cancelled"}), "icon": "fas fa-clipboard-check", "theme": "amber"},
        {"label": "Conflicts declared", "value": conflict_count, "icon": "fas fa-triangle-exclamation", "theme": "red" if conflict_count else "slate"},
    ]
    default_agenda_items = [
        {"order": 1, "title": "Apologies, attendance, quorum and conflicts of interest", "purpose": "Governance", "confidentiality": "Private"},
        {"order": 2, "title": "Confirmation of previous minutes and action register", "purpose": "Approval", "confidentiality": "Private"},
        {"order": 3, "title": "Registration Committee report and applicant exceptions", "purpose": "Decision", "confidentiality": "Private"},
        {"order": 4, "title": "Education Committee accreditation and graduate-list approvals", "purpose": "Decision", "confidentiality": "Private"},
        {"order": 5, "title": "Standards, CPD and professional conduct assurance", "purpose": "Discussion", "confidentiality": "Private"},
        {"order": 6, "title": "Complaints, discipline, conditions and public-protection risks", "purpose": "Decision", "confidentiality": "Confidential"},
        {"order": 7, "title": "Registrar report, finance, data quality and risk register", "purpose": "Noting", "confidentiality": "Private"},
    ]
    governance_controls = [
        "MFA-ready board-member login and role-separated access",
        "Public, private and confidential agenda classification",
        "Attendance, apology, conflict and recusal register",
        "Board papers linked to controlled document records",
        "Decision queue tied to applications, complaints and final decision records",
        "Action register with owner, due date, priority and completion status",
    ]

    return {
        "board_current_meeting": current_meeting,
        "board_recent_meetings": recent_meetings,
        "board_agenda_items": agenda_items,
        "board_default_agenda_items": default_agenda_items,
        "board_papers": board_papers,
        "board_recent_documents": recent_documents,
        "board_attendance_records": attendance_records,
        "board_user_attendance": user_attendance,
        "board_action_items": action_items,
        "board_decision_queue": decision_queue,
        "board_committee_rows": committee_rows,
        "board_metrics": board_metrics,
        "board_present_count": present_count,
        "board_apology_count": apology_count,
        "board_conflict_count": conflict_count,
        "board_quorum_required": quorum_required,
        "board_quorum_met": present_count >= quorum_required,
        "board_user_role": _board_role_for_user(current_meeting, user),
        "board_can_manage": can_manage_regulatory_operations(user) or is_system_admin(user),
        "board_governance_controls": governance_controls,
        "board_attendance_status_choices": NursingCouncilBoardAttendance.STATUS_CHOICES,
        "board_action_status_choices": NursingCouncilBoardActionItem.STATUS_CHOICES,
        "board_action_priority_choices": NursingCouncilBoardActionItem.PRIORITY_CHOICES,
        "board_agenda_purpose_choices": NursingCouncilBoardAgendaItem.PURPOSE_CHOICES,
        "board_agenda_category_choices": NursingCouncilBoardAgendaItem.CATEGORY_CHOICES,
        "board_today": timezone.localdate(),
    }


def _handle_nursing_board_portal_post(request):
    if not can_access_nursing_board_portal(request.user):
        raise Http404("Board portal not available")

    action = request.POST.get("board_action", "")
    meeting = get_object_or_404(NursingCouncilBoardMeeting, pk=request.POST.get("meeting_id"))
    target = reverse("nursing_council_board_portal")

    if action == "record_attendance":
        attendance_status = _choice_or_default(
            request.POST.get("attendance_status"),
            NursingCouncilBoardAttendance.STATUS_CHOICES,
            "expected",
        )
        conflict_declared = request.POST.get("conflict_declared") == "on"
        conflict_note = str(request.POST.get("conflict_note") or "").strip()
        defaults = {
            "role_on_board": _board_role_for_user(meeting, request.user),
            "attendance_status": attendance_status,
            "conflict_declared": conflict_declared,
            "conflict_note": conflict_note,
            "recusal_required": conflict_declared and request.POST.get("recusal_required") == "on",
        }
        NursingCouncilBoardAttendance.objects.update_or_create(
            meeting=meeting,
            member=request.user,
            defaults=defaults,
        )
        messages.success(request, "Board attendance and conflict declaration saved.")
        return redirect(f"{target}#board-attendance")

    if action == "add_action_item":
        title = str(request.POST.get("title") or "").strip()
        if not title:
            messages.error(request, "Action title is required.")
            return redirect(f"{target}#board-actions")
        NursingCouncilBoardActionItem.objects.create(
            meeting=meeting,
            title=title,
            description=str(request.POST.get("description") or "").strip(),
            owner=request.user,
            due_date=parse_date(request.POST.get("due_date") or ""),
            priority=_choice_or_default(request.POST.get("priority"), NursingCouncilBoardActionItem.PRIORITY_CHOICES, "normal"),
            created_by=request.user,
        )
        messages.success(request, "Board action item added.")
        return redirect(f"{target}#board-actions")

    if action == "update_action_status":
        item = get_object_or_404(NursingCouncilBoardActionItem, pk=request.POST.get("action_id"), meeting=meeting)
        can_update = can_manage_regulatory_operations(request.user) or item.owner_id == request.user.id
        if not can_update:
            messages.error(request, "Only the action owner or approved operations staff can update this action.")
            return redirect(f"{target}#board-actions")
        item.status = _choice_or_default(request.POST.get("status"), NursingCouncilBoardActionItem.STATUS_CHOICES, item.status)
        item.save(update_fields=["status", "completed_at", "updated_at"])
        messages.success(request, "Board action status updated.")
        return redirect(f"{target}#board-actions")

    if action == "add_agenda_item":
        if not (can_manage_regulatory_operations(request.user) or is_nursing_council_board_member(request.user)):
            messages.error(request, "You do not have permission to add board agenda items.")
            return redirect(f"{target}#board-agenda")
        title = str(request.POST.get("title") or "").strip()
        if not title:
            messages.error(request, "Agenda item title is required.")
            return redirect(f"{target}#board-agenda")
        next_order = (meeting.agenda_items.aggregate(Max("order")).get("order__max") or 0) + 1
        NursingCouncilBoardAgendaItem.objects.create(
            meeting=meeting,
            order=next_order,
            title=title,
            purpose=_choice_or_default(request.POST.get("purpose"), NursingCouncilBoardAgendaItem.PURPOSE_CHOICES, "discussion"),
            category=_choice_or_default(request.POST.get("category"), NursingCouncilBoardAgendaItem.CATEGORY_CHOICES, "governance"),
            confidentiality="private",
            summary=str(request.POST.get("summary") or "").strip(),
            presenter=request.user,
        )
        messages.success(request, "Board agenda item added.")
        return redirect(f"{target}#board-agenda")

    messages.error(request, "Board portal action was not recognised.")
    return redirect(target)


def _medical_board_context(user=None):
    doctor_ct = ContentType.objects.get_for_model(MedicalDoctor)
    chw_ct = ContentType.objects.get_for_model(CommunityHealthWorker)
    facility_ct = ContentType.objects.get_for_model(Facility)
    reference_breakdown = build_reference_breakdown()
    medical_form_codes = sorted(MEDICAL_BOARD_FORM_CODES)
    recent_applications = list(
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

    expiring_soon_cutoff = today + timedelta(days=90)
    expired_doctor_license_count = MedicalDoctor.objects.filter(license_expiry_date__lt=today).count()
    expiring_doctor_license_count = MedicalDoctor.objects.filter(
        license_expiry_date__gte=today,
        license_expiry_date__lte=expiring_soon_cutoff,
    ).count()
    practicing_total = doctor_practicing_total + chw_practicing_total
    registered_total = doctor_registration_total + chw_registration_total
    registered_without_practicing_count = max(registered_total - practicing_total, 0)
    recent_decisions = []
    open_medical_complaints = []
    open_medical_discipline = []
    open_medical_complaint_count = 0
    open_medical_discipline_count = 0
    high_risk_medical_complaint_count = 0
    high_severity_medical_discipline_count = 0
    medical_decision_queryset = None
    if user is not None and getattr(user, "is_authenticated", False):
        open_medical_complaint_queryset = open_complaint_cases(user).filter(office_scope="medical")
        open_medical_discipline_queryset = open_disciplinary_cases(user).filter(office_scope="medical")
        open_medical_complaint_count = open_medical_complaint_queryset.count()
        open_medical_discipline_count = open_medical_discipline_queryset.count()
        high_risk_medical_complaint_count = open_medical_complaint_queryset.filter(
            Q(risk_level__in=["high", "critical"]) | Q(priority="critical")
        ).count()
        high_severity_medical_discipline_count = open_medical_discipline_queryset.filter(
            severity__in=["high", "critical"],
        ).count()
        open_medical_complaints = list(open_medical_complaint_queryset.order_by("-updated_at")[:5])
        open_medical_discipline = list(open_medical_discipline_queryset.order_by("-updated_at")[:5])
        medical_decision_queryset = scoped_decision_records(user).filter(office_scope="medical")
        recent_decisions = list(medical_decision_queryset.order_by("-updated_at")[:5])

    final_decision_count = medical_decision_queryset.filter(status="final").count() if medical_decision_queryset is not None else 0
    draft_decision_count = medical_decision_queryset.filter(status="draft").count() if medical_decision_queryset is not None else 0
    active_condition_count = 0
    if medical_decision_queryset is not None:
        active_condition_count = medical_decision_queryset.filter(
            status="final",
        ).exclude(conditions="").exclude(expiry_date__lt=today).count()

    latest_refresh_date = None
    if latest_medical_import:
        latest_refresh_date = latest_medical_import.completed_at or latest_medical_import.started_at
    import_status_label = latest_medical_import.get_status_display() if latest_medical_import else "No import"
    import_status_theme = "success" if latest_medical_import and latest_medical_import.status == "completed" else "warning"
    application_readiness_rows = [
        _medical_board_application_readiness(application)
        for application in recent_applications[:10]
    ]

    medical_facility_forms = Application.objects.filter(content_type=facility_ct, form_code__in=['MBAC', 'MBPF', 'MBTC'])
    quality_context = _data_quality_review_context(medical_missing_reviews, limit=20, scope_key="medical")
    medical_risk_tiles = [
        {
            "label": "Pending registration decisions",
            "count": Application.objects.filter(form_code__in=medical_form_codes, status="pending").count(),
            "detail": "Applications awaiting Registrar or reviewer action.",
            "theme": "primary",
            "href": "#medical-application-readiness",
        },
        {
            "label": "Practising certificates expiring",
            "count": expiring_doctor_license_count + expired_doctor_license_count,
            "detail": f"{expired_doctor_license_count} already expired; monitored over 90 days.",
            "theme": "warning" if expiring_doctor_license_count else "secondary",
            "href": "#medical-registration-status",
        },
        {
            "label": "High-risk data quality",
            "count": quality_context["high_priority_missing_data_count"],
            "detail": "Missing or inconsistent registration evidence.",
            "theme": "danger" if quality_context["high_priority_missing_data_count"] else "success",
            "href": "#medical-data-quality",
        },
        {
            "label": "Open complaints",
            "count": open_medical_complaint_count,
            "detail": f"{high_risk_medical_complaint_count} high-risk or critical matters.",
            "theme": "danger" if high_risk_medical_complaint_count else "secondary",
            "href": reverse("complaint_case_list") + "?office=medical",
        },
        {
            "label": "Open discipline cases",
            "count": open_medical_discipline_count,
            "detail": f"{high_severity_medical_discipline_count} high-severity matters.",
            "theme": "danger" if high_severity_medical_discipline_count else "secondary",
            "href": reverse("disciplinary_case_list") + "?office=medical",
        },
        {
            "label": "Import assurance",
            "count": latest_medical_import.processed_rows if latest_medical_import else 0,
            "detail": f"Latest Medical Board import status: {import_status_label}.",
            "theme": import_status_theme,
            "href": "#medical-import-assurance",
        },
    ]
    medical_register_status_rows = [
        {
            "register": "Medical practitioners",
            "registered": doctor_registration_total or len(doctors),
            "licensed": doctor_practicing_total,
            "profiles": len(doctors),
            "expiring": expiring_doctor_license_count,
            "expired": expired_doctor_license_count,
            "conditions": active_condition_count,
            "status": "Operational",
        },
        {
            "register": "Specialists",
            "registered": max(specialist_profile_count, specialist_import_count),
            "licensed": specialist_import_count,
            "profiles": specialist_profile_count,
            "expiring": 0,
            "expired": 0,
            "conditions": 0,
            "status": "Specialist list",
        },
        {
            "register": "Community Health Workers",
            "registered": chw_registration_total,
            "licensed": chw_practicing_total,
            "profiles": len(chws),
            "expiring": 0,
            "expired": 0,
            "conditions": 0,
            "status": "Medical Board CHW scope",
        },
        {
            "register": "Facilities and training colleges",
            "registered": medical_facility_forms.count(),
            "licensed": 0,
            "profiles": Facility.objects.count(),
            "expiring": 0,
            "expired": 0,
            "conditions": 0,
            "status": "Accreditation queue",
        },
    ]
    medical_regulatory_lanes = [
        {"label": "Doctors", "count": len(doctors), "detail": f"{doctor_practicing_total} practising licence records", "icon": "fas fa-user-doctor", "href": "#medical-registration-status"},
        {"label": "Specialists", "count": max(specialist_profile_count, specialist_import_count), "detail": "Specialist register and credentials", "icon": "fas fa-stethoscope", "href": "#medical-specialty-assurance"},
        {"label": "CHW", "count": len(chws), "detail": f"{chw_practicing_total} practising licence records", "icon": "fas fa-kit-medical", "href": "#medical-chw-assurance"},
        {"label": "Practising Certificates", "count": practicing_total, "detail": f"{registered_without_practicing_count} registered without current licence record", "icon": "fas fa-id-card", "href": "#medical-registration-status"},
        {"label": "Facilities", "count": Facility.objects.count(), "detail": f"{medical_facility_forms.count()} accreditation applications", "icon": "fas fa-hospital", "href": "#medical-facility-assurance"},
        {"label": "Fitness to Practise", "count": open_medical_complaint_count + open_medical_discipline_count, "detail": "ICMS, discipline and decisions", "icon": "fas fa-scale-balanced", "href": "#medical-fitness"},
        {"label": "Data Quality", "count": quality_context["missing_data_review_count"], "detail": "Evidence and import review", "icon": "fas fa-triangle-exclamation", "href": "#medical-data-quality"},
        {"label": "Reports", "count": final_decision_count, "detail": f"{draft_decision_count} draft decision records", "icon": "fas fa-file-signature", "href": reverse("regulatory_decision_list") + "?office=medical"},
    ]
    medical_public_trust_actions = [
        {"label": "Verify Register Record", "detail": "Staff search for public-facing practitioner status.", "href": reverse("dashboard_search"), "icon": "fas fa-search"},
        {"label": "Forms and Applications", "detail": "Doctor, specialist, CHW, facility and training college forms.", "href": reverse("medical_board_register"), "icon": "fas fa-file-medical"},
        {"label": "Complaints Intake", "detail": "Public complaint and professional conduct intake.", "href": reverse("complaint_public_submit"), "icon": "fas fa-inbox"},
        {"label": "Medical Board Fees", "detail": "Registration, renewal and CHW fee schedule.", "href": reverse("fee_structure"), "icon": "fas fa-receipt"},
        {"label": "Medical Facilities Map", "detail": "Facility and training location assurance.", "href": reverse("workforce_map"), "icon": "fas fa-map-location-dot"},
        {"label": "Decision Register", "detail": "Formal decisions, conditions, evidence and appeal rights.", "href": reverse("regulatory_decision_list") + "?office=medical", "icon": "fas fa-gavel"},
    ]
    facility_breakdown_context = _medical_facility_institution_breakdown_context()
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
        'medical_chw_training_reference_count': reference_breakdown['medical_board_chw_training_reference_count'],
        'medical_chw_training_examples': reference_breakdown['medical_board_chw_training_examples'],
        'medical_flow_year_labels': json.dumps([row['year'] for row in chart_rows]),
        'medical_flow_doctor_values': json.dumps([row['doctor_registration_count'] for row in chart_rows]),
        'medical_flow_chw_values': json.dumps([row['chw_registration_count'] for row in chart_rows]),
        'medical_flow_practicing_values': json.dumps([
            row['doctor_practicing_count'] + row['chw_practicing_count']
            for row in chart_rows
        ]),
        **quality_context,
        'expiring_medical_licenses': expiring_licenses,
        'medical_expiring_license_count': expiring_doctor_license_count,
        'medical_expired_license_count': expired_doctor_license_count,
        'medical_registered_without_practicing_count': registered_without_practicing_count,
        'medical_active_condition_count': active_condition_count,
        'medical_formal_decision_count': final_decision_count,
        'medical_draft_decision_count': draft_decision_count,
        'medical_open_complaint_count': open_medical_complaint_count,
        'medical_high_risk_complaint_count': high_risk_medical_complaint_count,
        'medical_open_discipline_count': open_medical_discipline_count,
        'medical_high_severity_discipline_count': high_severity_medical_discipline_count,
        'medical_recent_complaints': open_medical_complaints,
        'medical_recent_discipline_cases': open_medical_discipline,
        'medical_recent_decisions': recent_decisions,
        'medical_risk_tiles': medical_risk_tiles,
        'medical_register_status_rows': medical_register_status_rows,
        'medical_regulatory_lanes': medical_regulatory_lanes,
        'medical_public_trust_actions': medical_public_trust_actions,
        'medical_application_readiness_rows': application_readiness_rows,
        **facility_breakdown_context,
        'medical_latest_refresh_date': latest_refresh_date,
        'medical_import_status_label': import_status_label,
        'medical_registration_count': Application.objects.filter(form_code__in=['MD1', 'CHW1', 'MBSP']).count(),
        'medical_renewal_count': Application.objects.filter(form_code__in=['MD2', 'MBRN']).count(),
        'latest_medical_import': latest_medical_import,
        'latest_medical_import_sheets': latest_import_sheets,
        'medical_board_forms': [
            {'code': 'MD1', 'title': 'Initial Medical Practitioner Registration', 'url': 'medical_board_form_register'},
            {'code': 'MD2', 'title': 'Medical Practitioner Renewal', 'url': 'medical_board_form_register'},
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


def _admin_batch_progress(batch):
    if not batch:
        return 0
    total_steps = batch.total_rows or batch.total_sheets or 0
    completed_steps = batch.processed_rows or batch.processed_sheets or 0
    if batch.status == "completed":
        return 100
    if not total_steps:
        return 0
    return max(0, min(int((completed_steps / total_steps) * 100), 100))


def _admin_latest_batch_for_source_kinds(source_kinds):
    return DataImportBatch.objects.filter(source_kind__in=source_kinds).order_by("-started_at").first()


def _admin_batch_health_row(label, source_kinds):
    batch = _admin_latest_batch_for_source_kinds(source_kinds)
    if not batch:
        return {
            "label": label,
            "status": "No import yet",
            "tone": "warning",
            "progress": 0,
            "source": "-",
            "rows": 0,
            "started": None,
            "completed": None,
        }
    tone = "success" if batch.status == "completed" else "danger" if batch.status == "failed" else "warning"
    return {
        "label": label,
        "status": batch.get_status_display(),
        "tone": tone,
        "progress": _admin_batch_progress(batch),
        "source": batch.source_file_name,
        "rows": batch.processed_rows or batch.total_rows or 0,
        "started": batch.started_at,
        "completed": batch.completed_at,
    }


def _admin_metric_card(label, value, detail, *, tone="neutral", icon="fas fa-circle", href=None, meta=None):
    return {
        "label": label,
        "value": value,
        "detail": detail,
        "tone": tone,
        "icon": icon,
        "href": href,
        "meta": meta or "",
    }


def _admin_priority_item(label, count, detail, *, href, icon, severity="warning"):
    tone = "success" if not count else severity
    status = "Clear" if not count else "Action required"
    return {
        "label": label,
        "count": count,
        "detail": detail,
        "href": href,
        "icon": icon,
        "tone": tone,
        "status": status,
    }


def _system_admin_command_centre_context(user, base_context, quality_context):
    today = timezone.localdate()
    now = timezone.now()
    sla_days = 14
    overdue_cutoff = today - timedelta(days=sla_days)
    expiry_cutoff = today + timedelta(days=60)

    pending_applications_qs = Application.objects.filter(status="pending")
    overdue_application_count = pending_applications_qs.filter(submitted_date__lte=overdue_cutoff).count()
    duplicate_review_count = DuplicateReviewQueue.objects.filter(status="pending").count()
    failed_import_count = DataImportBatch.objects.filter(status="failed").count()
    running_import_count = DataImportBatch.objects.filter(status__in=["pending", "running"]).count()
    import_attention_count = failed_import_count + running_import_count
    receipt_mismatch_count = Receipt.objects.filter(
        Q(status__in=["pending", "failed"])
        | Q(payer_match_confidence__in=["unlinked", "ambiguous"])
    ).count()
    practitioner_roles = ["nurse", "nurse_aide", "doctor", "chw", "graduand", "student"]
    unlinked_practitioner_count = User.objects.filter(role__in=practitioner_roles).exclude(
        professional_record_status="linked"
    ).count()
    pending_access_count = User.objects.filter(
        role__in=["admin", "registrar", "reviewer", "mobile_collector"],
    ).filter(
        Q(role_approved=False) | Q(system_admin_approved=False)
    ).count()
    recent_security_event_count = SecurityAuditEvent.objects.filter(
        action__in=["LOGIN_FAILED", "MFA_FAILED", "ACCESS_DENIED"],
        created_at__gte=now - timedelta(hours=24),
    ).count()
    recent_security_events = SecurityAuditEvent.objects.filter(
        action__in=["LOGIN_FAILED", "MFA_FAILED", "ACCESS_DENIED"],
    ).order_by("-created_at")[:6]

    licence_expiry_count = (
        NursingProfessional.objects.filter(
            license_expiry_date__isnull=False,
            license_expiry_date__lte=expiry_cutoff,
        ).count()
        + Midwife.objects.filter(
            license_expiry_date__isnull=False,
            license_expiry_date__lte=expiry_cutoff,
        ).count()
        + MedicalDoctor.objects.filter(
            license_expiry_date__isnull=False,
            license_expiry_date__lte=expiry_cutoff,
        ).count()
    )

    nursing_review_count = _data_quality_review_queryset_for_user(user, "nursing").count()
    medical_review_count = _data_quality_review_queryset_for_user(user, "medical").count()
    nursing_pending_count = Application.objects.filter(form_code__in=NURSING_FORM_CODES, status="pending").count()
    medical_pending_count = Application.objects.filter(form_code__in=MEDICAL_BOARD_FORM_CODES, status="pending").count()
    nursing_register_count = (
        base_context.get("nursing_count", 0)
        + base_context.get("midwife_count", 0)
        + base_context.get("nurse_aide_count", 0)
    )
    medical_register_count = (
        base_context.get("medical_count", 0)
        + base_context.get("chw_count", 0)
        + base_context.get("allied_count", 0)
    )
    latest_snapshot = base_context.get("latest_snapshot")
    latest_import_batch = DataImportBatch.objects.order_by("-started_at").first()
    latest_import_progress = _admin_batch_progress(latest_import_batch)
    linked_user_count = User.objects.filter(professional_record_status="linked").count()
    total_practitioner_accounts = User.objects.filter(role__in=practitioner_roles).count()

    system_checks = [
        bool(latest_import_batch and latest_import_batch.status == "completed"),
        bool(latest_snapshot),
        not quality_context.get("data_quality_high_count", 0),
        not receipt_mismatch_count,
        not duplicate_review_count,
        not recent_security_event_count,
        not import_attention_count,
        pending_access_count == 0,
    ]
    system_readiness_percent = round((sum(1 for item in system_checks if item) / len(system_checks)) * 100)
    readiness_tone = "success" if system_readiness_percent >= 80 else "warning" if system_readiness_percent >= 55 else "danger"
    if failed_import_count or recent_security_event_count or quality_context.get("data_quality_high_count", 0):
        system_status = {
            "label": "Attention Required",
            "tone": "danger",
            "detail": "Critical data, import, or access-control items need review.",
        }
    elif running_import_count or overdue_application_count or receipt_mismatch_count:
        system_status = {
            "label": "Operational Watch",
            "tone": "warning",
            "detail": "The platform is online with open operational work.",
        }
    else:
        system_status = {
            "label": "Operational",
            "tone": "success",
            "detail": "Core registry services are online.",
        }

    priority_items = [
        _admin_priority_item(
            "Critical data quality reviews",
            quality_context.get("data_quality_high_count", 0),
            "High-severity missing or inconsistent registry data.",
            href=reverse("review_centre"),
            icon="fas fa-triangle-exclamation",
            severity="danger",
        ),
        _admin_priority_item(
            "Failed or running import jobs",
            import_attention_count,
            "Workbook imports that failed or have not completed.",
            href=reverse("admin_dashboard"),
            icon="fas fa-database",
            severity="danger" if failed_import_count else "warning",
        ),
        _admin_priority_item(
            f"Pending applications over {sla_days} days",
            overdue_application_count,
            "Applications waiting beyond the operational service threshold.",
            href=reverse("workforce_flow"),
            icon="fas fa-clock",
            severity="warning",
        ),
        _admin_priority_item(
            "Receipt mismatches or failed payments",
            receipt_mismatch_count,
            "Receipts needing payer, application, or payment-status review.",
            href=reverse("records_home"),
            icon="fas fa-receipt",
            severity="warning",
        ),
        _admin_priority_item(
            "Pending duplicate reviews",
            duplicate_review_count,
            "Potential duplicate records awaiting merge or review decisions.",
            href=reverse("duplicate_review_workflow"),
            icon="fas fa-code-branch",
            severity="warning",
        ),
        _admin_priority_item(
            "Unlinked practitioner accounts",
            unlinked_practitioner_count,
            "Normal users whose account has not been linked to a verified register record.",
            href=reverse("records_home"),
            icon="fas fa-link",
            severity="warning",
        ),
        _admin_priority_item(
            "Licence expiry reviews",
            licence_expiry_count,
            "Nursing, midwifery, and medical doctor licences expired or due within 60 days.",
            href=reverse("workforce_flow"),
            icon="fas fa-calendar-check",
            severity="warning",
        ),
        _admin_priority_item(
            "Access-control security events",
            recent_security_event_count,
            "Login failures, MFA failures, or access denials in the last 24 hours.",
            href=reverse("admin_dashboard"),
            icon="fas fa-shield-halved",
            severity="danger",
        ),
    ]
    priority_items.sort(key=lambda item: (0 if item["count"] else 1, {"danger": 0, "warning": 1, "success": 2}.get(item["tone"], 3), item["label"]))

    reference_breakdown = base_context.get("reference_breakdown", {})
    metric_groups = [
        {
            "title": "Registry Integrity",
            "description": "Source data, legal register linkage, duplicate risk, and unresolved data quality.",
            "cards": [
                _admin_metric_card(
                    "Imported Source Rows",
                    base_context.get("import_record_count", 0),
                    "Latest approved workbook rows available for reporting.",
                    tone="info",
                    icon="fas fa-database",
                    href=reverse("workforce_flow"),
                    meta=f"{latest_import_progress}% latest import progress",
                ),
                _admin_metric_card(
                    "Linked Professional Accounts",
                    linked_user_count,
                    f"{total_practitioner_accounts} practitioner portal accounts in scope.",
                    tone="success" if unlinked_practitioner_count == 0 else "warning",
                    icon="fas fa-link",
                    href=reverse("records_home"),
                ),
                _admin_metric_card(
                    "Pending Duplicate Reviews",
                    duplicate_review_count,
                    "Identity, registration, and import duplicate decisions.",
                    tone="success" if duplicate_review_count == 0 else "warning",
                    icon="fas fa-code-branch",
                    href=reverse("duplicate_review_workflow"),
                ),
                _admin_metric_card(
                    "Open Data Quality Reviews",
                    quality_context.get("missing_data_review_count", 0),
                    f"{quality_context.get('data_quality_high_count', 0)} high priority.",
                    tone="success" if quality_context.get("missing_data_review_count", 0) == 0 else "danger",
                    icon="fas fa-triangle-exclamation",
                    href=reverse("review_centre"),
                ),
            ],
        },
        {
            "title": "Licensing Workflow",
            "description": "Applications, approvals, rejections, and renewal readiness across boards.",
            "cards": [
                _admin_metric_card(
                    "Pending Applications",
                    base_context.get("pending_applications", 0),
                    f"{overdue_application_count} beyond {sla_days} days.",
                    tone="warning" if overdue_application_count else "info",
                    icon="fas fa-hourglass-half",
                    href=reverse("workforce_flow"),
                ),
                _admin_metric_card(
                    "Approved Applications",
                    base_context.get("approved_applications", 0),
                    "Completed regulator decisions.",
                    tone="success",
                    icon="fas fa-circle-check",
                    href=reverse("workforce_flow"),
                ),
                _admin_metric_card(
                    "Rejected Applications",
                    base_context.get("rejected_applications", 0),
                    "Rejected or returned application outcomes.",
                    tone="neutral",
                    icon="fas fa-circle-xmark",
                    href=reverse("workforce_flow"),
                ),
                _admin_metric_card(
                    "Licence Expiry Reviews",
                    licence_expiry_count,
                    "Expiry date review window: 60 days.",
                    tone="success" if licence_expiry_count == 0 else "warning",
                    icon="fas fa-calendar-days",
                    href=reverse("workforce_flow"),
                ),
            ],
        },
        {
            "title": "Payments And Receipts",
            "description": "Receipted payments, failed transactions, and payer-link assurance.",
            "cards": [
                _admin_metric_card(
                    "Receipted Payments",
                    base_context.get("receipt_completed_count", 0),
                    "Completed receipt records.",
                    tone="success",
                    icon="fas fa-receipt",
                    href=reverse("records_home"),
                ),
                _admin_metric_card(
                    "Pending Receipts",
                    base_context.get("receipt_pending_count", 0),
                    "Payments awaiting confirmation.",
                    tone="warning" if base_context.get("receipt_pending_count", 0) else "success",
                    icon="fas fa-money-check",
                    href=reverse("records_home"),
                ),
                _admin_metric_card(
                    "Failed Receipts",
                    base_context.get("receipt_failed_count", 0),
                    "Failed payment records requiring review.",
                    tone="danger" if base_context.get("receipt_failed_count", 0) else "success",
                    icon="fas fa-ban",
                    href=reverse("records_home"),
                ),
                _admin_metric_card(
                    "Unmatched Receipts",
                    receipt_mismatch_count,
                    "Unlinked or ambiguous payer matches.",
                    tone="danger" if receipt_mismatch_count else "success",
                    icon="fas fa-user-magnifying-glass",
                    href=reverse("records_home"),
                ),
            ],
        },
        {
            "title": "Workforce Intelligence",
            "description": "Snapshot readiness, facilities, training institutions, and board coverage.",
            "cards": [
                _admin_metric_card(
                    "Latest Snapshot Year",
                    latest_snapshot.year if latest_snapshot else "-",
                    "System-wide workforce reporting snapshot.",
                    tone="success" if latest_snapshot else "warning",
                    icon="fas fa-chart-line",
                    href=reverse("workforce_flow"),
                ),
                _admin_metric_card(
                    "Recognised PNG Nursing Schools",
                    reference_breakdown.get("png_nursing_school_count", base_context.get("institution_count", 0)),
                    "Canonical Nursing Council school references.",
                    tone="info",
                    icon="fas fa-school",
                    href=reverse("records_home"),
                ),
                _admin_metric_card(
                    "Verified Facility Records",
                    base_context.get("verified_facility_count", base_context.get("facility_count", 0)),
                    "Facility master records used for workforce mapping.",
                    tone="info",
                    icon="fas fa-hospital",
                    href=reverse("workforce_map"),
                ),
                _admin_metric_card(
                    "Medical Board Workforce",
                    medical_register_count,
                    "Doctors, CHW, and allied health references in scope.",
                    tone="info",
                    icon="fas fa-stethoscope",
                    href=reverse("medical_board_portal"),
                ),
            ],
        },
        {
            "title": "Access And Security",
            "description": "User accounts, role approval, linked practitioner access, and security events.",
            "cards": [
                _admin_metric_card(
                    "Total Users",
                    base_context.get("total_users", 0),
                    "All platform user accounts.",
                    tone="info",
                    icon="fas fa-users",
                    href=reverse("admin_dashboard"),
                ),
                _admin_metric_card(
                    "Pending Staff Approvals",
                    pending_access_count,
                    "Staff role or operations access waiting for approval.",
                    tone="success" if pending_access_count == 0 else "warning",
                    icon="fas fa-user-shield",
                    href=reverse("admin_dashboard"),
                ),
                _admin_metric_card(
                    "Unlinked Practitioner Accounts",
                    unlinked_practitioner_count,
                    "User accounts not yet connected to verified records.",
                    tone="success" if unlinked_practitioner_count == 0 else "warning",
                    icon="fas fa-user-lock",
                    href=reverse("records_home"),
                ),
                _admin_metric_card(
                    "Security Events 24h",
                    recent_security_event_count,
                    "Failed login, MFA failure, and access denied events.",
                    tone="danger" if recent_security_event_count else "success",
                    icon="fas fa-shield-halved",
                    href=reverse("admin_dashboard"),
                ),
            ],
        },
    ]

    board_status_rows = [
        {
            "board": "PNG Nursing Council",
            "scope": "Nursing, midwifery, nurse aide, graduand, ATP and licence pathways",
            "register_count": nursing_register_count,
            "pending_count": nursing_pending_count,
            "data_quality_count": nursing_review_count,
            "public_register_url": reverse("public_nursing_register_search_root"),
            "portal_url": reverse("nursing_council_portal"),
            "tone": "danger" if nursing_review_count else "success",
        },
        {
            "board": "Medical Board",
            "scope": "Medical doctors, specialists, CHW, allied health and medical facility pathways",
            "register_count": medical_register_count,
            "pending_count": medical_pending_count,
            "data_quality_count": medical_review_count,
            "public_register_url": reverse("public_medical_board_register_search_root"),
            "portal_url": reverse("medical_board_portal"),
            "tone": "danger" if medical_review_count else "success",
        },
    ]

    import_health_rows = [
        _admin_batch_health_row("Nursing Council imports", NURSING_IMPORT_SOURCE_KINDS),
        _admin_batch_health_row("Medical Board imports", MEDICAL_IMPORT_SOURCE_KINDS),
        _admin_batch_health_row("All import batches", NURSING_IMPORT_SOURCE_KINDS + MEDICAL_IMPORT_SOURCE_KINDS),
    ]

    command_rows = [
        {
            "label": "Select ATP Workbook",
            "command": "",
            "href": reverse("nursing_council_portal") + "?import=atp#nursing-public-protection",
            "action_label": "Select",
            "area": "Nursing Council",
            "detail": "Choose the ATP workbook and optional worksheet tab before import.",
            "icon": "fas fa-file-import",
            "tone": "primary",
            "last_run": import_health_rows[0]["completed"] or import_health_rows[0]["started"],
            "confirmation": "",
            "background": True,
        },
        {
            "label": "Select Full-Licence Workbook",
            "command": "",
            "href": reverse("nursing_council_portal") + "?import=full_licence#nursing-public-protection",
            "action_label": "Select",
            "area": "Nursing Council",
            "detail": "Choose the full-licence workbook and optional worksheet tab before import.",
            "icon": "fas fa-certificate",
            "tone": "primary",
            "last_run": import_health_rows[0]["completed"] or import_health_rows[0]["started"],
            "confirmation": "",
            "background": True,
        },
        {
            "label": "Select Provisional Workbook",
            "command": "",
            "href": reverse("nursing_council_portal") + "?import=provisional#nursing-public-protection",
            "action_label": "Select",
            "area": "Nursing Council",
            "detail": "Choose the provisional/graduand workbook and optional worksheet tab before import.",
            "icon": "fas fa-file-import",
            "tone": "primary",
            "last_run": import_health_rows[0]["completed"] or import_health_rows[0]["started"],
            "confirmation": "",
            "background": True,
        },
        {
            "label": "Import N-DATA Workbook",
            "command": "import_ndata_workbook",
            "area": "Nursing Council",
            "detail": "Refresh historical nursing source rows used by analytics.",
            "icon": "fas fa-database",
            "tone": "dark",
            "last_run": import_health_rows[0]["completed"] or import_health_rows[0]["started"],
            "confirmation": "Run the N-DATA workbook import now?",
        },
        {
            "label": "Import Medical Board Workbook",
            "command": "import_medical_board_workbook",
            "area": "Medical Board",
            "detail": "Refresh doctors, specialists, CHW and medical board references.",
            "icon": "fas fa-stethoscope",
            "tone": "info",
            "last_run": import_health_rows[1]["completed"] or import_health_rows[1]["started"],
            "confirmation": "Run the Medical Board workbook import now?",
        },
        {
            "label": "Bootstrap Reference Data",
            "command": "bootstrap_reference_data",
            "area": "Shared registry",
            "detail": "Refresh baseline cadres, document types, locations, facilities and institutions.",
            "icon": "fas fa-sitemap",
            "tone": "success",
            "last_run": None,
            "confirmation": "Refresh shared reference data now?",
        },
        {
            "label": "Generate Snapshot",
            "command": "generate_snapshot",
            "area": "Workforce intelligence",
            "detail": "Generate a year-based workforce summary for charts and reports.",
            "icon": "fas fa-chart-line",
            "tone": "success",
            "last_run": latest_snapshot.created_at if latest_snapshot else None,
            "confirmation": "Generate the workforce snapshot now?",
        },
        {
            "label": "Audit Missing Data",
            "command": "audit_missing_data",
            "area": "Data quality",
            "detail": "Create or update missing-data reviews and profile alerts from the latest batch.",
            "icon": "fas fa-triangle-exclamation",
            "tone": "warning",
            "last_run": quality_context.get("data_quality_recent_review_date"),
            "confirmation": "Run the missing-data audit now?",
            "background": True,
        },
    ]

    standards_rows = [
        {
            "label": "NHWA indicator readiness",
            "value": f"{system_readiness_percent}%",
            "detail": "Completeness of import, snapshot, quality, and access controls.",
            "tone": readiness_tone,
        },
        {
            "label": "ISCO workforce category coverage",
            "value": base_context.get("registration_count", 0),
            "detail": "Professionals currently represented in operational registers.",
            "tone": "info",
        },
        {
            "label": "FHIR PractitionerRole readiness",
            "value": base_context.get("posting_count", 0),
            "detail": "Current postings available for practitioner-role mapping.",
            "tone": "info",
        },
        {
            "label": "Public register assurance",
            "value": "Online",
            "detail": "Nursing and Medical Board public verification routes are exposed.",
            "tone": "success",
        },
    ]

    return {
        "admin_system_status": system_status,
        "admin_system_readiness": {
            "percent": system_readiness_percent,
            "tone": readiness_tone,
            "checks_complete": sum(1 for item in system_checks if item),
            "checks_total": len(system_checks),
        },
        "admin_sla_days": sla_days,
        "admin_latest_import_batch": latest_import_batch,
        "admin_latest_import_progress": latest_import_progress,
        "admin_priority_items": priority_items,
        "admin_metric_groups": metric_groups,
        "admin_board_status_rows": board_status_rows,
        "admin_import_health_rows": import_health_rows,
        "admin_command_rows": command_rows,
        "admin_standards_rows": standards_rows,
        "admin_recent_security_events": recent_security_events,
        "admin_pending_access_count": pending_access_count,
        "admin_receipt_mismatch_count": receipt_mismatch_count,
        "admin_overdue_application_count": overdue_application_count,
        "admin_unlinked_practitioner_count": unlinked_practitioner_count,
        "admin_duplicate_review_count": duplicate_review_count,
        "admin_import_attention_count": import_attention_count,
    }


@login_required
@user_passes_test(_role_in('admin', 'registrar'))
def admin_dashboard(request):
    missing_queryset = MissingDataReview.objects.exclude(status='resolved')
    quality_context = _data_quality_review_context(missing_queryset, limit=15, scope_key="admin")
    context = {
        'total_users': User.objects.count(),
        'pending_applications': Application.objects.filter(status='pending').count(),
        'recent_notifications': [],
    }
    context.update(quality_context)
    context.update(_current_workforce_context(include_facility_workers=True))
    context.update(_system_admin_command_centre_context(request.user, context, quality_context))
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
        pending_queryset = pending_queryset.filter(form_code__in=MEDICAL_BOARD_FORM_CODES)
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
    registrar_scope = "nursing" if is_nursing_registrar else "medical" if is_medical_registrar else None
    context.update(_current_workforce_context(
        include_facility_workers=True,
        facility_target_models=facility_target_models,
        scope=registrar_scope,
    ))
    context['registrar_scope'] = registrar_scope
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

    severity_filter = request.GET.get("severity", "")
    valid_severities = {value for value, _label in MissingDataReview.SEVERITY_CHOICES}
    if severity_filter in valid_severities:
        queryset = queryset.filter(severity=severity_filter)

    status_filter = request.GET.get("status", "")
    valid_statuses = {value for value, _label in MissingDataReview.STATUS_CHOICES}
    if status_filter in valid_statuses:
        queryset = queryset.filter(status=status_filter)

    source_year_filter = request.GET.get("source_year", "")
    if source_year_filter == "no_year":
        queryset = queryset.filter(quality_record_year__isnull=True)
    elif source_year_filter:
        source_year = _safe_int(source_year_filter, None)
        if source_year is not None:
            queryset = queryset.filter(quality_record_year=source_year)

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


def _dashboard_license_record_table_config(table_key):
    config = DASHBOARD_LICENSE_RECORD_TABLE_MAP.get(table_key)
    if not config:
        raise Http404("Licence record table not available")
    return config


def _dashboard_license_record_queryset(user, table_key):
    config = _dashboard_license_record_table_config(table_key)
    return (
        scoped_record_queryset(PracticingLicenseRecord, user, DASHBOARD_LICENSE_MODEL_SLUG)
        .filter(record_type=config["record_type"])
        .select_related("batch", "sheet")
    )


def _dashboard_license_table_context(user):
    scoped_records = scoped_record_queryset(PracticingLicenseRecord, user, DASHBOARD_LICENSE_MODEL_SLUG)
    record_type_counts = {
        row["record_type"]: row["total"]
        for row in scoped_records.values("record_type").annotate(total=Count("id"))
    }
    can_create = _can_create_records(user)
    tables = []
    for config in DASHBOARD_LICENSE_RECORD_TABLES:
        create_query = urlencode({"record_type": config["record_type"]})
        tables.append({
            **config,
            "table_id": f"dashboard-{config['key']}-records-table",
            "ajax_url": reverse("dashboard_license_record_table", args=[config["key"]]),
            "list_url": reverse("record_list", args=[DASHBOARD_LICENSE_MODEL_SLUG]),
            "create_url": f"{reverse('record_create', args=[DASHBOARD_LICENSE_MODEL_SLUG])}?{create_query}",
            "count": record_type_counts.get(config["record_type"], 0),
            "can_create": can_create,
        })
    return tables


def _dashboard_license_search_queryset(queryset, search_value):
    if not search_value:
        return queryset
    search_query = Q()
    for field_name in DASHBOARD_LICENSE_SEARCH_FIELDS:
        search_query |= Q(**{f"{field_name}__icontains": search_value})
    search_number = _safe_int(search_value, None)
    if search_number is not None:
        search_query |= Q(id=search_number) | Q(record_year=search_number) | Q(source_row=search_number)
    return queryset.filter(search_query)


def _dashboard_license_text(value):
    if value is None or value == "":
        return "-"
    return conditional_escape(str(value))


def _dashboard_license_date(value):
    if not value:
        return "-"
    return value.strftime("%d %b %Y")


def _dashboard_license_row(record, can_delete):
    return {
        "full_name": _dashboard_license_text(record.full_name),
        "registration_no": _dashboard_license_text(record.registration_no),
        "practitioner_number": _dashboard_license_text(record.practitioner_number),
        "category": _dashboard_license_text(record.category),
        "target_model": _dashboard_license_text(record.get_target_model_display()),
        "record_year": _dashboard_license_text(record.record_year),
        "issued_date": _dashboard_license_date(record.issued_date),
        "payment_date": _dashboard_license_date(record.payment_date),
        "source_sheet_name": _dashboard_license_text(record.source_sheet_name),
        "source_row": _dashboard_license_text(record.source_row),
        "actions": _record_action_buttons(DASHBOARD_LICENSE_MODEL_SLUG, record, can_delete),
    }


@login_required
@user_passes_test(_role_in('admin', 'registrar'))
def dashboard_license_record_table(request, table_key):
    queryset = _dashboard_license_record_queryset(request.user, table_key)
    records_total = queryset.count()

    search_value = " ".join((request.GET.get("search[value]") or "").split())
    queryset = _dashboard_license_search_queryset(queryset, search_value)
    records_filtered = queryset.count()

    order_column = request.GET.get("order[0][column]", "")
    order_dir = request.GET.get("order[0][dir]", "desc")
    column_name = request.GET.get(f"columns[{order_column}][name]", "") if order_column.isdigit() else ""
    order_field = DASHBOARD_LICENSE_ORDER_FIELDS.get(column_name)
    if order_field:
        order_expression = F(order_field)
        order_expression = order_expression.asc(nulls_last=True) if order_dir == "asc" else order_expression.desc(nulls_last=True)
        queryset = queryset.order_by(order_expression, "-id" if order_dir == "asc" else "id")
    else:
        queryset = queryset.order_by(F("record_year").desc(nulls_last=True), "-updated_at", "-id")

    start = max(_safe_int(request.GET.get("start"), 0), 0)
    length = _safe_int(request.GET.get("length"), 25)
    if length < 0:
        length = 100
    length = min(max(length, 10), 250)

    can_delete = _can_delete_records(request.user, DASHBOARD_LICENSE_MODEL_SLUG, PracticingLicenseRecord)
    page_records = list(queryset[start:start + length])
    return JsonResponse({
        "draw": _safe_int(request.GET.get("draw"), 1),
        "recordsTotal": records_total,
        "recordsFiltered": records_filtered,
        "data": [
            _dashboard_license_row(record, can_delete)
            for record in page_records
        ],
    })


def _nursing_analytics_text(value):
    if value is None or value == "":
        return "-"
    return conditional_escape(str(value))


def _nursing_analytics_date(value):
    if not value:
        return "-"
    return value.strftime("%d %b %Y")


def _nursing_analytics_drilldown_row(fact):
    return {
        "record_id": _nursing_analytics_text(fact.record_id),
        "lifecycle_stage": _nursing_analytics_text(fact.lifecycle_stage),
        "cycle_year": _nursing_analytics_text(fact.cycle_year),
        "age": _nursing_analytics_text(fact.age),
        "full_name": _nursing_analytics_text(fact.full_name),
        "cadre": _nursing_analytics_text(fact.cadre),
        "province": _nursing_analytics_text(fact.province),
        "facility": _nursing_analytics_text(fact.facility),
        "institution": _nursing_analytics_text(fact.institution),
        "registration_no": _nursing_analytics_text(fact.registration_no),
        "practitioner_no": _nursing_analytics_text(fact.practitioner_no),
        "record_quality": _nursing_analytics_text(fact.record_quality),
        "event_date": _nursing_analytics_date(fact.event_date),
    }


@login_required
@user_passes_test(lambda user: is_nursing_council_staff(user))
def nursing_council_analytics_summary(request):
    snapshot = active_nursing_analytics_snapshot()
    return JsonResponse(nursing_analytics_metric_payload(snapshot))


@login_required
@user_passes_test(lambda user: is_nursing_council_staff(user))
def nursing_council_analytics_drilldown(request):
    snapshot = active_nursing_analytics_snapshot()
    if not snapshot:
        return JsonResponse({
            "draw": _safe_int(request.GET.get("draw"), 1),
            "recordsTotal": 0,
            "recordsFiltered": 0,
            "data": [],
        })

    filters = {
        "stage": request.GET.get("stage", ""),
        "year": _safe_int(request.GET.get("year"), None),
        "cadre": request.GET.get("cadre", ""),
        "province": request.GET.get("province", ""),
        "institution": request.GET.get("institution", ""),
        "facility": request.GET.get("facility", ""),
        "quality": request.GET.get("quality", ""),
        "age_min": _safe_int(request.GET.get("age_min"), None),
        "age_max": _safe_int(request.GET.get("age_max"), None),
    }
    records_total = snapshot.lifecycle_facts.count()
    search_value = " ".join((request.GET.get("search[value]") or "").split())
    queryset = filtered_lifecycle_facts(snapshot, filters, search_value=search_value)
    records_filtered = queryset.count()

    order_column = request.GET.get("order[0][column]", "")
    order_dir = request.GET.get("order[0][dir]", "asc")
    column_name = request.GET.get(f"columns[{order_column}][name]", "") if order_column.isdigit() else ""
    order_fields = {
        "record_id": "record_id",
        "lifecycle_stage": "lifecycle_stage",
        "cycle_year": "cycle_year",
        "age": "age",
        "full_name": "full_name",
        "cadre": "cadre",
        "province": "province",
        "facility": "facility",
        "institution": "institution",
        "registration_no": "registration_no",
        "record_quality": "record_quality",
    }
    order_field = order_fields.get(column_name)
    if order_field:
        order_expression = F(order_field)
        order_expression = order_expression.asc(nulls_last=True) if order_dir == "asc" else order_expression.desc(nulls_last=True)
        queryset = queryset.order_by(order_expression, "id" if order_dir == "asc" else "-id")
    else:
        queryset = queryset.order_by(F("cycle_year").desc(nulls_last=True), "lifecycle_order", "record_id")

    start = max(_safe_int(request.GET.get("start"), 0), 0)
    length = _safe_int(request.GET.get("length"), 25)
    if length < 0:
        length = 100
    length = min(max(length, 10), 250)
    page_records = list(queryset[start:start + length])
    return JsonResponse({
        "draw": _safe_int(request.GET.get("draw"), 1),
        "recordsTotal": records_total,
        "recordsFiltered": records_filtered,
        "data": [_nursing_analytics_drilldown_row(record) for record in page_records],
    })


@login_required
@user_passes_test(_role_in('admin', 'registrar', 'reviewer'))
def platform_standards_alignment(request):
    return render(request, "dashboard/platform_standards_alignment.html", build_platform_standards_context())


@login_required
def nhwa_toolkit(request):
    can_view_nhwa = (
        is_system_admin(request.user)
        or is_data_quality_reviewer(request.user)
        or is_finance_reviewer(request.user)
        or is_nursing_council_staff(request.user)
        or is_medical_board_staff(request.user)
    )
    if not can_view_nhwa:
        raise Http404("NHWA toolkit not available")
    return render(request, "dashboard/nhwa_toolkit.html", build_nhwa_toolkit_context())


@login_required
def review_centre(request):
    if not (can_manage_regulatory_operations(request.user) or is_data_quality_reviewer(request.user)):
        raise Http404("Review centre not available")
    context = _review_centre_context(request.user, request.GET.get("scope"))
    return render(request, "dashboard/review_centre.html", context)


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
        context['license_record_tables'] = _dashboard_license_table_context(self.request.user)
        if can_manage_regulatory_operations(self.request.user) or is_data_quality_reviewer(self.request.user):
            context["review_centre"] = _review_centre_context(self.request.user, scope)
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
        scope = _workflow_scope_from_request(self.request.user, self.request)
        context.update(_current_workforce_context(include_facility_workers=True, scope=scope))
        if scope == 'nursing':
            _apply_nursing_overview_scope(context)
        elif scope == 'medical':
            _apply_medical_overview_scope(context)
        else:
            context['dashboard_scope'] = 'global'
        context.update(_workflow_task_context(self.request, scope, context))
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
    mark_report_generated('registered_nurses', scope='nursing', user=request.user, output_label='registered_nurses.pdf')
    return response


@login_required
@user_passes_test(_role_in('admin', 'registrar'))
def export_registered_nurses_excel(request):
    if not can_access_staff_domain(request.user, 'nursing'):
        raise Http404("Report not available")
    response = HttpResponse(
        build_registered_nurses_excel(generated_by=request.user),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = 'attachment; filename="registered_nurses_analytics.xlsx"'
    mark_report_generated('registered_nurses', scope='nursing', user=request.user, output_label='registered_nurses_analytics.xlsx')
    return response


@login_required
@user_passes_test(_role_in('admin', 'registrar'))
def generate_csv_report(request, report_type):
    if report_type == 'registered_nurses':
        if not can_access_staff_domain(request.user, 'nursing'):
            raise Http404("Report not available")
        return export_registered_nurses_excel(request)
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
    mark_report_generated('monthly_analytics', scope=scope, user=request.user, output_label=filename)
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
    mark_report_generated('monthly_analytics', scope=scope, user=request.user, output_label=filename)
    return response


@login_required
@user_passes_test(_role_in('admin', 'registrar'))
def export_monthly_analytics_pdf(request):
    scope = _analytics_scope_for_user(request.user, _analytics_export_scope(request))
    response = HttpResponse(content_type='application/pdf')
    filename = f'ndoh_{scope}_monthly_analytics_report.pdf' if scope else 'ndoh_monthly_analytics_report.pdf'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response.write(build_monthly_analytics_pdf(scope))
    mark_report_generated('monthly_analytics', scope=scope, user=request.user, output_label=filename)
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
    mark_report_generated('yearly_analytics', scope=scope, user=request.user, output_label=filename)
    return response


@login_required
@user_passes_test(_role_in('admin', 'registrar'))
def export_yearly_analytics_pdf(request):
    scope = _analytics_scope_for_user(request.user, _analytics_export_scope(request))
    response = HttpResponse(content_type='application/pdf')
    filename = f'ndoh_{scope}_yearly_analytics_report.pdf' if scope else 'ndoh_yearly_analytics_report.pdf'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response.write(build_yearly_analytics_pdf(scope))
    mark_report_generated('yearly_analytics', scope=scope, user=request.user, output_label=filename)
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
    mark_report_generated(
        'minister_brief',
        scope='all',
        user=request.user,
        output_label='NDOH_Regulatory_Bodies_Online_Workforce_System_Brief_Minister_Updated.docx',
    )
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
    mark_report_generated(
        'registrar_secretary_brief',
        scope='all',
        user=request.user,
        output_label='NDOH_Regulatory_Bodies_Online_Workforce_System_Brief.docx',
    )
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
    mark_report_generated('financial_forecast', scope=scope, user=request.user, output_label=f'financial_forecast_{filename_scope}_report.xlsx')
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
    mark_report_generated('financial_forecast', scope=scope, user=request.user, output_label=f'financial_forecast_{filename_scope}_report.pdf')
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
    mark_report_generated('financial_forecast', scope=scope, user=request.user, output_label=f'financial_forecast_{filename_scope}_report.docx')
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
    question, session_id = _staff_ai_question_payload(request)
    if not request.session.session_key:
        request.session.save()
    return JsonResponse(build_staff_ai_chat_response(
        request.user,
        question,
        session_id=session_id,
        browser_session_key=request.session.session_key or "",
    ))


@login_required
@user_passes_test(_role_in('admin', 'registrar', 'reviewer'))
@require_POST
def staff_ai_feedback(request):
    """Capture staff feedback without making it model-training data."""
    if is_finance_reviewer(request.user):
        return JsonResponse({'error': 'Finance Officer access is limited to operational finance workflows.'}, status=403)
    try:
        payload = json.loads(request.body.decode('utf-8')) if request.content_type == 'application/json' else request.POST
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid feedback payload.'}, status=400)

    session_id = str(payload.get('session_id', '')).strip()[:64]
    try:
        assistant_message_id = int(payload.get('assistant_message_id', 0))
    except (TypeError, ValueError):
        assistant_message_id = 0
    rating = str(payload.get('rating', '')).strip()
    feedback_text = ' '.join(str(payload.get('feedback_text', '')).split())[:1200]
    if rating not in {'helpful', 'needs_review'}:
        return JsonResponse({'error': 'Choose helpful or needs_review.'}, status=400)
    if not session_id:
        return JsonResponse({'error': 'An assistant session is required.'}, status=400)

    conversation = get_object_or_404(
        AssistantConversation.objects.filter(
            session_id=session_id,
            assistant_kind='staff_assistant',
            user=request.user,
        )
    )
    assistant_message = conversation.messages.filter(role='assistant', id=assistant_message_id).first()
    if not assistant_message:
        return JsonResponse({'error': 'The selected assistant answer is unavailable for feedback.'}, status=404)

    feedback, _created = AssistantFeedback.objects.update_or_create(
        assistant_message=assistant_message,
        submitted_by=request.user,
        defaults={
            'rating': rating,
            'feedback_text': feedback_text,
            'redacted_feedback': '',
            'review_status': 'pending',
            'requires_redaction': True,
            'reviewed_by': None,
            'reviewer_notes': '',
        },
    )
    return JsonResponse({
        'ok': True,
        'feedback_id': feedback.id,
        'message': 'Feedback is queued for human privacy review and is not used for model training.',
    })


def _staff_ai_question_payload(request):
    question = request.POST.get('question', '')
    session_id = request.POST.get('session_id', '')
    if not question and request.content_type == 'application/json':
        try:
            payload = json.loads(request.body.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {}
        question = payload.get('question', '')
        session_id = payload.get('session_id', session_id)
    return question, session_id


def _sse_event(event, payload):
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=True, default=str)}\n\n"


@login_required
@user_passes_test(_role_in('admin', 'registrar', 'reviewer'))
@require_POST
def staff_ai_chat_stream(request):
    if is_finance_reviewer(request.user):
        return JsonResponse({'error': 'Finance Officer access is limited to Workforce Flow and Financial Forecast until elevated access is approved.'}, status=403)
    question, session_id = _staff_ai_question_payload(request)
    if not request.session.session_key:
        request.session.save()
    browser_session_key = request.session.session_key or ""

    def event_stream():
        yield _sse_event("status", {"message": "Checking authorised platform context."})
        provider_status = ai_provider_status()
        if provider_status.get("mode") == "redis_worker":
            yield _sse_event("status", {"message": "Queued AI worker is preparing a scoped model response."})
        if staff_ai_question_needs_knowledge_search(question):
            yield _sse_event("status", {"message": "Searching the assistant knowledge sources."})
        else:
            yield _sse_event("status", {"message": "Preparing the scoped assistant answer."})
        response = build_staff_ai_chat_response(
            request.user,
            question,
            session_id=session_id,
            browser_session_key=browser_session_key,
        )
        yield _sse_event("answer", response)
        yield _sse_event("done", {"session_id": response.get("session_id", "")})

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


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
    context.update(_account_record_link_context(request.user))
    context.update(dashboard_review_context(nurse, request.user))
    context.update(_nursing_professional_status_context(nurse, applications, audience="nurse"))
    context.update(build_professional_identity_context(nurse))
    if not nurse:
        context.update(_nursing_unlinked_portal_context(request.user))
    return render(request, 'dashboard/nurse_dashboard.html', context)


@login_required(login_url='board_login')
def nursing_council_board_portal(request):
    if not can_access_nursing_board_portal(request.user):
        return redirect('main_dashboard')
    if request.method == "POST":
        return _handle_nursing_board_portal_post(request)
    return redirect('board_nursing_dashboard')


@login_required
def nursing_council_portal(request):
    if not is_nursing_council_staff(request.user):
        return redirect('registrar_dashboard' if request.user.role == 'registrar' else 'main_dashboard')
    analytics_context = nursing_analytics_dashboard_context()
    if analytics_context["nursing_analytics_has_snapshot"]:
        snapshot = analytics_context["nursing_analytics_snapshot"]
        payload = analytics_context["nursing_analytics_payload"]
        kpis = payload.get("kpis", {})
        charts = payload.get("charts", {})
        year_chart = charts.get("year", {})
        province_chart = charts.get("province", {})
        snapshot_live_context = _nursing_snapshot_live_context(snapshot, payload)
        latest_year = snapshot_live_context.get("atp_current_year") or max(year_chart.get("labels") or [0])
        reference_breakdown = build_reference_breakdown()
        pending_queryset = Application.objects.filter(status='pending', form_code__in=NURSING_FORM_CODES).order_by('-submitted_date')
        context = {
            'can_manage_nursing_operations': can_manage_regulatory_operations(request.user),
            'nursing_count': kpis.get("clean_atp_records", 0),
            'midwife_count': 0,
            'institutions_count': reference_breakdown['png_nursing_school_count'],
            'pending_applications': pending_queryset.count(),
            'recent_applications': pending_queryset[:15],
            'current_provisional_licenses': [],
            'provisional_license_count': kpis.get("clean_provisional_records", 0),
            'provisional_license_display_count': 0,
            'provisional_license_limit': 0,
            'renewals_pending': 0,
            'missing_data_review_count': 0,
            'reference_breakdown': reference_breakdown,
            'registrar_worker_origin_scope_label': 'Nursing Council',
            'registrar_worker_origin_summary': {
                'displayed_rows': 0,
                'national_total': 0,
                'overseas_total': 0,
                'combined_total': 0,
            },
            'registrar_worker_origin_rows': [],
            'registrar_worker_origin_table_limit': 0,
            'nursing_analytics_batch': analytics_context["nursing_analytics_snapshot"].source_batch,
            'nursing_pipeline_totals': [
                {'stage': 'Provisional Licence', 'count': kpis.get("clean_provisional_records", 0)},
                {'stage': 'Full Licence', 'count': kpis.get("clean_full_licence_records", 0)},
                {'stage': 'Authority to Practice', 'count': kpis.get("clean_atp_records", 0)},
            ],
            'nursing_provisional_pipeline_total': kpis.get("clean_provisional_records", 0),
            'nursing_full_registration_total': kpis.get("clean_full_licence_records", 0),
            'nursing_full_approved_total': kpis.get("clean_atp_records", 0),
            'nursing_latest_year': latest_year,
            'nursing_latest_full_count': kpis.get("clean_full_licence_records", 0),
            'nursing_latest_full_approved_count': kpis.get("clean_atp_records", 0),
            'nursing_latest_practicing_count': kpis.get("clean_atp_records", 0),
            'nursing_yearly_rows': [],
            'nursing_full_license_records': [],
            'nursing_flow_year_labels': json.dumps(year_chart.get("labels", [])),
            'nursing_flow_graduand_values': json.dumps(year_chart.get("provisional", [])),
            'nursing_flow_full_values': json.dumps(year_chart.get("full_licence", [])),
            'nursing_flow_full_approved_values': json.dumps(year_chart.get("authority_to_practice", [])),
            'nursing_flow_practicing_values': json.dumps(year_chart.get("authority_to_practice", [])),
            'province_rows': [
                {'province': label, 'total': value}
                for label, value in zip(province_chart.get("labels", []), province_chart.get("values", []))
            ],
            'province_labels': json.dumps(province_chart.get("labels", [])),
            'province_values': json.dumps(province_chart.get("values", [])),
            'atp_batch': analytics_context["nursing_analytics_snapshot"].source_batch,
            'atp_current_year': latest_year,
            'atp_current_person_total': kpis.get("clean_atp_records", 0),
            'atp_current_public_total': 0,
            'atp_current_church_total': 0,
            'atp_current_private_total': 0,
            'atp_year_rows': [],
            'atp_category_rows': [],
            'atp_gender_rows': [],
            'atp_workplace_rows': [],
            'atp_recent_record_rows': [],
            'atp_year_labels': json.dumps(year_chart.get("labels", [])),
            'atp_year_values': json.dumps(year_chart.get("authority_to_practice", [])),
            'atp_gender_labels': json.dumps([]),
            'atp_gender_values': json.dumps([]),
            'atp_ownership_labels': json.dumps([]),
            'atp_ownership_values': json.dumps([]),
            'frequent_current_nurse_total': kpis.get("clean_atp_records", 0),
            'frequent_pha_facility_total': 0,
            'frequent_private_facility_total': 0,
            'frequent_ngo_facility_total': 0,
            'frequent_nursing_category_rows': [],
            'frequent_nursing_category_review_total': 0,
            'frequent_nursing_category_review_rows': [],
            'frequent_facility_ownership_rows': [],
            'nursing_workflow_rows': build_nursing_workflow_rows(),
            'today': date.today(),
        }
        context.update(_nursing_reference_detail_context(reference_breakdown))
        context.update(snapshot_live_context)
        context.update(analytics_context)
        context.update(lapsed_renewal_review_context(
            limit=20,
            age_min=request.GET.get("lapsed_age_min"),
            age_max=request.GET.get("lapsed_age_max"),
        ))
        context.update(_nursing_council_public_protection_context(request.user))
        nursing_intelligence = build_nursing_workforce_intelligence_context(
            filters={
                key: request.GET.get(f'nursing_{key}', '')
                for key in ('province', 'cadre', 'year')
            }
        )
        context['nursing_workforce_intelligence'] = nursing_intelligence
        if bool(getattr(settings, 'REGULATORY_ML_ENABLED', True)):
            context['regulatory_ml_forecast'] = build_workforce_forecast_context(
                nursing_context=nursing_intelligence,
                medical_context={},
                horizon_years=getattr(settings, 'REGULATORY_ML_FORECAST_HORIZON_YEARS', 10),
            )
        context.update({
            'nursing_analytics_summary_url': reverse('nursing_council_analytics_summary'),
            'nursing_analytics_drilldown_url': reverse('nursing_council_analytics_drilldown'),
            'professional_profile_update_queue_url': reverse('professional_profile_update_queue') + '?office=nursing',
        })
        return render(request, 'dashboard/nursing_council_portal.html', context)

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
    context.update(_nursing_reference_detail_context(context["reference_breakdown"]))
    context.update(_nursing_province_distribution_context())
    context.update(_nursing_atp_context())
    context.update(_registrar_worker_origin_context(request.user))
    context.update(analytics_context)
    context.update(lapsed_renewal_review_context(
        limit=20,
        age_min=request.GET.get("lapsed_age_min"),
        age_max=request.GET.get("lapsed_age_max"),
    ))
    context.update(_nursing_council_public_protection_context(request.user))
    nursing_intelligence = build_nursing_workforce_intelligence_context(
        filters={
            key: request.GET.get(f'nursing_{key}', '')
            for key in ('province', 'cadre', 'year')
        }
    )
    context['nursing_workforce_intelligence'] = nursing_intelligence
    if bool(getattr(settings, 'REGULATORY_ML_ENABLED', True)):
        context['regulatory_ml_forecast'] = build_workforce_forecast_context(
            nursing_context=nursing_intelligence,
            medical_context={},
            horizon_years=getattr(settings, 'REGULATORY_ML_FORECAST_HORIZON_YEARS', 10),
        )
    context.update({
        'nursing_analytics_summary_url': reverse('nursing_council_analytics_summary'),
        'nursing_analytics_drilldown_url': reverse('nursing_council_analytics_drilldown'),
        'professional_profile_update_queue_url': reverse('professional_profile_update_queue') + '?office=nursing',
    })
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
    context.update(_account_record_link_context(request.user))
    context.update(dashboard_review_context(chw, request.user))
    context.update(_medical_professional_status_context(chw, applications, audience="chw"))
    if not chw:
        context.update(_medical_unlinked_portal_context(request.user))
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
    context.update(_account_record_link_context(request.user))
    context.update(dashboard_review_context(nurse_aide, request.user))
    context.update(_nursing_professional_status_context(nurse_aide, applications, audience="nurse_aide"))
    if not nurse_aide:
        context.update(_nursing_unlinked_portal_context(request.user))
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
    context.update(_account_record_link_context(request.user))
    context.update(dashboard_review_context(doctor, request.user))
    context.update(_medical_professional_status_context(doctor, applications, audience="doctor"))
    context.update(build_professional_identity_context(doctor))
    if not doctor:
        context.update(_medical_unlinked_portal_context(request.user))
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
    context.update(_account_record_link_context(request.user))
    context.update(dashboard_review_context(student, request.user))
    context.update(_nursing_professional_status_context(student, applications, audience="graduand"))
    if not student:
        context.update(_nursing_unlinked_portal_context(request.user))
    return render(request, 'dashboard/student_dashboard.html', context)


@login_required
def medical_board_portal(request):
    if not is_medical_board_staff(request.user):
        return redirect('registrar_dashboard' if request.user.role == 'registrar' else 'main_dashboard')
    context = _current_workforce_context(
        include_facility_workers=True,
        facility_target_models=['medicaldoctor', 'communityhealthworker'],
        scope='medical',
    )
    context.update(_medical_board_context(request.user))
    context.update(_registrar_worker_origin_context(request.user))
    medical_intelligence_context = build_medical_board_intelligence_context({
        key: request.GET.get(f'medical_{key}', '')
        for key in ('specialty', 'province', 'district', 'facility', 'sector', 'gender')
    })
    context.update(medical_intelligence_context)
    if bool(getattr(settings, 'REGULATORY_ML_ENABLED', True)):
        context['regulatory_ml_forecast'] = build_workforce_forecast_context(
            nursing_context={},
            medical_context=medical_intelligence_context,
            horizon_years=getattr(settings, 'REGULATORY_ML_FORECAST_HORIZON_YEARS', 10),
        )
    context['can_manage_medical_operations'] = can_manage_regulatory_operations(request.user)
    context['professional_profile_update_queue_url'] = reverse('professional_profile_update_queue') + '?office=medical'
    return render(request, 'dashboard/medical_board_portal.html', context)


@login_required
@user_passes_test(is_medical_board_staff)
def medical_staff_portal(request):
    doctors = MedicalDoctor.objects.order_by("last_name", "first_name")
    chws = CommunityHealthWorker.objects.order_by("last_name", "first_name")
    medical_applications = Application.objects.filter(form_code__in=MEDICAL_BOARD_FORM_CODES)
    medical_documents = Document.objects.filter(office_scope="medical")
    medical_records = _quality_approved_practicing_records().filter(
        batch__source_kind__in=MEDICAL_IMPORT_SOURCE_KINDS,
        target_model__in=["medicaldoctor", "communityhealthworker", "other"],
    )
    active_practicing_identities = {
        _record_identity(record)
        for record in medical_records.filter(record_type="practicing_license")
        if _record_identity(record)
    }
    staff_rows = []
    for doctor in doctors[:30]:
        staff_rows.append({
            "name": str(doctor),
            "registration": doctor.registration_no or doctor.registration_number or "-",
            "category": doctor.specialty or "Medical Doctor",
            "status": _medical_public_licence_status_for_dashboard(doctor),
            "province": doctor.province or "-",
            "url": reverse("record_detail", args=["medicaldoctor", doctor.pk]),
        })
    for chw in chws[:30]:
        staff_rows.append({
            "name": str(chw),
            "registration": chw.registration_no or chw.community_id or "-",
            "category": chw.training_level or "Community Health Worker",
            "status": "Registered" if chw.is_active else "Inactive",
            "province": chw.province or "-",
            "url": reverse("record_detail", args=["communityhealthworker", chw.pk]),
        })

    context = {
        "doctor_count": doctors.count(),
        "chw_count": chws.count(),
        "pending_applications": medical_applications.filter(status="pending").count(),
        "active_staff": len(active_practicing_identities) or doctors.filter(is_active=True).count() + chws.filter(is_active=True).count(),
        "documents_count": medical_documents.count(),
        "recent_applications": medical_applications.order_by("-submitted_date")[:8],
        "staff_rows": staff_rows[:40],
        "medical_board_map_url": reverse("workforce_map") + "?office=medical",
        "medical_register_url": reverse("public_medical_board_register_search_root"),
    }
    return render(request, "dashboard/medical_staff_portal.html", context)


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
        receipt_scope = 'medical' if request.user.role in MEDICAL_RECEIPT_ROLES else 'nursing'
        mark_report_data_changed(
            scope=receipt_scope,
            reason='Receipt submitted',
            source_label=f"Receipt {receipt.receipt_number}",
        )
        return redirect(redirect_name)

    context = {
        'receipts': _receipt_queryset_for_user(request.user),
        'receipt_form': form,
        'registration_guidelines': _guidelines_for_audience(request.user.role if request.user.role in {'nurse', 'doctor', 'graduand', 'student', 'chw', 'nurse_aide'} else 'general'),
        'registration_guideline_audience': request.user.role if request.user.role in {'nurse', 'doctor', 'graduand', 'student', 'chw', 'nurse_aide'} else 'general',
    }
    context.update(_account_record_link_context(request.user))
    context.update(dashboard_review_context(professional, request.user))
    if request.user.role == 'doctor':
        context.update({
            'doctor': professional,
            'applications': applications,
            'license_expiry': professional.license_expiry_date if professional else None,
        })
        context.update(_medical_professional_status_context(professional, applications, audience="doctor"))
        if not professional:
            context.update(_medical_unlinked_portal_context(request.user))
        return render(request, 'dashboard/doctor_dashboard.html', context)
    if request.user.role in {'graduand', 'student'}:
        context.update({
            'student': professional,
            'applications': applications,
            'expected_graduation': professional.expected_graduation_date if professional else None,
            'graduand_pathway_forms': ['G1', 'G2', 'G3', 'G4', 'NC1', 'NC6', 'NC2', 'NC3'],
        })
        context.update(_nursing_professional_status_context(professional, applications, audience="graduand"))
        if not professional:
            context.update(_nursing_unlinked_portal_context(request.user))
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
        context.update(_nursing_professional_status_context(professional, applications, audience="nurse"))
        if not professional:
            context.update(_nursing_unlinked_portal_context(request.user))
        return render(request, 'dashboard/nurse_dashboard.html', context)
    if request.user.role == 'chw':
        context.update({'chw': professional, 'applications': applications})
        context.update(_medical_professional_status_context(professional, applications, audience="chw"))
        if not professional:
            context.update(_medical_unlinked_portal_context(request.user))
        return render(request, 'dashboard/chw_dashboard.html', context)
    if request.user.role == 'nurse_aide':
        context.update({'nurse_aide': professional, 'applications': applications})
        context.update(_nursing_professional_status_context(professional, applications, audience="nurse_aide"))
        if not professional:
            context.update(_nursing_unlinked_portal_context(request.user))
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
    elif role == 'board_member':
        return redirect('board_nursing_dashboard')

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


def _selected_nursing_import_sheet_names(request, *, multiple=False):
    values = request.POST.getlist("sheet_name") + request.POST.getlist("atp_sheet_name")
    selected = []
    seen = set()
    for value in values:
        sheet_name = re.sub(r"\s+", " ", str(value or "").strip())
        if not sheet_name:
            continue
        key = sheet_name.lower()
        if key in seen:
            continue
        selected.append(sheet_name)
        seen.add(key)
        if not multiple:
            break
    return selected


def _save_nursing_import_workbook_upload(uploaded_file, import_config):
    label = import_config["label"]
    original_filename = Path(getattr(uploaded_file, "name", "") or "").name
    extension = Path(original_filename).suffix.lower()
    if extension not in NURSING_WORKBOOK_UPLOAD_EXTENSIONS:
        allowed = ", ".join(sorted(NURSING_WORKBOOK_UPLOAD_EXTENSIONS))
        raise ValueError(f"Please select an Excel {label} workbook ({allowed}).")

    file_size = getattr(uploaded_file, "size", 0) or 0
    if file_size > NURSING_WORKBOOK_UPLOAD_MAX_BYTES:
        raise ValueError(f"The selected {label} workbook is too large. Maximum upload size is 100 MB.")

    safe_original = get_valid_filename(original_filename) or f"{import_config['storage_folder']}-workbook{extension}"
    safe_stem = slugify(Path(safe_original).stem) or f"selected-{import_config['storage_folder']}-workbook"
    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{safe_stem[:80]}{extension}"
    storage = FileSystemStorage(
        location=str(Path(settings.MEDIA_ROOT) / "imports" / "nursing" / import_config["storage_folder"])
    )
    saved_name = storage.save(filename, uploaded_file)
    return Path(storage.path(saved_name)), original_filename


def _selected_nursing_workbook_upload_response(request, import_key):
    import_config = NURSING_SELECTED_WORKBOOK_IMPORTS[import_key]
    label = import_config["label"]

    if not can_manage_regulatory_operations(request.user):
        return JsonResponse({'error': 'This import is restricted to approved Registrar and System Admin staff.'}, status=403)
    if request.user.role != 'admin' and not is_nursing_council_staff(request.user):
        return JsonResponse({'error': f'{label} workbook import is only available for Nursing Council operations.'}, status=403)

    uploaded_file = request.FILES.get("workbook") or request.FILES.get(import_config.get("field_name", "workbook"))
    if not uploaded_file:
        return JsonResponse({'error': f'Select the {label} workbook to import.'}, status=400)

    selected_sheets = _selected_nursing_import_sheet_names(
        request,
        multiple=import_config.get("multiple_sheets", False),
    )
    try:
        saved_path, original_filename = _save_nursing_import_workbook_upload(uploaded_file, import_config)
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)

    command = [sys.executable, 'manage.py', import_config["command"], '--file', str(saved_path)]
    for sheet_name in selected_sheets:
        command.extend(['--sheet', sheet_name])

    try:
        log_dir = Path(settings.BASE_DIR) / 'docs' / 'command_logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
        log_path = log_dir / f'{import_config["log_prefix"]}_{timestamp}.log'
        with log_path.open('w', encoding='utf-8') as handle:
            handle.write(f"Uploaded by: {request.user.get_username()}\n")
            handle.write(f"Import type: {label}\n")
            handle.write(f"Original file: {original_filename}\n")
            handle.write(f"Saved file: {saved_path}\n")
            handle.write(
                f"Selected sheets: {', '.join(selected_sheets) if selected_sheets else import_config['all_sheets_label']}\n\n"
            )
            handle.flush()
            process = subprocess.Popen(
                command,
                cwd=settings.BASE_DIR,
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
    except Exception as exc:
        return JsonResponse({'error': str(exc)}, status=500)

    sheet_label = ', '.join(selected_sheets) if selected_sheets else import_config['all_sheets_label'].lower()
    return JsonResponse({
        'message': f'{label} import started from "{original_filename}" ({sheet_label}).',
        'output': f'Background {label} import started. Log file: {log_path.name}',
        'returncode': 0,
        'background': True,
        'pid': process.pid,
        'log_file': log_path.name,
        'source_file': original_filename,
        'saved_file': saved_path.name,
        'selected_sheets': selected_sheets,
    })


@login_required
@require_POST
def upload_atp_workbook_import(request):
    return _selected_nursing_workbook_upload_response(request, "atp")


@login_required
@require_POST
def upload_full_licence_workbook_import(request):
    return _selected_nursing_workbook_upload_response(request, "full_licence")


@login_required
@require_POST
def upload_provisional_workbook_import(request):
    return _selected_nursing_workbook_upload_response(request, "provisional")


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
        'import_ndata_workbook': [sys.executable, 'manage.py', 'import_ndata_workbook', '--file', r'd:\2026 Current N-DATA Statistics & Tracking - SECTIONS (Autosaved).xlsx'],
        'import_medical_board_workbook': [sys.executable, 'manage.py', 'import_medical_board_workbook', '--file', str(DEFAULT_MEDICAL_BOARD_WORKBOOK)],
        'import_medical_board_legacy_workbooks': [sys.executable, 'manage.py', 'import_medical_board_legacy_workbooks'],
        'bootstrap_reference_data': [sys.executable, 'manage.py', 'bootstrap_reference_data'],
        'bootstrap_nursing_council_workflows': [sys.executable, 'manage.py', 'bootstrap_nursing_council_workflows'],
        'seed_engagement_platform': [sys.executable, 'manage.py', 'seed_engagement_platform'],
        'import_workforce_files': [sys.executable, 'manage.py', 'import_workforce_files', '--path', 'notebooks/csv_templates'],
        'generate_snapshot': [sys.executable, 'manage.py', 'generate_snapshot'],
        'audit_missing_data': [sys.executable, 'manage.py', 'audit_missing_data', '--audit-import-rows', '--latest-batch'],
    }
    background_commands = {'audit_missing_data'}

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
                'import_ndata_workbook',
                'bootstrap_reference_data',
                'bootstrap_nursing_council_workflows',
                'seed_engagement_platform',
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
def platform_resilience_status(request):
    if not is_staff_dashboard_user(request.user):
        raise Http404("Platform resilience status not available")
    if request.GET.get("refresh") == "1" and is_system_admin(request.user):
        status = refresh_platform_connectivity()
    else:
        status = current_platform_status(use_cache=False)
    return JsonResponse({"platform": status})


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


def _nursing_analytics_search_tokens(query):
    tokens = []
    seen = set()
    for token in re.findall(r"[A-Za-z0-9]+", query or ""):
        normalized = token.strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in ANALYTICS_SEARCH_STOP_WORDS:
            continue
        if normalized.isdigit():
            if len(normalized) < 3:
                continue
        elif len(normalized) < 3:
            continue
        key = normalized.upper()
        if key not in seen:
            seen.add(key)
            tokens.append(normalized)
    return tokens[:24]


def _nursing_analytics_registration_terms(query):
    terms = []
    seen = set()
    for prefix, number in re.findall(r"\b([A-Za-z]{1,5})\s+(\d{2,}(?:\.\d+)?)\b", query or ""):
        term = f"{prefix.upper()} {number}"
        if term not in seen:
            seen.add(term)
            terms.append(term)
    return terms[:10]


def _nursing_analytics_search_text(row):
    parts = [
        row.full_name,
        row.person_group_key,
        row.registration_no,
        row.practitioner_no,
        row.lifecycle_stage,
        row.licence_status,
        row.cadre,
        row.institution,
        row.facility,
        row.province,
        row.source_sheet,
        row.source_lineage,
        str(row.source_row or ""),
        str(row.cycle_year or ""),
    ]
    return " ".join(part for part in parts if part).upper()


def _nursing_analytics_snapshot_search(query, limit=30):
    snapshot = active_nursing_analytics_snapshot()
    if not snapshot:
        return []

    tokens = _nursing_analytics_search_tokens(query)
    registration_terms = _nursing_analytics_registration_terms(query)
    filters = Q()
    direct_fields = [
        "record_id",
        "full_name",
        "registration_no",
        "practitioner_no",
        "person_group_key",
        "institution",
        "facility",
        "province",
        "lifecycle_stage",
        "licence_status",
        "source_sheet",
        "source_lineage",
    ]
    if query:
        for field in direct_fields:
            filters |= Q(**{f"{field}__icontains": query})
    for term in registration_terms:
        filters |= Q(registration_no__icontains=term)
        filters |= Q(practitioner_no__icontains=term)
    for token in tokens:
        for field in direct_fields:
            filters |= Q(**{f"{field}__icontains": token})
        if token.isdigit():
            numeric_value = int(token)
            filters |= Q(source_row=numeric_value)
            filters |= Q(cycle_year=numeric_value)

    if not filters:
        return []

    candidates = list(
        filtered_lifecycle_facts(snapshot, {}, "")
        .filter(filters)
        .order_by("lifecycle_order", "-cycle_year", "full_name")[:500]
    )
    query_upper = (query or "").upper()
    scored_rows = []
    for row in candidates:
        searchable = _nursing_analytics_search_text(row)
        score = 0
        if query_upper and query_upper in searchable:
            score += 50
        for term in registration_terms:
            if term.upper() in searchable:
                score += 20
        for token in tokens:
            token_upper = token.upper()
            if token_upper in searchable:
                score += 4 if token.isdigit() else 6
        if row.registration_no and any(term.upper() == row.registration_no.upper() for term in registration_terms):
            score += 25
        if score:
            scored_rows.append((score, row))

    scored_rows.sort(key=lambda item: (
        -item[0],
        item[1].lifecycle_order or 99,
        -(item[1].cycle_year or 0),
        item[1].full_name,
    ))
    visible_rows = [row for _score, row in scored_rows[:limit]]
    pathway_stats_by_key = _snapshot_pathway_stats_by_key(
        snapshot,
        {row.person_group_key for row in visible_rows if row.person_group_key},
    )
    results = []
    for row in visible_rows:
        if row.source_sheet:
            source = row.source_lineage or f"{row.source_sheet}, row {row.source_row or '-'}"
        else:
            source = row.source_lineage or "-"
        pathway_stats = pathway_stats_by_key.get(row.person_group_key)
        has_linked_pathway = bool(pathway_stats and pathway_stats.get("record_count", 0) > 1)
        results.append({
            "detail_url": _snapshot_pathway_detail_url(row.pk, pathway_stats),
            "name": row.full_name or row.person_group_key or "-",
            "registration": row.registration_no or row.practitioner_no or "-",
            "stage": row.lifecycle_stage or "-",
            "year": _snapshot_pathway_year_label(pathway_stats) if has_linked_pathway else row.cycle_year or "-",
            "cadre": row.cadre or "-",
            "institution": row.institution or "-",
            "facility": row.facility or "-",
            "province": _normalize_province_label(row.province),
            "source": source,
            "quality": row.record_quality or "-",
            "has_linked_pathway": has_linked_pathway,
            "pathway_complete": bool(pathway_stats and pathway_stats.get("is_complete")),
            "pathway_stage_summary": pathway_stats.get("stage_summary") if pathway_stats else "",
            "pathway_record_count": pathway_stats.get("record_count") if pathway_stats else 0,
            "open_label": "Open pathway" if has_linked_pathway else "Open",
        })
    return results


def _nursing_analytics_pathway_queryset(fact):
    queryset = NursingLifecycleFact.objects.filter(snapshot=fact.snapshot)
    if fact.person_group_key:
        queryset = queryset.filter(person_group_key=fact.person_group_key)
    elif fact.registration_link_key:
        queryset = queryset.filter(registration_link_key=fact.registration_link_key)
    elif fact.registration_no:
        queryset = queryset.filter(
            Q(registration_no=fact.registration_no)
            | Q(practitioner_no=fact.registration_no)
            | Q(registration_link_key=fact.registration_no)
        )
    elif fact.practitioner_no:
        queryset = queryset.filter(
            Q(practitioner_no=fact.practitioner_no)
            | Q(registration_no=fact.practitioner_no)
            | Q(registration_link_key=fact.practitioner_no)
        )
    else:
        queryset = queryset.filter(pk=fact.pk)
    return queryset.order_by("lifecycle_order", "cycle_year", "event_date", "record_id")


def _nursing_analytics_pathway_index_for_fact(fact):
    if not fact.person_group_key:
        return None
    return (
        NursingPractitionerIndex.objects
        .filter(snapshot=fact.snapshot, person_group_key=fact.person_group_key)
        .order_by("practitioner_group_id")
        .first()
    )


def _nursing_analytics_fact_source(fact):
    if fact.source_sheet:
        return fact.source_lineage or f"{fact.source_sheet} row {fact.source_row or '-'}"
    return fact.source_lineage or "-"


@user_passes_test(lambda user: is_nursing_council_staff(user))
def nursing_analytics_fact_detail(request, fact_id):
    fact = get_object_or_404(
        NursingLifecycleFact.objects.select_related("snapshot", "snapshot__source_batch"),
        pk=fact_id,
        snapshot__is_active=True,
    )
    summary_fields = [
        ("Lifecycle stage", fact.lifecycle_stage),
        ("Licence status", fact.licence_status),
        ("Cycle year", fact.cycle_year),
        ("Event date", fact.event_date),
        ("Full name", fact.full_name),
        ("Person group key", fact.person_group_key),
        ("Identity confidence", fact.identity_confidence),
        ("Registration number", fact.registration_no),
        ("Practitioner number", fact.practitioner_no),
        ("Cadre", fact.cadre),
        ("Cadre group", fact.cadre_group),
        ("Qualification", fact.formal_qualification),
        ("Institution", fact.institution),
        ("Facility", fact.facility),
        ("Province", _normalize_province_label(fact.province)),
        ("Organization type", fact.organization_type),
        ("Nationality group", fact.nationality_group),
        ("Country", fact.country),
    ]
    source_fields = [
        ("Source workbook", fact.source_workbook or fact.snapshot.source_file_name),
        ("Source sheet", fact.source_sheet),
        ("Source row", fact.source_row),
        ("Source lineage", fact.source_lineage),
        ("Snapshot", fact.snapshot.source_file_name),
        ("Snapshot hash", fact.snapshot.source_file_hash),
        ("Workbook generated on", fact.snapshot.workbook_generated_on),
        ("Activated at", fact.snapshot.activated_at),
        ("Import batch", fact.snapshot.source_batch.source_file_name if fact.snapshot.source_batch else ""),
    ]
    quality_fields = [
        ("Record quality", fact.record_quality),
        ("Completeness score", fact.completeness_score),
        ("Data quality flags", fact.data_quality_flags),
        ("Included in official totals", "Yes" if fact.include_in_official_totals else "No"),
    ]
    raw_payload_rows = []
    if isinstance(fact.raw_payload, dict):
        raw_payload_rows = [
            (key, value)
            for key, value in fact.raw_payload.items()
            if value not in ("", None, [])
        ]

    return render(request, "dashboard/nursing_analytics_fact_detail.html", {
        "fact": fact,
        "summary_fields": summary_fields,
        "source_fields": source_fields,
        "quality_fields": quality_fields,
        "raw_payload_rows": raw_payload_rows,
        "back_url": request.META.get("HTTP_REFERER") or reverse("dashboard_search"),
    })


@user_passes_test(lambda user: is_nursing_council_staff(user))
def nursing_analytics_pathway_detail(request, fact_id):
    selected_fact = get_object_or_404(
        NursingLifecycleFact.objects.select_related("snapshot", "snapshot__source_batch"),
        pk=fact_id,
        snapshot__is_active=True,
    )
    pathway_facts = list(_nursing_analytics_pathway_queryset(selected_fact))
    pathway_index = _nursing_analytics_pathway_index_for_fact(selected_fact)
    pathway_stats = (
        _snapshot_pathway_stats_from_index(pathway_index)
        if pathway_index else _snapshot_pathway_stats_from_facts(pathway_facts, selected_fact.person_group_key)
    )
    fact_rows = []
    for fact in pathway_facts:
        fact_rows.append({
            "detail_url": reverse("nursing_analytics_fact_detail", args=[fact.pk]),
            "record_id": fact.record_id,
            "stage": fact.lifecycle_stage or "-",
            "status": fact.licence_status or "-",
            "year": fact.cycle_year or "-",
            "event_date": fact.event_date,
            "registration": fact.registration_no or fact.practitioner_no or "-",
            "cadre": fact.cadre or "-",
            "institution": fact.institution or "-",
            "facility": fact.facility or "-",
            "province": _normalize_province_label(fact.province),
            "quality": fact.record_quality or "-",
            "source": _nursing_analytics_fact_source(fact),
        })

    summary_fields = [
        ("Representative name", pathway_stats.get("representative_name") or selected_fact.full_name),
        ("Person group key", selected_fact.person_group_key),
        ("Identity confidence", pathway_stats.get("identity_confidence") or selected_fact.identity_confidence),
        ("Linked stages", pathway_stats.get("stage_summary")),
        ("Linked record count", pathway_stats.get("record_count")),
        ("Complete provisional to ATP pathway", "Yes" if pathway_stats.get("is_complete") else "No"),
        ("First year", pathway_stats.get("first_year")),
        ("Latest year", pathway_stats.get("latest_year")),
        ("Latest ATP year", pathway_stats.get("latest_atp_year")),
        ("Registration numbers", pathway_stats.get("registration_nos")),
        ("Practitioner numbers", pathway_stats.get("practitioner_nos")),
        ("Latest cadre", pathway_stats.get("latest_cadre")),
        ("Latest facility", pathway_stats.get("latest_facility")),
        ("Latest province", _normalize_province_label(pathway_stats.get("latest_province"))),
        ("Manual review needed", "Yes" if pathway_stats.get("needs_manual_review") else "No"),
    ]
    source_fields = [
        ("Snapshot", selected_fact.snapshot.source_file_name),
        ("Snapshot hash", selected_fact.snapshot.source_file_hash),
        ("Workbook generated on", selected_fact.snapshot.workbook_generated_on),
        ("Activated at", selected_fact.snapshot.activated_at),
        ("Import batch", selected_fact.snapshot.source_batch.source_file_name if selected_fact.snapshot.source_batch else ""),
    ]
    return render(request, "dashboard/nursing_analytics_pathway_detail.html", {
        "selected_fact": selected_fact,
        "pathway_stats": pathway_stats,
        "pathway_facts": fact_rows,
        "summary_fields": summary_fields,
        "source_fields": source_fields,
        "back_url": request.META.get("HTTP_REFERER") or reverse("dashboard_search"),
    })


def public_faqs(request):
    query = request.GET.get("q", "").strip()
    categories = (
        FAQCategory.objects
        .filter(is_active=True, audience__in=["public", "practitioner"], office_scope__in=["shared", "nursing", "medical"])
        .prefetch_related("entries")
    )
    category_rows = []
    for category in categories:
        entries = category.entries.filter(is_published=True)
        if query:
            entries = entries.filter(
                Q(question__icontains=query)
                | Q(answer__icontains=query)
                | Q(keywords__icontains=query)
            )
        entries = list(entries)
        if entries or not query:
            category_rows.append({
                "category": category,
                "entries": entries,
            })
    return render(request, "dashboard/public_faqs.html", {
        "query": query,
        "category_rows": category_rows,
    })


def nursing_council_public_profile(request):
    return render(request, "dashboard/nursing_council_public_profile.html")


def forum_index(request):
    categories = _visible_forum_categories(request.user)
    category_rows = []
    for category in categories:
        topics = _forum_topic_queryset_for_user(category, request.user)
        category_rows.append({
            "category": category,
            "topic_count": topics.count(),
            "latest_topic": topics.order_by("-last_post_at", "-created_at").first(),
        })
    return render(request, "dashboard/forum_index.html", {
        "category_rows": category_rows,
    })


def forum_category_detail(request, slug):
    category = get_object_or_404(ForumCategory, slug=slug, is_active=True)
    if not _forum_category_visible_for_user(category, request.user):
        return HttpResponse("You do not have access to this forum category.", status=403)

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        body = request.POST.get("body", "").strip()
        public_author_name = request.POST.get("public_author_name", "").strip()
        public_author_email = request.POST.get("public_author_email", "").strip()
        if not title or not body:
            messages.error(request, "A topic title and message are required.")
            return redirect("forum_category_detail", slug=category.slug)
        if not getattr(request.user, "is_authenticated", False) and not category.allow_public_posts:
            return HttpResponse("Public posting is not enabled for this forum category.", status=403)

        status = _forum_post_status_for_user(category, request.user)
        author = request.user if getattr(request.user, "is_authenticated", False) else None
        topic = ForumTopic.objects.create(
            category=category,
            title=title,
            slug=_unique_topic_slug(category, title),
            author=author,
            public_author_name=public_author_name,
            public_author_email=public_author_email,
            status=status,
            last_post_at=timezone.now(),
        )
        post = ForumPost.objects.create(
            topic=topic,
            author=author,
            public_author_name=public_author_name,
            public_author_email=public_author_email,
            body=body,
            status=status,
        )
        ForumModerationLog.objects.create(
            category=category,
            topic=topic,
            post=post,
            action="submitted",
            actor=author,
            note="Topic submitted from forum category page.",
        )
        if status == "approved":
            messages.success(request, "Your forum topic has been published.")
            return redirect("forum_topic_detail", category_slug=category.slug, topic_slug=topic.slug)
        messages.success(request, "Your forum topic has been submitted for moderation.")
        return redirect("forum_category_detail", slug=category.slug)

    topics = _forum_topic_queryset_for_user(category, request.user).order_by("-is_pinned", "-last_post_at", "-created_at")
    return render(request, "dashboard/forum_category.html", {
        "category": category,
        "topics": topics[:100],
        "can_post": getattr(request.user, "is_authenticated", False) or category.allow_public_posts,
    })


def forum_topic_detail(request, category_slug, topic_slug):
    category = get_object_or_404(ForumCategory, slug=category_slug, is_active=True)
    if not _forum_category_visible_for_user(category, request.user):
        return HttpResponse("You do not have access to this forum topic.", status=403)
    topic = get_object_or_404(ForumTopic.objects.select_related("category", "author"), category=category, slug=topic_slug)
    if topic.status != "approved" and not (getattr(request.user, "is_authenticated", False) and is_staff_dashboard_user(request.user)):
        return HttpResponse("This forum topic is awaiting moderation.", status=403)

    if request.method == "POST":
        if topic.is_locked:
            messages.error(request, "This forum topic is locked.")
            return redirect("forum_topic_detail", category_slug=category.slug, topic_slug=topic.slug)
        if not getattr(request.user, "is_authenticated", False) and not category.allow_public_posts:
            return HttpResponse("Public posting is not enabled for this forum category.", status=403)
        body = request.POST.get("body", "").strip()
        public_author_name = request.POST.get("public_author_name", "").strip()
        public_author_email = request.POST.get("public_author_email", "").strip()
        if not body:
            messages.error(request, "A message is required.")
            return redirect("forum_topic_detail", category_slug=category.slug, topic_slug=topic.slug)
        status = _forum_post_status_for_user(category, request.user)
        author = request.user if getattr(request.user, "is_authenticated", False) else None
        post = ForumPost.objects.create(
            topic=topic,
            author=author,
            public_author_name=public_author_name,
            public_author_email=public_author_email,
            body=body,
            status=status,
        )
        if status == "approved":
            topic.last_post_at = timezone.now()
            topic.save(update_fields=["last_post_at", "updated_at"])
        ForumModerationLog.objects.create(
            category=category,
            topic=topic,
            post=post,
            action="submitted",
            actor=author,
            note="Post submitted from forum topic page.",
        )
        if status == "approved":
            messages.success(request, "Your reply has been published.")
        else:
            messages.success(request, "Your reply has been submitted for moderation.")
        return redirect("forum_topic_detail", category_slug=category.slug, topic_slug=topic.slug)

    ForumTopic.objects.filter(pk=topic.pk).update(view_count=F("view_count") + 1)
    posts = _forum_posts_for_user(topic, request.user)
    return render(request, "dashboard/forum_topic.html", {
        "category": category,
        "topic": topic,
        "posts": posts,
        "can_post": not topic.is_locked and (getattr(request.user, "is_authenticated", False) or category.allow_public_posts),
        "can_moderate_forum": getattr(request.user, "is_authenticated", False) and is_staff_dashboard_user(request.user),
    })


@user_passes_test(lambda user: is_staff_dashboard_user(user))
@require_POST
def forum_moderate_post(request, post_id):
    post = get_object_or_404(ForumPost.objects.select_related("topic", "topic__category"), pk=post_id)
    action = request.POST.get("action", "")
    if action not in {"approved", "rejected"}:
        messages.error(request, "That moderation action is not available.")
        return redirect("forum_topic_detail", category_slug=post.topic.category.slug, topic_slug=post.topic.slug)
    old_status = post.status
    post.status = action
    post.moderated_by = request.user
    post.moderated_at = timezone.now()
    post.moderation_note = request.POST.get("note", "").strip()
    post.save(update_fields=["status", "moderated_by", "moderated_at", "moderation_note", "updated_at"])
    topic = post.topic
    if action == "approved" and topic.status == "pending":
        topic.status = "approved"
    topic.last_post_at = timezone.now()
    topic.save(update_fields=["status", "last_post_at", "updated_at"])
    ForumModerationLog.objects.create(
        category=topic.category,
        topic=topic,
        post=post,
        action=action,
        actor=request.user,
        note=f"Post changed from {old_status} to {action}.",
    )
    messages.success(request, f"Forum post marked {action}.")
    return redirect("forum_topic_detail", category_slug=topic.category.slug, topic_slug=topic.slug)


def workforce_map(request):
    queryset = _mapped_entities_queryset(request)
    entities = list(queryset[:600])
    for entity in entities:
        entity.detail_url = _mapped_entity_detail_url(entity)
    entity_payload = [_mapped_entity_payload(entity) for entity in entities]
    selected_province = request.GET.get("province", "")
    search_query = request.GET.get("q", "").strip()
    provinces = list(
        MappedEntity.objects
        .filter(is_active=True)
        .exclude(province="")
        .values_list("province", flat=True)
        .distinct()
        .order_by("province")
    )
    map_entities = [item for item in entity_payload if item["latitude"] is not None and item["longitude"] is not None]
    google_maps_api_key = getattr(settings, "GOOGLE_MAPS_API_KEY", "")
    if search_query:
        google_maps_embed_query = search_query
    elif entities:
        first_entity = entities[0]
        parts = [first_entity.name, first_entity.district, first_entity.province, "Papua New Guinea"]
        google_maps_embed_query = ", ".join(part for part in parts if part)
    elif selected_province:
        google_maps_embed_query = f"{selected_province}, Papua New Guinea"
    else:
        google_maps_embed_query = "Papua New Guinea"
    google_maps_embed_url = ""
    if google_maps_api_key:
        google_maps_embed_url = "https://www.google.com/maps/embed/v1/place?" + urlencode({
            "key": google_maps_api_key,
            "q": google_maps_embed_query,
        })
    return render(request, "dashboard/workforce_map.html", {
        "entities": entities,
        "entities_json": json.dumps(entity_payload),
        "map_entities_json": json.dumps(map_entities),
        "filtered_entity_count": len(entities),
        "map_entity_count": len(map_entities),
        "provinces": provinces,
        "entity_type_choices": MappedEntity.ENTITY_TYPE_CHOICES,
        "selected_office": request.GET.get("office", "all"),
        "selected_type": request.GET.get("type", "all"),
        "selected_province": selected_province,
        "query": search_query,
        "google_maps_api_key": google_maps_api_key,
        "google_maps_configured": bool(google_maps_api_key),
        "google_maps_embed_query": google_maps_embed_query,
        "google_maps_embed_url": google_maps_embed_url,
    })


@login_required
def facility_worker_detail(request, facility_id):
    facility = get_object_or_404(Facility.objects.select_related("location"), pk=facility_id)
    context = _facility_worker_context(request, facility=facility)
    return render(request, "dashboard/facility_worker_detail.html", context)


@login_required
def facilities_directory(request):
    requested_scope = request.GET.get("scope")
    scope = _staff_reference_scope(request.user, requested_scope)
    # Administrators can switch offices from the directory.  A dedicated
    # navigation link always supplies a scope, but Nursing is a safe default
    # when an administrator opens the bare URL.
    if scope not in {"medical", "nursing"}:
        scope = requested_scope if requested_scope in {"medical", "nursing"} else "nursing"
    context = _facility_directory_context(scope)
    context["can_switch_facility_scope"] = getattr(request.user, "role", "") == "admin"
    return render(request, "dashboard/facilities_directory.html", context)


@login_required
def imported_facility_worker_detail(request):
    facility_name = request.GET.get("name", "").strip()
    if not facility_name:
        raise Http404("Facility not available")
    context = _facility_worker_context(request, facility=None)
    return render(request, "dashboard/facility_worker_detail.html", context)


@login_required
def institution_graduand_detail(request, institution_id):
    institution = get_object_or_404(TrainingInstitution, pk=institution_id)
    context = _institution_graduand_context(request, institution)
    return render(request, "dashboard/institution_graduand_detail.html", context)


@login_required
def dashboard_search(request):
    if is_finance_reviewer(request.user):
        messages.warning(request, "Finance Officer access is limited to Workforce Flow and separate Financial Forecast views until elevated access is approved.")
        return redirect("financial_forecast_dashboard")
    if is_nursing_council_board_member(request.user):
        messages.warning(request, "Board member access is limited to the Nursing Council Board governance portal. Registry search and registration helpdesk guidance are outside the board scope.")
        return redirect("board_nursing_dashboard")

    query = " ".join(request.GET.get("q", "").strip().split())
    scope = request.GET.get("scope", "all")
    staff_user = is_staff_dashboard_user(request.user)
    medical_staff = is_medical_board_staff(request.user)
    nursing_staff = is_nursing_council_staff(request.user) and not medical_staff
    staff_scope = _staff_reference_scope(request.user, scope) if staff_user else None
    results = {
        "professionals": [],
        "applications": [],
        "analytics_records": [],
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

            if not medical_staff:
                results["analytics_records"] = _nursing_analytics_snapshot_search(query)

            facilities = Facility.objects.filter(
                Q(name__icontains=query)
                | Q(code__icontains=query)
                | Q(type__icontains=query)
                | Q(location__province__icontains=query)
                | Q(location__district__icontains=query)
            ).select_related("location")[:20]
            matched_facility_names = []
            for facility in facilities:
                matched_facility_names.append(facility.name)
                summary = _facility_worker_summary_for_search(facility=facility, scope=staff_scope)
                results["facilities"].append({
                    "name": facility.name,
                    "code": facility.code or "-",
                    "type": facility.type or "-",
                    "location": str(facility.location or "-"),
                    "detail_url": reverse("facility_worker_detail", args=[facility.pk]),
                    **summary,
                })
            results["facilities"].extend(
                _imported_facility_search_results(
                    query,
                    scope=staff_scope,
                    excluded_names=matched_facility_names,
                    limit=max(0, 20 - len(results["facilities"])),
                )
            )

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
        "show_nursing_analytics_search": staff_user and not medical_staff,
        "results": results,
        "result_count": result_count,
        "helpdesk_answer": helpdesk_answer,
    })
