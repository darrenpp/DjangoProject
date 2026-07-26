from django.db.models import Q
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View

from apps.documents.access import can_access_document_repository, can_view_document, visible_document_scopes_for_user

from .forms import OCRImportForm
from .models import OCRDocument


REFERENCE_LABELS = {
    "official_receipt_numbers": "Official Receipt Numbers",
    "atp_numbers": "ATP Numbers",
    "registration_numbers": "Registration Numbers",
    "practitioner_numbers": "Practitioner Numbers",
    "license_numbers": "Licence Numbers",
    "years": "Years",
}


class OCRImportView(LoginRequiredMixin, View):
    def _visible_scopes(self, user):
        return visible_document_scopes_for_user(user) if can_access_document_repository(user) else []

    def _recent_documents(self, user):
        visible_scopes = self._visible_scopes(user)
        if not visible_scopes:
            return OCRDocument.objects.none()
        return (
            OCRDocument.objects
            .select_related("document_version__document")
            .filter(
                Q(document_version__isnull=True)
                | Q(document_version__document__office_scope__in=visible_scopes)
            )
            .order_by("-processed_at")[:10]
        )

    def get(self, request):
        if not can_access_document_repository(request.user):
            return render(request, 'ocr/import_pdf.html', {"forbidden": True}, status=403)
        return render(request, 'ocr/import_pdf.html', {
            "form": OCRImportForm(visible_scopes=self._visible_scopes(request.user)),
            "recent_ocr_documents": self._recent_documents(request.user),
        })

    def post(self, request):
        if not can_access_document_repository(request.user):
            return render(request, 'ocr/import_pdf.html', {"forbidden": True}, status=403)

        form = OCRImportForm(request.POST, request.FILES, visible_scopes=self._visible_scopes(request.user))
        if form.is_valid():
            doc = OCRDocument.objects.create(
                file=form.cleaned_data["pdf_file"],
                document_version=form.cleaned_data.get("document_version"),
            )
            processed = doc.process_ocr(raise_errors=False)

            if processed:
                messages.success(request, "OCR processed successfully. Extracted text saved.")
            else:
                messages.error(
                    request,
                    "The file was uploaded, but OCR processing failed: "
                    f"{doc.processing_error}",
                )
            return redirect('ocr_detail', pk=doc.pk)

        messages.error(request, "Please upload a file and correct any OCR form errors.")
        return render(
            request,
            'ocr/import_pdf.html',
            {
                "form": form,
                "recent_ocr_documents": self._recent_documents(request.user),
            },
            status=400,
        )


class OCRDetailView(LoginRequiredMixin, View):
    def get(self, request, pk):
        if not can_access_document_repository(request.user):
            return render(request, 'ocr/detail.html', {"forbidden": True}, status=403)

        ocr_document = get_object_or_404(
            OCRDocument.objects.select_related("document_version__document"),
            pk=pk,
        )
        if ocr_document.document_version and not can_view_document(request.user, ocr_document.document_version.document):
            return render(request, 'ocr/detail.html', {"forbidden": True}, status=403)

        metadata_rows = [
            {
                "label": REFERENCE_LABELS.get(key, key.replace("_", " ").title()),
                "values": values,
            }
            for key, values in (ocr_document.extracted_metadata or {}).items()
        ]
        return render(request, 'ocr/detail.html', {
            "ocr_document": ocr_document,
            "metadata_rows": metadata_rows,
        })
