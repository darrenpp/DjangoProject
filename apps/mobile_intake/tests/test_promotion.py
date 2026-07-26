from django.test import TestCase

from apps.mobile_intake.models import MobilePromotionLink, MobileSubmission
from apps.mobile_intake.services.promotion import promote_submission
from apps.workforce.models import Application, EmploymentRecord

from .utils import bootstrap, make_mobile_user, make_registrar, sample_submission_payload


class MobilePromotionTests(TestCase):
    def test_accepted_submission_promotes_to_application_and_employment(self):
        bootstrap()
        collector = make_mobile_user()
        registrar = make_registrar()
        payload = sample_submission_payload()["payload"]
        submission = MobileSubmission.objects.create(
            idempotency_key="idem-promote",
            submitted_by=collector,
            local_draft_id="draft-promote",
            office_scope="nursing",
            form_code="NC3",
            schema_version="2026.05.19",
            payload_json=payload,
            normalized_payload_json=payload,
            status="ACCEPTED",
        )

        promote_submission(submission, registrar, note="Reviewed and approved.")

        submission.refresh_from_db()
        self.assertEqual(submission.status, "PROMOTED")
        self.assertEqual(Application.objects.count(), 1)
        self.assertEqual(EmploymentRecord.objects.count(), 1)
        self.assertGreaterEqual(MobilePromotionLink.objects.count(), 2)
