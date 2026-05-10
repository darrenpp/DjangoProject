from django.db import models
from django.utils import timezone
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType


class CompetencyAssessment(models.Model):
    # Generic link to ANY professional type
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="competency_assessments"
    )
    object_id = models.PositiveIntegerField()
    professional = GenericForeignKey("content_type", "object_id")

    # Core fields (ALL SAFE FOR MIGRATIONS)
    assessment_name = models.CharField(
        max_length=255,
        default="Initial Assessment"
    )

    assessment_type = models.CharField(
        max_length=100,
        default="standard"
    )
    form_code = models.CharField(
        max_length=20,
        blank=True,
        default=""
    )
    profession_track = models.CharField(
        max_length=100,
        blank=True,
        default=""
    )
    competency_domains = models.JSONField(
        default=list,
        blank=True
    )
    supervisor_assessment = models.TextField(
        blank=True,
        default=""
    )

    supervisor_name = models.CharField(
        max_length=255,
        null=True,
        blank=True
    )
    supervisor_signature = models.CharField(
        max_length=255,
        blank=True,
        default=""
    )
    verification_signature = models.CharField(
        max_length=255,
        blank=True,
        default=""
    )

    score = models.FloatField(default=0)

    is_passed = models.BooleanField(default=True)

    assessment_date = models.DateField(default=timezone.now)

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
            models.Index(fields=["assessment_date"]),
        ]

    def __str__(self):
        return f"{self.assessment_name} - {self.score}"
