import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.db import transaction

from .services import calculate_file_checksum


class RepositoryScopedModel(models.Model):
    OFFICE_SCOPE_CHOICES = [
        ("general", "General Registry"),
        ("nursing", "Nursing Council"),
        ("medical", "Medical Board"),
    ]

    office_scope = models.CharField(max_length=20, choices=OFFICE_SCOPE_CHOICES, default="general", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class DocumentFolder(RepositoryScopedModel):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_document_folders",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["office_scope", "name"]
        unique_together = ("office_scope", "parent", "name")
        indexes = [
            models.Index(fields=["office_scope", "name"]),
        ]

    def __str__(self):
        return self.name

    @property
    def full_path(self):
        if not self.parent:
            return self.name
        return f"{self.parent.full_path} / {self.name}"


class Document(RepositoryScopedModel):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("active", "Active"),
        ("archived", "Archived"),
        ("superseded", "Superseded"),
    ]

    repository_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    folder = models.ForeignKey(
        DocumentFolder,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents",
    )
    document_type = models.ForeignKey(
        "workforce.DocumentType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="repository_documents",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft", db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    is_record = models.BooleanField(default=False, help_text="Marks the document as an official managed record.")
    retention_years = models.PositiveIntegerField(null=True, blank=True)
    related_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    related_object_id = models.PositiveIntegerField(null=True, blank=True)
    related_object = GenericForeignKey("related_content_type", "related_object_id")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_documents",
    )

    class Meta:
        ordering = ["-updated_at", "title"]
        indexes = [
            models.Index(fields=["office_scope", "status"]),
            models.Index(fields=["title"]),
            models.Index(fields=["related_content_type", "related_object_id"]),
        ]

    def __str__(self):
        return self.title

    @property
    def current_version(self):
        return self.versions.filter(is_current=True).order_by("-version_number").first()

    def save(self, *args, **kwargs):
        if self.folder_id and self.office_scope != self.folder.office_scope:
            self.office_scope = self.folder.office_scope
        super().save(*args, **kwargs)


def document_version_upload_to(instance, filename):
    return f"repository/{instance.document.office_scope}/{instance.document.repository_id}/{filename}"


class DocumentVersion(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="versions")
    version_number = models.PositiveIntegerField(default=1)
    file = models.FileField(upload_to=document_version_upload_to)
    original_filename = models.CharField(max_length=255, blank=True)
    mime_type = models.CharField(max_length=120, blank=True)
    file_size = models.BigIntegerField(default=0)
    checksum = models.CharField(max_length=128, blank=True)
    extracted_text = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    is_current = models.BooleanField(default=True, db_index=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_document_versions",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version_number", "-uploaded_at"]
        unique_together = ("document", "version_number")
        indexes = [
            models.Index(fields=["document", "is_current"]),
        ]

    def __str__(self):
        return f"{self.document.title} v{self.version_number}"

    def save(self, *args, **kwargs):
        if self.file and not self.original_filename:
            self.original_filename = self.file.name.split("/")[-1]
        if self.file:
            self.file_size = getattr(self.file, "size", self.file_size or 0) or 0
        with transaction.atomic():
            super().save(*args, **kwargs)
            if self.is_current:
                self.document.versions.exclude(pk=self.pk).filter(is_current=True).update(is_current=False)
            if self.file and not self.checksum:
                checksum = calculate_file_checksum(self.file)
                if checksum:
                    self.checksum = checksum
                    type(self).objects.filter(pk=self.pk).update(checksum=checksum)


class DocumentAccessPolicy(models.Model):
    ROLE_CHOICES = [
        ("admin", "Admin"),
        ("registrar", "Registrar"),
        ("reviewer", "Reviewer"),
        ("board_member", "Board Member"),
        ("viewer", "Viewer"),
        ("nurse", "Nurse"),
        ("doctor", "Doctor"),
        ("chw", "Community Health Worker"),
        ("graduand", "Graduand"),
        ("nurse_aide", "Nurse Aide"),
        ("mobile_collector", "Mobile Collector"),
    ]

    folder = models.ForeignKey(
        DocumentFolder,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="access_policies",
    )
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="access_policies",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="document_access_policies",
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, blank=True, db_index=True)
    can_view = models.BooleanField(default=True)
    can_download = models.BooleanField(default=True)
    can_upload = models.BooleanField(default=False)
    can_edit_metadata = models.BooleanField(default=False)
    can_manage_permissions = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["role", "user_id"]
        indexes = [
            models.Index(fields=["role"]),
        ]

    def __str__(self):
        target = self.document or self.folder
        subject = self.user.username if self.user else self.role or "policy"
        return f"{subject} -> {target}"

    def clean(self):
        if not self.document and not self.folder:
            raise ValidationError("Access policy must target a document or a folder.")
        if self.document and self.folder:
            raise ValidationError("Access policy cannot target both a document and a folder at the same time.")
        if not self.user and not self.role:
            raise ValidationError("Access policy must apply to a specific user or a role.")
        if self.document and self.folder and self.document.office_scope != self.folder.office_scope:
            raise ValidationError("Document and folder scope must match.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class DocumentAuditEvent(models.Model):
    EVENT_CHOICES = [
        ("created", "Created"),
        ("uploaded", "Uploaded"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("viewed", "Viewed"),
        ("downloaded", "Downloaded"),
        ("metadata_updated", "Metadata Updated"),
        ("status_changed", "Status Changed"),
        ("permission_changed", "Permission Changed"),
        ("linked", "Linked To Record"),
        ("ocr_processed", "OCR Processed"),
        ("access_denied", "Access Denied"),
    ]

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="audit_events")
    version = models.ForeignKey(
        DocumentVersion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="document_audit_events",
    )
    event_type = models.CharField(max_length=30, choices=EVENT_CHOICES, db_index=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["document", "event_type"]),
            models.Index(fields=["created_at", "event_type"]),
        ]

    def __str__(self):
        return f"{self.document.title} - {self.event_type}"


class DocumentApproval(models.Model):
    STATUS_CHOICES = [
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("revoked", "Revoked"),
    ]

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="approvals")
    version = models.ForeignKey(
        DocumentVersion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approvals",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, db_index=True)
    note = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="document_approvals",
    )
    approved_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-approved_at"]
        indexes = [
            models.Index(fields=["document", "status"]),
            models.Index(fields=["approved_at", "status"]),
        ]

    def __str__(self):
        return f"{self.document.title} - {self.get_status_display()}"
