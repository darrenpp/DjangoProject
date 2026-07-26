from django.utils import timezone

from apps.workforce.models import Cadre, DocumentType, Facility, Location

from ..constants import (
    ALLOWED_ATTACHMENT_TYPES,
    DEFAULT_REQUIRED_FIELDS,
    DEFAULT_SCHEMA_VERSION,
    EMPLOYMENT_SECTORS,
    EMPLOYMENT_STATUSES,
    FORM_DEFAULTS,
    MAX_ATTACHMENT_MB,
)
from ..models import MobileFormSchema
from ..permissions import user_mobile_office_scopes


def default_mobile_json_schema(form_code, form_name):
    return {
        "type": "object",
        "title": form_name,
        "properties": {
            "first_name": {"type": "string"},
            "surname": {"type": "string"},
            "gender": {"type": "string"},
            "date_of_birth": {"type": "string", "format": "date"},
            "registration_number": {"type": "string"},
            "practitioner_number": {"type": "string"},
            "licence_number": {"type": "string"},
            "employment_status": {"type": "string", "enum": list(EMPLOYMENT_STATUSES)},
            "employment_sector": {"type": "string", "enum": list(EMPLOYMENT_SECTORS)},
            "province": {"type": "string"},
            "district": {"type": "string"},
            "facility": {"type": "string"},
            "receipt_number": {"type": "string"},
        },
        "required": list(DEFAULT_REQUIRED_FIELDS),
        "additionalProperties": True,
    }


def default_attachment_requirements(form_code):
    common = [
        {"document_type": "identity", "label": "Valid ID", "required": True},
        {"document_type": "receipt", "label": "Payment receipt", "required": False},
        {"document_type": "qualification", "label": "Qualification evidence", "required": False},
    ]
    if form_code in {"NC1", "NC2", "NC6", "NC7", "MD1", "CHW1"}:
        common.append({"document_type": "licence_certificate", "label": "Licence or certificate", "required": True})
    return common


def bootstrap_mobile_forms(created_by=None):
    created = 0
    updated = 0
    for form_code, (form_name, office_scope) in FORM_DEFAULTS.items():
        schema, was_created = MobileFormSchema.objects.update_or_create(
            form_code=form_code,
            office_scope=office_scope,
            schema_version=DEFAULT_SCHEMA_VERSION,
            defaults={
                "form_name": form_name,
                "json_schema": default_mobile_json_schema(form_code, form_name),
                "ui_schema": {},
                "required_fields": list(DEFAULT_REQUIRED_FIELDS),
                "attachment_requirements": default_attachment_requirements(form_code),
                "validation_rules": {
                    "requires_duplicate_check": True,
                    "employment_status_values": list(EMPLOYMENT_STATUSES),
                    "employment_sector_values": list(EMPLOYMENT_SECTORS),
                },
                "is_enabled": True,
                "enabled_for_roles": ["admin", "registrar", "reviewer", "mobile_collector"],
                "created_by": created_by,
            },
        )
        if was_created:
            created += 1
        else:
            updated += 1
    return {"created": created, "updated": updated, "total": created + updated}


def enabled_forms_for_user(user):
    scopes = user_mobile_office_scopes(user)
    role = getattr(user, "role", "")
    queryset = MobileFormSchema.objects.filter(is_enabled=True, office_scope__in=scopes)
    forms = []
    for schema in queryset.order_by("office_scope", "form_code", "-schema_version"):
        roles = schema.enabled_for_roles or []
        if roles and role not in roles and "all" not in roles:
            continue
        forms.append({
            "form_code": schema.form_code,
            "form_name": schema.form_name,
            "office_scope": schema.office_scope,
            "schema_version": schema.schema_version,
            "json_schema": schema.json_schema,
            "ui_schema": schema.ui_schema,
            "required_fields": schema.required_fields,
            "attachment_requirements": schema.attachment_requirements,
        })
    return forms


def mobile_lookups_for_user(user):
    scopes = user_mobile_office_scopes(user)
    cadre_queryset = Cadre.objects.all()
    if scopes == {"nursing"}:
        cadre_queryset = cadre_queryset.filter(category__in=("nursing", "midwifery", "chw", "other"))
    elif scopes == {"medical"}:
        cadre_queryset = cadre_queryset.filter(category__in=("medical", "chw", "other"))
    location_rows = list(Location.objects.exclude(province="").order_by("province", "district").values("province", "district").distinct()[:1000])
    return {
        "provinces": sorted({row["province"] for row in location_rows if row["province"]}),
        "districts": location_rows,
        "facilities": list(Facility.objects.order_by("name").values("id", "name", "type", "ownership", "level")[:1000]),
        "cadres": list(cadre_queryset.order_by("name").values("id", "name", "category")[:500]),
        "document_types": list(DocumentType.objects.order_by("name").values("id", "name", "description", "is_required")[:500]),
        "employment_statuses": list(EMPLOYMENT_STATUSES),
        "employment_sectors": list(EMPLOYMENT_SECTORS),
    }


def bootstrap_payload(user):
    return {
        "server_time": timezone.localtime().isoformat(),
        "api_version": "v1",
        "enabled_forms": enabled_forms_for_user(user),
        "lookups": mobile_lookups_for_user(user),
        "validation_rules": {
            "requires_duplicate_check": True,
            "required_identity_fields": list(DEFAULT_REQUIRED_FIELDS),
        },
        "sync_rules": {
            "max_attachment_mb": MAX_ATTACHMENT_MB,
            "allowed_file_types": sorted(ALLOWED_ATTACHMENT_TYPES),
            "requires_duplicate_check": True,
        },
    }
