from django.db import models
from django.core.mail import send_mail
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from apps.accounts.models import User

class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    subject = models.CharField(max_length=200)
    message = models.TextField()
    notified_expiry = models.BooleanField(default=False)
    sent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def is_unread(self):
        return self.read_at is None

    def mark_read(self):
        if self.read_at:
            return
        self.read_at = timezone.now()
        self.save(update_fields=['read_at'])

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
    DELIVERY_CHOICES = [
        ('office', 'Office enquiry'),
        ('mailbox', 'Platform mailbox'),
        ('email', 'Direct email'),
        ('both', 'Mailbox and email'),
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
    recipient_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='received_enquiry_threads',
    )
    recipient_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    recipient_object_id = models.PositiveIntegerField(null=True, blank=True)
    recipient_record = GenericForeignKey('recipient_content_type', 'recipient_object_id')
    recipient_name = models.CharField(max_length=255, blank=True)
    recipient_email = models.EmailField(blank=True)
    delivery_channel = models.CharField(max_length=20, choices=DELIVERY_CHOICES, default='office')
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


class EnquiryMessageAttachment(models.Model):
    message = models.ForeignKey(EnquiryMessage, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to='mailbox_attachments/%Y/%m/')
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=120, blank=True)
    file_size = models.PositiveIntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['uploaded_at', 'id']

    def __str__(self):
        return self.original_filename or self.file.name


class EnquiryMailboxState(models.Model):
    FOLDER_CHOICES = [
        ('active', 'Active'),
        ('archived', 'Archived'),
        ('deleted', 'Deleted'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='enquiry_mailbox_states')
    thread = models.ForeignKey(EnquiryThread, on_delete=models.CASCADE, related_name='mailbox_states')
    folder = models.CharField(max_length=20, choices=FOLDER_CHOICES, default='active')
    notes = models.TextField(blank=True)
    read_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_read_message = models.ForeignKey(
        EnquiryMessage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('user', 'thread')]
        ordering = ['-updated_at']

    def __str__(self):
        return f"{self.user} - {self.thread} ({self.get_folder_display()})"
