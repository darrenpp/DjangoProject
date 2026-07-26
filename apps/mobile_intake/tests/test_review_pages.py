from django.test import TestCase
from django.urls import reverse

from apps.mobile_intake.models import MobileSubmission

from .utils import make_mobile_user, make_registrar, sample_submission_payload


class MobileReviewPageTests(TestCase):
    def setUp(self):
        self.collector = make_mobile_user()
        self.registrar = make_registrar()
        payload = sample_submission_payload()["payload"]
        payload.pop("licence_number", None)
        payload.pop("license_number", None)
        self.submission = MobileSubmission.objects.create(
            idempotency_key="idem-review-page",
            submitted_by=self.collector,
            local_draft_id="draft-review-page",
            office_scope="nursing",
            form_code="NC3",
            schema_version="2026.05.19",
            payload_json=payload,
            normalized_payload_json=payload,
            status="NEEDS_REVIEW",
        )
        self.client.force_login(self.registrar)

    def test_queue_handles_missing_optional_licence_number(self):
        response = self.client.get(reverse("mobile_intake_queue"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "N12345")
        self.assertContains(response, "Port Moresby General Hospital")

    def test_detail_handles_missing_optional_licence_number(self):
        response = self.client.get(reverse("mobile_intake_detail", args=[self.submission.submission_uuid]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "N12345")
        self.assertContains(response, "Port Moresby General Hospital")
