from collections import Counter
from datetime import date

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db.models import Q, Subquery
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from apps.dashboard.models import RegistryArchiveRecord
from apps.workforce.models import (
    CommunityHealthWorker,
    DeceasedNotification,
    HealthStudent,
    MedicalDoctor,
    Midwife,
    NurseAide,
    NursingProfessional,
    PracticingLicenseRecord,
)

DEFAULT_RETIREMENT_AGE = 65
DEFAULT_LAPSED_YEARS = 2
ARCHIVE_SYNC_CACHE_SECONDS = 15 * 60

NURSING_TARGET_MODELS = {"nursingprofessional", "midwife", "nurseaide", "healthstudent"}
MEDICAL_TARGET_MODELS = {"medicaldoctor", "communityhealthworker", "other"}

PROFESSIONAL_SCOPE_MODELS = {
    "nursing": (NursingProfessional, Midwife, NurseAide, HealthStudent),
    "medical": (MedicalDoctor, CommunityHealthWorker),
}


def current_archive_year():
    return timezone.localdate().year


def age_from_birth_date(birth_date, today=None):
    if not birth_date:
        return None
    today = today or timezone.localdate()
    age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
    if age < 0:
        return None
    return age


def scope_for_model(model):
    model_name = model.__name__.lower()
    if model_name in NURSING_TARGET_MODELS:
        return "nursing"
    if model_name in MEDICAL_TARGET_MODELS:
        return "medical"
    return "all"


def scope_for_import_record(record):
    target_model = (record.target_model or "").lower()
    if target_model in NURSING_TARGET_MODELS:
        return "nursing"
    if target_model in MEDICAL_TARGET_MODELS:
        return "medical"
    source_kind = getattr(record.batch, "source_kind", "") if getattr(record, "batch_id", None) else ""
    if source_kind == "medical_board_workbook":
        return "medical"
    return "all"


def scope_matches(scope, record_scope):
    return scope in {"", "all", None} or record_scope == scope


def professional_display_name(obj):
    pieces = [
        getattr(obj, "first_name", "") or "",
        getattr(obj, "middle_name", "") or "",
        getattr(obj, "last_name", "") or "",
    ]
    name = " ".join(piece for piece in pieces if piece).strip()
    return name or str(obj)


def professional_cadre(obj):
    cadre = getattr(obj, "cadre", None)
    if cadre:
        return getattr(cadre, "name", "") or str(cadre)
    for field in ("qualification_level", "training_level", "specialty", "program"):
        value = getattr(obj, field, "")
        if value:
            return value
    return obj.__class__.__name__


def _latest_renewal_year(obj):
    expiry = getattr(obj, "license_expiry_date", None)
    if expiry:
        return expiry.year
    issued = getattr(obj, "date_issued", None)
    if issued:
        return issued.year
    expected_graduation = getattr(obj, "expected_graduation_date", None)
    if expected_graduation:
        return expected_graduation.year
    return None


def _approved_deceased_notification(obj):
    content_type = ContentType.objects.get_for_model(obj.__class__)
    registration_numbers = [
        value for value in (getattr(obj, "registration_no", ""), getattr(obj, "registration_number", "")) if value
    ]
    query = Q(content_type=content_type, object_id=obj.pk)
    if registration_numbers:
        query |= Q(registration_number__in=registration_numbers)
    return DeceasedNotification.objects.filter(query, verification_status="approved").order_by("-updated_at").first()


def _payload_text(payload):
    if not payload:
        return ""
    if isinstance(payload, dict):
        values = []
        for key, value in payload.items():
            if isinstance(value, (str, int, float)):
                values.append(f"{key} {value}")
        return " ".join(values).lower()
    return str(payload).lower()


def professional_archive_signal(obj, *, current_year=None, retirement_age=DEFAULT_RETIREMENT_AGE, lapsed_years=DEFAULT_LAPSED_YEARS):
    current_year = current_year or current_archive_year()
    today = date(current_year, 12, 31)
    age = age_from_birth_date(getattr(obj, "date_of_birth", None), today=today)
    latest_renewal_year = _latest_renewal_year(obj)
    evidence = {"source": "professional_record"}

    deceased_notice = _approved_deceased_notification(obj)
    if deceased_notice:
        evidence.update({
            "deceased_notification_id": deceased_notice.pk,
            "date_of_death": deceased_notice.date_of_death.isoformat(),
            "verification_status": deceased_notice.verification_status,
        })
        return "deceased", "confirmed_deceased", age, latest_renewal_year, evidence

    if age is not None and age >= retirement_age:
        evidence.update({"age": age, "retirement_age": retirement_age})
        return "old_age", "review_required", age, latest_renewal_year, evidence

    expiry = getattr(obj, "license_expiry_date", None)
    if expiry and expiry.year <= current_year - lapsed_years:
        evidence.update({"license_expiry_date": expiry.isoformat(), "lapsed_years": lapsed_years})
        return "lapsed_renewal", "archived", age, latest_renewal_year, evidence

    if not getattr(obj, "is_active", True):
        evidence.update({"is_active": False})
        return "inactive", "review_required", age, latest_renewal_year, evidence

    return None


def import_record_archive_signal(record, *, current_year=None, retirement_age=DEFAULT_RETIREMENT_AGE, lapsed_years=DEFAULT_LAPSED_YEARS):
    current_year = current_year or current_archive_year()
    today = date(current_year, 12, 31)
    age = age_from_birth_date(record.date_of_birth, today=today)
    record_year = record.record_year
    evidence = {
        "source": "import_record",
        "record_type": record.record_type,
        "source_sheet_name": record.source_sheet_name,
        "source_row": record.source_row,
    }
    payload_text = " ".join([
        (record.category or ""),
        (record.full_name or ""),
        _payload_text(record.raw_payload),
    ]).lower()
    if "deceased" in payload_text or "death" in payload_text:
        return "deceased", "review_required", age, record_year, {**evidence, "matched_text": "deceased/death"}
    if "retired" in payload_text or "retirement" in payload_text:
        return "retired", "review_required", age, record_year, {**evidence, "matched_text": "retired/retirement"}
    if age is not None and age >= retirement_age:
        return "old_age", "review_required", age, record_year, {**evidence, "age": age, "retirement_age": retirement_age}
    if record.record_type == "practicing_license" and record_year and record_year <= current_year - lapsed_years:
        return "lapsed_renewal", "archived", age, record_year, {**evidence, "lapsed_years": lapsed_years}
    return None


def archive_key_for(obj, reason, record_year=None):
    content_type = ContentType.objects.get_for_model(obj.__class__)
    return f"{content_type.app_label}.{content_type.model}:{obj.pk}:{reason}:{record_year or 'na'}"


def _archive_defaults_for_object(obj, reason, status, age, latest_renewal_year, evidence, *, scope, user=None):
    registration_no = getattr(obj, "registration_no", "") or getattr(obj, "registration_number", "") or ""
    practitioner_number = getattr(obj, "practitioner_number", "") or ""
    if isinstance(obj, PracticingLicenseRecord):
        label = obj.full_name
        record_year = obj.record_year
        cadre = obj.category or obj.qualification_name or obj.get_target_model_display()
        facility = obj.workplace_address
        province = obj.province
        source_reference = f"{obj.batch_id}:{obj.source_sheet_name}:{obj.source_row}"
    else:
        label = professional_display_name(obj)
        record_year = latest_renewal_year
        cadre = professional_cadre(obj)
        facility = getattr(obj, "employer", "") or ""
        province = getattr(obj, "province", "") or ""
        source_reference = str(obj.pk)
    return {
        "content_type": ContentType.objects.get_for_model(obj.__class__),
        "object_id": obj.pk,
        "source_model": f"{obj.__class__._meta.app_label}.{obj.__class__._meta.model_name}",
        "source_reference": source_reference,
        "source_label": label,
        "scope": scope,
        "record_year": record_year,
        "latest_renewal_year": latest_renewal_year,
        "age": age,
        "archive_reason": reason,
        "archive_status": status,
        "registration_no": registration_no,
        "practitioner_number": practitioner_number,
        "cadre": cadre,
        "facility": facility,
        "province": province,
        "excluded_from_active_totals": status != "restored",
        "evidence": evidence,
        "archived_by": user if getattr(user, "is_authenticated", False) else None,
    }


def upsert_archive_record(obj, reason, status, age, latest_renewal_year, evidence, *, scope, user=None, dry_run=False):
    key = archive_key_for(obj, reason, latest_renewal_year)
    defaults = _archive_defaults_for_object(
        obj,
        reason,
        status,
        age,
        latest_renewal_year,
        evidence,
        scope=scope,
        user=user,
    )
    if dry_run:
        return None, True
    return RegistryArchiveRecord.objects.update_or_create(archive_key=key, defaults=defaults)


def _professional_models_for_scope(scope):
    if scope == "nursing":
        return PROFESSIONAL_SCOPE_MODELS["nursing"]
    if scope == "medical":
        return PROFESSIONAL_SCOPE_MODELS["medical"]
    return PROFESSIONAL_SCOPE_MODELS["nursing"] + PROFESSIONAL_SCOPE_MODELS["medical"]


def import_records_for_scope(scope):
    queryset = PracticingLicenseRecord.objects.select_related("batch").order_by("-record_year", "full_name")
    if scope == "nursing":
        return queryset.filter(target_model__in=NURSING_TARGET_MODELS).exclude(batch__source_kind="medical_board_workbook")
    if scope == "medical":
        return queryset.filter(
            Q(target_model__in=MEDICAL_TARGET_MODELS) | Q(batch__source_kind="medical_board_workbook")
        )
    return queryset


def sync_registry_archives(
    *,
    scope="all",
    current_year=None,
    retirement_age=DEFAULT_RETIREMENT_AGE,
    lapsed_years=DEFAULT_LAPSED_YEARS,
    user=None,
    dry_run=False,
    limit=None,
):
    current_year = current_year or current_archive_year()
    created = 0
    updated = 0
    reviewed = 0

    for model in _professional_models_for_scope(scope):
        record_scope = scope_for_model(model)
        queryset = model.objects.select_related("cadre").order_by("id")
        if limit:
            queryset = queryset[:limit]
        for obj in queryset.iterator(chunk_size=500):
            signal = professional_archive_signal(
                obj,
                current_year=current_year,
                retirement_age=retirement_age,
                lapsed_years=lapsed_years,
            )
            if not signal:
                continue
            reason, status, age, latest_year, evidence = signal
            _record, was_created = upsert_archive_record(
                obj,
                reason,
                status,
                age,
                latest_year,
                evidence,
                scope=record_scope,
                user=user,
                dry_run=dry_run,
            )
            created += 1 if was_created else 0
            updated += 0 if was_created else 1
            reviewed += 1

    import_queryset = import_records_for_scope(scope)
    if limit:
        import_queryset = import_queryset[:limit]
    for record in import_queryset.iterator(chunk_size=500):
        record_scope = scope_for_import_record(record)
        if not scope_matches(scope, record_scope):
            continue
        signal = import_record_archive_signal(
            record,
            current_year=current_year,
            retirement_age=retirement_age,
            lapsed_years=lapsed_years,
        )
        if not signal:
            continue
        reason, status, age, latest_year, evidence = signal
        _archive, was_created = upsert_archive_record(
            record,
            reason,
            status,
            age,
            latest_year,
            evidence,
            scope=record_scope,
            user=user,
            dry_run=dry_run,
        )
        created += 1 if was_created else 0
        updated += 0 if was_created else 1
        reviewed += 1

    return {
        "created": created,
        "updated": updated,
        "reviewed": reviewed,
        "current_year": current_year,
        "retirement_age": retirement_age,
        "lapsed_years": lapsed_years,
    }


def refresh_registry_archives(*, scope="all", user=None, force=False):
    cache_key = f"registry-archive-sync:{scope}:{current_archive_year()}"
    if not force and cache.get(cache_key):
        return {"skipped": True, "current_year": current_archive_year()}
    result = sync_registry_archives(scope=scope, user=user)
    cache.set(cache_key, True, ARCHIVE_SYNC_CACHE_SECONDS)
    return result


def archive_queryset(scope="all", *, year=None, reason="", status="", model_name="", search=""):
    queryset = RegistryArchiveRecord.objects.select_related("content_type").filter(excluded_from_active_totals=True)
    if scope and scope != "all":
        queryset = queryset.filter(scope=scope)
    if year:
        queryset = queryset.filter(Q(record_year=year) | Q(latest_renewal_year=year))
    if reason:
        queryset = queryset.filter(archive_reason=reason)
    if status:
        queryset = queryset.filter(archive_status=status)
    if model_name:
        queryset = queryset.filter(source_model=model_name)
    if search:
        queryset = queryset.filter(
            Q(source_label__icontains=search)
            | Q(registration_no__icontains=search)
            | Q(practitioner_number__icontains=search)
            | Q(cadre__icontains=search)
            | Q(facility__icontains=search)
            | Q(province__icontains=search)
        )
    return queryset.order_by("-archived_at", "source_label")


def archived_ids_for_model(model, *, scope=None):
    content_type = ContentType.objects.get_for_model(model)
    queryset = RegistryArchiveRecord.objects.filter(
        content_type=content_type,
        excluded_from_active_totals=True,
    ).exclude(archive_status="restored")
    if scope and scope != "all":
        queryset = queryset.filter(scope=scope)
    return queryset.values("object_id")


def active_professional_queryset(model, *, scope=None):
    queryset = model.objects.all()
    if hasattr(model, "is_active"):
        queryset = queryset.filter(is_active=True)
    return queryset.exclude(pk__in=Subquery(archived_ids_for_model(model, scope=scope)))


def active_professional_count(model, *, scope=None):
    return active_professional_queryset(model, scope=scope).count()


def active_import_record_queryset(queryset=None, *, scope=None):
    queryset = queryset if queryset is not None else import_records_for_scope(scope or "all")
    return queryset.exclude(pk__in=Subquery(archived_ids_for_model(PracticingLicenseRecord, scope=scope)))


def archive_filter_options(scope="all"):
    queryset = RegistryArchiveRecord.objects.filter(excluded_from_active_totals=True)
    if scope and scope != "all":
        queryset = queryset.filter(scope=scope)
    years = sorted(
        {
            value
            for row in queryset.values("record_year", "latest_renewal_year")
            for value in (row.get("record_year"), row.get("latest_renewal_year"))
            if value
        },
        reverse=True,
    )
    models = sorted(value for value in queryset.values_list("source_model", flat=True).distinct() if value)
    return {
        "years": years,
        "models": models,
        "reasons": RegistryArchiveRecord.REASON_CHOICES,
        "statuses": RegistryArchiveRecord.STATUS_CHOICES,
    }


def archive_summary(scope="all"):
    queryset = archive_queryset(scope)
    total = queryset.count()
    reason_counts = Counter()
    for row in queryset.values("archive_reason"):
        reason_counts[row["archive_reason"]] += 1
    year_counts = Counter()
    for row in queryset.values("record_year", "latest_renewal_year"):
        year = row.get("latest_renewal_year") or row.get("record_year")
        if year:
            year_counts[year] += 1
    return {
        "total": total,
        "by_reason": reason_counts,
        "top_years": year_counts.most_common(6),
    }


def archive_context_for_request(request, *, scope="all", limit=50):
    refresh_registry_archives(scope=scope, user=getattr(request, "user", None))
    raw_year = request.GET.get("archive_year", "").strip()
    try:
        year = int(raw_year) if raw_year else None
    except ValueError:
        year = None
    filters = {
        "year": year,
        "reason": request.GET.get("archive_reason", "").strip(),
        "status": request.GET.get("archive_status", "").strip(),
        "model_name": request.GET.get("archive_model", "").strip(),
        "search": request.GET.get("archive_q", "").strip(),
    }
    queryset = archive_queryset(scope, **filters)
    rows = list(queryset[:limit])
    summary = archive_summary(scope)
    return {
        "registry_archive_rows": rows,
        "registry_archive_total": summary["total"],
        "registry_archive_reason_counts": summary["by_reason"].most_common(),
        "registry_archive_top_years": summary["top_years"],
        "registry_archive_filters": filters,
        "registry_archive_filter_options": archive_filter_options(scope),
        "registry_archive_scope": scope,
    }


def archive_assistant_summary(scope="all"):
    refresh_registry_archives(scope=scope)
    summary = archive_summary(scope)
    recent = list(archive_queryset(scope)[:5])
    reason_labels = dict(RegistryArchiveRecord.REASON_CHOICES)
    bullets = [
        f"{reason_labels.get(reason, reason)}: {count}"
        for reason, count in summary["by_reason"].most_common(5)
    ]
    if summary["top_years"]:
        bullets.append("Top archive years: " + ", ".join(f"{year}: {count}" for year, count in summary["top_years"][:4]))
    if recent:
        bullets.extend(
            f"{row.source_label or row.source_reference} - {row.get_archive_reason_display()} ({row.latest_renewal_year or row.record_year or 'year not captured'})"
            for row in recent[:3]
        )
    try:
        archive_url = reverse("registry_archive")
    except NoReverseMatch:
        archive_url = ""
    return {
        "total": summary["total"],
        "bullets": bullets or ["No archived records currently match this scope."],
        "sources": [
            {
                "label": "Registry Archives",
                "detail": "Archive records created from age, lapsed-renewal, inactive, retired, and deceased-review filters.",
                "url": archive_url,
            }
        ],
    }
