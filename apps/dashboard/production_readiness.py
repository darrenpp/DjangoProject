from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Q, Subquery
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from apps.accounts.models import SecurityAuditEvent
from apps.common.models import DuplicateReviewQueue
from apps.dashboard.access import (
    MEDICAL_BOARD_FORM_CODES,
    MEDICAL_BOARD_PROFESSIONAL_MODELS,
    NURSING_COUNCIL_PROFESSIONAL_MODELS,
    is_data_quality_reviewer,
    is_medical_board_staff,
    is_nursing_council_staff,
)
from apps.dashboard.models import PlatformSyncOutboxItem, Receipt
from apps.dashboard.platform_resilience import current_platform_status
from apps.dashboard.report_freshness import report_freshness_rows
from apps.mobile_intake.models import (
    MobileDevice,
    MobileFormSchema,
    MobileLocalAccountRequest,
    MobilePromotionLink,
    MobileSubmission,
    MobileSubmissionAttachment,
)
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
MOBILE_REVIEW_STATUSES = {"RECEIVED", "VALIDATING", "DUPLICATE_RISK", "NEEDS_REVIEW", "NEEDS_CORRECTION"}


def _control_status(complete, *, pending_label="Pending Evidence", complete_label="Evidence Available", blocked=False):
    if complete:
        return {"label": complete_label, "tone": "success"}
    if blocked:
        return {"label": "Blocked", "tone": "danger"}
    return {"label": pending_label, "tone": "warning"}


def _manual_status(label, tone):
    return {"label": label, "tone": tone}


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
    receipt_content_type = ContentType.objects.get_for_model(Receipt)
    scoped_import_ids = _practicing_license_queryset(scope).values("id")
    scoped_receipt_ids = _receipt_queryset(scope).values("id")
    return queryset.filter(
        Q(content_type__model__in=_allowed_model_keys(scope))
        | Q(content_type=practicing_content_type, object_id__in=Subquery(scoped_import_ids))
        | Q(content_type=receipt_content_type, object_id__in=Subquery(scoped_receipt_ids))
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


def _mobile_submission_queryset(scope):
    queryset = MobileSubmission.objects.all()
    if scope:
        queryset = queryset.filter(office_scope=scope)
    return queryset


def _mobile_account_request_queryset(scope):
    queryset = MobileLocalAccountRequest.objects.all()
    if scope:
        queryset = queryset.filter(office_scope=scope)
    return queryset


def _mobile_schema_queryset(scope):
    queryset = MobileFormSchema.objects.filter(is_enabled=True)
    if scope:
        queryset = queryset.filter(office_scope=scope)
    return queryset


def _scope_readable(scope):
    return scope or "all"


def _settings_status_rows():
    default_database = settings.DATABASES.get("default", {})
    database_engine = str(default_database.get("ENGINE", "")).lower()
    allowed_hosts = list(getattr(settings, "ALLOWED_HOSTS", []) or [])
    email_backend = str(getattr(settings, "EMAIL_BACKEND", "") or "")
    email_host = str(getattr(settings, "EMAIL_HOST", "") or "")
    configured_email = bool(email_host and "console" not in email_backend.lower())
    secure_cookie_settings = bool(
        getattr(settings, "SESSION_COOKIE_SECURE", False)
        and getattr(settings, "CSRF_COOKIE_SECURE", False)
    )
    https_settings = bool(getattr(settings, "SECURE_SSL_REDIRECT", False) and secure_cookie_settings)
    return {
        "debug_off": not bool(getattr(settings, "DEBUG", False)),
        "allowed_hosts_configured": bool(allowed_hosts and "*" not in allowed_hosts),
        "postgres_configured": "postgres" in database_engine,
        "email_configured": configured_email,
        "mfa_required": bool(getattr(settings, "REQUIRE_STAFF_MFA", False)),
        "https_hardened": https_settings,
        "secure_cookies": secure_cookie_settings,
    }


def _pending_staff_approval_count():
    user_model = get_user_model()
    staff_roles = {"admin", "registrar", "reviewer", "mobile_collector"}
    return user_model.objects.filter(
        role__in=staff_roles,
    ).filter(
        Q(role_approved=False) | Q(system_admin_approved=False)
    ).count()


def _build_launch_gate_rows(scope, critical_total, duplicate_review_open):
    settings_rows = _settings_status_rows()
    pending_staff_accounts = _pending_staff_approval_count()
    open_mobile_submissions = _mobile_submission_queryset(scope).filter(status__in=MOBILE_REVIEW_STATUSES).count()
    pending_mobile_accounts = _mobile_account_request_queryset(scope).filter(status="PENDING").count()
    data_gate_clear = critical_total == 0 and duplicate_review_open == 0
    mobile_gate_clear = open_mobile_submissions == 0 and pending_mobile_accounts == 0

    return [
        {
            "area": "Hosting",
            "owner": "NDOH ICT",
            "evidence": "Approved staging/UAT and production hosting environment",
            "status": _control_status(
                settings_rows["debug_off"] and settings_rows["allowed_hosts_configured"] and settings_rows["postgres_configured"],
                pending_label="Needs ICT hosting evidence",
                complete_label="Configuration Evidence Available",
            ),
        },
        {
            "area": "Security",
            "owner": "NDOH ICT / security lead",
            "evidence": "Vulnerability scan, penetration test, permission test results",
            "status": _manual_status("External Test Required", "danger"),
        },
        {
            "area": "Domain / HTTPS",
            "owner": "NDOH ICT",
            "evidence": "Approved domain, certificate, DNS, HTTPS and secure cookie checks",
            "status": _control_status(
                settings_rows["https_hardened"] and settings_rows["allowed_hosts_configured"],
                pending_label="Needs HTTPS/domain evidence",
                complete_label="HTTPS Settings Present",
            ),
        },
        {
            "area": "Email / MFA",
            "owner": "NDOH ICT / system admin",
            "evidence": "SMTP tested, password reset tested, privileged MFA enabled",
            "status": _control_status(
                settings_rows["email_configured"] and settings_rows["mfa_required"],
                pending_label="Needs SMTP or MFA evidence",
                complete_label="Email and MFA Configured",
            ),
        },
        {
            "area": "Backup / restore",
            "owner": "NDOH ICT / DBA",
            "evidence": "Recorded database and media restore drill",
            "status": _manual_status("Restore Drill Required", "danger"),
        },
        {
            "area": "UAT",
            "owner": "Registrar + business users",
            "evidence": "Signed UAT scripts, issue log, retest evidence",
            "status": _manual_status("Scripts Required", "warning"),
        },
        {
            "area": "Data quality",
            "owner": "Registrar / data-quality lead",
            "evidence": "Duplicate, missing-data, date issue, and source-evidence sign-off",
            "status": _control_status(
                data_gate_clear,
                pending_label="Open data-quality issues",
                complete_label="No Open Data Blockers",
            ),
        },
        {
            "area": "Mobile intake",
            "owner": "Registrar + ICT + mobile field lead",
            "evidence": "One offline draft synced, reviewed, decided, and returned to Android",
            "status": _control_status(
                mobile_gate_clear,
                pending_label="Open mobile queue",
                complete_label="No Open Mobile Intake",
            ),
        },
        {
            "area": "Staff approval",
            "owner": "Registrar + System Admin",
            "evidence": "All staff roles have Registrar and System Admin approval before login",
            "status": _control_status(
                pending_staff_accounts == 0,
                pending_label="Pending staff approvals",
                complete_label="No Pending Staff Approvals",
            ),
        },
        {
            "area": "Support",
            "owner": "Business owner + ICT",
            "evidence": "SLA, escalation path, named support owner, release/change process",
            "status": _manual_status("Owner Sign-off Required", "warning"),
        },
    ]


def _build_environment_rows():
    settings_rows = _settings_status_rows()
    return [
        {
            "environment": "Development",
            "purpose": "Developer work only",
            "rule": "Sanitised or sample data only",
            "status": _manual_status("Local Build", "info"),
        },
        {
            "environment": "Staging / UAT",
            "purpose": "Registrar and staff testing",
            "rule": "Controlled production-like data, no public go-live",
            "status": _manual_status("ICT Environment Required", "warning"),
        },
        {
            "environment": "Production",
            "purpose": "Live government operations",
            "rule": "DEBUG=False, PostgreSQL, HTTPS, secure media, restricted access",
            "status": _control_status(
                settings_rows["debug_off"] and settings_rows["postgres_configured"] and settings_rows["https_hardened"],
                pending_label="Not Production Hardened",
                complete_label="Production Settings Present",
                blocked=bool(getattr(settings, "DEBUG", False)),
            ),
        },
        {
            "environment": "Backup / restore",
            "purpose": "Recovery testing and continuity",
            "rule": "Encrypted backups, separate storage, restore drills",
            "status": _manual_status("Restore Evidence Required", "danger"),
        },
    ]


def _build_security_rows():
    settings_rows = _settings_status_rows()
    since = timezone.now() - timedelta(days=1)
    recent_security_events = SecurityAuditEvent.objects.filter(
        action__in=["LOGIN_FAILED", "MFA_FAILED", "ACCESS_DENIED"],
        created_at__gte=since,
    ).count()
    audit_event_count = SecurityAuditEvent.objects.count()
    pending_staff_accounts = _pending_staff_approval_count()

    return [
        {
            "control": "Independent vulnerability scan",
            "why": "Finds common web exposure before launch",
            "evidence": "Signed scan report",
            "status": _manual_status("External Test Required", "danger"),
        },
        {
            "control": "Independent penetration test",
            "why": "Tests real attack paths and object-level access attempts",
            "evidence": "Signed penetration test report",
            "status": _manual_status("External Test Required", "danger"),
        },
        {
            "control": "Privileged MFA",
            "why": "Reduces compromise risk for System Admin and Registrar accounts",
            "evidence": "REQUIRE_STAFF_MFA setting and successful login test",
            "status": _control_status(
                settings_rows["mfa_required"],
                pending_label="MFA Not Enforced",
                complete_label="MFA Required",
            ),
        },
        {
            "control": "Dual staff account approval",
            "why": "Registrar and System Admin approval required before staff login",
            "evidence": f"{pending_staff_accounts} staff accounts pending approval",
            "status": _control_status(
                pending_staff_accounts == 0,
                pending_label="Pending Staff Approvals",
                complete_label="Approval Queue Clear",
            ),
        },
        {
            "control": "Security events and audit trail",
            "why": "Makes failed access, MFA, and sensitive actions defensible",
            "evidence": f"{audit_event_count} security audit events, {recent_security_events} in last 24 hours",
            "status": _control_status(
                audit_event_count > 0,
                pending_label="Needs Audit Evidence",
                complete_label="Audit Events Present",
            ),
        },
        {
            "control": "Secure browser/session settings",
            "why": "Reduces common browser and session risks",
            "evidence": "HTTPS redirect plus secure session and CSRF cookies",
            "status": _control_status(
                settings_rows["https_hardened"],
                pending_label="Needs HTTPS Hardening",
                complete_label="Secure Settings Present",
            ),
        },
        {
            "control": "Public-safe field review",
            "why": "Prevents private practitioner, applicant, receipt, document, or staff data leakage",
            "evidence": "Signed public-register field list",
            "status": _manual_status("Registrar Review Required", "warning"),
        },
    ]


def _build_data_quality_kpi_rows(scope, missing_data, duplicate_review_open, duplicate_identifier_rows, conflict_rows):
    receipt_queryset = _receipt_queryset(scope)
    mobile_queryset = _mobile_submission_queryset(scope)
    week_ago = timezone.now() - timedelta(days=7)
    receipts_not_linked = receipt_queryset.filter(
        Q(application__isnull=True) & (
            Q(payer_content_type__isnull=True)
            | Q(payer_match_confidence__in=["unlinked", "ambiguous"])
        )
    ).count()
    source_evidence_missing = _missing_reviews_queryset(scope).filter(
        Q(source_label="") | Q(source_label__isnull=True)
    ).count()
    promoted_this_week = MobilePromotionLink.objects.filter(promoted_at__gte=week_ago)
    if scope:
        promoted_this_week = promoted_this_week.filter(submission__office_scope=scope)

    return [
        {
            "kpi": "Duplicate records pending",
            "value": duplicate_review_open,
            "why": "Protects legal registry identity integrity",
            "status": _control_status(duplicate_review_open == 0, pending_label="Needs Review", complete_label="Clear"),
        },
        {
            "kpi": "Missing critical fields",
            "value": missing_data["high"],
            "why": "Improves reporting, licensing, and workforce planning",
            "status": _control_status(missing_data["high"] == 0, pending_label="Needs Source Check", complete_label="Clear"),
        },
        {
            "kpi": "Records without source evidence",
            "value": source_evidence_missing,
            "why": "Protects audit defensibility",
            "status": _control_status(source_evidence_missing == 0, pending_label="Needs Evidence Label", complete_label="Clear"),
        },
        {
            "kpi": "Receipts not linked to applications/records",
            "value": receipts_not_linked,
            "why": "Protects finance traceability",
            "status": _control_status(receipts_not_linked == 0, pending_label="Needs Reconciliation", complete_label="Clear"),
        },
        {
            "kpi": "Conflicting or dirty identifiers",
            "value": len(duplicate_identifier_rows) + len(conflict_rows),
            "why": "Prevents invalid active licences and duplicate identity rows",
            "status": _control_status(
                not duplicate_identifier_rows and not conflict_rows,
                pending_label="Needs Cleansing",
                complete_label="Clear",
            ),
        },
        {
            "kpi": "Mobile submissions awaiting review",
            "value": mobile_queryset.filter(status__in=MOBILE_REVIEW_STATUSES).count(),
            "why": "Prevents unreviewed field data becoming official",
            "status": _control_status(
                not mobile_queryset.filter(status__in=MOBILE_REVIEW_STATUSES).exists(),
                pending_label="Needs Desktop Review",
                complete_label="Clear",
            ),
        },
        {
            "kpi": "Records promoted this week",
            "value": promoted_this_week.count(),
            "why": "Shows controlled data-quality throughput",
            "status": _manual_status("Throughput Indicator", "info"),
        },
        {
            "kpi": "Rejected/corrected source rows",
            "value": mobile_queryset.filter(status__in=["REJECTED", "NEEDS_CORRECTION"]).count(),
            "why": "Shows cleansing discipline and prevents silent promotion",
            "status": _manual_status("Correction Indicator", "info"),
        },
    ]


def _build_finance_control_rows(scope):
    receipt_queryset = _receipt_queryset(scope)
    unlinked_or_ambiguous = receipt_queryset.filter(payer_match_confidence__in=["unlinked", "ambiguous"]).count()
    pending_receipts = receipt_queryset.filter(status="pending").count()
    completed_receipts = receipt_queryset.filter(status="completed").count()
    high_value_review = receipt_queryset.filter(
        amount__gte=Decimal("200.00"),
        payer_match_confidence__in=["unlinked", "ambiguous"],
    ).count()
    return [
        {
            "control": "Receipt-to-application linking",
            "purpose": "Prevents orphan payment evidence",
            "metric": f"{unlinked_or_ambiguous} unlinked/ambiguous",
            "status": _control_status(unlinked_or_ambiguous == 0, pending_label="Needs Reconciliation", complete_label="Linked"),
        },
        {
            "control": "Receipt status lifecycle",
            "purpose": "Separates pending, completed, rejected, disputed, and refund evidence",
            "metric": f"{pending_receipts} pending / {completed_receipts} completed",
            "status": _manual_status("Lifecycle In Use", "info"),
        },
        {
            "control": "High-value/manual override audit",
            "purpose": "Protects against fraud or accidental misuse",
            "metric": f"{high_value_review} high-value records to review",
            "status": _control_status(high_value_review == 0, pending_label="Needs Finance Review", complete_label="Clear"),
        },
        {
            "control": "Finance read-only principle",
            "purpose": "Finance verifies payment evidence but does not alter registry decisions",
            "metric": "Role matrix evidence required",
            "status": _manual_status("Permission Test Required", "warning"),
        },
        {
            "control": "Monthly reconciliation export",
            "purpose": "Supports monthly finance review",
            "metric": "Export sign-off required",
            "status": _manual_status("SOP Required", "warning"),
        },
    ]


def _build_uat_script_rows():
    return [
        ("Registrar", "Application review, decision, audit trail, and reports"),
        ("Reviewer", "Checklist review, evidence review, and messages"),
        ("Finance", "Receipt matching, verification, and finance export"),
        ("Data Quality", "Duplicate review, missing-data correction, and promotion"),
        ("System Admin", "User approval, role assignment, MFA, backup checks"),
        ("Professional / applicant", "Own profile, own application, own receipts only"),
        ("Public user", "Public-safe search only, no private data exposure"),
        ("Mobile user", "Offline draft, sync, status return"),
    ]


def _build_mobile_gate_rows(scope):
    queryset = _mobile_submission_queryset(scope)
    schema_count = _mobile_schema_queryset(scope).count()
    pending_accounts = _mobile_account_request_queryset(scope).filter(status="PENDING").count()
    failed_submissions = queryset.filter(status="FAILED").count()
    pending_submissions = queryset.filter(status__in=MOBILE_REVIEW_STATUSES).count()
    duplicate_risk = queryset.filter(status="DUPLICATE_RISK").count()
    attachment_failures = MobileSubmissionAttachment.objects.filter(upload_status="FAILED")
    if scope:
        attachment_failures = attachment_failures.filter(office_scope=scope)
    unapproved_devices = MobileDevice.objects.filter(approved_at__isnull=True, is_active=True).count()

    return [
        {
            "gate": "Idempotency tests",
            "why": "Prevent duplicate submissions after retry",
            "metric": "Idempotency key is unique in the backend model",
            "status": _manual_status("Model Guard Present", "success"),
        },
        {
            "gate": "Attachment retry handling",
            "why": "Prevent lost documents in weak connectivity",
            "metric": f"{attachment_failures.count()} failed attachment uploads",
            "status": _control_status(attachment_failures.count() == 0, pending_label="Needs Retry Review", complete_label="Clear"),
        },
        {
            "gate": "Device/account approval workflow",
            "why": "Prevent unauthorised field users",
            "metric": f"{pending_accounts} pending account requests, {unapproved_devices} unapproved active devices",
            "status": _control_status(
                pending_accounts == 0 and unapproved_devices == 0,
                pending_label="Needs Approval Review",
                complete_label="Clear",
            ),
        },
        {
            "gate": "Sync status dashboard",
            "why": "Lets admins see failed or pending mobile records",
            "metric": f"{pending_submissions} pending, {failed_submissions} failed",
            "status": _control_status(
                pending_submissions == 0 and failed_submissions == 0,
                pending_label="Open Mobile Queue",
                complete_label="Queue Clear",
            ),
        },
        {
            "gate": "Offline validation rules",
            "why": "Reduces poor-quality data before sync",
            "metric": f"{schema_count} enabled mobile schemas",
            "status": _control_status(schema_count > 0, pending_label="Schemas Required", complete_label="Schemas Enabled"),
        },
        {
            "gate": "Desktop review before promotion",
            "why": "Keeps mobile intake from becoming automatic approval",
            "metric": f"{duplicate_risk} duplicate-risk submissions",
            "status": _manual_status("Registrar Review Required", "warning" if duplicate_risk else "success"),
        },
        {
            "gate": "HTTPS-only production mobile API",
            "why": "Avoids local HTTP testing patterns leaking into production",
            "metric": "Requires production HTTPS/domain evidence",
            "status": _control_status(
                _settings_status_rows()["https_hardened"],
                pending_label="Needs HTTPS Evidence",
                complete_label="HTTPS Settings Present",
            ),
        },
    ]


def _build_platform_resilience_rows(platform_status):
    pending = platform_status.get("pending_sync_count", 0)
    failed = platform_status.get("failed_sync_count", 0)
    blocked = platform_status.get("blocked_sync_count", 0)
    return [
        {
            "control": "LAN/offline operating mode",
            "purpose": "Keeps the local office usable when internet service fails",
            "metric": platform_status.get("mode_label", "Unknown"),
            "status": _control_status(
                platform_status.get("offline_lan_enabled"),
                pending_label="Needs LAN Mode",
                complete_label="Enabled",
            ),
        },
        {
            "control": "Connectivity probe",
            "purpose": "Automatically marks the platform online or offline/LAN",
            "metric": platform_status.get("last_checked_at") or "No probe recorded",
            "status": _control_status(
                bool(platform_status.get("last_checked_at")),
                pending_label="Run Probe",
                complete_label="Probe Active",
            ),
        },
        {
            "control": "Automatic sync worker",
            "purpose": "Retries queued external sync items after connectivity returns",
            "metric": "Auto-sync enabled" if platform_status.get("auto_sync_enabled") else "Auto-sync disabled",
            "status": _control_status(
                platform_status.get("auto_sync_enabled"),
                pending_label="Enable Worker",
                complete_label="Enabled",
            ),
        },
        {
            "control": "Remote sync endpoint",
            "purpose": "Defines where queued online updates are pushed when internet returns",
            "metric": "Configured" if platform_status.get("sync_remote_configured") else "Not configured",
            "status": _control_status(
                platform_status.get("sync_remote_configured"),
                pending_label="Needs Endpoint",
                complete_label="Configured",
            ),
        },
        {
            "control": "Sync backlog",
            "purpose": "Shows queued, failed, or blocked internet-dependent work",
            "metric": f"{pending} pending / {failed} failed / {blocked} blocked",
            "status": (
                _manual_status("Blocked Items", "danger")
                if blocked
                else _control_status(failed == 0, pending_label="Needs Retry", complete_label="Healthy")
            ),
        },
    ]


def _build_permission_matrix_rows():
    return [
        {
            "access_area": "Public",
            "must_prove": "Can only see public-safe verification fields",
            "privacy_position": "No private practitioner, applicant, receipt, document, or staff data",
            "status": _manual_status("Negative Tests Required", "warning"),
        },
        {
            "access_area": "Professional / applicant",
            "must_prove": "Can only see own profile, applications, receipts, and documents",
            "privacy_position": "Cannot view another person's record",
            "status": _manual_status("Ownership Tests Required", "warning"),
        },
        {
            "access_area": "Nursing Council staff",
            "must_prove": "Cannot access Medical Board private records unless authorised",
            "privacy_position": "Nursing scope by default",
            "status": _manual_status("Cross-office Tests Required", "warning"),
        },
        {
            "access_area": "Medical Board staff",
            "must_prove": "Cannot access Nursing Council private records unless authorised",
            "privacy_position": "Medical scope by default",
            "status": _manual_status("Cross-office Tests Required", "warning"),
        },
        {
            "access_area": "Finance",
            "must_prove": "Read-only and scoped finance access",
            "privacy_position": "Cannot approve applications or alter registry records",
            "status": _manual_status("Permission Tests Required", "warning"),
        },
        {
            "access_area": "Reviewer",
            "must_prove": "Assigned review queues only",
            "privacy_position": "Cannot make final registrar decisions unless authorised",
            "status": _manual_status("Workflow Tests Required", "warning"),
        },
        {
            "access_area": "Data Quality",
            "must_prove": "Cleansing and review tasks only",
            "privacy_position": "No registrar override",
            "status": _manual_status("Workflow Tests Required", "warning"),
        },
        {
            "access_area": "System Admin",
            "must_prove": "Technical configuration only unless formally authorised",
            "privacy_position": "Should not replace registrar decisions",
            "status": _manual_status("Governance Sign-off Required", "warning"),
        },
    ]


def _build_support_dr_rows():
    return [
        {
            "area": "Support model",
            "minimum": "Helpdesk queue, escalation matrix, SLA, named business and ICT owners",
            "evidence": "Signed support plan",
            "status": _manual_status("Owner Sign-off Required", "warning"),
        },
        {
            "area": "Incident management",
            "minimum": "Severity levels, response times, incident log",
            "evidence": "Incident SOP",
            "status": _manual_status("SOP Required", "warning"),
        },
        {
            "area": "Release and change control",
            "minimum": "Release notes, staging test, approved deployment window",
            "evidence": "Change control register",
            "status": _manual_status("SOP Required", "warning"),
        },
        {
            "area": "Database backup",
            "minimum": "Daily automated database backup",
            "evidence": "Backup logs",
            "status": _manual_status("ICT Evidence Required", "danger"),
        },
        {
            "area": "Media/document backup",
            "minimum": "Daily backup of uploaded evidence and documents",
            "evidence": "Backup logs",
            "status": _manual_status("ICT Evidence Required", "danger"),
        },
        {
            "area": "Restore drill",
            "minimum": "Monthly restore test into staging/UAT",
            "evidence": "Signed restore report",
            "status": _manual_status("Restore Drill Required", "danger"),
        },
        {
            "area": "RPO / RTO",
            "minimum": "Define acceptable data loss and recovery time",
            "evidence": "Business continuity approval",
            "status": _manual_status("Decision Required", "warning"),
        },
    ]


def _build_integration_rows():
    return [
        {
            "control": "Data classification matrix",
            "purpose": "Defines public, restricted, confidential, and sensitive fields",
            "status": _manual_status("Registrar/ICT Sign-off Required", "warning"),
        },
        {
            "control": "API approval process",
            "purpose": "Prevents informal integrations and uncontrolled data exchange",
            "status": _manual_status("ICT Approval Required", "warning"),
        },
        {
            "control": "Export approval workflow",
            "purpose": "Controls CSV/report sharing and records who exported what",
            "status": _manual_status("SOP Required", "warning"),
        },
        {
            "control": "FHIR/interoperability assessment",
            "purpose": "Avoids premature standards claims before eHealth/TWG review",
            "status": _manual_status("Future Assessment", "info"),
        },
        {
            "control": "Data sharing agreements",
            "purpose": "Required before external exchange of restricted registry data",
            "status": _manual_status("Legal/ICT Review Required", "warning"),
        },
    ]


def _build_thirty_sixty_ninety_rows():
    return [
        {
            "period": "First 30 days",
            "focus": "Controlled hosting, owner assignment, UAT scripts, data-quality plan",
            "output": "UAT environment, owner matrix, test scripts, issue register",
        },
        {
            "period": "30-60 days",
            "focus": "UAT, security review, backup/restore drill, mobile end-to-end test",
            "output": "UAT evidence, security findings, restore evidence, mobile test report",
        },
        {
            "period": "60-90 days",
            "focus": "Fixes, staff training, SOPs, support model, readiness review",
            "output": "Signed readiness pack and controlled production decision",
        },
    ]


def build_production_readiness_context(user):
    scope = _scope_for_user(user)
    platform_status = current_platform_status(use_cache=False)
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
    launch_gate_rows = _build_launch_gate_rows(scope, critical_total, duplicate_review_open)
    gate_status_counts = {
        "clear": sum(1 for row in launch_gate_rows if row["status"]["tone"] == "success"),
        "warning": sum(1 for row in launch_gate_rows if row["status"]["tone"] == "warning"),
        "blocked": sum(1 for row in launch_gate_rows if row["status"]["tone"] == "danger"),
    }
    readiness_gate_percent = round((gate_status_counts["clear"] / len(launch_gate_rows)) * 100) if launch_gate_rows else 0
    settings_rows = _settings_status_rows()

    return {
        "generated_at": timezone.localtime(),
        "scope_label": _scope_label(scope),
        "scope_key": _scope_readable(scope),
        "readiness_status": "Needs Data Review" if critical_total else "Ready For UAT Review",
        "controlled_testing_status": (
            "Ready For Controlled Testing Review"
            if critical_total == 0
            else "Controlled Testing Blocked By Data Issues"
        ),
        "production_status": "Not Production Ready",
        "production_decision_line": (
            "The platform foundation is implemented. The decision sought is controlled testing "
            "and owner assignment, not uncontrolled production go-live."
        ),
        "critical_total": critical_total,
        "readiness_gate_percent": readiness_gate_percent,
        "gate_status_counts": gate_status_counts,
        "total_date_issues": total_date_issues,
        "date_issues": date_issues,
        "missing_data": missing_data,
        "duplicate_review_open": duplicate_review_open,
        "duplicate_identifier_rows": duplicate_identifier_rows,
        "unique_conflict_rows": conflict_rows,
        "import_batches": import_batches,
        "import_status_rows": import_status_rows,
        "launch_gate_rows": launch_gate_rows,
        "environment_rows": _build_environment_rows(),
        "security_control_rows": _build_security_rows(),
        "data_quality_kpi_rows": _build_data_quality_kpi_rows(
            scope,
            missing_data,
            duplicate_review_open,
            duplicate_identifier_rows,
            conflict_rows,
        ),
        "finance_control_rows": _build_finance_control_rows(scope),
        "uat_script_rows": [
            {"role": role, "proves": proves, "status": _manual_status("Needs UAT Evidence", "warning")}
            for role, proves in _build_uat_script_rows()
        ],
        "mobile_gate_rows": _build_mobile_gate_rows(scope),
        "platform_resilience_status": platform_status,
        "platform_resilience_rows": _build_platform_resilience_rows(platform_status),
        "permission_matrix_rows": _build_permission_matrix_rows(),
        "support_dr_rows": _build_support_dr_rows(),
        "integration_control_rows": _build_integration_rows(),
        "thirty_sixty_ninety_rows": _build_thirty_sixty_ninety_rows(),
        "platform_setting_rows": [
            {
                "label": "DEBUG off",
                "status": _control_status(settings_rows["debug_off"], pending_label="DEBUG=True", complete_label="DEBUG=False"),
            },
            {
                "label": "Allowed hosts configured",
                "status": _control_status(settings_rows["allowed_hosts_configured"], pending_label="Needs host list", complete_label="Configured"),
            },
            {
                "label": "PostgreSQL configured",
                "status": _control_status(settings_rows["postgres_configured"], pending_label="Not PostgreSQL", complete_label="Configured"),
            },
            {
                "label": "Production SMTP configured",
                "status": _control_status(settings_rows["email_configured"], pending_label="Needs SMTP", complete_label="Configured"),
            },
            {
                "label": "Privileged MFA required",
                "status": _control_status(settings_rows["mfa_required"], pending_label="Needs MFA", complete_label="Enabled"),
            },
            {
                "label": "HTTPS secure cookies",
                "status": _control_status(settings_rows["https_hardened"], pending_label="Needs HTTPS hardening", complete_label="Configured"),
            },
        ],
        "latest_reports": _latest_readiness_reports(),
        "report_freshness_rows": report_freshness_rows(scope),
        "production_rule": (
            "Imported rows are not automatically trusted. They are staged, validated, cleansed, "
            "reviewed, approved, then promoted into live registry records."
        ),
        "go_live_rule": (
            "Full production use must wait for ICT review, UAT sign-off, security checks, "
            "backup/restore confirmation, staff training, and production-readiness approval."
        ),
    }
