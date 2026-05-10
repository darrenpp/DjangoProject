from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('registrar', 'Registrar'),
        ('reviewer', 'Reviewer'),
        ('viewer', 'Viewer'),
        ('nurse_aide', 'Nurse Aide'),
        ('nurse', 'Nurse'),
        ('chw', 'Community Health Worker'),
        ('doctor', 'Doctor'),
        ('graduand', 'Graduand'),
    ]
    APPLICANT_TYPE_CHOICES = [
        ('national', 'National'),
        ('overseas', 'Overseas'),
    ]

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='viewer')
    applicant_type = models.CharField(max_length=20, choices=APPLICANT_TYPE_CHOICES, default='national')
    phone = models.CharField(max_length=20, blank=True)
    department = models.CharField(max_length=100, blank=True)
    employee_details = models.TextField(blank=True)
    license_number = models.CharField(max_length=50, blank=True, unique=True, null=True)
    registration_number = models.CharField(max_length=50, blank=True, unique=True, null=True)
    national_id = models.CharField(max_length=50, blank=True, null=True, unique=True)
    profile_image = models.ImageField(upload_to='profiles/users/', blank=True, null=True)
    passport_photo = models.ImageField(upload_to='profiles/passports/', blank=True, null=True)
    id_document_image = models.ImageField(upload_to='profiles/ids/', blank=True, null=True)
    is_email_verified = models.BooleanField(default=False)
    role_approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_user_accounts',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    operations_approved = models.BooleanField(default=False)
    operations_approved_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='operations_approved_user_accounts',
    )
    operations_approved_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        for field_name in ('license_number', 'registration_number', 'national_id'):
            if getattr(self, field_name) == '':
                setattr(self, field_name, None)
        if self.role == 'registrar':
            self.role_approved = True
            self.is_staff = True
        elif self.role == 'admin':
            self.is_staff = bool(self.role_approved or self.is_superuser)
        elif self.role == 'reviewer':
            self.is_staff = True
        super().save(*args, **kwargs)

    def has_perm(self, perm, obj=None):
        if self.is_active and self.is_staff and self.is_superuser and self.role == 'admin':
            return True
        return super().has_perm(perm, obj=obj)

    def has_module_perms(self, app_label):
        if self.is_active and self.is_staff and self.is_superuser and self.role == 'admin':
            return True
        return super().has_module_perms(app_label)

    def __str__(self):
        return f"{self.username} ({self.role})"


class OperationalAccessRequest(models.Model):
    OFFICE_CHOICES = [
        ('nursing', 'Nursing Council'),
        ('medical', 'Medical Board'),
        ('finance', 'Finance Office'),
        ('general', 'General Registry'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='operational_access_requests')
    requested_office = models.CharField(max_length=20, choices=OFFICE_CHOICES, default='general')
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    requested_at = models.DateTimeField(auto_now_add=True)
    decided_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='decided_operational_access_requests',
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True)

    class Meta:
        ordering = ['-requested_at']

    def __str__(self):
        return f"{self.user.username} - {self.get_requested_office_display()} - {self.get_status_display()}"


class UserMFAChallenge(models.Model):
    PURPOSE_CHOICES = [
        ('login', 'Login verification'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='mfa_challenges')
    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES, default='login')
    code_hash = models.CharField(max_length=255)
    delivery_channel = models.CharField(max_length=20, default='email')
    sent_to = models.EmailField(blank=True)
    attempts = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'purpose', 'verified_at']),
            models.Index(fields=['expires_at']),
        ]

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    @property
    def is_verified(self):
        return self.verified_at is not None

    def __str__(self):
        return f"{self.user.username} - {self.purpose} - {self.created_at:%Y-%m-%d %H:%M}"


class SecurityAuditEvent(models.Model):
    ACTION_CHOICES = [
        ('LOGIN_SUCCESS', 'Login success'),
        ('LOGIN_FAILED', 'Login failed'),
        ('LOGOUT', 'Logout'),
        ('MFA_CHALLENGE_CREATED', 'MFA challenge created'),
        ('MFA_VERIFIED', 'MFA verified'),
        ('MFA_FAILED', 'MFA failed'),
        ('MFA_REQUIRED', 'MFA required'),
        ('ACCESS_DENIED', 'Access denied'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='security_audit_events',
    )
    username = models.CharField(max_length=150, blank=True)
    action = models.CharField(max_length=40, choices=ACTION_CHOICES, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    path = models.CharField(max_length=500, blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['action', 'created_at']),
            models.Index(fields=['user', 'action']),
        ]

    def __str__(self):
        actor = self.username or (self.user.username if self.user else 'unknown')
        return f"{self.action} - {actor} - {self.created_at:%Y-%m-%d %H:%M}"
