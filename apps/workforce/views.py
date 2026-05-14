from datetime import date, timedelta
from tempfile import NamedTemporaryFile
import pandas as pd

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import Http404, JsonResponse
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.views.generic import View, DetailView, UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.views.decorators.http import require_POST

from .forms import (
    ApplicationForm,
    CouncilApplicationForm,
    GraduateMidwifeBatchListForm,
    GraduateMidwivesChecklistForm,
    GraduateNurseBatchListForm,
    GraduateNursesChecklistForm,
    GraduateVitaeForm,
    ImportForm,
    MidwifeCompetencyStatementForm,
    NC10ChildNursingCompetencyForm,
    NC11DoubleMajorChecklistForm,
    NC1ProvisionalLicenceForm,
    NC2FullLicenceForm,
    NC3RenewalLicenceForm,
    NC4ProvisionalChecklistForm,
    NC5OverseasFullRegistrationForm,
    NC6NursingCompetencyForm,
    NC7MidwiferyCompetencyForm,
    NC8TemporaryLicenceForm,
    NC9TemporaryChecklistForm,
    NurseCompetencyStatementForm,
    NursingPublicRegistrationForm,
    NursingFullLicenseForm,
    NursingRenewalForm,
    ChwPublicRegistrationForm,
    MedicalDoctorPublicRegistrationForm,
    MedicalBoardAccreditationChecklistForm,
    MedicalBoardChwRegistrationForm,
    MedicalBoardPrivateHealthFacilityChecklistForm,
    MedicalBoardRenewalRegistrationForm,
    MedicalBoardSpecialistApplicationForm,
    MedicalBoardTrainingCollegeFacilityForm,
    HealthStudentPublicRegistrationForm,
    NurseAidePublicRegistrationForm,
    ProfessionalPhotoForm,
    ProfessionalDocumentForm,
)
from .models import (
    NursingProfessional, MedicalDoctor, Midwife, CommunityHealthWorker, NurseAide,
    HealthStudent, Application, DataImportBatch, ProfessionalDocument, ProfessionalPhoto, PostingHistory, CPDRecord,
    Qualification, ApplicationChecklistItem, DeceasedNotification, EmployerVerificationRequest, SupervisorAssignment,
)
from ..accounts.models import User
from ..dashboard.models import Receipt
from ..dashboard.access import (
    can_manage_regulatory_operations,
    can_access_application_record,
    can_access_professional_record,
    is_data_quality_reviewer,
    is_medical_board_user,
    is_nursing_council_user,
    is_staff_dashboard_user,
)
from ..documents.access import can_view_document
from ..documents.models import Document
from ..notifications.views import send_application_status_email
from .services.ndata_workbook_import import DEFAULT_WORKBOOK, NDataWorkbookImporter
from .services.medical_board_workbook_import import (
    DEFAULT_MEDICAL_BOARD_WORKBOOK,
    MedicalBoardWorkbookImporter,
    is_medical_board_chw_workbook,
)
from .services.medical_board_legacy_import import MedicalBoardLegacyWorkbookImporter
from .services.nursing_council_workflows import (
    approve_deceased_notification,
    approve_nursing_application,
    build_public_form_guide,
    complete_supervisor_competency,
    create_deceased_notification,
    create_employer_verification_request,
    create_supervisor_assignment,
    generate_application_checklist,
    is_nursing_council_application,
    prepare_nursing_application_submission,
    reject_nursing_application,
    review_checklist_item,
    search_public_nursing_register,
    verify_application_payment,
)


def _professional_queryset(model, user):
    identifiers = [
        value for value in [
            getattr(user, "registration_number", None),
            getattr(user, "license_number", None),
            user.username,
        ]
        if value
    ]
    if not identifiers:
        return model.objects.none()
    return model.objects.filter(Q(registration_no__in=identifiers) | Q(email=user.email))


def _application_queryset_for(obj):
    if not obj:
        return Application.objects.none()
    ct = ContentType.objects.get_for_model(obj)
    return Application.objects.filter(content_type=ct, object_id=obj.id)


def _get_professional_by_pk(pk):
    for model in [NursingProfessional, MedicalDoctor, Midwife, CommunityHealthWorker, NurseAide, HealthStudent]:
        obj = model.objects.filter(pk=pk).first()
        if obj:
            return obj
    return None


def _can_access_professional_detail(user, professional):
    if can_access_professional_record(user, professional):
        return True
    if not getattr(user, "is_authenticated", False):
        return False
    return is_data_quality_reviewer(user)


# ====================== IMPORT VIEW ======================

class ImportDataView(LoginRequiredMixin, View):
    template_name = "workforce/import.html"

    def dispatch(self, request, *args, **kwargs):
        if not is_staff_dashboard_user(request.user):
            return redirect("main_dashboard")
        return super().dispatch(request, *args, **kwargs)

    def _import_scope(self, user):
        if is_medical_board_user(user) and not is_nursing_council_user(user):
            return "medical"
        return "nursing"

    def _recent_batches(self, user):
        source_kinds = ["medical_board_workbook"] if self._import_scope(user) == "medical" else ["ndata_workbook", "nursing_license_workbook"]
        batches = DataImportBatch.objects.filter(source_kind__in=source_kinds).order_by('-started_at')[:8]
        batch_rows = []
        for batch in batches:
            total_steps = batch.total_rows or batch.total_sheets or 0
            completed_steps = batch.processed_rows or batch.processed_sheets or 0
            progress = 100 if batch.status == 'completed' else int((completed_steps / total_steps) * 100) if total_steps else 0
            batch_rows.append({
                'batch': batch,
                'progress': max(0, min(progress, 100)),
            })
        return batch_rows

    def _render(self, request, form):
        import_scope = self._import_scope(request.user)
        default_workbook = DEFAULT_MEDICAL_BOARD_WORKBOOK if import_scope == "medical" else DEFAULT_WORKBOOK
        return render(request, self.template_name, {
            "form": form,
            "recent_batches": self._recent_batches(request.user),
            "default_workbook": str(default_workbook),
            "default_workbook_exists": default_workbook.exists(),
            "import_scope": import_scope,
        })

    def get(self, request):
        return self._render(request, ImportForm())

    def post(self, request):
        import_mode = request.POST.get("import_mode", "generic")
        import_scope = self._import_scope(request.user)
        if import_mode in {"default_workbook", "ndata_default"}:
            try:
                if import_scope == "medical":
                    batch = MedicalBoardWorkbookImporter(
                        workbook_path=DEFAULT_MEDICAL_BOARD_WORKBOOK,
                        initiated_by=request.user,
                    ).import_workbook()
                    messages.success(request, f'Medical Board CHW workbook imported successfully in batch #{batch.id}.')
                else:
                    batch = NDataWorkbookImporter(
                        workbook_path=DEFAULT_WORKBOOK,
                        initiated_by=request.user,
                    ).import_workbook()
                    messages.success(request, f'N-DATA workbook imported successfully in batch #{batch.id}.')
            except Exception as exc:
                messages.error(request, f'Workbook import failed: {exc}')
            return redirect("main_dashboard")

        form = ImportForm(request.POST, request.FILES)
        if not form.is_valid():
            return self._render(request, form)

        file = request.FILES["file"]

        try:
            if file.name.lower().endswith((".xlsx", ".xlsm", ".xls")):
                with NamedTemporaryFile(delete=False, suffix=file.name[file.name.rfind("."):]) as temp_file:
                    for chunk in file.chunks():
                        temp_file.write(chunk)
                    temp_path = temp_file.name

                try:
                    is_medical_workbook = is_medical_board_chw_workbook(temp_path)
                    if import_scope == "medical":
                        if is_medical_workbook:
                            batch = MedicalBoardWorkbookImporter(
                                workbook_path=temp_path,
                                initiated_by=request.user,
                            ).import_workbook()
                            messages.success(request, f'Medical Board CHW workbook imported successfully in batch #{batch.id}.')
                        else:
                            batch = MedicalBoardLegacyWorkbookImporter(
                                workbook_paths=[temp_path],
                                initiated_by=request.user,
                            ).import_workbooks()
                            messages.success(request, f'Medical Board legacy workbook imported successfully in batch #{batch.id}.')
                    elif is_medical_workbook:
                        batch = MedicalBoardWorkbookImporter(
                            workbook_path=temp_path,
                            initiated_by=request.user,
                        ).import_workbook()
                        messages.success(request, f'Medical Board CHW workbook imported successfully in batch #{batch.id}.')
                    else:
                        batch = NDataWorkbookImporter(
                            workbook_path=temp_path,
                            initiated_by=request.user,
                        ).import_workbook()
                        messages.success(request, f'Workbook imported successfully in batch #{batch.id}.')
                    return redirect("main_dashboard")
                finally:
                    try:
                        import os
                        os.unlink(temp_path)
                    except OSError:
                        pass

            if file.name.endswith(".csv"):
                df = pd.read_csv(file)
            else:
                messages.error(request, "Unsupported file format.")
                return redirect("import_data")

            REQUIRED_COLUMNS = ["first_name", "last_name"]

            for col in REQUIRED_COLUMNS:
                if col not in df.columns:
                    messages.error(request, f"Missing required column: {col}")
                    return redirect("import_data")

            imported_count = 0

            with transaction.atomic():
                for _, row in df.iterrows():
                    registration_no = row.get("registration_no") or row.get("national_id")
                    if not registration_no:
                        continue

                    NursingProfessional.objects.update_or_create(
                        registration_no=registration_no,
                        defaults={
                            "first_name": row.get("first_name", ""),
                            "last_name": row.get("last_name", ""),
                            "email": row.get("email", ""),
                            "primary_phone": row.get("primary_phone", ""),
                        }
                    )
                    imported_count += 1

            messages.success(request, f"Imported {imported_count} records.")
            return redirect("main_dashboard")

        except Exception as exc:
            messages.error(request, f"Import failed: {exc}")
            return self._render(request, form)


# ====================== PUBLIC REGISTRATION ======================

class PublicRegistrationView(View):
    template_name = "workforce/public_register.html"
    medical_template_name = "workforce/medical_board_register.html"

    FORM_MAP = {
        "G1": GraduateNursesChecklistForm,
        "G2": GraduateNurseBatchListForm,
        "G3": GraduateVitaeForm,
        "G4": NurseCompetencyStatementForm,
        "G5": MidwifeCompetencyStatementForm,
        "G6": GraduateMidwivesChecklistForm,
        "G7": GraduateMidwifeBatchListForm,
        "NC1": NC1ProvisionalLicenceForm,
        "NC2": NC2FullLicenceForm,
        "NC3": NC3RenewalLicenceForm,
        "NC4": NC4ProvisionalChecklistForm,
        "NC5": NC5OverseasFullRegistrationForm,
        "NC6": NC6NursingCompetencyForm,
        "NC7": NC7MidwiferyCompetencyForm,
        "NC8": NC8TemporaryLicenceForm,
        "NC9": NC9TemporaryChecklistForm,
        "NC10": NC10ChildNursingCompetencyForm,
        "NC11": NC11DoubleMajorChecklistForm,
        "MBSP": MedicalBoardSpecialistApplicationForm,
        "MBRN": MedicalBoardRenewalRegistrationForm,
        "MBAC": MedicalBoardAccreditationChecklistForm,
        "MBPF": MedicalBoardPrivateHealthFacilityChecklistForm,
        "MBTC": MedicalBoardTrainingCollegeFacilityForm,
        "CHW1": MedicalBoardChwRegistrationForm,
    }
    LEGACY_FORM_MAP = {
        "public_nurse_provisional_register": "NC1",
        "public_nurse_register": "NC1",
        "public_nurse_full_license": "NC2",
        "public_nurse_renewal": "NC3",
        "public_graduand_register": "G3",
        "public_chw_register": ChwPublicRegistrationForm,
        "public_doctor_register": MedicalDoctorPublicRegistrationForm,
        "public_nurse_aide_register": NurseAidePublicRegistrationForm,
    }
    LEGACY_APPLICATION_CODES = {
        "public_chw_register": "CHW1",
        "public_doctor_register": "MD1",
        "public_nurse_aide_register": "NC2",
    }
    MEDICAL_BOARD_CODES = {"MD1", "MD2", "CHW1", "MBSP", "MBRN", "MBAC", "MBPF", "MBTC"}
    FORM_GUIDE = {
        "local_nursing_graduate": [
            ("G1", "Graduate Nurses Checklist"),
            ("G2", "List of New Graduate Nurses for Provisional Licence"),
            ("G3", "Graduate Vitae"),
            ("G4", "Statement of Competency (Nurses)"),
            ("NC1", "Application for Provisional Licence"),
            ("NC6", "Competency for Full Licence Nursing"),
            ("NC2", "Application for Full Licence"),
            ("NC3", "Renewal of Licence"),
        ],
        "local_midwifery_graduate": [
            ("G6", "Graduate Midwives Checklist"),
            ("G7", "List of Graduate Midwives for Licence to Practise"),
            ("G3", "Graduate Vitae"),
            ("G5", "Statement of Competency (Midwives)"),
            ("NC1", "Application for Provisional Licence"),
            ("NC7", "Competency for Full Licence Midwifery"),
            ("NC2", "Application for Full Licence"),
            ("NC3", "Renewal of Licence"),
        ],
        "overseas_nurse": [
            ("NC1", "Application for Provisional Licence"),
            ("NC4", "Checklist for Provisional Licence"),
            ("NC6", "Competency for Full Licence Nursing"),
            ("NC5", "Application for Full Registration & Licence"),
            ("NC10", "Competency for Full Licence Child Nursing"),
            ("NC8", "Application for Temporary Licence"),
            ("NC9", "Checklist for Temporary Licence"),
        ],
        "overseas_midwife": [
            ("NC1", "Application for Provisional Licence"),
            ("NC4", "Checklist for Provisional Licence"),
            ("NC7", "Competency for Full Licence Midwifery"),
            ("NC5", "Application for Full Registration & Licence"),
            ("NC8", "Application for Temporary Licence"),
            ("NC9", "Checklist for Temporary Licence"),
        ],
        "special_case": [
            ("NC11", "Double Major Full Registration Checklist"),
        ],
    }
    MEDICAL_BOARD_FORM_GUIDE = {
        "practitioners": [
            ("CHW1", "Community Health Worker Registration"),
            ("MBRN", "Renewal Registration for Doctors, Specialists and CHWs"),
            ("MBSP", "Application for Specialist Registration"),
        ],
        "facilities": [
            ("MBAC", "Accreditation Checklist for Facilities"),
            ("MBPF", "Private Health Facilities Checklist"),
            ("MBTC", "Training Colleges Facilities Form"),
        ],
    }

    def dispatch(self, request, *args, **kwargs):
        form_code = kwargs.get("form_code")
        url_name = request.resolver_match.url_name
        is_medical_board = self.is_medical_board_request(form_code, url_name)
        if request.user.is_authenticated:
            role = getattr(request.user, "role", "")
            if role in {"doctor", "chw"} and not is_medical_board:
                messages.info(request, "Medical Board users should use the Medical Board registration forms.")
                return redirect("medical_board_register")
            if role in {"nurse", "nurse_aide", "graduand", "student"} and is_medical_board:
                messages.info(request, "Nursing Council users should use the Nursing Council registration forms.")
                return redirect("nursing_forms_portal")
        if request.user.is_authenticated and request.user.role == 'registrar':
            if is_medical_board and not is_medical_board_user(request.user):
                messages.warning(request, "Medical Board forms are restricted to Medical Board staff and administrators.")
                return redirect('registrar_dashboard')
            if not is_medical_board and not is_nursing_council_user(request.user):
                messages.warning(request, "Nursing Council forms are restricted to Nursing Council staff and administrators.")
                return redirect('registrar_dashboard')
        return super().dispatch(request, *args, **kwargs)

    def is_medical_board_request(self, form_code="", url_name=""):
        return url_name in {"medical_board_register", "medical_board_form_register"} or form_code in self.MEDICAL_BOARD_CODES

    def template_for_request(self, form_code="", url_name=""):
        if self.is_medical_board_request(form_code, url_name):
            return self.medical_template_name
        return self.template_name

    def get_form_class(self, form_code, url_name):
        if form_code:
            return self.FORM_MAP.get(form_code)
        legacy = self.LEGACY_FORM_MAP.get(url_name)
        if isinstance(legacy, str):
            return self.FORM_MAP.get(legacy)
        return legacy

    def get_form_descriptor(self, form_class, url_name=""):
        if not form_class:
            return None
        return {
            "code": getattr(form_class, "form_code", ""),
            "title": getattr(form_class, "form_title", "Online Registration"),
            "help": f"Complete all required sections for {getattr(form_class, 'form_title', 'this application')}.",
        }

    def get(self, request, *args, **kwargs):
        form_code = kwargs.get("form_code")
        url_name = request.resolver_match.url_name
        form_class = self.get_form_class(form_code, url_name)
        template_name = self.template_for_request(form_code, url_name)
        is_medical_board = self.is_medical_board_request(form_code, url_name)
        nursing_form_guide = build_public_form_guide() or self.FORM_GUIDE
        if not form_class:
            return render(request, template_name, {
                "form": None,
                "flow_title": "Medical Board Forms" if is_medical_board else "Nursing Council Forms",
                "flow_help": "Choose the correct Medical Board practitioner or facility form below." if is_medical_board else "Choose the correct applicant pathway and form code below.",
                "form_guide": self.MEDICAL_BOARD_FORM_GUIDE if is_medical_board else nursing_form_guide,
                "is_medical_board": is_medical_board,
            })

        descriptor = self.get_form_descriptor(form_class, url_name)
        return render(request, template_name, {
            "form": form_class(),
            "flow_title": f"{descriptor['code']} - {descriptor['title']}",
            "flow_help": descriptor["help"],
            "form_code": descriptor["code"],
            "form_guide": self.MEDICAL_BOARD_FORM_GUIDE if is_medical_board else nursing_form_guide,
            "is_medical_board": is_medical_board,
        })

    def post(self, request, *args, **kwargs):
        form_code = kwargs.get("form_code")
        url_name = request.resolver_match.url_name
        form_class = self.get_form_class(form_code, url_name)
        descriptor = self.get_form_descriptor(form_class, url_name)
        form = form_class(request.POST, request.FILES)
        template_name = self.template_for_request(form_code, url_name)
        is_medical_board = self.is_medical_board_request(form_code, url_name)
        nursing_form_guide = build_public_form_guide() or self.FORM_GUIDE

        if form.is_valid():
            result = form.save()
            if not isinstance(form, CouncilApplicationForm):
                application_code = self.LEGACY_APPLICATION_CODES.get(url_name)
                if application_code:
                    Application.objects.create(
                        content_type=ContentType.objects.get_for_model(result),
                        object_id=result.id,
                        form_code=application_code,
                        form_title=descriptor["title"] if descriptor else "",
                        status="pending",
                        reviewer_notes="Submitted via public portal",
                    )
            messages.success(request, "Registration submitted successfully.")
            if form_code:
                if is_medical_board:
                    return redirect("medical_board_form_register", form_code=form_code)
                return redirect("public_form_code_register", form_code=form_code)
            return redirect(request.resolver_match.url_name)

        return render(request, template_name, {
            "form": form,
            "flow_title": f"{descriptor['code']} - {descriptor['title']}" if descriptor else "Online Registration",
            "flow_help": descriptor["help"] if descriptor else "Submit your registration details below.",
            "form_code": descriptor["code"] if descriptor else "",
            "form_guide": self.MEDICAL_BOARD_FORM_GUIDE if is_medical_board else nursing_form_guide,
            "is_medical_board": is_medical_board,
        })


# ====================== DETAIL VIEW (FIXED) ======================

class ProfessionalDetailView(LoginRequiredMixin, DetailView):
    template_name = 'workforce/professional_detail.html'
    context_object_name = 'object'

    def get_object(self, **kwargs):
        pk = self.kwargs.get("pk")
        obj = _get_professional_by_pk(pk)
        if obj and _can_access_professional_detail(self.request.user, obj):
            return obj
        raise Http404("Professional not found")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        obj = self.object

        ct = ContentType.objects.get_for_model(obj)

        context.update({
            "model_slug": obj.__class__.__name__.lower(),
            "documents": ProfessionalDocument.objects.filter(content_type=ct, object_id=obj.id),
            "photos": ProfessionalPhoto.objects.filter(content_type=ct, object_id=obj.id),
            "postings": PostingHistory.objects.filter(content_type=ct, object_id=obj.id),
            "cpd_count": CPDRecord.objects.filter(content_type=ct, object_id=obj.id).count(),
            "can_upload_professional_media": can_manage_regulatory_operations(self.request.user),
            "qualification_records": Qualification.objects.filter(
                content_type=ct,
                object_id=obj.id,
            ).select_related("institution").order_by("-date_completed", "-completion_year", "qualification_name"),
            "photo_form": ProfessionalPhotoForm(),
            "document_form": ProfessionalDocumentForm(),
        })

        return context


class ApplicationDetailView(LoginRequiredMixin, DetailView):
    model = Application
    template_name = 'workforce/application_detail.html'

    def get_object(self, queryset=None):
        application = super().get_object(queryset=queryset)
        if not can_access_application_record(self.request.user, application):
            raise Http404("Application not found")
        return application

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["can_edit_application"] = is_registrar(self.request.user)
        application = self.object
        if is_nursing_council_application(application):
            prepare_nursing_application_submission(application, actor=self.request.user, request=self.request)
        app_ct = ContentType.objects.get_for_model(application)
        repository_evidence = list(
            Document.objects.filter(
                related_content_type=app_ct,
                related_object_id=application.pk,
            ).select_related("folder", "document_type").prefetch_related("versions").order_by("-updated_at")
        )
        professional = getattr(application, "professional", None)
        if professional:
            professional_ct = ContentType.objects.get_for_model(professional)
            repository_evidence.extend(
                Document.objects.filter(
                    related_content_type=professional_ct,
                    related_object_id=professional.pk,
                ).select_related("folder", "document_type").prefetch_related("versions").order_by("-updated_at")[:10]
            )
        context["repository_evidence"] = [
            document for document in repository_evidence
            if can_view_document(self.request.user, document)
        ]
        context["checklist_items"] = ApplicationChecklistItem.objects.filter(
            application=application,
        ).select_related("document_requirement", "document", "verified_by")
        context["application_receipts"] = Receipt.objects.filter(application=application).order_by("-transaction_date")
        context["status_history"] = application.status_history.select_related("changed_by").all()[:20]
        context["supervisor_assignments"] = SupervisorAssignment.objects.filter(application=application).select_related("supervisor_user")
        context["is_nursing_application"] = is_nursing_council_application(application)
        return context


class ApplicationUpdateView(LoginRequiredMixin, UpdateView):
    model = Application
    form_class = ApplicationForm
    template_name = 'workforce/application_form.html'

    def dispatch(self, request, *args, **kwargs):
        if not is_registrar(request.user):
            raise Http404("Application not found")
        return super().dispatch(request, *args, **kwargs)

    def get_object(self, queryset=None):
        application = super().get_object(queryset=queryset)
        if not can_access_application_record(self.request.user, application):
            raise Http404("Application not found")
        return application

    def form_valid(self, form):
        old_application = self.get_object()
        old_status = old_application.status
        application = form.save(commit=False)
        if application.status == "approved" and old_status != "approved":
            application.status = old_status
            application.save()
            result = approve_nursing_application(application, actor=self.request.user, request=self.request)
            if not result.get("approved"):
                for error in result.get("errors", []):
                    messages.error(self.request, error)
                return redirect('application_detail', pk=application.pk)
            messages.success(self.request, "Application approved through the configured workflow.")
            return redirect('application_detail', pk=application.pk)
        if application.status == "rejected" and old_status != "rejected":
            application.status = old_status
            application.save()
            reject_nursing_application(application, actor=self.request.user, request=self.request, reason=application.reviewer_notes)
            messages.success(self.request, "Application rejected through the configured workflow.")
            return redirect('application_detail', pk=application.pk)
        if application.status in {'approved', 'rejected'} and not application.reviewed_by:
            application.reviewed_by = self.request.user
        application.save()
        messages.success(self.request, "Application updated successfully.")
        return redirect('application_detail', pk=application.pk)


@login_required
def upload_professional_media(request, pk):
    if not can_manage_regulatory_operations(request.user):
        raise Http404("Professional not found")

    professional = _get_professional_by_pk(pk)
    if not professional or not can_access_professional_record(request.user, professional):
        raise Http404("Professional not found")

    ct = ContentType.objects.get_for_model(professional)
    if request.method == "POST":
        media_type = request.POST.get("media_type")
        if media_type == "photo":
            form = ProfessionalPhotoForm(request.POST, request.FILES)
            if form.is_valid():
                photo = form.save(commit=False)
                photo.content_type = ct
                photo.object_id = professional.id
                photo.save()
        else:
            form = ProfessionalDocumentForm(request.POST, request.FILES)
            if form.is_valid():
                doc = form.save(commit=False)
                doc.content_type = ct
                doc.object_id = professional.id
                doc.save()
        return redirect("professional_detail", pk=professional.id)

    return redirect("professional_detail", pk=professional.id)


# ====================== DASHBOARDS ======================

@login_required
def professional_dashboard(request):
    professional = _professional_queryset(NursingProfessional, request.user).first()
    applications = _application_queryset_for(professional)

    return render(request, 'workforce/professional_dashboard.html', {
        'applications': applications,
        'professional': professional,
    })


@login_required
def admin_dashboard(request):
    return redirect('/dashboard/admin/')


@login_required
def registrar_dashboard(request):
    return redirect('/dashboard/registrar/')


# ====================== APPROVAL (SECURED) ======================

def is_registrar(user):
    return can_manage_regulatory_operations(user) or (
        user.is_authenticated
        and user.is_active
        and user.groups.filter(name="Registrar").exists()
    )


@login_required
@user_passes_test(is_registrar)
def approve_application(request, pk):
    if request.method != "POST":
        return redirect("registrar_dashboard")

    app = get_object_or_404(Application, pk=pk)
    if not can_access_application_record(request.user, app):
        raise Http404("Application not found")

    result = approve_nursing_application(app, actor=request.user, request=request)
    if not result.get("approved"):
        for error in result.get("errors", []):
            messages.error(request, error)
        messages.warning(request, "Application was not approved because required workflow checks are incomplete.")
        return redirect('application_detail', pk=app.pk)

    send_application_status_email(app)

    messages.success(request, "Application approved.")
    return redirect('registrar_dashboard')


@login_required
@user_passes_test(is_registrar)
def reject_application(request, pk):
    if request.method != "POST":
        return redirect("registrar_dashboard")

    app = get_object_or_404(Application, pk=pk)
    if not can_access_application_record(request.user, app):
        raise Http404("Application not found")

    reject_nursing_application(app, actor=request.user, request=request, reason=request.POST.get("reason", "Rejected by registrar"))
    send_application_status_email(app)
    messages.success(request, "Application rejected.")
    return redirect('application_detail', pk=app.pk)


@login_required
@user_passes_test(is_registrar)
@require_POST
def generate_application_checklist_view(request, pk):
    app = get_object_or_404(Application, pk=pk)
    if not can_access_application_record(request.user, app):
        raise Http404("Application not found")
    items = generate_application_checklist(app)
    messages.success(request, f"Generated or refreshed {len(items)} checklist items.")
    return redirect("application_detail", pk=app.pk)


@login_required
@user_passes_test(is_registrar)
@require_POST
def review_application_checklist_item(request, pk, item_id):
    app = get_object_or_404(Application, pk=pk)
    if not can_access_application_record(request.user, app):
        raise Http404("Application not found")
    item = get_object_or_404(ApplicationChecklistItem, pk=item_id, application=app)
    status = request.POST.get("status", "accepted")
    if status not in {"accepted", "rejected", "waived", "verification_pending"}:
        messages.error(request, "Invalid checklist status.")
        return redirect("application_detail", pk=app.pk)
    review_checklist_item(
        item,
        status=status,
        actor=request.user,
        request=request,
        rejection_reason=request.POST.get("rejection_reason", ""),
    )
    messages.success(request, f"Checklist item marked as {status.replace('_', ' ')}.")
    return redirect("application_detail", pk=app.pk)


@login_required
@user_passes_test(is_registrar)
@require_POST
def verify_application_payment_view(request, pk):
    app = get_object_or_404(Application, pk=pk)
    if not can_access_application_record(request.user, app):
        raise Http404("Application not found")
    updated = verify_application_payment(app, actor=request.user, request=request)
    if updated:
        messages.success(request, f"Verified {updated} receipt record(s).")
    else:
        messages.info(request, "No pending receipt records were found for this application.")
    return redirect("application_detail", pk=app.pk)


@login_required
@user_passes_test(is_registrar)
@require_POST
def create_supervisor_assignment_view(request, pk):
    app = get_object_or_404(Application, pk=pk)
    if not can_access_application_record(request.user, app):
        raise Http404("Application not found")
    supervisor_name = request.POST.get("supervisor_name", "").strip()
    if not supervisor_name:
        messages.error(request, "Supervisor name is required.")
        return redirect("application_detail", pk=app.pk)
    create_supervisor_assignment(
        application=app,
        supervisor_name=supervisor_name,
        supervisor_registration_number=request.POST.get("supervisor_registration_number", ""),
        employer_name=request.POST.get("employer_name", ""),
        actor=request.user,
        request=request,
    )
    messages.success(request, "Supervisor assignment created.")
    return redirect("application_detail", pk=app.pk)


@login_required
@user_passes_test(is_registrar)
@require_POST
def complete_supervisor_assignment_view(request, assignment_id):
    assignment = get_object_or_404(SupervisorAssignment, pk=assignment_id)
    if not can_access_application_record(request.user, assignment.application):
        raise Http404("Supervisor assignment not found")
    complete_supervisor_competency(
        assignment=assignment,
        actor=request.user,
        result=request.POST.get("result", "competent"),
        comments=request.POST.get("comments", ""),
        request=request,
    )
    messages.success(request, "Supervisor competency assessment completed.")
    return redirect("application_detail", pk=assignment.application.pk)


def public_nursing_register_search(request):
    rows = search_public_nursing_register(
        query=request.GET.get("name", "") or request.GET.get("q", ""),
        registration_number=request.GET.get("registration_number", ""),
        practitioner_number=request.GET.get("practitioner_number", ""),
        professional_category=request.GET.get("professional_category", ""),
        licence_status=request.GET.get("licence_status", ""),
    )
    return JsonResponse({"count": len(rows), "results": rows})


@login_required
@user_passes_test(is_registrar)
def nursing_workflow_tools(request):
    employer_result = None
    deceased_result = None
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "employer_verify":
            employer_result = create_employer_verification_request(
                actor=request.user,
                registration_number=request.POST.get("registration_number", ""),
                practitioner_number=request.POST.get("practitioner_number", ""),
                employer_name=request.POST.get("employer_name", ""),
                facility_name=request.POST.get("facility_name", ""),
                comments=request.POST.get("comments", ""),
                request=request,
            )
            messages.success(request, "Employer verification request recorded.")
        elif action == "deceased_notice":
            date_value = request.POST.get("date_of_death")
            try:
                date_of_death = date.fromisoformat(date_value)
            except (TypeError, ValueError):
                messages.error(request, "A valid date of death is required.")
                return redirect("nursing_workflow_tools")
            deceased_result = create_deceased_notification(
                actor=request.user,
                name_at_report=request.POST.get("name_at_report", ""),
                date_of_death=date_of_death,
                registration_number=request.POST.get("registration_number", ""),
                practitioner_number=request.POST.get("practitioner_number", ""),
                workforce_category=request.POST.get("workforce_category", ""),
                facility_name=request.POST.get("facility_name", ""),
                comments=request.POST.get("comments", ""),
                request=request,
            )
            messages.success(request, "Deceased notification recorded for registrar approval.")

    return render(request, "workforce/nursing_workflow_tools.html", {
        "employer_result": employer_result,
        "deceased_result": deceased_result,
        "recent_employer_requests": EmployerVerificationRequest.objects.order_by("-created_at")[:10],
        "recent_deceased_notifications": DeceasedNotification.objects.order_by("-created_at")[:10],
    })


@login_required
@user_passes_test(is_registrar)
@require_POST
def approve_deceased_notification_view(request, pk):
    notification = get_object_or_404(DeceasedNotification, pk=pk)
    approve_deceased_notification(notification, actor=request.user, request=request)
    messages.success(request, "Deceased notification approved and practitioner removed from active workforce counts.")
    return redirect("nursing_workflow_tools")
