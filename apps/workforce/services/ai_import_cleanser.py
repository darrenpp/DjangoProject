from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from difflib import get_close_matches
import json
import re

import pandas as pd
from django.conf import settings

from apps.dashboard.ai_provider import AIProviderError, ai_provider_status, call_configured_ai_json


SENTINELS = {"", "-", "--", "---", "N/A", "NA", "NONE", "NULL", "NIL", "UNKNOWN", "UNKNOW", "NOT KNOWN", "TBA", "TBC", "?"}
PNG_PROVINCES = [
    "Autonomous Region of Bougainville",
    "Central Province",
    "Chimbu Province",
    "East New Britain Province",
    "East Sepik Province",
    "Eastern Highlands Province",
    "Enga Province",
    "Gulf Province",
    "Hela Province",
    "Jiwaka Province",
    "Madang Province",
    "Manus Province",
    "Milne Bay Province",
    "Morobe Province",
    "National Capital District",
    "New Ireland Province",
    "Oro Province",
    "Sandaun Province",
    "Southern Highlands Province",
    "Western Highlands Province",
    "Western Province",
    "West New Britain Province",
]
PROVINCE_ALIASES = {
    "NCD": "National Capital District",
    "N.C.D": "National Capital District",
    "N.C.D.": "National Capital District",
    "NATIONAL CAPITAL DISTRICT": "National Capital District",
    "CENTRAL": "Central Province",
    "ENB": "East New Britain Province",
    "EAST NEW BRITAIN": "East New Britain Province",
    "ESP": "East Sepik Province",
    "EAST SEPIK": "East Sepik Province",
    "EHP": "Eastern Highlands Province",
    "EASTERN HIGHLANDS": "Eastern Highlands Province",
    "ENGA": "Enga Province",
    "GULF": "Gulf Province",
    "HELA": "Hela Province",
    "JIWAKA": "Jiwaka Province",
    "MADANG": "Madang Province",
    "MANUS": "Manus Province",
    "MILNE BAY": "Milne Bay Province",
    "MOROBE": "Morobe Province",
    "NEW IRELAND": "New Ireland Province",
    "ORO": "Oro Province",
    "NORTHERN": "Oro Province",
    "SANDAUN": "Sandaun Province",
    "WEST SEPIK": "Sandaun Province",
    "SIMBU": "Chimbu Province",
    "CHIMBU": "Chimbu Province",
    "SHP": "Southern Highlands Province",
    "SOUTHERN HIGHLANDS": "Southern Highlands Province",
    "WESTERN": "Western Province",
    "WHP": "Western Highlands Province",
    "WESTERN HIGHLANDS": "Western Highlands Province",
    "WNB": "West New Britain Province",
    "WEST NEW BRITAIN": "West New Britain Province",
    "AROB": "Autonomous Region of Bougainville",
    "BOUGAINVILLE": "Autonomous Region of Bougainville",
}
GENDER_ALIASES = {
    "M": "Male",
    "MALE": "Male",
    "F": "Female",
    "FEMALE": "Female",
}
IDENTIFIER_FIELDS = {
    "registration_no",
    "registration_number",
    "practitioner_number",
    "license_number",
    "licence_number",
    "atp_number",
    "receipt_number",
    "official_receipt_no",
    "reference_number",
}
DATE_FIELD_TOKENS = ("date", "issued", "expiry", "expired", "payment")


IMPORT_CLEANSING_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "normalized_row": {"type": "object"},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "field": {"type": "string"},
                    "issue_type": {"type": "string"},
                    "original_value": {"type": "string"},
                    "suggested_value": {"type": "string"},
                    "confidence": {"type": "number"},
                    "requires_human_review": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
                "required": ["field", "issue_type", "original_value", "suggested_value", "confidence", "requires_human_review", "reason"],
            },
        },
        "ready_for_staging": {"type": "boolean"},
        "requires_human_review": {"type": "boolean"},
    },
    "required": ["normalized_row", "issues", "ready_for_staging", "requires_human_review"],
}


def _clean_key(value):
    key = re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return key or "unnamed_field"


def _clean_text(value):
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    text = re.sub(r"\s+", " ", str(value).replace("\xa0", " ")).strip()
    if text.upper() in SENTINELS:
        return ""
    return text


def _normalize_identifier(value):
    text = _clean_text(value).upper()
    if not text:
        return ""
    if re.fullmatch(r"\d+\.0+", text):
        text = text.split(".", 1)[0]
    if re.fullmatch(r"\d+\.\d+", text):
        try:
            text = str(int(Decimal(text)))
        except (InvalidOperation, ValueError):
            pass
    text = text.replace("_", " ")
    text = re.sub(r"\s*/\s*", "/", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_date(value):
    if value is None or value == "":
        return None
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        serial_value = float(value)
        if 20000 <= serial_value <= 60000:
            return date(1899, 12, 30) + timedelta(days=int(serial_value))
    text = _clean_text(value)
    if not text:
        return None
    if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", text):
        try:
            return datetime.strptime(text, "%Y-%m-%d").date()
        except ValueError:
            return None
    for dayfirst in (True, False):
        parsed = pd.to_datetime(text, errors="coerce", dayfirst=dayfirst)
        if not pd.isna(parsed):
            return parsed.date()
    return None


def _normalize_province(value):
    text = _clean_text(value)
    if not text:
        return "", None
    direct = PROVINCE_ALIASES.get(text.upper())
    if direct:
        return direct, {
            "issue_type": "province_alias",
            "suggested_value": direct,
            "confidence": 0.96,
            "reason": "Province matched a known PNG province alias.",
        }
    exact = next((province for province in PNG_PROVINCES if province.lower() == text.lower()), "")
    if exact:
        return exact, None
    match = get_close_matches(text, PNG_PROVINCES, n=1, cutoff=0.82)
    if match:
        return match[0], {
            "issue_type": "province_fuzzy_match",
            "suggested_value": match[0],
            "confidence": 0.82,
            "reason": "Province looks like a known PNG province but needs staff confirmation.",
        }
    return text, {
        "issue_type": "unknown_province",
        "suggested_value": "",
        "confidence": 0.2,
        "reason": "Province was not recognised in the PNG province list.",
    }


def _normalize_field(field, value):
    if field in IDENTIFIER_FIELDS:
        return _normalize_identifier(value), None
    if "gender" in field or field == "sex":
        text = _clean_text(value)
        normalized = GENDER_ALIASES.get(text.upper(), text.title() if text else "")
        issue = None
        if text and normalized != text:
            issue = {
                "issue_type": "gender_alias",
                "suggested_value": normalized,
                "confidence": 0.96,
                "reason": "Gender value matched a known alias.",
            }
        return normalized, issue
    if "province" in field:
        return _normalize_province(value)
    if "email" in field:
        return _clean_text(value).lower(), None
    if _is_date_field(field):
        parsed = _parse_date(value)
        return parsed.isoformat() if parsed else _clean_text(value), None
    return _clean_text(value), None


def _is_date_field(field):
    if field.endswith("_status") or field in {"status", "payment_status", "license_status", "licence_status"}:
        return False
    return any(token in field for token in DATE_FIELD_TOKENS)


def _add_issue(issues, *, field, issue_type, original_value, suggested_value="", confidence=0.5, requires_human_review=True, reason=""):
    issues.append({
        "field": field,
        "issue_type": issue_type,
        "original_value": "" if original_value is None else str(original_value),
        "suggested_value": "" if suggested_value is None else str(suggested_value),
        "confidence": float(confidence),
        "requires_human_review": bool(requires_human_review),
        "reason": reason,
    })


def local_cleanse_import_row(row, *, row_number=None, source_label="", scope="nursing"):
    normalized = {}
    issues = []
    original_by_clean_key = {}
    for original_key, value in dict(row).items():
        field = _clean_key(original_key)
        original_by_clean_key[field] = value
        normalized_value, issue = _normalize_field(field, value)
        normalized[field] = normalized_value
        if issue:
            _add_issue(
                issues,
                field=field,
                issue_type=issue["issue_type"],
                original_value=value,
                suggested_value=issue["suggested_value"],
                confidence=issue["confidence"],
                requires_human_review=issue["issue_type"] in {"province_fuzzy_match", "unknown_province"},
                reason=issue["reason"],
            )

    name_keys = [key for key in normalized if key in {"name", "full_name", "fullname", "surname", "last_name", "first_name"}]
    has_name = any(normalized.get(key) for key in name_keys)
    if not has_name:
        _add_issue(
            issues,
            field="full_name",
            issue_type="missing_required_identity",
            original_value="",
            reason="No name field was available for person matching.",
        )

    has_identifier = any(normalized.get(key) for key in IDENTIFIER_FIELDS if key in normalized)
    if not has_identifier:
        _add_issue(
            issues,
            field="registration_or_practitioner_number",
            issue_type="missing_identifier",
            original_value="",
            reason="No registration, practitioner, licence, ATP, receipt, or reference number was found.",
        )

    today = date.today()
    for field, normalized_value in normalized.items():
        if not _is_date_field(field):
            continue
        parsed = _parse_date(normalized_value)
        if not parsed:
            if _clean_text(original_by_clean_key.get(field)):
                _add_issue(
                    issues,
                    field=field,
                    issue_type="unparsed_date",
                    original_value=original_by_clean_key.get(field),
                    reason="Date could not be parsed reliably.",
                )
            continue
        if parsed > today:
            _add_issue(
                issues,
                field=field,
                issue_type="future_date",
                original_value=original_by_clean_key.get(field),
                suggested_value=parsed.isoformat(),
                confidence=0.95,
                reason="Date is later than today and may be a data-entry or parsing error.",
            )
        elif parsed.year < 2000:
            _add_issue(
                issues,
                field=field,
                issue_type="old_date_before_2000",
                original_value=original_by_clean_key.get(field),
                suggested_value=parsed.isoformat(),
                confidence=0.75,
                reason="Date is before 2000 and needs source verification before reporting.",
            )

    requires_review = any(issue["requires_human_review"] for issue in issues)
    return {
        "provider": "local",
        "mode": "offline_rules",
        "source_label": source_label,
        "row_number": row_number,
        "scope": scope,
        "normalized_row": normalized,
        "issues": issues,
        "ready_for_staging": has_name and bool(normalized),
        "requires_human_review": requires_review,
    }


def cleanse_import_row(row, *, row_number=None, source_label="", scope="nursing"):
    local_result = local_cleanse_import_row(row, row_number=row_number, source_label=source_label, scope=scope)
    status = ai_provider_status()
    model_cleansing_enabled = bool(getattr(settings, "AI_IMPORT_CLEANSING_MODEL_ENABLED", False)) or bool(getattr(settings, "AI_IMPORT_CLEANSING_EXTERNAL_ENABLED", False))
    if status["mode"] not in {"openai", "ollama", "local_llm"} or not model_cleansing_enabled:
        local_result["ai_provider"] = status
        return local_result

    system_prompt = (
        "You are an import-cleansing assistant for a government health regulatory registry. "
        "You only suggest normalized spreadsheet values and data-quality flags. "
        "Never approve records, never invent missing identity data, and mark uncertain items for human review."
    )
    try:
        live_result = call_configured_ai_json(
            system_prompt=system_prompt,
            user_payload={
                "scope": scope,
                "source_label": source_label,
                "row_number": row_number,
                "raw_row": dict(row),
                "local_rule_result": local_result,
            },
            schema=IMPORT_CLEANSING_SCHEMA,
            schema_name="import_cleansing_suggestion",
        )
    except AIProviderError as exc:
        local_result["ai_provider"] = {
            **status,
            "mode": "local_fallback",
            "detail": f"External import cleansing fallback used: {exc}",
        }
        return local_result

    live_result["provider"] = status["mode"]
    live_result["mode"] = "external_gpt_suggestions"
    live_result["source_label"] = source_label
    live_result["row_number"] = row_number
    live_result["scope"] = scope
    live_result["ai_provider"] = status
    return live_result


def cleanse_rows(rows, *, source_label="", scope="nursing", start_row=1):
    results = []
    for offset, row in enumerate(rows, start=start_row):
        results.append(cleanse_import_row(row, row_number=offset, source_label=source_label, scope=scope))
    return {
        "source_label": source_label,
        "scope": scope,
        "row_count": len(results),
        "requires_human_review": sum(1 for result in results if result["requires_human_review"]),
        "issue_count": sum(len(result["issues"]) for result in results),
        "results": results,
    }


def dumps_report(report):
    return json.dumps(report, indent=2, ensure_ascii=True, default=str)
