from types import SimpleNamespace

from django.db import models

from apps.documents.models import DocumentAuditEvent, DocumentVersion
from apps.documents.services import extract_reference_candidates

try:
    import easyocr
except ImportError:
    easyocr = SimpleNamespace(Reader=None)


class OCRDocument(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]

    file = models.FileField(upload_to='ocr/')
    extracted_text = models.TextField(blank=True)
    extracted_metadata = models.JSONField(default=dict, blank=True)
    document_version = models.ForeignKey(
        DocumentVersion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ocr_documents",
    )
    processing_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    processing_error = models.TextField(blank=True)
    processed_at = models.DateTimeField(auto_now_add=True)

    def process_ocr(self):
        try:
            if easyocr.Reader is None:
                raise RuntimeError("EasyOCR is not installed for this Python runtime.")

            reader = easyocr.Reader(['en'])
            result = reader.readtext(self.file.path)
            self.extracted_text = ' '.join([text[1] for text in result])
            self.extracted_metadata = extract_reference_candidates(self.extracted_text)
            self.processing_status = "completed"
            self.processing_error = ""
            self.save()

            if self.document_version:
                self.document_version.extracted_text = self.extracted_text
                self.document_version.save()
                document = self.document_version.document
                merged_metadata = dict(document.metadata or {})
                if self.extracted_metadata:
                    merged_metadata["extracted_references"] = self.extracted_metadata
                    document.metadata = merged_metadata
                    document.save(update_fields=["metadata", "updated_at"])
                DocumentAuditEvent.objects.create(
                    document=document,
                    version=self.document_version,
                    event_type="ocr_processed",
                    details={
                        "ocr_document_id": self.pk,
                        "references": self.extracted_metadata,
                    },
                )
        except Exception as exc:
            self.processing_status = "failed"
            self.processing_error = str(exc)
            self.save(update_fields=["processing_status", "processing_error"])
            raise
