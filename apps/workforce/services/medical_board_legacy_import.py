from collections import Counter
from datetime import date
from decimal import Decimal
import os
from pathlib import Path
import re

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone
from openpyxl import load_workbook

from apps.workforce.models import (
    DataImportBatch,
    ImportedWorkbookSheet,
    MedicalDoctor,
    PracticingLicenseRecord,
    Qualification,
)
from apps.workforce.services.medical_board_workbook_import import (
    clean_text,
    extract_amount,
    normalize_registration,
    parse_date,
    split_name,
    title_name,
)


DEFAULT_MEDICAL_BOARD_LEGACY_WORKBOOKS = [
    Path(
        r"c:\Users\darre\OneDrive\Documents\ProjectApps\databasedocuments"
        r"\medicalboarddata\Current database on Medical Board"
        r"\All ANAESTHESTICS 2026\All ANAESTHESTICS 2026.xlsx"
    ),
    Path(
        r"c:\Users\darre\OneDrive\Documents\ProjectApps\databasedocuments"
        r"\medicalboarddata\Current database on Medical Board"
        r"\All EHO'S  2026\All EHO'S  2026.xlsx"
    ),
    Path(
        r"c:\Users\darre\OneDrive\Documents\ProjectApps\databasedocuments"
        r"\medicalboarddata\Current database on Medical Board"
        r"\All MLT-MLA 2026\All MLT-MLA 2026.xlsx"
    ),
    Path(
        r"c:\Users\darre\OneDrive\Documents\ProjectApps\databasedocuments"
        r"\medicalboarddata\EXCEL DATA"
        r"\LIST OF EHO'S MIX  2026 UPDATES\LIST OF EHO'S MIX  2026 UPDATES.xlsx"
    ),
    Path(
        r"c:\Users\darre\OneDrive\Documents\ProjectApps\databasedocuments"
        r"\medicalboarddata\EXCEL DATA"
        r"\OVERSEAS DATABASE REGISTRATION 2026\OVERSEAS DATABASE REGISTRATION 2026.xlsx"
    ),
]

HEADER_ALIASES = {
    "app for": "application_for",
    "arc#": "registration_card",
    "atp / frc": "license_status",
    "atp / full r c": "license_status",
    "atp date": "atp_date",
    "authority to practice / full r c": "license_status",
    "card #": "registration_card",
    "doctors name": "full_name",
    "employer": "employer_name",
    "last atp": "last_atp_year",
    "last atp year": "last_atp_year",
    "mb rego card#": "registration_card",
    "mb rego no.#": "registration_card",
    "medical practioners#": "medical_practitioner_no",
    "mp#": "medical_practitioner_no",
    "names": "full_name",
    "nationality": "nationality",
    "officer name": "full_name",
    "practisioners #": "practitioner_no",
    "practioners #/nos": "practitioner_no",
    "prov mlt#/nos": "provisional_no",
    "province": "province",
    "qualification": "qualification",
    "qualification/designation": "qualification",
    "reciept no#": "receipt_number",
    "reciept#": "receipt_number",
    "receipt no#": "receipt_number",
    "receipt#": "receipt_number",
    "rego date": "registration_date",
    "registration date": "registration_date",
    "remarks": "remarks",
    "spec#": "specialist_no",
    "year": "record_year",
}

SHEET_CATEGORY_HINTS = {
    "EHO": "Environmental Health Officer",
    "HEO": "Health Extension Officer",
    "NAT-ANAESTHESTICS": "Anaesthetics/ATO",
    "NAT-MLT-MLA": "Medical Laboratory Technician / Assistant",
    "NAT-PHYSIOTHERAPIST": "Physiotherapist",
    "ALL OVERSESA MEMBERS MB": "Overseas Medical Board Practitioner",
}

DOCTOR_KEYWORDS = (
    "BDS",
    "DENTAL",
    "DOCTOR",
    "MBBS",
    "MEDICAL PRACTITIONER",
    "MEDICAL PRACTIONER",
    "MD ",
    "PAEDIATRIC",
    "PEADIATRIC",
    "SPECIALIST",
    "SURGEON",
)

GENERIC_REGISTRATION_CODES = {
    "ATO01",
    "MB.01",
    "MLT/MLA01",
    "PHYSIO-01",
}


def normalize_header(value):
    text = clean_text(value).lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def safe_sheet_label(workbook_path, sheet_name):
    label = f"{Path(workbook_path).stem}::{sheet_name}"
    return label[:255]


def normalise_source_key(value):
    text = clean_text(value).upper()
    return re.sub(r"[^A-Z0-9]+", "-", text).strip("-")


def compact_source_key(workbook_path, source_sheet, row_number):
    workbook_key = normalise_source_key(Path(workbook_path).stem)[:14]
    sheet_key = normalise_source_key(source_sheet)[:14]
    return f"{row_number}-{workbook_key}-{sheet_key}"


def is_generic_registration_code(value):
    text = clean_text(value).upper()
    if not text:
        return True
    if text in GENERIC_REGISTRATION_CODES:
        return True
    return bool(re.fullmatch(r"[A-Z]{2,6}\.?\d{1,2}", text))


def latest_year(value):
    parsed = parse_date(value)
    if parsed:
        return parsed.year
    years = [
        int(match.group(0))
        for match in re.finditer(r"(?:19|20)\d{2}", clean_text(value))
        if 1901 <= int(match.group(0)) <= date.today().year + 1
    ]
    if years:
        return max(years)
    text = clean_text(value)
    if re.fullmatch(r"\d{2}", text):
        year = int(text)
        return 2000 + year if year <= date.today().year % 100 + 1 else 1900 + year
    return None


def infer_category(sheet_name, qualification):
    sheet_upper = clean_text(sheet_name).upper()
    for hint, label in SHEET_CATEGORY_HINTS.items():
        if hint in sheet_upper:
            return label
    return clean_text(qualification) or "Medical Board Practitioner"


def infer_target_model(category, qualification, sheet_name):
    text = f"{category} {qualification} {sheet_name}".upper()
    if any(keyword in text for keyword in DOCTOR_KEYWORDS):
        return "medicaldoctor"
    return "other"


def infer_specialty_value(category, qualification):
    text = f"{category} {qualification}".upper()
    if "PUBLIC HEALTH" in text:
        return "public_health"
    if "PAEDIATR" in text or "PEADIATR" in text:
        return "paediatric_child_health"
    if "RADIOLOG" in text:
        return "radiology"
    if "PATHOLOG" in text:
        return "pathology"
    if "MICROBIOLOG" in text:
        return "microbiology"
    if "DERMATOLOG" in text:
        return "dermatology"
    if "PSYCHIAT" in text:
        return "psychiatry_mental_health"
    if "CARDIO" in text:
        return "cardiology"
    if "SPECIALIST" in text:
        return "other"
    return ""


def record_type_from_status(status):
    text = clean_text(status).upper()
    if "FULL" in text or "FRC" in text or "R C" in text:
        return "full"
    return "workforce_listing"


def applicant_type_from_nationality(nationality):
    text = clean_text(nationality).upper()
    return "national" if text in {"PNG", "PAPUA NEW GUINEA", "P.N.G."} else "overseas"


def year_columns(headers):
    columns = []
    for index, header in enumerate(headers):
        text = clean_text(header)
        if re.fullmatch(r"(?:19|20)\d{2}", text):
            year = int(text)
            if 1901 <= year <= date.today().year + 1:
                columns.append((index, year))
    return columns


class MedicalBoardLegacyWorkbookImporter:
    def __init__(self, workbook_paths=None, initiated_by=None):
        self.workbook_paths = [Path(path) for path in (workbook_paths or DEFAULT_MEDICAL_BOARD_LEGACY_WORKBOOKS)]
        self.initiated_by = initiated_by
        self.summary = Counter()
        self._row_dedupes = set()
        self._licence_dedupes = set()

    def import_workbooks(self):
        existing_paths = [path for path in self.workbook_paths if path.exists()]
        missing_paths = [str(path) for path in self.workbook_paths if not path.exists()]
        if not existing_paths:
            raise FileNotFoundError("No Medical Board legacy workbooks were found.")

        workbook_metadata = []
        for path in existing_paths:
            workbook = load_workbook(path, read_only=True, data_only=True)
            try:
                workbook_metadata.append({
                    "path": path,
                    "sheet_count": len(workbook.sheetnames),
                    "row_count": sum(workbook[name].max_row or 0 for name in workbook.sheetnames),
                })
            finally:
                workbook.close()

        batch = DataImportBatch.objects.create(
            source_file_name="Medical Board legacy workbooks",
            source_file_path=os.linesep.join(str(item["path"]) for item in workbook_metadata),
            source_kind="medical_board_workbook",
            status="running",
            total_sheets=sum(item["sheet_count"] for item in workbook_metadata),
            total_rows=sum(item["row_count"] for item in workbook_metadata),
            initiated_by=self.initiated_by,
            summary={"missing_files": missing_paths},
        )

        try:
            with transaction.atomic():
                for item in workbook_metadata:
                    self._import_single_workbook(batch, item["path"])
            batch.status = "completed"
            batch.processed_rows = self.summary.get("records_created", 0)
            batch.summary = {**dict(self.summary), "missing_files": missing_paths}
            batch.completed_at = timezone.now()
            batch.save(update_fields=["status", "processed_rows", "summary", "completed_at"])
            return batch
        except Exception as exc:
            batch.status = "failed"
            batch.summary = {"error": str(exc), **dict(self.summary), "missing_files": missing_paths}
            batch.completed_at = timezone.now()
            batch.save(update_fields=["status", "summary", "completed_at"])
            raise

    def _import_single_workbook(self, batch, workbook_path):
        workbook = load_workbook(workbook_path, read_only=True, data_only=True)
        try:
            for worksheet in workbook.worksheets:
                self._import_worksheet(batch, workbook_path, worksheet)
                batch.processed_sheets += 1
                batch.save(update_fields=["processed_sheets"])
        finally:
            workbook.close()

    def _find_header(self, worksheet):
        for row_number, row in enumerate(
            worksheet.iter_rows(min_row=1, max_row=min(worksheet.max_row or 0, 10), values_only=True),
            start=1,
        ):
            headers = [clean_text(value) for value in row]
            mapped = {}
            for index, header in enumerate(headers):
                canonical = HEADER_ALIASES.get(normalize_header(header))
                if canonical and canonical not in mapped:
                    mapped[canonical] = index
            if "full_name" in mapped:
                return row_number, headers, mapped
        return None, [], {}

    def _import_worksheet(self, batch, workbook_path, worksheet):
        sheet_name = safe_sheet_label(workbook_path, worksheet.title)
        header_row, headers, header_map = self._find_header(worksheet)
        sheet = ImportedWorkbookSheet.objects.create(
            batch=batch,
            sheet_name=sheet_name,
            sheet_type="medical_board_legacy",
            status="processed" if header_row else "skipped",
            raw_rows=max((worksheet.max_row or 0) - (header_row or 0), 0),
            notes="" if header_row else "No Medical Board row header found.",
            metadata={"source_file": str(workbook_path), "source_sheet": worksheet.title},
        )
        if not header_row:
            self.summary["sheets_skipped"] += 1
            return

        imported = skipped = 0
        for row_number, row in enumerate(worksheet.iter_rows(min_row=header_row + 1, values_only=True), start=header_row + 1):
            record = self._row_to_record(headers, header_map, row)
            if not record.get("full_name"):
                skipped += 1
                continue
            created = self._record_legacy_row(batch, sheet, workbook_path, worksheet.title, row_number, record)
            imported += created
            if not created:
                skipped += 1
            self._record_year_columns(batch, sheet, worksheet.title, row_number, record, headers, row)

        sheet.imported_rows = imported
        sheet.skipped_rows = skipped
        sheet.save(update_fields=["imported_rows", "skipped_rows"])

    def _row_to_record(self, headers, header_map, row):
        record = {}
        for field_name, index in header_map.items():
            if index < len(row):
                record[field_name] = clean_text(row[index])
        record["raw_headers"] = headers
        return record

    def _source_registration(self, record, source_key, target_model):
        candidates = [
            record.get("medical_practitioner_no"),
            record.get("specialist_no"),
            record.get("practitioner_no"),
            record.get("provisional_no"),
            record.get("registration_card"),
        ]
        for candidate in candidates:
            text = clean_text(candidate).upper()
            if text and not is_generic_registration_code(text):
                prefix = "MD" if target_model == "medicaldoctor" else "MB"
                return normalize_registration(text, prefix=prefix)
        prefix = "MD" if target_model == "medicaldoctor" else "MB-AH"
        return normalize_registration(source_key, prefix=prefix)

    def _record_legacy_row(self, batch, sheet, workbook_path, source_sheet, row_number, record):
        source_key = compact_source_key(workbook_path, source_sheet, row_number)
        category = infer_category(source_sheet, record.get("qualification"))
        target_model = infer_target_model(category, record.get("qualification"), source_sheet)
        full_name = title_name(record.get("full_name"))
        first_name, last_name = split_name(full_name)
        record_year = (
            latest_year(record.get("record_year"))
            or latest_year(record.get("last_atp_year"))
            or latest_year(record.get("atp_date"))
            or latest_year(record.get("registration_date"))
        )
        issued_date = parse_date(record.get("atp_date")) or parse_date(record.get("registration_date"))
        registration_no = self._source_registration(record, source_key, target_model)
        practitioner_number = clean_text(record.get("practitioner_no") or record.get("medical_practitioner_no"))
        receipt_number = clean_text(record.get("receipt_number"))
        applicant_type = applicant_type_from_nationality(record.get("nationality"))
        identity_key = (
            full_name.upper(),
            category.upper(),
            registration_no.upper(),
            practitioner_number.upper(),
            str(record_year or ""),
            receipt_number.upper(),
        )
        if identity_key in self._row_dedupes:
            self.summary["duplicate_rows_skipped"] += 1
            return 0
        self._row_dedupes.add(identity_key)

        medical_doctor = None
        if target_model == "medicaldoctor":
            medical_doctor = self._upsert_medical_doctor(
                registration_no,
                first_name,
                last_name,
                record,
                category,
                applicant_type,
                issued_date,
            )

        PracticingLicenseRecord.objects.create(
            batch=batch,
            sheet=sheet,
            record_type=record_type_from_status(record.get("license_status")),
            target_model=target_model,
            source_sheet_name=sheet.sheet_name,
            source_row=row_number,
            record_year=record_year,
            full_name=full_name,
            first_name=first_name,
            last_name=last_name,
            registration_no=registration_no,
            practitioner_number=practitioner_number,
            applicant_type=applicant_type,
            nationality=record.get("nationality", ""),
            qualification_name=record.get("qualification", ""),
            category=category,
            workplace_address=record.get("employer_name", ""),
            province=record.get("province", ""),
            issued_date=issued_date,
            reference_number=receipt_number,
            amount=extract_amount(record.get("remarks") or record.get("receipt_number")),
            raw_payload=self._payload(record, workbook_path, source_sheet, category, target_model, source_key),
        )
        self.summary["records_created"] += 1
        self.summary[f"{target_model}_rows"] += 1
        self.summary[f"category_{category}"] += 1
        if target_model == "medicaldoctor" and medical_doctor:
            self.summary["medical_doctors_upserted"] += 1

        if receipt_number:
            self._record_payment(
                batch,
                sheet,
                row_number,
                record,
                full_name,
                first_name,
                last_name,
                registration_no,
                practitioner_number,
                applicant_type,
                category,
                target_model,
                record_year,
                issued_date,
                receipt_number,
            )
        return 1

    def _record_year_columns(self, batch, sheet, source_sheet, row_number, record, headers, row):
        full_name = title_name(record.get("full_name"))
        if not full_name:
            return
        first_name, last_name = split_name(full_name)
        category = infer_category(source_sheet, record.get("qualification"))
        target_model = infer_target_model(category, record.get("qualification"), source_sheet)
        source_key = f"{row_number}-{normalise_source_key(sheet.sheet_name)[:24]}"
        registration_no = self._source_registration(record, source_key, target_model)
        practitioner_number = clean_text(record.get("practitioner_no") or record.get("medical_practitioner_no"))
        applicant_type = applicant_type_from_nationality(record.get("nationality"))

        for position, (index, year) in enumerate(year_columns(headers), start=1):
            payment_text = clean_text(row[index] if index < len(row) else None)
            receipt_text = clean_text(row[index + 1] if index + 1 < len(row) else None)
            if not payment_text and not receipt_text:
                continue
            key = (
                full_name.upper(),
                category.upper(),
                str(year),
                payment_text.upper(),
                receipt_text.upper(),
            )
            if key in self._licence_dedupes:
                self.summary["duplicate_licence_rows_skipped"] += 1
                continue
            self._licence_dedupes.add(key)
            PracticingLicenseRecord.objects.create(
                batch=batch,
                sheet=sheet,
                record_type="practicing_license",
                target_model=target_model,
                source_sheet_name=sheet.sheet_name,
                source_row=(row_number * 100) + position,
                record_year=year,
                full_name=full_name,
                first_name=first_name,
                last_name=last_name,
                registration_no=registration_no,
                practitioner_number=practitioner_number,
                applicant_type=applicant_type,
                qualification_name=record.get("qualification", ""),
                category=category,
                workplace_address=record.get("employer_name", ""),
                province=record.get("province", ""),
                payment_date=parse_date(payment_text),
                amount=extract_amount(payment_text),
                reference_number=receipt_text or payment_text,
                raw_payload={
                    "source_sheet": source_sheet,
                    "payment": payment_text,
                    "receipt": receipt_text,
                    "year": year,
                    "form_code": "MBRN",
                    "profession_track": "medical_doctor" if target_model == "medicaldoctor" else "allied_health",
                },
            )
            self.summary["records_created"] += 1
            self.summary["practicing_license_rows"] += 1

    def _record_payment(
        self,
        batch,
        sheet,
        row_number,
        record,
        full_name,
        first_name,
        last_name,
        registration_no,
        practitioner_number,
        applicant_type,
        category,
        target_model,
        record_year,
        issued_date,
        receipt_number,
    ):
        PracticingLicenseRecord.objects.create(
            batch=batch,
            sheet=sheet,
            record_type="payment",
            target_model=target_model,
            source_sheet_name=sheet.sheet_name,
            source_row=(row_number * 1000) + 1,
            record_year=record_year,
            full_name=full_name,
            first_name=first_name,
            last_name=last_name,
            registration_no=registration_no,
            practitioner_number=practitioner_number,
            applicant_type=applicant_type,
            qualification_name=record.get("qualification", ""),
            category=category,
            workplace_address=record.get("employer_name", ""),
            province=record.get("province", ""),
            payment_date=issued_date,
            amount=extract_amount(record.get("remarks") or receipt_number),
            reference_number=receipt_number,
            raw_payload={**record, "form_code": "MBRN", "payment_source": "legacy_medical_board_workbook"},
        )
        self.summary["records_created"] += 1
        self.summary["payment_rows"] += 1

    def _payload(self, record, workbook_path, source_sheet, category, target_model, source_key):
        return {
            "source_file": str(workbook_path),
            "source_sheet": source_sheet,
            "source_key": source_key,
            "form_code": "MBSP" if "SPECIALIST" in category.upper() else "MBRN",
            "profession_track": "medical_doctor" if target_model == "medicaldoctor" else "allied_health",
            "category": category,
            "full_name": record.get("full_name", ""),
            "nationality": record.get("nationality", ""),
            "registration_no": record.get("registration_card", ""),
            "practitioner_no": record.get("practitioner_no") or record.get("medical_practitioner_no", ""),
            "qualification": record.get("qualification", ""),
            "application_for": record.get("application_for", ""),
            "year": record.get("record_year", ""),
            "employer_name": record.get("employer_name", ""),
            "license_status": record.get("license_status", ""),
            "atp_date": record.get("atp_date", ""),
            "receipt_number": record.get("receipt_number", ""),
            "province": record.get("province", ""),
            "remarks": record.get("remarks", ""),
        }

    def _upsert_medical_doctor(self, registration_no, first_name, last_name, record, category, applicant_type, issued_date):
        specialty = infer_specialty_value(category, record.get("qualification", ""))
        existing = MedicalDoctor.objects.filter(registration_no=registration_no).only("pk").first()
        defaults = {
            "first_name": first_name or "Medical",
            "last_name": last_name or "Practitioner",
            "applicant_type": applicant_type,
            "nationality": record.get("nationality", ""),
            "full_address": record.get("employer_name", ""),
            "province": record.get("province", ""),
            "date_issued": issued_date,
            "is_active": True,
        }
        if specialty or not existing:
            defaults["specialty"] = specialty
        doctor, _created = MedicalDoctor.objects.update_or_create(
            registration_no=registration_no,
            defaults=defaults,
        )
        qualification = record.get("qualification", "")
        if qualification:
            Qualification.objects.update_or_create(
                content_type=ContentType.objects.get_for_model(doctor),
                object_id=doctor.pk,
                qualification_name=qualification[:200],
                defaults={
                    "institution_name": record.get("employer_name", "")[:255],
                    "program_completed": category[:255],
                    "qualification_type": "Medical Board legacy import",
                    "country": record.get("nationality", "") or "Papua New Guinea",
                },
            )
        return doctor
