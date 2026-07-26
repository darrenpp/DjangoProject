from django.test import TestCase
from django.urls import reverse

from apps.workforce.models import NursingProfessional

from .utils import auth_client, bootstrap, make_mobile_user


class MobileDuplicateCheckTests(TestCase):
    def test_duplicate_check_returns_safe_summary(self):
        bootstrap()
        NursingProfessional.objects.create(first_name="Mary", last_name="Example", registration_number="N12345")
        client = auth_client(make_mobile_user())
        response = client.post(reverse("mobile_v1_duplicate_check"), {
            "office_scope": "nursing",
            "form_code": "NC3",
            "first_name": "Mary",
            "surname": "Example",
            "registration_number": "N12345",
        }, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["duplicate_risk"], "HIGH")
        match = response.json()["matches"][0]
        self.assertIn("registration_number", match["matched_fields"])
        self.assertNotIn("email", match)
