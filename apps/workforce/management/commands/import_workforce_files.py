from pathlib import Path

import pandas as pd
from django.core.management.base import BaseCommand, CommandError
from django.contrib.contenttypes.models import ContentType

from apps.accounts.models import User
from apps.common.models import DeceasedRecord, DuplicateReviewQueue
from apps.competency.models import CPDRecord, CompetencyAssessment
from apps.dashboard.models import Report
from apps.notifications.models import Notification
from apps.ocr.models import OCRDocument
from apps.workforce.models import (
    Application,
    Cadre,
    CommunityHealthWorker,
    DocumentType,
    Facility,
    HealthStudent,
    Location,
    MedicalDoctor,
    Midwife,
    NursingProfessional,
    TrainingInstitution,
    WorkforceSnapshot,
)


class Command(BaseCommand):
    help = "Bulk import multiple CSV/Excel files by model name from a folder."

    def add_arguments(self, parser):
        parser.add_argument("--path", required=True, help="Folder containing import files.")

    def handle(self, *args, **options):
        base_path = Path(options["path"])
        if not base_path.exists():
            raise CommandError(f"Path does not exist: {base_path}")

        files = [p for p in base_path.iterdir() if p.suffix.lower() in [".csv", ".xls", ".xlsx"]]
        if not files:
            self.stdout.write(self.style.WARNING("No CSV/Excel files found."))
            return

        for file_path in files:
            model_key = file_path.stem.lower()
            try:
                df = pd.read_csv(file_path) if file_path.suffix.lower() == ".csv" else pd.read_excel(file_path)
                self._import_file(model_key, df)
                self.stdout.write(self.style.SUCCESS(f"Imported: {file_path.name}"))
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"Failed {file_path.name}: {exc}"))

    def _import_file(self, model_key, dataframe):
        handlers = {
            "cadre": self._import_cadre,
            "location": self._import_location,
            "traininginstitution": self._import_training_institution,
            "documenttype": self._import_document_type,
            "facility": self._import_facility,
            "medicaldoctor": self._import_medical_doctor,
            "nursingprofessional": self._import_nursing_professional,
            "midwife": self._import_midwife,
            "communityhealthworker": self._import_chw,
            "healthstudent": self._import_health_student,
            "application": self._import_application,
            "workforcesnapshot": self._import_workforce_snapshot,
            "user": self._import_user,
            "duplicatereviewqueue": self._import_duplicate_review_queue,
            "deceasedrecord": self._import_deceased_record,
            "notification": self._import_notification,
            "report": self._import_report,
            "ocrdocument": self._import_ocr_document,
            "cpdrecord": self._import_cpd_record,
            "competencyassessment": self._import_competency_assessment,
        }
        handler = handlers.get(model_key)
        if not handler:
            raise CommandError(f"Unsupported file/model key: {model_key}")
        handler(dataframe.fillna(""))

    def _import_cadre(self, df):
        for _, row in df.iterrows():
            Cadre.objects.get_or_create(name=row.get("name"), defaults={"description": row.get("description", "")})

    def _import_location(self, df):
        for _, row in df.iterrows():
            Location.objects.get_or_create(
                province=row.get("province"),
                district=row.get("district"),
                defaults={"ward": row.get("ward", "")},
            )

    def _import_training_institution(self, df):
        for _, row in df.iterrows():
            TrainingInstitution.objects.update_or_create(
                name=row.get("name"),
                defaults={
                    "type": row.get("type", "Nursing/Health"),
                    "accreditation_status": row.get("accreditation_status", "accredited"),
                },
            )

    def _import_document_type(self, df):
        for _, row in df.iterrows():
            DocumentType.objects.update_or_create(
                name=row.get("name"),
                defaults={"description": row.get("description", ""), "is_required": bool(row.get("is_required"))},
            )

    def _import_facility(self, df):
        for _, row in df.iterrows():
            location = None
            if row.get("province") and row.get("district"):
                location, _ = Location.objects.get_or_create(province=row.get("province"), district=row.get("district"))
            Facility.objects.update_or_create(
                code=row.get("code"),
                defaults={
                    "name": row.get("name"),
                    "type": row.get("type", "General"),
                    "ownership": row.get("ownership", "public"),
                    "level": row.get("level", "district"),
                    "location": location,
                },
            )

    def _upsert_professional(self, model, row):
        cadre = None
        if row.get("cadre"):
            cadre, _ = Cadre.objects.get_or_create(name=row.get("cadre"))
        model.objects.update_or_create(
            registration_no=row.get("registration_no") or row.get("national_id"),
            defaults={
                "first_name": row.get("first_name"),
                "last_name": row.get("last_name"),
                "date_of_birth": row.get("date_of_birth") or None,
                "gender": row.get("gender", ""),
                "primary_phone": row.get("primary_phone", ""),
                "email": row.get("email", ""),
                "registration_number": row.get("registration_number", ""),
                "license_expiry_date": row.get("license_expiry_date") or row.get("license_expiry") or None,
                "qualification_level": row.get("qualification_level", ""),
                "cadre": cadre,
                "is_active": bool(row.get("is_active", True)),
            },
        )

    def _import_medical_doctor(self, df):
        for _, row in df.iterrows():
            cadre = None
            if row.get("cadre"):
                cadre, _ = Cadre.objects.get_or_create(name=row.get("cadre"))
            MedicalDoctor.objects.update_or_create(
                registration_no=row.get("registration_no") or row.get("national_id"),
                defaults={
                    "first_name": row.get("first_name"),
                    "last_name": row.get("last_name"),
                    "date_of_birth": row.get("date_of_birth") or None,
                    "gender": row.get("gender", ""),
                    "primary_phone": row.get("primary_phone", ""),
                    "email": row.get("email", ""),
                    "registration_number": row.get("registration_number", ""),
                    "license_expiry_date": row.get("license_expiry_date") or None,
                    "cadre": cadre,
                    "is_active": bool(row.get("is_active", True)),
                },
            )

    def _import_nursing_professional(self, df):
        for _, row in df.iterrows():
            self._upsert_professional(NursingProfessional, row)

    def _import_midwife(self, df):
        for _, row in df.iterrows():
            self._upsert_professional(Midwife, row)

    def _import_chw(self, df):
        for _, row in df.iterrows():
            CommunityHealthWorker.objects.update_or_create(
                registration_no=row.get("registration_no") or row.get("national_id"),
                defaults={
                    "first_name": row.get("first_name"),
                    "last_name": row.get("last_name"),
                    "date_of_birth": row.get("date_of_birth") or None,
                    "gender": row.get("gender", ""),
                    "primary_phone": row.get("primary_phone", ""),
                    "email": row.get("email", ""),
                    "community_id": row.get("community_id", ""),
                    "training_level": row.get("training_level", ""),
                    "is_active": bool(row.get("is_active", True)),
                },
            )

    def _import_health_student(self, df):
        for _, row in df.iterrows():
            institution = None
            if row.get("institution"):
                institution, _ = TrainingInstitution.objects.get_or_create(name=row.get("institution"))
            HealthStudent.objects.update_or_create(
                registration_no=row.get("registration_no") or row.get("national_id"),
                defaults={
                    "first_name": row.get("first_name"),
                    "last_name": row.get("last_name"),
                    "program": row.get("program", ""),
                    "institution": institution,
                    "expected_graduation_date": row.get("expected_graduation_date") or None,
                    "is_graduate": bool(row.get("is_graduate")),
                    "graduate_checklist_completed": bool(row.get("graduate_checklist_completed")),
                    "competency_statement_submitted": bool(row.get("competency_statement_submitted")),
                },
            )

    def _import_application(self, df):
        for _, row in df.iterrows():
            Application.objects.create(
                form_code=row.get("form_code", "OTHER"),
                status=row.get("status", "pending"),
                reviewer_notes=row.get("reviewer_notes", ""),
                object_id=int(row.get("object_id", 1)),
                content_type_id=int(row.get("content_type_id", 1)),
            )

    def _import_workforce_snapshot(self, df):
        for _, row in df.iterrows():
            WorkforceSnapshot.objects.update_or_create(
                year=int(row.get("year")),
                defaults={
                    "total_active_workers": int(row.get("total_active_workers", 0)),
                    "total_nurses": int(row.get("total_nurses", 0)),
                    "total_doctors": int(row.get("total_doctors", 0)),
                    "total_midwives": int(row.get("total_midwives", 0)),
                    "total_chw": int(row.get("total_chw", 0)),
                    "new_registrations": int(row.get("new_registrations", 0)),
                    "renewals": int(row.get("renewals", 0)),
                    "retirements": int(row.get("retirements", 0)),
                    "new_graduates_joined": int(row.get("new_graduates_joined", 0)),
                    "nearing_retirement": int(row.get("nearing_retirement", 0)),
                },
            )

    def _import_user(self, df):
        for _, row in df.iterrows():
            user, created = User.objects.update_or_create(
                username=row.get("username"),
                defaults={
                    "email": row.get("email", ""),
                    "first_name": row.get("first_name", ""),
                    "last_name": row.get("last_name", ""),
                    "role": row.get("role", "viewer"),
                    "phone": row.get("phone", ""),
                    "department": row.get("department", ""),
                    "is_active": bool(row.get("is_active", True)),
                    "is_staff": bool(row.get("is_staff", False)),
                },
            )
            if created and not user.password:
                # Imported accounts should be activated intentionally through the
                # normal onboarding/reset flow, not with a predictable password.
                user.set_unusable_password()
                user.save(update_fields=["password"])

    def _import_duplicate_review_queue(self, df):
        for _, row in df.iterrows():
            DuplicateReviewQueue.objects.create(
                content_type_id=int(row.get("content_type_id", 1)),
                object_id=int(row.get("object_id", 1)),
                suspected_duplicate=row.get("suspected_duplicate", {}),
                similarity_score=float(row.get("similarity_score", 0)),
                status=row.get("status", "pending"),
            )

    def _import_deceased_record(self, df):
        for _, row in df.iterrows():
            DeceasedRecord.objects.create(
                content_type_id=int(row.get("content_type_id", 1)),
                object_id=int(row.get("object_id", 1)),
                date_of_death=row.get("date_of_death"),
                status=row.get("status", "pending"),
            )

    def _import_notification(self, df):
        for _, row in df.iterrows():
            Notification.objects.create(
                user_id=int(row.get("user_id", 1)),
                subject=row.get("subject", ""),
                message=row.get("message", ""),
                sent=bool(row.get("sent", False)),
            )

    def _import_report(self, df):
        for _, row in df.iterrows():
            Report.objects.create(
                title=row.get("title", ""),
                report_type=row.get("report_type", "workforce_summary"),
                generated_by_id=int(row.get("generated_by_id", 1)),
            )

    def _import_ocr_document(self, df):
        for _, row in df.iterrows():
            OCRDocument.objects.create(file=row.get("file", ""), extracted_text=row.get("extracted_text", ""))

    def _import_cpd_record(self, df):
        for _, row in df.iterrows():
            CPDRecord.objects.create(
                content_type_id=int(row.get("content_type_id", 1)),
                object_id=int(row.get("object_id", 1)),
                training_type=row.get("training_type", ""),
                start_date=row.get("start_date"),
                hours_credits=float(row.get("hours_credits", 0)),
            )

    def _import_competency_assessment(self, df):
        for _, row in df.iterrows():
            CompetencyAssessment.objects.create(
                content_type_id=int(row.get("content_type_id", 1)),
                object_id=int(row.get("object_id", 1)),
                assessment_type=row.get("assessment_type", ""),
                assessment_date=row.get("assessment_date"),
                supervisor_name=row.get("supervisor_name", ""),
                overall_recommendation=row.get("overall_recommendation", "competent"),
                checklist_completed=bool(row.get("checklist_completed", False)),
            )
