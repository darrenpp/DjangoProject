from django.test import TestCase
from django.urls import reverse

from apps.mobile_intake.models import MobileSubmission

from .utils import auth_client, bootstrap, make_mobile_user, sample_submission_payload


class MobileIdempotencyTests(TestCase):
    def test_same_idempotency_key_returns_same_submission(self):
        bootstrap()
        client = auth_client(make_mobile_user())
        first = client.post(reverse("mobile_v1_submission_create"), sample_submission_payload(), format="json")
        second = client.post(reverse("mobile_v1_submission_create"), sample_submission_payload(), format="json")

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.json()["idempotent"])
        self.assertEqual(MobileSubmission.objects.count(), 1)
        self.assertEqual(first.json()["server_submission_id"], second.json()["server_submission_id"])
