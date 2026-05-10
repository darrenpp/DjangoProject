from django.contrib import admin

from .models import EnquiryMessage, EnquiryThread, Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "subject", "sent", "created_at")
    list_filter = ("sent", "created_at")
    search_fields = ("subject", "message", "user__username", "user__email")
    date_hierarchy = "created_at"


class EnquiryMessageInline(admin.TabularInline):
    model = EnquiryMessage
    extra = 0
    readonly_fields = ("sender", "body", "emailed", "created_at")


@admin.register(EnquiryThread)
class EnquiryThreadAdmin(admin.ModelAdmin):
    list_display = ("id", "subject", "office", "status", "created_by", "assigned_to", "updated_at")
    list_filter = ("office", "status", "created_at", "updated_at")
    search_fields = ("subject", "created_by__username", "created_by__email", "messages__body")
    date_hierarchy = "updated_at"
    inlines = [EnquiryMessageInline]


@admin.register(EnquiryMessage)
class EnquiryMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "thread", "sender", "emailed", "created_at")
    list_filter = ("emailed", "created_at")
    search_fields = ("body", "thread__subject", "sender__username")
    date_hierarchy = "created_at"
