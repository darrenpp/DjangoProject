from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.documents.models import Document, DocumentAuditEvent, DocumentFolder, DocumentVersion
from apps.ocr.models import OCRDocument
from apps.ocr.forms import OCRImportForm


def make_text_file(name="sample.txt", content=b"sample repository content"):
    return SimpleUploadedFile(name, content, content_type="text/plain")


def make_pdf_file(name="scan.pdf", content=b"%PDF-1.4 test document"):
    return SimpleUploadedFile(name, content, content_type="application/pdf")


class RepositorySearchTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.nursing_registrar = user_model.objects.create_user(
            username="nursing.registrar",
            password="testpass123",
            role="registrar",
            department="Nursing Council",
        )
        self.medical_registrar = user_model.objects.create_user(
            username="medical.registrar",
            password="testpass123",
            role="registrar",
            department="Medical Board",
        )
        self.unapproved_reviewer = user_model.objects.create_user(
            username="nursing.reviewer",
            password="testpass123",
            role="reviewer",
            department="Nursing Council",
        )
        self.nursing_folder = DocumentFolder.objects.create(
            office_scope="nursing",
            name="Nursing Council Repository",
        )
        self.medical_folder = DocumentFolder.objects.create(
            office_scope="medical",
            name="Medical Board Repository",
        )

    def test_search_uses_ocr_text_and_scope(self):
        nursing_document = Document.objects.create(
            office_scope="nursing",
            title="Nursing OCR Record",
            folder=self.nursing_folder,
            status="active",
            metadata={"source": "scan"},
        )
        nursing_version = DocumentVersion.objects.create(
            document=nursing_document,
            version_number=1,
            file=make_text_file("nursing.txt", b"nursing-content"),
            extracted_text="Official receipt OR-4455 for nursing workflow",
        )

        medical_document = Document.objects.create(
            office_scope="medical",
            title="Medical OCR Record",
            folder=self.medical_folder,
            status="active",
        )
        DocumentVersion.objects.create(
            document=medical_document,
            version_number=1,
            file=make_text_file("medical.txt", b"medical-content"),
            extracted_text="Official receipt OR-4455 for medical workflow",
        )

        self.client.force_login(self.nursing_registrar)
        response = self.client.get(reverse("repository_search"), {"q": "OR-4455"})

        self.assertEqual(response.status_code, 200)
        page_objects = list(response.context["page_obj"].object_list)
        self.assertEqual(len(page_objects), 1)
        self.assertEqual(page_objects[0].id, nursing_document.id)
        self.assertEqual(page_objects[0].current_version.id, nursing_version.id)

    def test_medical_registrar_only_sees_medical_scope(self):
        medical_document = Document.objects.create(
            office_scope="medical",
            title="Medical Board Case File",
            folder=self.medical_folder,
            status="active",
        )
        DocumentVersion.objects.create(
            document=medical_document,
            version_number=1,
            file=make_text_file("medical-case.txt", b"medical-content"),
        )

        self.client.force_login(self.medical_registrar)
        response = self.client.get(reverse("repository_search"))

        self.assertEqual(response.status_code, 200)
        page_objects = list(response.context["page_obj"].object_list)
        self.assertEqual(len(page_objects), 1)
        self.assertEqual(page_objects[0].id, medical_document.id)

    def test_unapproved_reviewer_cannot_use_repository(self):
        self.client.force_login(self.unapproved_reviewer)
        response = self.client.get(reverse("repository_search"))

        self.assertEqual(response.status_code, 403)

    def test_staff_upload_detail_and_download_are_audited(self):
        self.client.force_login(self.nursing_registrar)
        upload_response = self.client.post(
            reverse("repository_upload"),
            {
                "office_scope": "nursing",
                "folder": self.nursing_folder.id,
                "title": "Treasury Receipt Evidence",
                "description": "Receipt for renewal application",
                "status": "active",
                "metadata_text": "receipt_number: G 4296\nregistration_number: RN-12345",
                "retention_years": "7",
                "version_notes": "Initial scan",
                "file": make_text_file("receipt.txt", b"receipt-data"),
            },
        )

        self.assertEqual(upload_response.status_code, 302)
        document = Document.objects.get(title="Treasury Receipt Evidence")
        version = document.current_version
        self.assertEqual(document.office_scope, "nursing")
        self.assertIsNotNone(version)
        self.assertEqual(document.metadata["receipt_number"], "G 4296")
        self.assertTrue(DocumentAuditEvent.objects.filter(document=document, event_type="created").exists())
        self.assertTrue(DocumentAuditEvent.objects.filter(document=document, event_type="uploaded").exists())

        detail_response = self.client.get(reverse("repository_detail", kwargs={"pk": document.pk}))
        self.assertEqual(detail_response.status_code, 200)
        self.assertTrue(DocumentAuditEvent.objects.filter(document=document, event_type="viewed").exists())

        download_response = self.client.get(reverse("repository_download", kwargs={"pk": document.pk, "version_id": version.pk}))
        self.assertEqual(download_response.status_code, 200)
        self.assertTrue(DocumentAuditEvent.objects.filter(document=document, version=version, event_type="downloaded").exists())

    def test_metadata_update_and_new_version_are_audited(self):
        self.client.force_login(self.nursing_registrar)
        document = Document.objects.create(
            office_scope="nursing",
            title="Policy Draft",
            folder=self.nursing_folder,
            status="draft",
            metadata={"source": "manual"},
        )
        DocumentVersion.objects.create(
            document=document,
            version_number=1,
            file=make_text_file("policy-v1.txt", b"policy-v1"),
        )

        update_response = self.client.post(
            reverse("repository_update_metadata", kwargs={"pk": document.pk}),
            {
                "office_scope": "nursing",
                "folder": self.nursing_folder.id,
                "title": "Policy Active",
                "description": "Approved policy",
                "status": "active",
                "metadata_text": "source: registrar\npolicy_year: 2026",
            },
        )
        self.assertEqual(update_response.status_code, 302)
        document.refresh_from_db()
        self.assertEqual(document.status, "active")
        self.assertTrue(DocumentAuditEvent.objects.filter(document=document, event_type="status_changed").exists())
        self.assertTrue(DocumentAuditEvent.objects.filter(document=document, event_type="metadata_updated").exists())

        version_response = self.client.post(
            reverse("repository_add_version", kwargs={"pk": document.pk}),
            {"notes": "Final version", "file": make_text_file("policy-v2.txt", b"policy-v2")},
        )
        self.assertEqual(version_response.status_code, 302)
        self.assertEqual(document.versions.count(), 2)
        self.assertEqual(document.current_version.version_number, 2)


class OCRIntegrationTests(TestCase):
    def test_ocr_form_accepts_receipt_image_uploads(self):
        form = OCRImportForm(
            data={},
            files={
                "pdf_file": SimpleUploadedFile(
                    "receipt.jpg",
                    b"image-bytes",
                    content_type="image/jpeg",
                )
            },
        )

        self.assertTrue(form.is_valid(), form.errors)

    @patch("apps.ocr.models.easyocr.Reader")
    def test_ocr_processing_updates_linked_document_version(self, reader_mock):
        reader_instance = reader_mock.return_value
        reader_instance.readtext.return_value = [
            ((0, 0), "Official Receipt No OR-7788", 0.99),
            ((0, 0), "ATP NO ATP-9922", 0.98),
        ]

        folder = DocumentFolder.objects.create(
            office_scope="nursing",
            name="Nursing OCR Root",
        )
        document = Document.objects.create(
            office_scope="nursing",
            title="Scanned Receipt",
            folder=folder,
            status="active",
        )
        version = DocumentVersion.objects.create(
            document=document,
            version_number=1,
            file=make_text_file("receipt.txt", b"receipt-content"),
        )

        ocr_document = OCRDocument.objects.create(
            file=make_pdf_file(),
            document_version=version,
        )
        ocr_document.process_ocr()

        version.refresh_from_db()
        document.refresh_from_db()
        ocr_document.refresh_from_db()

        self.assertEqual(ocr_document.processing_status, "completed")
        self.assertIn("Official Receipt No OR-7788", ocr_document.extracted_text)
        self.assertEqual(version.extracted_text, ocr_document.extracted_text)
        self.assertIn("extracted_references", document.metadata)
        self.assertIn("official_receipt_numbers", document.metadata["extracted_references"])
        self.assertTrue(
            DocumentAuditEvent.objects.filter(
                document=document,
                version=version,
                event_type="ocr_processed",
            ).exists()
        )

    @patch("apps.ocr.models.easyocr.Reader")
    def test_ocr_processing_suppresses_windows_charmap_progress_output(self, reader_mock):
        class CharmapFailingStream:
            def write(self, text):
                if "\u2588" in text:
                    raise UnicodeEncodeError("charmap", text, text.index("\u2588"), text.index("\u2588") + 1, "character maps to <undefined>")
                return len(text)

            def flush(self):
                return None

        reader_instance = reader_mock.return_value

        def build_reader(*args, **kwargs):
            print("loading OCR \u2588")
            return reader_instance

        def readtext(*args, **kwargs):
            print("processing OCR \u2588")
            return [((0, 0), "Receipt No OR-8899", 0.97)]

        reader_mock.side_effect = build_reader
        reader_instance.readtext.side_effect = readtext

        ocr_document = OCRDocument.objects.create(file=make_pdf_file())

        with patch("sys.stdout", CharmapFailingStream()), patch("sys.stderr", CharmapFailingStream()):
            ocr_document.process_ocr()

        ocr_document.refresh_from_db()
        self.assertEqual(ocr_document.processing_status, "completed")
        self.assertIn("Receipt No OR-8899", ocr_document.extracted_text)
        self.assertEqual(ocr_document.processing_error, "")

    def test_ocr_import_view_records_processing_failure_without_500(self):
        user_model = get_user_model()
        user = user_model.objects.create_superuser(
            username="ocr.admin",
            email="ocr.admin@example.com",
            password="testpass123",
            role="admin",
        )

        def fail_processing(ocr_document, *, raise_errors=True):
            ocr_document.processing_status = "failed"
            ocr_document.processing_error = "EasyOCR is not installed for this Python runtime."
            ocr_document.save(update_fields=["processing_status", "processing_error"])
            return False

        self.client.force_login(user)
        with patch("apps.ocr.models.OCRDocument.process_ocr", fail_processing):
            response = self.client.post(
                reverse("ocr_import"),
                {
                    "pdf_file": SimpleUploadedFile(
                        "receipt.jpg",
                        b"image-bytes",
                        content_type="image/jpeg",
                    ),
                    "document_version": "",
                },
            )

        self.assertEqual(response.status_code, 302)
        ocr_document = OCRDocument.objects.latest("id")
        self.assertRedirects(response, reverse("ocr_detail", args=[ocr_document.pk]))
        self.assertEqual(ocr_document.processing_status, "failed")
        self.assertIn("EasyOCR is not installed", ocr_document.processing_error)

        detail_response = self.client.get(reverse("ocr_detail", args=[ocr_document.pk]))
        self.assertContains(detail_response, "OCR Record Detail")
        self.assertContains(detail_response, "EasyOCR is not installed")

    def test_ocr_import_view_redirects_to_saved_extracted_details(self):
        user_model = get_user_model()
        user = user_model.objects.create_superuser(
            username="ocr.detail.admin",
            email="ocr.detail.admin@example.com",
            password="testpass123",
            role="admin",
        )

        def complete_processing(ocr_document, *, raise_errors=True):
            ocr_document.extracted_text = "Official Receipt No OR-7788 Registration No RN-1234 ATP No ATP-9922"
            ocr_document.extracted_metadata = {
                "official_receipt_numbers": ["OR-7788"],
                "registration_numbers": ["RN-1234"],
                "atp_numbers": ["ATP-9922"],
            }
            ocr_document.processing_status = "completed"
            ocr_document.processing_error = ""
            ocr_document.save()
            return True

        self.client.force_login(user)
        with patch("apps.ocr.models.OCRDocument.process_ocr", complete_processing):
            response = self.client.post(
                reverse("ocr_import"),
                {
                    "pdf_file": SimpleUploadedFile(
                        "receipt.jpg",
                        b"image-bytes",
                        content_type="image/jpeg",
                    ),
                    "document_version": "",
                },
            )

        ocr_document = OCRDocument.objects.latest("id")
        self.assertRedirects(response, reverse("ocr_detail", args=[ocr_document.pk]))

        detail_response = self.client.get(reverse("ocr_detail", args=[ocr_document.pk]))
        self.assertContains(detail_response, "Official Receipt No OR-7788")
        self.assertContains(detail_response, "Official Receipt Numbers")
        self.assertContains(detail_response, "OR-7788")
        self.assertContains(detail_response, "Registration Numbers")
        self.assertContains(detail_response, "RN-1234")
        self.assertContains(detail_response, "ATP Numbers")
        self.assertContains(detail_response, "ATP-9922")
