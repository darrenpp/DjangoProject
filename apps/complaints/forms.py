from django import forms

from apps.accounts.models import User

from .models import (
    ComplaintCase,
    ComplaintCaseEvent,
    DisciplinaryCase,
    DisciplinaryCaseEvent,
    RegulatoryDecisionRecord,
)


def _apply_bootstrap_widgets(form):
    for field_name, field in form.fields.items():
        widget = field.widget
        if isinstance(widget, forms.CheckboxInput):
            widget.attrs.setdefault("class", "form-check-input")
        elif isinstance(widget, forms.FileInput):
            widget.attrs.setdefault("class", "form-control-file")
        else:
            widget.attrs.setdefault("class", "form-control")
        if field_name in {"title", "description"}:
            field.required = True


class ComplaintPublicIntakeForm(forms.ModelForm):
    class Meta:
        model = ComplaintCase
        fields = [
            "office_scope",
            "case_type",
            "title",
            "description",
            "incident_date",
            "location",
            "complainant_name",
            "complainant_email",
            "complainant_phone",
            "consent_to_contact",
        ]
        widgets = {
            "incident_date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 6}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap_widgets(self)

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get("complainant_name") and not cleaned_data.get("complainant_email"):
            raise forms.ValidationError("Provide at least a complainant name or email address.")
        return cleaned_data


class ComplaintStaffCaseForm(forms.ModelForm):
    class Meta:
        model = ComplaintCase
        fields = [
            "office_scope",
            "case_type",
            "source",
            "priority",
            "risk_level",
            "title",
            "description",
            "incident_date",
            "location",
            "complainant_name",
            "complainant_email",
            "complainant_phone",
            "subject_name",
            "subject_identifier",
            "assigned_to",
            "due_at",
            "is_sensitive",
        ]
        widgets = {
            "incident_date": forms.DateInput(attrs={"type": "date"}),
            "due_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "description": forms.Textarea(attrs={"rows": 6}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap_widgets(self)
        self.fields["assigned_to"].queryset = User.objects.filter(
            is_active=True,
            role__in=["admin", "registrar", "reviewer"],
        ).order_by("role", "first_name", "last_name", "username")
        self.fields["assigned_to"].required = False


class ComplaintCaseUpdateForm(forms.ModelForm):
    class Meta:
        model = ComplaintCase
        fields = [
            "status",
            "priority",
            "risk_level",
            "assigned_to",
            "due_at",
            "acknowledged_at",
            "closure_summary",
        ]
        widgets = {
            "due_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "acknowledged_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "closure_summary": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap_widgets(self)
        self.fields["assigned_to"].queryset = User.objects.filter(
            is_active=True,
            role__in=["admin", "registrar", "reviewer"],
        ).order_by("role", "first_name", "last_name", "username")
        self.fields["assigned_to"].required = False
        self.fields["closure_summary"].required = False


class ComplaintCaseEventForm(forms.ModelForm):
    class Meta:
        model = ComplaintCaseEvent
        fields = ["action_type", "body", "is_public_response"]
        widgets = {
            "body": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap_widgets(self)


class DisciplinaryCaseForm(forms.ModelForm):
    class Meta:
        model = DisciplinaryCase
        fields = [
            "office_scope",
            "subject_name",
            "subject_identifier",
            "allegation_summary",
            "statutory_basis",
            "stage",
            "status",
            "severity",
            "assigned_to",
            "committee_reference",
            "hearing_date",
            "notice_served_at",
            "response_due_at",
        ]
        widgets = {
            "allegation_summary": forms.Textarea(attrs={"rows": 6}),
            "statutory_basis": forms.Textarea(attrs={"rows": 4}),
            "hearing_date": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "notice_served_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "response_due_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap_widgets(self)
        self.fields["assigned_to"].queryset = User.objects.filter(
            is_active=True,
            role__in=["admin", "registrar", "reviewer"],
        ).order_by("role", "first_name", "last_name", "username")
        self.fields["assigned_to"].required = False


class DisciplinaryCaseUpdateForm(DisciplinaryCaseForm):
    class Meta(DisciplinaryCaseForm.Meta):
        fields = [
            "stage",
            "status",
            "severity",
            "assigned_to",
            "committee_reference",
            "hearing_date",
            "notice_served_at",
            "response_due_at",
            "sanction_type",
            "sanction_summary",
            "effective_from",
            "effective_to",
        ]
        widgets = {
            "hearing_date": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "notice_served_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "response_due_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "sanction_summary": forms.Textarea(attrs={"rows": 4}),
            "effective_from": forms.DateInput(attrs={"type": "date"}),
            "effective_to": forms.DateInput(attrs={"type": "date"}),
        }


class DisciplinaryCaseEventForm(forms.ModelForm):
    class Meta:
        model = DisciplinaryCaseEvent
        fields = ["action_type", "body"]
        widgets = {
            "body": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap_widgets(self)


class RegulatoryDecisionRecordForm(forms.ModelForm):
    class Meta:
        model = RegulatoryDecisionRecord
        fields = [
            "office_scope",
            "decision_type",
            "status",
            "title",
            "subject_name",
            "subject_identifier",
            "decision_text",
            "rationale",
            "authority_reference",
            "evidence_summary",
            "conditions",
            "appeal_rights",
            "effective_date",
            "expiry_date",
            "decided_by",
        ]
        widgets = {
            "decision_text": forms.Textarea(attrs={"rows": 4}),
            "rationale": forms.Textarea(attrs={"rows": 4}),
            "authority_reference": forms.Textarea(attrs={"rows": 3}),
            "evidence_summary": forms.Textarea(attrs={"rows": 3}),
            "conditions": forms.Textarea(attrs={"rows": 3}),
            "appeal_rights": forms.Textarea(attrs={"rows": 3}),
            "effective_date": forms.DateInput(attrs={"type": "date"}),
            "expiry_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap_widgets(self)
        self.fields["decided_by"].queryset = User.objects.filter(
            is_active=True,
            role__in=["admin", "registrar", "reviewer"],
        ).order_by("role", "first_name", "last_name", "username")
        self.fields["decided_by"].required = False
