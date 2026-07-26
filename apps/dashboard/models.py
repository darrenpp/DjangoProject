from uuid import uuid4

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone


class Report(models.Model):
    title = models.CharField(max_length=200)
    report_type = models.CharField(max_length=50, choices=[
        ('registered_nurses', 'Registered Nurses List'),
        ('workforce_summary', 'Workforce Summary'),
        ('expiry_report', 'License Expiry Report'),
        ('cpd_summary', 'CPD Summary'),
    ])
    generated_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True)
    generated_at = models.DateTimeField(auto_now_add=True)
    file = models.FileField(upload_to='reports/', null=True, blank=True)

    def __str__(self):
        return f"{self.title} - {self.generated_at.date()}"


class ReportFreshnessState(models.Model):
    REPORT_KEY_CHOICES = [
        ('monthly_analytics', 'Monthly Analytics'),
        ('yearly_analytics', 'Yearly Analytics'),
        ('financial_forecast', 'Financial Forecast'),
        ('registered_nurses', 'Registered Nurses'),
        ('minister_brief', 'Minister Brief'),
        ('registrar_secretary_brief', 'Registrar / Secretary Brief'),
        ('production_readiness', 'Production Readiness'),
    ]
    SCOPE_CHOICES = [
        ('all', 'All Regulatory Offices'),
        ('nursing', 'Nursing Council'),
        ('medical', 'Medical Board'),
    ]

    report_key = models.CharField(max_length=80, choices=REPORT_KEY_CHOICES)
    scope = models.CharField(max_length=20, choices=SCOPE_CHOICES, default='all')
    data_version = models.PositiveIntegerField(default=0)
    last_data_changed_at = models.DateTimeField(null=True, blank=True)
    last_data_change_reason = models.CharField(max_length=255, blank=True)
    last_data_change_source = models.CharField(max_length=255, blank=True)
    last_generated_at = models.DateTimeField(null=True, blank=True)
    last_generated_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    last_generated_output = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['report_key', 'scope']
        unique_together = ('report_key', 'scope')

    @property
    def is_stale(self):
        if not self.last_data_changed_at:
            return False
        if not self.last_generated_at:
            return True
        return self.last_generated_at < self.last_data_changed_at

    def __str__(self):
        return f"{self.get_report_key_display()} - {self.get_scope_display()}"


class PlatformConnectivityState(models.Model):
    MODE_ONLINE = 'online'
    MODE_OFFLINE_LAN = 'offline_lan'
    MODE_DEGRADED = 'degraded'
    MODE_UNKNOWN = 'unknown'
    MODE_CHOICES = [
        (MODE_ONLINE, 'Online'),
        (MODE_OFFLINE_LAN, 'Offline LAN'),
        (MODE_DEGRADED, 'Degraded'),
        (MODE_UNKNOWN, 'Unknown'),
    ]

    key = models.CharField(max_length=40, unique=True, default='platform')
    mode = models.CharField(max_length=30, choices=MODE_CHOICES, default=MODE_UNKNOWN, db_index=True)
    forced_offline = models.BooleanField(default=False)
    sync_enabled = models.BooleanField(default=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_online_at = models.DateTimeField(null=True, blank=True)
    last_offline_at = models.DateTimeField(null=True, blank=True)
    last_successful_url = models.URLField(blank=True)
    last_error = models.TextField(blank=True)
    consecutive_successes = models.PositiveIntegerField(default=0)
    consecutive_failures = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Platform connectivity state'
        verbose_name_plural = 'Platform connectivity state'

    @property
    def is_online(self):
        return self.mode == self.MODE_ONLINE and not self.forced_offline

    @property
    def status_label(self):
        if self.forced_offline:
            return 'Offline LAN forced'
        return self.get_mode_display()

    def __str__(self):
        return f"{self.key} - {self.status_label}"


class PlatformSyncOutboxItem(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_SYNCED = 'synced'
    STATUS_FAILED = 'failed'
    STATUS_BLOCKED = 'blocked'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_IN_PROGRESS, 'In Progress'),
        (STATUS_SYNCED, 'Synced'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_BLOCKED, 'Blocked'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]
    METHOD_CHOICES = [
        ('POST', 'POST'),
        ('PUT', 'PUT'),
        ('PATCH', 'PATCH'),
        ('DELETE', 'DELETE'),
    ]

    item_uuid = models.UUIDField(default=uuid4, editable=False, unique=True)
    sync_type = models.CharField(max_length=80, db_index=True)
    destination = models.CharField(max_length=120, blank=True, db_index=True)
    endpoint_url = models.URLField(blank=True)
    http_method = models.CharField(max_length=10, choices=METHOD_CHOICES, default='POST')
    idempotency_key = models.CharField(max_length=160, unique=True, null=True, blank=True)
    headers_json = models.JSONField(default=dict, blank=True)
    payload_json = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    priority = models.PositiveSmallIntegerField(default=50, db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=12)
    next_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    locked_by = models.CharField(max_length=120, blank=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    response_status_code = models.PositiveIntegerField(null=True, blank=True)
    response_body_excerpt = models.TextField(blank=True)
    created_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='platform_sync_outbox_items')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['priority', 'created_at']
        indexes = [
            models.Index(fields=['status', 'next_attempt_at', 'priority']),
            models.Index(fields=['sync_type', 'destination']),
            models.Index(fields=['created_at']),
        ]

    @property
    def is_due(self):
        return self.status in {self.STATUS_PENDING, self.STATUS_FAILED} and (
            self.next_attempt_at is None or self.next_attempt_at <= timezone.now()
        ) and self.attempts < self.max_attempts

    def __str__(self):
        return f"{self.sync_type} -> {self.destination or 'default'} ({self.status})"


class NursingCouncilBoardMeeting(models.Model):
    MEETING_TYPE_CHOICES = [
        ('ordinary', 'Ordinary Council Meeting'),
        ('special', 'Special Council Meeting'),
        ('emergency', 'Emergency Council Meeting'),
        ('committee_report', 'Committee Report Meeting'),
    ]
    MEETING_MODE_CHOICES = [
        ('in_person', 'In person'),
        ('hybrid', 'Hybrid'),
        ('virtual', 'Virtual'),
    ]
    STATUS_CHOICES = [
        ('scheduled', 'Scheduled'),
        ('papers_issued', 'Papers Issued'),
        ('in_session', 'In Session'),
        ('minutes_draft', 'Draft Minutes'),
        ('confirmed', 'Minutes Confirmed'),
        ('cancelled', 'Cancelled'),
    ]

    meeting_uuid = models.UUIDField(default=uuid4, editable=False, unique=True)
    title = models.CharField(max_length=255)
    meeting_type = models.CharField(max_length=40, choices=MEETING_TYPE_CHOICES, default='ordinary')
    scheduled_for = models.DateTimeField(db_index=True)
    location = models.CharField(max_length=255, blank=True)
    meeting_mode = models.CharField(max_length=20, choices=MEETING_MODE_CHOICES, default='hybrid')
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='scheduled', db_index=True)
    quorum_required = models.PositiveSmallIntegerField(default=5)
    papers_due_at = models.DateTimeField(null=True, blank=True)
    agenda_lock_at = models.DateTimeField(null=True, blank=True)
    chair = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='chaired_nursing_board_meetings')
    secretary = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='secretary_nursing_board_meetings')
    public_summary = models.TextField(blank=True)
    private_notes = models.TextField(blank=True)
    minutes_summary = models.TextField(blank=True)
    minutes_confirmed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='created_nursing_board_meetings')
    updated_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['scheduled_for', 'title']
        indexes = [
            models.Index(fields=['status', 'scheduled_for']),
            models.Index(fields=['meeting_type', 'scheduled_for']),
        ]

    @property
    def is_complete(self):
        return self.status in {'minutes_draft', 'confirmed', 'cancelled'}

    @property
    def papers_are_due(self):
        return bool(self.papers_due_at and timezone.now() > self.papers_due_at and self.status == 'scheduled')

    def __str__(self):
        return f"{self.title} - {self.scheduled_for:%Y-%m-%d}"


class NursingCouncilBoardAgendaItem(models.Model):
    PURPOSE_CHOICES = [
        ('decision', 'Decision'),
        ('approval', 'Approval'),
        ('discussion', 'Discussion'),
        ('noting', 'For Noting'),
    ]
    CATEGORY_CHOICES = [
        ('registration', 'Registration'),
        ('education', 'Education and Accreditation'),
        ('standards', 'Standards and Policy'),
        ('conduct', 'Conduct and Fitness to Practise'),
        ('finance', 'Finance and Fees'),
        ('risk', 'Risk and Assurance'),
        ('governance', 'Governance'),
        ('other', 'Other'),
    ]
    CONFIDENTIALITY_CHOICES = [
        ('public', 'Public'),
        ('private', 'Private'),
        ('confidential', 'Confidential'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('ready', 'Ready'),
        ('noted', 'Noted'),
        ('approved', 'Approved'),
        ('deferred', 'Deferred'),
        ('rejected', 'Rejected'),
    ]

    meeting = models.ForeignKey(NursingCouncilBoardMeeting, on_delete=models.CASCADE, related_name='agenda_items')
    order = models.PositiveSmallIntegerField(default=1)
    title = models.CharField(max_length=255)
    purpose = models.CharField(max_length=30, choices=PURPOSE_CHOICES, default='discussion')
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default='governance')
    confidentiality = models.CharField(max_length=20, choices=CONFIDENTIALITY_CHOICES, default='private')
    summary = models.TextField(blank=True)
    recommendation = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    presenter = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='presented_nursing_board_items')
    related_decision = models.ForeignKey('complaints.RegulatoryDecisionRecord', on_delete=models.SET_NULL, null=True, blank=True, related_name='board_agenda_items')
    related_document = models.ForeignKey('documents.Document', on_delete=models.SET_NULL, null=True, blank=True, related_name='board_agenda_items')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['meeting', 'order', 'id']
        unique_together = ('meeting', 'order')
        indexes = [
            models.Index(fields=['meeting', 'category', 'status']),
            models.Index(fields=['confidentiality', 'status']),
        ]

    def __str__(self):
        return f"{self.meeting}: {self.order}. {self.title}"


class NursingCouncilBoardPaper(models.Model):
    CLASSIFICATION_CHOICES = NursingCouncilBoardAgendaItem.CONFIDENTIALITY_CHOICES
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('issued', 'Issued to Board'),
        ('withdrawn', 'Withdrawn'),
        ('superseded', 'Superseded'),
    ]

    meeting = models.ForeignKey(NursingCouncilBoardMeeting, on_delete=models.CASCADE, related_name='papers')
    agenda_item = models.ForeignKey(NursingCouncilBoardAgendaItem, on_delete=models.SET_NULL, null=True, blank=True, related_name='papers')
    title = models.CharField(max_length=255)
    document = models.ForeignKey('documents.Document', on_delete=models.SET_NULL, null=True, blank=True, related_name='board_papers')
    classification = models.CharField(max_length=20, choices=CLASSIFICATION_CHOICES, default='private')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft', db_index=True)
    version_label = models.CharField(max_length=40, blank=True)
    prepared_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='prepared_nursing_board_papers')
    due_at = models.DateTimeField(null=True, blank=True)
    issued_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['meeting', 'agenda_item__order', 'title']
        indexes = [
            models.Index(fields=['meeting', 'status']),
            models.Index(fields=['classification', 'status']),
        ]

    @property
    def is_late(self):
        return bool(self.due_at and timezone.now() > self.due_at and self.status in {'draft', 'submitted'})

    def __str__(self):
        return self.title


class NursingCouncilBoardAttendance(models.Model):
    ROLE_CHOICES = [
        ('chair', 'Chair'),
        ('deputy_chair', 'Deputy Chair'),
        ('member', 'Member'),
        ('secretary', 'Secretary'),
        ('observer', 'Observer'),
    ]
    STATUS_CHOICES = [
        ('expected', 'Expected'),
        ('present', 'Present'),
        ('apology', 'Apology'),
        ('absent', 'Absent'),
        ('recused', 'Recused'),
    ]

    meeting = models.ForeignKey(NursingCouncilBoardMeeting, on_delete=models.CASCADE, related_name='attendance_records')
    member = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='nursing_board_attendance_records')
    role_on_board = models.CharField(max_length=30, choices=ROLE_CHOICES, default='member')
    attendance_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='expected', db_index=True)
    conflict_declared = models.BooleanField(default=False)
    conflict_note = models.TextField(blank=True)
    recusal_required = models.BooleanField(default=False)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['meeting', 'role_on_board', 'member__last_name', 'member__first_name']
        unique_together = ('meeting', 'member')
        indexes = [
            models.Index(fields=['meeting', 'attendance_status']),
            models.Index(fields=['conflict_declared', 'recusal_required']),
        ]

    def save(self, *args, **kwargs):
        if self.attendance_status != 'expected' and not self.confirmed_at:
            self.confirmed_at = timezone.now()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.member} - {self.meeting}"


class NursingCouncilBoardActionItem(models.Model):
    PRIORITY_CHOICES = [
        ('normal', 'Normal'),
        ('high', 'High'),
        ('critical', 'Critical'),
    ]
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('deferred', 'Deferred'),
        ('cancelled', 'Cancelled'),
    ]

    meeting = models.ForeignKey(NursingCouncilBoardMeeting, on_delete=models.CASCADE, related_name='action_items')
    agenda_item = models.ForeignKey(NursingCouncilBoardAgendaItem, on_delete=models.SET_NULL, null=True, blank=True, related_name='action_items')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    owner = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='owned_nursing_board_actions')
    due_date = models.DateField(null=True, blank=True)
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='normal', db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open', db_index=True)
    source_decision = models.ForeignKey('complaints.RegulatoryDecisionRecord', on_delete=models.SET_NULL, null=True, blank=True, related_name='board_action_items')
    completed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='created_nursing_board_actions')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['status', 'due_date', 'priority', 'title']
        indexes = [
            models.Index(fields=['meeting', 'status']),
            models.Index(fields=['owner', 'status']),
            models.Index(fields=['priority', 'due_date']),
        ]

    def save(self, *args, **kwargs):
        if self.status == 'completed' and not self.completed_at:
            self.completed_at = timezone.now()
        if self.status != 'completed':
            self.completed_at = None
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class AssistantConversation(models.Model):
    ASSISTANT_KIND_CHOICES = [
        ('public_helpdesk', 'Public Helpdesk'),
        ('staff_assistant', 'Staff Assistant'),
    ]
    SCOPE_CHOICES = [
        ('public', 'Public'),
        ('all', 'All Regulatory Offices'),
        ('nursing', 'Nursing Council'),
        ('medical', 'Medical Board'),
        ('restricted', 'Restricted'),
    ]

    session_id = models.CharField(max_length=64, unique=True, db_index=True)
    assistant_kind = models.CharField(max_length=40, choices=ASSISTANT_KIND_CHOICES)
    user = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='assistant_conversations')
    browser_session_key = models.CharField(max_length=80, blank=True, db_index=True)
    scope = models.CharField(max_length=30, choices=SCOPE_CHOICES, default='public')
    role = models.CharField(max_length=50, blank=True)
    title = models.CharField(max_length=255, blank=True)
    last_question = models.TextField(blank=True)
    summary = models.TextField(blank=True)
    last_sources = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['assistant_kind', 'scope', 'updated_at']),
            models.Index(fields=['user', 'assistant_kind', 'updated_at']),
            models.Index(fields=['browser_session_key', 'assistant_kind']),
        ]

    def __str__(self):
        return f"{self.get_assistant_kind_display()} - {self.session_id}"


class AssistantMessage(models.Model):
    ROLE_CHOICES = [
        ('user', 'User'),
        ('assistant', 'Assistant'),
        ('system', 'System'),
    ]

    conversation = models.ForeignKey(AssistantConversation, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField()
    payload = models.JSONField(default=dict, blank=True)
    sources = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['conversation', 'created_at']),
            models.Index(fields=['role', 'created_at']),
        ]

    def __str__(self):
        return f"{self.role} - {self.created_at:%Y-%m-%d %H:%M}"


class AssistantFeedback(models.Model):
    """Human feedback retained for review, never as automatic model-training data."""

    RATING_CHOICES = [
        ('helpful', 'Helpful'),
        ('needs_review', 'Needs expert review'),
    ]
    REVIEW_STATUS_CHOICES = [
        ('pending', 'Pending redaction and review'),
        ('approved', 'Approved redacted feedback'),
        ('rejected', 'Rejected'),
    ]

    assistant_message = models.ForeignKey(AssistantMessage, on_delete=models.CASCADE, related_name='feedback')
    submitted_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='assistant_feedback')
    rating = models.CharField(max_length=20, choices=RATING_CHOICES)
    feedback_text = models.TextField(blank=True)
    redacted_feedback = models.TextField(blank=True)
    review_status = models.CharField(max_length=20, choices=REVIEW_STATUS_CHOICES, default='pending', db_index=True)
    requires_redaction = models.BooleanField(default=True)
    reviewed_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_assistant_feedback')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewer_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ('assistant_message', 'submitted_by')
        indexes = [
            models.Index(fields=['review_status', 'created_at']),
            models.Index(fields=['submitted_by', 'created_at']),
        ]

    @property
    def eligible_for_model_evaluation(self):
        """Only reviewed, redacted feedback can inform future human-led evaluation."""
        return self.review_status == 'approved' and bool(self.redacted_feedback.strip())

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.review_status == 'approved' and not self.redacted_feedback.strip():
            raise ValidationError({
                'redacted_feedback': 'Approved feedback must contain a reviewed, redacted summary.',
            })

    def save(self, *args, **kwargs):
        if self.review_status == 'approved' and not self.redacted_feedback.strip():
            raise ValueError('Approved assistant feedback must be redacted before it can be retained as review-ready evidence.')
        if self.review_status == 'approved' and not self.reviewed_at:
            self.reviewed_at = timezone.now()
        if self.review_status != 'approved':
            self.reviewed_at = None
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.get_rating_display()} feedback for assistant message {self.assistant_message_id}"


class AssistantMemory(models.Model):
    MEMORY_KIND_CHOICES = [
        ('recent_focus', 'Recent Focus'),
        ('preference', 'Preference'),
        ('workflow_context', 'Workflow Context'),
    ]

    assistant_kind = models.CharField(max_length=40, choices=AssistantConversation.ASSISTANT_KIND_CHOICES)
    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE, null=True, blank=True, related_name='assistant_memories')
    browser_session_key = models.CharField(max_length=80, blank=True, db_index=True)
    scope = models.CharField(max_length=30, choices=AssistantConversation.SCOPE_CHOICES, default='public')
    memory_kind = models.CharField(max_length=40, choices=MEMORY_KIND_CHOICES, default='recent_focus')
    memory_key = models.CharField(max_length=120)
    memory_text = models.TextField()
    source_conversation = models.ForeignKey(AssistantConversation, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        unique_together = ('assistant_kind', 'user', 'browser_session_key', 'scope', 'memory_kind', 'memory_key')
        indexes = [
            models.Index(fields=['assistant_kind', 'scope', 'memory_kind']),
            models.Index(fields=['user', 'assistant_kind']),
            models.Index(fields=['browser_session_key', 'assistant_kind']),
        ]

    def __str__(self):
        owner = self.user_id or self.browser_session_key or 'anonymous'
        return f"{self.assistant_kind}:{owner}:{self.memory_key}"


class RegistrationGuideline(models.Model):
    AUDIENCE_CHOICES = [
        ('general', 'General'),
        ('graduand', 'Graduand'),
        ('nurse', 'Nurse'),
        ('doctor', 'Doctor'),
        ('chw', 'Community Health Worker'),
        ('nurse_aide', 'Nurse Aide'),
    ]

    code = models.CharField(max_length=20)
    title = models.CharField(max_length=255)
    audience = models.CharField(max_length=30, choices=AUDIENCE_CHOICES, default='general')
    summary = models.TextField(blank=True)
    required_fields = models.JSONField(default=list, blank=True)
    action_url_name = models.CharField(max_length=100, blank=True)
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['audience', 'display_order', 'code']
        unique_together = ('code', 'audience')

    def __str__(self):
        return f"{self.code} - {self.title}"


class NursingAnalyticsSnapshot(models.Model):
    snapshot_id = models.UUIDField(default=uuid4, editable=False, unique=True)
    source_batch = models.ForeignKey(
        'workforce.DataImportBatch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='nursing_analytics_snapshots',
    )
    source_file_name = models.CharField(max_length=255)
    source_file_path = models.TextField(blank=True)
    source_file_hash = models.CharField(max_length=64, db_index=True)
    workbook_generated_on = models.DateField(null=True, blank=True)
    workbook_title = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=False, db_index=True)
    total_sheets = models.PositiveIntegerField(default=0)
    processed_sheets = models.PositiveIntegerField(default=0)
    total_rows = models.PositiveIntegerField(default=0)
    imported_rows = models.PositiveIntegerField(default=0)
    sheet_row_counts = models.JSONField(default=dict, blank=True)
    kpi_summary = models.JSONField(default=dict, blank=True)
    filter_options = models.JSONField(default=dict, blank=True)
    import_summary = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    activated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['is_active'],
                condition=models.Q(is_active=True),
                name='unique_active_nursing_analytics_snapshot',
            ),
        ]
        indexes = [
            models.Index(fields=['source_file_hash']),
            models.Index(fields=['is_active', 'created_at']),
        ]

    def __str__(self):
        active = 'active' if self.is_active else 'inactive'
        return f"{self.source_file_name} ({active})"


class NursingLifecycleFact(models.Model):
    snapshot = models.ForeignKey(
        NursingAnalyticsSnapshot,
        on_delete=models.CASCADE,
        related_name='lifecycle_facts',
    )
    record_id = models.CharField(max_length=80)
    lifecycle_stage = models.CharField(max_length=80, db_index=True)
    licence_status = models.CharField(max_length=100, blank=True)
    lifecycle_order = models.PositiveSmallIntegerField(null=True, blank=True)
    cycle_year = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    event_date = models.DateField(null=True, blank=True)
    full_name = models.CharField(max_length=255, blank=True, db_index=True)
    name_key = models.CharField(max_length=255, blank=True)
    person_group_key = models.CharField(max_length=255, blank=True, db_index=True)
    identity_confidence = models.CharField(max_length=120, blank=True)
    dob = models.DateField(null=True, blank=True)
    sex = models.CharField(max_length=40, blank=True)
    age = models.PositiveIntegerField(null=True, blank=True)
    cadre = models.CharField(max_length=150, blank=True, db_index=True)
    cadre_group = models.CharField(max_length=120, blank=True)
    profession_speciality_raw = models.CharField(max_length=255, blank=True)
    formal_qualification = models.CharField(max_length=255, blank=True)
    registration_no = models.CharField(max_length=100, blank=True, db_index=True)
    practitioner_no = models.CharField(max_length=100, blank=True, db_index=True)
    registration_link_key = models.CharField(max_length=120, blank=True)
    institution = models.CharField(max_length=255, blank=True, db_index=True)
    facility = models.CharField(max_length=255, blank=True, db_index=True)
    province = models.CharField(max_length=120, blank=True, db_index=True)
    organization_type = models.CharField(max_length=160, blank=True)
    nationality_group = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, blank=True)
    include_in_official_totals = models.BooleanField(default=True)
    data_quality_flags = models.TextField(blank=True)
    completeness_score = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    record_quality = models.CharField(max_length=80, blank=True, db_index=True)
    source_workbook = models.CharField(max_length=255, blank=True)
    source_sheet = models.CharField(max_length=255, blank=True)
    source_row = models.PositiveIntegerField(null=True, blank=True)
    source_lineage = models.CharField(max_length=255, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['cycle_year', 'record_id']
        unique_together = ('snapshot', 'record_id')
        indexes = [
            models.Index(fields=['snapshot', 'lifecycle_stage', 'cycle_year']),
            models.Index(fields=['snapshot', 'cadre']),
            models.Index(fields=['snapshot', 'province']),
            models.Index(fields=['snapshot', 'person_group_key']),
            models.Index(fields=['snapshot', 'record_quality']),
            models.Index(fields=['snapshot', 'facility']),
            models.Index(fields=['snapshot', 'institution']),
        ]

    def __str__(self):
        return f"{self.record_id} - {self.lifecycle_stage}"


class NursingPractitionerIndex(models.Model):
    snapshot = models.ForeignKey(
        NursingAnalyticsSnapshot,
        on_delete=models.CASCADE,
        related_name='practitioner_index_rows',
    )
    practitioner_group_id = models.CharField(max_length=80)
    person_group_key = models.CharField(max_length=255, blank=True, db_index=True)
    representative_name = models.CharField(max_length=255, blank=True)
    identity_confidence = models.CharField(max_length=120, blank=True)
    record_count = models.PositiveIntegerField(default=0)
    stages_present = models.CharField(max_length=255, blank=True)
    has_provisional = models.BooleanField(default=False)
    has_full_licence = models.BooleanField(default=False)
    has_atp = models.BooleanField(default=False)
    first_year = models.PositiveIntegerField(null=True, blank=True)
    latest_year = models.PositiveIntegerField(null=True, blank=True)
    latest_atp_year = models.PositiveIntegerField(null=True, blank=True)
    latest_cadre = models.CharField(max_length=150, blank=True)
    latest_facility = models.CharField(max_length=255, blank=True)
    latest_province = models.CharField(max_length=120, blank=True)
    registration_nos = models.TextField(blank=True)
    practitioner_nos = models.TextField(blank=True)
    dq_flag_count = models.PositiveIntegerField(default=0)
    needs_manual_review = models.BooleanField(default=False)
    raw_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['representative_name', 'practitioner_group_id']
        unique_together = ('snapshot', 'practitioner_group_id')
        indexes = [
            models.Index(fields=['snapshot', 'person_group_key']),
            models.Index(fields=['snapshot', 'latest_year']),
        ]

    def __str__(self):
        return f"{self.practitioner_group_id} - {self.representative_name}"


class RegistryArchiveRecord(models.Model):
    SCOPE_CHOICES = [
        ('all', 'All Regulatory Offices'),
        ('nursing', 'Nursing Council'),
        ('medical', 'Medical Board'),
    ]
    REASON_CHOICES = [
        ('old_age', 'Old age / retirement age'),
        ('lapsed_renewal', 'Lapsed renewal'),
        ('expired_licence', 'Expired licence'),
        ('deceased', 'Deceased'),
        ('retired', 'Retired'),
        ('inactive', 'Inactive'),
        ('manual_review', 'Manual review'),
    ]
    STATUS_CHOICES = [
        ('archived', 'Archived'),
        ('review_required', 'Review required'),
        ('confirmed_deceased', 'Confirmed deceased'),
        ('confirmed_retired', 'Confirmed retired'),
        ('restored', 'Restored'),
    ]

    archive_uuid = models.UUIDField(default=uuid4, editable=False, unique=True)
    archive_key = models.CharField(max_length=255, unique=True, db_index=True)
    content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True)
    object_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    source_object = GenericForeignKey('content_type', 'object_id')
    source_model = models.CharField(max_length=120, db_index=True)
    source_reference = models.CharField(max_length=255, blank=True, db_index=True)
    source_label = models.CharField(max_length=255, blank=True)
    scope = models.CharField(max_length=20, choices=SCOPE_CHOICES, default='all', db_index=True)
    record_year = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    latest_renewal_year = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    age = models.PositiveSmallIntegerField(null=True, blank=True, db_index=True)
    archive_reason = models.CharField(max_length=40, choices=REASON_CHOICES, db_index=True)
    archive_status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='archived', db_index=True)
    registration_no = models.CharField(max_length=100, blank=True, db_index=True)
    practitioner_number = models.CharField(max_length=100, blank=True, db_index=True)
    cadre = models.CharField(max_length=150, blank=True, db_index=True)
    facility = models.CharField(max_length=255, blank=True, db_index=True)
    province = models.CharField(max_length=120, blank=True, db_index=True)
    excluded_from_active_totals = models.BooleanField(default=True, db_index=True)
    evidence = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)
    archived_at = models.DateTimeField(auto_now_add=True)
    archived_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-archived_at', 'source_label']
        indexes = [
            models.Index(fields=['scope', 'archive_reason', 'archive_status']),
            models.Index(fields=['scope', 'record_year']),
            models.Index(fields=['scope', 'latest_renewal_year']),
            models.Index(fields=['content_type', 'object_id']),
            models.Index(fields=['excluded_from_active_totals', 'archive_status']),
        ]

    def __str__(self):
        return f"{self.source_label or self.source_reference} - {self.get_archive_reason_display()}"


class NursingStageYearMetric(models.Model):
    snapshot = models.ForeignKey(NursingAnalyticsSnapshot, on_delete=models.CASCADE, related_name='stage_year_metrics')
    year = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    year_label = models.CharField(max_length=40, blank=True)
    provisional_licence_count = models.PositiveIntegerField(default=0)
    full_licence_count = models.PositiveIntegerField(default=0)
    authority_to_practice_count = models.PositiveIntegerField(default=0)
    grand_total = models.PositiveIntegerField(default=0)
    raw_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['year', 'year_label']
        unique_together = ('snapshot', 'year', 'year_label')
        indexes = [
            models.Index(fields=['snapshot', 'year']),
        ]


class NursingCadreStageMetric(models.Model):
    snapshot = models.ForeignKey(NursingAnalyticsSnapshot, on_delete=models.CASCADE, related_name='cadre_stage_metrics')
    cadre = models.CharField(max_length=150, db_index=True)
    cadre_group = models.CharField(max_length=120, blank=True)
    provisional_licence_count = models.PositiveIntegerField(default=0)
    full_licence_count = models.PositiveIntegerField(default=0)
    authority_to_practice_count = models.PositiveIntegerField(default=0)
    grand_total = models.PositiveIntegerField(default=0)
    raw_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-grand_total', 'cadre']
        unique_together = ('snapshot', 'cadre', 'cadre_group')
        indexes = [
            models.Index(fields=['snapshot', 'cadre']),
        ]


class NursingFacilityCadreYearMetric(models.Model):
    snapshot = models.ForeignKey(NursingAnalyticsSnapshot, on_delete=models.CASCADE, related_name='facility_cadre_year_metrics')
    facility = models.CharField(max_length=255, db_index=True)
    province = models.CharField(max_length=120, blank=True, db_index=True)
    organization_type = models.CharField(max_length=160, blank=True)
    cadre = models.CharField(max_length=150, blank=True, db_index=True)
    year = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    year_label = models.CharField(max_length=40, blank=True)
    count = models.PositiveIntegerField(default=0)
    raw_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['facility', 'cadre', 'year_label']
        indexes = [
            models.Index(fields=['snapshot', 'facility']),
            models.Index(fields=['snapshot', 'province']),
            models.Index(fields=['snapshot', 'cadre', 'year']),
        ]


class NursingInstitutionCadreYearMetric(models.Model):
    snapshot = models.ForeignKey(NursingAnalyticsSnapshot, on_delete=models.CASCADE, related_name='institution_cadre_year_metrics')
    institution = models.CharField(max_length=255, db_index=True)
    lifecycle_stage = models.CharField(max_length=80, blank=True, db_index=True)
    cadre = models.CharField(max_length=150, blank=True, db_index=True)
    year = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    year_label = models.CharField(max_length=40, blank=True)
    count = models.PositiveIntegerField(default=0)
    raw_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['institution', 'lifecycle_stage', 'cadre', 'year_label']
        indexes = [
            models.Index(fields=['snapshot', 'institution']),
            models.Index(fields=['snapshot', 'lifecycle_stage']),
            models.Index(fields=['snapshot', 'cadre', 'year']),
        ]


class NursingProvinceYearMetric(models.Model):
    snapshot = models.ForeignKey(NursingAnalyticsSnapshot, on_delete=models.CASCADE, related_name='province_year_metrics')
    province = models.CharField(max_length=120, db_index=True)
    year = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    year_label = models.CharField(max_length=40, blank=True)
    count = models.PositiveIntegerField(default=0)
    raw_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['province', 'year_label']
        indexes = [
            models.Index(fields=['snapshot', 'province']),
            models.Index(fields=['snapshot', 'year']),
        ]


class NursingDataQualityMetric(models.Model):
    snapshot = models.ForeignKey(NursingAnalyticsSnapshot, on_delete=models.CASCADE, related_name='data_quality_metrics')
    lifecycle_stage = models.CharField(max_length=80, db_index=True)
    high_count = models.PositiveIntegerField(default=0)
    medium_count = models.PositiveIntegerField(default=0)
    needs_review_count = models.PositiveIntegerField(default=0)
    grand_total = models.PositiveIntegerField(default=0)
    needs_review_percent = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['lifecycle_stage']
        unique_together = ('snapshot', 'lifecycle_stage')
        indexes = [
            models.Index(fields=['snapshot', 'lifecycle_stage']),
        ]


class NursingStandardsFieldMap(models.Model):
    MAP_TYPE_CHOICES = [
        ('platform', 'Platform Field Map'),
        ('fhir_nhwa', 'FHIR / NHWA Map'),
    ]

    snapshot = models.ForeignKey(NursingAnalyticsSnapshot, on_delete=models.CASCADE, related_name='standards_field_maps')
    map_type = models.CharField(max_length=30, choices=MAP_TYPE_CHOICES)
    platform_field = models.CharField(max_length=255, blank=True)
    unified_field = models.CharField(max_length=255, db_index=True)
    used_for = models.TextField(blank=True)
    data_quality_rule = models.TextField(blank=True)
    fhir_mapping = models.TextField(blank=True)
    nhwa_dimension = models.TextField(blank=True)
    implementation_note = models.TextField(blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['map_type', 'unified_field']
        indexes = [
            models.Index(fields=['snapshot', 'map_type']),
            models.Index(fields=['snapshot', 'unified_field']),
        ]


class NursingInstitutionAlias(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('verified', 'Verified'),
        ('rejected', 'Rejected'),
    ]

    snapshot = models.ForeignKey(NursingAnalyticsSnapshot, on_delete=models.CASCADE, related_name='institution_aliases')
    raw_name = models.CharField(max_length=255)
    normalized_name = models.CharField(max_length=255, db_index=True)
    verified_institution = models.ForeignKey(
        'workforce.TrainingInstitution',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='nursing_analytics_aliases',
    )
    confidence = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    dhis2_org_unit_id = models.CharField(max_length=120, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['normalized_name']
        unique_together = ('snapshot', 'raw_name')
        indexes = [
            models.Index(fields=['snapshot', 'normalized_name']),
            models.Index(fields=['snapshot', 'status']),
        ]


class NursingFacilityAlias(models.Model):
    STATUS_CHOICES = NursingInstitutionAlias.STATUS_CHOICES

    snapshot = models.ForeignKey(NursingAnalyticsSnapshot, on_delete=models.CASCADE, related_name='facility_aliases')
    raw_name = models.CharField(max_length=255)
    normalized_name = models.CharField(max_length=255, db_index=True)
    verified_facility = models.ForeignKey(
        'workforce.Facility',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='nursing_analytics_aliases',
    )
    province = models.CharField(max_length=120, blank=True)
    organization_type = models.CharField(max_length=160, blank=True)
    confidence = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    dhis2_org_unit_id = models.CharField(max_length=120, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['normalized_name']
        unique_together = ('snapshot', 'raw_name', 'province', 'organization_type')
        indexes = [
            models.Index(fields=['snapshot', 'normalized_name']),
            models.Index(fields=['snapshot', 'province']),
            models.Index(fields=['snapshot', 'status']),
        ]


class FAQCategory(models.Model):
    AUDIENCE_CHOICES = [
        ('public', 'Public'),
        ('practitioner', 'Applicant / Practitioner'),
        ('staff', 'Staff'),
    ]
    OFFICE_SCOPE_CHOICES = [
        ('shared', 'Shared'),
        ('nursing', 'Nursing Council'),
        ('medical', 'Medical Board'),
    ]

    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=180, unique=True)
    audience = models.CharField(max_length=30, choices=AUDIENCE_CHOICES, default='public')
    office_scope = models.CharField(max_length=30, choices=OFFICE_SCOPE_CHOICES, default='shared')
    description = models.TextField(blank=True)
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'name']
        verbose_name = 'FAQ category'
        verbose_name_plural = 'FAQ categories'
        indexes = [
            models.Index(fields=['audience', 'office_scope', 'is_active']),
            models.Index(fields=['display_order', 'name']),
        ]

    def __str__(self):
        return self.name


class FAQEntry(models.Model):
    category = models.ForeignKey(FAQCategory, on_delete=models.CASCADE, related_name='entries')
    question = models.CharField(max_length=255)
    answer = models.TextField()
    keywords = models.CharField(max_length=255, blank=True)
    display_order = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=True)
    created_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    updated_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['category__display_order', 'display_order', 'question']
        indexes = [
            models.Index(fields=['is_published', 'display_order']),
        ]

    def __str__(self):
        return self.question


class ForumCategory(models.Model):
    VISIBILITY_CHOICES = [
        ('public', 'Public'),
        ('staff', 'All Staff'),
        ('nursing_staff', 'Nursing Council Staff'),
        ('medical_staff', 'Medical Board Staff'),
        ('practitioner', 'All Practitioners'),
        ('registered_nurse', 'Registered Nurses'),
        ('provisional', 'Provisional Licence Holders'),
        ('full_applicant', 'Full-Licence Applicants'),
        ('full_approved', 'Full-Licence Approved'),
    ]
    OFFICE_SCOPE_CHOICES = FAQCategory.OFFICE_SCOPE_CHOICES

    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=180, unique=True)
    description = models.TextField(blank=True)
    visibility = models.CharField(max_length=40, choices=VISIBILITY_CHOICES, default='public')
    office_scope = models.CharField(max_length=30, choices=OFFICE_SCOPE_CHOICES, default='shared')
    requires_moderation = models.BooleanField(default=True)
    allow_public_posts = models.BooleanField(default=False)
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'name']
        verbose_name_plural = 'Forum categories'
        indexes = [
            models.Index(fields=['visibility', 'office_scope', 'is_active']),
            models.Index(fields=['display_order', 'name']),
        ]

    def __str__(self):
        return self.name


class ForumTopic(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending Moderation'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('closed', 'Closed'),
    ]

    category = models.ForeignKey(ForumCategory, on_delete=models.CASCADE, related_name='topics')
    title = models.CharField(max_length=220)
    slug = models.SlugField(max_length=240)
    author = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='forum_topics')
    public_author_name = models.CharField(max_length=120, blank=True)
    public_author_email = models.EmailField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    is_pinned = models.BooleanField(default=False)
    is_locked = models.BooleanField(default=False)
    view_count = models.PositiveIntegerField(default=0)
    last_post_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_pinned', '-last_post_at', '-created_at']
        unique_together = ('category', 'slug')
        indexes = [
            models.Index(fields=['category', 'status', 'is_pinned']),
            models.Index(fields=['last_post_at', 'created_at']),
        ]

    def __str__(self):
        return self.title


class ForumPost(models.Model):
    STATUS_CHOICES = ForumTopic.STATUS_CHOICES

    topic = models.ForeignKey(ForumTopic, on_delete=models.CASCADE, related_name='posts')
    author = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='forum_posts')
    public_author_name = models.CharField(max_length=120, blank=True)
    public_author_email = models.EmailField(blank=True)
    body = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    moderated_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    moderated_at = models.DateTimeField(null=True, blank=True)
    moderation_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['topic', 'status', 'created_at']),
        ]

    def __str__(self):
        return f"Post on {self.topic}"


class ForumModerationLog(models.Model):
    ACTION_CHOICES = [
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('closed', 'Closed'),
        ('reopened', 'Reopened'),
    ]

    category = models.ForeignKey(ForumCategory, on_delete=models.SET_NULL, null=True, blank=True)
    topic = models.ForeignKey(ForumTopic, on_delete=models.CASCADE, null=True, blank=True, related_name='moderation_logs')
    post = models.ForeignKey(ForumPost, on_delete=models.CASCADE, null=True, blank=True, related_name='moderation_logs')
    action = models.CharField(max_length=30, choices=ACTION_CHOICES)
    actor = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['action', 'created_at']),
        ]

    def __str__(self):
        return f"{self.action} - {self.created_at:%Y-%m-%d}"


class MappedEntity(models.Model):
    ENTITY_TYPE_CHOICES = [
        ('institution', 'Institution'),
        ('facility', 'Facility'),
        ('school', 'School'),
        ('hospital', 'Hospital'),
        ('pha', 'Provincial Health Authority'),
        ('private_clinic', 'Private Clinic'),
        ('other', 'Other'),
    ]
    OFFICE_SCOPE_CHOICES = FAQCategory.OFFICE_SCOPE_CHOICES
    VERIFICATION_STATUS_CHOICES = [
        ('unverified', 'Unverified'),
        ('pending', 'Pending Verification'),
        ('verified', 'Verified'),
        ('rejected', 'Rejected'),
    ]

    name = models.CharField(max_length=255)
    normalized_name = models.CharField(max_length=255, db_index=True)
    entity_type = models.CharField(max_length=40, choices=ENTITY_TYPE_CHOICES)
    office_scope = models.CharField(max_length=30, choices=OFFICE_SCOPE_CHOICES, default='shared')
    province = models.CharField(max_length=120, blank=True, db_index=True)
    district = models.CharField(max_length=120, blank=True)
    address = models.TextField(blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    google_place_id = models.CharField(max_length=180, blank=True)
    dhis2_org_unit_id = models.CharField(max_length=120, blank=True)
    source = models.CharField(max_length=120, blank=True)
    source_model = models.CharField(max_length=120, blank=True)
    source_object_id = models.CharField(max_length=80, blank=True)
    active_workforce_count = models.PositiveIntegerField(default=0)
    cadre_summary = models.JSONField(default=dict, blank=True)
    verification_status = models.CharField(max_length=30, choices=VERIFICATION_STATUS_CHOICES, default='pending')
    verified_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    verified_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Mapped entities'
        unique_together = ('normalized_name', 'entity_type', 'office_scope', 'province')
        indexes = [
            models.Index(fields=['office_scope', 'entity_type']),
            models.Index(fields=['province', 'entity_type']),
            models.Index(fields=['verification_status', 'is_active']),
            models.Index(fields=['latitude', 'longitude']),
        ]

    @property
    def has_coordinates(self):
        return self.latitude is not None and self.longitude is not None

    def __str__(self):
        return self.name


class MappedEntityAlias(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('verified', 'Verified'),
        ('rejected', 'Rejected'),
    ]

    entity = models.ForeignKey(MappedEntity, on_delete=models.CASCADE, related_name='aliases')
    raw_name = models.CharField(max_length=255)
    normalized_name = models.CharField(max_length=255, db_index=True)
    source = models.CharField(max_length=120, blank=True)
    confidence = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['normalized_name']
        unique_together = ('entity', 'raw_name')
        indexes = [
            models.Index(fields=['normalized_name', 'status']),
        ]

    def __str__(self):
        return f"{self.raw_name} -> {self.entity}"


class MappedEntityVerification(models.Model):
    entity = models.ForeignKey(MappedEntity, on_delete=models.CASCADE, related_name='verification_events')
    previous_status = models.CharField(max_length=30, blank=True)
    new_status = models.CharField(max_length=30)
    verified_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    note = models.TextField(blank=True)
    evidence_url = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['new_status', 'created_at']),
        ]

    def __str__(self):
        return f"{self.entity} - {self.new_status}"


class Receipt(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    PAYER_MATCH_CONFIDENCE_CHOICES = [
        ('unlinked', 'Unlinked'),
        ('application', 'Application Link'),
        ('account', 'Account Link'),
        ('receipt_number', 'Receipt Number Match'),
        ('practitioner_number', 'Practitioner Number Match'),
        ('name_date_amount', 'Name / Date / Amount Match'),
        ('ambiguous', 'Ambiguous Match'),
    ]

    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='receipts', null=True, blank=True)
    receipt_number = models.CharField(max_length=50, unique=True)
    official_receipt_no = models.CharField(max_length=50, unique=True, blank=True, null=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(blank=True)
    receipt_image = models.ImageField(upload_to='receipts/', blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    transaction_date = models.DateTimeField(auto_now_add=True)
    receipt_date = models.DateTimeField(null=True, blank=True)
    payment_method = models.CharField(max_length=50, blank=True, default='online')
    application = models.ForeignKey('workforce.Application', on_delete=models.SET_NULL, null=True, blank=True)
    officer_receiving = models.CharField(max_length=255, blank=True)
    provincial_treasury_office = models.CharField(max_length=255, blank=True)
    atp_number = models.CharField(max_length=100, blank=True)
    payment_stamp = models.CharField(max_length=255, blank=True)
    practitioner_number = models.CharField(max_length=100, blank=True)
    payer_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='dashboard_receipt_payers',
    )
    payer_object_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    payer_record = GenericForeignKey('payer_content_type', 'payer_object_id')
    payer_match_confidence = models.CharField(
        max_length=40,
        choices=PAYER_MATCH_CONFIDENCE_CHOICES,
        default='unlinked',
        db_index=True,
    )
    payer_match_rule = models.CharField(max_length=80, blank=True)
    payer_match_notes = models.TextField(blank=True)
    payer_linked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-transaction_date']
        indexes = [
            models.Index(fields=['payer_content_type', 'payer_object_id']),
            models.Index(fields=['payer_match_confidence', 'status']),
        ]

    def save(self, *args, **kwargs):
        if not self.receipt_number:
            self.receipt_number = f"RCT-{uuid4().hex[:10].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        owner = self.user.username if self.user else "Unassigned"
        return f"{self.receipt_number} - {owner}"
