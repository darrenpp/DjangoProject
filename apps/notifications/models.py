from django.db import models
from django.core.mail import send_mail
from django.template.loader import render_to_string
from apps.accounts.models import User

class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    subject = models.CharField(max_length=200)
    message = models.TextField()
    notified_expiry = models.BooleanField(default=False)
    sent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def send_email(self):
        send_mail(
            self.subject,
            self.message,
            'no-reply@ndoh.gov.pg',
            [self.user.email],
            fail_silently=False,
        )
        self.sent = True
        self.save()


class EnquiryThread(models.Model):
    OFFICE_CHOICES = [
        ('general', 'General Registry'),
        ('nursing', 'Nursing Council'),
        ('medical', 'Medical Board'),
    ]
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('pending', 'Pending Response'),
        ('closed', 'Closed'),
    ]

    subject = models.CharField(max_length=255)
    office = models.CharField(max_length=20, choices=OFFICE_CHOICES, default='general')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='enquiry_threads')
    assigned_to = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_enquiry_threads',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f"{self.subject} ({self.get_office_display()})"


class EnquiryMessage(models.Model):
    thread = models.ForeignKey(EnquiryThread, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='enquiry_messages')
    body = models.TextField()
    emailed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Message from {self.sender} on {self.thread}"
