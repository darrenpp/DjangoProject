from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


User = get_user_model()


class RegulatoryWorkspaceViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username="workspace-admin",
            email="workspace-admin@example.test",
            password="test-pass",
            role="admin",
        )
        self.client.force_login(self.user)

    def test_medical_board_workspace_renders_filterable_aggregate_intelligence(self):
        response = self.client.get(reverse("medical_board_portal"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Clinical Regulation Intelligence")
        self.assertContains(response, "Aggregate decision support only")
        self.assertContains(response, "medical_specialty")

    def test_nursing_workspace_renders_aggregate_workforce_intelligence(self):
        response = self.client.get(
            reverse("nursing_council_portal"),
            {"nursing_province": "Morobe", "nursing_cadre": "Registered Nurse", "nursing_year": "2026"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nursing Workforce Intelligence")
        self.assertContains(response, "Aggregate-only decision support")
        self.assertContains(response, "Aggregate filters")
        self.assertContains(response, "nursing_province")
        self.assertContains(response, "nursing_cadre")
        self.assertContains(response, "nursing_year")
        self.assertContains(response, "Profile update queue")
