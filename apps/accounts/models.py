from django.contrib.auth.models import AbstractUser
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    STAFF_LOGIN_APPROVAL_ROLES = {'admin', 'registrar', 'reviewer', 'board_member', 'mobile_collector'}
    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('registrar', 'Registrar'),
        ('reviewer', 'Reviewer'),
        ('board_member', 'Board Member'),
        ('viewer', 'Viewer'),
        ('nurse_aide', 'Nurse Aide'),
        ('nurse', 'Nurse'),
        ('chw', 'Community Health Worker'),
        ('doctor', 'Doctor'),
        ('graduand', 'Graduand'),
        ('mobile_collector', 'Mobile Collector'),
    ]
    APPLICANT_TYPE_CHOICES = [
        ('national', 'National'),
        ('overseas', 'Overseas'),
    ]
    WORK_STATUS_CHOICES = [
        ('practicing', 'Practicing / Active'),
        ('available', 'Available for Work'),
        ('on_leave', 'On Leave'),
        ('training', 'In Training'),
        ('not_practicing', 'Not Currently Practicing'),
        ('retired', 'Retired'),
    ]
    PRIMARY_CONTACT_CHOICES = [
        ('portal', 'Portal Messages'),
        ('email', 'Email'),
        ('phone', 'Phone'),
    ]
    PROFILE_VISIBILITY_CHOICES = [
        ('private', 'Private to My Account'),
        ('regulatory_staff', 'Visible to Regulatory Staff'),
        ('public_directory', 'Public Directory Profile'),
    ]
    PROFESSIONAL_RECORD_STATUS_CHOICES = [
        ('unmatched', 'No Professional Record Linked'),
        ('pending_review', 'Pending Registrar Review'),
        ('linked', 'Linked to Professional Record'),
        ('deceased', 'Deceased'),
    ]

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='viewer')
    applicant_type = models.CharField(max_length=20, choices=APPLICANT_TYPE_CHOICES, default='national')
    phone = models.CharField(max_length=20, blank=True)
    middle_name = models.CharField(max_length=150, blank=True)
    secondary_email = models.EmailField(blank=True)
    postal_address = models.TextField(blank=True)
    department = models.CharField(max_length=100, blank=True)
    employee_details = models.TextField(blank=True)
    license_number = models.CharField(max_length=50, blank=True, unique=True, null=True)
    registration_number = models.CharField(max_length=50, blank=True, unique=True, null=True)
    national_id = models.CharField(max_length=50, blank=True, null=True, unique=True)
    cadre_name = models.CharField(max_length=120, blank=True)
    professional_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='professional_user_accounts',
    )
    professional_object_id = models.PositiveIntegerField(null=True, blank=True)
    professional_record = GenericForeignKey('professional_content_type', 'professional_object_id')
    professional_record_status = models.CharField(
        max_length=30,
        choices=PROFESSIONAL_RECORD_STATUS_CHOICES,
        default='unmatched',
        db_index=True,
    )
    professional_linked_at = models.DateTimeField(null=True, blank=True)
    professional_link_review_note = models.TextField(blank=True)
    profile_image = models.ImageField(upload_to='profiles/users/', blank=True, null=True)
    passport_photo = models.ImageField(upload_to='profiles/passports/', blank=True, null=True)
    id_document_image = models.ImageField(upload_to='profiles/ids/', blank=True, null=True)
    job_title = models.CharField(max_length=120, blank=True)
    workplace_name = models.CharField(max_length=180, blank=True)
    workplace_location = models.CharField(max_length=180, blank=True)
    practice_country = models.CharField(max_length=100, blank=True)
    practice_province = models.CharField(max_length=100, blank=True)
    practice_district = models.CharField(max_length=100, blank=True)
    work_status = models.CharField(max_length=30, choices=WORK_STATUS_CHOICES, default='practicing')
    professional_bio = models.TextField(blank=True)
    qualification_summary = models.TextField(blank=True)
    specialty_area = models.CharField(max_length=160, blank=True)
    professional_memberships = models.TextField(blank=True)
    primary_contact_method = models.CharField(max_length=20, choices=PRIMARY_CONTACT_CHOICES, default='portal')
    profile_visibility = models.CharField(max_length=30, choices=PROFILE_VISIBILITY_CHOICES, default='regulatory_staff')
    show_email_on_profile = models.BooleanField(default=False)
    show_phone_on_profile = models.BooleanField(default=False)
    allow_profile_contact = models.BooleanField(default=True)
    profile_updated_at = models.DateTimeField(null=True, blank=True)
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
    system_admin_approved = models.BooleanField(default=False)
    system_admin_approved_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='system_admin_approved_user_accounts',
    )
    system_admin_approved_at = models.DateTimeField(null=True, blank=True)
    board_registration_token = models.CharField(max_length=40, blank=True, null=True, unique=True)
    board_registration_token_created_at = models.DateTimeField(null=True, blank=True)
    operations_approved = models.BooleanField(default=False)
    operations_approved_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='operations_approved_user_accounts',
    )
    operations_approved_at = models.DateTimeField(null=True, blank=True)

    @property
    def account_display_name(self):
        parts = [self.first_name, self.middle_name, self.last_name]
        full_name = " ".join(str(part or "").strip() for part in parts if str(part or "").strip())
        if full_name:
            return full_name
        username = str(self.username or "").strip()
        if username:
            return " ".join(segment for segment in username.replace("_", " ").replace(".", " ").replace("-", " ").split()).title()
        return "User"

    def get_full_name(self):
        return self.account_display_name

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        defer_staff_approval = getattr(self, '_defer_staff_login_approval', False)
        for field_name in ('license_number', 'registration_number', 'national_id'):
            if getattr(self, field_name) == '':
                setattr(self, field_name, None)
        if self.role in self.STAFF_LOGIN_APPROVAL_ROLES:
            if defer_staff_approval:
                self.role_approved = False
                self.system_admin_approved = False
                self.is_staff = False
            elif self.role == 'admin':
                if self.is_superuser:
                    self.role_approved = True
                    self.system_admin_approved = True
                self.is_staff = bool(
                    self.is_superuser
                    or (self.role_approved and self.system_admin_approved)
                )
            else:
                if is_new:
                    if not self.role_approved:
                        self.role_approved = True
                    if not self.system_admin_approved:
                        self.system_admin_approved = True
                self.is_staff = bool(self.role_approved and self.system_admin_approved)
        super().save(*args, **kwargs)

    def has_required_staff_login_approvals(self):
        if self.role not in self.STAFF_LOGIN_APPROVAL_ROLES:
            return True
        if self.role == 'admin' and self.is_superuser:
            return True
        return bool(self.role_approved and self.system_admin_approved)

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
        ('MOBILE_LOGIN_SUCCESS', 'Mobile login success'),
        ('MOBILE_LOGIN_FAILED', 'Mobile login failed'),
        ('MOBILE_BOOTSTRAP_REQUEST', 'Mobile bootstrap request'),
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
