from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View

from apps.documents.access import can_access_document_repository, visible_document_scopes_for_user

from .forms import OCRImportForm
from .models import OCRDocument


class OCRImportView(LoginRequiredMixin, View):
    def _visible_scopes(self, user):
        return visible_document_scopes_for_user(user) if can_access_document_repository(user) else []

    def get(self, request):
        if not can_access_document_repository(request.user):
            return render(request, 'ocr/import_pdf.html', {"forbidden": True}, status=403)
        return render(request, 'ocr/import_pdf.html', {
            "form": OCRImportForm(visible_scopes=self._visible_scopes(request.user)),
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
            doc.process_ocr()  # Runs EasyOCR

            # OCR extraction is saved on OCRDocument. Manual review/creation can be done in admin.
            messages.success(request, "PDF processed successfully. Extracted text saved.")
            return redirect('ocr_import')

        messages.error(request, "Please upload a file and correct any OCR form errors.")
        return render(request, 'ocr/import_pdf.html', {"form": form}, status=400)
