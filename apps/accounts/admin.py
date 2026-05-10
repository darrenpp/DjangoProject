# apps/accounts/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django import forms
from django.http import HttpResponse
from django.template.response import TemplateResponse
from django.urls import path
from django.utils import timezone
import csv
from io import BytesIO

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

from .models import OperationalAccessRequest, SecurityAuditEvent, User, UserMFAChallenge


class UserAdminForm(forms.ModelForm):
    class Meta:
        model = User
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get('role')
        return cleaned_data


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = UserAdminForm
    list_display = ('username', 'email', 'role', 'applicant_type', 'department', 'license_number', 'registration_number', 'operations_approved', 'is_active')
    list_filter = ('role', 'is_active', 'is_staff', 'operations_approved')
    search_fields = ('username', 'email', 'first_name', 'last_name', 'department', 'license_number', 'registration_number')
    actions = ['approve_selected_admin_accounts', 'export_as_csv', 'export_as_xlsx', 'export_as_pdf']

    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal Info', {'fields': ('first_name', 'last_name', 'email', 'phone', 'department', 'employee_details', 'profile_image', 'passport_photo', 'id_document_image')}),
        ('Role & Permissions',
         {'fields': ('role', 'applicant_type', 'license_number', 'registration_number', 'national_id', 'role_approved', 'approved_by', 'approved_at', 'operations_approved', 'operations_approved_by', 'operations_approved_at', 'is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important Dates', {'fields': ('last_login', 'date_joined')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'password1', 'password2', 'role', 'applicant_type', 'department', 'employee_details', 'profile_image', 'passport_photo', 'id_document_image', 'license_number', 'registration_number'),
        }),
    )

    def get_actions(self, request):
        actions = super().get_actions(request)
        if getattr(request.user, "role", None) != "registrar":
            actions.pop("approve_selected_admin_accounts", None)
        return actions

    def approve_selected_admin_accounts(self, request, queryset):
        if getattr(request.user, "role", None) != "registrar":
            self.message_user(request, "Only a registrar can approve admin accounts.", level="error")
            return
        approved = 0
        for user in queryset.filter(role='admin'):
            user.role_approved = True
            user.approved_by = request.user
            user.approved_at = timezone.now()
            user.is_active = True
            user.is_staff = True
            user.save()
            approved += 1
        self.message_user(request, f"Approved {approved} admin account(s).")
    approve_selected_admin_accounts.short_description = "Approve selected admin accounts"

    def _selected_rows(self, queryset):
        return queryset.values_list('username', 'email', 'role', 'applicant_type', 'department', 'license_number', 'registration_number', 'is_active')

    def export_as_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="users.csv"'
        writer = csv.writer(response)
        writer.writerow(['Username', 'Email', 'Role', 'Applicant Type', 'Department', 'License No', 'Registration No', 'Active'])
        for row in self._selected_rows(queryset):
            writer.writerow(row)
        return response
    export_as_csv.short_description = "Export selected as CSV"

    def export_as_xlsx(self, request, queryset):
        buffer = BytesIO()
        df = pd.DataFrame(list(self._selected_rows(queryset)), columns=['Username', 'Email', 'Role', 'Applicant Type', 'Department', 'License No', 'Registration No', 'Active'])
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Users')
        response = HttpResponse(buffer.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = 'attachment; filename="users.xlsx"'
        return response
    export_as_xlsx.short_description = "Export selected as XLSX"

    def export_as_pdf(self, request, queryset):
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="users.pdf"'
        doc = SimpleDocTemplate(response, pagesize=landscape(letter))
        data = [['Username', 'Email', 'Role', 'Applicant Type', 'Department', 'License No', 'Registration No', 'Active']]
        data.extend([list(row) for row in self._selected_rows(queryset)])
        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f766e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#94a3b8')),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('LEADING', (0, 0), (-1, -1), 10),
        ]))
        doc.build([table])
        return response
    export_as_pdf.short_description = "Export selected as PDF"


@admin.register(OperationalAccessRequest)
class OperationalAccessRequestAdmin(admin.ModelAdmin):
    list_display = ('user', 'requested_office', 'status', 'requested_at', 'decided_by', 'decided_at')
    list_filter = ('requested_office', 'status')
    search_fields = ('user__username', 'user__email', 'user__department', 'reason', 'decision_note')
    autocomplete_fields = ('user', 'decided_by')


@admin.register(UserMFAChallenge)
class UserMFAChallengeAdmin(admin.ModelAdmin):
    list_display = ('user', 'purpose', 'delivery_channel', 'sent_to', 'attempts', 'created_at', 'expires_at', 'verified_at')
    list_filter = ('purpose', 'delivery_channel', 'verified_at')
    search_fields = ('user__username', 'user__email', 'sent_to')
    readonly_fields = ('code_hash', 'created_at', 'verified_at')


@admin.register(SecurityAuditEvent)
class SecurityAuditEventAdmin(admin.ModelAdmin):
    list_display = ('action', 'user', 'username', 'ip_address', 'path', 'created_at')
    list_filter = ('action', 'created_at')
    search_fields = ('username', 'user__username', 'user__email', 'ip_address', 'path', 'user_agent')
    readonly_fields = ('user', 'username', 'action', 'ip_address', 'user_agent', 'path', 'details', 'created_at')
