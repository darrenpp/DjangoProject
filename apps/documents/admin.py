from django.contrib import admin

from .models import (
    Document,
    DocumentAccessPolicy,
    DocumentApproval,
    DocumentAuditEvent,
    DocumentFolder,
    DocumentVersion,
)


class DocumentVersionInline(admin.TabularInline):
    model = DocumentVersion
    extra = 0


class DocumentAccessPolicyInline(admin.TabularInline):
    model = DocumentAccessPolicy
    extra = 0
    fk_name = "document"


class DocumentApprovalInline(admin.TabularInline):
    model = DocumentApproval
    extra = 0
    readonly_fields = ("approved_at",)


@admin.register(DocumentFolder)
class DocumentFolderAdmin(admin.ModelAdmin):
    list_display = ("name", "office_scope", "parent", "is_active", "created_at")
    list_filter = ("office_scope", "is_active")
    search_fields = ("name", "description")


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "office_scope", "status", "folder", "document_type", "is_record", "updated_at")
    list_filter = ("office_scope", "status", "is_record", "document_type")
    search_fields = ("title", "description")
    inlines = [DocumentVersionInline, DocumentApprovalInline, DocumentAccessPolicyInline]


@admin.register(DocumentVersion)
class DocumentVersionAdmin(admin.ModelAdmin):
    list_display = ("document", "version_number", "is_current", "mime_type", "uploaded_by", "uploaded_at")
    list_filter = ("is_current", "mime_type")
    search_fields = ("document__title", "original_filename", "checksum")


@admin.register(DocumentAccessPolicy)
class DocumentAccessPolicyAdmin(admin.ModelAdmin):
    list_display = ("document", "folder", "user", "role", "can_view", "can_download", "can_upload")
    list_filter = ("role", "can_view", "can_download", "can_upload")
    search_fields = ("document__title", "folder__name", "user__username")


@admin.register(DocumentAuditEvent)
class DocumentAuditEventAdmin(admin.ModelAdmin):
    list_display = ("document", "event_type", "user", "created_at")
    list_filter = ("event_type", "created_at")
    search_fields = ("document__title", "user__username")


@admin.register(DocumentApproval)
class DocumentApprovalAdmin(admin.ModelAdmin):
    list_display = ("document", "version", "status", "approved_by", "approved_at")
    list_filter = ("status", "approved_at")
    search_fields = ("document__title", "note", "approved_by__username")
    readonly_fields = ("approved_at",)
