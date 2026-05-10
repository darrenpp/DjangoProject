from collections import defaultdict
from datetime import date
from datetime import timedelta
import json
from pathlib import Path

import pandas as pd
import sys
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Count, Q, Subquery, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.utils.http import url_has_allowed_host_and_scheme
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
from apps.dashboard.production_readiness import (
    build_production_readiness_context,
    build_production_readiness_review_queryset,
)
from apps.dashboard.staff_ai import build_staff_ai_chat_response, build_staff_ai_context
from apps.notifications.helpdesk import HELPDESK_KNOWLEDGE, get_helpdesk_response
from apps.workforce.services.data_quality import dashboard_review_context
from apps.workforce.services.nursing_council_workflows import build_nursing_workflow_rows
from apps.workforce.models import (
    Application,
    Cadre,
    CommunityHealthWorker,
    DataImportBatch,
    DocumentType,
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
    TrainingInstitution,
    WorkforceSnapshot,
)


ATP_WORKBOOK_PATH = Path(
    r"C:\Users\timhi\OneDrive\Desktop\ParotOs\NDOH_Database\ATP_LATEST\2026 Current ATP-DATA Statistics & Tracking latest.xlsx"
)
ATP_NURSING_TARGET_MODELS = ["nursingprofessional", "midwife", "nurseaide"]
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


def _role_in(*roles):
    return lambda user: user.is_authenticated and user.role in roles


def _staff_portal_target(user):
    if is_medical_board_staff(user):
        return 'medical_board_portal'
    if is_nursing_council_staff(user):
        return 'nursing_council_portal'
    return None


def _analytics_scope_for_user(user):
    if getattr(user, 'role', '') == 'admin':
        return None
    if is_finance_reviewer(user):
        raise Http404("Report not available")
    if is_medical_board_staff(user):
        return 'medical'
    if is_nursing_council_staff(user):
        return 'nursing'
    raise Http404("Report not available")


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
    context['registration_count'] = context.get('medical_count', 0) + context.get('chw_count', 0)
    context['application_count'] = Application.objects.filter(status='pending', form_code__in=medical_form_codes).count()
    context['approved_applications'] = Application.objects.filter(status='approved', form_code__in=medical_form_codes).count()
    context['rejected_applications'] = Application.objects.filter(status='rejected', form_code__in=medical_form_codes).count()
    context['national_workers_table'] = [
        row for row in context.get('national_workers_table', [])
        if row.get('type') in {'Medical', 'CHW'}
    ]
    context['overseas_workers_table'] = [
        row for row in context.get('overseas_workers_table', [])
        if row.get('type') in {'Medical', 'CHW'}
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


def _imported_facility_worker_context(latest_batch=None, target_models=None, limit=100):
    records = PracticingLicenseRecord.objects.exclude(workplace_address__isnull=True).exclude(workplace_address='')
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


def _current_provisional_licenses():
    today = date.today()
    nursing_ct = ContentType.objects.get_for_model(NursingProfessional)
    provisional_apps = (
        Application.objects.filter(form_code='NC1', status='approved', content_type=nursing_ct)
        .select_related('content_type')
        .order_by('expiry_date', '-approved_date')
    )

    rows = []
    for app in provisional_apps:
        professional = app.professional
        if not professional:
            continue

        issued_date = app.approved_date or app.submitted_date
        expiry_date = app.expiry_date
        if not expiry_date and issued_date:
            expiry_date = issued_date + timedelta(days=180)

        rows.append({
            'application': app,
            'professional': professional,
            'full_name': f'{professional.first_name} {professional.last_name}'.strip(),
            'registration_no': getattr(professional, 'registration_no', '') or getattr(professional, 'registration_number', ''),
            'license_no': app.payload.get('license_no') or app.payload.get('provisional_licence_number') or getattr(professional, 'registration_no', ''),
            'year': issued_date.year if issued_date else None,
            'institution': getattr(professional, 'institution', None),
            'qualification': getattr(professional, 'qualification_level', '') or getattr(professional, 'program', '') or '',
            'issued_date': issued_date,
            'expiry_date': expiry_date,
            'days_left': (expiry_date - today).days if expiry_date else None,
            'status': 'Active' if expiry_date and expiry_date >= today else 'Expired' if expiry_date else 'Missing issued date',
            'source': 'NC1 Application',
        })

    imported_provisional = PracticingLicenseRecord.objects.filter(
        record_type='provisional',
        target_model='healthstudent',
    )

    seen = {row['registration_no'] or row['full_name'] for row in rows}
    for record in imported_provisional.order_by('-record_year', '-issued_date', 'full_name')[:250]:
        if not record.record_year and not record.issued_date:
            continue
        if 'listing starts here' in (record.full_name or '').lower():
            continue
        key = record.registration_no or record.full_name
        if key in seen:
            continue
        seen.add(key)
        issued_date = record.issued_date
        expiry_date = issued_date + timedelta(days=180) if issued_date else None
        rows.append({
            'application': None,
            'professional': None,
            'full_name': record.full_name,
            'registration_no': record.registration_no,
            'license_no': record.registration_no,
            'year': record.record_year,
            'institution': record.institution_name,
            'qualification': record.qualification_name,
            'issued_date': issued_date,
            'expiry_date': expiry_date,
            'days_left': (expiry_date - today).days if expiry_date else None,
            'status': 'Active' if expiry_date and expiry_date >= today else 'Expired' if expiry_date else 'Missing issued date',
            'source': record.source_sheet_name,
        })

    return rows


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
    return PracticingLicenseRecord.objects.filter(
        target_model__in=['nursingprofessional', 'midwife', 'nurseaide', 'healthstudent'],
        record_year__isnull=False,
        record_year__lte=current_year,
    ).exclude(batch__source_file_name__icontains='ATP')


def _latest_atp_batch():
    return DataImportBatch.objects.filter(
        source_kind='ndata_workbook',
        status='completed',
        source_file_name__icontains='ATP',
    ).order_by('-started_at').first()


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


def _year_band_label(year_value, current_year):
    if not year_value:
        return 'Past'
    if year_value == current_year:
        return 'Current'
    if year_value >= current_year - 2:
        return 'Recent'
    return 'Past'


def _nursing_province_distribution_context():
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
    return {
        'province_rows': province_rows,
        'province_labels': json.dumps([row['label'] for row in province_rows]),
        'province_values': json.dumps([row['count'] for row in province_rows]),
    }


def _nursing_council_analytics_context():
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

    full_license_records = (
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

    return {
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


def _latest_ndata_batch():
    return DataImportBatch.objects.filter(
        source_kind='ndata_workbook',
        status='completed',
    ).exclude(source_file_name__icontains='ATP').order_by('-started_at').first()


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

    cache_key = f"nursing_atp_context:{batch.id}:{batch.completed_at.isoformat() if batch.completed_at else 'pending'}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    practice_rows = list(
        PracticingLicenseRecord.objects.filter(
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
        current_categories[row['category'] or 'Uncategorised'].add(identity)

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


def _import_batch_context():
    latest_batch = _latest_ndata_batch()
    recent_batches = DataImportBatch.objects.filter(
        source_kind='ndata_workbook'
    ).order_by('-started_at')[:5]
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
        return context

    latest_sheets = list(latest_batch.sheets.order_by('sheet_name')[:20])
    records = list(
        PracticingLicenseRecord.objects.filter(batch=latest_batch).order_by('source_sheet_name', 'source_row')
    )
    context['latest_import_sheets'] = latest_sheets
    context['import_record_count'] = len(records)

    year_sets = {}
    category_counts = {}
    province_counts = {}
    gender_counts = {}
    applicant_type_counts = {}
    workplace_counts = {}
    record_type_counts = {}

    for record in records:
        person_key = record.registration_no or record.practitioner_number or record.full_name
        if record.record_year:
            year_sets.setdefault(record.record_year, set()).add(person_key)
        if record.category:
            category_counts[record.category] = category_counts.get(record.category, 0) + 1
        if record.province:
            province_label = _normalize_province_label(record.province)
            province_counts[province_label] = province_counts.get(province_label, 0) + 1
        if record.gender:
            gender_counts[record.gender] = gender_counts.get(record.gender, 0) + 1
        if record.applicant_type:
            applicant_type_counts[record.applicant_type.title()] = applicant_type_counts.get(record.applicant_type.title(), 0) + 1
        if record.workplace_address:
            workplace_counts[record.workplace_address] = workplace_counts.get(record.workplace_address, 0) + 1
        record_type_counts[record.get_record_type_display()] = record_type_counts.get(record.get_record_type_display(), 0) + 1

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
    return context


def _current_workforce_context(include_facility_workers=False, facility_target_models=None):
    snapshots = WorkforceSnapshot.objects.order_by('year')
    import_context = _import_batch_context()
    reference_breakdown = build_reference_breakdown()
    if include_facility_workers:
        imported_workplace_context = _imported_facility_worker_context(
            import_context.get('latest_import_batch'),
            target_models=facility_target_models,
        )
    else:
        imported_workplace_context = {
            'imported_facility_workers': [],
            'imported_facility_count': 0,
            'imported_facility_worker_count': 0,
        }
    today = date.today()

    def get_age(dob):
        if not dob:
            return None
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

    nurses = list(NursingProfessional.objects.filter(is_active=True))
    nurse_ages = [age for age in (get_age(n.date_of_birth) for n in nurses) if age is not None]
    if not nurse_ages and import_context['latest_import_batch']:
        imported_age_records = PracticingLicenseRecord.objects.filter(
            batch=import_context['latest_import_batch'],
            date_of_birth__isnull=False,
        )
        nurse_ages = [
            today.year - record.date_of_birth.year - ((today.month, today.day) < (record.date_of_birth.month, record.date_of_birth.day))
            for record in imported_age_records
        ]

    graduand_by_institution = []
    for institution in TrainingInstitution.objects.order_by('name'):
        graduands = list(HealthStudent.objects.filter(institution=institution).order_by('last_name', 'first_name'))
        graduand_by_institution.append({
            'institution': institution,
            'students': graduands,
            'graduands': graduands,
            'count': len(graduands),
        })

    professional_rows = []
    for model, label in [
        (NursingProfessional, 'Nursing'),
        (MedicalDoctor, 'Medical'),
        (Midwife, 'Midwife'),
        (CommunityHealthWorker, 'CHW'),
        (NurseAide, 'Nurse Aide'),
        (HealthStudent, 'Graduand'),
    ]:
        for obj in model.objects.order_by('last_name', 'first_name'):
            professional_rows.append({
                'name': f'{obj.first_name} {obj.last_name}',
                'type': label,
                'registration_no': obj.registration_no,
                'applicant_type': getattr(obj, 'applicant_type', 'national'),
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

    completed_receipts = Receipt.objects.filter(status='completed')
    years = [s.year for s in snapshots]
    total_workers_by_year = [s.total_active_workers for s in snapshots]
    if import_context['import_years']:
        years = import_context['import_years']
        total_workers_by_year = import_context['import_year_counts']

    context = {
        'years': years,
        'total_workers_by_year': total_workers_by_year,
        'new_graduates_by_year': [s.new_graduates_joined for s in snapshots],
        'retirements_by_year': [s.retirements for s in snapshots],
        'latest_snapshot': snapshots.last(),
        'medical_count': MedicalDoctor.objects.count(),
        'nursing_count': NursingProfessional.objects.count(),
        'midwife_count': Midwife.objects.count(),
        'allied_count': 0,
        'chw_count': CommunityHealthWorker.objects.count(),
        'nurse_aide_count': NurseAide.objects.count(),
        'graduand_count': HealthStudent.objects.count(),
        'student_count': HealthStudent.objects.count(),
        'facility_count': Facility.objects.count() or reference_breakdown['facility_grouped_reference_count'],
        'institution_count': reference_breakdown['png_nursing_school_count'],
        'cadres': Cadre.objects.order_by('name'),
        'facilities': Facility.objects.select_related('location').order_by('name'),
        'institutions': TrainingInstitution.objects.order_by('name'),
        'document_types': DocumentType.objects.order_by('name'),
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
        'document_type_count': DocumentType.objects.count(),
        'document_count': 0,
        'receipt_pending_count': Receipt.objects.filter(status='pending').count(),
        'receipt_completed_count': completed_receipts.count(),
        'receipt_failed_count': Receipt.objects.filter(status='failed').count(),
        'receipt_total_amount': completed_receipts.aggregate(total=Sum('amount'))['total'] or 0,
        'receipt_count': Receipt.objects.count(),
        'age_groups': ['Under 30', '30-40', '41-50', '51-55', '56+'],
        'age_counts': [
            sum(1 for age in nurse_ages if age < 30),
            sum(1 for age in nurse_ages if 30 <= age <= 40),
            sum(1 for age in nurse_ages if 41 <= age <= 50),
            sum(1 for age in nurse_ages if 51 <= age <= 55),
            sum(1 for age in nurse_ages if age > 55),
        ],
        'flow_labels': ['Incoming Graduands', 'New Graduates', 'Nearing Retirement', 'Young Workforce'],
        'flow_data': [
            HealthStudent.objects.filter(is_graduate=False).count(),
            Application.objects.filter(form_code__in=['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G7'], status='approved').count(),
            sum(1 for age in nurse_ages if age >= 55),
            sum(1 for age in nurse_ages if age <= 35),
        ],
        'nurses_total': len(nurses),
        'nearing_retirement': sum(1 for age in nurse_ages if age >= 55),
        'young_workers': sum(1 for age in nurse_ages if age <= 35),
        'incoming_graduands': HealthStudent.objects.filter(is_graduate=False).count(),
        'incoming_students': HealthStudent.objects.filter(is_graduate=False).count(),
        'graduates_entering': Application.objects.filter(
            form_code__in=['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G7'], status='approved'
        ).count(),
        'graduand_by_institution': graduand_by_institution,
        'student_by_institution': graduand_by_institution,
        'national_workers_table': [row for row in professional_rows if row['applicant_type'] == 'national'],
        'overseas_workers_table': [row for row in professional_rows if row['applicant_type'] == 'overseas'],
        'workers_by_facility': workers_by_facility,
        'facility_reference_rows': imported_workplace_context['imported_facility_workers'],
        'recent_sync': None,
        'reference_breakdown': reference_breakdown,
    }
    context.update(import_context)
    context.update(imported_workplace_context)
    if import_context['latest_import_batch']:
        latest_batch_records = PracticingLicenseRecord.objects.filter(batch=import_context['latest_import_batch'])
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
    nursing_form_codes = ['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G7', 'NC1', 'NC2', 'NC3', 'NC4', 'NC5', 'NC6', 'NC7', 'NC8', 'NC9', 'NC10', 'NC11']
    context['dashboard_scope'] = 'nursing'
    context['medical_count'] = 0
    context['chw_count'] = 0
    context['allied_count'] = 0
    context['registration_count'] = (
        context.get('nursing_count', 0)
        + context.get('midwife_count', 0)
        + context.get('nurse_aide_count', 0)
    )
    context['application_count'] = Application.objects.filter(status='pending', form_code__in=nursing_form_codes).count()
    context['approved_applications'] = Application.objects.filter(status='approved', form_code__in=nursing_form_codes).count()
    context['rejected_applications'] = Application.objects.filter(status='rejected', form_code__in=nursing_form_codes).count()
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
    specialty_counts = {}
    for doctor in doctors:
        label = doctor.specialty or 'General Practice'
        specialty_counts[label] = specialty_counts.get(label, 0) + 1
    if not specialty_counts:
        specialty_counts = {'No specialty data loaded': 0}

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
    medical_records = PracticingLicenseRecord.objects.filter(
        target_model__in=['medicaldoctor', 'communityhealthworker'],
        record_year__isnull=False,
        record_year__lte=current_year,
    )
    if latest_medical_import:
        medical_records = medical_records.filter(batch=latest_medical_import)

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
    chw_registration_total = len({
        _record_identity(record)
        for record in medical_records.filter(target_model='communityhealthworker', record_type__in=['full', 'workforce_listing'])
        if _record_identity(record)
    }) or len(chws)
    chw_practicing_total = len({
        _record_identity(record)
        for record in medical_records.filter(target_model='communityhealthworker', record_type='practicing_license')
        if _record_identity(record)
    })

    medical_record_review_ids = list(
        medical_records.values_list('id', flat=True)[:50000]
    )
    medical_missing_reviews = MissingDataReview.objects.filter(
        Q(professional_type__in=['Medical Doctor', 'Community Health Worker'])
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
    return {
        'recent_applications': recent_applications,
        'pending_applications': Application.objects.filter(form_code__in=medical_form_codes, status='pending').count(),
        'renewals_pending': Application.objects.filter(form_code__in=['MD2', 'MBRN'], status='pending').count(),
        'facilities_count': Facility.objects.count(),
        'medical_doctor_count': len(doctors),
        'medical_specialist_count': sum(1 for doctor in doctors if doctor.specialty),
        'medical_chw_count': len(chws),
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
        'missing_data_review_count': medical_missing_reviews.count(),
        'high_priority_missing_data_count': medical_missing_reviews.filter(severity='high').count(),
        'missing_data_reviews': medical_missing_reviews[:20],
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
    context = {
        'total_users': User.objects.count(),
        'pending_applications': Application.objects.filter(status='pending').count(),
        'missing_data_review_count': MissingDataReview.objects.exclude(status='resolved').count(),
        'high_priority_missing_data_count': MissingDataReview.objects.filter(severity='high').exclude(status='resolved').count(),
        'missing_data_reviews': MissingDataReview.objects.exclude(status='resolved')[:15],
        'recent_notifications': [],
    }
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
        'missing_data_review_count': missing_queryset.count(),
        'high_priority_missing_data_count': missing_queryset.filter(severity='high').count(),
        'missing_data_reviews': missing_queryset[:15],
    }
    facility_target_models = None
    if request.user.role != 'admin':
        if is_nursing_registrar:
            facility_target_models = ['nursingprofessional', 'midwife', 'nurseaide', 'healthstudent']
        elif is_medical_registrar:
            facility_target_models = ['medicaldoctor', 'communityhealthworker']
    context.update(_current_workforce_context(include_facility_workers=True, facility_target_models=facility_target_models))
    return render(request, 'dashboard/registrar_dashboard.html', context)


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
        context.update(_current_workforce_context(include_facility_workers=True))
        if self.request.user.role in {'registrar', 'reviewer'} and is_nursing_council_staff(self.request.user):
            _apply_nursing_overview_scope(context)
        elif self.request.user.role in {'registrar', 'reviewer'} and is_medical_board_staff(self.request.user):
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
    scope = _analytics_scope_for_user(request.user)
    response = HttpResponse(content_type='application/pdf')
    filename = f'ndoh_{scope}_monthly_analytics_report.pdf' if scope else 'ndoh_monthly_analytics_report.pdf'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response.write(build_monthly_analytics_pdf(scope))
    return response


@login_required
@user_passes_test(_role_in('admin', 'registrar'))
def export_monthly_analytics_excel(request):
    scope = _analytics_scope_for_user(request.user)
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
    scope = _analytics_scope_for_user(request.user)
    response = HttpResponse(content_type='application/pdf')
    filename = f'ndoh_{scope}_monthly_analytics_report.pdf' if scope else 'ndoh_monthly_analytics_report.pdf'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response.write(build_monthly_analytics_pdf(scope))
    return response


@login_required
@user_passes_test(_role_in('admin', 'registrar'))
def export_yearly_analytics_excel(request):
    scope = _analytics_scope_for_user(request.user)
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
    scope = _analytics_scope_for_user(request.user)
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
    provisional_licenses = _current_provisional_licenses()
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
        'current_provisional_licenses': provisional_licenses,
        'provisional_license_count': len(provisional_licenses),
        'missing_data_review_count': nursing_missing_reviews.count(),
        'high_priority_missing_data_count': nursing_missing_reviews.filter(severity='high').count(),
        'missing_data_reviews': nursing_missing_reviews[:20],
        'renewals_pending': sum(
            1 for row in provisional_licenses
            if row['days_left'] is not None and 0 <= row['days_left'] <= 30
        ),
    })
    context.update(_nursing_province_distribution_context())
    context.update(_nursing_atp_context())
    return render(request, 'dashboard/nursing_council_portal.html', context)


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
        'import_medical_board_workbook': [sys.executable, 'manage.py', 'import_medical_board_workbook', '--file', r'd:\Database Template\Medical Board\CHW 1985-2026 DATABASE CURRENTLY UPDATING.xlsx'],
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
    return render(request, 'dashboard/fee_structure.html')


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
                        "url": "professional_detail",
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

            imported_records = PracticingLicenseRecord.objects.filter(
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
