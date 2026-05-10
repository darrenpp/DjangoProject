from django import forms
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

from apps.dashboard.access import application_domain, professional_domain
from apps.dashboard.models import Receipt
from apps.workforce.models import (
    Application,
    CommunityHealthWorker,
    DocumentType,
    HealthStudent,
    MedicalDoctor,
    Midwife,
    NurseAide,
    NursingProfessional,
)

from .models import Document, DocumentFolder


RELATED_MODEL_MAP = {
    "workforce.application": Application,
    "workforce.nursingprofessional": NursingProfessional,
    "workforce.midwife": Midwife,
    "workforce.nurseaide": NurseAide,
    "workforce.healthstudent": HealthStudent,
    "workforce.medicaldoctor": MedicalDoctor,
    "workforce.communityhealthworker": CommunityHealthWorker,
    "dashboard.receipt": Receipt,
}


RELATED_CHOICES = [
    ("", "No linked record"),
    ("workforce.application", "Application"),
    ("workforce.nursingprofessional", "Nursing Professional"),
    ("workforce.midwife", "Midwife"),
    ("workforce.nurseaide", "Nurse Aide"),
    ("workforce.healthstudent", "Graduand / Health Student"),
    ("workforce.medicaldoctor", "Medical Doctor"),
    ("workforce.communityhealthworker", "Community Health Worker"),
    ("dashboard.receipt", "Receipt"),
]


def metadata_to_lines(metadata):
    if not metadata:
        return ""
    lines = []
    for key, value in sorted(metadata.items()):
        if isinstance(value, (list, dict)):
            lines.append(f"{key}: {value}")
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines)


def parse_metadata_lines(raw_text):
    metadata = {}
    for line_number, raw_line in enumerate((raw_text or "").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if ":" not in line:
            raise ValidationError(f"Metadata line {line_number} must use 'Label: value' format.")
        key, value = line.split(":", 1)
        key = " ".join(key.strip().lower().replace("_", " ").split()).replace(" ", "_")
        value = value.strip()
        if not key:
            raise ValidationError(f"Metadata line {line_number} is missing a label.")
        metadata[key] = value
    return metadata


def object_domain(instance):
    if instance is None:
        return ""
    if isinstance(instance, Application):
        return application_domain(instance)
    if isinstance(instance, Receipt):
        return application_domain(instance.application) if instance.application_id else ""
    return professional_domain(instance)


class RepositoryBaseForm(forms.Form):
    metadata_text = forms.CharField(
        label="Metadata",
        required=False,
        widget=forms.Textarea(attrs={
            "rows": 8,
            "class": "form-control",
            "placeholder": "receipt_number: G 4296\nregistration_number: RN-12345\nsource_file: ATP workbook",
        }),
        help_text="Use one metadata value per line in 'label: value' format.",
    )

    def _configure_common_fields(self, visible_scopes):
        scope_choices = [
            (scope, dict(Document.OFFICE_SCOPE_CHOICES).get(scope, scope.title()))
            for scope in visible_scopes
        ]
        self.fields["office_scope"].choices = scope_choices
        self.fields["folder"].queryset = DocumentFolder.objects.filter(
            office_scope__in=visible_scopes,
            is_active=True,
        ).order_by("office_scope", "name")
        self.fields["document_type"].queryset = DocumentType.objects.order_by("name")

        for field in self.fields.values():
            if not isinstance(field.widget, (forms.CheckboxInput, forms.FileInput)):
                field.widget.attrs.setdefault("class", "form-control")

    def clean_metadata_text(self):
        return parse_metadata_lines(self.cleaned_data.get("metadata_text"))

    def clean(self):
        cleaned = super().clean()
        folder = cleaned.get("folder")
        office_scope = cleaned.get("office_scope")
        if folder and office_scope and folder.office_scope != office_scope:
            self.add_error("folder", "Folder scope must match the selected office scope.")
        return cleaned


class DocumentUploadForm(RepositoryBaseForm):
    office_scope = forms.ChoiceField(label="Repository scope")
    folder = forms.ModelChoiceField(queryset=DocumentFolder.objects.none(), required=False)
    document_type = forms.ModelChoiceField(queryset=DocumentType.objects.none(), required=False)
    title = forms.CharField(max_length=255)
    description = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 4}))
    status = forms.ChoiceField(choices=Document.STATUS_CHOICES, initial="draft")
    is_record = forms.BooleanField(required=False, label="Mark as official managed record")
    retention_years = forms.IntegerField(required=False, min_value=1, max_value=100)
    related_model = forms.ChoiceField(choices=RELATED_CHOICES, required=False)
    related_object_id = forms.IntegerField(required=False, min_value=1, label="Linked record ID")
    file = forms.FileField(label="Initial file")
    version_notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, visible_scopes=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.visible_scopes = visible_scopes or ["general"]
        self._configure_common_fields(self.visible_scopes)
        self.fields["file"].widget.attrs.update({"class": "form-control-file"})

    def clean(self):
        cleaned = super().clean()
        related_model = cleaned.get("related_model")
        related_object_id = cleaned.get("related_object_id")
        office_scope = cleaned.get("office_scope")
        if bool(related_model) != bool(related_object_id):
            raise ValidationError("Choose both linked record type and linked record ID, or leave both blank.")
        if related_model and related_object_id:
            model = RELATED_MODEL_MAP.get(related_model)
            if not model:
                raise ValidationError("Linked record type is not supported.")
            try:
                linked_object = model.objects.get(pk=related_object_id)
            except model.DoesNotExist as exc:
                raise ValidationError("Linked record was not found.") from exc
            domain = object_domain(linked_object)
            if domain and office_scope != "general" and office_scope != domain:
                raise ValidationError("Linked record belongs to a different regulatory body scope.")
            cleaned["linked_object"] = linked_object
            cleaned["linked_content_type"] = ContentType.objects.get_for_model(model)
        return cleaned


class DocumentUpdateForm(RepositoryBaseForm):
    office_scope = forms.ChoiceField(label="Repository scope")
    folder = forms.ModelChoiceField(queryset=DocumentFolder.objects.none(), required=False)
    document_type = forms.ModelChoiceField(queryset=DocumentType.objects.none(), required=False)
    title = forms.CharField(max_length=255)
    description = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 4}))
    status = forms.ChoiceField(choices=Document.STATUS_CHOICES)
    is_record = forms.BooleanField(required=False, label="Mark as official managed record")
    retention_years = forms.IntegerField(required=False, min_value=1, max_value=100)

    def __init__(self, *args, instance=None, visible_scopes=None, **kwargs):
        initial = kwargs.pop("initial", {}) or {}
        if instance:
            initial.update({
                "office_scope": instance.office_scope,
                "folder": instance.folder,
                "document_type": instance.document_type,
                "title": instance.title,
                "description": instance.description,
                "status": instance.status,
                "is_record": instance.is_record,
                "retention_years": instance.retention_years,
                "metadata_text": metadata_to_lines(instance.metadata),
            })
        super().__init__(*args, initial=initial, **kwargs)
        self.instance = instance
        self.visible_scopes = visible_scopes or ["general"]
        self._configure_common_fields(self.visible_scopes)

    def save(self):
        document = self.instance
        document.office_scope = self.cleaned_data["office_scope"]
        document.folder = self.cleaned_data.get("folder")
        document.document_type = self.cleaned_data.get("document_type")
        document.title = self.cleaned_data["title"]
        document.description = self.cleaned_data.get("description", "")
        document.status = self.cleaned_data["status"]
        document.is_record = self.cleaned_data.get("is_record", False)
        document.retention_years = self.cleaned_data.get("retention_years")
        document.metadata = self.cleaned_data.get("metadata_text") or {}
        document.save()
        return document


class DocumentVersionUploadForm(forms.Form):
    file = forms.FileField(label="New version file")
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3, "class": "form-control"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["file"].widget.attrs.update({"class": "form-control-file"})
