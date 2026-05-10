from django import forms

from apps.documents.models import DocumentVersion


class OCRImportForm(forms.Form):
    pdf_file = forms.FileField()
    document_version = forms.ModelChoiceField(
        queryset=DocumentVersion.objects.select_related("document").order_by("-uploaded_at"),
        required=False,
        empty_label="Process as standalone OCR file",
    )

    def __init__(self, *args, **kwargs):
        office_scope = kwargs.pop("office_scope", "")
        visible_scopes = kwargs.pop("visible_scopes", None)
        super().__init__(*args, **kwargs)
        queryset = DocumentVersion.objects.select_related("document").order_by("-uploaded_at")
        if visible_scopes:
            queryset = queryset.filter(document__office_scope__in=visible_scopes)
        if office_scope:
            queryset = queryset.filter(document__office_scope=office_scope)
        self.fields["document_version"].queryset = queryset[:200]
        self.fields["pdf_file"].widget.attrs.update({"class": "form-control-file", "accept": ".pdf"})
        self.fields["document_version"].widget.attrs.update({"class": "form-control"})
