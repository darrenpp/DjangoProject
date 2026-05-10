from django.contrib import admin

from .models import Report, Receipt


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("title", "report_type", "generated_by", "generated_at")
    list_filter = ("report_type", "generated_at")
    search_fields = ("title", "generated_by__username")
    date_hierarchy = "generated_at"


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ("receipt_number", "official_receipt_no", "user", "amount", "status", "transaction_date")
    list_filter = ("status", "payment_method")
    search_fields = ("receipt_number", "official_receipt_no", "user__username")
    date_hierarchy = "transaction_date"
    readonly_fields = ("receipt_number", "transaction_date")
    show_facets = admin.ShowFacets.NEVER
