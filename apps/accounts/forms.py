# apps/accounts/forms.py
import secrets
import string

from django import forms
from django.contrib.auth.forms import PasswordChangeForm, PasswordResetForm, SetPasswordForm, UserCreationForm
from django.utils import timezone
from apps.workforce.models import Cadre
from .models import User


DEFAULT_CADRE_CHOICES = (
    ("Medical Doctor", "Medical Board - Medical Doctor (Full License)"),
    ("Medical Specialist", "Medical Board - Medical Specialist"),
    ("Community Health Worker (CHW)", "Medical Board - CHW Provisional Registration"),
    ("Community Health Worker", "Medical Board - CHW Full License"),
    ("Nursing", "Nursing Council - Nursing (Full License)"),
    ("General Nursing", "Nursing Council - General Nursing"),
    ("Midwifery", "Nursing Council - Midwifery (Full License)"),
    ("Nurse Aide", "Nursing Council - Nurse Aide"),
    ("Graduand", "Nursing Council - Graduand / Provisional"),
    ("Nursing Graduand", "Nursing Council - Nursing Graduand"),
    ("Midwifery Graduand", "Nursing Council - Midwifery Graduand"),
    ("Allied Health Professional", "Allied Health - Other Professional"),
)

CADRE_LABEL_OVERRIDES = dict(DEFAULT_CADRE_CHOICES)

CADRE_CATEGORY_LABELS = {
    "medical": "Medical Board",
    "chw": "Medical Board - CHW",
    "nursing": "Nursing Council",
    "midwifery": "Nursing Council",
    "other": "Other Health Workforce",
}

CADRE_SCOPE_DEFAULT_VALUES = {
    "medical": {
        "Medical Doctor",
        "Medical Specialist",
        "Community Health Worker (CHW)",
        "Community Health Worker",
    },
    "nursing": {
        "Nursing",
        "General Nursing",
        "Midwifery",
        "Nurse Aide",
        "Graduand",
        "Nursing Graduand",
        "Midwifery Graduand",
    },
}

CADRE_SCOPE_CATEGORIES = {
    "medical": {"medical", "chw"},
    "nursing": {"nursing", "midwifery"},
}

NURSING_CADRE_EXCLUDED_NAMES = CADRE_SCOPE_DEFAULT_VALUES["medical"] | {
    "Allied Health Professional",
}
MEDICAL_CADRE_EXCLUDED_NAMES = CADRE_SCOPE_DEFAULT_VALUES["nursing"] | {
    "Allied Health Professional",
}


class PublicUserRegistrationForm(UserCreationForm):
    PUBLIC_ROLE_CHOICES = [
        ('graduand', 'Graduand'),
        ('nurse', 'Nurse'),
        ('doctor', 'Doctor'),
        ('chw', 'Community Health Worker'),
        ('nurse_aide', 'Nurse Aide'),
    ]

    first_name = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First name'})
    )
    middle_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Middle name'})
    )
    last_name = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last name'})
    )
    role = forms.ChoiceField(
        label="Role",
        choices=PUBLIC_ROLE_CHOICES,
        initial='graduand',
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    applicant_type = forms.ChoiceField(
        label="Applicant Type",
        choices=User.APPLICANT_TYPE_CHOICES,
        initial='national',
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    license_number = forms.CharField(
        max_length=50,
        required=False,
        label="License Number",
        widget=forms.TextInput(
            attrs={'class': 'form-control', 'placeholder': 'e.g. RN-12345'})
    )

    registration_number = forms.CharField(
        max_length=50,
        required=False,
        label="Registration Number",
        widget=forms.TextInput(
            attrs={'class': 'form-control', 'placeholder': 'e.g. ST-2026-001'})
    )
    cadre_name = forms.ChoiceField(
        required=True,
        label="Cadre",
        choices=(),
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    profile_image = forms.ImageField(
        required=False,
        label="Profile Picture",
        widget=forms.ClearableFileInput(attrs={'class': 'form-control-file'})
    )
    passport_photo = forms.ImageField(
        required=False,
        label="Passport Photo",
        widget=forms.ClearableFileInput(attrs={'class': 'form-control-file'})
    )
    id_document_image = forms.ImageField(
        required=False,
        label="Valid ID",
        widget=forms.ClearableFileInput(attrs={'class': 'form-control-file'})
    )

    class Meta:
        model = User
        fields = [
            'first_name',
            'middle_name',
            'last_name',
            'username',
            'email',
            'phone',
            'employee_details',
            'role',
            'applicant_type',
            'cadre_name',
            'license_number',
            'registration_number',
            'profile_image',
            'passport_photo',
            'id_document_image',
            'password1',
            'password2',
        ]
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        self.signup_scope = kwargs.pop('signup_scope', '')
        allowed_roles = kwargs.pop('allowed_roles', None)
        super().__init__(*args, **kwargs)
        allowed_values = set(allowed_roles or [choice[0] for choice in self.PUBLIC_ROLE_CHOICES])
        scoped_role_choices = [
            choice for choice in self.PUBLIC_ROLE_CHOICES
            if choice[0] in allowed_values
        ]
        self.allowed_public_role_values = {choice[0] for choice in scoped_role_choices}
        if scoped_role_choices:
            self.fields['role'].choices = scoped_role_choices
            self.fields['role'].initial = scoped_role_choices[0][0]

        # Add Bootstrap classes and required field indicators
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})
            if field.required:
                field.label = f"{field.label} *"
        self.fields['first_name'].label = "First Name"
        self.fields['middle_name'].label = "Middle Name"
        self.fields['last_name'].label = "Last Name"
        self.fields['username'].help_text = "Use your portal username or professional number."
        self.fields['employee_details'].widget = forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Department, job title, employer or other employee details'})
        self.fields['employee_details'].required = False
        self.fields['cadre_name'].choices = self._cadre_choices(self.signup_scope)
        self.fields['cadre_name'].help_text = "Used with your name and professional number to link your account to the correct registry record."
        self.fields['license_number'].help_text = "Required for nurses, doctors, and CHWs who already hold a professional licence."
        self.fields['registration_number'].help_text = "Required for nurse aides. Graduands without a provisional licence can leave this blank and follow the graduand pathway after account creation."
        self.fields['profile_image'].help_text = "Optional profile picture for your account."
        self.fields['passport_photo'].help_text = "Upload a passport-style photo."
        self.fields['id_document_image'].help_text = "Upload a valid government or professional ID."

    @staticmethod
    def _cadre_choices(scope=""):
        choices = [("", "Select Cadre")]
        try:
            cadre_rows = list(Cadre.objects.order_by("category", "name").values_list("name", "category"))
        except Exception:
            cadre_rows = []

        scope_values = CADRE_SCOPE_DEFAULT_VALUES.get(scope)
        scope_categories = CADRE_SCOPE_CATEGORIES.get(scope)
        seen = set()
        for value, label in DEFAULT_CADRE_CHOICES:
            if scope_values is not None and value not in scope_values:
                continue
            choices.append((value, label))
            seen.add(value)

        for name, category in cadre_rows:
            if not name or name in seen:
                continue
            normalized_name = str(name or "").lower()
            if scope == "nursing" and (
                name in NURSING_CADRE_EXCLUDED_NAMES
                or "medical" in normalized_name
                or "community health worker" in normalized_name
                or "chw" in normalized_name
            ):
                continue
            if scope == "medical" and (
                name in MEDICAL_CADRE_EXCLUDED_NAMES
                or "nurs" in normalized_name
                or "midwif" in normalized_name
                or "graduand" in normalized_name
            ):
                continue
            if scope_categories is not None and str(category or "").lower() not in scope_categories:
                continue
            seen.add(name)
            label = CADRE_LABEL_OVERRIDES.get(name)
            if not label:
                category_label = CADRE_CATEGORY_LABELS.get(
                    str(category or "").lower(),
                    str(category or "Specialty").replace("_", " ").title(),
                )
                label = f"{category_label} - {name}"
            choices.append((name, label))
        return choices

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get('role')
        license_number = cleaned_data.get('license_number')
        registration_number = cleaned_data.get('registration_number')

        allowed_role_values = getattr(self, 'allowed_public_role_values', {choice[0] for choice in self.PUBLIC_ROLE_CHOICES})
        if role not in allowed_role_values:
            self.add_error('role', 'Select a valid public applicant type.')

        if role in {'nurse', 'chw', 'doctor'} and not license_number:
            self.add_error('license_number', 'License number is required for this role.')
        if role == 'nurse_aide' and not registration_number:
            self.add_error('registration_number', 'Registration number is required for this role.')
        return cleaned_data


class StaffUserRegistrationForm(UserCreationForm):
    STAFF_GROUP_CONFIG = {
        'system_admin': {
            'label': 'System Admin',
            'role': 'admin',
            'department': 'System Administration',
            'job_title': 'System Admin',
            'main_access': 'User setup, system configuration, admin console, repository setup, and production checks.',
            'privacy_position': 'Can support both offices technically, but should not replace registrar decisions unless officially authorised.',
            'role_approved': False,
            'system_admin_approved': False,
            'is_active': True,
            'is_staff': False,
            'message': 'System Admin request submitted. Registrar and System Admin approval are both required before login.',
        },
        'nursing_council_staff': {
            'label': 'Nursing Council Registrar / Staff',
            'role': 'registrar',
            'department': 'Nursing Council',
            'job_title': 'Nursing Council Registrar / Staff',
            'main_access': 'Nursing Council dashboard, applications, records, reports, finance, documents, and data-quality tools.',
            'privacy_position': 'Should not access private Medical Board records unless explicitly authorised.',
            'role_approved': False,
            'system_admin_approved': False,
            'is_active': True,
            'is_staff': False,
            'message': 'Nursing Council staff request submitted. Registrar and System Admin approval are both required before login.',
        },
        'medical_board_staff': {
            'label': 'Medical Board Registrar / Staff',
            'role': 'registrar',
            'department': 'Medical Board',
            'job_title': 'Medical Board Registrar / Staff',
            'main_access': 'Medical Board dashboard, doctor/CHW records, medical workflows, medical reports, and finance.',
            'privacy_position': 'Should not access private Nursing Council records unless explicitly authorised.',
            'role_approved': False,
            'system_admin_approved': False,
            'is_active': True,
            'is_staff': False,
            'message': 'Medical Board staff request submitted. Registrar and System Admin approval are both required before login.',
        },
        'reviewer_nursing': {
            'label': 'Reviewer - Nursing Council',
            'role': 'reviewer',
            'department': 'Nursing Council Review Office',
            'job_title': 'Reviewer',
            'main_access': 'Assigned review work after operational approval.',
            'privacy_position': 'Cannot make final registrar decisions unless explicitly authorised.',
            'role_approved': False,
            'system_admin_approved': False,
            'is_active': True,
            'is_staff': False,
            'message': 'Nursing Council reviewer request submitted. Registrar and System Admin approval are both required before login.',
        },
        'reviewer_medical': {
            'label': 'Reviewer - Medical Board',
            'role': 'reviewer',
            'department': 'Medical Board Review Office',
            'job_title': 'Reviewer',
            'main_access': 'Assigned review work after operational approval.',
            'privacy_position': 'Cannot make final registrar decisions unless explicitly authorised.',
            'role_approved': False,
            'system_admin_approved': False,
            'is_active': True,
            'is_staff': False,
            'message': 'Medical Board reviewer request submitted. Registrar and System Admin approval are both required before login.',
        },
        'data_quality_officer': {
            'label': 'Data Quality Officer',
            'role': 'reviewer',
            'department': 'Data Quality Office',
            'job_title': 'Data Quality Officer',
            'main_access': 'Missing-data review, duplicate review, source checking, and cleansing notes.',
            'privacy_position': 'Cannot approve applications or bypass registrar workflow.',
            'role_approved': False,
            'system_admin_approved': False,
            'is_active': True,
            'is_staff': False,
            'message': 'Data Quality Officer request submitted. Registrar and System Admin approval are both required before login.',
        },
        'finance_officer': {
            'label': 'Finance Officer',
            'role': 'reviewer',
            'department': 'Finance Office',
            'job_title': 'Finance Officer',
            'main_access': 'Nursing and Medical Board financial forecast views.',
            'privacy_position': 'Cannot edit registry records or approve applications.',
            'role_approved': False,
            'system_admin_approved': False,
            'is_active': True,
            'is_staff': False,
            'message': 'Finance Officer request submitted. Registrar and System Admin approval are both required before login.',
        },
    }
    STAFF_GROUP_CHOICES = [(key, value['label']) for key, value in STAFF_GROUP_CONFIG.items()]
    LEGACY_ROLE_MAP = {
        'admin': 'system_admin',
        'registrar': 'nursing_council_staff',
    }
    NON_STAFF_ACCESS_GROUPS = [
        {
            'label': 'Professional user',
            'main_access': 'Own profile, applications, receipts, and documents.',
            'privacy_position': "Cannot view another person's record.",
        },
        {
            'label': 'Graduand / Student user',
            'main_access': 'Own graduand pathway, application status, receipt, and supporting documents.',
            'privacy_position': "Cannot access staff dashboards or other graduands' records.",
        },
        {
            'label': 'Public user',
            'main_access': 'Public-safe pages and public register search.',
            'privacy_position': 'Cannot access private practitioner details or staff-only tools.',
        },
    ]

    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)
    staff_group = forms.ChoiceField(
        label='Role / user group',
        choices=STAFF_GROUP_CHOICES,
        initial='nursing_council_staff',
        help_text='Select the access group. The platform maps this to the safe backend role and office scope.',
    )
    department = forms.CharField(max_length=100, required=False)
    job_title = forms.CharField(max_length=120, required=False)
    employee_details = forms.CharField(
        label='Access request note',
        required=False,
        widget=forms.Textarea(attrs={'rows': 3}),
        help_text='Optional: authorising office, assignment, or reason this staff access is needed.',
    )
    phone = forms.CharField(max_length=20, required=False)
    profile_image = forms.ImageField(required=False)

    class Meta:
        model = User
        fields = [
            'first_name',
            'last_name',
            'username',
            'email',
            'phone',
            'department',
            'job_title',
            'employee_details',
            'staff_group',
            'profile_image',
            'password1',
            'password2',
        ]
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'department': forms.TextInput(attrs={'class': 'form-control'}),
            'job_title': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        if args and args[0] and 'staff_group' not in args[0] and 'role' in args[0]:
            data = args[0].copy()
            data['staff_group'] = self.LEGACY_ROLE_MAP.get(data.get('role'), data.get('role'))
            args = (data, *args[1:])
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name == 'profile_image':
                field.widget.attrs.update({'class': 'form-control-file', 'accept': 'image/*'})
            else:
                existing_class = field.widget.attrs.get('class', '')
                field.widget.attrs['class'] = (existing_class + ' form-control').strip()
        self.fields['first_name'].label = 'First Name'
        self.fields['last_name'].label = 'Last Name'
        self.fields['profile_image'].label = 'Profile Picture'
        self.fields['department'].help_text = 'Optional. Leave blank to use the default department for the selected group.'
        self.fields['job_title'].help_text = 'Optional. Leave blank to use the selected group title.'

    def clean_staff_group(self):
        staff_group = self.cleaned_data.get('staff_group')
        if staff_group not in self.STAFF_GROUP_CONFIG:
            raise forms.ValidationError('Select a valid staff access group.')
        return staff_group

    def selected_group_config(self):
        staff_group = self.cleaned_data.get('staff_group') or 'nursing_council_staff'
        return self.STAFF_GROUP_CONFIG[staff_group]

    def apply_staff_group(self, user):
        config = self.selected_group_config()
        user.role = config['role']
        user.department = self.cleaned_data.get('department') or config['department']
        user.job_title = self.cleaned_data.get('job_title') or config['job_title']
        user.employee_details = self.cleaned_data.get('employee_details') or ''
        user.phone = self.cleaned_data.get('phone') or ''
        user.profile_image = self.cleaned_data.get('profile_image')
        user.role_approved = config['role_approved']
        user.system_admin_approved = config['system_admin_approved']
        user.system_admin_approved_by = None
        user.system_admin_approved_at = None
        user.operations_approved = False
        user.operations_approved_by = None
        user.operations_approved_at = None
        user.is_active = config['is_active']
        user.is_staff = config['is_staff']
        user._defer_staff_login_approval = True
        if user.role == 'admin':
            user.is_superuser = False
        return user

    @classmethod
    def staff_access_guide(cls):
        return list(cls.STAFF_GROUP_CONFIG.values())


class BoardMemberRegistrationForm(UserCreationForm):
    BOARD_MEMBER_ROLE_CONFIG = {
        'label': 'Board Member',
        'role': 'board_member',
        'department': 'Nursing Council Board',
        'job_title': 'Board Member',
        'main_access': 'Board governance, meeting packets, agenda actions, decision queue and notices.',
        'privacy_position': 'Board member credentials are privileged and should only be issued to appointed Nursing Council board members.',
        'role_approved': False,
        'system_admin_approved': False,
        'is_active': True,
        'is_staff': False,
        'message': 'Board member request submitted. Registrar and System Admin approval are both required before login.',
    }

    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)
    phone = forms.CharField(max_length=20, required=False)
    department = forms.CharField(max_length=100, required=False)
    job_title = forms.CharField(max_length=120, required=False)
    employee_details = forms.CharField(
        label='Board role and contact note',
        required=False,
        widget=forms.Textarea(attrs={'rows': 3}),
        help_text='Optional notes for the Secretariat to support your onboarding and governance access.',
    )
    profile_image = forms.ImageField(required=False)

    class Meta:
        model = User
        fields = [
            'first_name',
            'last_name',
            'username',
            'email',
            'phone',
            'department',
            'job_title',
            'employee_details',
            'profile_image',
            'password1',
            'password2',
        ]
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'department': forms.TextInput(attrs={'class': 'form-control'}),
            'job_title': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name == 'profile_image':
                field.widget.attrs.update({'class': 'form-control-file', 'accept': 'image/*'})
            else:
                existing_class = field.widget.attrs.get('class', '')
                field.widget.attrs['class'] = (existing_class + ' form-control').strip()
        self.fields['first_name'].label = 'First Name'
        self.fields['last_name'].label = 'Last Name'
        self.fields['username'].help_text = 'Use your board account username or official board email alias.'
        self.fields['department'].help_text = 'Optional. Leave blank to use the default Nursing Council board office.'
        self.fields['job_title'].help_text = 'Optional. Leave blank to keep default "Board Member".'
        self.fields['employee_details'].help_text = 'Optional: secretariat note, role details, or board office context.'
        self.fields['department'].initial = self.BOARD_MEMBER_ROLE_CONFIG['department']
        self.fields['job_title'].initial = self.BOARD_MEMBER_ROLE_CONFIG['job_title']

    @staticmethod
    def generate_board_registration_token():
        date_part = timezone.localdate().strftime('%Y%m%d')
        alphabet = string.ascii_uppercase + string.digits
        for _attempt in range(20):
            random_part = ''.join(secrets.choice(alphabet) for _ in range(8))
            token = f'NCB-{date_part}-{random_part}'
            if not User.objects.filter(board_registration_token=token).exists():
                return token
        raise forms.ValidationError('A board request token could not be generated. Please try again.')

    def apply_board_member_group(self, user):
        user.role = self.BOARD_MEMBER_ROLE_CONFIG['role']
        user.department = self.cleaned_data.get('department') or self.BOARD_MEMBER_ROLE_CONFIG['department']
        user.job_title = self.cleaned_data.get('job_title') or self.BOARD_MEMBER_ROLE_CONFIG['job_title']
        user.employee_details = self.cleaned_data.get('employee_details') or ''
        user.phone = self.cleaned_data.get('phone') or ''
        user.profile_image = self.cleaned_data.get('profile_image')
        user.role_approved = self.BOARD_MEMBER_ROLE_CONFIG['role_approved']
        user.system_admin_approved = self.BOARD_MEMBER_ROLE_CONFIG['system_admin_approved']
        user.system_admin_approved_by = None
        user.system_admin_approved_at = None
        user.operations_approved = False
        user.operations_approved_by = None
        user.operations_approved_at = None
        user.is_active = self.BOARD_MEMBER_ROLE_CONFIG['is_active']
        user.is_staff = self.BOARD_MEMBER_ROLE_CONFIG['is_staff']
        user.board_registration_token = self.generate_board_registration_token()
        user.board_registration_token_created_at = timezone.now()
        user._defer_staff_login_approval = True
        if user.role == 'admin':
            user.is_superuser = False
        return user


class UserProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = [
            'first_name',
            'middle_name',
            'last_name',
            'email',
            'phone',
            'secondary_email',
            'postal_address',
            'applicant_type',
            'license_number',
            'registration_number',
            'cadre_name',
            'national_id',
            'department',
            'job_title',
            'workplace_name',
            'workplace_location',
            'practice_country',
            'practice_province',
            'practice_district',
            'work_status',
            'professional_bio',
            'qualification_summary',
            'specialty_area',
            'professional_memberships',
            'employee_details',
            'primary_contact_method',
            'profile_visibility',
            'show_email_on_profile',
            'show_phone_on_profile',
            'allow_profile_contact',
            'profile_image',
        ]
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'middle_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'secondary_email': forms.EmailInput(attrs={'class': 'form-control'}),
            'postal_address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'applicant_type': forms.Select(attrs={'class': 'form-control'}),
            'license_number': forms.TextInput(attrs={'class': 'form-control'}),
            'registration_number': forms.TextInput(attrs={'class': 'form-control'}),
            'cadre_name': forms.TextInput(attrs={'class': 'form-control'}),
            'national_id': forms.TextInput(attrs={'class': 'form-control'}),
            'department': forms.TextInput(attrs={'class': 'form-control'}),
            'job_title': forms.TextInput(attrs={'class': 'form-control'}),
            'workplace_name': forms.TextInput(attrs={'class': 'form-control'}),
            'workplace_location': forms.TextInput(attrs={'class': 'form-control'}),
            'practice_country': forms.TextInput(attrs={'class': 'form-control'}),
            'practice_province': forms.TextInput(attrs={'class': 'form-control'}),
            'practice_district': forms.TextInput(attrs={'class': 'form-control'}),
            'work_status': forms.Select(attrs={'class': 'form-control'}),
            'professional_bio': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'qualification_summary': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'specialty_area': forms.TextInput(attrs={'class': 'form-control'}),
            'professional_memberships': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'employee_details': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'primary_contact_method': forms.Select(attrs={'class': 'form-control'}),
            'profile_visibility': forms.Select(attrs={'class': 'form-control'}),
            'show_email_on_profile': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_phone_on_profile': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'allow_profile_contact': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'profile_image': forms.ClearableFileInput(attrs={'class': 'form-control-file'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].required = True
        self.fields['first_name'].required = True
        self.fields['last_name'].required = True
        self.fields['middle_name'].label = "Middle Name"
        self.fields['phone'].help_text = "Primary contact number used by the regulatory offices."
        self.fields['cadre_name'].label = "Cadre"
        self.fields['cadre_name'].help_text = "Your professional cadre or pathway, used for registry matching and registrar review."
        self.fields['secondary_email'].help_text = "Optional backup email for professional contact."
        self.fields['department'].help_text = "Council, board, unit, or current department."
        self.fields['job_title'].label = "Current Position / Job Title"
        self.fields['workplace_name'].label = "Employer / Facility"
        self.fields['workplace_location'].label = "Facility Location"
        self.fields['practice_country'].label = "Country of Practice"
        self.fields['practice_province'].label = "Province of Practice"
        self.fields['practice_district'].label = "District of Practice"
        self.fields['professional_bio'].label = "Professional Bio"
        self.fields['qualification_summary'].label = "Qualifications"
        self.fields['professional_memberships'].label = "Professional Memberships / Boards"
        self.fields['employee_details'].label = "Additional Employment Details"
        self.fields['profile_visibility'].help_text = (
            "Controls how broadly your profile can be shown as future public or staff directory features are expanded."
        )
        self.fields['show_email_on_profile'].label = "Show my email on my profile"
        self.fields['show_phone_on_profile'].label = "Show my phone number on my profile"
        self.fields['allow_profile_contact'].label = "Allow authorized portal users to contact me"

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.profile_updated_at = timezone.now()
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class StyledPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        placeholders = {
            'old_password': 'Current password',
            'new_password1': 'New password',
            'new_password2': 'Confirm new password',
        }
        for name, field in self.fields.items():
            field.widget.attrs.update({
                'class': 'form-control',
                'placeholder': placeholders.get(name, field.label),
                'autocomplete': 'current-password' if name == 'old_password' else 'new-password',
            })


class StyledPasswordResetForm(PasswordResetForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].widget.attrs.update(
            {
                'class': 'form-control',
                'placeholder': 'Enter the email address saved on your account',
                'autocomplete': 'email',
            }
        )
        self.fields['email'].label = 'Account Email Address'
        self.fields['email'].help_text = (
            'A reset link will be sent only if this email matches an active account.'
        )


class StyledSetPasswordForm(SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})
