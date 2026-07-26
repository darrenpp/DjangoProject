from django.test import TestCase
from django.urls import reverse

from apps.mobile_intake.models import MobileDevice

from .utils import make_mobile_user


class MobileAuthTests(TestCase):
    def test_mobile_login_returns_jwt_and_capabilities(self):
        make_mobile_user()
        response = self.client.post(reverse("mobile_v1_login"), {
            "username": "collector",
            "password": "StrongPass123!",
            "device_id": "device-auth",
            "device_name": "Android Tablet",
            "app_version": "1.0.0",
        }, content_type="application/json")

        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.json())
        self.assertTrue(response.json()["mobile_capabilities"]["can_submit_nursing"])
        self.assertTrue(MobileDevice.objects.filter(device_uuid="device-auth").exists())

    def test_mobile_login_rejects_unapproved_user(self):
        user = make_mobile_user(username="blocked")
        user.role_approved = False
        user.operations_approved = False
        user.save()
        response = self.client.post(reverse("mobile_v1_login"), {
            "username": "blocked",
            "password": "StrongPass123!",
        }, content_type="application/json")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "ACCOUNT_NOT_APPROVED")
