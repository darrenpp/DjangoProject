from uuid import uuid4

from django.db import models


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


class Receipt(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
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

    class Meta:
        ordering = ['-transaction_date']

    def save(self, *args, **kwargs):
        if not self.receipt_number:
            self.receipt_number = f"RCT-{uuid4().hex[:10].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        owner = self.user.username if self.user else "Unassigned"
        return f"{self.receipt_number} - {owner}"
