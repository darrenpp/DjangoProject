from django.contrib import admin
from django.contrib.contenttypes.admin import GenericTabularInline
from django import forms
from django.db.models import OuterRef, Subquery
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.template.response import TemplateResponse
from django.urls import path
from django.utils import timezone
from datetime import datetime
from io import BytesIO
import csv

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.competency.models import CompetencyAssessment

from .models import (
    Cadre,
    Location,
    Facility,
    TrainingInstitution,
    DocumentType,
    RegulatoryBody,
    ApplicationPathway,
    DynamicFormDefinition,
    DeceasedNotification,
    DocumentRequirement,
    EmployerVerificationRequest,
    NursingProfessional,
    Midwife,
    MedicalDoctor,
    CommunityHealthWorker,
    NurseAide,
    HealthStudent,
    Qualification,
    ProfessionalDocument,
    PostingHistory,
    CPDRecord,
    Application,
    ApplicationChecklistItem,
    ApplicationFormResponse,
    ApplicantDeclaration,
    ApplicationStatusHistory,
    AuditLog,
    DataImportBatch,
    DeclarationTemplate,
    FeeSchedule,
    ImportedWorkbookSheet,
    MissingDataReview,
    PolicyDocument,
    PracticingLicenseRecord,
    SupervisorAssignment,
    WorkforceSnapshot,
)


class CompetencyAssessmentInline(GenericTabularInline):
    model = CompetencyAssessment
    extra = 0


class QualificationInline(GenericTabularInline):
    model = Qualification
    extra = 0


class ProfessionalDocumentInline(GenericTabularInline):
    model = ProfessionalDocument
    extra = 0


class PostingHistoryInline(GenericTabularInline):
    model = PostingHistory
    extra = 0


class CPDRecordInline(GenericTabularInline):
    model = CPDRecord
    extra = 0


class ApplicationInline(GenericTabularInline):
    model = Application
    extra = 0


def _export_rows(modeladmin, queryset):
    fields = [field.name for field in queryset.model._meta.concrete_fields if field.name != 'id']
    rows = list(queryset.values_list(*fields))
    return fields, rows


def _excel_safe_value(value):
    if isinstance(value, datetime) and timezone.is_aware(value):
        return timezone.localtime(value).replace(tzinfo=None)
    return value


def _pdf_safe_text(value):
    if value is None:
        return ""
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.strftime("%Y-%m-%d %H:%M")
    text = str(value)
    if len(text) > 70:
        return f"{text[:67]}..."
    return text


def _humanize_header(field_name):
    return field_name.replace("_", " ").title()


def _pdf_column_widths(fields, rows, available_width):
    weights = []
    for index, field_name in enumerate(fields):
        header_weight = min(max(len(_humanize_header(field_name)), 6), 18)
        sample_weight = header_weight
        for row in rows[:25]:
            sample_weight = max(sample_weight, min(len(_pdf_safe_text(row[index])), 28))
        weights.append(sample_weight)

    total_weight = sum(weights) or 1
    min_width = 34
    widths = [max(min_width, available_width * weight / total_weight) for weight in weights]
    width_total = sum(widths)
    if width_total > available_width:
        scale = available_width / width_total
        widths = [max(26, width * scale) for width in widths]
    return widths


def export_as_csv(modeladmin, request, queryset):
    fields, rows = _export_rows(modeladmin, queryset)
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{queryset.model._meta.model_name}.csv"'
    writer = csv.writer(response)
    writer.writerow(fields)
    writer.writerows(rows)
    return response


def export_as_xlsx(modeladmin, request, queryset):
    fields, rows = _export_rows(modeladmin, queryset)
    buffer = BytesIO()
    excel_rows = [[_excel_safe_value(value) for value in row] for row in rows]
    df = pd.DataFrame(excel_rows, columns=fields)
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name=queryset.model._meta.verbose_name_plural[:31])
    response = HttpResponse(
        buffer.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{queryset.model._meta.model_name}.xlsx"'
    return response


def export_as_pdf(modeladmin, request, queryset):
    fields, rows = _export_rows(modeladmin, queryset)
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{queryset.model._meta.model_name}.pdf"'
    doc = SimpleDocTemplate(
        response,
        pagesize=landscape(letter),
        leftMargin=18,
        rightMargin=18,
        topMargin=18,
        bottomMargin=18,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ExportTitle",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=14,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=8,
    )
    header_style = ParagraphStyle(
        "ExportHeader",
        fontName="Helvetica-Bold",
        fontSize=6.2,
        leading=7,
        textColor=colors.white,
        alignment=1,
    )
    cell_style = ParagraphStyle(
        "ExportCell",
        fontName="Helvetica",
        fontSize=6,
        leading=7,
        textColor=colors.HexColor("#0f172a"),
        splitLongWords=True,
    )
    data = [[Paragraph(_humanize_header(field), header_style) for field in fields]]
    for row in rows:
        data.append([Paragraph(_pdf_safe_text(value), cell_style) for value in row])
    available_width = doc.width
    table = Table(data, repeatRows=1, colWidths=_pdf_column_widths(fields, rows, available_width), hAlign="LEFT")
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f766e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#94a3b8')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
    ]))
    title = f"{queryset.model._meta.verbose_name_plural.title()} Export"
    subtitle = f"{queryset.count()} selected record(s)"
    doc.build([
        Paragraph(title, title_style),
        Paragraph(subtitle, cell_style),
        Spacer(1, 8),
        table,
    ])
    return response


export_as_csv.short_description = "Export selected as CSV"
export_as_xlsx.short_description = "Export selected as XLSX"
export_as_pdf.short_description = "Export selected as PDF"


class NursingProfessionalImportForm(forms.Form):
    file = forms.FileField(help_text="Upload a CSV or Excel file.")


class NursingFullRegistrationYearFilter(admin.SimpleListFilter):
    title = "full registration year"
    parameter_name = "full_registration_year"

    def lookups(self, request, model_admin):
        years = (
            PracticingLicenseRecord.objects.filter(
                target_model="nursingprofessional",
                record_type="full",
                record_year__isnull=False,
            )
            .order_by("-record_year")
            .values_list("record_year", flat=True)
            .distinct()
        )
        return [(year, year) for year in years]

    def queryset(self, request, queryset):
        if not self.value():
            return queryset
        registration_numbers = PracticingLicenseRecord.objects.filter(
            target_model="nursingprofessional",
            record_type="full",
            record_year=self.value(),
        ).values("registration_no")
        return queryset.filter(registration_no__in=registration_numbers)


class NursingPractisingLicenseYearFilter(admin.SimpleListFilter):
    title = "practising licence year"
    parameter_name = "practising_licence_year"

    def lookups(self, request, model_admin):
        years = (
            PracticingLicenseRecord.objects.filter(
                target_model="nursingprofessional",
                record_type="practicing_license",
                record_year__isnull=False,
            )
            .order_by("-record_year")
            .values_list("record_year", flat=True)
            .distinct()
        )
        return [(year, year) for year in years]

    def queryset(self, request, queryset):
        if not self.value():
            return queryset
        registration_numbers = PracticingLicenseRecord.objects.filter(
            target_model="nursingprofessional",
            record_type="practicing_license",
            record_year=self.value(),
        ).values("registration_no")
        return queryset.filter(registration_no__in=registration_numbers)


class MedicalDoctorRegistrationYearFilter(admin.SimpleListFilter):
    title = "medical registration year"
    parameter_name = "medical_registration_year"

    def lookups(self, request, model_admin):
        years = (
            PracticingLicenseRecord.objects.filter(
                target_model="medicaldoctor",
                record_type__in=["full", "workforce_listing"],
                record_year__isnull=False,
            )
            .order_by("-record_year")
            .values_list("record_year", flat=True)
            .distinct()
        )
        return [(year, year) for year in years]

    def queryset(self, request, queryset):
        if not self.value():
            return queryset
        registration_numbers = PracticingLicenseRecord.objects.filter(
            target_model="medicaldoctor",
            record_type__in=["full", "workforce_listing"],
            record_year=self.value(),
        ).values("registration_no")
        return queryset.filter(registration_no__in=registration_numbers)


class MedicalDoctorLicenseYearFilter(admin.SimpleListFilter):
    title = "medical licence year"
    parameter_name = "medical_licence_year"

    def lookups(self, request, model_admin):
        years = (
            PracticingLicenseRecord.objects.filter(
                target_model="medicaldoctor",
                record_type="practicing_license",
                record_year__isnull=False,
            )
            .order_by("-record_year")
            .values_list("record_year", flat=True)
            .distinct()
        )
        return [(year, year) for year in years]

    def queryset(self, request, queryset):
        if not self.value():
            return queryset
        registration_numbers = PracticingLicenseRecord.objects.filter(
            target_model="medicaldoctor",
            record_type="practicing_license",
            record_year=self.value(),
        ).values("registration_no")
        return queryset.filter(registration_no__in=registration_numbers)


class CHWRegistrationYearFilter(admin.SimpleListFilter):
    title = "CHW registration year"
    parameter_name = "chw_registration_year"

    def lookups(self, request, model_admin):
        years = (
            PracticingLicenseRecord.objects.filter(
                target_model="communityhealthworker",
                record_type__in=["full", "workforce_listing"],
                record_year__isnull=False,
            )
            .order_by("-record_year")
            .values_list("record_year", flat=True)
            .distinct()
        )
        return [(year, year) for year in years]

    def queryset(self, request, queryset):
        if not self.value():
            return queryset
        registration_numbers = PracticingLicenseRecord.objects.filter(
            target_model="communityhealthworker",
            record_type__in=["full", "workforce_listing"],
            record_year=self.value(),
        ).values("registration_no")
        return queryset.filter(registration_no__in=registration_numbers)


class CHWLicenseYearFilter(admin.SimpleListFilter):
    title = "CHW licence year"
    parameter_name = "chw_licence_year"

    def lookups(self, request, model_admin):
        years = (
            PracticingLicenseRecord.objects.filter(
                target_model="communityhealthworker",
                record_type="practicing_license",
                record_year__isnull=False,
            )
            .order_by("-record_year")
            .values_list("record_year", flat=True)
            .distinct()
        )
        return [(year, year) for year in years]

    def queryset(self, request, queryset):
        if not self.value():
            return queryset
        registration_numbers = PracticingLicenseRecord.objects.filter(
            target_model="communityhealthworker",
            record_type="practicing_license",
            record_year=self.value(),
        ).values("registration_no")
        return queryset.filter(registration_no__in=registration_numbers)


@admin.register(Cadre)
class CadreAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'description')
    search_fields = ('name',)


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ('province', 'district', 'ward')
    list_filter = ('province',)
    search_fields = ('province', 'district')


@admin.register(Facility)
class FacilityAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'type', 'ownership', 'level')
    list_filter = ('ownership', 'level')
    search_fields = ('name',)
    autocomplete_fields = ('location',)


@admin.register(TrainingInstitution)
class TrainingInstitutionAdmin(admin.ModelAdmin):
    list_display = ('name', 'type', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name',)


@admin.register(DocumentType)
class DocumentTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_required', 'description')
    list_filter = ('is_required',)
    search_fields = ('name',)


@admin.register(RegulatoryBody)
class RegulatoryBodyAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('code', 'name')


@admin.register(ApplicationPathway)
class ApplicationPathwayAdmin(admin.ModelAdmin):
    list_display = (
        'pathway_code', 'pathway_name', 'regulatory_body', 'primary_form_code',
        'requires_payment', 'requires_employer', 'requires_institution',
        'requires_supervisor', 'public_visible', 'active', 'sort_order'
    )
    list_filter = (
        'regulatory_body', 'requires_payment', 'requires_employer',
        'requires_institution', 'requires_supervisor', 'public_visible', 'active'
    )
    search_fields = ('pathway_code', 'pathway_name', 'primary_form_code', 'checklist_code')
    autocomplete_fields = ('regulatory_body',)


@admin.register(DynamicFormDefinition)
class DynamicFormDefinitionAdmin(admin.ModelAdmin):
    list_display = ('form_code', 'form_name', 'version', 'regulatory_body', 'pathway', 'active')
    list_filter = ('regulatory_body', 'active', 'version')
    search_fields = ('form_code', 'form_name', 'pathway__pathway_code')
    autocomplete_fields = ('regulatory_body', 'pathway')


@admin.register(DocumentRequirement)
class DocumentRequirementAdmin(admin.ModelAdmin):
    list_display = (
        'label', 'document_type_code', 'pathway', 'required',
        'requires_certification', 'requires_translation', 'active', 'sort_order'
    )
    list_filter = ('required', 'requires_certification', 'requires_translation', 'active', 'pathway__regulatory_body')
    search_fields = ('label', 'document_type_code', 'pathway__pathway_code')
    autocomplete_fields = ('pathway', 'form_definition', 'document_type')


class BaseHealthProfessionalAdmin(admin.ModelAdmin):
    list_display = (
        'first_name', 'last_name', 'registration_no', 'applicant_type',
        'gender', 'primary_phone', 'email',
        'is_active', 'created_at'
    )
    list_filter = ('is_active', 'gender', 'applicant_type')
    search_fields = (
        'first_name', 'last_name',
        'registration_no'
    )
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('cadre',)

    inlines = [
        QualificationInline,
        ProfessionalDocumentInline,
        PostingHistoryInline,
        CPDRecordInline,
        ApplicationInline,
        CompetencyAssessmentInline,
    ]
    actions = [export_as_csv, export_as_xlsx, export_as_pdf]


@admin.register(NursingProfessional)
class NursingProfessionalAdmin(BaseHealthProfessionalAdmin):
    list_display = (
        'first_name', 'last_name', 'registration_no', 'applicant_type',
        'qualification_level', 'full_registration_year', 'practising_licence_year',
        'date_issued', 'license_expiry_date', 'is_active'
    )
    list_filter = (
        NursingFullRegistrationYearFilter,
        NursingPractisingLicenseYearFilter,
        'is_active',
        'gender',
        'applicant_type',
        ('date_issued', admin.DateFieldListFilter),
        ('license_expiry_date', admin.DateFieldListFilter),
    )
    search_fields = (
        'first_name', 'last_name', 'registration_no', 'registration_number',
        'email', 'primary_phone', 'qualification_level'
    )

    change_list_template = "admin/workforce/nursingprofessional_changelist.html"

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        full_year = (
            PracticingLicenseRecord.objects.filter(
                target_model="nursingprofessional",
                record_type="full",
                registration_no=OuterRef("registration_no"),
                record_year__isnull=False,
            )
            .order_by("-record_year")
            .values("record_year")[:1]
        )
        licence_year = (
            PracticingLicenseRecord.objects.filter(
                target_model="nursingprofessional",
                record_type="practicing_license",
                registration_no=OuterRef("registration_no"),
                record_year__isnull=False,
            )
            .order_by("-record_year")
            .values("record_year")[:1]
        )
        return queryset.annotate(
            admin_full_registration_year=Subquery(full_year),
            admin_practising_licence_year=Subquery(licence_year),
        )

    @admin.display(ordering="admin_full_registration_year", description="Full Reg Year")
    def full_registration_year(self, obj):
        return obj.admin_full_registration_year or (obj.date_issued.year if obj.date_issued else "-")

    @admin.display(ordering="admin_practising_licence_year", description="Licence Year")
    def practising_licence_year(self, obj):
        return obj.admin_practising_licence_year or (obj.license_expiry_date.year if obj.license_expiry_date else "-")

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path('import/', self.admin_site.admin_view(self.import_view), name='workforce_nursingprofessional_import'),
        ]
        return custom + urls

    def import_view(self, request):
        if request.method == 'POST':
            form = NursingProfessionalImportForm(request.POST, request.FILES)
            if form.is_valid():
                file = request.FILES['file']
                if file.name.endswith('.csv'):
                    df = pd.read_csv(file)
                else:
                    df = pd.read_excel(file)

                created = 0
                for _, row in df.iterrows():
                    reg_no = str(row.get('registration_no') or row.get('registration_number') or row.get('national_id') or '').strip()
                    if not reg_no:
                        continue
                    NursingProfessional.objects.update_or_create(
                        registration_no=reg_no,
                        defaults={
                            'first_name': str(row.get('first_name', '')).strip(),
                            'last_name': str(row.get('last_name', '')).strip(),
                            'email': str(row.get('email', '')).strip(),
                            'primary_phone': str(row.get('primary_phone', '')).strip(),
                            'qualification_level': str(row.get('qualification_level', '')).strip(),
                            'is_active': True,
                        }
                    )
                    created += 1
                self.message_user(request, f"Imported or updated {created} nursing records.")
                return redirect('admin:workforce_nursingprofessional_changelist')
        else:
            form = NursingProfessionalImportForm()
        context = dict(
            self.admin_site.each_context(request),
            title="Import Nursing Records",
            form=form,
            opts=self.model._meta,
        )
        return TemplateResponse(request, "admin/workforce/nursingprofessional_import.html", context)


@admin.register(Midwife)
class MidwifeAdmin(BaseHealthProfessionalAdmin):
    list_display = (
        'first_name', 'last_name', 'registration_no', 'applicant_type',
        'qualification_level', 'license_expiry_date', 'is_active'
    )


@admin.register(MedicalDoctor)
class MedicalDoctorAdmin(BaseHealthProfessionalAdmin):
    list_display = (
        'first_name', 'last_name', 'registration_no', 'applicant_type',
        'specialty', 'medical_registration_year', 'medical_licence_year',
        'date_issued', 'license_expiry_date', 'is_active'
    )
    list_filter = (
        MedicalDoctorRegistrationYearFilter,
        MedicalDoctorLicenseYearFilter,
        'is_active',
        'gender',
        'applicant_type',
        ('date_issued', admin.DateFieldListFilter),
        ('license_expiry_date', admin.DateFieldListFilter),
    )
    search_fields = (
        'first_name', 'last_name', 'registration_no', 'registration_number',
        'email', 'primary_phone', 'specialty'
    )

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        registration_year = (
            PracticingLicenseRecord.objects.filter(
                target_model="medicaldoctor",
                record_type__in=["full", "workforce_listing"],
                registration_no=OuterRef("registration_no"),
                record_year__isnull=False,
            )
            .order_by("-record_year")
            .values("record_year")[:1]
        )
        licence_year = (
            PracticingLicenseRecord.objects.filter(
                target_model="medicaldoctor",
                record_type="practicing_license",
                registration_no=OuterRef("registration_no"),
                record_year__isnull=False,
            )
            .order_by("-record_year")
            .values("record_year")[:1]
        )
        return queryset.annotate(
            admin_medical_registration_year=Subquery(registration_year),
            admin_medical_licence_year=Subquery(licence_year),
        )

    @admin.display(ordering="admin_medical_registration_year", description="Reg Year")
    def medical_registration_year(self, obj):
        return obj.admin_medical_registration_year or (obj.date_issued.year if obj.date_issued else "-")

    @admin.display(ordering="admin_medical_licence_year", description="Licence Year")
    def medical_licence_year(self, obj):
        return obj.admin_medical_licence_year or (obj.license_expiry_date.year if obj.license_expiry_date else "-")


@admin.register(CommunityHealthWorker)
class CommunityHealthWorkerAdmin(BaseHealthProfessionalAdmin):
    list_display = (
        'first_name', 'last_name', 'registration_no', 'applicant_type',
        'community_id', 'training_level', 'chw_registration_year',
        'chw_licence_year', 'is_active'
    )
    list_filter = (
        CHWRegistrationYearFilter,
        CHWLicenseYearFilter,
        'is_active',
        'gender',
        'applicant_type',
    )
    search_fields = (
        'first_name', 'last_name', 'registration_no', 'registration_number',
        'email', 'primary_phone', 'community_id', 'training_level'
    )

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        registration_year = (
            PracticingLicenseRecord.objects.filter(
                target_model="communityhealthworker",
                record_type__in=["full", "workforce_listing"],
                registration_no=OuterRef("registration_no"),
                record_year__isnull=False,
            )
            .order_by("-record_year")
            .values("record_year")[:1]
        )
        licence_year = (
            PracticingLicenseRecord.objects.filter(
                target_model="communityhealthworker",
                record_type="practicing_license",
                registration_no=OuterRef("registration_no"),
                record_year__isnull=False,
            )
            .order_by("-record_year")
            .values("record_year")[:1]
        )
        return queryset.annotate(
            admin_chw_registration_year=Subquery(registration_year),
            admin_chw_licence_year=Subquery(licence_year),
        )

    @admin.display(ordering="admin_chw_registration_year", description="Reg Year")
    def chw_registration_year(self, obj):
        return obj.admin_chw_registration_year or "-"

    @admin.display(ordering="admin_chw_licence_year", description="Licence Year")
    def chw_licence_year(self, obj):
        return obj.admin_chw_licence_year or "-"


@admin.register(NurseAide)
class NurseAideAdmin(BaseHealthProfessionalAdmin):
    list_display = (
        'first_name', 'last_name', 'registration_no', 'applicant_type',
        'training_level', 'employer', 'is_active'
    )


@admin.register(HealthStudent)
class HealthStudentAdmin(BaseHealthProfessionalAdmin):
    list_display = (
        'first_name', 'last_name', 'registration_no', 'applicant_type',
        'program', 'institution', 'is_graduate',
        'expected_graduation_date'
    )
    list_filter = ('is_graduate',)
    autocomplete_fields = ('institution',)


@admin.register(Qualification)
class QualificationAdmin(admin.ModelAdmin):
    list_display = ('qualification_name', 'professional', 'completion_year', 'institution')
    search_fields = ('qualification_name',)
    autocomplete_fields = ('institution',)


@admin.register(ProfessionalDocument)
class ProfessionalDocumentAdmin(admin.ModelAdmin):
    list_display = ('document_type', 'professional', 'uploaded_at')
    autocomplete_fields = ('document_type',)
    search_fields = ('document_label', 'document_type__name', 'verification_signature')


@admin.register(PostingHistory)
class PostingHistoryAdmin(admin.ModelAdmin):
    list_display = ('professional', 'facility', 'position_title', 'start_date', 'is_current')
    autocomplete_fields = ('facility',)


@admin.register(CPDRecord)
class CPDRecordAdmin(admin.ModelAdmin):
    list_display = ('professional', 'training_type', 'provider', 'start_date', 'hours_credits')


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ('form_code', 'status', 'submitted_date', 'approved_date', 'professional')
    list_filter = ('form_code', 'status')
    search_fields = ('reviewer_notes',)
    actions = [export_as_csv, export_as_xlsx, export_as_pdf]


@admin.register(ApplicationFormResponse)
class ApplicationFormResponseAdmin(admin.ModelAdmin):
    list_display = ('application', 'form_code', 'form_version', 'submitted_by', 'submitted_at', 'locked_at')
    list_filter = ('form_code', 'form_version', 'submitted_at')
    search_fields = ('form_code', 'application__reviewer_notes')
    autocomplete_fields = ('application', 'submitted_by', 'locked_by')
    readonly_fields = ('submitted_at',)


@admin.register(ApplicationChecklistItem)
class ApplicationChecklistItemAdmin(admin.ModelAdmin):
    list_display = ('application', 'document_requirement', 'status', 'verified_by', 'verified_at')
    list_filter = ('status', 'document_requirement__pathway__regulatory_body')
    search_fields = ('application__reviewer_notes', 'document_requirement__label')
    autocomplete_fields = ('application', 'document_requirement', 'document', 'verified_by')


@admin.register(FeeSchedule)
class FeeScheduleAdmin(admin.ModelAdmin):
    list_display = ('fee_rule_code', 'label', 'regulatory_body', 'applicant_type', 'amount', 'currency', 'active')
    list_filter = ('regulatory_body', 'applicant_type', 'active')
    search_fields = ('fee_rule_code', 'label')
    autocomplete_fields = ('regulatory_body', 'pathway')


@admin.register(PolicyDocument)
class PolicyDocumentAdmin(admin.ModelAdmin):
    list_display = ('code', 'title', 'regulatory_body', 'version', 'effective_from', 'active')
    list_filter = ('regulatory_body', 'active', 'version')
    search_fields = ('code', 'title')
    autocomplete_fields = ('regulatory_body',)


@admin.register(DeclarationTemplate)
class DeclarationTemplateAdmin(admin.ModelAdmin):
    list_display = ('code', 'title', 'regulatory_body', 'required_for_pathway', 'active')
    list_filter = ('regulatory_body', 'active')
    search_fields = ('code', 'title', 'required_for_pathway__pathway_code')
    autocomplete_fields = ('regulatory_body', 'required_for_pathway')


@admin.register(ApplicantDeclaration)
class ApplicantDeclarationAdmin(admin.ModelAdmin):
    list_display = ('application', 'declaration_template', 'accepted_by', 'accepted_at')
    list_filter = ('accepted_at', 'declaration_template__regulatory_body')
    search_fields = ('application__reviewer_notes', 'declaration_template__code')
    autocomplete_fields = ('application', 'declaration_template', 'accepted_by')


@admin.register(ApplicationStatusHistory)
class ApplicationStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ('application', 'old_status', 'new_status', 'changed_by', 'reason', 'created_at')
    list_filter = ('new_status', 'created_at')
    search_fields = ('application__reviewer_notes', 'reason', 'comment')
    autocomplete_fields = ('application', 'changed_by', 'supporting_document')
    readonly_fields = ('created_at',)


@admin.register(EmployerVerificationRequest)
class EmployerVerificationRequestAdmin(admin.ModelAdmin):
    list_display = ('employer_name', 'facility_name', 'professional', 'status', 'requester', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('employer_name', 'facility_name', 'comments')
    autocomplete_fields = ('application', 'facility', 'requester')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(SupervisorAssignment)
class SupervisorAssignmentAdmin(admin.ModelAdmin):
    list_display = ('application', 'supervisor_name', 'supervisor_registration_number', 'status', 'assigned_at', 'completed_at')
    list_filter = ('status', 'assigned_at')
    search_fields = ('supervisor_name', 'supervisor_registration_number', 'employer_name', 'notes')
    autocomplete_fields = ('application', 'facility', 'supervisor_user')
    readonly_fields = ('assigned_at',)


@admin.register(DeceasedNotification)
class DeceasedNotificationAdmin(admin.ModelAdmin):
    list_display = ('name_at_report', 'registration_number', 'workforce_category', 'date_of_death', 'verification_status', 'registrar_approved_by')
    list_filter = ('verification_status', 'workforce_category', 'date_of_death')
    search_fields = ('name_at_report', 'registration_number', 'practitioner_number', 'facility_name', 'comments')
    autocomplete_fields = ('reported_by_facility', 'supporting_document', 'reported_by', 'verified_by', 'registrar_approved_by')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('action', 'entity_type', 'entity_id', 'actor', 'created_at')
    list_filter = ('action', 'entity_type', 'created_at')
    search_fields = ('action', 'entity_type', 'entity_id', 'actor__username')
    autocomplete_fields = ('actor',)
    readonly_fields = ('created_at',)


@admin.register(WorkforceSnapshot)
class WorkforceSnapshotAdmin(admin.ModelAdmin):
    list_display = ('year', 'total_active_workers', 'total_nurses', 'total_midwives')
    ordering = ('-year',)
    actions = [export_as_csv, export_as_xlsx, export_as_pdf]


@admin.register(DataImportBatch)
class DataImportBatchAdmin(admin.ModelAdmin):
    list_display = (
        'source_file_name', 'source_kind', 'status', 'total_sheets',
        'processed_sheets', 'total_rows', 'processed_rows', 'started_at', 'completed_at'
    )
    list_filter = ('status', 'source_kind', 'started_at')
    search_fields = ('source_file_name', 'source_file_path')
    readonly_fields = ('started_at', 'completed_at', 'summary')
    actions = [export_as_csv, export_as_xlsx, export_as_pdf]


@admin.register(ImportedWorkbookSheet)
class ImportedWorkbookSheetAdmin(admin.ModelAdmin):
    list_display = ('sheet_name', 'sheet_type', 'status', 'raw_rows', 'imported_rows', 'skipped_rows', 'batch')
    list_filter = ('status', 'sheet_type')
    search_fields = ('sheet_name', 'batch__source_file_name')
    autocomplete_fields = ('batch',)
    actions = [export_as_csv, export_as_xlsx, export_as_pdf]


@admin.register(PracticingLicenseRecord)
class PracticingLicenseRecordAdmin(admin.ModelAdmin):
    list_display = (
        'full_name', 'record_type', 'record_year', 'registration_no',
        'practitioner_number', 'category', 'province', 'payment_date'
    )
    list_filter = ('record_type', 'record_year', 'target_model', 'province', 'applicant_type')
    search_fields = ('full_name', 'registration_no', 'practitioner_number', 'category', 'province')
    autocomplete_fields = ('batch', 'sheet')
    actions = [export_as_csv, export_as_xlsx, export_as_pdf]


@admin.register(MissingDataReview)
class MissingDataReviewAdmin(admin.ModelAdmin):
    list_display = (
        'full_name', 'professional_type', 'registration_no', 'missing_count',
        'severity', 'status', 'notification_sent', 'email_sent', 'updated_at'
    )
    list_filter = ('status', 'severity', 'professional_type', 'notification_sent', 'email_sent')
    search_fields = ('full_name', 'registration_no', 'email', 'source_label')
    readonly_fields = (
        'content_type', 'object_id', 'record', 'full_name', 'registration_no',
        'email', 'professional_type', 'missing_fields', 'missing_count',
        'source_label', 'source_row', 'notification_sent', 'email_sent',
        'notified_at', 'resolved_at', 'created_at', 'updated_at'
    )
    actions = [export_as_csv, export_as_xlsx, export_as_pdf]
