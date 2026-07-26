from django.contrib import admin

from .models import (
    ComplaintCase,
    ComplaintCaseAttachment,
    ComplaintCaseEvent,
    DisciplinaryCase,
    DisciplinaryCaseAttachment,
    DisciplinaryCaseEvent,
    RegulatoryDecisionRecord,
)


class ComplaintCaseEventInline(admin.TabularInline):
    model = ComplaintCaseEvent
    extra = 0
    readonly_fields = ("created_at",)


class ComplaintCaseAttachmentInline(admin.TabularInline):
    model = ComplaintCaseAttachment
    extra = 0
    readonly_fields = ("uploaded_at", "original_filename", "content_type", "file_size")


@admin.register(ComplaintCase)
class ComplaintCaseAdmin(admin.ModelAdmin):
    list_display = (
        "case_number",
        "title",
        "office_scope",
        "case_type",
        "status",
        "priority",
        "risk_level",
        "assigned_to",
        "updated_at",
    )
    list_filter = ("office_scope", "case_type", "status", "priority", "risk_level", "source")
    search_fields = (
        "case_number",
        "title",
        "description",
        "complainant_name",
        "complainant_email",
        "subject_name",
        "subject_identifier",
    )
    readonly_fields = ("case_uuid", "case_number", "created_at", "updated_at", "closed_at")
    inlines = [ComplaintCaseEventInline, ComplaintCaseAttachmentInline]


@admin.register(ComplaintCaseEvent)
class ComplaintCaseEventAdmin(admin.ModelAdmin):
    list_display = ("case", "action_type", "created_by", "from_status", "to_status", "created_at")
    list_filter = ("action_type", "is_public_response", "created_at")
    search_fields = ("case__case_number", "case__title", "body")
    readonly_fields = ("created_at",)


@admin.register(ComplaintCaseAttachment)
class ComplaintCaseAttachmentAdmin(admin.ModelAdmin):
    list_display = ("case", "original_filename", "uploaded_by", "file_size", "uploaded_at")
    list_filter = ("uploaded_at",)
    search_fields = ("case__case_number", "case__title", "original_filename")
    readonly_fields = ("uploaded_at", "original_filename", "content_type", "file_size")


class DisciplinaryCaseEventInline(admin.TabularInline):
    model = DisciplinaryCaseEvent
    extra = 0
    readonly_fields = ("created_at",)


class DisciplinaryCaseAttachmentInline(admin.TabularInline):
    model = DisciplinaryCaseAttachment
    extra = 0
    readonly_fields = ("uploaded_at", "original_filename", "content_type", "file_size")


@admin.register(DisciplinaryCase)
class DisciplinaryCaseAdmin(admin.ModelAdmin):
    list_display = (
        "discipline_number",
        "subject_name",
        "office_scope",
        "stage",
        "status",
        "severity",
        "assigned_to",
        "updated_at",
    )
    list_filter = ("office_scope", "stage", "status", "severity", "sanction_type")
    search_fields = (
        "discipline_number",
        "subject_name",
        "subject_identifier",
        "allegation_summary",
        "source_complaint__case_number",
    )
    readonly_fields = ("discipline_uuid", "discipline_number", "created_at", "updated_at", "closed_at")
    inlines = [DisciplinaryCaseEventInline, DisciplinaryCaseAttachmentInline]


@admin.register(DisciplinaryCaseEvent)
class DisciplinaryCaseEventAdmin(admin.ModelAdmin):
    list_display = ("case", "action_type", "created_by", "from_stage", "to_stage", "created_at")
    list_filter = ("action_type", "created_at")
    search_fields = ("case__discipline_number", "case__subject_name", "body")
    readonly_fields = ("created_at",)


@admin.register(DisciplinaryCaseAttachment)
class DisciplinaryCaseAttachmentAdmin(admin.ModelAdmin):
    list_display = ("case", "original_filename", "uploaded_by", "file_size", "uploaded_at")
    list_filter = ("uploaded_at",)
    search_fields = ("case__discipline_number", "case__subject_name", "original_filename")
    readonly_fields = ("uploaded_at", "original_filename", "content_type", "file_size")


@admin.register(RegulatoryDecisionRecord)
class RegulatoryDecisionRecordAdmin(admin.ModelAdmin):
    list_display = (
        "decision_number",
        "title",
        "office_scope",
        "decision_type",
        "status",
        "decided_by",
        "decided_at",
    )
    list_filter = ("office_scope", "decision_type", "status", "created_at")
    search_fields = (
        "decision_number",
        "title",
        "subject_name",
        "subject_identifier",
        "decision_text",
        "rationale",
    )
    readonly_fields = ("decision_uuid", "decision_number", "created_at", "updated_at")
