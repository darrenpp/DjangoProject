from django.test import TestCase
from django.urls import reverse

from .utils import auth_client, bootstrap, make_mobile_user, sample_submission_payload


class MobilePermissionTests(TestCase):
    def test_medical_user_cannot_submit_nursing_payload(self):
        bootstrap()
        client = auth_client(make_mobile_user(username="medical_collector", scope="medical"))
        response = client.post(reverse("mobile_v1_submission_create"), sample_submission_payload(), format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "VALIDATION_FAILED")
