import hashlib

from django.core.exceptions import ValidationError

from ..constants import ALLOWED_ATTACHMENT_TYPES, MAX_ATTACHMENT_BYTES
from ..models import MobileSubmissionAttachment
from .audit import log_audit, log_sync_event


def calculate_sha256(uploaded_file):
    hasher = hashlib.sha256()
    position = uploaded_file.tell() if hasattr(uploaded_file, "tell") else None
    for chunk in uploaded_file.chunks():
        hasher.update(chunk)
    if position is not None:
        uploaded_file.seek(position)
    else:
        uploaded_file.seek(0)
    return hasher.hexdigest()


def validate_upload(uploaded_file):
    content_type = getattr(uploaded_file, "content_type", "") or ""
    if content_type not in ALLOWED_ATTACHMENT_TYPES:
        raise ValidationError("Attachment type is not allowed.")
    if getattr(uploaded_file, "size", 0) > MAX_ATTACHMENT_BYTES:
        raise ValidationError("Attachment is larger than the mobile intake limit.")


def receive_attachment(submission, *, local_attachment_uuid, uploaded_file, document_type, created_offline_at=None, request=None):
    validate_upload(uploaded_file)
    checksum = calculate_sha256(uploaded_file)
    attachment, created = MobileSubmissionAttachment.objects.get_or_create(
        submission=submission,
        local_attachment_uuid=local_attachment_uuid,
        defaults={
            "file": uploaded_file,
            "original_filename": getattr(uploaded_file, "name", ""),
            "content_type": getattr(uploaded_file, "content_type", ""),
            "file_size": getattr(uploaded_file, "size", 0) or 0,
            "sha256_checksum": checksum,
            "document_type": document_type,
            "office_scope": submission.office_scope,
            "created_offline_at": created_offline_at,
        },
    )
    duplicate_count = MobileSubmissionAttachment.objects.filter(sha256_checksum=checksum).exclude(pk=attachment.pk).count()
    log_sync_event(
        submission=submission,
        device=submission.device,
        user=request.user if request else None,
        event_type="MOBILE_ATTACHMENT_UPLOADED",
        status_after=submission.status,
        message=f"Attachment {attachment.original_filename} received.",
        request=request,
    )
    log_audit(
        "MOBILE_ATTACHMENT_UPLOADED",
        attachment,
        request=request,
        new_values={
            "submission_uuid": str(submission.submission_uuid),
            "document_type": document_type,
            "sha256_checksum": checksum,
            "duplicate_checksum_count": duplicate_count,
            "idempotent": not created,
        },
    )
    return attachment, duplicate_count
