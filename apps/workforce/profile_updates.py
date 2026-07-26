"""Governed professional-profile update requests and regulatory passports.

This module keeps self-service useful without letting an applicant edit the
official register directly.  A request is staged first and an authorised
registrar decision is required before it is promoted into the registry.
"""

from __future__ import annotations

from datetime import date

from django import forms
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from apps.dashboard.access import professional_domain

from .models import (
    CPDRecord,
    ClinicalPrivilege,
    CredentialVerification,
    EmploymentRecord,
    Facility,
    MedicalDoctor,
    ProfessionalProfileUpdateRequest,
    Qualification,
)


PROFILE_UPDATE_LABELS = {
    "contact": "Contact details",
    "workplace": "Current workplace",
    "qualification": "Qualification or specialist credential",
    "cpd": "CPD activity",
    "clinical_privilege": "Clinical privilege",
}


class ProfessionalProfileUpdateRequestForm(forms.Form):
    """One deliberately small, auditable request form for linked professionals."""

    update_type = forms.ChoiceField(
        choices=ProfessionalProfileUpdateRequest.UPDATE_TYPE_CHOICES,
        label="What would you like reviewed?",
    )
    primary_phone = forms.CharField(max_length=20, required=False, label="Phone")
    email = forms.EmailField(required=False, label="Professional email")
    province = forms.CharField(max_length=100, required=False)

    employer_name = forms.CharField(max_length=255, required=False)
    workplace_name = forms.CharField(max_length=255, required=False, label="Current workplace / facility")
    position_title = forms.CharField(max_length=255, required=False)
    employment_sector = forms.ChoiceField(
        choices=[("", "Select sector"), *EmploymentRecord.EMPLOYMENT_SECTOR_CHOICES],
        required=False,
    )

    credential_type = forms.ChoiceField(
        choices=CredentialVerification.CREDENTIAL_TYPE_CHOICES,
        required=False,
        label="Credential type",
    )
    qualification_name = forms.CharField(max_length=255, required=False, label="Qualification / credential")
    institution_name = forms.CharField(max_length=255, required=False, label="Institution")
    specialty = forms.CharField(max_length=150, required=False, label="Specialty (Medical Board only)")

    cpd_training_type = forms.CharField(max_length=150, required=False, label="CPD activity")
    cpd_provider = forms.CharField(max_length=200, required=False, label="CPD provider")
    cpd_start_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    cpd_hours = forms.FloatField(required=False, min_value=0, label="CPD hours / credits")

    privilege_name = forms.CharField(max_length=255, required=False, label="Requested clinical privilege")
    privilege_facility = forms.CharField(max_length=255, required=False, label="Practice facility")
    privilege_expiry_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))

    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}), required=False, label="Explanation for the reviewer")
    evidence = forms.FileField(required=False, label="Supporting evidence")

    def clean(self):
        cleaned = super().clean()
        update_type = cleaned.get("update_type")

        if update_type == "contact" and not any(cleaned.get(name) for name in ("primary_phone", "email", "province")):
            raise forms.ValidationError("Provide at least one contact or location value for review.")
        if update_type == "workplace" and not any(cleaned.get(name) for name in ("employer_name", "workplace_name", "position_title")):
            raise forms.ValidationError("Provide a workplace, employer, or position for review.")
        if update_type == "qualification" and not cleaned.get("qualification_name"):
            self.add_error("qualification_name", "Enter the qualification or credential to be verified.")
        if update_type == "cpd":
            if not cleaned.get("cpd_training_type"):
                self.add_error("cpd_training_type", "Enter the CPD activity.")
            if not cleaned.get("cpd_start_date"):
                self.add_error("cpd_start_date", "Enter the CPD activity date.")
        if update_type == "clinical_privilege" and not cleaned.get("privilege_name"):
            self.add_error("privilege_name", "Enter the clinical privilege requested.")
        return cleaned

    def proposed_changes(self) -> dict:
        """Return only non-empty, defined fields; never persist form internals."""

        keys = {
            "contact": ("primary_phone", "email", "province"),
            "workplace": ("employer_name", "workplace_name", "position_title", "province", "employment_sector"),
            "qualification": ("credential_type", "qualification_name", "institution_name", "specialty"),
            "cpd": ("cpd_training_type", "cpd_provider", "cpd_start_date", "cpd_hours"),
            "clinical_privilege": ("privilege_name", "privilege_facility", "privilege_expiry_date"),
        }
        values = {}
        for key in keys.get(self.cleaned_data["update_type"], ()):  # pragma: no branch - choices constrain type
            value = self.cleaned_data.get(key)
            if value not in (None, ""):
                values[key] = value.isoformat() if hasattr(value, "isoformat") else value
        return values


def _relation_kwargs(professional):
    return {
        "content_type": ContentType.objects.get_for_model(professional, for_concrete_model=False),
        "object_id": professional.pk,
    }


def profile_update_requests_for(professional):
    if professional is None or not getattr(professional, "pk", None):
        return ProfessionalProfileUpdateRequest.objects.none()
    return ProfessionalProfileUpdateRequest.objects.filter(**_relation_kwargs(professional))


def current_employment_for(professional):
    if professional is None or not getattr(professional, "pk", None):
        return None
    return EmploymentRecord.objects.filter(
        **_relation_kwargs(professional),
        is_current=True,
    ).select_related("facility").order_by("-start_date", "-created_at", "-pk").first()


def build_professional_identity_context(professional):
    """Build a safe, self-service regulatory passport without sensitive fields."""

    if professional is None or not getattr(professional, "pk", None):
        return {
            "professional_identity": None,
            "professional_profile_update_requests": ProfessionalProfileUpdateRequest.objects.none(),
        }

    relation = _relation_kwargs(professional)
    domain = professional_domain(professional)
    qualifications = Qualification.objects.filter(**relation).order_by("-date_completed", "-completion_year", "qualification_name")
    credentials = CredentialVerification.objects.filter(**relation).order_by("-updated_at", "credential_title")
    privileges = ClinicalPrivilege.objects.filter(**relation).select_related("facility").order_by("privilege_name")
    cpd_records = CPDRecord.objects.filter(**relation)
    employment = current_employment_for(professional)

    specialty = getattr(professional, "specialty", "") if domain == "medical" else ""
    qualification_label = getattr(professional, "qualification_level", "") or (qualifications.first().qualification_name if qualifications.exists() else "")
    workplace_label = ""
    if employment:
        workplace_label = employment.facility.name if employment.facility else (
            employment.place_of_work or employment.facility_name_raw or employment.employer_name
        )

    completeness_checks = [
        ("Registration identifier", bool(getattr(professional, "registration_no", "") or getattr(professional, "registration_number", ""))),
        ("Professional contact", bool(getattr(professional, "primary_phone", "") or getattr(professional, "email", ""))),
        ("Province", bool(getattr(professional, "province", ""))),
        ("Current workplace", bool(workplace_label)),
        ("Qualification", bool(qualification_label)),
        ("Verified evidence or CPD", credentials.filter(status="verified").exists() or cpd_records.exists()),
    ]
    completed = sum(1 for _label, complete in completeness_checks if complete)
    profile_completeness = round((completed / len(completeness_checks)) * 100) if completeness_checks else 0
    missing_items = [label for label, complete in completeness_checks if not complete]

    issue_date = getattr(professional, "date_issued", None)
    years_practicing = None
    if issue_date:
        today = timezone.localdate()
        years_practicing = max(0, today.year - issue_date.year - ((today.month, today.day) < (issue_date.month, issue_date.day)))

    identity = {
        "domain": domain,
        "title": "Medical Professional Profile" if domain == "medical" else "Nursing Professional Profile",
        "full_name": str(professional),
        "registration_number": getattr(professional, "registration_no", "") or getattr(professional, "registration_number", ""),
        "status": "Active practitioner" if getattr(professional, "is_active", False) else "Record requires review",
        "status_theme": "success" if getattr(professional, "is_active", False) else "warning",
        "specialty_or_category": specialty or getattr(getattr(professional, "cadre", None), "name", "") or "Registered professional",
        "qualification": qualification_label,
        "years_practicing": years_practicing,
        "workplace": workplace_label,
        "province": getattr(professional, "province", ""),
        "cpd_credits": round(sum(record.hours_credits or 0 for record in cpd_records), 1),
        "profile_completeness": profile_completeness,
        "missing_items": missing_items,
        "verified_credential_count": credentials.filter(status="verified").count(),
        "credential_rows": list(credentials[:4]),
        "clinical_privileges": list(privileges.filter(status__in=["approved", "conditional"])[:5]),
        "last_updated": getattr(professional, "updated_at", None),
    }
    return {
        "professional_identity": identity,
        "professional_profile_update_requests": profile_update_requests_for(professional)[:8],
    }


def create_profile_update_request(*, professional, requested_by, form):
    if not form.is_valid():
        raise ValueError("A valid update request form is required.")
    domain = professional_domain(professional)
    if domain not in {"medical", "nursing"}:
        raise ValueError("This professional record is not managed by a regulatory office.")
    if form.cleaned_data["update_type"] == "clinical_privilege" and domain != "medical":
        raise ValueError("Clinical privileges are available only in the Medical Board workspace.")
    return ProfessionalProfileUpdateRequest.objects.create(
        **_relation_kwargs(professional),
        office_scope=domain,
        update_type=form.cleaned_data["update_type"],
        proposed_changes=form.proposed_changes(),
        reason=form.cleaned_data.get("reason", ""),
        evidence=form.cleaned_data.get("evidence"),
        requested_by=requested_by,
    )


def _date_value(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _apply_profile_update(request_obj, actor):
    professional = request_obj.professional
    if professional is None:
        raise ValueError("The linked professional record no longer exists.")
    changes = request_obj.proposed_changes or {}
    relation = _relation_kwargs(professional)

    if request_obj.update_type == "contact":
        fields = []
        for field in ("primary_phone", "email", "province"):
            if field in changes:
                setattr(professional, field, changes[field])
                fields.append(field)
        if fields:
            professional.save(update_fields=[*fields, "updated_at"])

    elif request_obj.update_type == "workplace":
        employment = current_employment_for(professional)
        if employment is None:
            employment = EmploymentRecord(**relation, is_current=True, review_status="promoted")
        employment.employer_name = changes.get("employer_name", employment.employer_name)
        employment.place_of_work = changes.get("workplace_name", employment.place_of_work)
        employment.facility_name_raw = changes.get("workplace_name", employment.facility_name_raw)
        employment.position_title = changes.get("position_title", employment.position_title)
        employment.province = changes.get("province", employment.province)
        employment.employment_sector = changes.get("employment_sector", employment.employment_sector)
        employment.employment_status = employment.employment_status or "employed"
        employment.review_status = "promoted"
        employment.source_type = "professional_profile_update"
        employment.save()
        if changes.get("province"):
            professional.province = changes["province"]
            professional.save(update_fields=["province", "updated_at"])

    elif request_obj.update_type == "qualification":
        qualification_name = changes.get("qualification_name", "")
        Qualification.objects.create(
            **relation,
            qualification_name=qualification_name,
            institution_name=changes.get("institution_name", ""),
            certificate_attached=bool(request_obj.evidence),
        )
        CredentialVerification.objects.create(
            **relation,
            credential_type=changes.get("credential_type") or "qualification",
            credential_title=qualification_name,
            issuing_institution=changes.get("institution_name", ""),
            status="verified",
            evidence_summary=("Supporting evidence attached to approved profile update." if request_obj.evidence else "Verified by authorised profile-update decision."),
            verified_by=actor,
            verified_at=timezone.now(),
        )
        if isinstance(professional, MedicalDoctor) and changes.get("specialty"):
            professional.specialty = changes["specialty"]
            professional.save(update_fields=["specialty", "updated_at"])

    elif request_obj.update_type == "cpd":
        CPDRecord.objects.create(
            **relation,
            training_type=changes.get("cpd_training_type", "CPD activity"),
            provider=changes.get("cpd_provider", ""),
            start_date=_date_value(changes.get("cpd_start_date")) or timezone.localdate(),
            hours_credits=changes.get("cpd_hours") or 0,
        )

    elif request_obj.update_type == "clinical_privilege":
        if not isinstance(professional, MedicalDoctor):
            raise ValueError("Clinical privileges can only be approved for Medical Doctor records.")
        facility_name = (changes.get("privilege_facility") or "").strip()
        facility = Facility.objects.filter(name__iexact=facility_name).first() if facility_name else None
        ClinicalPrivilege.objects.create(
            **relation,
            privilege_name=changes.get("privilege_name", "Clinical privilege"),
            status="approved",
            facility=facility,
            expiry_date=_date_value(changes.get("privilege_expiry_date")),
            evidence_summary=("Supporting evidence attached to approved profile update." if request_obj.evidence else "Approved through Medical Board profile-update decision."),
            approved_by=actor,
            approved_at=timezone.now(),
        )


def review_profile_update_request(*, request_id, actor, approved, reviewer_note=""):
    """Make one auditable decision and promote data only after approval."""

    with transaction.atomic():
        request_obj = ProfessionalProfileUpdateRequest.objects.select_for_update().get(pk=request_id)
        if request_obj.status not in {"submitted", "under_review"}:
            raise ValueError("This profile-update request has already been decided.")

        request_obj.reviewer = actor
        request_obj.reviewer_note = (reviewer_note or "").strip()
        request_obj.reviewed_at = timezone.now()
        if approved:
            _apply_profile_update(request_obj, actor)
            request_obj.status = "approved"
            request_obj.applied_at = timezone.now()
        else:
            request_obj.status = "rejected"
        request_obj.save(update_fields=["reviewer", "reviewer_note", "reviewed_at", "status", "applied_at"])
    return request_obj
