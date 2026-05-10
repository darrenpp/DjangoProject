from django import forms
from django.core.paginator import Paginator
from django.forms import modelform_factory
from django.http import Http404
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.contenttypes.models import ContentType
from django.views import View
from django.views.generic import TemplateView

from .record_registry import MODEL_REGISTRY
from apps.workforce.models import ProfessionalDocument, ProfessionalPhoto


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
        profile = " ".join(
            str(value or "")
            for value in [
                getattr(user, "department", ""),
                getattr(user, "username", ""),
                getattr(user, "first_name", ""),
                getattr(user, "last_name", ""),
            ]
        ).lower()
        return "data quality" in profile
    return False


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
        models = []
        seen_models = set()
        for slug, model in MODEL_REGISTRY.items():
            if model in seen_models:
                continue
            if model.__name__ == "HealthStudent":
                slug = "graduand"
            models.append({
                "slug": slug,
                "label": model._meta.verbose_name_plural.title(),
                "count": model.objects.count(),
            })
            seen_models.add(model)
        context["models"] = models
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
        model = resolve_model(model_slug)
        search_term = request.GET.get("q", "").strip()
        queryset = apply_search(model.objects.all().order_by("-id"), model, search_term)
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
                "model_label": model._meta.verbose_name.title(),
                "model_plural_label": model._meta.verbose_name_plural.title(),
                "objects": object_list,
                "page_obj": page_obj,
                "paginator": paginator,
                "search_term": search_term,
                "is_professional_model": is_professional_model,
                "media_lookup": media_lookup,
                "document_lookup": document_lookup,
                "extra_columns": 3 if is_professional_model else 1,
                "fields": [field.name for field in model._meta.fields[:8]],
            },
        )


class RecordDetailView(View):
    template_name = "records/detail.html"

    def get(self, request, model_slug, pk):
        if not _can_access_records(request.user):
            return HttpResponseForbidden("You do not have access to records.")
        model = resolve_model(model_slug)
        obj = get_object_or_404(model, pk=pk)
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
                "model_label": model._meta.verbose_name.title(),
                "model_plural_label": model._meta.verbose_name_plural.title(),
                "object": obj,
                "fields": [field.name for field in model._meta.fields],
                "media_fields": media_fields,
                "related_photos": related_photos,
                "related_documents": related_documents,
            },
        )


class RecordCreateView(View):
    template_name = "records/form.html"

    def get(self, request, model_slug):
        if not _can_access_records(request.user):
            return HttpResponseForbidden("You do not have access to records.")
        model = resolve_model(model_slug)
        form = build_form_class(model)()
        return render(request, self.template_name, {
            "form": form,
            "model_slug": model_slug,
            "model": model,
            "model_label": model._meta.verbose_name.title(),
            "is_create": True,
        })

    def post(self, request, model_slug):
        if not _can_access_records(request.user):
            return HttpResponseForbidden("You do not have access to records.")
        model = resolve_model(model_slug)
        form = build_form_class(model)(request.POST, request.FILES)
        if form.is_valid():
            obj = form.save(commit=False)
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
            "model_label": model._meta.verbose_name.title(),
            "is_create": True,
        })


class RecordUpdateView(View):
    template_name = "records/form.html"

    def get(self, request, model_slug, pk):
        if not _can_access_records(request.user):
            return HttpResponseForbidden("You do not have access to records.")
        model = resolve_model(model_slug)
        obj = get_object_or_404(model, pk=pk)
        form = build_form_class(model)(instance=obj)
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "model_slug": model_slug,
                "model": model,
                "model_label": model._meta.verbose_name.title(),
                "object": obj,
                "is_create": False,
            },
        )

    def post(self, request, model_slug, pk):
        if not _can_access_records(request.user):
            return HttpResponseForbidden("You do not have access to records.")
        model = resolve_model(model_slug)
        obj = get_object_or_404(model, pk=pk)
        form = build_form_class(model)(request.POST, request.FILES, instance=obj)
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
                "model_label": model._meta.verbose_name.title(),
                "object": obj,
                "is_create": False,
            },
        )


class RecordDeleteView(View):
    template_name = "records/confirm_delete.html"

    def get(self, request, model_slug, pk):
        if not _can_access_records(request.user):
            return HttpResponseForbidden("You do not have access to records.")
        model = resolve_model(model_slug)
        obj = get_object_or_404(model, pk=pk)
        return render(request, self.template_name, {
            "model_slug": model_slug,
            "model": model,
            "model_label": model._meta.verbose_name.title(),
            "object": obj,
        })

    def post(self, request, model_slug, pk):
        if not _can_access_records(request.user):
            return HttpResponseForbidden("You do not have access to records.")
        model = resolve_model(model_slug)
        obj = get_object_or_404(model, pk=pk)
        obj.delete()
        return redirect("record_list", model_slug=model_slug)
