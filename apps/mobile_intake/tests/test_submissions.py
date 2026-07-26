from django.test import TestCase
from django.urls import reverse

from apps.mobile_intake.models import MobileSubmission
from apps.notifications.models import Notification
from apps.notifications.services import build_user_notification_summary

from .utils import auth_client, bootstrap, make_mobile_user, make_registrar, sample_submission_payload


class MobileSubmissionTests(TestCase):
    def test_submission_is_received_into_staging(self):
        bootstrap()
        client = auth_client(make_mobile_user())
        response = client.post(reverse("mobile_v1_submission_create"), sample_submission_payload(), format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(MobileSubmission.objects.count(), 1)
        submission = MobileSubmission.objects.get()
        self.assertEqual(submission.form_code, "NC3")
        self.assertIn(submission.status, {"NEEDS_REVIEW", "DUPLICATE_RISK"})
        self.assertFalse(submission.promoted_object_id)

    def test_schema_version_mismatch_is_rejected(self):
        bootstrap()
        client = auth_client(make_mobile_user())
        response = client.post(reverse("mobile_v1_submission_create"), sample_submission_payload(schema_version="2025.01"), format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "VALIDATION_FAILED")

    def test_submission_notifies_scoped_registrar_once(self):
        bootstrap()
        nursing_registrar = make_registrar(username="nursing_registrar")
        medical_registrar = make_registrar(username="medical_registrar", scope="medical")
        client = auth_client(make_mobile_user())
        payload = sample_submission_payload()

        response = client.post(reverse("mobile_v1_submission_create"), payload, format="json")
        replay_response = client.post(reverse("mobile_v1_submission_create"), payload, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(replay_response.status_code, 200)
        self.assertEqual(
            Notification.objects.filter(
                user=nursing_registrar,
                subject__startswith="Mobile intake review required: NC3",
            ).count(),
            1,
        )
        self.assertFalse(
            Notification.objects.filter(
                user=medical_registrar,
                subject__startswith="Mobile intake review required: NC3",
            ).exists()
        )
        summary = build_user_notification_summary(nursing_registrar)
        self.assertEqual(summary["unread_total_count"], 1)
        self.assertEqual(summary["unread_items"][0]["url"], reverse("mobile_intake_queue"))
        self.assertEqual(summary["unread_items"][0]["action"], "Open queue")
