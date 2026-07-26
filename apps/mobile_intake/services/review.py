from django.utils import timezone

from ..constants import (
    STATUS_ACCEPTED,
    STATUS_DUPLICATE_RISK,
    STATUS_NEEDS_CORRECTION,
    STATUS_NEEDS_REVIEW,
    STATUS_REJECTED,
    STATUS_SUPERSEDED,
)
from ..models import MobileSubmission
from ..permissions import can_decide_mobile_submission, can_review_mobile_intake
from .audit import log_audit, record_status_change
from .duplicate_check import duplicate_check
from .validation import required_field_errors


def run_validation(submission, user, request=None):
    if not can_review_mobile_intake(user, submission.office_scope):
        raise PermissionError("You cannot validate this submission.")
    schema = submission_schema(submission)
    if not schema:
        submission.validation_errors = [{"field": "schema_version", "message": "Schema is no longer enabled."}]
    else:
        submission.validation_errors = required_field_errors(schema, submission.normalized_payload_json)
    submission.save(update_fields=["validation_errors", "updated_at"])
    log_audit("MOBILE_VALIDATION_COMPLETED", submission, request=request, actor=user, new_values={"validation_errors": submission.validation_errors})
    if submission.status not in {STATUS_ACCEPTED, STATUS_REJECTED, STATUS_SUPERSEDED}:
        target = STATUS_DUPLICATE_RISK if (submission.duplicate_summary or {}).get("duplicate_risk") == "HIGH" else STATUS_NEEDS_REVIEW
        record_status_change(submission, target, user=user, note="Validation refreshed.", request=request)
    return submission


def submission_schema(submission):
    from ..models import MobileFormSchema

    return MobileFormSchema.objects.filter(
        office_scope=submission.office_scope,
        form_code=submission.form_code,
        schema_version=submission.schema_version,
        is_enabled=True,
    ).first()


def run_duplicate_check(submission, user, request=None):
    if not can_review_mobile_intake(user, submission.office_scope):
        raise PermissionError("You cannot run duplicate checks for this submission.")
    summary = duplicate_check(submission.office_scope, submission.form_code, submission.normalized_payload_json)
    submission.duplicate_summary = summary
    submission.duplicate_score = max([match.get("score", 0) for match in summary.get("matches", [])] or [0])
    submission.save(update_fields=["duplicate_summary", "duplicate_score", "updated_at"])
    log_audit("MOBILE_DUPLICATE_CHECK_RUN", submission, request=request, actor=user, new_values=summary)
    if summary.get("duplicate_risk") == "HIGH":
        record_status_change(submission, STATUS_DUPLICATE_RISK, user=user, note="High duplicate risk requires review.", request=request)
    return submission


def request_correction(submission, user, note, request=None):
    if not note:
        raise ValueError("Correction note is required.")
    if not can_decide_mobile_submission(user, submission.office_scope):
        raise PermissionError("You cannot request corrections for this submission.")
    submission.correction_note = note
    submission.review_notes = note
    submission.reviewed_by = user
    submission.reviewed_at = timezone.now()
    submission.save(update_fields=["correction_note", "review_notes", "reviewed_by", "reviewed_at", "updated_at"])
    record_status_change(submission, STATUS_NEEDS_CORRECTION, user=user, note=note, request=request)
    log_audit("MOBILE_CORRECTION_REQUESTED", submission, request=request, actor=user, new_values={"note": note})
    return submission


def reject_submission(submission, user, note, request=None):
    if not note:
        raise ValueError("Reject note is required.")
    if not can_decide_mobile_submission(user, submission.office_scope):
        raise PermissionError("You cannot reject this submission.")
    submission.review_notes = note
    submission.reviewed_by = user
    submission.reviewed_at = timezone.now()
    submission.save(update_fields=["review_notes", "reviewed_by", "reviewed_at", "updated_at"])
    record_status_change(submission, STATUS_REJECTED, user=user, note=note, request=request)
    log_audit("MOBILE_SUBMISSION_REJECTED", submission, request=request, actor=user, new_values={"note": note})
    return submission


def accept_submission(submission, user, note="", request=None):
    if not can_decide_mobile_submission(user, submission.office_scope):
        raise PermissionError("You cannot accept this submission.")
    if (submission.duplicate_summary or {}).get("duplicate_risk") == "HIGH" and not note:
        raise ValueError("A note is required to accept a high duplicate-risk submission.")
    submission.review_notes = note or submission.review_notes
    submission.reviewed_by = user
    submission.reviewed_at = timezone.now()
    submission.accepted_by = user
    submission.accepted_at = timezone.now()
    submission.save(update_fields=["review_notes", "reviewed_by", "reviewed_at", "accepted_by", "accepted_at", "updated_at"])
    record_status_change(submission, STATUS_ACCEPTED, user=user, note=note or "Submission accepted.", request=request)
    log_audit("MOBILE_SUBMISSION_ACCEPTED", submission, request=request, actor=user, new_values={"note": note})
    return submission


def mark_superseded(submission, user, note="", request=None):
    if not can_decide_mobile_submission(user, submission.office_scope):
        raise PermissionError("You cannot mark this submission superseded.")
    record_status_change(submission, STATUS_SUPERSEDED, user=user, note=note or "Marked superseded by reviewer.", request=request)
    return submission


def visible_submissions_for_user(user):
    from ..permissions import user_mobile_office_scopes

    scopes = user_mobile_office_scopes(user)
    return MobileSubmission.objects.filter(office_scope__in=scopes).select_related("submitted_by", "device", "reviewed_by")
