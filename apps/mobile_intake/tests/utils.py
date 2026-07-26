from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.mobile_intake.services.bootstrap import bootstrap_mobile_forms


def make_mobile_user(username="collector", scope="nursing", role="mobile_collector"):
    department = "Medical Board Mobile Intake" if scope == "medical" else "Nursing Council Mobile Intake"
    user = User.objects.create_user(
        username=username,
        password="StrongPass123!",
        role=role,
        department=department,
        role_approved=True,
        operations_approved=True,
    )
    return user


def make_registrar(username="registrar", scope="nursing"):
    department = "Medical Board Registrar" if scope == "medical" else "Nursing Council Registrar"
    return User.objects.create_user(
        username=username,
        password="StrongPass123!",
        role="registrar",
        department=department,
        role_approved=True,
        operations_approved=True,
    )


def auth_client(user):
    client = APIClient()
    token = RefreshToken.for_user(user).access_token
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def bootstrap():
    bootstrap_mobile_forms()


def sample_submission_payload(**overrides):
    payload = {
        "idempotency_key": "device-1-draft-1-v1",
        "device_id": "device-1",
        "local_draft_id": "draft-1",
        "local_version": 1,
        "office_scope": "nursing",
        "form_code": "NC3",
        "schema_version": "2026.05.19",
        "created_offline_at": "2026-05-19T08:30:00+10:00",
        "payload": {
            "first_name": "Mary",
            "surname": "Example",
            "gender": "female",
            "date_of_birth": "1990-01-01",
            "registration_number": "N12345",
            "province": "National Capital District",
            "facility": "Port Moresby General Hospital",
            "employment_status": "employed",
            "employment_sector": "public",
        },
    }
    payload.update(overrides)
    return payload
