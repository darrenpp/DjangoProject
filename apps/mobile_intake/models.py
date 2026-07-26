import uuid

from django.conf import settings
from django.db import models


class MobileDevice(models.Model):
    device_uuid = models.CharField(max_length=100, unique=True)
    device_name = models.CharField(max_length=255, blank=True)
    platform = models.CharField(max_length=50, default="android")
    app_version = models.CharField(max_length=50, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    registered_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    risk_status = models.CharField(max_length=50, default="normal")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_seen_at", "-created_at"]

    def __str__(self):
        return self.device_name or self.device_uuid


class MobileLocalAccountRequest(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
        ("DISABLED", "Disabled"),
    ]

    local_account_uuid = models.CharField(max_length=100, unique=True)
    full_name = models.CharField(max_length=255)
    username = models.CharField(max_length=150)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    requested_role = models.CharField(max_length=100)
    requested_cadre = models.CharField(max_length=100, blank=True)
    office_scope = models.CharField(max_length=50)
    device = models.ForeignKey(MobileDevice, null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    linked_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="mobile_account_requests")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["office_scope", "status"]),
            models.Index(fields=["username"]),
        ]

    def __str__(self):
        return f"{self.username} - {self.status}"


class MobileFormSchema(models.Model):
    form_code = models.CharField(max_length=50)
    form_name = models.CharField(max_length=255)
    office_scope = models.CharField(max_length=50)
    schema_version = models.CharField(max_length=50)
    json_schema = models.JSONField(default=dict)
    ui_schema = models.JSONField(default=dict)
    required_fields = models.JSONField(default=list)
    attachment_requirements = models.JSONField(default=list)
    validation_rules = models.JSONField(default=dict)
    is_enabled = models.BooleanField(default=True)
    enabled_for_roles = models.JSONField(default=list)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["office_scope", "form_code", "-schema_version"]
        unique_together = ("form_code", "office_scope", "schema_version")
        indexes = [
            models.Index(fields=["office_scope", "form_code", "is_enabled"]),
        ]

    def __str__(self):
        return f"{self.form_code} {self.schema_version} ({self.office_scope})"


class MobileSubmission(models.Model):
    STATUS_CHOICES = [
        ("RECEIVED", "Received"),
        ("VALIDATING", "Validating"),
        ("DUPLICATE_RISK", "Duplicate Risk"),
        ("NEEDS_REVIEW", "Needs Review"),
        ("NEEDS_CORRECTION", "Needs Correction"),
        ("REJECTED", "Rejected"),
        ("ACCEPTED", "Accepted"),
        ("PROMOTED", "Promoted"),
        ("FAILED", "Failed"),
        ("SUPERSEDED", "Superseded"),
    ]

    submission_uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    idempotency_key = models.CharField(max_length=255, unique=True)
    device = models.ForeignKey(MobileDevice, null=True, blank=True, on_delete=models.SET_NULL)
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    local_account_request = models.ForeignKey(MobileLocalAccountRequest, null=True, blank=True, on_delete=models.SET_NULL)
    local_draft_id = models.CharField(max_length=100)
    local_version = models.PositiveIntegerField(default=1)
    office_scope = models.CharField(max_length=50)
    form_code = models.CharField(max_length=50)
    schema_version = models.CharField(max_length=50)
    payload_json = models.JSONField(default=dict)
    normalized_payload_json = models.JSONField(default=dict)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="RECEIVED")
    validation_errors = models.JSONField(default=list)
    duplicate_score = models.FloatField(null=True, blank=True)
    duplicate_summary = models.JSONField(default=dict)
    review_notes = models.TextField(blank=True)
    correction_note = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    accepted_at = models.DateTimeField(null=True, blank=True)
    promoted_object_type = models.CharField(max_length=100, blank=True)
    promoted_object_id = models.CharField(max_length=100, blank=True)
    created_offline_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-received_at"]
        indexes = [
            models.Index(fields=["office_scope", "status"]),
            models.Index(fields=["form_code", "schema_version"]),
            models.Index(fields=["local_draft_id", "local_version"]),
            models.Index(fields=["received_at"]),
        ]

    def __str__(self):
        return f"{self.form_code} {self.submission_uuid} - {self.status}"

    @property
    def device_label(self):
        if not self.device:
            return ""
        return self.device.device_name or self.device.device_uuid or ""

    def payload_value(self, *keys, default=""):
        payload = self.normalized_payload_json or self.payload_json or {}
        for key in keys:
            value = payload.get(key)
            if value not in (None, ""):
                return value
        return default

    @property
    def applicant_name(self):
        first = str(self.payload_value("first_name")).strip()
        surname = str(self.payload_value("surname", "last_name")).strip()
        full_name = str(self.payload_value("full_name")).strip()
        return full_name or f"{first} {surname}".strip()

    @property
    def registration_number(self):
        return self.payload_value("registration_number", "registration_no")

    @property
    def practitioner_number(self):
        return self.payload_value("practitioner_number", "practitioner_no")

    @property
    def licence_number(self):
        return self.payload_value("licence_number", "license_number", "licence_no", "license_no")

    @property
    def province(self):
        return self.payload_value("province")

    @property
    def district(self):
        return self.payload_value("district")

    @property
    def facility(self):
        return self.payload_value("facility", "facility_name_raw", "facility_name")

    @property
    def employment_status(self):
        return self.payload_value("employment_status")


class MobileSubmissionAttachment(models.Model):
    submission = models.ForeignKey(MobileSubmission, on_delete=models.CASCADE, related_name="attachments")
    local_attachment_uuid = models.CharField(max_length=100)
    file = models.FileField(upload_to="mobile_intake/%Y/%m/")
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    file_size = models.PositiveIntegerField()
    sha256_checksum = models.CharField(max_length=64)
    document_type = models.CharField(max_length=100)
    office_scope = models.CharField(max_length=50)
    repository_document = models.ForeignKey("documents.Document", null=True, blank=True, on_delete=models.SET_NULL)
    repository_version = models.ForeignKey("documents.DocumentVersion", null=True, blank=True, on_delete=models.SET_NULL)
    ocr_status = models.CharField(max_length=50, default="PENDING")
    upload_status = models.CharField(max_length=50, default="RECEIVED")
    created_offline_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-received_at"]
        unique_together = ("submission", "local_attachment_uuid")
        indexes = [
            models.Index(fields=["office_scope", "document_type"]),
            models.Index(fields=["sha256_checksum"]),
        ]

    def __str__(self):
        return f"{self.document_type} - {self.original_filename}"


class MobileSyncEvent(models.Model):
    submission = models.ForeignKey(MobileSubmission, null=True, blank=True, on_delete=models.CASCADE, related_name="sync_events")
    device = models.ForeignKey(MobileDevice, null=True, blank=True, on_delete=models.SET_NULL)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    event_type = models.CharField(max_length=100)
    status_before = models.CharField(max_length=50, blank=True)
    status_after = models.CharField(max_length=50, blank=True)
    message = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["event_type", "created_at"]),
            models.Index(fields=["submission", "created_at"]),
        ]

    def __str__(self):
        return f"{self.event_type} - {self.created_at:%Y-%m-%d %H:%M}"


class MobileSubmissionStatusHistory(models.Model):
    submission = models.ForeignKey(MobileSubmission, on_delete=models.CASCADE, related_name="status_history")
    old_status = models.CharField(max_length=50, blank=True)
    new_status = models.CharField(max_length=50)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    note = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["submission", "new_status"]),
        ]

    def __str__(self):
        return f"{self.submission_id}: {self.old_status} -> {self.new_status}"


class MobilePromotionLink(models.Model):
    submission = models.ForeignKey(MobileSubmission, on_delete=models.CASCADE, related_name="promotion_links")
    target_type = models.CharField(max_length=100)
    target_id = models.CharField(max_length=100)
    action = models.CharField(max_length=100, default="promoted")
    metadata = models.JSONField(default=dict, blank=True)
    promoted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    promoted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-promoted_at"]
        indexes = [
            models.Index(fields=["target_type", "target_id"]),
            models.Index(fields=["submission", "target_type"]),
        ]

    def __str__(self):
        return f"{self.submission_id} -> {self.target_type}:{self.target_id}"
