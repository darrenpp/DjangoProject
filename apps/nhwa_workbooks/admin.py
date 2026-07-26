from django.contrib import admin

from .models import (
    NHWACellEntry,
    NHWACellTemplate,
    NHWAWebSheet,
    NHWAWebWorkbook,
    NHWAWorkbookAuditEvent,
)


class NHWAWebSheetInline(admin.TabularInline):
    model = NHWAWebSheet
    extra = 0
    fields = ("source_sheet_name", "title", "sort_order", "editable", "max_row", "max_column")
    readonly_fields = ("max_row", "max_column")


@admin.register(NHWAWebWorkbook)
class NHWAWebWorkbookAdmin(admin.ModelAdmin):
    list_display = ("title", "office_scope", "reporting_year", "status", "updated_at")
    list_filter = ("office_scope", "status", "reporting_year")
    search_fields = ("title", "source_title", "notes")
    prepopulated_fields = {"slug": ("office_scope", "title")}
    inlines = [NHWAWebSheetInline]


@admin.register(NHWAWebSheet)
class NHWAWebSheetAdmin(admin.ModelAdmin):
    list_display = ("title", "workbook", "source_sheet_name", "editable", "sort_order")
    list_filter = ("editable", "workbook__office_scope")
    search_fields = ("title", "source_sheet_name", "workbook__title")


@admin.register(NHWACellTemplate)
class NHWACellTemplateAdmin(admin.ModelAdmin):
    list_display = ("sheet", "coordinate", "is_editable", "is_formula", "is_heading")
    list_filter = ("is_editable", "is_formula", "is_heading", "sheet__workbook__office_scope")
    search_fields = ("coordinate", "initial_value", "formula", "sheet__source_sheet_name")
    readonly_fields = ("sheet", "coordinate", "row_index", "column_index", "column_letter")


@admin.register(NHWACellEntry)
class NHWACellEntryAdmin(admin.ModelAdmin):
    list_display = ("template", "updated_by", "updated_at")
    search_fields = ("template__coordinate", "template__sheet__source_sheet_name", "value")
    readonly_fields = ("updated_at",)


@admin.register(NHWAWorkbookAuditEvent)
class NHWAWorkbookAuditEventAdmin(admin.ModelAdmin):
    list_display = ("action", "workbook", "sheet", "actor", "created_at")
    list_filter = ("action", "workbook__office_scope")
    search_fields = ("workbook__title", "sheet__title", "actor__username")
    readonly_fields = ("created_at",)
