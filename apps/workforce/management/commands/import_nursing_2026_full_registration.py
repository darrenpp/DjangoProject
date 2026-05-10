from datetime import timedelta
from pathlib import Path
import re

import pandas as pd
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.common.models import DuplicateReviewQueue
from apps.workforce.models import (
    Application,
    Cadre,
    DataImportBatch,
    ImportedWorkbookSheet,
    Midwife,
    NursingProfessional,
    PracticingLicenseRecord,
    Qualification,
    TrainingInstitution,
)
from apps.workforce.services.data_quality import audit_imported_license_rows, audit_professional_profiles
from notebooks.cleanse_full_registrations import (
    infer_applicant_type,
    infer_pathway,
    infer_profession_track,
    normalize_name,
    normalize_registration_no,
    normalize_text,
    parse_issued_date,
    split_name,
)


DEFAULT_WORKBOOK = Path(r"d:\YEAR 2026 FULL REGISTRATION RECORD.(1).xlsx")
MASTER_SHEET = "FULL REGO 2009 - current2026 "
SCREENING_SHEETS = ["Jan- 2026", "Feb -Mar 2026 ", "April 2026", "Feb - 2026  (2)"]


def clean_number(value):
    text = normalize_text(value)
    if text.endswith(".0"):
        text = text[:-2]
    return text


def normalize_phone(value):
    text = normalize_text(value)
    return text.replace(" ", "")[:20]


def normalize_gender(value):
    text = normalize_text(value).title()
    if text.startswith("M"):
        return "Male"
    if text.startswith("F"):
        return "Female"
    return ""


def parse_date(value):
    parsed, _status = parse_issued_date(value)
    if pd.isna(parsed):
        return None
    return parsed.date() if hasattr(parsed, "date") else parsed


def extract_meeting_date(raw_frame):
    for _, row in raw_frame.head(10).iterrows():
        text = " ".join(normalize_text(value) for value in row.tolist())
        match = re.search(r"Date\s*:\s*(.+?)(?:Venue|$)", text, flags=re.IGNORECASE)
        if match:
            parsed = pd.to_datetime(match.group(1).replace("th", "").replace("st", "").replace("nd", "").replace("rd", ""), errors="coerce", dayfirst=True)
            if not pd.isna(parsed):
                return parsed.date()
    return None


def professional_name(obj):
    return normalize_text(f"{obj.first_name} {obj.last_name}").upper()


class Command(BaseCommand):
    help = "Import the 2026 Nursing Council full-registration workbook and queue duplicate reviews."

    def add_arguments(self, parser):
        parser.add_argument("--file", type=str, default=str(DEFAULT_WORKBOOK), help="Path to the 2026 full-registration workbook.")
        parser.add_argument("--dry-run", action="store_true", help="Read, cleanse, and compare without saving.")

    def handle(self, *args, **options):
        workbook = Path(options["file"])
        dry_run = options["dry_run"]
        if not workbook.exists():
            raise CommandError(f"Workbook not found: {workbook}")

        xl = pd.ExcelFile(workbook)
        missing_sheets = [sheet for sheet in [MASTER_SHEET, *SCREENING_SHEETS] if sheet not in xl.sheet_names]
        if missing_sheets:
            raise CommandError(f"Workbook is missing expected sheet(s): {missing_sheets}")

        master_rows = self._read_master_rows(workbook)
        screening_rows = self._read_screening_rows(workbook)

        self.stdout.write(f"Master 2026 full-registration rows found: {len(master_rows)}")
        self.stdout.write(f"Screening/supporting rows found: {len(screening_rows)}")

        if dry_run:
            duplicate_preview = self._duplicate_preview(master_rows, screening_rows)
            self.stdout.write(self.style.WARNING("Dry run selected. No database records were changed."))
            self.stdout.write(f"Potential duplicate review rows: {duplicate_preview}")
            return

        with transaction.atomic():
            batch = DataImportBatch.objects.create(
                source_file_name=workbook.name,
                source_file_path=str(workbook),
                source_kind="nursing_full_registration_2026",
                status="running",
                total_sheets=1 + len(SCREENING_SHEETS),
            )
            summary = self._import_rows(batch, workbook, master_rows, screening_rows)
            batch.status = "completed"
            batch.completed_at = timezone.now()
            batch.summary = summary
            batch.processed_sheets = batch.sheets.filter(status="processed").count()
            batch.total_rows = summary["master_rows_seen"] + summary["screening_rows_seen"]
            batch.processed_rows = summary["practice_records_created"]
            batch.save(update_fields=["status", "completed_at", "summary", "processed_sheets", "total_rows", "processed_rows"])

        profile_audit = audit_professional_profiles(send_notifications=False)
        import_audit = audit_imported_license_rows(batch=batch)

        self.stdout.write(self.style.SUCCESS(f"Imported Nursing Council 2026 full-registration batch #{batch.id}"))
        for key, value in summary.items():
            self.stdout.write(f"{key}: {value}")
        self.stdout.write(f"Missing profile audit: {profile_audit}")
        self.stdout.write(f"Missing import-row audit: {import_audit}")

    def _read_master_rows(self, workbook):
        df = pd.read_excel(workbook, sheet_name=MASTER_SHEET, header=3)
        rows = []
        for index, row in df.iterrows():
            issued_date = parse_date(row.get("ISSUED DATE"))
            if not issued_date or issued_date.year != 2026:
                continue
            full_name = normalize_name(row.get("NAME"))
            if not full_name:
                continue
            p_code = clean_number(row.get("Unnamed: 4"))
            license_no = clean_number(row.get("NO."))
            registration_no = normalize_registration_no(p_code, license_no)
            if not registration_no:
                continue
            qualification = normalize_text(row.get("QUALIFICATION"))
            profession_track = infer_profession_track(qualification)
            rows.append({
                "source_sheet": MASTER_SHEET,
                "source_row": int(index) + 5,
                "full_name": full_name,
                "first_name": split_name(full_name)[0],
                "last_name": split_name(full_name)[1],
                "registration_no": registration_no,
                "p_code": p_code,
                "license_no": license_no,
                "issued_date": issued_date,
                "institution_name": normalize_text(row.get("INSTITUTION ATTENDED")),
                "graduation_year": self._safe_int(row.get("YEAR")),
                "qualification_name": qualification,
                "workplace_address": normalize_text(row.get("P/Number")),
                "applicant_type": infer_applicant_type(row.get("INSTITUTION ATTENDED")),
                "profession_track": profession_track,
                "target_model": "midwife" if profession_track == "midwifery" else "nursingprofessional",
                "pathway": infer_pathway(infer_applicant_type(row.get("INSTITUTION ATTENDED")), profession_track),
                "raw_payload": {str(k): self._json_value(v) for k, v in row.to_dict().items()},
            })
        return rows

    def _read_screening_rows(self, workbook):
        rows = []
        for sheet_name in SCREENING_SHEETS:
            raw = pd.read_excel(workbook, sheet_name=sheet_name, header=None)
            meeting_date = extract_meeting_date(raw)
            df = pd.read_excel(workbook, sheet_name=sheet_name, header=7)
            for index, row in df.iterrows():
                row_no = self._safe_int(row.get("NO"))
                full_name = normalize_name(row.get("APPLICANT'S FULL NAME"))
                if not row_no or not full_name:
                    continue
                if full_name.lower() in {"southern region", "highlands region", "momase region", "new guinea island region", "total"}:
                    continue
                qualification = normalize_text(row.get("Qualification"))
                profession_track = infer_profession_track(qualification)
                comment = normalize_text(row.get("COMMENT"))
                status = "approved"
                if "not recommended" in comment.lower() or "redo" in comment.lower():
                    status = "rejected"
                elif "pending" in comment.lower():
                    status = "pending"
                applicant_type = "overseas" if normalize_text(row.get("COUNTRY OF ORIGIN")).upper() not in {"", "PNG", "PAPUA NEW GUINEA"} else "national"
                rows.append({
                    "source_sheet": sheet_name,
                    "source_row": int(index) + 9,
                    "row_no": row_no,
                    "full_name": full_name,
                    "first_name": split_name(full_name)[0],
                    "last_name": split_name(full_name)[1],
                    "registration_no": "",
                    "practitioner_number": clean_number(row.get("Provisional Number")),
                    "issued_date": meeting_date,
                    "date_of_birth": parse_date(row.get("Date of Birth")),
                    "gender": normalize_gender(row.get("Gender")),
                    "phone": normalize_phone(row.get("Mobile No")),
                    "email": normalize_text(row.get("Email Address"))[:254],
                    "receipt_no": normalize_text(row.get("Recipt No:")),
                    "receipt_date": parse_date(row.get("RECIPT DATE")),
                    "institution_name": normalize_text(row.get("Name of School/institute")),
                    "graduation_year": self._safe_int(row.get("Year Graduate")),
                    "qualification_name": qualification,
                    "workplace_address": normalize_text(row.get("ORGANIZATION/EMPLOYMENT ADDRESS")) or normalize_text(row.get("Residential Address")),
                    "province": normalize_text(row.get("Home Province")),
                    "applicant_type": applicant_type,
                    "profession_track": profession_track,
                    "target_model": "midwife" if profession_track == "midwifery" else "nursingprofessional",
                    "pathway": infer_pathway(applicant_type, profession_track),
                    "application_status": status,
                    "comment": comment,
                    "raw_payload": {str(k): self._json_value(v) for k, v in row.to_dict().items()},
                })
        return rows

    def _import_rows(self, batch, workbook, master_rows, screening_rows):
        nursing_cadre, _ = Cadre.objects.get_or_create(name="Nursing", defaults={"category": "nursing"})
        midwifery_cadre, _ = Cadre.objects.get_or_create(name="Midwifery", defaults={"category": "midwifery"})
        nurse_ct = ContentType.objects.get_for_model(NursingProfessional)
        midwife_ct = ContentType.objects.get_for_model(Midwife)
        record_ct = ContentType.objects.get_for_model(PracticingLicenseRecord)
        sheet_cache = {}
        full_name_index = {}
        summary = {
            "master_rows_seen": len(master_rows),
            "screening_rows_seen": len(screening_rows),
            "practice_records_created": 0,
            "professionals_created": 0,
            "professionals_updated": 0,
            "applications_created": 0,
            "applications_updated": 0,
            "duplicate_reviews_created": 0,
            "duplicates_detected": 0,
        }

        for rows, sheet_type in [(master_rows, "full_registration_master"), (screening_rows, "full_registration_screening")]:
            by_sheet = {}
            for row in rows:
                by_sheet.setdefault(row["source_sheet"], []).append(row)
            for sheet_name, sheet_rows in by_sheet.items():
                sheet_cache[sheet_name] = ImportedWorkbookSheet.objects.create(
                    batch=batch,
                    sheet_name=sheet_name,
                    sheet_type=sheet_type,
                    status="processed",
                    raw_rows=len(sheet_rows),
                    imported_rows=len(sheet_rows),
                    metadata={"year": 2026},
                )

        for row in master_rows:
            model = Midwife if row["target_model"] == "midwife" else NursingProfessional
            content_type = midwife_ct if model is Midwife else nurse_ct
            cadre = midwifery_cadre if model is Midwife else nursing_cadre
            duplicate_matches = self._professional_duplicates(model, row)
            record = self._create_license_record(batch, sheet_cache[row["source_sheet"]], row, "full")
            summary["practice_records_created"] += 1
            if duplicate_matches:
                summary["duplicates_detected"] += len(duplicate_matches)
                summary["duplicate_reviews_created"] += self._queue_duplicate_reviews(record_ct, record, duplicate_matches, row)

            professional, created, updated = self._upsert_professional(model, content_type, cadre, row, allow_create=True)
            summary["professionals_created"] += int(created)
            summary["professionals_updated"] += int(updated)
            if professional:
                full_name_index.setdefault(normalize_text(row["full_name"]).upper(), professional)
                self._upsert_qualification(content_type, professional, row)
                app_created = self._upsert_application(content_type, professional, row, "approved", workbook.name)
                summary["applications_created"] += int(app_created)
                summary["applications_updated"] += int(not app_created)

        for row in screening_rows:
            row["registration_no"] = self._match_registration_from_master(row, master_rows)
            record = self._create_license_record(batch, sheet_cache[row["source_sheet"]], row, "full")
            summary["practice_records_created"] += 1
            matches = self._screening_duplicates(row, full_name_index)
            if matches:
                summary["duplicates_detected"] += len(matches)
                summary["duplicate_reviews_created"] += self._queue_duplicate_reviews(record_ct, record, matches, row)

            professional = None
            if row["registration_no"]:
                model = Midwife if row["target_model"] == "midwife" else NursingProfessional
                content_type = midwife_ct if model is Midwife else nurse_ct
                cadre = midwifery_cadre if model is Midwife else nursing_cadre
                professional, created, updated = self._upsert_professional(model, content_type, cadre, row, allow_create=False)
                summary["professionals_created"] += int(created)
                summary["professionals_updated"] += int(updated)
            if not professional:
                professional = full_name_index.get(normalize_text(row["full_name"]).upper())
                content_type = ContentType.objects.get_for_model(professional) if professional else None
            if professional and content_type:
                app_created = self._upsert_application(content_type, professional, row, row["application_status"], workbook.name)
                summary["applications_created"] += int(app_created)
                summary["applications_updated"] += int(not app_created)

        return summary

    def _create_license_record(self, batch, sheet, row, record_type):
        return PracticingLicenseRecord.objects.create(
            batch=batch,
            sheet=sheet,
            source_sheet_name=row["source_sheet"],
            source_row=row["source_row"],
            record_type=record_type,
            target_model=row["target_model"],
            record_year=2026,
            full_name=row["full_name"][:255],
            first_name=row["first_name"][:100],
            last_name=row["last_name"][:100],
            gender=row.get("gender", ""),
            date_of_birth=row.get("date_of_birth"),
            registration_no=row.get("registration_no", ""),
            practitioner_number=row.get("practitioner_number", ""),
            applicant_type=row.get("applicant_type", ""),
            nationality="Papua New Guinea" if row.get("applicant_type") == "national" else "",
            qualification_name=row.get("qualification_name", "")[:255],
            category="Full Registration",
            institution_name=row.get("institution_name", "")[:255],
            workplace_address=row.get("workplace_address", ""),
            province=row.get("province", ""),
            issued_date=row.get("issued_date"),
            payment_date=row.get("receipt_date"),
            reference_number=row.get("receipt_no", ""),
            raw_payload=row.get("raw_payload", {}),
        )

    def _upsert_professional(self, model, content_type, cadre, row, allow_create):
        registration_no = row.get("registration_no")
        if not registration_no:
            return None, False, False
        professional = model.objects.filter(registration_no=registration_no).first()
        if professional is None and not allow_create:
            return None, False, False
        created = False
        if professional is None:
            professional = model(registration_no=registration_no)
            created = True
        professional.first_name = row["first_name"][:100] or professional.first_name
        professional.last_name = row["last_name"][:100] or professional.last_name
        professional.applicant_type = row.get("applicant_type") or professional.applicant_type
        professional.gender = row.get("gender") or professional.gender
        professional.date_of_birth = row.get("date_of_birth") or professional.date_of_birth
        professional.primary_phone = row.get("phone") or professional.primary_phone
        professional.email = row.get("email") or professional.email
        professional.full_address = row.get("workplace_address") or professional.full_address
        professional.province = row.get("province") or professional.province
        professional.registration_number = registration_no
        professional.date_issued = row.get("issued_date") or professional.date_issued
        professional.license_expiry_date = (row["issued_date"] + timedelta(days=1095)) if row.get("issued_date") else professional.license_expiry_date
        professional.qualification_level = row.get("qualification_name", "")[:100] or professional.qualification_level
        professional.cadre = cadre
        professional.is_active = True
        professional.save()
        return professional, created, not created

    def _upsert_qualification(self, content_type, professional, row):
        institution_name = row.get("institution_name", "")[:255]
        institution = None
        if institution_name:
            institution, _ = TrainingInstitution.objects.get_or_create(name=institution_name)
        Qualification.objects.update_or_create(
            content_type=content_type,
            object_id=professional.id,
            qualification_name=(row.get("qualification_name") or "Full Registration")[:200],
            defaults={
                "institution": institution,
                "institution_name": institution_name,
                "program_completed": row.get("qualification_name", "")[:255],
                "completion_year": row.get("graduation_year"),
                "qualification_type": "Full Registration",
                "country": "Papua New Guinea" if row.get("applicant_type") == "national" else "",
            },
        )

    def _upsert_application(self, content_type, professional, row, status, workbook_name):
        payload = {
            "source_workbook": workbook_name,
            "source_sheet": row["source_sheet"],
            "source_row": row["source_row"],
            "registration_no": row.get("registration_no", ""),
            "provisional_number": row.get("practitioner_number", ""),
            "receipt_no": row.get("receipt_no", ""),
            "comment": row.get("comment", ""),
        }
        application, created = Application.objects.update_or_create(
            content_type=content_type,
            object_id=professional.id,
            form_code="NC2",
            defaults={
                "pathway": row.get("pathway") or "other",
                "form_title": "Application for Full Licence",
                "profession_track": row.get("profession_track", ""),
                "status": status,
                "approved_date": row.get("issued_date") if status == "approved" else None,
                "expiry_date": (row["issued_date"] + timedelta(days=1095)) if row.get("issued_date") and status == "approved" else None,
                "payload": payload,
                "reviewer_notes": f"Imported from {workbook_name} / {row['source_sheet']} row {row['source_row']}.",
            },
        )
        if row.get("issued_date"):
            application.submitted_date = row["issued_date"]
            application.save(update_fields=["submitted_date"])
        return created

    def _professional_duplicates(self, model, row):
        matches = []
        reg = row.get("registration_no")
        if reg:
            existing = model.objects.filter(registration_no=reg).first()
            if existing and professional_name(existing) != normalize_text(row["full_name"]).upper():
                matches.append({
                    "match_type": "registration_no_conflict",
                    "model": model.__name__,
                    "object_id": existing.id,
                    "existing_name": str(existing),
                    "existing_registration_no": existing.registration_no,
                    "similarity_score": 1.0,
                })
        same_name = model.objects.filter(first_name__iexact=row["first_name"], last_name__iexact=row["last_name"]).exclude(registration_no=reg).first()
        if same_name:
            matches.append({
                "match_type": "same_name_different_registration",
                "model": model.__name__,
                "object_id": same_name.id,
                "existing_name": str(same_name),
                "existing_registration_no": same_name.registration_no,
                "similarity_score": 0.88,
            })
        return matches

    def _screening_duplicates(self, row, full_name_index):
        matches = []
        professional = full_name_index.get(normalize_text(row["full_name"]).upper())
        if professional:
            matches.append({
                "match_type": "screening_row_matches_full_registration",
                "model": professional.__class__.__name__,
                "object_id": professional.id,
                "existing_name": str(professional),
                "existing_registration_no": professional.registration_no,
                "similarity_score": 0.95,
            })
        provisional = row.get("practitioner_number")
        if provisional:
            existing = PracticingLicenseRecord.objects.filter(practitioner_number=provisional).exclude(source_sheet_name=row["source_sheet"]).first()
            if existing:
                matches.append({
                    "match_type": "provisional_number_seen_before",
                    "model": "PracticingLicenseRecord",
                    "object_id": existing.id,
                    "existing_name": existing.full_name,
                    "existing_registration_no": existing.registration_no,
                    "existing_provisional_number": existing.practitioner_number,
                    "similarity_score": 0.9,
                })
        return matches

    def _queue_duplicate_reviews(self, content_type, record, matches, row):
        created = 0
        for match in matches:
            suspected = {
                "source_file": record.batch.source_file_name,
                "source_sheet": row["source_sheet"],
                "source_row": row["source_row"],
                "incoming_name": row["full_name"],
                "incoming_registration_no": row.get("registration_no", ""),
                "incoming_provisional_number": row.get("practitioner_number", ""),
                "match": match,
            }
            DuplicateReviewQueue.objects.create(
                content_type=content_type,
                object_id=record.id,
                suspected_duplicate=suspected,
                similarity_score=match["similarity_score"],
            )
            created += 1
        return created

    def _match_registration_from_master(self, row, master_rows):
        incoming = normalize_text(row["full_name"]).upper()
        for master in master_rows:
            if normalize_text(master["full_name"]).upper() == incoming:
                return master["registration_no"]
        return ""

    def _duplicate_preview(self, master_rows, screening_rows):
        count = 0
        for row in master_rows:
            model = Midwife if row["target_model"] == "midwife" else NursingProfessional
            count += len(self._professional_duplicates(model, row))
        full_names = {normalize_text(row["full_name"]).upper() for row in master_rows}
        count += sum(1 for row in screening_rows if normalize_text(row["full_name"]).upper() in full_names)
        return count

    def _safe_int(self, value):
        number = pd.to_numeric(value, errors="coerce")
        if pd.isna(number):
            return None
        return int(number)

    def _json_value(self, value):
        if value is None or pd.isna(value):
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return value
