import json
from pathlib import Path

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.core.management import BaseCommand, CommandError, call_command
from django.db import transaction
from django.db.models import Q
from django.utils import timezone


NURSING_TARGET_MODELS = {"nursingprofessional", "midwife", "nurseaide", "healthstudent"}
NURSING_FORM_PREFIXES = ("NC", "G")
NURSING_IMPORT_FILE_MARKERS = ("ATP", "N-DATA", "Nursing")
REPORT_DIR = Path("docs") / "reports"
BACKUP_DIR = Path("backups") / "nursing_council_reset"


def get_optional_model(label):
    try:
        return apps.get_model(label)
    except LookupError:
        return None


class Command(BaseCommand):
    help = (
        "Dry-run or apply a scoped reset of Nursing Council registry data while "
        "leaving Medical Board records and platform configuration in place."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply the destructive reset. Without this flag the command only reports counts.",
        )
        parser.add_argument(
            "--yes-i-understand",
            action="store_true",
            help="Required with --apply to confirm Nursing Council records will be deleted.",
        )
        parser.add_argument(
            "--skip-backup",
            action="store_true",
            help="Do not create a JSON model backup before applying the reset.",
        )
        parser.add_argument(
            "--include-training-institutions",
            action="store_true",
            help="Also remove Nursing Council training-institution records. Disabled by default.",
        )

    def handle(self, *args, **options):
        apply_reset = options["apply"]
        if apply_reset and not options["yes_i_understand"]:
            raise CommandError("Use --yes-i-understand with --apply to confirm this destructive reset.")

        timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
        context = self._build_context(options)
        counts = self._count_context(context)
        report_path = self._write_report(timestamp, apply_reset, counts, context)
        backup_path = None

        if apply_reset and not options["skip_backup"]:
            backup_path = self._write_backup(timestamp)

        deleted = {}
        unlinked_users = 0
        if apply_reset:
            with transaction.atomic():
                unlinked_users = self._unlink_users(context)
                deleted = self._delete_context(context)

        summary = {
            "mode": "apply" if apply_reset else "dry_run",
            "report_path": str(report_path),
            "backup_path": str(backup_path) if backup_path else "",
            "counts": counts,
            "deleted": deleted,
            "unlinked_users": unlinked_users,
        }
        json_path = report_path.with_suffix(".json")
        json_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

        if apply_reset:
            self.stdout.write(self.style.WARNING("Nursing Council registry reset applied."))
            self.stdout.write(f"Unlinked user accounts: {unlinked_users}")
            for label, value in deleted.items():
                self.stdout.write(f"Deleted {label}: {value}")
        else:
            self.stdout.write(self.style.WARNING("Dry-run only. No database rows were deleted."))
            for label, value in counts.items():
                self.stdout.write(f"{label}: {value}")
        self.stdout.write(f"Report written: {report_path}")
        if backup_path:
            self.stdout.write(f"Backup written: {backup_path}")

    def _build_context(self, options):
        workforce_models = {
            "NursingProfessional": apps.get_model("workforce", "NursingProfessional"),
            "Midwife": apps.get_model("workforce", "Midwife"),
            "NurseAide": apps.get_model("workforce", "NurseAide"),
            "HealthStudent": apps.get_model("workforce", "HealthStudent"),
        }
        content_types = {
            name: ContentType.objects.get_for_model(model)
            for name, model in workforce_models.items()
        }
        professional_ids = {
            name: list(model.objects.values_list("pk", flat=True))
            for name, model in workforce_models.items()
        }
        professional_ct_ids = [ct.pk for ct in content_types.values()]
        application_ct = ContentType.objects.get_for_model(apps.get_model("workforce", "Application"))

        Application = apps.get_model("workforce", "Application")
        application_q = Q(content_type_id__in=professional_ct_ids)
        for prefix in NURSING_FORM_PREFIXES:
            application_q |= Q(form_code__istartswith=prefix)
        applications = Application.objects.filter(application_q).distinct()
        application_ids = list(applications.values_list("pk", flat=True))

        DataImportBatch = apps.get_model("workforce", "DataImportBatch")
        nursing_import_q = Q(source_kind="nursing_license_workbook")
        for marker in NURSING_IMPORT_FILE_MARKERS:
            nursing_import_q |= Q(source_kind="ndata_workbook", source_file_name__icontains=marker)
        nursing_import_q |= Q(source_kind="ndata_workbook", source_file_name__istartswith="tmp")
        import_batches = DataImportBatch.objects.filter(nursing_import_q).exclude(
            source_file_name__icontains="Medical"
        ).exclude(
            source_file_name__icontains="CHW"
        ).distinct()
        import_batch_ids = list(import_batches.values_list("pk", flat=True))

        ImportedWorkbookSheet = apps.get_model("workforce", "ImportedWorkbookSheet")
        imported_sheets = ImportedWorkbookSheet.objects.filter(batch_id__in=import_batch_ids)

        PracticingLicenseRecord = apps.get_model("workforce", "PracticingLicenseRecord")
        practicing_records = PracticingLicenseRecord.objects.filter(
            Q(target_model__in=NURSING_TARGET_MODELS) | Q(batch_id__in=import_batch_ids)
        ).distinct()
        receipt_references = set(
            value
            for value in practicing_records.values_list("reference_number", flat=True)
            if value
        )

        Document = get_optional_model("documents.Document")
        document_q = Q()
        if Document:
            document_q |= Q(office_scope="nursing")
            document_q |= self._related_object_q(content_types, professional_ids)
            if application_ids:
                document_q |= Q(related_content_type=application_ct, related_object_id__in=application_ids)
            documents = Document.objects.filter(document_q).distinct()
        else:
            documents = None

        EnquiryThread = get_optional_model("notifications.EnquiryThread")
        if EnquiryThread:
            enquiry_q = Q(office="nursing") | self._recipient_object_q(content_types, professional_ids)
            enquiries = EnquiryThread.objects.filter(enquiry_q).distinct()
        else:
            enquiries = None

        TrainingInstitution = apps.get_model("workforce", "TrainingInstitution")
        training_institutions = TrainingInstitution.objects.none()
        if options["include_training_institutions"]:
            training_institutions = TrainingInstitution.objects.filter(
                Q(regulatory_body_name__icontains="nursing")
                | Q(type__icontains="nursing")
                | Q(type__icontains="midwif")
                | Q(name__icontains="nursing")
                | Q(name__icontains="midwif")
            )

        return {
            "content_types": content_types,
            "professional_ids": professional_ids,
            "professional_ct_ids": professional_ct_ids,
            "applications": applications,
            "application_ids": application_ids,
            "import_batches": import_batches,
            "import_batch_ids": import_batch_ids,
            "imported_sheets": imported_sheets,
            "practicing_records": practicing_records,
            "receipt_references": receipt_references,
            "documents": documents,
            "enquiries": enquiries,
            "training_institutions": training_institutions,
        }

    def _related_object_q(self, content_types, professional_ids):
        query = Q(pk__in=[])
        for name, ct in content_types.items():
            ids = professional_ids.get(name) or []
            if ids:
                query |= Q(related_content_type=ct, related_object_id__in=ids)
        return query

    def _recipient_object_q(self, content_types, professional_ids):
        query = Q(pk__in=[])
        for name, ct in content_types.items():
            ids = professional_ids.get(name) or []
            if ids:
                query |= Q(recipient_content_type=ct, recipient_object_id__in=ids)
        return query

    def _generic_queryset(self, label, context):
        model = get_optional_model(label)
        if not model:
            return None
        if not hasattr(model, "content_type") or not hasattr(model, "object_id"):
            return None
        return model.objects.filter(content_type_id__in=context["professional_ct_ids"])

    def _count_context(self, context):
        counts = {}
        for name, ids in context["professional_ids"].items():
            counts[name] = len(ids)
        counts["Applications"] = context["applications"].count()
        counts["DataImportBatch"] = context["import_batches"].count()
        counts["ImportedWorkbookSheet"] = context["imported_sheets"].count()
        counts["PracticingLicenseRecord"] = context["practicing_records"].count()

        Receipt = get_optional_model("dashboard.Receipt")
        if Receipt:
            counts["Receipt"] = Receipt.objects.filter(
                Q(application_id__in=context["application_ids"])
                | Q(official_receipt_no__in=context["receipt_references"])
                | Q(receipt_number__in=context["receipt_references"])
            ).distinct().count()

        if context["documents"] is not None:
            counts["RepositoryDocument"] = context["documents"].count()
        if context["enquiries"] is not None:
            counts["EnquiryThread"] = context["enquiries"].count()

        for label in [
            "workforce.Qualification",
            "workforce.ProfessionalDocument",
            "workforce.PostingHistory",
            "workforce.CPDRecord",
            "workforce.ProfessionalPhoto",
            "workforce.EmploymentRecord",
            "workforce.EmployerVerificationRequest",
            "workforce.SupervisorAssignment",
            "workforce.DeceasedNotification",
            "workforce.MissingDataReview",
            "common.DuplicateReviewQueue",
            "common.DeceasedRecord",
        ]:
            qs = self._generic_queryset(label, context)
            if qs is not None:
                counts[label] = qs.count()

        MobileSubmission = get_optional_model("mobile_intake.MobileSubmission")
        if MobileSubmission:
            counts["mobile_intake.MobileSubmission"] = MobileSubmission.objects.filter(office_scope="nursing").count()
        MobileLocalAccountRequest = get_optional_model("mobile_intake.MobileLocalAccountRequest")
        if MobileLocalAccountRequest:
            counts["mobile_intake.MobileLocalAccountRequest"] = MobileLocalAccountRequest.objects.filter(office_scope="nursing").count()
        NHWACellEntry = get_optional_model("nhwa_workbooks.NHWACellEntry")
        if NHWACellEntry:
            counts["nhwa_workbooks.NHWACellEntry"] = NHWACellEntry.objects.filter(
                template__sheet__workbook__office_scope="nursing"
            ).count()
        counts["TrainingInstitution"] = context["training_institutions"].count()
        counts["UserLinksToUnlink"] = self._user_links_queryset(context).count()
        return counts

    def _write_report(self, timestamp, apply_reset, counts, context):
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        report_path = REPORT_DIR / f"nursing_council_data_reset_{timestamp}.md"
        lines = [
            "# Nursing Council Data Reset Inventory",
            "",
            f"Generated at: {timezone.now().isoformat()}",
            f"Mode: {'apply' if apply_reset else 'dry_run'}",
            "",
            "## Scope",
            "",
            "- Deletes Nursing Council professional registry data only.",
            "- Leaves Medical Board professional records and platform configuration in place.",
            "- Keeps Nursing Council form/workflow definitions so clean data can be re-imported.",
            "- Removes Nursing/ATP import-batch metadata so the next Nursing Council import starts clean.",
            "- User accounts are not deleted; links to deleted Nursing Council professional records are cleared.",
            "",
            "## Counts",
            "",
            "| Target | Rows |",
            "|---|---:|",
        ]
        for label, value in sorted(counts.items()):
            lines.append(f"| {label} | {value} |")
        lines.extend([
            "",
            "## Receipt Matching",
            "",
            f"Nursing receipt references collected from licence rows: {len(context['receipt_references'])}",
            "",
        ])
        report_path.write_text("\n".join(lines), encoding="utf-8")
        return report_path

    def _write_backup(self, timestamp):
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        backup_path = BACKUP_DIR / f"nursing_council_pre_reset_{timestamp}.json"
        model_labels = [
            "workforce.NursingProfessional",
            "workforce.Midwife",
            "workforce.NurseAide",
            "workforce.HealthStudent",
            "workforce.Qualification",
            "workforce.ProfessionalDocument",
            "workforce.PostingHistory",
            "workforce.CPDRecord",
            "workforce.Application",
            "workforce.ApplicationFormResponse",
            "workforce.ApplicationChecklistItem",
            "workforce.ApplicationStatusHistory",
            "workforce.ApplicantDeclaration",
            "workforce.EmployerVerificationRequest",
            "workforce.SupervisorAssignment",
            "workforce.DeceasedNotification",
            "workforce.ProfessionalPhoto",
            "workforce.EmploymentRecord",
            "workforce.DataImportBatch",
            "workforce.ImportedWorkbookSheet",
            "workforce.PracticingLicenseRecord",
            "workforce.IssuedLicenceDocument",
            "workforce.MissingDataReview",
            "dashboard.Receipt",
            "common.DuplicateReviewQueue",
            "common.DeceasedRecord",
            "documents.Document",
            "documents.DocumentVersion",
            "notifications.EnquiryThread",
            "notifications.EnquiryMessage",
            "notifications.EnquiryMessageAttachment",
            "notifications.EnquiryMailboxState",
            "mobile_intake.MobileSubmission",
            "mobile_intake.MobileSubmissionAttachment",
            "mobile_intake.MobileSyncEvent",
            "mobile_intake.MobileSubmissionStatusHistory",
            "mobile_intake.MobilePromotionLink",
            "nhwa_workbooks.NHWACellEntry",
            "nhwa_workbooks.NHWAWorkbookAuditEvent",
        ]
        existing_labels = []
        for label in model_labels:
            if get_optional_model(label):
                existing_labels.append(label)
        call_command("dumpdata", *existing_labels, indent=2, output=str(backup_path))
        return backup_path

    def _user_links_queryset(self, context):
        User = apps.get_model("accounts", "User")
        return User.objects.filter(professional_content_type_id__in=context["professional_ct_ids"])

    def _unlink_users(self, context):
        return self._user_links_queryset(context).update(
            professional_content_type=None,
            professional_object_id=None,
            professional_record_status="unmatched",
            professional_linked_at=None,
            professional_link_review_note="Nursing Council registry data reset for clean re-import.",
        )

    def _delete_queryset(self, deleted, label, queryset):
        if queryset is None:
            return
        count, details = queryset.delete()
        deleted[label] = count
        for detail_label, detail_count in details.items():
            deleted[f"  {detail_label}"] = detail_count

    def _delete_context(self, context):
        deleted = {}

        Receipt = get_optional_model("dashboard.Receipt")
        if Receipt:
            receipt_qs = Receipt.objects.filter(
                Q(application_id__in=context["application_ids"])
                | Q(official_receipt_no__in=context["receipt_references"])
                | Q(receipt_number__in=context["receipt_references"])
            ).distinct()
            self._delete_queryset(deleted, "Receipt", receipt_qs)

        self._delete_queryset(deleted, "RepositoryDocument", context["documents"])
        self._delete_queryset(deleted, "EnquiryThread", context["enquiries"])

        MobileSubmission = get_optional_model("mobile_intake.MobileSubmission")
        if MobileSubmission:
            self._delete_queryset(
                deleted,
                "mobile_intake.MobileSubmission",
                MobileSubmission.objects.filter(office_scope="nursing"),
            )
        MobileLocalAccountRequest = get_optional_model("mobile_intake.MobileLocalAccountRequest")
        if MobileLocalAccountRequest:
            self._delete_queryset(
                deleted,
                "mobile_intake.MobileLocalAccountRequest",
                MobileLocalAccountRequest.objects.filter(office_scope="nursing"),
            )

        NHWAWorkbookAuditEvent = get_optional_model("nhwa_workbooks.NHWAWorkbookAuditEvent")
        if NHWAWorkbookAuditEvent:
            self._delete_queryset(
                deleted,
                "nhwa_workbooks.NHWAWorkbookAuditEvent",
                NHWAWorkbookAuditEvent.objects.filter(workbook__office_scope="nursing"),
            )
        NHWACellEntry = get_optional_model("nhwa_workbooks.NHWACellEntry")
        if NHWACellEntry:
            self._delete_queryset(
                deleted,
                "nhwa_workbooks.NHWACellEntry",
                NHWACellEntry.objects.filter(template__sheet__workbook__office_scope="nursing"),
            )

        for label in [
            "common.DuplicateReviewQueue",
            "common.DeceasedRecord",
            "workforce.MissingDataReview",
            "workforce.Qualification",
            "workforce.ProfessionalDocument",
            "workforce.PostingHistory",
            "workforce.CPDRecord",
            "workforce.ProfessionalPhoto",
            "workforce.EmploymentRecord",
            "workforce.EmployerVerificationRequest",
            "workforce.SupervisorAssignment",
            "workforce.DeceasedNotification",
        ]:
            qs = self._generic_queryset(label, context)
            self._delete_queryset(deleted, label, qs)

        self._delete_queryset(deleted, "workforce.Application", context["applications"])
        self._delete_queryset(deleted, "workforce.PracticingLicenseRecord", context["practicing_records"])
        self._delete_queryset(deleted, "workforce.ImportedWorkbookSheet", context["imported_sheets"])
        self._delete_queryset(deleted, "workforce.DataImportBatch", context["import_batches"])
        self._delete_queryset(deleted, "workforce.TrainingInstitution", context["training_institutions"])

        for name, model in [
            ("workforce.NursingProfessional", apps.get_model("workforce", "NursingProfessional")),
            ("workforce.Midwife", apps.get_model("workforce", "Midwife")),
            ("workforce.NurseAide", apps.get_model("workforce", "NurseAide")),
            ("workforce.HealthStudent", apps.get_model("workforce", "HealthStudent")),
        ]:
            self._delete_queryset(deleted, name, model.objects.all())

        return deleted
