from django.conf import settings
from django.db import models
from django.utils.text import slugify


class NHWAWebWorkbook(models.Model):
    OFFICE_SCOPE_CHOICES = [
        ("nursing", "Nursing Council"),
        ("medical", "Medical Board"),
    ]
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("active", "Active"),
        ("locked", "Locked"),
        ("archived", "Archived"),
    ]

    office_scope = models.CharField(max_length=30, choices=OFFICE_SCOPE_CHOICES, db_index=True)
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=180, unique=True)
    source_title = models.CharField(max_length=255, blank=True)
    source_version = models.CharField(max_length=80, blank=True)
    reporting_year = models.PositiveIntegerField(default=2025)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active", db_index=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_nhwa_workbooks",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["office_scope", "title"]
        indexes = [
            models.Index(fields=["office_scope", "status"]),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(f"{self.office_scope}-{self.title}")[:180]
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.get_office_scope_display()} - {self.title}"


class NHWAWebSheet(models.Model):
    workbook = models.ForeignKey(NHWAWebWorkbook, on_delete=models.CASCADE, related_name="sheets")
    source_sheet_name = models.CharField(max_length=120)
    title = models.CharField(max_length=255)
    sort_order = models.PositiveIntegerField(default=0)
    max_row = models.PositiveIntegerField(default=0)
    max_column = models.PositiveIntegerField(default=0)
    editable = models.BooleanField(default=True)
    purpose = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["workbook", "sort_order", "id"]
        unique_together = ("workbook", "source_sheet_name")
        indexes = [
            models.Index(fields=["source_sheet_name"]),
            models.Index(fields=["editable"]),
        ]

    def __str__(self):
        return f"{self.workbook} - {self.title}"


class NHWACellTemplate(models.Model):
    sheet = models.ForeignKey(NHWAWebSheet, on_delete=models.CASCADE, related_name="cell_templates")
    coordinate = models.CharField(max_length=12)
    row_index = models.PositiveIntegerField()
    column_index = models.PositiveIntegerField()
    column_letter = models.CharField(max_length=6)
    initial_value = models.TextField(blank=True)
    formula = models.TextField(blank=True)
    fill_rgb = models.CharField(max_length=12, blank=True)
    is_editable = models.BooleanField(default=False)
    is_formula = models.BooleanField(default=False)
    is_heading = models.BooleanField(default=False)
    is_required = models.BooleanField(default=False)
    number_format = models.CharField(max_length=80, blank=True)
    style_json = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["sheet", "row_index", "column_index"]
        unique_together = ("sheet", "coordinate")
        indexes = [
            models.Index(fields=["sheet", "row_index", "column_index"]),
            models.Index(fields=["sheet", "is_editable"]),
            models.Index(fields=["sheet", "is_formula"]),
        ]

    def __str__(self):
        return f"{self.sheet.source_sheet_name}!{self.coordinate}"


class NHWACellEntry(models.Model):
    template = models.OneToOneField(NHWACellTemplate, on_delete=models.CASCADE, related_name="entry")
    value = models.TextField(blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_nhwa_cells",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["template__sheet", "template__row_index", "template__column_index"]
        indexes = [
            models.Index(fields=["updated_at"]),
        ]

    def __str__(self):
        return f"{self.template}: {self.value[:40]}"


class NHWAWorkbookAuditEvent(models.Model):
    ACTION_CHOICES = [
        ("BOOTSTRAPPED", "Bootstrapped"),
        ("CELL_UPDATED", "Cell updated"),
        ("SHEET_SAVED", "Sheet saved"),
        ("VIEWED", "Viewed"),
        ("LOCKED", "Locked"),
        ("UNLOCKED", "Unlocked"),
    ]

    workbook = models.ForeignKey(NHWAWebWorkbook, on_delete=models.CASCADE, related_name="audit_events")
    sheet = models.ForeignKey(NHWAWebSheet, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=40, choices=ACTION_CHOICES)
    details = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["action", "created_at"]),
            models.Index(fields=["workbook", "created_at"]),
        ]

    def __str__(self):
        return f"{self.action} - {self.workbook_id} - {self.created_at:%Y-%m-%d %H:%M}"
