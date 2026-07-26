from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.mobile_intake.models import MobileSubmissionAttachment

from .utils import auth_client, bootstrap, make_mobile_user, sample_submission_payload


class MobileAttachmentTests(TestCase):
    def test_attachment_upload_stays_in_mobile_staging(self):
        bootstrap()
        client = auth_client(make_mobile_user())
        submission_response = client.post(reverse("mobile_v1_submission_create"), sample_submission_payload(), format="json")
        submission_id = submission_response.json()["server_submission_id"]
        file_obj = SimpleUploadedFile("receipt.pdf", b"receipt-data", content_type="application/pdf")

        response = client.post(
            reverse("mobile_v1_attachment_upload", args=[submission_id]),
            {"local_attachment_uuid": "att-1", "document_type": "receipt", "file": file_obj},
            format="multipart",
        )

        self.assertEqual(response.status_code, 201)
        attachment = MobileSubmissionAttachment.objects.get()
        self.assertEqual(attachment.upload_status, "RECEIVED")
        self.assertIsNone(attachment.repository_document)
