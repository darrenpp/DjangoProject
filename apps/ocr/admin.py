from django.contrib import admin

from .models import OCRDocument


@admin.register(OCRDocument)
class OCRDocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "file", "document_version", "processing_status", "processed_at")
    list_filter = ("processing_status", "processed_at")
    search_fields = ("extracted_text", "file")
    date_hierarchy = "processed_at"
    readonly_fields = ("processed_at", "processing_error", "extracted_metadata")
