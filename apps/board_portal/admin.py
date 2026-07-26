from django.contrib import admin

from .models import (
    BoardActionEvidence,
    BoardCommittee,
    BoardDecisionQueueItem,
    BoardMinutes,
    BoardMotion,
    BoardNotice,
    BoardPack,
    BoardPackReadReceipt,
    BoardPaperReadReceipt,
    BoardPortalAuditEvent,
    BoardProfile,
    BoardResolution,
    BoardRiskItem,
    BoardVote,
    ConflictDeclaration,
    GovernanceLibraryItem,
)


@admin.register(BoardProfile)
class BoardProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "board_role", "is_active", "mfa_expected", "appointment_start", "appointment_end")
    list_filter = ("board_role", "is_active", "mfa_expected")
    search_fields = ("user__username", "user__first_name", "user__last_name", "appointment_reference")


@admin.register(BoardCommittee)
class BoardCommitteeAdmin(admin.ModelAdmin):
    list_display = ("name", "committee_type", "chair", "secretary", "is_active")
    list_filter = ("committee_type", "is_active")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "description")


@admin.register(BoardPack)
class BoardPackAdmin(admin.ModelAdmin):
    list_display = ("meeting", "status", "version_label", "issued_at", "issued_by", "contains_confidential", "download_restricted")
    list_filter = ("status", "contains_confidential", "download_restricted")
    search_fields = ("meeting__title", "version_label", "executive_summary")


@admin.register(BoardPackReadReceipt)
class BoardPackReadReceiptAdmin(admin.ModelAdmin):
    list_display = ("pack", "member", "marked_read_at", "acknowledged_confidentiality", "bookmarked", "last_viewed_at")
    list_filter = ("acknowledged_confidentiality", "bookmarked")
    search_fields = ("pack__meeting__title", "member__username", "member__first_name", "member__last_name")


@admin.register(BoardPaperReadReceipt)
class BoardPaperReadReceiptAdmin(admin.ModelAdmin):
    list_display = ("paper", "member", "marked_read_at", "acknowledged_confidentiality", "bookmarked", "last_viewed_at")
    list_filter = ("acknowledged_confidentiality", "bookmarked")
    search_fields = ("paper__title", "member__username", "member__first_name", "member__last_name")


@admin.register(ConflictDeclaration)
class ConflictDeclarationAdmin(admin.ModelAdmin):
    list_display = ("member", "meeting", "declaration_type", "status", "recusal_required", "declared_at")
    list_filter = ("declaration_type", "status", "recusal_required")
    search_fields = ("member__username", "meeting__title", "declaration_text")


@admin.register(BoardDecisionQueueItem)
class BoardDecisionQueueItemAdmin(admin.ModelAdmin):
    list_display = ("reference", "title", "category", "committee", "required_action", "due_date", "status", "confidentiality")
    list_filter = ("category", "status", "confidentiality", "required_action")
    search_fields = ("reference", "title", "subject", "risk_flag", "reason")


class BoardVoteInline(admin.TabularInline):
    model = BoardVote
    extra = 0


@admin.register(BoardMotion)
class BoardMotionAdmin(admin.ModelAdmin):
    list_display = ("meeting", "status", "moved_by", "seconded_by", "created_at")
    list_filter = ("status",)
    search_fields = ("motion_text", "vote_summary")
    inlines = [BoardVoteInline]


@admin.register(BoardVote)
class BoardVoteAdmin(admin.ModelAdmin):
    list_display = ("motion", "member", "vote", "recorded_at")
    list_filter = ("vote",)
    search_fields = ("member__username", "note")


@admin.register(BoardResolution)
class BoardResolutionAdmin(admin.ModelAdmin):
    list_display = ("resolution_reference", "meeting", "status", "locked_at", "created_by", "created_at")
    list_filter = ("status",)
    search_fields = ("resolution_reference", "resolution_text", "authority_reference")


@admin.register(BoardMinutes)
class BoardMinutesAdmin(admin.ModelAdmin):
    list_display = ("meeting", "status", "chair_reviewed_at", "confirmed_at", "signed_by_chair_at", "signed_by_secretary_at")
    list_filter = ("status",)
    search_fields = ("meeting__title", "draft_text", "public_safe_extract")


@admin.register(BoardActionEvidence)
class BoardActionEvidenceAdmin(admin.ModelAdmin):
    list_display = ("action_item", "document", "uploaded_by", "uploaded_at")
    search_fields = ("action_item__title", "completion_note", "document__title")


@admin.register(GovernanceLibraryItem)
class GovernanceLibraryItemAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "classification", "policy_owner", "review_due_date", "board_approved_at", "is_current")
    list_filter = ("category", "classification", "is_current")
    search_fields = ("title", "policy_owner", "document__title")


@admin.register(BoardRiskItem)
class BoardRiskItemAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "status", "owner", "due_date", "is_active")
    list_filter = ("category", "status", "is_active")
    search_fields = ("title", "summary", "source_reference")


@admin.register(BoardNotice)
class BoardNoticeAdmin(admin.ModelAdmin):
    list_display = ("title", "notice_type", "classification", "posted_by", "publish_at", "expires_at")
    list_filter = ("notice_type", "classification")
    search_fields = ("title", "message")


@admin.register(BoardPortalAuditEvent)
class BoardPortalAuditEventAdmin(admin.ModelAdmin):
    list_display = ("event_type", "user", "path", "created_at")
    list_filter = ("event_type", "created_at")
    search_fields = ("user__username", "path")
    readonly_fields = ("event_uuid", "created_at")
