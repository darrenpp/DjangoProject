from django.db.models import Q

from apps.workforce.models import (
    CommunityHealthWorker,
    HealthStudent,
    MedicalDoctor,
    Midwife,
    NurseAide,
    NursingProfessional,
    PracticingLicenseRecord,
)

from ..constants import OFFICE_SCOPE_MEDICAL, OFFICE_SCOPE_NURSING


NURSING_MODELS = (NursingProfessional, Midwife, NurseAide, HealthStudent)
MEDICAL_MODELS = (MedicalDoctor, CommunityHealthWorker)


def _clean(value):
    return str(value or "").strip()


def _model_queryset(model, payload):
    query = Q()
    registration_number = _clean(payload.get("registration_number") or payload.get("registration_no"))
    first_name = _clean(payload.get("first_name"))
    surname = _clean(payload.get("surname") or payload.get("last_name"))
    email = _clean(payload.get("email"))
    phone = _clean(payload.get("phone") or payload.get("primary_phone"))
    if registration_number:
        query |= Q(registration_no__iexact=registration_number) | Q(registration_number__iexact=registration_number)
    if first_name and surname:
        query |= Q(first_name__iexact=first_name, last_name__iexact=surname)
    if email:
        query |= Q(email__iexact=email)
    if phone:
        query |= Q(primary_phone=phone)
    return model.objects.filter(query) if query else model.objects.none()


def _score_record(record, payload):
    matched = []
    score = 0.0
    registration_number = _clean(payload.get("registration_number") or payload.get("registration_no"))
    if registration_number and registration_number.lower() in {
        _clean(getattr(record, "registration_no", "")).lower(),
        _clean(getattr(record, "registration_number", "")).lower(),
    }:
        matched.append("registration_number")
        score = max(score, 0.95)
    first_name = _clean(payload.get("first_name"))
    surname = _clean(payload.get("surname") or payload.get("last_name"))
    if first_name and surname and first_name.lower() == _clean(record.first_name).lower() and surname.lower() == _clean(record.last_name).lower():
        matched.append("name")
        score = max(score, 0.72)
    if payload.get("date_of_birth") and str(getattr(record, "date_of_birth", "") or "") == str(payload.get("date_of_birth")):
        matched.append("date_of_birth")
        score = max(score, 0.88 if "name" in matched else 0.65)
    email = _clean(payload.get("email"))
    if email and email.lower() == _clean(getattr(record, "email", "")).lower():
        matched.append("email")
        score = max(score, 0.9)
    phone = _clean(payload.get("phone") or payload.get("primary_phone"))
    if phone and phone == _clean(getattr(record, "primary_phone", "")):
        matched.append("phone")
        score = max(score, 0.65)
    return score, matched


def _safe_name(record):
    return " ".join(part for part in [getattr(record, "first_name", ""), getattr(record, "last_name", "")] if part).strip()


def duplicate_check(office_scope, form_code, payload):
    models = MEDICAL_MODELS if office_scope == OFFICE_SCOPE_MEDICAL else NURSING_MODELS
    matches = []
    high_score = 0.0
    for model in models:
        for record in _model_queryset(model, payload).order_by("-updated_at")[:10]:
            score, matched = _score_record(record, payload)
            if not matched:
                continue
            high_score = max(high_score, score)
            matches.append({
                "record_type": model.__name__.lower(),
                "record_id": record.pk,
                "display_name": _safe_name(record),
                "score": round(score, 2),
                "matched_fields": matched,
            })

    registration_number = _clean(payload.get("registration_number") or payload.get("registration_no"))
    practitioner_number = _clean(payload.get("practitioner_number"))
    licence_number = _clean(payload.get("licence_number") or payload.get("license_number"))
    imported_query = Q()
    if registration_number:
        imported_query |= Q(registration_no__iexact=registration_number)
    if practitioner_number:
        imported_query |= Q(practitioner_number__iexact=practitioner_number)
    if licence_number:
        imported_query |= Q(reference_number__iexact=licence_number)
    if imported_query:
        imported = PracticingLicenseRecord.objects.filter(imported_query)
        if office_scope == OFFICE_SCOPE_NURSING:
            imported = imported.exclude(target_model__in=("medicaldoctor", "communityhealthworker"))
        elif office_scope == OFFICE_SCOPE_MEDICAL:
            imported = imported.filter(target_model__in=("medicaldoctor", "communityhealthworker"))
        for record in imported.order_by("-record_year", "-id")[:10]:
            matched = []
            if registration_number and registration_number.lower() == _clean(record.registration_no).lower():
                matched.append("registration_number")
            if practitioner_number and practitioner_number.lower() == _clean(record.practitioner_number).lower():
                matched.append("practitioner_number")
            if licence_number and licence_number.lower() == _clean(record.reference_number).lower():
                matched.append("licence_number")
            score = 0.91 if matched else 0.0
            high_score = max(high_score, score)
            matches.append({
                "record_type": "practicing_license_record",
                "record_id": record.pk,
                "display_name": record.full_name,
                "score": round(score, 2),
                "matched_fields": matched,
            })

    matches = sorted(matches, key=lambda item: item["score"], reverse=True)[:20]
    if high_score >= 0.85:
        risk = "HIGH"
    elif high_score >= 0.65:
        risk = "MEDIUM"
    else:
        risk = "LOW"
    return {
        "duplicate_risk": risk,
        "matches": matches,
        "must_review": bool(matches),
        "form_code": form_code,
    }
