# apps/accounts/forms.py
from django import forms
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm, UserCreationForm
from .models import User


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
            'last_name',
            'username',
            'email',
            'phone',
            'employee_details',
            'role',
            'applicant_type',
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
        super().__init__(*args, **kwargs)
        # Add Bootstrap classes and required field indicators
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})
            if field.required:
                field.label = f"{field.label} *"
        self.fields['first_name'].label = "First Name"
        self.fields['last_name'].label = "Last Name"
        self.fields['username'].help_text = "Use your portal username or professional number."
        self.fields['employee_details'].widget = forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Department, job title, employer or other employee details'})
        self.fields['employee_details'].required = False
        self.fields['license_number'].help_text = "Required for nurses, doctors, and CHWs."
        self.fields['registration_number'].help_text = "Required for graduands and nurse aides."
        self.fields['profile_image'].help_text = "Optional profile picture for your account."
        self.fields['passport_photo'].help_text = "Upload a passport-style photo."
        self.fields['id_document_image'].help_text = "Upload a valid government or professional ID."

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get('role')
        license_number = cleaned_data.get('license_number')
        registration_number = cleaned_data.get('registration_number')

        if role not in {choice[0] for choice in self.PUBLIC_ROLE_CHOICES}:
            self.add_error('role', 'Select a valid public applicant type.')

        if role in {'nurse', 'chw', 'doctor'} and not license_number:
            self.add_error('license_number', 'License number is required for this role.')
        if role in {'graduand', 'nurse_aide'} and not registration_number:
            self.add_error('registration_number', 'Registration number is required for this role.')
        return cleaned_data


class StaffUserRegistrationForm(UserCreationForm):
    STAFF_ROLE_CHOICES = [
        ('registrar', 'Registrar'),
        ('admin', 'Admin'),
    ]

    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)
    role = forms.ChoiceField(choices=STAFF_ROLE_CHOICES, initial='registrar')
    department = forms.CharField(max_length=100, required=False)
    phone = forms.CharField(max_length=20, required=False)
    profile_image = forms.ImageField(required=False)

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'username', 'email', 'phone', 'department', 'role', 'profile_image', 'password1', 'password2']

    def clean_role(self):
        role = self.cleaned_data.get('role')
        if role not in {'registrar', 'admin'}:
            raise forms.ValidationError('Select a valid staff role.')
        return role


class UserProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = [
            'first_name',
            'last_name',
            'email',
            'phone',
            'department',
            'employee_details',
            'profile_image',
        ]
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'department': forms.TextInput(attrs={'class': 'form-control'}),
            'employee_details': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'profile_image': forms.ClearableFileInput(attrs={'class': 'form-control-file'}),
        }


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
