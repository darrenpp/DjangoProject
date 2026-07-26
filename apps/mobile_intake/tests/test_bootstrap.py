from django.test import TestCase
from django.urls import reverse

from .utils import auth_client, bootstrap, make_mobile_user


class MobileBootstrapTests(TestCase):
    def test_bootstrap_returns_nursing_forms_only_for_nursing_user(self):
        bootstrap()
        client = auth_client(make_mobile_user(scope="nursing"))
        response = client.get(reverse("mobile_v1_bootstrap"))

        self.assertEqual(response.status_code, 200)
        form_codes = {row["form_code"] for row in response.json()["enabled_forms"]}
        self.assertIn("NC1", form_codes)
        self.assertIn("NC2", form_codes)
        self.assertIn("NC3", form_codes)
        self.assertIn("NC6", form_codes)
        self.assertIn("NC7", form_codes)
        self.assertNotIn("MD1", form_codes)
