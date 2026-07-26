from django.test import TestCase

from apps.mobile_intake.models import MobileSubmission
from apps.mobile_intake.services.review import accept_submission, request_correction

from .utils import bootstrap, make_mobile_user, make_registrar, sample_submission_payload


class MobileReviewActionTests(TestCase):
    def test_registrar_can_accept_and_request_correction(self):
        bootstrap()
        collector = make_mobile_user()
        registrar = make_registrar()
        submission = MobileSubmission.objects.create(
            idempotency_key="idem-review",
            submitted_by=collector,
            local_draft_id="draft-review",
            office_scope="nursing",
            form_code="NC3",
            schema_version="2026.05.19",
            payload_json=sample_submission_payload()["payload"],
            normalized_payload_json=sample_submission_payload()["payload"],
            status="NEEDS_REVIEW",
        )

        request_correction(submission, registrar, "Upload receipt evidence.")
        submission.refresh_from_db()
        self.assertEqual(submission.status, "NEEDS_CORRECTION")

        accept_submission(submission, registrar, "Receipt reviewed.")
        submission.refresh_from_db()
        self.assertEqual(submission.status, "ACCEPTED")
        self.assertEqual(submission.status_history.count(), 2)
