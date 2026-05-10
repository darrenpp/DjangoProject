from django import forms

from .models import Receipt


class ReceiptSubmissionForm(forms.ModelForm):
    class Meta:
        model = Receipt
        fields = [
            'official_receipt_no',
            'amount',
            'payment_method',
            'receipt_date',
            'receipt_image',
            'description',
            'application',
        ]
        widgets = {
            'official_receipt_no': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Official receipt number'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'payment_method': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Cash, bank deposit, online, etc.'}),
            'receipt_date': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'receipt_image': forms.ClearableFileInput(attrs={'class': 'form-control-file'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Payment details or notes'}),
            'application': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        application_queryset = kwargs.pop('application_queryset', None)
        super().__init__(*args, **kwargs)
        if application_queryset is not None:
            self.fields['application'].queryset = application_queryset
        self.fields['application'].required = False
