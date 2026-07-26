from rest_framework import serializers

from .constants import OFFICE_SCOPES


class MobileLoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)
    device_id = serializers.CharField(required=False, allow_blank=True)
    device_name = serializers.CharField(required=False, allow_blank=True)
    platform = serializers.CharField(required=False, allow_blank=True, default="android")
    app_version = serializers.CharField(required=False, allow_blank=True)


class MobileSubmissionSerializer(serializers.Serializer):
    idempotency_key = serializers.CharField()
    device_id = serializers.CharField(required=False, allow_blank=True)
    local_draft_id = serializers.CharField()
    local_version = serializers.IntegerField(min_value=1, default=1)
    office_scope = serializers.ChoiceField(choices=sorted(OFFICE_SCOPES))
    form_code = serializers.CharField()
    schema_version = serializers.CharField()
    created_offline_at = serializers.CharField(required=False, allow_blank=True)
    payload = serializers.DictField()
    device_name = serializers.CharField(required=False, allow_blank=True)
    app_version = serializers.CharField(required=False, allow_blank=True)


class DuplicateCheckSerializer(serializers.Serializer):
    office_scope = serializers.ChoiceField(choices=sorted(OFFICE_SCOPES))
    form_code = serializers.CharField()
    first_name = serializers.CharField(required=False, allow_blank=True)
    surname = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)
    date_of_birth = serializers.CharField(required=False, allow_blank=True)
    registration_number = serializers.CharField(required=False, allow_blank=True)
    practitioner_number = serializers.CharField(required=False, allow_blank=True)
    licence_number = serializers.CharField(required=False, allow_blank=True)
    license_number = serializers.CharField(required=False, allow_blank=True)


class MobileAccountRegistrationSerializer(serializers.Serializer):
    local_account_uuid = serializers.CharField()
    full_name = serializers.CharField()
    username = serializers.CharField()
    email = serializers.EmailField(required=False, allow_blank=True)
    phone = serializers.CharField(required=False, allow_blank=True)
    requested_role = serializers.CharField(default="mobile_collector")
    requested_cadre = serializers.CharField(required=False, allow_blank=True)
    office_scope = serializers.ChoiceField(choices=sorted(OFFICE_SCOPES))
    device_id = serializers.CharField(required=False, allow_blank=True)
