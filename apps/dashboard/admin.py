from django.contrib import admin

from .models import (
    AssistantFeedback,
    FAQCategory,
    FAQEntry,
    ForumCategory,
    ForumModerationLog,
    ForumPost,
    ForumTopic,
    MappedEntity,
    MappedEntityAlias,
    MappedEntityVerification,
    NursingCouncilBoardActionItem,
    NursingCouncilBoardAgendaItem,
    NursingCouncilBoardAttendance,
    NursingCouncilBoardMeeting,
    NursingCouncilBoardPaper,
    NursingAnalyticsSnapshot,
    NursingCadreStageMetric,
    NursingDataQualityMetric,
    NursingFacilityAlias,
    NursingFacilityCadreYearMetric,
    NursingInstitutionAlias,
    NursingInstitutionCadreYearMetric,
    NursingLifecycleFact,
    NursingPractitionerIndex,
    NursingProvinceYearMetric,
    NursingStandardsFieldMap,
    NursingStageYearMetric,
    PlatformConnectivityState,
    PlatformSyncOutboxItem,
    Report,
    ReportFreshnessState,
    RegistryArchiveRecord,
    Receipt,
)


@admin.register(AssistantFeedback)
class AssistantFeedbackAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'rating', 'review_status', 'requires_redaction', 'submitted_by',
        'reviewed_by', 'created_at',
    )
    list_filter = ('rating', 'review_status', 'requires_redaction')
    search_fields = ('feedback_text', 'redacted_feedback', 'reviewer_notes', 'submitted_by__username')
    readonly_fields = ('assistant_message', 'submitted_by', 'created_at', 'updated_at', 'reviewed_at')
    fieldsets = (
        ('Submitted feedback', {
            'fields': ('assistant_message', 'submitted_by', 'rating', 'feedback_text', 'requires_redaction', 'created_at'),
        }),
        ('Privacy review', {
            'fields': ('review_status', 'redacted_feedback', 'reviewed_by', 'reviewed_at', 'reviewer_notes'),
        }),
    )
    show_facets = admin.ShowFacets.NEVER


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("title", "report_type", "generated_by", "generated_at")
    list_filter = ("report_type", "generated_at")
    search_fields = ("title", "generated_by__username")
    date_hierarchy = "generated_at"


@admin.register(ReportFreshnessState)
class ReportFreshnessStateAdmin(admin.ModelAdmin):
    list_display = (
        "report_key",
        "scope",
        "data_version",
        "last_data_changed_at",
        "last_generated_at",
        "is_stale",
    )
    list_filter = ("report_key", "scope")
    search_fields = ("last_data_change_reason", "last_data_change_source", "last_generated_output")
    readonly_fields = ("updated_at",)
    show_facets = admin.ShowFacets.NEVER


@admin.register(PlatformConnectivityState)
class PlatformConnectivityStateAdmin(admin.ModelAdmin):
    list_display = (
        "key",
        "mode",
        "forced_offline",
        "sync_enabled",
        "last_checked_at",
        "last_online_at",
        "last_offline_at",
        "consecutive_failures",
    )
    readonly_fields = (
        "last_checked_at",
        "last_online_at",
        "last_offline_at",
        "last_successful_url",
        "last_error",
        "consecutive_successes",
        "consecutive_failures",
        "updated_at",
    )
    show_facets = admin.ShowFacets.NEVER


@admin.register(PlatformSyncOutboxItem)
class PlatformSyncOutboxItemAdmin(admin.ModelAdmin):
    list_display = (
        "sync_type",
        "destination",
        "status",
        "priority",
        "attempts",
        "next_attempt_at",
        "last_success_at",
        "created_at",
    )
    list_filter = ("status", "sync_type", "destination")
    search_fields = ("sync_type", "destination", "endpoint_url", "idempotency_key", "last_error")
    readonly_fields = (
        "item_uuid",
        "attempts",
        "locked_at",
        "locked_by",
        "last_attempt_at",
        "last_success_at",
        "last_error",
        "response_status_code",
        "response_body_excerpt",
        "created_at",
        "updated_at",
    )
    show_facets = admin.ShowFacets.NEVER


class NursingCouncilBoardAgendaItemInline(admin.TabularInline):
    model = NursingCouncilBoardAgendaItem
    extra = 0
    fields = ("order", "title", "purpose", "category", "confidentiality", "status", "presenter")


class NursingCouncilBoardPaperInline(admin.TabularInline):
    model = NursingCouncilBoardPaper
    extra = 0
    fields = ("title", "agenda_item", "classification", "status", "version_label", "due_at", "issued_at")


class NursingCouncilBoardAttendanceInline(admin.TabularInline):
    model = NursingCouncilBoardAttendance
    extra = 0
    fields = ("member", "role_on_board", "attendance_status", "conflict_declared", "recusal_required", "confirmed_at")
    readonly_fields = ("confirmed_at",)


class NursingCouncilBoardActionItemInline(admin.TabularInline):
    model = NursingCouncilBoardActionItem
    extra = 0
    fields = ("title", "owner", "due_date", "priority", "status", "completed_at")
    readonly_fields = ("completed_at",)


@admin.register(NursingCouncilBoardMeeting)
class NursingCouncilBoardMeetingAdmin(admin.ModelAdmin):
    list_display = ("title", "meeting_type", "scheduled_for", "status", "quorum_required", "chair", "secretary")
    list_filter = ("meeting_type", "meeting_mode", "status", "scheduled_for")
    search_fields = ("title", "location", "public_summary", "private_notes")
    date_hierarchy = "scheduled_for"
    readonly_fields = ("meeting_uuid", "created_at", "updated_at")
    inlines = (
        NursingCouncilBoardAgendaItemInline,
        NursingCouncilBoardPaperInline,
        NursingCouncilBoardAttendanceInline,
        NursingCouncilBoardActionItemInline,
    )
    show_facets = admin.ShowFacets.NEVER


@admin.register(NursingCouncilBoardAgendaItem)
class NursingCouncilBoardAgendaItemAdmin(admin.ModelAdmin):
    list_display = ("meeting", "order", "title", "purpose", "category", "confidentiality", "status")
    list_filter = ("purpose", "category", "confidentiality", "status")
    search_fields = ("title", "summary", "recommendation")
    show_facets = admin.ShowFacets.NEVER


@admin.register(NursingCouncilBoardPaper)
class NursingCouncilBoardPaperAdmin(admin.ModelAdmin):
    list_display = ("title", "meeting", "agenda_item", "classification", "status", "version_label", "due_at", "issued_at")
    list_filter = ("classification", "status", "meeting")
    search_fields = ("title", "version_label", "document__title")
    show_facets = admin.ShowFacets.NEVER


@admin.register(NursingCouncilBoardAttendance)
class NursingCouncilBoardAttendanceAdmin(admin.ModelAdmin):
    list_display = ("meeting", "member", "role_on_board", "attendance_status", "conflict_declared", "recusal_required", "confirmed_at")
    list_filter = ("role_on_board", "attendance_status", "conflict_declared", "recusal_required")
    search_fields = ("member__username", "member__first_name", "member__last_name", "conflict_note")
    readonly_fields = ("confirmed_at",)
    show_facets = admin.ShowFacets.NEVER


@admin.register(NursingCouncilBoardActionItem)
class NursingCouncilBoardActionItemAdmin(admin.ModelAdmin):
    list_display = ("title", "meeting", "owner", "due_date", "priority", "status", "completed_at")
    list_filter = ("priority", "status", "due_date")
    search_fields = ("title", "description", "owner__username")
    readonly_fields = ("completed_at",)
    show_facets = admin.ShowFacets.NEVER


@admin.register(NursingAnalyticsSnapshot)
class NursingAnalyticsSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "source_file_name",
        "is_active",
        "workbook_generated_on",
        "imported_rows",
        "source_file_hash",
        "created_at",
    )
    list_filter = ("is_active", "workbook_generated_on")
    search_fields = ("source_file_name", "source_file_hash")
    readonly_fields = (
        "snapshot_id",
        "source_file_hash",
        "sheet_row_counts",
        "kpi_summary",
        "filter_options",
        "import_summary",
        "created_at",
        "activated_at",
    )
    show_facets = admin.ShowFacets.NEVER


@admin.register(NursingLifecycleFact)
class NursingLifecycleFactAdmin(admin.ModelAdmin):
    list_display = ("record_id", "lifecycle_stage", "cycle_year", "full_name", "cadre", "province", "record_quality")
    list_filter = ("lifecycle_stage", "cycle_year", "record_quality", "province")
    search_fields = ("record_id", "full_name", "registration_no", "practitioner_no", "person_group_key")
    show_facets = admin.ShowFacets.NEVER


@admin.register(NursingPractitionerIndex)
class NursingPractitionerIndexAdmin(admin.ModelAdmin):
    list_display = ("practitioner_group_id", "representative_name", "record_count", "latest_year", "has_atp", "needs_manual_review")
    list_filter = ("has_provisional", "has_full_licence", "has_atp", "needs_manual_review")
    search_fields = ("practitioner_group_id", "representative_name", "person_group_key")
    show_facets = admin.ShowFacets.NEVER


@admin.register(RegistryArchiveRecord)
class RegistryArchiveRecordAdmin(admin.ModelAdmin):
    list_display = (
        "source_label",
        "scope",
        "archive_reason",
        "archive_status",
        "age",
        "latest_renewal_year",
        "registration_no",
        "archived_at",
    )
    list_filter = ("scope", "archive_reason", "archive_status", "record_year", "latest_renewal_year")
    search_fields = ("source_label", "registration_no", "practitioner_number", "cadre", "facility", "province")
    readonly_fields = ("archive_uuid", "archive_key", "archived_at", "updated_at")
    show_facets = admin.ShowFacets.NEVER


@admin.register(NursingStageYearMetric)
class NursingStageYearMetricAdmin(admin.ModelAdmin):
    list_display = ("year", "provisional_licence_count", "full_licence_count", "authority_to_practice_count", "grand_total")
    list_filter = ("year",)
    show_facets = admin.ShowFacets.NEVER


@admin.register(NursingCadreStageMetric)
class NursingCadreStageMetricAdmin(admin.ModelAdmin):
    list_display = ("cadre", "cadre_group", "provisional_licence_count", "full_licence_count", "authority_to_practice_count", "grand_total")
    list_filter = ("cadre_group",)
    search_fields = ("cadre",)
    show_facets = admin.ShowFacets.NEVER


@admin.register(NursingProvinceYearMetric)
class NursingProvinceYearMetricAdmin(admin.ModelAdmin):
    list_display = ("province", "year_label", "count")
    list_filter = ("year", "province")
    search_fields = ("province",)
    show_facets = admin.ShowFacets.NEVER


@admin.register(NursingFacilityCadreYearMetric)
class NursingFacilityCadreYearMetricAdmin(admin.ModelAdmin):
    list_display = ("facility", "province", "organization_type", "cadre", "year_label", "count")
    list_filter = ("province", "organization_type", "cadre", "year")
    search_fields = ("facility",)
    show_facets = admin.ShowFacets.NEVER


@admin.register(NursingInstitutionCadreYearMetric)
class NursingInstitutionCadreYearMetricAdmin(admin.ModelAdmin):
    list_display = ("institution", "lifecycle_stage", "cadre", "year_label", "count")
    list_filter = ("lifecycle_stage", "cadre", "year")
    search_fields = ("institution",)
    show_facets = admin.ShowFacets.NEVER


@admin.register(NursingDataQualityMetric)
class NursingDataQualityMetricAdmin(admin.ModelAdmin):
    list_display = ("lifecycle_stage", "high_count", "medium_count", "needs_review_count", "grand_total", "needs_review_percent")
    list_filter = ("lifecycle_stage",)
    show_facets = admin.ShowFacets.NEVER


@admin.register(NursingStandardsFieldMap)
class NursingStandardsFieldMapAdmin(admin.ModelAdmin):
    list_display = ("map_type", "unified_field", "platform_field")
    list_filter = ("map_type",)
    search_fields = ("unified_field", "platform_field", "fhir_mapping", "nhwa_dimension")
    show_facets = admin.ShowFacets.NEVER


@admin.register(NursingInstitutionAlias)
class NursingInstitutionAliasAdmin(admin.ModelAdmin):
    list_display = ("raw_name", "normalized_name", "status", "verified_institution")
    list_filter = ("status",)
    search_fields = ("raw_name", "normalized_name")
    show_facets = admin.ShowFacets.NEVER


@admin.register(NursingFacilityAlias)
class NursingFacilityAliasAdmin(admin.ModelAdmin):
    list_display = ("raw_name", "province", "organization_type", "status", "verified_facility")
    list_filter = ("status", "province", "organization_type")
    search_fields = ("raw_name", "normalized_name")
    show_facets = admin.ShowFacets.NEVER


@admin.register(FAQCategory)
class FAQCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "audience", "office_scope", "display_order", "is_active")
    list_filter = ("audience", "office_scope", "is_active")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "description")
    show_facets = admin.ShowFacets.NEVER


@admin.register(FAQEntry)
class FAQEntryAdmin(admin.ModelAdmin):
    list_display = ("question", "category", "display_order", "is_published")
    list_filter = ("category", "is_published")
    search_fields = ("question", "answer", "keywords")
    show_facets = admin.ShowFacets.NEVER


@admin.register(ForumCategory)
class ForumCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "visibility", "office_scope", "requires_moderation", "allow_public_posts", "is_active")
    list_filter = ("visibility", "office_scope", "requires_moderation", "is_active")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "description")
    show_facets = admin.ShowFacets.NEVER


@admin.register(ForumTopic)
class ForumTopicAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "status", "is_pinned", "is_locked", "last_post_at", "created_at")
    list_filter = ("status", "category", "is_pinned", "is_locked")
    search_fields = ("title", "public_author_name", "author__username")
    show_facets = admin.ShowFacets.NEVER


@admin.register(ForumPost)
class ForumPostAdmin(admin.ModelAdmin):
    list_display = ("topic", "status", "author", "public_author_name", "created_at", "moderated_at")
    list_filter = ("status", "topic__category")
    search_fields = ("body", "public_author_name", "author__username", "topic__title")
    show_facets = admin.ShowFacets.NEVER


@admin.register(ForumModerationLog)
class ForumModerationLogAdmin(admin.ModelAdmin):
    list_display = ("action", "category", "topic", "actor", "created_at")
    list_filter = ("action", "category")
    search_fields = ("topic__title", "post__body", "note", "actor__username")
    show_facets = admin.ShowFacets.NEVER


@admin.register(MappedEntity)
class MappedEntityAdmin(admin.ModelAdmin):
    list_display = ("name", "entity_type", "office_scope", "province", "verification_status", "active_workforce_count")
    list_filter = ("entity_type", "office_scope", "province", "verification_status", "is_active")
    search_fields = ("name", "normalized_name", "google_place_id", "dhis2_org_unit_id")
    show_facets = admin.ShowFacets.NEVER


@admin.register(MappedEntityAlias)
class MappedEntityAliasAdmin(admin.ModelAdmin):
    list_display = ("raw_name", "entity", "status", "source", "confidence")
    list_filter = ("status", "source")
    search_fields = ("raw_name", "normalized_name", "entity__name")
    show_facets = admin.ShowFacets.NEVER


@admin.register(MappedEntityVerification)
class MappedEntityVerificationAdmin(admin.ModelAdmin):
    list_display = ("entity", "previous_status", "new_status", "verified_by", "created_at")
    list_filter = ("new_status",)
    search_fields = ("entity__name", "note")
    show_facets = admin.ShowFacets.NEVER


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = (
        "receipt_number",
        "official_receipt_no",
        "user",
        "payer_record",
        "payer_match_confidence",
        "amount",
        "status",
        "transaction_date",
    )
    list_filter = ("status", "payment_method", "payer_match_confidence")
    search_fields = (
        "receipt_number",
        "official_receipt_no",
        "user__username",
        "practitioner_number",
        "payer_match_notes",
    )
    date_hierarchy = "transaction_date"
    readonly_fields = ("receipt_number", "transaction_date", "payer_linked_at")
    show_facets = admin.ShowFacets.NEVER
