from django.contrib import admin

from .models import (
    MobileDevice,
    MobileFormSchema,
    MobileLocalAccountRequest,
    MobilePromotionLink,
    MobileSubmission,
    MobileSubmissionAttachment,
    MobileSubmissionStatusHistory,
    MobileSyncEvent,
)


@admin.register(MobileDevice)
class MobileDeviceAdmin(admin.ModelAdmin):
    list_display = ("device_uuid", "device_name", "platform", "app_version", "risk_status", "is_active", "last_seen_at")
    search_fields = ("device_uuid", "device_name", "app_version")
    list_filter = ("platform", "risk_status", "is_active")


@admin.register(MobileLocalAccountRequest)
class MobileLocalAccountRequestAdmin(admin.ModelAdmin):
    list_display = ("username", "full_name", "office_scope", "requested_role", "status", "reviewed_by", "updated_at")
    search_fields = ("username", "full_name", "email", "phone", "local_account_uuid")
    list_filter = ("office_scope", "requested_role", "status")


@admin.register(MobileFormSchema)
class MobileFormSchemaAdmin(admin.ModelAdmin):
    list_display = ("form_code", "form_name", "office_scope", "schema_version", "is_enabled", "updated_at")
    search_fields = ("form_code", "form_name", "schema_version")
    list_filter = ("office_scope", "is_enabled")


class MobileSubmissionAttachmentInline(admin.TabularInline):
    model = MobileSubmissionAttachment
    extra = 0
    fields = ("document_type", "original_filename", "content_type", "file_size", "sha256_checksum", "upload_status", "repository_document")
    readonly_fields = ("sha256_checksum",)


@admin.register(MobileSubmission)
class MobileSubmissionAdmin(admin.ModelAdmin):
    list_display = ("submission_uuid", "form_code", "office_scope", "applicant_name", "status", "duplicate_score", "submitted_by", "received_at")
    search_fields = ("submission_uuid", "idempotency_key", "local_draft_id", "form_code", "normalized_payload_json")
    list_filter = ("office_scope", "form_code", "status", "schema_version")
    inlines = [MobileSubmissionAttachmentInline]
    readonly_fields = ("submission_uuid", "received_at", "updated_at")


@admin.register(MobileSubmissionAttachment)
class MobileSubmissionAttachmentAdmin(admin.ModelAdmin):
    list_display = ("submission", "document_type", "original_filename", "office_scope", "upload_status", "received_at")
    search_fields = ("original_filename", "sha256_checksum", "local_attachment_uuid")
    list_filter = ("office_scope", "document_type", "upload_status")


@admin.register(MobileSyncEvent)
class MobileSyncEventAdmin(admin.ModelAdmin):
    list_display = ("event_type", "submission", "device", "user", "status_before", "status_after", "created_at")
    search_fields = ("event_type", "message", "submission__submission_uuid", "device__device_uuid", "user__username")
    list_filter = ("event_type", "status_after")


@admin.register(MobileSubmissionStatusHistory)
class MobileSubmissionStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ("submission", "old_status", "new_status", "changed_by", "created_at")
    search_fields = ("submission__submission_uuid", "note")
    list_filter = ("new_status",)


@admin.register(MobilePromotionLink)
class MobilePromotionLinkAdmin(admin.ModelAdmin):
    list_display = ("submission", "target_type", "target_id", "action", "promoted_by", "promoted_at")
    search_fields = ("submission__submission_uuid", "target_type", "target_id")
    list_filter = ("target_type", "action")
