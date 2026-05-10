from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from apps.accounts.models import User

class DuplicateReviewQueue(models.Model):
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    record = GenericForeignKey('content_type', 'object_id')

    suspected_duplicate = models.JSONField()  # Store suspected record data
    similarity_score = models.FloatField()
    status = models.CharField(max_length=20, choices=[('pending','Pending'),('reviewed','Reviewed'),('merged','Merged')], default='pending')
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    review_date = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Duplicate Review - Score: {self.similarity_score}"


class DeceasedRecord(models.Model):
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    professional = GenericForeignKey('content_type', 'object_id')
    date_of_death = models.DateField()
    death_certificate = models.FileField(upload_to='deceased/', null=True, blank=True)
    reported_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    reported_date = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, default='pending')

    def __str__(self):
        return f"Deceased: {self.professional}"