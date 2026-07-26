from uuid import uuid4

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone


class BoardProfile(models.Model):
    BOARD_ROLE_CHOICES = [
        ("chair", "Board Chair"),
        ("deputy_chair", "Deputy Chair"),
        ("board_member", "Board Member"),
        ("registrar", "Registrar"),
        ("secretariat", "Secretariat"),
        ("committee_chair", "Committee Chair"),
        ("committee_member", "Committee Member"),
        ("legal_advisor", "Legal Advisor / Observer"),
        ("system_admin", "System Admin"),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="board_profile")
    board_role = models.CharField(max_length=30, choices=BOARD_ROLE_CHOICES, default="board_member", db_index=True)
    appointment_reference = models.CharField(max_length=120, blank=True)
    appointment_start = models.DateField(null=True, blank=True)
    appointment_end = models.DateField(null=True, blank=True)
    committee_access = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    mfa_expected = models.BooleanField(default=True)
    induction_completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["board_role", "user__last_name", "user__first_name"]

    def __str__(self):
        return f"{self.user} - {self.get_board_role_display()}"


class BoardCommittee(models.Model):
    COMMITTEE_TYPE_CHOICES = [
        ("registration", "Registration Committee"),
        ("education", "Education Committee"),
        ("standards", "Standards Committee"),
        ("conduct", "Disciplinary / Professional Conduct Committee"),
        ("governance", "Governance Committee"),
        ("risk", "Risk and Compliance Committee"),
    ]

    name = models.CharField(max_length=180)
    slug = models.SlugField(max_length=80, unique=True)
    committee_type = models.CharField(max_length=30, choices=COMMITTEE_TYPE_CHOICES, db_index=True)
    description = models.TextField(blank=True)
    chair = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="chaired_board_committees")
    secretary = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="secretary_board_committees")
    terms_of_reference_document = models.ForeignKey("documents.Document", on_delete=models.SET_NULL, null=True, blank=True, related_name="board_committee_terms")
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["committee_type", "name"]

    def __str__(self):
        return self.name


class BoardPack(models.Model):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("secretariat_review", "Ready for Secretariat Review"),
        ("chair_review", "Ready for Chair Review"),
        ("ready", "Ready for Board Pack"),
        ("issued", "Issued to Members"),
        ("superseded", "Superseded"),
        ("archived", "Archived"),
    ]

    pack_uuid = models.UUIDField(default=uuid4, editable=False, unique=True)
    meeting = models.OneToOneField("dashboard.NursingCouncilBoardMeeting", on_delete=models.CASCADE, related_name="board_pack")
    version_label = models.CharField(max_length=40, default="v1")
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="draft", db_index=True)
    issued_at = models.DateTimeField(null=True, blank=True)
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="issued_board_packs")
    executive_summary = models.TextField(blank=True)
    ai_summary = models.TextField(blank=True, help_text="Advisory only. Secretariat and Chair review remain required.")
    missing_items = models.JSONField(default=list, blank=True)
    contains_confidential = models.BooleanField(default=False)
    download_restricted = models.BooleanField(default=False)
    locked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-meeting__scheduled_for"]
        indexes = [
            models.Index(fields=["status", "issued_at"]),
        ]

    @property
    def is_locked(self):
        return bool(self.locked_at)

    def __str__(self):
        return f"{self.meeting.title} board pack"


class BoardPackReadReceipt(models.Model):
    pack = models.ForeignKey(BoardPack, on_delete=models.CASCADE, related_name="read_receipts")
    member = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="board_pack_read_receipts")
    marked_read_at = models.DateTimeField(null=True, blank=True)
    acknowledged_confidentiality = models.BooleanField(default=False)
    private_notes = models.TextField(blank=True)
    bookmarked = models.BooleanField(default=False)
    last_viewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("pack", "member")
        ordering = ["pack", "member__last_name", "member__first_name"]

    def mark_viewed(self):
        self.last_viewed_at = timezone.now()
        self.save(update_fields=["last_viewed_at"])

    def __str__(self):
        return f"{self.member} - {self.pack}"


class BoardPaperReadReceipt(models.Model):
    paper = models.ForeignKey("dashboard.NursingCouncilBoardPaper", on_delete=models.CASCADE, related_name="read_receipts")
    member = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="board_paper_read_receipts")
    marked_read_at = models.DateTimeField(null=True, blank=True)
    acknowledged_confidentiality = models.BooleanField(default=False)
    private_notes = models.TextField(blank=True)
    bookmarked = models.BooleanField(default=False)
    last_viewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("paper", "member")
        ordering = ["paper", "member__last_name", "member__first_name"]

    def __str__(self):
        return f"{self.member} - {self.paper}"


class ConflictDeclaration(models.Model):
    DECLARATION_TYPE_CHOICES = [
        ("annual", "Annual declaration"),
        ("meeting", "Meeting declaration"),
        ("agenda_item", "Agenda item declaration"),
    ]
    STATUS_CHOICES = [
        ("no_conflict", "No conflict"),
        ("declared", "Conflict declared"),
        ("recused", "Recused"),
        ("review_required", "Review required"),
    ]

    meeting = models.ForeignKey("dashboard.NursingCouncilBoardMeeting", on_delete=models.CASCADE, related_name="conflict_declarations")
    agenda_item = models.ForeignKey("dashboard.NursingCouncilBoardAgendaItem", on_delete=models.SET_NULL, null=True, blank=True, related_name="conflict_declarations")
    member = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="board_conflict_declarations")
    declaration_type = models.CharField(max_length=20, choices=DECLARATION_TYPE_CHOICES, default="meeting")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="no_conflict", db_index=True)
    declaration_text = models.TextField(blank=True)
    recusal_required = models.BooleanField(default=False)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="reviewed_board_conflicts")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    declared_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-declared_at"]
        indexes = [
            models.Index(fields=["meeting", "status"]),
            models.Index(fields=["member", "status"]),
        ]

    def __str__(self):
        return f"{self.member} - {self.get_status_display()}"


class BoardDecisionQueueItem(models.Model):
    CATEGORY_CHOICES = [
        ("provisional_registration", "Provisional registration"),
        ("full_registration", "Full registration"),
        ("licence_renewal", "Licence renewal"),
        ("provisional_to_full", "Provisional-to-full conversion"),
        ("overseas_registration", "Overseas registration"),
        ("temporary_registration", "Temporary registration"),
        ("restoration", "Restoration / re-registration"),
        ("education_accreditation", "Education accreditation"),
        ("institution_approval", "Training institution approval"),
        ("policy_standard", "Policy / standard approval"),
        ("complaint_discipline", "Complaint / discipline decision"),
        ("appeal_review", "Appeal / review matter"),
        ("finance_fee", "Fee or finance-related decision"),
    ]
    RECOMMENDATION_CHOICES = [
        ("approve", "Approve"),
        ("approve_conditions", "Approve with conditions"),
        ("defer", "Defer"),
        ("reject", "Reject"),
        ("request_information", "Request more information"),
        ("return_committee", "Return to committee"),
        ("refer_registrar", "Refer to Registrar"),
        ("note", "Note"),
    ]
    STATUS_CHOICES = [
        ("ready", "Ready"),
        ("needs_review", "Needs review"),
        ("deferred", "Deferred"),
        ("approved", "Approved"),
        ("approved_conditions", "Approved with conditions"),
        ("rejected", "Rejected"),
        ("information_requested", "Information requested"),
        ("returned_to_committee", "Returned to committee"),
        ("closed", "Closed"),
    ]
    CONFIDENTIALITY_CHOICES = [
        ("public", "Public"),
        ("internal", "Internal"),
        ("confidential", "Confidential"),
        ("highly_confidential", "Highly confidential"),
    ]

    queue_uuid = models.UUIDField(default=uuid4, editable=False, unique=True)
    reference = models.CharField(max_length=120, blank=True)
    title = models.CharField(max_length=255)
    subject = models.CharField(max_length=255, blank=True)
    category = models.CharField(max_length=40, choices=CATEGORY_CHOICES, default="provisional_registration", db_index=True)
    committee = models.ForeignKey(BoardCommittee, on_delete=models.SET_NULL, null=True, blank=True, related_name="decision_items")
    committee_recommendation = models.CharField(max_length=40, choices=RECOMMENDATION_CHOICES, default="approve")
    risk_flag = models.CharField(max_length=255, blank=True)
    required_action = models.CharField(max_length=40, choices=RECOMMENDATION_CHOICES, default="approve")
    due_date = models.DateField(null=True, blank=True, db_index=True)
    status = models.CharField(max_length=40, choices=STATUS_CHOICES, default="ready", db_index=True)
    confidentiality = models.CharField(max_length=30, choices=CONFIDENTIALITY_CHOICES, default="internal")
    board_paper = models.ForeignKey("dashboard.NursingCouncilBoardPaper", on_delete=models.SET_NULL, null=True, blank=True, related_name="decision_queue_items")
    regulatory_decision = models.ForeignKey("complaints.RegulatoryDecisionRecord", on_delete=models.SET_NULL, null=True, blank=True, related_name="board_queue_items")
    application = models.ForeignKey("workforce.Application", on_delete=models.SET_NULL, null=True, blank=True, related_name="board_queue_items")
    complaint_case = models.ForeignKey("complaints.ComplaintCase", on_delete=models.SET_NULL, null=True, blank=True, related_name="board_queue_items")
    disciplinary_case = models.ForeignKey("complaints.DisciplinaryCase", on_delete=models.SET_NULL, null=True, blank=True, related_name="board_queue_items")
    linked_content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True)
    linked_object_id = models.PositiveIntegerField(null=True, blank=True)
    linked_object = GenericForeignKey("linked_content_type", "linked_object_id")
    decision_text = models.TextField(blank=True)
    reason = models.TextField(blank=True)
    conditions = models.TextField(blank=True)
    authority_reference = models.TextField(blank=True)
    evidence_summary = models.TextField(blank=True)
    mover = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="moved_board_decision_items")
    seconder = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="seconded_board_decision_items")
    vote_result = models.CharField(max_length=120, blank=True)
    final_minute_reference = models.CharField(max_length=120, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="decided_board_queue_items")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_board_queue_items")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "due_date", "title"]
        indexes = [
            models.Index(fields=["category", "status"]),
            models.Index(fields=["confidentiality", "status"]),
        ]

    @property
    def is_overdue(self):
        return bool(self.due_date and self.due_date < timezone.localdate() and self.status not in {"approved", "approved_conditions", "rejected", "closed"})

    def __str__(self):
        return self.reference or self.title


class BoardMotion(models.Model):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("moved", "Moved"),
        ("carried", "Carried"),
        ("lost", "Lost"),
        ("withdrawn", "Withdrawn"),
    ]

    meeting = models.ForeignKey("dashboard.NursingCouncilBoardMeeting", on_delete=models.CASCADE, related_name="motions")
    agenda_item = models.ForeignKey("dashboard.NursingCouncilBoardAgendaItem", on_delete=models.SET_NULL, null=True, blank=True, related_name="motions")
    motion_text = models.TextField()
    moved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="board_motions_moved")
    seconded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="board_motions_seconded")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft", db_index=True)
    vote_summary = models.CharField(max_length=255, blank=True)
    dissent_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["meeting", "created_at"]

    def __str__(self):
        return self.motion_text[:80]


class BoardVote(models.Model):
    VOTE_CHOICES = [
        ("for", "For"),
        ("against", "Against"),
        ("abstain", "Abstain"),
        ("recused", "Recused"),
    ]

    motion = models.ForeignKey(BoardMotion, on_delete=models.CASCADE, related_name="votes")
    member = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="board_votes")
    vote = models.CharField(max_length=20, choices=VOTE_CHOICES)
    note = models.TextField(blank=True)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("motion", "member")

    def __str__(self):
        return f"{self.member} - {self.vote}"


class BoardResolution(models.Model):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("approved", "Approved"),
        ("locked", "Locked"),
        ("superseded", "Superseded"),
    ]

    resolution_uuid = models.UUIDField(default=uuid4, editable=False, unique=True)
    meeting = models.ForeignKey("dashboard.NursingCouncilBoardMeeting", on_delete=models.CASCADE, related_name="resolutions")
    agenda_item = models.ForeignKey("dashboard.NursingCouncilBoardAgendaItem", on_delete=models.SET_NULL, null=True, blank=True, related_name="resolutions")
    motion = models.ForeignKey(BoardMotion, on_delete=models.SET_NULL, null=True, blank=True, related_name="resolutions")
    decision_queue_item = models.ForeignKey(BoardDecisionQueueItem, on_delete=models.SET_NULL, null=True, blank=True, related_name="resolutions")
    regulatory_decision = models.ForeignKey("complaints.RegulatoryDecisionRecord", on_delete=models.SET_NULL, null=True, blank=True, related_name="board_resolutions")
    resolution_reference = models.CharField(max_length=120, blank=True)
    resolution_text = models.TextField()
    authority_reference = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft", db_index=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_board_resolutions")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.resolution_reference or self.resolution_text[:80]


class BoardMinutes(models.Model):
    STATUS_CHOICES = [
        ("draft", "Draft minutes"),
        ("secretariat_review", "Secretariat review"),
        ("chair_review", "Chair review"),
        ("board_confirmation", "Awaiting Board confirmation"),
        ("confirmed", "Confirmed"),
        ("signed_locked", "Signed and locked"),
    ]

    meeting = models.OneToOneField("dashboard.NursingCouncilBoardMeeting", on_delete=models.CASCADE, related_name="board_minutes")
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="draft", db_index=True)
    draft_text = models.TextField(blank=True)
    confidential_minutes = models.TextField(blank=True)
    public_safe_extract = models.TextField(blank=True)
    final_document = models.ForeignKey("documents.Document", on_delete=models.SET_NULL, null=True, blank=True, related_name="board_minutes_records")
    chair_reviewed_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    signed_by_chair_at = models.DateTimeField(null=True, blank=True)
    signed_by_secretary_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_board_minutes")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-meeting__scheduled_for"]

    def __str__(self):
        return f"Minutes - {self.meeting}"


class BoardActionEvidence(models.Model):
    action_item = models.ForeignKey("dashboard.NursingCouncilBoardActionItem", on_delete=models.CASCADE, related_name="completion_evidence")
    document = models.ForeignKey("documents.Document", on_delete=models.SET_NULL, null=True, blank=True, related_name="board_action_evidence")
    completion_note = models.TextField(blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="uploaded_board_action_evidence")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return f"Evidence for {self.action_item}"


class GovernanceLibraryItem(models.Model):
    CATEGORY_CHOICES = [
        ("act_legal_basis", "Nursing Council Act / legal basis"),
        ("board_charter", "Board charter"),
        ("standing_orders", "Standing orders"),
        ("committee_tor", "Committee terms of reference"),
        ("code_conduct", "Codes of conduct"),
        ("professional_standard", "Professional standards"),
        ("registration_policy", "Registration policies"),
        ("education_standard", "Education standards"),
        ("accreditation", "Accreditation materials"),
        ("disciplinary_procedure", "Disciplinary procedures"),
        ("fee_schedule", "Fee schedule"),
        ("template", "Templates"),
        ("induction", "Board induction pack"),
        ("minutes", "Past minutes"),
        ("resolution", "Past resolutions"),
        ("annual_report", "Annual reports"),
        ("public_notice", "Approved public notices"),
    ]
    CLASSIFICATION_CHOICES = BoardDecisionQueueItem.CONFIDENTIALITY_CHOICES

    title = models.CharField(max_length=255)
    category = models.CharField(max_length=40, choices=CATEGORY_CHOICES, db_index=True)
    document = models.ForeignKey("documents.Document", on_delete=models.CASCADE, related_name="governance_library_items")
    classification = models.CharField(max_length=30, choices=CLASSIFICATION_CHOICES, default="internal")
    tags = models.JSONField(default=list, blank=True)
    policy_owner = models.CharField(max_length=180, blank=True)
    review_due_date = models.DateField(null=True, blank=True, db_index=True)
    board_approved_at = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=True, db_index=True)
    linked_decision = models.ForeignKey("complaints.RegulatoryDecisionRecord", on_delete=models.SET_NULL, null=True, blank=True, related_name="governance_library_items")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "title"]

    @property
    def review_overdue(self):
        return bool(self.review_due_date and self.review_due_date < timezone.localdate())

    def __str__(self):
        return self.title


class BoardRiskItem(models.Model):
    CATEGORY_CHOICES = [
        ("registration_backlog", "Registration backlog"),
        ("renewal_backlog", "Renewal backlog"),
        ("complaints_pending", "Complaints pending"),
        ("disciplinary_pending", "Disciplinary cases pending"),
        ("education_audits", "Education audits due"),
        ("accreditation_conditions", "Accreditation conditions overdue"),
        ("policy_reviews", "Policy reviews overdue"),
        ("data_quality", "Data-quality issues"),
        ("payments", "Receipt/payment exceptions"),
    ]
    STATUS_CHOICES = [
        ("green", "Green"),
        ("amber", "Amber"),
        ("red", "Red"),
    ]

    title = models.CharField(max_length=255)
    category = models.CharField(max_length=40, choices=CATEGORY_CHOICES, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="green", db_index=True)
    summary = models.TextField(blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="owned_board_risks")
    due_date = models.DateField(null=True, blank=True)
    source_reference = models.CharField(max_length=180, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "due_date", "category", "title"]

    @property
    def is_overdue(self):
        return bool(self.due_date and self.due_date < timezone.localdate() and self.status != "green")

    def __str__(self):
        return self.title


class BoardNotice(models.Model):
    NOTICE_TYPE_CHOICES = [
        ("registrar_notice", "Registrar notice"),
        ("chair_notice", "Chair notice"),
        ("secretariat_notice", "Secretariat notice"),
        ("meeting_reminder", "Meeting reminder"),
        ("paper_issued", "Paper issued"),
        ("decision_required", "Decision required"),
        ("conflict_required", "Conflict declaration required"),
        ("action_overdue", "Action overdue"),
        ("confidential_update", "Confidential update"),
    ]
    CLASSIFICATION_CHOICES = BoardDecisionQueueItem.CONFIDENTIALITY_CHOICES

    notice_type = models.CharField(max_length=40, choices=NOTICE_TYPE_CHOICES, db_index=True)
    title = models.CharField(max_length=255)
    message = models.TextField()
    classification = models.CharField(max_length=30, choices=CLASSIFICATION_CHOICES, default="internal")
    meeting = models.ForeignKey("dashboard.NursingCouncilBoardMeeting", on_delete=models.SET_NULL, null=True, blank=True, related_name="board_notices")
    agenda_item = models.ForeignKey("dashboard.NursingCouncilBoardAgendaItem", on_delete=models.SET_NULL, null=True, blank=True, related_name="board_notices")
    posted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="posted_board_notices")
    publish_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-publish_at", "-created_at"]
        indexes = [
            models.Index(fields=["notice_type", "classification"]),
            models.Index(fields=["publish_at", "expires_at"]),
        ]

    @property
    def is_current(self):
        now = timezone.now()
        return self.publish_at <= now and (not self.expires_at or self.expires_at >= now)

    def __str__(self):
        return self.title


class BoardPortalAuditEvent(models.Model):
    EVENT_TYPE_CHOICES = [
        ("viewed", "Viewed"),
        ("downloaded", "Downloaded"),
        ("marked_read", "Marked read"),
        ("conflict_declared", "Conflict declared"),
        ("decision_recorded", "Decision recorded"),
        ("vote_recorded", "Vote recorded"),
        ("minutes_updated", "Minutes updated"),
        ("resolution_locked", "Resolution locked"),
        ("notice_created", "Notice created"),
        ("access_denied", "Access denied"),
    ]

    event_uuid = models.UUIDField(default=uuid4, editable=False, unique=True)
    event_type = models.CharField(max_length=40, choices=EVENT_TYPE_CHOICES, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="board_audit_events")
    path = models.CharField(max_length=255, blank=True)
    target_content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True)
    target_object_id = models.PositiveIntegerField(null=True, blank=True)
    target_object = GenericForeignKey("target_content_type", "target_object_id")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["event_type", "created_at"]),
            models.Index(fields=["user", "created_at"]),
        ]

    def __str__(self):
        return f"{self.event_type} - {self.user}"
