import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.dashboard.models import Receipt
from apps.workforce.models import (
    CommunityHealthWorker,
    HealthStudent,
    MedicalDoctor,
    Midwife,
    MissingDataReview,
    NurseAide,
    NursingProfessional,
    PracticingLicenseRecord,
)
from apps.workforce.services.ndata_workbook_import import normalize_name


PLACEHOLDER_VALUES = {"", "-", "--", "N/A", "NA", "NIL", "NONE", "NULL", "UNKNOWN", "TBA", "TBD"}
GENERIC_PAYMENT_METHOD_VALUES = {
    "BANK",
    "BANK DEPOSIT",
    "CASH",
    "CARD",
    "IMPORTED",
    "IMPORTED ATP PAYMENT",
    "IMPORTED ATP RECEIPT",
    "OFFICE",
    "ONLINE",
    "PAYMENT",
}
MEDICAL_TARGET_MODELS = {"medicaldoctor", "communityhealthworker"}
NURSING_TARGET_MODELS = {"nursingprofessional", "midwife", "nurseaide", "healthstudent"}

@dataclass(frozen=True)
class ReceiptOwnerMatch:
    content_type: ContentType
    object_id: int
    confidence: str
    rule: str
    notes: str
    score: int


@dataclass
class ReceiptLinkingIndexes:
    by_reference: dict[str, list]
    by_identifier: dict[str, list]
    by_name_date: dict[tuple[str, object], list]


def compact_identifier(value) -> str:
    text = str(value or "").strip().upper()
    if text in PLACEHOLDER_VALUES:
        return ""
    return re.sub(r"[^A-Z0-9]+", "", text)


def reference_key(value) -> str:
    text = str(value or "").strip().upper()
    if text in PLACEHOLDER_VALUES or text in GENERIC_PAYMENT_METHOD_VALUES:
        return ""
    if not re.search(r"\d", text):
        return ""
    return text


def receipt_reference_values(receipt: Receipt) -> set[str]:
    values = {
        receipt.official_receipt_no,
        receipt.receipt_number,
        receipt.payment_method,
    }
    normalized = {str(value or "").strip() for value in values if str(value or "").strip()}
    return {value for value in normalized if reference_key(value)}


def receipt_practitioner_values(receipt: Receipt) -> set[str]:
    values = {
        receipt.practitioner_number,
        receipt.atp_number,
        getattr(receipt.user, "registration_number", ""),
        getattr(receipt.user, "license_number", ""),
        getattr(receipt.user, "national_id", ""),
    }
    identifiers = {compact_identifier(value) for value in values if compact_identifier(value)}
    return {value for value in identifiers if re.search(r"\d", value)}


def _object_key(obj) -> tuple[str, int]:
    return (obj.__class__.__name__, obj.pk)


def _content_type_for_object(obj) -> ContentType:
    return ContentType.objects.get_for_model(obj, for_concrete_model=False)


def build_receipt_linking_indexes(scope: str | None = None) -> ReceiptLinkingIndexes:
    queryset = PracticingLicenseRecord.objects.only(
        "id",
        "record_year",
        "record_type",
        "target_model",
        "full_name",
        "registration_no",
        "practitioner_number",
        "reference_number",
        "payment_method",
        "payment_date",
        "issued_date",
        "date_of_birth",
    )
    if scope == "medical":
        queryset = queryset.filter(target_model__in=MEDICAL_TARGET_MODELS)
    elif scope == "nursing":
        queryset = queryset.filter(target_model__in=NURSING_TARGET_MODELS)

    by_reference = defaultdict(list)
    by_identifier = defaultdict(list)
    by_name_date = defaultdict(list)

    for record in queryset.iterator(chunk_size=4000):
        for value in (record.reference_number, record.payment_method):
            key = reference_key(value)
            if key:
                by_reference[key].append(record)
        for value in (record.practitioner_number, record.registration_no):
            key = compact_identifier(value)
            if key and re.search(r"\d", key):
                by_identifier[key].append(record)
        if record.full_name and record.payment_date:
            by_name_date[(normalize_name(record.full_name).upper(), record.payment_date)].append(record)

    return ReceiptLinkingIndexes(
        by_reference=dict(by_reference),
        by_identifier=dict(by_identifier),
        by_name_date=dict(by_name_date),
    )


def _license_record_identity_key(record: PracticingLicenseRecord) -> str:
    target = record.target_model or "other"
    registration = compact_identifier(record.registration_no)
    practitioner = compact_identifier(record.practitioner_number)
    name = normalize_name(record.full_name).upper()
    dob = record.date_of_birth.isoformat() if record.date_of_birth else ""
    if registration:
        return f"{target}:registration:{registration}"
    if practitioner:
        return f"{target}:practitioner:{practitioner}"
    if name and dob:
        return f"{target}:name_dob:{name}:{dob}"
    if name:
        return f"{target}:name:{name}"
    return f"{target}:pk:{record.pk}"


def _collapse_license_candidates(candidates) -> tuple[PracticingLicenseRecord | None, str]:
    unique = {}
    for record in candidates:
        unique[record.pk] = record
    if not unique:
        return None, ""

    by_owner = defaultdict(list)
    for record in unique.values():
        by_owner[_license_record_identity_key(record)].append(record)

    if len(by_owner) > 1:
        return None, f"Matched {len(unique)} rows across {len(by_owner)} possible owners."

    records = next(iter(by_owner.values()))
    records.sort(
        key=lambda record: (
            record.record_year or 0,
            record.payment_date or record.issued_date or date.min,
            record.id,
        ),
        reverse=True,
    )
    selected = records[0]
    if len(records) > 1:
        return selected, f"Matched {len(records)} rows for the same owner key; linked to latest row #{selected.pk}."
    return selected, f"Matched imported licence/payment row #{selected.pk}."


def _match_from_application(receipt: Receipt) -> ReceiptOwnerMatch | None:
    application = receipt.application
    if not application or not application.content_type_id or not application.object_id:
        return None
    return ReceiptOwnerMatch(
        content_type=application.content_type,
        object_id=application.object_id,
        confidence="application",
        rule="application_professional",
        notes=f"Receipt is attached to application #{application.pk}.",
        score=100,
    )


def _match_from_account(receipt: Receipt) -> ReceiptOwnerMatch | None:
    user = receipt.user
    if not user or not user.professional_content_type_id or not user.professional_object_id:
        return None
    return ReceiptOwnerMatch(
        content_type=user.professional_content_type,
        object_id=user.professional_object_id,
        confidence="account",
        rule="account_professional_link",
        notes=f"Receipt user {user.username} is linked to a professional record.",
        score=90,
    )


def _license_match_from_receipt_number(receipt: Receipt, indexes: ReceiptLinkingIndexes | None = None) -> ReceiptOwnerMatch | None:
    values = receipt_reference_values(receipt)
    if not values:
        return None
    if indexes:
        candidates = []
        for value in values:
            candidates.extend(indexes.by_reference.get(reference_key(value), []))
    else:
        query = Q()
        for value in values:
            query |= Q(reference_number__iexact=value) | Q(payment_method__iexact=value)
        candidates = PracticingLicenseRecord.objects.filter(query)
    record, note = _collapse_license_candidates(candidates)
    if not record:
        if note:
            return ReceiptOwnerMatch(
                content_type=ContentType.objects.get_for_model(Receipt),
                object_id=receipt.pk,
                confidence="ambiguous",
                rule="receipt_number_ambiguous",
                notes=note,
                score=10,
            )
        return None
    return ReceiptOwnerMatch(
        content_type=_content_type_for_object(record),
        object_id=record.pk,
        confidence="receipt_number",
        rule="imported_receipt_number",
        notes=note,
        score=85,
    )


def _license_match_from_practitioner_number(receipt: Receipt, indexes: ReceiptLinkingIndexes | None = None) -> ReceiptOwnerMatch | None:
    values = receipt_practitioner_values(receipt)
    if not values:
        return None
    if indexes:
        candidates = []
        for value in values:
            candidates.extend(indexes.by_identifier.get(value, []))
    else:
        query = Q()
        for value in values:
            query |= Q(practitioner_number__iexact=value) | Q(registration_no__iexact=value)
        candidates = PracticingLicenseRecord.objects.filter(query)
    record, note = _collapse_license_candidates(candidates)
    if not record:
        if note:
            return ReceiptOwnerMatch(
                content_type=ContentType.objects.get_for_model(Receipt),
                object_id=receipt.pk,
                confidence="ambiguous",
                rule="practitioner_number_ambiguous",
                notes=note,
                score=10,
            )
        return None
    return ReceiptOwnerMatch(
        content_type=_content_type_for_object(record),
        object_id=record.pk,
        confidence="practitioner_number",
        rule="receipt_practitioner_number",
        notes=note,
        score=75,
    )


def _license_match_from_description(receipt: Receipt, indexes: ReceiptLinkingIndexes | None = None) -> ReceiptOwnerMatch | None:
    description = str(receipt.description or "")
    if not description or not receipt.receipt_date:
        return None

    match = re.search(r"\bfor\s+(.+)$", description, flags=re.IGNORECASE)
    if not match:
        return None

    name = normalize_name(match.group(1)).upper()
    if not name:
        return None

    payment_date = receipt.receipt_date.date()
    if indexes:
        candidates = indexes.by_name_date.get((name, payment_date), [])
    else:
        candidates = [
            record
            for record in PracticingLicenseRecord.objects.filter(payment_date=payment_date).iterator(chunk_size=1000)
            if normalize_name(record.full_name).upper() == name
        ]
    record, note = _collapse_license_candidates(candidates)
    if not record:
        if note:
            return ReceiptOwnerMatch(
                content_type=ContentType.objects.get_for_model(Receipt),
                object_id=receipt.pk,
                confidence="ambiguous",
                rule="description_name_date_ambiguous",
                notes=note,
                score=10,
            )
        return None
    return ReceiptOwnerMatch(
        content_type=_content_type_for_object(record),
        object_id=record.pk,
        confidence="name_date_amount",
        rule="description_name_and_receipt_date",
        notes=note,
        score=60,
    )


def find_receipt_owner_match(receipt: Receipt, indexes: ReceiptLinkingIndexes | None = None) -> ReceiptOwnerMatch | None:
    candidates = [
        _match_from_application(receipt),
        _match_from_account(receipt),
        _license_match_from_receipt_number(receipt, indexes),
        _license_match_from_practitioner_number(receipt, indexes),
        _license_match_from_description(receipt, indexes),
    ]
    candidates = [candidate for candidate in candidates if candidate]
    if not candidates:
        return None
    candidates.sort(key=lambda candidate: candidate.score, reverse=True)
    return candidates[0]


def _receipt_scope_query(scope: str | None):
    if scope == "medical":
        return Q(application__form_code__in={"MD1", "MD2", "CHW1", "CHWP", "CHWF", "MBSP", "MBRN", "MBAC", "MBPF", "MBTC"})
    if scope == "nursing":
        return (
            Q(application__isnull=True)
            | Q(application__form_code__istartswith="NC")
            | Q(application__form_code__istartswith="G")
        )
    return Q()


def eligible_receipts(scope: str | None = None, *, include_failed=False):
    queryset = Receipt.objects.select_related(
        "user",
        "application",
        "application__content_type",
        "payer_content_type",
    ).order_by("id")
    if not include_failed:
        queryset = queryset.exclude(status="failed")
    scope_query = _receipt_scope_query(scope)
    return queryset.filter(scope_query) if scope_query else queryset


def _review_fields(reason: str, receipt: Receipt) -> list[str]:
    fields = [
        f"High value review: {reason}",
        "Receipt owner could not be verified against an application, account, imported licence record, or practitioner identifier.",
    ]
    if receipt.amount is not None:
        fields.append(f"Receipt amount: PGK {receipt.amount}")
    reference = receipt.official_receipt_no or receipt.receipt_number
    if reference:
        fields.append(f"Receipt reference: {reference}")
    return fields


def _upsert_receipt_review(receipt: Receipt, reason: str) -> bool:
    content_type = ContentType.objects.get_for_model(Receipt)
    fields = _review_fields(reason, receipt)
    review, created = MissingDataReview.objects.update_or_create(
        content_type=content_type,
        object_id=receipt.pk,
        defaults={
            "full_name": str(receipt.user or "Unassigned receipt")[:255],
            "registration_no": (receipt.official_receipt_no or receipt.receipt_number or "")[:100],
            "email": getattr(receipt.user, "email", "") or "",
            "professional_type": "Receipt / Payment",
            "missing_fields": fields,
            "missing_count": len(fields),
            "source_label": "Receipt ownership linkage",
            "source_row": None,
            "status": "under_review",
            "severity": "high",
            "resolved_at": None,
        },
    )
    return created


def _resolve_receipt_review(receipt: Receipt) -> int:
    content_type = ContentType.objects.get_for_model(Receipt)
    return MissingDataReview.objects.filter(
        content_type=content_type,
        object_id=receipt.pk,
    ).exclude(status="resolved").update(
        status="resolved",
        missing_fields=[],
        missing_count=0,
        resolved_at=timezone.now(),
    )


def _apply_match(receipt: Receipt, match: ReceiptOwnerMatch) -> bool:
    if match.confidence == "ambiguous":
        receipt.payer_match_confidence = "ambiguous"
        receipt.payer_match_rule = match.rule
        receipt.payer_match_notes = match.notes
        receipt.payer_linked_at = None
        receipt.save(update_fields=[
            "payer_match_confidence",
            "payer_match_rule",
            "payer_match_notes",
            "payer_linked_at",
        ])
        return False

    changed = (
        receipt.payer_content_type_id != match.content_type.id
        or receipt.payer_object_id != match.object_id
        or receipt.payer_match_confidence != match.confidence
        or receipt.payer_match_rule != match.rule
        or receipt.payer_match_notes != match.notes
    )
    if not changed:
        return False

    receipt.payer_content_type = match.content_type
    receipt.payer_object_id = match.object_id
    receipt.payer_match_confidence = match.confidence
    receipt.payer_match_rule = match.rule
    receipt.payer_match_notes = match.notes
    receipt.payer_linked_at = timezone.now()
    receipt.save(update_fields=[
        "payer_content_type",
        "payer_object_id",
        "payer_match_confidence",
        "payer_match_rule",
        "payer_match_notes",
        "payer_linked_at",
    ])
    return True


def link_receipts_to_individual_records(
    *,
    apply_changes=False,
    scope: str | None = None,
    limit: int | None = None,
    include_failed=False,
) -> dict:
    queryset = eligible_receipts(scope=scope, include_failed=include_failed)
    if limit:
        queryset = queryset[:limit]

    result = Counter({
        "reviewed": 0,
        "linked": 0,
        "already_linked": 0,
        "unmatched_reviews_created": 0,
        "unmatched_reviews_updated": 0,
        "ambiguous_reviews_created": 0,
        "ambiguous_reviews_updated": 0,
        "resolved_reviews": 0,
    })
    by_rule = Counter()
    indexes = build_receipt_linking_indexes(scope)

    with transaction.atomic():
        for receipt in queryset.iterator(chunk_size=1000):
            result["reviewed"] += 1
            match = find_receipt_owner_match(receipt, indexes)
            if not match:
                if apply_changes:
                    created = _upsert_receipt_review(receipt, "receipt has no traceable owner")
                    receipt.payer_match_confidence = "unlinked"
                    receipt.payer_match_rule = "no_traceable_owner"
                    receipt.payer_match_notes = "No application, account, receipt-number, practitioner-number, or name/date match was found."
                    receipt.payer_linked_at = None
                    receipt.save(update_fields=[
                        "payer_match_confidence",
                        "payer_match_rule",
                        "payer_match_notes",
                        "payer_linked_at",
                    ])
                    result["unmatched_reviews_created" if created else "unmatched_reviews_updated"] += 1
                else:
                    result["unmatched_reviews_updated"] += 1
                continue

            by_rule[match.rule] += 1
            if match.confidence == "ambiguous":
                if apply_changes:
                    _apply_match(receipt, match)
                    created = _upsert_receipt_review(receipt, f"ambiguous owner match ({match.rule})")
                    result["ambiguous_reviews_created" if created else "ambiguous_reviews_updated"] += 1
                else:
                    result["ambiguous_reviews_updated"] += 1
                continue

            if apply_changes:
                changed = _apply_match(receipt, match)
                result["linked" if changed else "already_linked"] += 1
                result["resolved_reviews"] += _resolve_receipt_review(receipt)
            else:
                existing_same = (
                    receipt.payer_content_type_id == match.content_type.id
                    and receipt.payer_object_id == match.object_id
                    and receipt.payer_match_confidence == match.confidence
                )
                result["already_linked" if existing_same else "linked"] += 1

    payload = dict(result)
    payload["by_rule"] = dict(sorted(by_rule.items()))
    payload["mode"] = "apply" if apply_changes else "dry_run"
    payload["scope"] = scope or "all"
    return payload
