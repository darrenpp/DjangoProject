from uuid import uuid4

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone


class ComplaintCase(models.Model):
    OFFICE_SCOPE_CHOICES = [
        ("general", "General Registry"),
        ("nursing", "Nursing Council"),
        ("medical", "Medical Board"),
    ]
    CASE_TYPE_CHOICES = [
        ("complaint", "Complaint"),
        ("incident", "Incident"),
        ("professional_conduct", "Professional conduct"),
        ("licensing", "Registration or licensing"),
        ("facility", "Facility or employer"),
        ("training_institution", "Training institution"),
        ("payment", "Payment or receipt"),
        ("data_privacy", "Data privacy"),
        ("service_quality", "Service quality"),
        ("other", "Other"),
    ]
    SOURCE_CHOICES = [
        ("public_portal", "Public portal"),
        ("staff_entry", "Staff entry"),
        ("enquiry", "Enquiry inbox"),
        ("email", "Email"),
        ("phone", "Phone"),
        ("walk_in", "Walk-in"),
        ("mobile_intake", "Mobile intake"),
        ("other", "Other"),
    ]
    STATUS_CHOICES = [
        ("new", "New"),
        ("triage", "Triage"),
        ("assigned", "Assigned"),
        ("investigating", "Investigating"),
        ("awaiting_response", "Awaiting response"),
        ("escalated", "Escalated"),
        ("resolved", "Resolved"),
        ("closed", "Closed"),
        ("withdrawn", "Withdrawn"),
    ]
    PRIORITY_CHOICES = [
        ("low", "Low"),
        ("normal", "Normal"),
        ("high", "High"),
        ("critical", "Critical"),
    ]
    RISK_CHOICES = [
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
        ("critical", "Critical"),
    ]

    case_uuid = models.UUIDField(default=uuid4, editable=False, unique=True)
    case_number = models.CharField(max_length=40, unique=True, blank=True, editable=False)
    title = models.CharField(max_length=255)
    description = models.TextField()
    office_scope = models.CharField(max_length=20, choices=OFFICE_SCOPE_CHOICES, default="general", db_index=True)
    case_type = models.CharField(max_length=40, choices=CASE_TYPE_CHOICES, default="complaint", db_index=True)
    source = models.CharField(max_length=30, choices=SOURCE_CHOICES, default="staff_entry", db_index=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="new", db_index=True)
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default="normal", db_index=True)
    risk_level = models.CharField(max_length=20, choices=RISK_CHOICES, default="medium", db_index=True)
    incident_date = models.DateField(null=True, blank=True)
    location = models.CharField(max_length=255, blank=True)
    complainant_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="complaint_cases",
    )
    complainant_name = models.CharField(max_length=255, blank=True)
    complainant_email = models.EmailField(blank=True)
    complainant_phone = models.CharField(max_length=50, blank=True)
    consent_to_contact = models.BooleanField(default=False)
    subject_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="complaint_subject_cases",
    )
    subject_object_id = models.PositiveIntegerField(null=True, blank=True)
    subject_record = GenericForeignKey("subject_content_type", "subject_object_id")
    subject_name = models.CharField(max_length=255, blank=True)
    subject_identifier = models.CharField(max_length=120, blank=True)
    source_enquiry = models.ForeignKey(
        "notifications.EnquiryThread",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="complaint_cases",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_complaint_cases",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_complaint_cases",
    )
    is_public_submission = models.BooleanField(default=False, db_index=True)
    is_sensitive = models.BooleanField(default=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    closure_summary = models.TextField(blank=True)
    tags = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]
        indexes = [
            models.Index(fields=["office_scope", "status", "priority"]),
            models.Index(fields=["office_scope", "risk_level"]),
            models.Index(fields=["assigned_to", "status"]),
            models.Index(fields=["case_number"]),
            models.Index(fields=["source", "created_at"]),
            models.Index(fields=["subject_content_type", "subject_object_id"]),
        ]

    def __str__(self):
        return f"{self.case_number or 'ICMS'} - {self.title}"

    @property
    def is_open(self):
        return self.status not in {"closed", "resolved", "withdrawn"}

    @property
    def complainant_display(self):
        if self.complainant_name:
            return self.complainant_name
        if self.complainant_user_id:
            return self.complainant_user.get_full_name() or self.complainant_user.username
        return "Unidentified complainant"

    def save(self, *args, **kwargs):
        if not self.case_number:
            self.case_number = self._generate_case_number()
        if self.status in {"closed", "resolved", "withdrawn"} and not self.closed_at:
            self.closed_at = timezone.now()
        if self.status not in {"closed", "resolved", "withdrawn"}:
            self.closed_at = None
        super().save(*args, **kwargs)

    def _generate_case_number(self):
        token = {
            "nursing": "NC",
            "medical": "MB",
            "general": "GEN",
        }.get(self.office_scope, "GEN")
        year = timezone.now().year
        while True:
            candidate = f"ICMS-{token}-{year}-{uuid4().hex[:8].upper()}"
            if not ComplaintCase.objects.filter(case_number=candidate).exists():
                return candidate


class ComplaintCaseEvent(models.Model):
    ACTION_CHOICES = [
        ("intake", "Intake"),
        ("note", "Case note"),
        ("status_change", "Status change"),
        ("assignment", "Assignment"),
        ("triage", "Triage"),
        ("escalation", "Escalation"),
        ("public_response", "Public response"),
        ("closure", "Closure"),
    ]

    case = models.ForeignKey(ComplaintCase, on_delete=models.CASCADE, related_name="events")
    action_type = models.CharField(max_length=30, choices=ACTION_CHOICES, default="note", db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="complaint_case_events",
    )
    from_status = models.CharField(max_length=30, blank=True)
    to_status = models.CharField(max_length=30, blank=True)
    body = models.TextField()
    is_public_response = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["case", "created_at"]),
            models.Index(fields=["action_type", "created_at"]),
        ]

    def __str__(self):
        return f"{self.case.case_number} - {self.get_action_type_display()}"


class ComplaintCaseAttachment(models.Model):
    case = models.ForeignKey(ComplaintCase, on_delete=models.CASCADE, related_name="attachments")
    event = models.ForeignKey(
        ComplaintCaseEvent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attachments",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="complaint_case_attachments",
    )
    file = models.FileField(upload_to="complaint_cases/%Y/%m/")
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=120, blank=True)
    file_size = models.PositiveIntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["uploaded_at", "id"]

    def __str__(self):
        return self.original_filename or self.file.name


class RegulatoryDecisionRecord(models.Model):
    OFFICE_SCOPE_CHOICES = ComplaintCase.OFFICE_SCOPE_CHOICES
    DECISION_TYPE_CHOICES = [
        ("registration", "Registration"),
        ("licence", "Licence"),
        ("renewal", "Renewal"),
        ("complaint", "Complaint"),
        ("discipline", "Discipline"),
        ("document", "Document control"),
        ("data_quality", "Data quality"),
        ("finance", "Finance"),
        ("other", "Other"),
    ]
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("final", "Final"),
        ("superseded", "Superseded"),
        ("withdrawn", "Withdrawn"),
    ]

    decision_uuid = models.UUIDField(default=uuid4, editable=False, unique=True)
    decision_number = models.CharField(max_length=50, unique=True, blank=True, editable=False)
    office_scope = models.CharField(max_length=20, choices=OFFICE_SCOPE_CHOICES, default="general", db_index=True)
    decision_type = models.CharField(max_length=30, choices=DECISION_TYPE_CHOICES, default="other", db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft", db_index=True)
    title = models.CharField(max_length=255)
    subject_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="regulatory_decision_subjects",
    )
    subject_object_id = models.PositiveIntegerField(null=True, blank=True)
    subject_record = GenericForeignKey("subject_content_type", "subject_object_id")
    subject_name = models.CharField(max_length=255, blank=True)
    subject_identifier = models.CharField(max_length=120, blank=True)
    related_complaint = models.ForeignKey(
        ComplaintCase,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="decision_records",
    )
    decision_text = models.TextField()
    rationale = models.TextField()
    authority_reference = models.TextField(blank=True)
    evidence_summary = models.TextField(blank=True)
    conditions = models.TextField(blank=True)
    appeal_rights = models.TextField(blank=True)
    effective_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="regulatory_decisions_made",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="regulatory_decisions_created",
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-decided_at", "-updated_at"]
        indexes = [
            models.Index(fields=["office_scope", "decision_type", "status"]),
            models.Index(fields=["decision_number"]),
            models.Index(fields=["subject_content_type", "subject_object_id"]),
        ]

    def __str__(self):
        return f"{self.decision_number or 'DEC'} - {self.title}"

    def save(self, *args, **kwargs):
        if not self.decision_number:
            self.decision_number = self._generate_decision_number()
        if self.status == "final" and not self.decided_at:
            self.decided_at = timezone.now()
        super().save(*args, **kwargs)

    def _generate_decision_number(self):
        token = {
            "nursing": "NC",
            "medical": "MB",
            "general": "GEN",
        }.get(self.office_scope, "GEN")
        year = timezone.now().year
        while True:
            candidate = f"DEC-{token}-{year}-{uuid4().hex[:8].upper()}"
            if not RegulatoryDecisionRecord.objects.filter(decision_number=candidate).exists():
                return candidate


class DisciplinaryCase(models.Model):
    OFFICE_SCOPE_CHOICES = ComplaintCase.OFFICE_SCOPE_CHOICES
    STAGE_CHOICES = [
        ("intake", "Intake"),
        ("preliminary_assessment", "Preliminary assessment"),
        ("investigation", "Investigation"),
        ("committee_review", "Committee review"),
        ("notice_issued", "Notice issued"),
        ("hearing", "Hearing"),
        ("decision", "Decision"),
        ("appeal_monitoring", "Appeal / monitoring"),
        ("closed", "Closed"),
    ]
    STATUS_CHOICES = [
        ("open", "Open"),
        ("on_hold", "On hold"),
        ("awaiting_response", "Awaiting response"),
        ("referred", "Referred"),
        ("decided", "Decided"),
        ("closed", "Closed"),
        ("withdrawn", "Withdrawn"),
    ]
    SEVERITY_CHOICES = [
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
        ("critical", "Critical"),
    ]
    SANCTION_CHOICES = [
        ("none", "No sanction"),
        ("warning", "Warning"),
        ("conditions", "Conditions on practice"),
        ("suspension", "Suspension"),
        ("cancellation", "Cancellation / removal"),
        ("referral", "Referral to another authority"),
        ("other", "Other"),
    ]

    discipline_uuid = models.UUIDField(default=uuid4, editable=False, unique=True)
    discipline_number = models.CharField(max_length=50, unique=True, blank=True, editable=False)
    office_scope = models.CharField(max_length=20, choices=OFFICE_SCOPE_CHOICES, default="general", db_index=True)
    source_complaint = models.ForeignKey(
        ComplaintCase,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="disciplinary_cases",
    )
    subject_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="disciplinary_subject_cases",
    )
    subject_object_id = models.PositiveIntegerField(null=True, blank=True)
    subject_record = GenericForeignKey("subject_content_type", "subject_object_id")
    subject_name = models.CharField(max_length=255)
    subject_identifier = models.CharField(max_length=120, blank=True)
    allegation_summary = models.TextField()
    statutory_basis = models.TextField(blank=True)
    stage = models.CharField(max_length=40, choices=STAGE_CHOICES, default="intake", db_index=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="open", db_index=True)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default="medium", db_index=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_disciplinary_cases",
    )
    committee_reference = models.CharField(max_length=160, blank=True)
    hearing_date = models.DateTimeField(null=True, blank=True)
    notice_served_at = models.DateTimeField(null=True, blank=True)
    response_due_at = models.DateTimeField(null=True, blank=True)
    decision_record = models.ForeignKey(
        RegulatoryDecisionRecord,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="disciplinary_cases",
    )
    sanction_type = models.CharField(max_length=30, choices=SANCTION_CHOICES, default="none", db_index=True)
    sanction_summary = models.TextField(blank=True)
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_disciplinary_cases",
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]
        indexes = [
            models.Index(fields=["office_scope", "stage", "status"]),
            models.Index(fields=["assigned_to", "status"]),
            models.Index(fields=["severity", "status"]),
            models.Index(fields=["subject_content_type", "subject_object_id"]),
        ]

    def __str__(self):
        return f"{self.discipline_number or 'DISC'} - {self.subject_name}"

    @property
    def is_open(self):
        return self.status not in {"closed", "withdrawn"}

    def save(self, *args, **kwargs):
        if not self.discipline_number:
            self.discipline_number = self._generate_discipline_number()
        if self.status in {"closed", "withdrawn"} and not self.closed_at:
            self.closed_at = timezone.now()
        if self.status not in {"closed", "withdrawn"}:
            self.closed_at = None
        super().save(*args, **kwargs)

    def _generate_discipline_number(self):
        token = {
            "nursing": "NC",
            "medical": "MB",
            "general": "GEN",
        }.get(self.office_scope, "GEN")
        year = timezone.now().year
        while True:
            candidate = f"DISC-{token}-{year}-{uuid4().hex[:8].upper()}"
            if not DisciplinaryCase.objects.filter(discipline_number=candidate).exists():
                return candidate


class DisciplinaryCaseEvent(models.Model):
    ACTION_CHOICES = [
        ("intake", "Intake"),
        ("note", "Case note"),
        ("stage_change", "Stage change"),
        ("assignment", "Assignment"),
        ("notice", "Notice"),
        ("evidence", "Evidence"),
        ("hearing", "Hearing"),
        ("decision", "Decision"),
        ("appeal", "Appeal"),
        ("closure", "Closure"),
    ]

    case = models.ForeignKey(DisciplinaryCase, on_delete=models.CASCADE, related_name="events")
    action_type = models.CharField(max_length=30, choices=ACTION_CHOICES, default="note", db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="disciplinary_case_events",
    )
    from_stage = models.CharField(max_length=40, blank=True)
    to_stage = models.CharField(max_length=40, blank=True)
    body = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["case", "created_at"]),
            models.Index(fields=["action_type", "created_at"]),
        ]

    def __str__(self):
        return f"{self.case.discipline_number} - {self.get_action_type_display()}"


class DisciplinaryCaseAttachment(models.Model):
    case = models.ForeignKey(DisciplinaryCase, on_delete=models.CASCADE, related_name="attachments")
    event = models.ForeignKey(
        DisciplinaryCaseEvent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attachments",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="disciplinary_case_attachments",
    )
    file = models.FileField(upload_to="disciplinary_cases/%Y/%m/")
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=120, blank=True)
    file_size = models.PositiveIntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["uploaded_at", "id"]

    def __str__(self):
        return self.original_filename or self.file.name
