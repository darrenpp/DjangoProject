from django.contrib import admin

from .models import EnquiryMailboxState, EnquiryMessage, EnquiryMessageAttachment, EnquiryThread, Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "subject", "sent", "created_at")
    list_filter = ("sent", "created_at")
    search_fields = ("subject", "message", "user__username", "user__email")
    date_hierarchy = "created_at"


class EnquiryMessageAttachmentInline(admin.TabularInline):
    model = EnquiryMessageAttachment
    extra = 0
    readonly_fields = ("original_filename", "content_type", "file_size", "uploaded_at")


class EnquiryMessageInline(admin.TabularInline):
    model = EnquiryMessage
    extra = 0
    readonly_fields = ("sender", "body", "emailed", "created_at")


@admin.register(EnquiryThread)
class EnquiryThreadAdmin(admin.ModelAdmin):
    list_display = ("id", "subject", "office", "status", "delivery_channel", "created_by", "recipient_name", "assigned_to", "updated_at")
    list_filter = ("office", "status", "delivery_channel", "created_at", "updated_at")
    search_fields = (
        "subject",
        "created_by__username",
        "created_by__email",
        "recipient_name",
        "recipient_email",
        "messages__body",
    )
    date_hierarchy = "updated_at"
    inlines = [EnquiryMessageInline]


@admin.register(EnquiryMessage)
class EnquiryMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "thread", "sender", "emailed", "created_at")
    list_filter = ("emailed", "created_at")
    search_fields = ("body", "thread__subject", "sender__username")
    date_hierarchy = "created_at"
    inlines = [EnquiryMessageAttachmentInline]


@admin.register(EnquiryMessageAttachment)
class EnquiryMessageAttachmentAdmin(admin.ModelAdmin):
    list_display = ("id", "message", "original_filename", "content_type", "file_size", "uploaded_at")
    list_filter = ("content_type", "uploaded_at")
    search_fields = ("original_filename", "message__body", "message__thread__subject")
    date_hierarchy = "uploaded_at"


@admin.register(EnquiryMailboxState)
class EnquiryMailboxStateAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "thread", "folder", "read_at", "last_read_message", "updated_at")
    list_filter = ("folder", "read_at", "updated_at")
    search_fields = ("user__username", "user__email", "thread__subject", "notes")
    date_hierarchy = "updated_at"
