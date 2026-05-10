from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.documents.models import Document, DocumentAuditEvent, DocumentFolder, DocumentVersion
from apps.ocr.models import OCRDocument


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
