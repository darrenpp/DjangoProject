from dataclasses import dataclass

from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.workforce.models import (
    Application,
    CommunityHealthWorker,
    HealthStudent,
    MedicalDoctor,
    Midwife,
    NurseAide,
    NursingProfessional,
)


APPLICANT_ROLES = {"nurse", "doctor", "chw", "graduand", "student", "nurse_aide"}

ROLE_MODELS = {
    "nurse": (NursingProfessional, Midwife),
    "doctor": (MedicalDoctor,),
    "chw": (CommunityHealthWorker,),
    "graduand": (HealthStudent,),
    "student": (HealthStudent,),
    "nurse_aide": (NurseAide,),
}

ROLE_FORM_CODES = {
    "graduand": "G3",
    "student": "G3",
    "nurse": "NC1",
    "doctor": "MD1",
    "chw": "CHW1",
    "nurse_aide": "NC2",
}

ROLE_FORM_TITLES = {
    "G3": "Graduate Vitae",
    "NC1": "Application for Provisional Licence",
    "NC2": "Application for Full Licence",
    "MD1": "Medical Registration",
    "CHW1": "Community Health Worker Registration",
}

ROLE_PATHWAYS = {
    "graduand": "local_nursing_graduate",
    "student": "local_nursing_graduate",
    "nurse": "other",
    "doctor": "medical_board",
    "chw": "medical_board",
    "nurse_aide": "other",
}

ROLE_NEXT_URLS = {
    "graduand": "public_graduand_register",
    "student": "public_graduand_register",
    "nurse": "public_nurse_provisional_register",
    "doctor": "public_doctor_register",
    "chw": "public_chw_register",
    "nurse_aide": "public_nurse_aide_register",
}


@dataclass
class ProfessionalLinkOutcome:
    status: str
    professional: object = None
    application: Application = None
    created_record: bool = False
    linked_existing: bool = False
    message: str = ""
    next_url_name: str = ""


def get_next_url_name_for_role(role):
    return ROLE_NEXT_URLS.get(role, "professional_dashboard")


def _norm(value):
    return " ".join(str(value or "").strip().lower().split())


def _identifier_for_role(role, cleaned_data, user=None):
    license_number = cleaned_data.get("license_number") or getattr(user, "license_number", None)
    registration_number = cleaned_data.get("registration_number") or getattr(user, "registration_number", None)
    if role in {"graduand", "student", "nurse_aide"}:
        return registration_number or license_number
    return license_number or registration_number


def _identifier_filter(identifier):
    return Q(registration_no__iexact=identifier) | Q(registration_number__iexact=identifier)


def _role_models(role):
    return ROLE_MODELS.get(role, ())


def _names_match(professional, cleaned_data):
    first_name = cleaned_data.get("first_name", "")
    middle_name = cleaned_data.get("middle_name", "")
    last_name = cleaned_data.get("last_name", "")
    if _norm(professional.first_name) != _norm(first_name):
        return False
    if _norm(professional.last_name) != _norm(last_name):
        return False
    record_middle = getattr(professional, "middle_name", "")
    if middle_name and record_middle and _norm(record_middle) != _norm(middle_name):
        return False
    return True


def _cadre_matches(professional, cleaned_data):
    requested = _norm(cleaned_data.get("cadre_name"))
    if not requested:
        return True
    cadre = getattr(professional, "cadre", None)
    if not cadre:
        return True
    values = [_norm(getattr(cadre, "name", "")), _norm(getattr(cadre, "category", ""))]
    return any(requested == value or requested in value or value in requested for value in values if value)


def find_matching_professional(role, cleaned_data, user=None):
    identifier = _identifier_for_role(role, cleaned_data, user)
    if not identifier:
        return None
    for model in _role_models(role):
        candidates = model.objects.filter(_identifier_filter(identifier)).select_related("cadre")
        for professional in candidates:
            if _names_match(professional, cleaned_data) and _cadre_matches(professional, cleaned_data):
                return professional
    return None


def has_identifier_candidate(role, identifier):
    if not identifier:
        return False
    for model in _role_models(role):
        if model.objects.filter(_identifier_filter(identifier)).exists():
            return True
    return False


def attach_professional_record(user, professional, *, status="linked", review_note=""):
    user.professional_content_type = ContentType.objects.get_for_model(professional) if professional else None
    user.professional_object_id = professional.pk if professional else None
    user.professional_record_status = status
    user.professional_link_review_note = review_note
    user.professional_linked_at = timezone.now() if status == "linked" and professional else None
    user.save(update_fields=[
        "professional_content_type",
        "professional_object_id",
        "professional_record_status",
        "professional_link_review_note",
        "professional_linked_at",
    ])


def _build_professional_record(user, cleaned_data):
    role = user.role
    identifier = _identifier_for_role(role, cleaned_data, user)
    registration_number = cleaned_data.get("registration_number") or None
    common = {
        "first_name": user.first_name,
        "middle_name": getattr(user, "middle_name", ""),
        "last_name": user.last_name,
        "registration_no": identifier or None,
        "registration_number": registration_number,
        "email": user.email,
        "primary_phone": user.phone,
        "applicant_type": cleaned_data.get("applicant_type", "national"),
        "passport_photo": user.passport_photo,
        "id_document_image": user.id_document_image,
    }

    if role in {"graduand", "student"}:
        return HealthStudent.objects.create(
            **common,
            program=cleaned_data.get("program", "General Nursing"),
            is_graduate=True,
        )
    if role == "nurse":
        return NursingProfessional.objects.create(
            **common,
            qualification_level=cleaned_data.get("qualification_level", ""),
        )
    if role == "doctor":
        return MedicalDoctor.objects.create(
            **common,
            specialty=cleaned_data.get("specialty", ""),
        )
    if role == "chw":
        return CommunityHealthWorker.objects.create(
            **common,
            community_id=cleaned_data.get("community_id", ""),
            training_level=cleaned_data.get("training_level", ""),
        )
    if role == "nurse_aide":
        return NurseAide.objects.create(
            **common,
            training_level=cleaned_data.get("training_level", ""),
        )
    return None


def create_pending_application(professional, role, reviewer_notes):
    if professional is None:
        return None
    form_code = ROLE_FORM_CODES.get(role, "NC1")
    return Application.objects.create(
        content_type=ContentType.objects.get_for_model(professional),
        object_id=professional.pk,
        form_code=form_code,
        form_title=ROLE_FORM_TITLES.get(form_code, ""),
        pathway=ROLE_PATHWAYS.get(role, "other"),
        status="pending",
        reviewer_notes=reviewer_notes,
    )


def link_or_create_professional_record(user, cleaned_data):
    role = user.role
    next_url_name = get_next_url_name_for_role(role)
    if role not in APPLICANT_ROLES:
        return ProfessionalLinkOutcome(status="unmatched", next_url_name=next_url_name)

    match = find_matching_professional(role, cleaned_data, user)
    if match:
        attach_professional_record(
            user,
            match,
            status="linked",
            review_note="Account matched to an existing registry record during public account registration.",
        )
        return ProfessionalLinkOutcome(
            status="linked",
            professional=match,
            linked_existing=True,
            message="Account created and linked to your existing professional record.",
            next_url_name="professional_dashboard",
        )

    identifier = _identifier_for_role(role, cleaned_data, user)
    if has_identifier_candidate(role, identifier):
        note = (
            "A registry record with this professional number exists, but the name or cadre did not match. "
            "Registrar review is required before the account can be linked."
        )
        attach_professional_record(user, None, status="pending_review", review_note=note)
        return ProfessionalLinkOutcome(
            status="pending_review",
            message=note,
            next_url_name=next_url_name,
        )

    try:
        with transaction.atomic():
            professional = _build_professional_record(user, cleaned_data)
            if professional is None:
                attach_professional_record(user, None, status="unmatched", review_note="")
                return ProfessionalLinkOutcome(status="unmatched", next_url_name=next_url_name)
            attach_professional_record(
                user,
                professional,
                status="pending_review",
                review_note="Applicant-created record is waiting for registrar review and approval.",
            )
            application = create_pending_application(
                professional,
                role,
                "Applicant-created record from public account registration. Registrar review required.",
            )
    except IntegrityError:
        note = (
            "This professional number could not be linked automatically. "
            "Registrar review is required before the account can be used for licensing."
        )
        attach_professional_record(user, None, status="pending_review", review_note=note)
        return ProfessionalLinkOutcome(status="pending_review", message=note, next_url_name=next_url_name)

    return ProfessionalLinkOutcome(
        status="pending_review",
        professional=professional,
        application=application,
        created_record=True,
        message="Account created. A professional record has been opened and is waiting for registrar review.",
        next_url_name=next_url_name,
    )


def link_authenticated_user_to_submission(user, submission):
    if not getattr(user, "is_authenticated", False) or getattr(user, "role", "") not in APPLICANT_ROLES:
        return None

    current_professional = getattr(user, "professional_record", None)
    if getattr(user, "professional_record_status", "") == "linked" and current_professional is not None:
        return current_professional

    professional = None
    if isinstance(submission, Application):
        professional = submission.professional
    else:
        professional = submission
    if professional is None:
        return None

    status = "linked" if getattr(submission, "status", "") == "approved" else "pending_review"
    if getattr(user, "professional_record_status", "") == "linked":
        status = "linked"
    attach_professional_record(
        user,
        professional,
        status=status,
        review_note="Account linked to the professional record submitted through the online forms.",
    )
    return professional


def mark_users_linked_for_professional(professional):
    if professional is None:
        return 0
    ct = ContentType.objects.get_for_model(professional)
    from .models import User

    return User.objects.filter(
        professional_content_type=ct,
        professional_object_id=professional.pk,
    ).exclude(
        professional_record_status="deceased",
    ).update(
        professional_record_status="linked",
        professional_linked_at=timezone.now(),
        professional_link_review_note="Professional record approved by registrar.",
    )


def mark_users_deceased_for_professional(professional):
    if professional is None:
        return 0
    ct = ContentType.objects.get_for_model(professional)
    from .models import User

    return User.objects.filter(
        professional_content_type=ct,
        professional_object_id=professional.pk,
    ).update(
        professional_record_status="deceased",
        professional_link_review_note="Professional record marked deceased by registrar-approved notification.",
    )
