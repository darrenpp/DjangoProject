from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from apps.documents.models import Document, DocumentAuditEvent, DocumentVersion
from apps.workforce.models import Application, ApplicationFormResponse, ApplicationStatusHistory, DocumentType, EmploymentRecord

from ..constants import STATUS_ACCEPTED, STATUS_DUPLICATE_RISK, STATUS_PROMOTED
from ..models import MobilePromotionLink
from .audit import log_audit, record_status_change


def _payload(submission):
    return submission.normalized_payload_json or submission.payload_json or {}


def _document_type(document_type_name):
    if not document_type_name:
        return None
    return DocumentType.objects.filter(name__iexact=document_type_name).first() or DocumentType.objects.filter(name__icontains=document_type_name).first()


def _metadata(submission, extra=None):
    payload = _payload(submission)
    metadata = {
        "source": "mobile_intake",
        "mobile_submission_id": str(submission.submission_uuid),
        "form_code": submission.form_code,
        "office_scope": submission.office_scope,
        "applicant_name": submission.applicant_name,
        "registration_number": payload.get("registration_number", ""),
        "practitioner_number": payload.get("practitioner_number", ""),
        "licence_number": payload.get("licence_number") or payload.get("license_number", ""),
        "receipt_number": payload.get("receipt_number", ""),
    }
    if extra:
        metadata.update(extra)
    return metadata


def _ensure_promotable(submission, *, waive_missing=False, waive_duplicate=False, note=""):
    if submission.status != STATUS_ACCEPTED:
        raise ValueError("Only accepted mobile submissions can be promoted.")
    if submission.validation_errors and not waive_missing:
        raise ValueError("Submission has missing required fields.")
    if (submission.duplicate_summary or {}).get("duplicate_risk") == "HIGH" and not waive_duplicate:
        raise ValueError("High duplicate-risk submission requires an override note before promotion.")
    if (waive_missing or waive_duplicate) and not note:
        raise ValueError("A note is required for override or waiver promotion.")


def promote_to_application(submission, user, *, note="", waive_missing=False, waive_duplicate=False, request=None):
    _ensure_promotable(submission, waive_missing=waive_missing, waive_duplicate=waive_duplicate, note=note)
    payload = _payload(submission)
    pathway = "medical_board" if submission.office_scope == "medical" else "other"
    with transaction.atomic():
        application = Application.objects.create(
            form_code=submission.form_code,
            pathway=pathway,
            form_title=f"{submission.form_code} mobile intake",
            profession_track=payload.get("cadre") or payload.get("cadre_name", ""),
            status="approved",
            approved_date=timezone.localdate(),
            reviewer_notes=note or f"Promoted from mobile intake {submission.submission_uuid}.",
            reviewed_by=user,
            payload={
                "source": "mobile_intake",
                "mobile_submission_uuid": str(submission.submission_uuid),
                "office_scope": submission.office_scope,
                "form_code": submission.form_code,
                "schema_version": submission.schema_version,
                "payload": submission.payload_json,
                "normalized_payload": submission.normalized_payload_json,
                "duplicate_summary": submission.duplicate_summary,
            },
        )
        ApplicationFormResponse.objects.update_or_create(
            application=application,
            form_code=submission.form_code,
            form_version=submission.schema_version,
            defaults={
                "response_json": application.payload,
                "submitted_by": submission.submitted_by,
            },
        )
        ApplicationStatusHistory.objects.create(
            application=application,
            old_status="",
            new_status="approved",
            changed_by=user,
            reason="mobile_intake_promotion",
            comment=note,
        )
        MobilePromotionLink.objects.create(
            submission=submission,
            target_type="workforce.Application",
            target_id=str(application.pk),
            action="application_created",
            metadata=_metadata(submission),
            promoted_by=user,
        )
        submission.promoted_object_type = "workforce.Application"
        submission.promoted_object_id = str(application.pk)
        submission.save(update_fields=["promoted_object_type", "promoted_object_id", "updated_at"])
        log_audit("MOBILE_SUBMISSION_PROMOTED", submission, request=request, actor=user, new_values={"application_id": application.pk})
    return application


def promote_employment(submission, user, *, request=None):
    payload = _payload(submission)
    employment = EmploymentRecord.objects.create(
        employer_name=payload.get("employer_name") or payload.get("facility") or "",
        position_held=payload.get("position_title", ""),
        employment_status=payload.get("employment_status") or "unknown",
        area_of_employment=payload.get("employment_sector") or "unknown",
        place_of_work=payload.get("facility") or payload.get("facility_name_raw") or "",
        business_address=payload.get("district") or payload.get("province") or "",
        function_type=payload.get("workforce_function", ""),
    )
    for field_name in (
        "employment_sector",
        "facility_id",
        "facility_name_raw",
        "province",
        "district",
        "position_title",
        "workforce_function",
        "start_date",
        "end_date",
        "is_current",
        "source_type",
        "source_submission",
        "source_file",
        "source_sheet",
        "source_row",
        "review_status",
    ):
        if hasattr(employment, field_name):
            value = payload.get(field_name)
            if field_name == "source_submission":
                value = str(submission.submission_uuid)
            elif field_name == "source_type":
                value = "mobile_intake"
            elif field_name == "review_status":
                value = "accepted"
            setattr(employment, field_name, value or getattr(employment, field_name))
    employment.save()
    MobilePromotionLink.objects.create(
        submission=submission,
        target_type="workforce.EmploymentRecord",
        target_id=str(employment.pk),
        action="employment_created",
        metadata=_metadata(submission),
        promoted_by=user,
    )
    log_audit("MOBILE_EMPLOYMENT_PROMOTED", employment, request=request, actor=user, new_values=_metadata(submission))
    return employment


def link_attachments_to_repository(submission, user, *, request=None):
    linked = []
    submission_ct = ContentType.objects.get_for_model(submission)
    for attachment in submission.attachments.all():
        if attachment.repository_document_id and attachment.repository_version_id:
            linked.append(attachment)
            continue
        document = Document.objects.create(
            title=f"{submission.form_code} {attachment.document_type} - {submission.applicant_name or submission.local_draft_id}",
            description="Mobile intake evidence linked after review.",
            office_scope=submission.office_scope,
            document_type=_document_type(attachment.document_type),
            status="active",
            metadata=_metadata(submission, {
                "document_type": attachment.document_type,
                "original_filename": attachment.original_filename,
                "sha256_checksum": attachment.sha256_checksum,
                "local_attachment_uuid": attachment.local_attachment_uuid,
            }),
            is_record=True,
            related_content_type=submission_ct,
            related_object_id=submission.pk,
            created_by=user,
        )
        version = DocumentVersion.objects.create(
            document=document,
            file=attachment.file,
            original_filename=attachment.original_filename,
            mime_type=attachment.content_type,
            file_size=attachment.file_size,
            checksum=attachment.sha256_checksum,
            uploaded_by=user,
        )
        DocumentAuditEvent.objects.create(document=document, version=version, user=user, event_type="created", details=_metadata(submission))
        DocumentAuditEvent.objects.create(document=document, version=version, user=user, event_type="uploaded", details={"source": "mobile_intake"})
        DocumentAuditEvent.objects.create(document=document, version=version, user=user, event_type="linked", details={"mobile_attachment_id": attachment.pk})
        attachment.repository_document = document
        attachment.repository_version = version
        attachment.upload_status = "LINKED"
        attachment.save(update_fields=["repository_document", "repository_version", "upload_status"])
        MobilePromotionLink.objects.create(
            submission=submission,
            target_type="documents.Document",
            target_id=str(document.pk),
            action="document_linked",
            metadata={"attachment_id": attachment.pk, "version_id": version.pk},
            promoted_by=user,
        )
        log_audit("MOBILE_DOCUMENT_LINKED", document, request=request, actor=user, new_values={"attachment_id": attachment.pk})
        linked.append(attachment)
    return linked


def promote_submission(submission, user, *, note="", waive_missing=False, waive_duplicate=False, request=None):
    if submission.status == STATUS_DUPLICATE_RISK and not waive_duplicate:
        raise ValueError("Duplicate-risk submissions need registrar override before promotion.")
    application = promote_to_application(
        submission,
        user,
        note=note,
        waive_missing=waive_missing,
        waive_duplicate=waive_duplicate,
        request=request,
    )
    employment = promote_employment(submission, user, request=request)
    link_attachments_to_repository(submission, user, request=request)
    record_status_change(submission, STATUS_PROMOTED, user=user, note=note or "Submission promoted.", request=request)
    return {"application": application, "employment": employment}
