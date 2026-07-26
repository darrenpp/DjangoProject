from contextlib import contextmanager, redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from django.db import models

from apps.documents.models import DocumentAuditEvent, DocumentVersion
from apps.documents.services import extract_reference_candidates

easyocr = SimpleNamespace(Reader=None)


class OCREngineUnavailable(RuntimeError):
    pass


def _easyocr_module():
    global easyocr
    if getattr(easyocr, "Reader", None) is not None:
        return easyocr
    try:
        import easyocr as easyocr_module
    except ImportError:
        return easyocr
    easyocr = easyocr_module
    return easyocr


@contextmanager
def _silence_ocr_console_output():
    """Prevent OCR library progress output from breaking Windows charmap streams."""
    with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
        yield


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

    def process_ocr(self, *, raise_errors=True):
        try:
            self.extracted_text = self._extract_text()
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
            if raise_errors:
                raise
            return False
        return True

    def _extract_text(self):
        extension = Path(self.file.name or "").suffix.lower()
        if extension == ".pdf":
            text = self._extract_pdf_text_layer()
            if text.strip():
                return text
            return self._extract_scanned_pdf_with_easyocr()
        return self._extract_image_with_easyocr(self.file.path)

    def _reader(self):
        easyocr_module = _easyocr_module()
        if easyocr_module.Reader is None:
            raise OCREngineUnavailable(
                "EasyOCR is not installed for this Python runtime. "
                "Install easyocr in the active virtual environment, then retry OCR processing."
            )
        try:
            with _silence_ocr_console_output():
                return easyocr_module.Reader(['en'], gpu=False, verbose=False)
        except TypeError:
            with _silence_ocr_console_output():
                return easyocr_module.Reader(['en'], gpu=False)

    def _extract_image_with_easyocr(self, image_path):
        result = self._readtext(self._reader(), image_path)
        return ' '.join([text[1] for text in result])

    def _readtext(self, reader, image_path):
        with _silence_ocr_console_output():
            return reader.readtext(str(image_path))

    def _extract_pdf_text_layer(self):
        try:
            import fitz
        except ImportError:
            return ""

        text_parts = []
        try:
            with fitz.open(self.file.path) as pdf_document:
                for page in pdf_document:
                    text_parts.append(page.get_text("text"))
        except Exception:
            return ""
        return "\n".join(text_parts).strip()

    def _extract_scanned_pdf_with_easyocr(self):
        try:
            import fitz
        except ImportError as exc:
            raise OCREngineUnavailable(
                "Scanned PDF OCR needs PyMuPDF plus EasyOCR. PyMuPDF is not installed."
            ) from exc

        reader = self._reader()
        text_parts = []
        with TemporaryDirectory() as temp_dir:
            try:
                with fitz.open(self.file.path) as pdf_document:
                    for page_index, page in enumerate(pdf_document):
                        pixmap = page.get_pixmap(dpi=200)
                        image_path = Path(temp_dir) / f"page-{page_index + 1}.png"
                        pixmap.save(str(image_path))
                        result = self._readtext(reader, image_path)
                        text_parts.extend(text[1] for text in result)
            except Exception:
                result = self._readtext(reader, self.file.path)
                text_parts.extend(text[1] for text in result)
        return " ".join(text_parts)
