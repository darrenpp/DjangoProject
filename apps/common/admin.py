from django.contrib import admin

from .models import DeceasedRecord, DuplicateReviewQueue


@admin.register(DuplicateReviewQueue)
class DuplicateReviewQueueAdmin(admin.ModelAdmin):
    list_display = ("id", "content_type", "object_id", "similarity_score", "status", "reviewed_by", "review_date")
    list_filter = ("status", "content_type", "review_date")
    search_fields = ("object_id", "reviewed_by__username")
    readonly_fields = ("record",)


@admin.register(DeceasedRecord)
class DeceasedRecordAdmin(admin.ModelAdmin):
    list_display = ("id", "content_type", "object_id", "date_of_death", "reported_by", "reported_date", "status")
    list_filter = ("status", "date_of_death", "reported_date", "content_type")
    search_fields = ("object_id", "reported_by__username")
    readonly_fields = ("professional", "reported_date")
