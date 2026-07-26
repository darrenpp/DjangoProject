from django.db import transaction

from ..constants import (
    STATUS_DUPLICATE_RISK,
    STATUS_FAILED,
    STATUS_NEEDS_REVIEW,
    STATUS_RECEIVED,
    STATUS_SUPERSEDED,
)
from ..models import MobileSubmission
from ..permissions import user_mobile_office_scopes
from .audit import log_audit, log_sync_event, record_status_change
from .duplicate_check import duplicate_check
from .notifications import notify_mobile_submission_ready_for_review
from .validation import normalize_payload, parse_client_datetime, required_field_errors, validate_submission_contract


def receive_submission(user, data, request=None):
    scopes = user_mobile_office_scopes(user)
    idempotency_key = str(data.get("idempotency_key") or "").strip()
    if not idempotency_key:
        return None, {"idempotency_key": ["This field is required."]}, False

    existing = MobileSubmission.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        log_sync_event(
            submission=existing,
            device=existing.device,
            user=user,
            event_type="MOBILE_SUBMISSION_IDEMPOTENT_REPLAY",
            status_after=existing.status,
            request=request,
        )
        return existing, None, True

    schema, contract_errors = validate_submission_contract(
        user,
        office_scope=data.get("office_scope"),
        form_code=data.get("form_code"),
        schema_version=data.get("schema_version"),
        scopes=scopes,
    )
    if contract_errors:
        return None, {"validation_errors": contract_errors}, False

    normalized_payload = normalize_payload(data.get("payload") or {})
    required_errors = required_field_errors(schema, normalized_payload)

    from .accounts import get_or_create_device

    device = get_or_create_device(
        data.get("device_id"),
        device_name=data.get("device_name", ""),
        app_version=data.get("app_version", ""),
        user=user,
    )
    duplicate_summary = duplicate_check(schema.office_scope, schema.form_code, normalized_payload)
    duplicate_score = max([match.get("score", 0) for match in duplicate_summary.get("matches", [])] or [0])
    status = STATUS_DUPLICATE_RISK if duplicate_summary["duplicate_risk"] == "HIGH" else STATUS_NEEDS_REVIEW
    if required_errors:
        status = STATUS_NEEDS_REVIEW

    with transaction.atomic():
        older_versions = MobileSubmission.objects.filter(
            submitted_by=user,
            local_draft_id=data.get("local_draft_id"),
            local_version__lt=int(data.get("local_version") or 1),
        ).exclude(status__in=[STATUS_SUPERSEDED, STATUS_FAILED])
        for older_submission in older_versions:
            record_status_change(
                older_submission,
                STATUS_SUPERSEDED,
                user=user,
                note="Superseded by a newer mobile draft version.",
                request=request,
            )
        submission = MobileSubmission.objects.create(
            idempotency_key=idempotency_key,
            device=device,
            submitted_by=user,
            local_draft_id=data.get("local_draft_id"),
            local_version=data.get("local_version") or 1,
            office_scope=schema.office_scope,
            form_code=schema.form_code,
            schema_version=schema.schema_version,
            payload_json=data.get("payload") or {},
            normalized_payload_json=normalized_payload,
            status=STATUS_RECEIVED,
            validation_errors=required_errors,
            duplicate_score=duplicate_score,
            duplicate_summary=duplicate_summary,
            created_offline_at=parse_client_datetime(data.get("created_offline_at")),
        )
        log_sync_event(
            submission=submission,
            device=device,
            user=user,
            event_type="MOBILE_DRAFT_RECEIVED",
            status_after=STATUS_RECEIVED,
            request=request,
        )
        log_audit(
            "MOBILE_DRAFT_RECEIVED",
            submission,
            request=request,
            actor=user,
            new_values={
                "office_scope": submission.office_scope,
                "form_code": submission.form_code,
                "local_draft_id": submission.local_draft_id,
            },
        )
        record_status_change(
            submission,
            status,
            user=user,
            note="Duplicate check and required-field validation completed.",
            metadata={"validation_errors": required_errors, "duplicate_summary": duplicate_summary},
            request=request,
        )
        notify_mobile_submission_ready_for_review(submission)
    return submission, None, False


def status_payload_for_user(user, *, device_id="", since=None):
    scopes = user_mobile_office_scopes(user)
    submissions = MobileSubmission.objects.filter(office_scope__in=scopes).order_by("-updated_at")
    if device_id:
        submissions = submissions.filter(device__device_uuid=device_id)
    if since:
        submissions = submissions.filter(updated_at__gte=since)
    rows = []
    for submission in submissions[:250]:
        rows.append({
            "local_draft_id": submission.local_draft_id,
            "server_submission_id": str(submission.submission_uuid),
            "status": submission.status,
            "message": submission.correction_note or submission.review_notes or submission.status,
            "review_notes": submission.review_notes,
            "updated_at": submission.updated_at.isoformat(),
        })
    return rows
