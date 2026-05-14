from django import forms
from django.core.paginator import Paginator
from django.forms import modelform_factory
from django.http import Http404
from django.db.models import Q, Subquery
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.contenttypes.models import ContentType
from django.views import View
from django.views.generic import TemplateView

from .record_registry import MODEL_REGISTRY
from apps.dashboard.access import (
    MEDICAL_BOARD_FORM_CODES,
    MEDICAL_BOARD_PROFESSIONAL_MODELS,
    NURSING_COUNCIL_PROFESSIONAL_MODELS,
    is_data_quality_reviewer,
    is_medical_board_staff,
    is_nursing_council_staff,
)
from apps.workforce.forms import MEDICAL_BOARD_SPECIALIST_CHOICES
from apps.workforce.models import Cadre, ProfessionalDocument, ProfessionalPhoto, PracticingLicenseRecord

MEDICAL_SPECIALIST_SLUG = "medicalspecialist"
MEDICAL_BOARD_RECORD_SLUGS = set(MEDICAL_BOARD_PROFESSIONAL_MODELS) | {MEDICAL_SPECIALIST_SLUG}
NURSING_COUNCIL_RECORD_SLUGS = set(NURSING_COUNCIL_PROFESSIONAL_MODELS) | {"graduand"}
MEDICAL_RECEIPT_ROLES = {"doctor", "chw"}
NURSING_RECEIPT_ROLES = {"nurse", "nurse_aide", "graduand", "student"}
DOMAIN_SCOPED_CONTENT_MODELS = {
    "ProfessionalDocument",
    "ProfessionalPhoto",
    "CPDRecord",
    "CompetencyAssessment",
    "DuplicateReviewQueue",
    "DeceasedRecord",
}
SPECIALIST_VALUES = {value for value, _label in MEDICAL_BOARD_SPECIALIST_CHOICES}
SPECIALIST_KEYWORDS = (
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
GENERIC_SPECIALTY_LABELS = {
    "",
    "general practice",
    "medical board practitioner",
    "medical doctor",
    "overseas medical board practitioner",
}
MODEL_CADRE_CATEGORIES = {
    "MedicalDoctor": {"medical"},
    "CommunityHealthWorker": {"chw"},
    "NursingProfessional": {"nursing"},
    "Midwife": {"midwifery"},
    "NurseAide": {"nursing"},
    "HealthStudent": {"nursing", "midwifery"},
}
DEFAULT_CADRES = {
    "MedicalDoctor": (("Medical Doctor", "medical"), ("Medical Specialist", "medical")),
    "CommunityHealthWorker": (("Community Health Worker", "chw"),),
    "NursingProfessional": (("Nursing", "nursing"),),
    "Midwife": (("Midwifery", "midwifery"),),
    "NurseAide": (("Nurse Aide", "nursing"),),
    "HealthStudent": (("Nursing Graduand", "nursing"), ("Midwifery Graduand", "midwifery")),
}
MEDICAL_IMPORT_TARGET_MODELS = {"medicaldoctor", "communityhealthworker", "other"}
NURSING_IMPORT_TARGET_MODELS = {"nursingprofessional", "midwife", "nurseaide", "healthstudent"}
INTERNAL_RECORD_SLUGS = {
    "user",
    "notification",
    "ocrdocument",
    "report",
    "workforcesnapshot",
}
MEDICAL_RECORD_HUB_SLUGS = {
    "application",
    "cadre",
    "communityhealthworker",
    "cpdrecord",
    "deceasedrecord",
    "documenttype",
    "duplicatereviewqueue",
    "facility",
    "location",
    "medicaldoctor",
    MEDICAL_SPECIALIST_SLUG,
    "practicinglicenserecord",
    "professionaldocument",
    "professionalphoto",
    "receipt",
    "traininginstitution",
}
NURSING_RECORD_HUB_SLUGS = {
    "application",
    "cadre",
    "competencyassessment",
    "cpdrecord",
    "deceasedrecord",
    "documenttype",
    "duplicatereviewqueue",
    "facility",
    "graduand",
    "healthstudent",
    "location",
    "midwife",
    "nurseaide",
    "nursingprofessional",
    "practicinglicenserecord",
    "professionaldocument",
    "professionalphoto",
    "receipt",
    "traininginstitution",
}


def resolve_model(model_slug):
    model = MODEL_REGISTRY.get(model_slug)
    if not model:
        raise Http404("Unknown model.")
    return model


def build_form_class(model):
    fields = [
        field.name
        for field in model._meta.fields
        if field.editable and not field.auto_created and field.name != "id"
    ]
    form_class = modelform_factory(model, fields=fields)

    class StyledForm(form_class):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            for field_name, field in self.fields.items():
                css_class = "form-control"
                if isinstance(field.widget, forms.CheckboxInput):
                    css_class = "form-check-input"
                if isinstance(field.widget, forms.FileInput):
                    css_class = "form-control-file"
                existing = field.widget.attrs.get("class", "")
                field.widget.attrs["class"] = f"{existing} {css_class}".strip()
                if isinstance(field, forms.ModelChoiceField):
                    field.queryset = field.queryset.only("id")
                    if field_name == "application":
                        field.label_from_instance = lambda obj: f"{getattr(obj, 'form_code', 'Application')} #{obj.pk}"
                    elif field_name == "user":
                        field.label_from_instance = lambda obj: getattr(obj, "username", str(obj))
                    elif field_name == "content_type":
                        field.label_from_instance = lambda obj: f"{obj.app_label}.{obj.model}"

    return StyledForm


def _canonical_model_slug(model_slug, model):
    if model.__name__ == "HealthStudent":
        return "graduand"
    return model_slug


def _model_label(model_slug, model, *, plural=False):
    if model_slug == MEDICAL_SPECIALIST_SLUG:
        return "Medical Specialists" if plural else "Medical Specialist"
    return (model._meta.verbose_name_plural if plural else model._meta.verbose_name).title()


def _specialist_record_filter():
    query = Q()
    for keyword in SPECIALIST_KEYWORDS:
        query |= Q(qualification_name__icontains=keyword)
        query |= Q(category__icontains=keyword)
        query |= Q(source_sheet_name__icontains=keyword)
    return query


def _specialist_profile_filter():
    query = Q(specialty__in=SPECIALIST_VALUES)
    for keyword in SPECIALIST_KEYWORDS:
        query |= Q(specialty__icontains=keyword)
    for label in GENERIC_SPECIALTY_LABELS:
        if label:
            query &= ~Q(specialty__iexact=label)
    specialist_registration_numbers = PracticingLicenseRecord.objects.filter(
        batch__source_kind="medical_board_workbook",
        target_model="medicaldoctor",
    ).filter(_specialist_record_filter()).exclude(registration_no="").values("registration_no")
    return query | Q(registration_no__in=Subquery(specialist_registration_numbers))


def _scope_specialist_queryset(queryset):
    return queryset.filter(_specialist_profile_filter()).distinct()


def _scope_document_type_queryset(queryset, scope):
    if scope not in {"medical", "nursing"}:
        return queryset
    medical_filter = (
        Q(description__icontains="Medical Board")
        | Q(name__icontains="Medical Board")
        | Q(documentrequirement__pathway__regulatory_body__name__icontains="Medical Board")
        | Q(documentrequirement__pathway__regulatory_body__code__icontains="medical")
    )
    nursing_filter = (
        Q(description__icontains="Nursing Council")
        | Q(name__icontains="Nursing Council")
        | Q(documentrequirement__pathway__regulatory_body__name__icontains="Nursing Council")
        | Q(documentrequirement__pathway__regulatory_body__code__icontains="nursing")
    )
    if scope == "medical":
        return queryset.filter(medical_filter).exclude(nursing_filter).distinct()
    return queryset.filter(nursing_filter).exclude(medical_filter).distinct()


def _scope_practicing_license_queryset(queryset, scope):
    if scope == "medical":
        return queryset.filter(
            batch__source_kind="medical_board_workbook",
            target_model__in=MEDICAL_IMPORT_TARGET_MODELS,
        )
    if scope == "nursing":
        return queryset.filter(
            target_model__in=NURSING_IMPORT_TARGET_MODELS,
        ).exclude(batch__source_kind="medical_board_workbook")
    return queryset


def _records_scope_for_user(user):
    if not user.is_authenticated:
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


def _record_hub_title(scope):
    if scope == "medical":
        return "Medical Board Records Hub"
    if scope == "nursing":
        return "Nursing Council Records Hub"
    return "All Records Hub"


def _model_allowed_for_scope(model_slug, model, scope):
    if scope in {"", "all"}:
        return bool(scope)
    slug = _canonical_model_slug(model_slug, model)
    if scope == "medical":
        return slug not in NURSING_COUNCIL_RECORD_SLUGS
    if scope == "nursing":
        return slug not in MEDICAL_BOARD_RECORD_SLUGS
    return False


def _model_visible_for_scope(model_slug, model, scope):
    if not _model_allowed_for_scope(model_slug, model, scope):
        return False
    slug = _canonical_model_slug(model_slug, model)
    if scope == "medical":
        return slug in MEDICAL_RECORD_HUB_SLUGS
    if scope == "nursing":
        return slug in NURSING_RECORD_HUB_SLUGS
    if scope == "all":
        return slug not in INTERNAL_RECORD_SLUGS or model_slug == "user"
    return False


def resolve_accessible_model(model_slug, user):
    model = resolve_model(model_slug)
    scope = _records_scope_for_user(user)
    if not _model_visible_for_scope(model_slug, model, scope):
        raise Http404("Unknown model.")
    return model


def _content_type_models_for_scope(scope):
    if scope == "medical":
        return MEDICAL_BOARD_RECORD_SLUGS
    if scope == "nursing":
        return NURSING_COUNCIL_RECORD_SLUGS
    return None


def _scope_application_queryset(queryset, scope):
    if scope == "medical":
        return queryset.filter(form_code__in=MEDICAL_BOARD_FORM_CODES)
    if scope == "nursing":
        return queryset.exclude(form_code__in=MEDICAL_BOARD_FORM_CODES)
    return queryset


def _medical_receipt_filter():
    unlinked = Q(application__isnull=True)
    return (
        Q(application__form_code__in=MEDICAL_BOARD_FORM_CODES)
        | (unlinked & Q(user__role__in=MEDICAL_RECEIPT_ROLES))
        | (unlinked & Q(user__department__icontains="medical"))
        | (unlinked & Q(user__username__icontains="medical"))
        | (unlinked & Q(user__username__icontains="doctor"))
        | (unlinked & Q(user__username__icontains="chw"))
    )


def _nursing_receipt_filter():
    unlinked = Q(application__isnull=True)
    linked_nursing = Q(application__isnull=False) & ~Q(application__form_code__in=MEDICAL_BOARD_FORM_CODES)
    return (
        linked_nursing
        | (unlinked & Q(user__isnull=True))
        | (unlinked & Q(user__role__in=NURSING_RECEIPT_ROLES))
        | (unlinked & Q(user__department__icontains="nursing"))
        | (unlinked & Q(user__department__icontains="nurse"))
        | (unlinked & Q(user__username__icontains="nursing"))
        | (unlinked & Q(user__username__icontains="nurse"))
    )


def _scope_receipt_queryset(queryset, user, scope):
    current_user_receipts = Q(application__isnull=True, user=user)
    if scope == "medical":
        return queryset.filter(_medical_receipt_filter() | current_user_receipts)
    if scope == "nursing":
        return queryset.filter(_nursing_receipt_filter() | current_user_receipts)
    return queryset


def _scope_user_queryset(queryset, user, scope):
    current_user = Q(pk=user.pk)
    if scope == "medical":
        return queryset.filter(
            Q(role__in=MEDICAL_RECEIPT_ROLES)
            | Q(department__icontains="medical")
            | Q(username__icontains="medical")
            | Q(username__icontains="doctor")
            | Q(username__icontains="chw")
            | current_user
        )
    if scope == "nursing":
        return queryset.filter(
            Q(role__in=NURSING_RECEIPT_ROLES)
            | Q(department__icontains="nursing")
            | Q(department__icontains="nurse")
            | Q(username__icontains="nursing")
            | Q(username__icontains="nurse")
            | current_user
        )
    return queryset


def _scope_form_code_choices(form, scope):
    form_code_field = form.fields.get("form_code")
    if not form_code_field or scope not in {"medical", "nursing"}:
        return

    choices = []
    for value, label in form_code_field.choices:
        code = str(value or "").upper()
        if not code:
            choices.append((value, label))
        elif scope == "medical" and code in MEDICAL_BOARD_FORM_CODES:
            choices.append((value, label))
        elif scope == "nursing" and code not in MEDICAL_BOARD_FORM_CODES:
            choices.append((value, label))
    form_code_field.choices = choices


def _scope_content_type_queryset(queryset, scope):
    content_type_models = _content_type_models_for_scope(scope)
    if content_type_models is None:
        return queryset
    return queryset.filter(content_type__model__in=content_type_models)


def _ensure_model_cadres(model_name):
    for name, category in DEFAULT_CADRES.get(model_name, ()):
        Cadre.objects.get_or_create(
            name=name,
            defaults={"category": category, "description": f"{name} records"},
        )


def _scope_cadre_choices(form, model):
    cadre_field = form.fields.get("cadre")
    categories = MODEL_CADRE_CATEGORIES.get(model.__name__)
    if not cadre_field or not categories:
        return
    _ensure_model_cadres(model.__name__)
    cadre_field.queryset = Cadre.objects.filter(category__in=categories).order_by("name")


def _scope_specialty_choices(form, model):
    if model.__name__ != "MedicalDoctor" or "specialty" not in form.fields:
        return
    field = form.fields["specialty"]
    choices = [("", "---------")] + list(MEDICAL_BOARD_SPECIALIST_CHOICES)
    choice_values = {str(value) for value, _label in choices}
    current_value = str(getattr(form.instance, "specialty", "") or form.initial.get("specialty", "") or "")
    if current_value and current_value not in choice_values:
        choices.append((current_value, f"{current_value} (current value)"))
    field.choices = choices
    field.widget = forms.Select(choices=choices, attrs=field.widget.attrs)
    field.required = False
    field.label = "Specialty"


def _scope_practicing_license_form(form, model, scope):
    if model.__name__ != "PracticingLicenseRecord":
        return
    batch_field = form.fields.get("batch")
    if batch_field and scope == "medical":
        batch_field.queryset = batch_field.queryset.filter(source_kind="medical_board_workbook")
    elif batch_field and scope == "nursing":
        batch_field.queryset = batch_field.queryset.exclude(source_kind="medical_board_workbook")

    target_model_field = form.fields.get("target_model")
    if not target_model_field or scope not in {"medical", "nursing"}:
        return
    allowed_targets = MEDICAL_IMPORT_TARGET_MODELS if scope == "medical" else NURSING_IMPORT_TARGET_MODELS
    target_model_field.choices = [
        (value, label)
        for value, label in target_model_field.choices
        if not value or value in allowed_targets
    ]


def scoped_record_queryset(model, user, model_slug=None):
    scope = _records_scope_for_user(user)
    queryset = model.objects.all()

    if model_slug == MEDICAL_SPECIALIST_SLUG:
        queryset = _scope_specialist_queryset(queryset)
    if model.__name__ == "Application":
        return _scope_application_queryset(queryset, scope)
    if model.__name__ == "Receipt":
        return _scope_receipt_queryset(queryset, user, scope)
    if model.__name__ == "DocumentType":
        return _scope_document_type_queryset(queryset, scope)
    if model.__name__ == "PracticingLicenseRecord":
        return _scope_practicing_license_queryset(queryset, scope)
    if model.__name__ in DOMAIN_SCOPED_CONTENT_MODELS and any(
        field.name == "content_type" for field in model._meta.fields
    ):
        return _scope_content_type_queryset(queryset, scope)
    return queryset


def _scope_record_form(form, user):
    scope = _records_scope_for_user(user)
    model = getattr(getattr(form, "_meta", None), "model", None)
    _scope_form_code_choices(form, scope)
    if model:
        _scope_cadre_choices(form, model)
        _scope_specialty_choices(form, model)
        _scope_practicing_license_form(form, model, scope)

    user_field = form.fields.get("user")
    if user_field:
        user_field.queryset = _scope_user_queryset(user_field.queryset, user, scope)

    application_field = form.fields.get("application")
    if application_field:
        application_field.queryset = _scope_application_queryset(application_field.queryset, scope)

    content_type_field = form.fields.get("content_type")
    content_type_models = _content_type_models_for_scope(scope)
    if content_type_field and content_type_models is not None:
        content_type_field.queryset = content_type_field.queryset.filter(model__in=content_type_models)
    return form


def apply_search(queryset, model, search_term):
    if not search_term:
        return queryset

    search_fields = [
        field.name
        for field in model._meta.fields
        if field.get_internal_type() in {"CharField", "TextField", "EmailField", "SlugField"}
    ]
    if not search_fields:
        return queryset

    filters = Q()
    for field_name in search_fields:
        filters |= Q(**{f"{field_name}__icontains": search_term})
    return queryset.filter(filters)


def _can_access_records(user):
    if not user.is_authenticated:
        return False
    if user.role in {"admin", "registrar"}:
        return True
    if user.role == "reviewer":
        return is_data_quality_reviewer(user)
    return False


def _can_create_records(user):
    return _can_access_records(user)


def _can_delete_records(user):
    return _is_system_admin(user)


def _is_system_admin(user):
    return (
        user.is_authenticated
        and user.role == "admin"
        and user.is_superuser
    )


class RecordsHomeView(TemplateView):
    template_name = "records/index.html"

    def dispatch(self, request, *args, **kwargs):
        if not _can_access_records(request.user):
            return HttpResponseForbidden("You do not have access to records.")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        scope = _records_scope_for_user(self.request.user)
        models = []
        seen_models = set()
        for slug, model in MODEL_REGISTRY.items():
            if model in seen_models and slug != MEDICAL_SPECIALIST_SLUG:
                continue
            if model.__name__ == "HealthStudent":
                slug = "graduand"
            if not _model_visible_for_scope(slug, model, scope):
                continue
            models.append({
                "slug": slug,
                "label": _model_label(slug, model, plural=True),
                "count": scoped_record_queryset(model, self.request.user, slug).count(),
            })
            if slug != MEDICAL_SPECIALIST_SLUG:
                seen_models.add(model)
        context["models"] = models
        context["records_hub_title"] = _record_hub_title(scope)
        context["can_create_records"] = _can_create_records(self.request.user)
        context["can_delete_records"] = _can_delete_records(self.request.user)
        return context


class PopulationGuideView(TemplateView):
    template_name = "records/population_guide.html"

    def dispatch(self, request, *args, **kwargs):
        if not _is_system_admin(request.user):
            return HttpResponseForbidden("Population Guide is restricted to the System Admin.")
        return super().dispatch(request, *args, **kwargs)


class RecordListView(View):
    template_name = "records/list.html"

    def get(self, request, model_slug):
        if not _can_access_records(request.user):
            return HttpResponseForbidden("You do not have access to records.")
        model = resolve_accessible_model(model_slug, request.user)
        search_term = request.GET.get("q", "").strip()
        queryset = apply_search(scoped_record_queryset(model, request.user, model_slug).order_by("-id"), model, search_term)
        paginator = Paginator(queryset, 100)
        page_obj = paginator.get_page(request.GET.get("page"))
        object_list = page_obj.object_list
        is_professional_model = model.__name__ in {
            "NursingProfessional",
            "MedicalDoctor",
            "Midwife",
            "CommunityHealthWorker",
            "HealthStudent",
            "NurseAide",
        }
        media_lookup = {}
        document_lookup = {}
        if is_professional_model:
            ct = ContentType.objects.get_for_model(model)
            object_ids = [obj.pk for obj in object_list]
            for photo in ProfessionalPhoto.objects.filter(content_type=ct, object_id__in=object_ids).order_by("-is_primary", "-uploaded_at"):
                media_lookup.setdefault(photo.object_id, photo)
            for doc in ProfessionalDocument.objects.filter(content_type=ct, object_id__in=object_ids).order_by("-uploaded_at"):
                document_lookup.setdefault(doc.object_id, doc)
        return render(
            request,
            self.template_name,
            {
                "model_slug": model_slug,
                "model": model,
                "model_label": _model_label(model_slug, model),
                "model_plural_label": _model_label(model_slug, model, plural=True),
                "objects": object_list,
                "page_obj": page_obj,
                "paginator": paginator,
                "search_term": search_term,
                "is_professional_model": is_professional_model,
                "media_lookup": media_lookup,
                "document_lookup": document_lookup,
                "extra_columns": 3 if is_professional_model else 1,
                "fields": [field.name for field in model._meta.fields[:8]],
                "can_create_records": _can_create_records(request.user),
                "can_delete_records": _can_delete_records(request.user),
            },
        )


class RecordDetailView(View):
    template_name = "records/detail.html"

    def get(self, request, model_slug, pk):
        if not _can_access_records(request.user):
            return HttpResponseForbidden("You do not have access to records.")
        model = resolve_accessible_model(model_slug, request.user)
        obj = get_object_or_404(scoped_record_queryset(model, request.user, model_slug), pk=pk)
        media_fields = [
            field.name
            for field in model._meta.fields
            if field.get_internal_type() in {"ImageField", "FileField"}
        ]
        related_photos = []
        related_documents = []
        if model.__name__ in {
            "NursingProfessional",
            "MedicalDoctor",
            "Midwife",
            "CommunityHealthWorker",
            "HealthStudent",
            "NurseAide",
        }:
            ct = ContentType.objects.get_for_model(model)
            related_photos = ProfessionalPhoto.objects.filter(content_type=ct, object_id=obj.pk).order_by("-is_primary", "-uploaded_at")
            related_documents = ProfessionalDocument.objects.filter(content_type=ct, object_id=obj.pk).order_by("-uploaded_at")
        return render(
            request,
            self.template_name,
            {
                "model_slug": model_slug,
                "model": model,
                "model_label": _model_label(model_slug, model),
                "model_plural_label": _model_label(model_slug, model, plural=True),
                "object": obj,
                "fields": [field.name for field in model._meta.fields],
                "media_fields": media_fields,
                "related_photos": related_photos,
                "related_documents": related_documents,
                "can_delete_records": _can_delete_records(request.user),
            },
        )


class RecordCreateView(View):
    template_name = "records/form.html"

    def get(self, request, model_slug):
        if not _can_access_records(request.user):
            return HttpResponseForbidden("You do not have access to records.")
        model = resolve_accessible_model(model_slug, request.user)
        form = _scope_record_form(build_form_class(model)(), request.user)
        return render(request, self.template_name, {
            "form": form,
            "model_slug": model_slug,
            "model": model,
            "model_label": _model_label(model_slug, model),
            "is_create": True,
        })

    def post(self, request, model_slug):
        if not _can_access_records(request.user):
            return HttpResponseForbidden("You do not have access to records.")
        model = resolve_accessible_model(model_slug, request.user)
        form = _scope_record_form(build_form_class(model)(request.POST, request.FILES), request.user)
        if form.is_valid():
            obj = form.save(commit=False)
            if model.__name__ == "Receipt" and request.user.is_authenticated and not getattr(obj, "user_id", None):
                obj.user = request.user
            if hasattr(obj, "created_by") and request.user.is_authenticated and not getattr(obj, "created_by", None):
                obj.created_by = request.user
            if hasattr(obj, "updated_by") and request.user.is_authenticated:
                obj.updated_by = request.user
            obj.save()
            return redirect("record_detail", model_slug=model_slug, pk=obj.pk)
        return render(request, self.template_name, {
            "form": form,
            "model_slug": model_slug,
            "model": model,
            "model_label": _model_label(model_slug, model),
            "is_create": True,
        })


class RecordUpdateView(View):
    template_name = "records/form.html"

    def get(self, request, model_slug, pk):
        if not _can_access_records(request.user):
            return HttpResponseForbidden("You do not have access to records.")
        model = resolve_accessible_model(model_slug, request.user)
        obj = get_object_or_404(scoped_record_queryset(model, request.user, model_slug), pk=pk)
        form = _scope_record_form(build_form_class(model)(instance=obj), request.user)
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "model_slug": model_slug,
                "model": model,
                "model_label": _model_label(model_slug, model),
                "object": obj,
                "is_create": False,
            },
        )

    def post(self, request, model_slug, pk):
        if not _can_access_records(request.user):
            return HttpResponseForbidden("You do not have access to records.")
        model = resolve_accessible_model(model_slug, request.user)
        obj = get_object_or_404(scoped_record_queryset(model, request.user, model_slug), pk=pk)
        form = _scope_record_form(build_form_class(model)(request.POST, request.FILES, instance=obj), request.user)
        if form.is_valid():
            obj = form.save(commit=False)
            if hasattr(obj, "updated_by") and request.user.is_authenticated:
                obj.updated_by = request.user
            obj.save()
            return redirect("record_detail", model_slug=model_slug, pk=obj.pk)
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "model_slug": model_slug,
                "model": model,
                "model_label": _model_label(model_slug, model),
                "object": obj,
                "is_create": False,
            },
        )


class RecordDeleteView(View):
    template_name = "records/confirm_delete.html"

    def get(self, request, model_slug, pk):
        if not _can_access_records(request.user):
            return HttpResponseForbidden("You do not have access to records.")
        if not _can_delete_records(request.user):
            return HttpResponseForbidden("Only the System Admin can delete records from the generic Records Hub.")
        model = resolve_accessible_model(model_slug, request.user)
        obj = get_object_or_404(scoped_record_queryset(model, request.user, model_slug), pk=pk)
        return render(request, self.template_name, {
            "model_slug": model_slug,
            "model": model,
            "model_label": _model_label(model_slug, model),
            "object": obj,
        })

    def post(self, request, model_slug, pk):
        if not _can_access_records(request.user):
            return HttpResponseForbidden("You do not have access to records.")
        if not _can_delete_records(request.user):
            return HttpResponseForbidden("Only the System Admin can delete records from the generic Records Hub.")
        model = resolve_accessible_model(model_slug, request.user)
        obj = get_object_or_404(scoped_record_queryset(model, request.user, model_slug), pk=pk)
        obj.delete()
        return redirect("record_list", model_slug=model_slug)
