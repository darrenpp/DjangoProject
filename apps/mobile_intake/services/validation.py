from django.utils.dateparse import parse_datetime

from ..constants import OFFICE_SCOPES
from ..models import MobileFormSchema


def normalize_payload(payload):
    normalized = {}
    for key, value in (payload or {}).items():
        normalized_key = str(key).strip().lower().replace(" ", "_")
        normalized[normalized_key] = value.strip() if isinstance(value, str) else value
    if "last_name" in normalized and "surname" not in normalized:
        normalized["surname"] = normalized["last_name"]
    if "registration_no" in normalized and "registration_number" not in normalized:
        normalized["registration_number"] = normalized["registration_no"]
    if "facility_name" in normalized and "facility" not in normalized:
        normalized["facility"] = normalized["facility_name"]
    return normalized


def parse_client_datetime(value):
    if not value:
        return None
    parsed = parse_datetime(str(value))
    return parsed


def get_enabled_schema(office_scope, form_code, schema_version):
    return MobileFormSchema.objects.filter(
        office_scope=office_scope,
        form_code=str(form_code or "").upper(),
        schema_version=str(schema_version or ""),
        is_enabled=True,
    ).first()


def validate_submission_contract(user, *, office_scope, form_code, schema_version, scopes):
    errors = []
    office_scope = str(office_scope or "").lower()
    form_code = str(form_code or "").upper()
    schema_version = str(schema_version or "")
    if office_scope not in OFFICE_SCOPES:
        errors.append({"field": "office_scope", "message": "Office scope is not valid."})
    elif office_scope not in scopes:
        errors.append({"field": "office_scope", "message": "Your account cannot submit to this office scope."})
    if not form_code:
        errors.append({"field": "form_code", "message": "Form code is required."})
    if not schema_version:
        errors.append({"field": "schema_version", "message": "Schema version is required."})
    schema = get_enabled_schema(office_scope, form_code, schema_version) if not errors else None
    if not schema and office_scope in OFFICE_SCOPES and form_code and schema_version:
        errors.append({"field": "schema_version", "message": "Form is disabled or schema version is not available."})
    if schema and schema.enabled_for_roles:
        role = getattr(user, "role", "")
        if role not in schema.enabled_for_roles and "all" not in schema.enabled_for_roles:
            errors.append({"field": "form_code", "message": "This form is not enabled for your role."})
    return schema, errors


def required_field_errors(schema, payload):
    errors = []
    normalized = normalize_payload(payload)
    for field_name in schema.required_fields or []:
        value = normalized.get(field_name)
        if value in (None, "", [], {}):
            errors.append({"field": field_name, "message": "This field is required."})
    return errors
