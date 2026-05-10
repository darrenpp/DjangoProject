from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
import re

import pandas as pd
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone
from openpyxl import load_workbook

from apps.workforce.models import (
    CommunityHealthWorker,
    DataImportBatch,
    ImportedWorkbookSheet,
    PracticingLicenseRecord,
    Qualification,
    TrainingInstitution,
)


DEFAULT_MEDICAL_BOARD_WORKBOOK = Path(r"d:\Database Template\Medical Board\CHW 1985-2026 DATABASE CURRENTLY UPDATING.xlsx")

PROVINCES = [
    "Autonomous Region of Bougainville",
    "Central",
    "Chimbu",
    "East New Britain",
    "East Sepik",
    "Eastern Highlands",
    "Enga",
    "Gulf",
    "Hela",
    "Jiwaka",
    "Madang",
    "Manus",
    "Milne Bay",
    "Morobe",
    "National Capital District",
    "New Ireland",
    "Northern",
    "Oro",
    "Sandaun",
    "Simbu",
    "Southern Highlands",
    "Western",
    "Western Highlands",
    "West New Britain",
]

PROVINCE_ALIASES = {
    "NCD": "National Capital District",
    "W.H.P": "Western Highlands",
    "WHP": "Western Highlands",
    "S.H.P": "Southern Highlands",
    "SHP": "Southern Highlands",
    "E.H.P": "Eastern Highlands",
    "EHP": "Eastern Highlands",
    "W.S.P": "Sandaun",
    "ORO": "Northern",
    "NORTHERN PROVINCE": "Northern",
    "MOROBE PROVINCE": "Morobe",
    "MADANG PROVINCE": "Madang",
}


def clean_text(value):
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    text = text.replace("\u25cf", "").replace("\u26ab", "")
    return re.sub(r"\s+", " ", text).strip()


def title_name(value):
    text = clean_text(value)
    if "," in text:
        family, given = [part.strip() for part in text.split(",", 1)]
        text = f"{given} {family}".strip()
    return text.title()


def split_name(value):
    text = title_name(value)
    parts = text.split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def parse_date(value):
    if value is None or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        return value.date() if 1901 <= value.year <= date.today().year + 1 else None
    if isinstance(value, date):
        return value if 1901 <= value.year <= date.today().year + 1 else None
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        serial_value = float(value)
        if 20000 <= serial_value <= 60000:
            parsed = date(1899, 12, 30) + timedelta(days=int(serial_value))
            return parsed if 1901 <= parsed.year <= date.today().year + 1 else None

    text = clean_text(value)
    if not text:
        return None
    text = text.replace("_", ".").replace("-", ".")
    text = re.sub(r"\s+", "", text)
    for fmt in ("%d.%m.%Y", "%d.%m.%y", "%d/%m/%Y", "%d/%m/%y"):
        try:
            parsed = datetime.strptime(text, fmt).date()
            return parsed if 1901 <= parsed.year <= date.today().year + 1 else None
        except ValueError:
            continue
    parsed = pd.to_datetime(text, dayfirst=True, errors="coerce")
    if pd.isna(parsed):
        return None
    parsed_date = pd.Timestamp(parsed).date()
    return parsed_date if 1901 <= parsed_date.year <= date.today().year + 1 else None


def extract_year(value, fallback_date=None):
    parsed = parse_date(value)
    if parsed:
        return parsed.year
    text = clean_text(value)
    match = re.search(r"(19|20)\d{2}", text)
    if match:
        year = int(match.group(0))
        if 1980 <= year <= date.today().year + 1:
            return year
    return fallback_date.year if fallback_date else None


def normalize_registration(value, prefix="CHW"):
    text = clean_text(value).upper()
    if not text:
        return ""
    if re.fullmatch(r"\d+\.0+", text):
        text = text.split(".", 1)[0]
    text = re.sub(r"\s+", "", text)
    return f"{prefix}-{text}"[:50]


def extract_practitioner_number(remarks):
    text = clean_text(remarks).upper()
    match = re.search(r"P\s*#\s*:?\s*([A-Z0-9/-]+)", text)
    return match.group(1)[:100] if match else ""


def extract_student_id(remarks):
    text = clean_text(remarks).upper()
    match = re.search(r"STUDENT\s*ID\s*[-:]?\s*([A-Z0-9/-]+)", text)
    return match.group(1)[:100] if match else ""


def extract_province(address):
    text = clean_text(address).upper()
    for alias, province in PROVINCE_ALIASES.items():
        if alias in text:
            return province
    for province in PROVINCES:
        if province.upper() in text:
            return province
    return ""


def extract_school_name(qualification):
    text = clean_text(qualification)
    match = re.search(r"\(([^)]+)\)", text)
    if match:
        return match.group(1).strip().title()
    match = re.search(r"CERT(?:IFICATE)? IN CHW,\s*([^,]+)", text, flags=re.IGNORECASE)
    return match.group(1).strip().title() if match else ""


class MedicalBoardWorkbookImporter:
    def __init__(self, workbook_path=DEFAULT_MEDICAL_BOARD_WORKBOOK, initiated_by=None):
        self.workbook_path = Path(workbook_path)
        self.initiated_by = initiated_by
        self.summary = Counter()

    def import_workbook(self):
        if not self.workbook_path.exists():
            raise FileNotFoundError(f"Medical Board workbook not found: {self.workbook_path}")

        workbook = load_workbook(self.workbook_path, read_only=True, data_only=True)
        batch = DataImportBatch.objects.create(
            source_file_name=self.workbook_path.name,
            source_file_path=str(self.workbook_path),
            source_kind="medical_board_workbook",
            status="running",
            total_sheets=len(workbook.sheetnames),
            total_rows=sum(workbook[name].max_row or 0 for name in workbook.sheetnames),
            initiated_by=self.initiated_by,
        )

        try:
            with transaction.atomic():
                for sheet_name in workbook.sheetnames:
                    worksheet = workbook[sheet_name]
                    if sheet_name.upper() == "CHW":
                        self._import_chw_sheet(batch, worksheet)
                    elif sheet_name.upper() == "NOT ON DATABASE":
                        self._import_pending_chw_sheet(batch, worksheet)
                    elif sheet_name.upper() == "SCHOOL ADDRESS":
                        self._import_school_sheet(batch, worksheet)
                    else:
                        ImportedWorkbookSheet.objects.create(
                            batch=batch,
                            sheet_name=sheet_name,
                            sheet_type="reference",
                            status="skipped",
                            raw_rows=worksheet.max_row or 0,
                            notes="Reference/chart sheet retained in workbook but not row-imported.",
                        )
                    batch.processed_sheets += 1
                    batch.save(update_fields=["processed_sheets"])

            batch.status = "completed"
            batch.summary = dict(self.summary)
            batch.processed_rows = self.summary.get("processed_rows", 0)
            batch.completed_at = timezone.now()
            batch.save(update_fields=["status", "summary", "processed_rows", "completed_at"])
            return batch
        except Exception as exc:
            batch.status = "failed"
            batch.summary = {"error": str(exc), **dict(self.summary)}
            batch.completed_at = timezone.now()
            batch.save(update_fields=["status", "summary", "completed_at"])
            raise

    def _record_import(self, batch, sheet, row_number, record, *, pending=False):
        registration_no = normalize_registration(record.get("registry"))
        source_name = clean_text(record.get("name"))
        full_name = title_name(source_name)
        if not full_name:
            self.summary["skipped_missing_name"] += 1
            return None

        issued_date = parse_date(record.get("date"))
        year = extract_year(record.get("date"), issued_date)
        first_name, last_name = split_name(source_name)
        qualification = clean_text(record.get("qualification"))
        address = clean_text(record.get("address"))
        remarks = clean_text(record.get("remarks"))
        receipt = clean_text(record.get("receipt"))
        practitioner_number = extract_practitioner_number(remarks) or extract_student_id(remarks)
        province = extract_province(address)

        if not registration_no:
            safe_key = practitioner_number or f"{sheet.sheet_name}-{row_number}"
            registration_no = normalize_registration(safe_key, prefix="CHW-PENDING")

        chw, _ = CommunityHealthWorker.objects.update_or_create(
            registration_no=registration_no,
            defaults={
                "first_name": first_name or "CHW",
                "last_name": last_name or "Record",
                "applicant_type": "national",
                "full_address": address,
                "province": province,
                "community_id": practitioner_number[:50],
                "training_level": qualification[:100],
                "is_active": True,
            },
        )
        self._save_qualification(chw, qualification)

        PracticingLicenseRecord.objects.create(
            batch=batch,
            sheet=sheet,
            record_type="workforce_listing",
            target_model="communityhealthworker",
            source_sheet_name=sheet.sheet_name,
            source_row=row_number,
            record_year=year,
            full_name=full_name,
            first_name=first_name,
            last_name=last_name,
            registration_no=registration_no,
            practitioner_number=practitioner_number,
            applicant_type="national",
            qualification_name=qualification,
            category="Community Health Worker - Pending" if pending else "Community Health Worker",
            institution_name=extract_school_name(qualification),
            workplace_address=address,
            province=province,
            issued_date=issued_date,
            reference_number=receipt,
            raw_payload={
                "registry": clean_text(record.get("registry")),
                "date": clean_text(record.get("date")),
                "address": address,
                "receipt": receipt,
                "remarks": remarks,
                "pending_import": pending,
            },
        )
        self.summary["chw_imported"] += 1
        if pending:
            self.summary["pending_chw_imported"] += 1
        self.summary["processed_rows"] += 1
        if year:
            self.summary[f"year_{year}"] += 1
        return chw

    def _import_chw_sheet(self, batch, worksheet):
        sheet = ImportedWorkbookSheet.objects.create(
            batch=batch,
            sheet_name=worksheet.title,
            sheet_type="medical_board_chw",
            status="processed",
            raw_rows=max((worksheet.max_row or 1) - 1, 0),
        )
        imported = skipped = 0
        for row_number, row in enumerate(worksheet.iter_rows(min_row=2, values_only=True), start=2):
            registry, entry_date, name, address, qualification, receipt, remarks = (list(row) + [None] * 7)[:7]
            if not clean_text(name):
                skipped += 1
                continue
            self._record_import(
                batch,
                sheet,
                row_number,
                {
                    "registry": registry,
                    "date": entry_date,
                    "name": name,
                    "address": address,
                    "qualification": qualification,
                    "receipt": receipt,
                    "remarks": remarks,
                },
            )
            imported += 1
        sheet.imported_rows = imported
        sheet.skipped_rows = skipped
        sheet.save(update_fields=["imported_rows", "skipped_rows"])

    def _import_pending_chw_sheet(self, batch, worksheet):
        sheet = ImportedWorkbookSheet.objects.create(
            batch=batch,
            sheet_name=worksheet.title,
            sheet_type="medical_board_chw_pending",
            status="processed",
            raw_rows=max((worksheet.max_row or 1) - 1, 0),
        )
        imported = skipped = 0
        for row_number, row in enumerate(worksheet.iter_rows(min_row=2, values_only=True), start=2):
            registry, entry_date, name, address, qualification, receipt, remarks = (list(row) + [None] * 7)[:7]
            if not clean_text(name):
                skipped += 1
                continue
            self._record_import(
                batch,
                sheet,
                row_number,
                {
                    "registry": registry,
                    "date": entry_date,
                    "name": name,
                    "address": address,
                    "qualification": qualification,
                    "receipt": receipt,
                    "remarks": remarks,
                },
                pending=True,
            )
            imported += 1
        sheet.imported_rows = imported
        sheet.skipped_rows = skipped
        sheet.save(update_fields=["imported_rows", "skipped_rows"])

    def _import_school_sheet(self, batch, worksheet):
        sheet = ImportedWorkbookSheet.objects.create(
            batch=batch,
            sheet_name=worksheet.title,
            sheet_type="medical_board_training_institutions",
            status="processed",
            raw_rows=worksheet.max_row or 0,
        )
        imported = 0
        stats = []
        for row in worksheet.iter_rows(min_row=4, values_only=True):
            number, school, province, address = (list(row) + [None] * 4)[:4]
            school_name = clean_text(school)
            if not school_name or not clean_text(number):
                continue
            institution, _ = TrainingInstitution.objects.update_or_create(
                name=school_name.title(),
                defaults={"type": "CHW Training School", "is_active": True},
            )
            stats.append({
                "institution_id": institution.pk,
                "school": institution.name,
                "province": clean_text(province),
                "address": clean_text(address),
            })
            imported += 1
        sheet.imported_rows = imported
        sheet.metadata = {"training_institutions": stats[:40]}
        sheet.save(update_fields=["imported_rows", "metadata"])
        self.summary["training_institutions_imported"] += imported

    def _save_qualification(self, chw, qualification):
        if not qualification:
            return
        content_type = ContentType.objects.get_for_model(chw)
        institution_name = extract_school_name(qualification)
        institution = None
        if institution_name:
            institution, _ = TrainingInstitution.objects.get_or_create(
                name=institution_name,
                defaults={"type": "CHW Training School", "is_active": True},
            )
        Qualification.objects.update_or_create(
            content_type=content_type,
            object_id=chw.pk,
            qualification_name=qualification[:200],
            defaults={
                "institution": institution,
                "institution_name": institution_name,
                "program_completed": "Community Health Worker",
                "qualification_type": "Certificate",
                "country": "Papua New Guinea",
            },
        )
