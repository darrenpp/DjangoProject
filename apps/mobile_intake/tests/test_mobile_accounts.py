from django.test import TestCase
from django.urls import reverse

from apps.mobile_intake.models import MobileLocalAccountRequest

from .utils import auth_client, make_mobile_user


class MobileAccountTests(TestCase):
    def test_mobile_local_account_request_is_staged(self):
        client = auth_client(make_mobile_user())
        response = client.post(reverse("mobile_v1_account_register"), {
            "local_account_uuid": "local-account-1",
            "full_name": "Collector Two",
            "username": "collector_two",
            "office_scope": "nursing",
            "requested_role": "mobile_collector",
        }, format="json")

        self.assertEqual(response.status_code, 201)
        account = MobileLocalAccountRequest.objects.get()
        self.assertEqual(account.status, "PENDING")
