from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.workforce.models import (
    MedicalDoctor,
    PracticingLicenseRecord,
    Qualification,
)

from .models import NHWACellEntry, NHWAWebWorkbook, NHWAWorkbookAuditEvent
from .services import clean_cell_value


NURSING_SOURCE_KINDS = ("ndata_workbook", "nursing_license_workbook")
MEDICAL_SOURCE_KINDS = ("medical_board_workbook",)


def _usable_identifier(value):
    value = clean_cell_value(value)
    if not value:
        return ""
    if value.upper() in {"TBA", "N/A", "NA", "-", "--", "NONE", "NULL"}:
        return ""
    return value


def _record_key(record):
    registration = _usable_identifier(record.registration_no)
    practitioner = _usable_identifier(record.practitioner_number)
    if registration:
        return f"reg:{record.target_model}:{registration.upper()}"
    if practitioner:
        return f"prac:{record.target_model}:{practitioner.upper()}"
    name = clean_cell_value(record.full_name).lower()
    return f"name:{record.target_model}:{name}:{clean_cell_value(record.gender).lower()}"


def _dedup(records):
    by_key = {}
    for record in records:
        by_key.setdefault(_record_key(record), record)
    return list(by_key.values())


def _gender_bucket(value):
    value = clean_cell_value(value).lower()
    if value in {"male", "m", "mael"}:
        return "male"
    if value in {"female", "f", "famale", "femile"}:
        return "female"
    return "unknown"


def _is_png_national(value):
    value = clean_cell_value(value).lower()
    if not value:
        return None
    return value in {
        "png",
        "papua new guinea",
        "papua new guinean",
        "papua new guinea citizen",
        "national",
    }


def _money_total(records):
    total = Decimal("0")
    has_value = False
    for record in records:
        for field in ("amount", "renewal_fee", "overseas_fee", "penalty_fee", "late_fee"):
            value = getattr(record, field, None)
            if value is not None:
                total += value
                has_value = True
    return total if has_value else None


def _format_number(value):
    if value in (None, ""):
        return ""
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return str(int(value))
        return str(value.quantize(Decimal("0.01")))
    return str(value)


def _json_safe(value):
    if isinstance(value, Decimal):
        return _format_number(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _nursing_category(record):
    target = clean_cell_value(record.target_model).lower()
    category = clean_cell_value(record.category).lower()
    text = f"{target} {category}"
    if target == "midwife" or "midwife" in text or "midwifery" in text:
        return "midwife"
    if target == "communityhealthworker" or "community health" in text or "chw" in text:
        return "chw"
    if target == "nurseaide" or "nurse aide" in text or "enrolled" in text or "auxiliary" in text:
        return "auxiliary_nurse"
    if (
        "special" in text
        or "acute" in text
        or "paediatric" in text
        or "pediatric" in text
        or "mental" in text
        or "maternal" in text
        or "eye" in text
        or "child" in text
    ):
        return "specialist_nurse"
    if target == "nursingprofessional":
        return "registered_nurse"
    return ""


def _stats_from_records(records):
    records = _dedup(records)
    practising = _dedup([record for record in records if record.record_type == "practicing_license"])
    gender_counts = Counter(_gender_bucket(record.gender) for record in practising)
    nationality_counts = Counter(_is_png_national(record.nationality) for record in practising)
    fee_total = _money_total(records)
    return {
        "registered": len(records),
        "active": len(records),
        "practising": len(practising),
        "male": gender_counts["male"],
        "female": gender_counts["female"],
        "unknown_sex": gender_counts["unknown"],
        "png": nationality_counts[True],
        "foreign": nationality_counts[False],
        "fee_total": fee_total,
    }


def _write_cell(sheet, coordinate, value, actor=None):
    cell = sheet.cell_templates.filter(coordinate=coordinate).first()
    if cell is None or cell.is_formula:
        return False
    value = clean_cell_value(_format_number(value))
    entry, _created = NHWACellEntry.objects.get_or_create(template=cell)
    if entry.value == value:
        return False
    entry.value = value
    entry.updated_by = actor
    entry.save(update_fields=["value", "updated_by", "updated_at"])
    return True


def _write_cells(sheet, values, actor=None):
    changed = 0
    for coordinate, value in values.items():
        if _write_cell(sheet, coordinate, value, actor=actor):
            changed += 1
    return changed


def _write_t3_category(sheet, row, stats, note, source_system, actor=None):
    values = {
        f"B{row}": stats.get("registered", ""),
        f"C{row}": stats.get("active", ""),
        f"D{row}": stats.get("practising", ""),
        f"G{row}": stats.get("male", ""),
        f"H{row}": stats.get("female", ""),
        f"I{row}": stats.get("unknown_sex", ""),
        f"K{row}": stats.get("png", ""),
        f"L{row}": stats.get("foreign", ""),
        f"M{row}": "",
        f"N{row}": stats.get("fee_total", ""),
        f"O{row}": note,
        f"P{row}": source_system,
    }
    return _write_cells(sheet, values, actor=actor)


def _clear_t3_category(sheet, row, note, source_system, actor=None):
    values = {
        f"B{row}": "",
        f"C{row}": "",
        f"D{row}": "",
        f"G{row}": "",
        f"H{row}": "",
        f"I{row}": "",
        f"K{row}": "",
        f"L{row}": "",
        f"M{row}": "",
        f"N{row}": "",
        f"O{row}": note,
        f"P{row}": source_system,
    }
    return _write_cells(sheet, values, actor=actor)


def _nursing_records(year):
    return list(
        PracticingLicenseRecord.objects.filter(
            record_year=year,
            batch__source_kind__in=NURSING_SOURCE_KINDS,
        )
        .exclude(record_type__in=["payment", "summary"])
        .order_by("source_sheet_name", "source_row", "id")
    )


def _medical_records(year):
    return list(
        PracticingLicenseRecord.objects.filter(
            record_year=year,
            batch__source_kind__in=MEDICAL_SOURCE_KINDS,
        )
        .exclude(record_type__in=["payment", "summary"])
        .order_by("source_sheet_name", "source_row", "id")
    )


def _populate_nursing_council_register(workbook, year, actor=None):
    sheet = workbook.sheets.get(source_sheet_name="T3_COUNCIL_REGISTER")
    changed = _write_cells(
        sheet,
        {
            "D10": "Nursing Council of Papua New Guinea",
            "D11": f"{year} database records only",
        },
        actor=actor,
    )
    grouped = defaultdict(list)
    for record in _nursing_records(year):
        group = _nursing_category(record)
        if group:
            grouped[group].append(record)

    source_system = f"Live database {year}: ndata_workbook + nursing_license_workbook"
    note = (
        f"Auto-populated from verified {year} imported registry rows only. "
        "Blank primary-qualification-country fields mean the source data did not capture that field."
    )
    row_map = {
        "registered_nurse": 22,
        "auxiliary_nurse": 23,
        "midwife": 24,
        "specialist_nurse": 25,
        "chw": 26,
    }
    summary = {}
    for group, row in row_map.items():
        stats = _stats_from_records(grouped.get(group, []))
        summary[group] = stats
        changed += _write_t3_category(sheet, row, stats, note, source_system, actor=actor)

    changed += _clear_t3_category(
        sheet,
        27,
        f"No verified {year} Nursing Council Health Extension Officer register rows are present in the database.",
        source_system,
        actor=actor,
    )

    trend_note = f"{year} counts are available; earlier trend years are not auto-filled by this 2026-only population."
    changed += _write_cells(
        sheet,
        {
            "F43": summary["registered_nurse"]["registered"] + summary["specialist_nurse"]["registered"] + summary["auxiliary_nurse"]["registered"],
            "F44": summary["midwife"]["registered"],
            "F45": summary["chw"]["registered"],
            "I43": trend_note,
            "I44": trend_note,
            "I45": trend_note,
            "I46": "No verified 2026 HEO register rows in Nursing Council source.",
        },
        actor=actor,
    )
    return changed, summary


def _medical_doctor_stats(year):
    doctors = list(MedicalDoctor.objects.filter(date_issued__year=year).order_by("id"))
    grouped = {
        "generalist": [],
        "specialist": [],
        "resident": [],
        "img": [],
    }
    for doctor in doctors:
        specialty = clean_cell_value(doctor.specialty).lower()
        applicant_type = clean_cell_value(doctor.applicant_type).lower()
        if applicant_type == "overseas":
            grouped["img"].append(doctor)
        elif specialty:
            grouped["specialist"].append(doctor)
        else:
            grouped["generalist"].append(doctor)

    def stats(items):
        gender_counts = Counter(_gender_bucket(item.gender) for item in items)
        nationality_counts = Counter(_is_png_national(item.nationality) for item in items)
        return {
            "registered": len(items),
            "active": len(items),
            "practising": "",
            "male": gender_counts["male"],
            "female": gender_counts["female"],
            "unknown_sex": gender_counts["unknown"],
            "png": nationality_counts[True],
            "foreign": nationality_counts[False],
            "fee_total": None,
        }

    return {key: stats(value) for key, value in grouped.items()}


def _populate_medical_council_register(workbook, year, actor=None):
    sheet = workbook.sheets.get(source_sheet_name="T3_COUNCIL_REGISTER")
    medical_records = _medical_records(year)
    eho_count = len(_dedup([record for record in medical_records if "environmental" in clean_cell_value(record.category).lower()]))
    changed = _write_cells(
        sheet,
        {
            "D10": "Medical Board of Papua New Guinea",
            "D11": f"{year} database records only",
        },
        actor=actor,
    )
    source_system = f"Live database {year}: medical_board_workbook"
    stats_by_group = _medical_doctor_stats(year)
    row_map = {
        "generalist": 16,
        "specialist": 17,
        "resident": 18,
        "img": 19,
    }
    for group, row in row_map.items():
        stats = stats_by_group[group]
        if stats["registered"]:
            changed += _write_t3_category(
                sheet,
                row,
                stats,
                f"Auto-populated from MedicalDoctor records with date_issued in {year}. Practising certificate field is blank because no verified ATP source is linked.",
                source_system,
                actor=actor,
            )
        else:
            changed += _clear_t3_category(
                sheet,
                row,
                f"No verified {year} MedicalDoctor rows are present for this NHWA doctor category. {eho_count} verified Environmental Health Officer row(s) exist in the Medical Board source but are not mapped to doctor categories.",
                source_system,
                actor=actor,
            )
    return changed, {"medical_doctor": stats_by_group, "environmental_health_officers": eho_count}


def _qualification_group(qualification):
    text = " ".join(
        clean_cell_value(value).lower()
        for value in [
            qualification.qualification_name,
            qualification.program_completed,
            qualification.qualification_type,
        ]
    )
    if "midwife" in text or "midwifery" in text:
        return "midwife"
    if "nursing" in text or "nurse" in text:
        return "nursing_diploma"
    if "medical" in text or "mbbs" in text or "mbchb" in text:
        return "medical_generalist"
    return ""


def _populate_training_school(workbook, year, actor=None):
    sheet = workbook.sheets.get(source_sheet_name="T2_TRAINING_SCHOOL")
    changed = _write_cells(
        sheet,
        {
            "A6": "Papua New Guinea",
            "D6": str(year),
            "G6": "Live database qualification records",
            "K6": "System Admin",
            "O6": date.today().isoformat(),
        },
        actor=actor,
    )
    rows = {
        "medical_generalist": 13,
        "nursing_diploma": 18,
        "midwife": 21,
    }
    grouped = defaultdict(list)
    for qualification in Qualification.objects.filter(completion_year=year).select_related("content_type", "institution"):
        group = _qualification_group(qualification)
        if not group:
            continue
        if workbook.office_scope == "medical" and group != "medical_generalist":
            continue
        if workbook.office_scope == "nursing" and group == "medical_generalist":
            continue
        grouped[group].append(qualification)

    summary = {}
    for group, row in rows.items():
        qualifications = grouped.get(group, [])
        if workbook.office_scope == "medical" and group != "medical_generalist":
            continue
        if workbook.office_scope == "nursing" and group == "medical_generalist":
            continue
        people = {}
        institutions = Counter()
        genders = Counter()
        for qualification in qualifications:
            key = f"{qualification.content_type_id}:{qualification.object_id}:{qualification.qualification_name}:{qualification.institution_name}"
            people.setdefault(key, qualification)
            institution = qualification.institution_name or (qualification.institution.name if qualification.institution else "")
            if institution:
                institutions[institution] += 1
            professional = qualification.professional
            genders[_gender_bucket(getattr(professional, "gender", ""))] += 1
        total = len(people)
        summary[group] = total
        changed += _write_cells(
            sheet,
            {
                f"B{row}": "; ".join(name for name, _count in institutions.most_common(4)),
                f"C{row}": total if total else "",
                f"D{row}": genders["male"] if total else "",
                f"E{row}": genders["female"] if total else "",
                f"K{row}": "",
                f"L{row}": (
                    f"{year} completion_year records only; accreditation and capacity not captured in qualification table."
                    if total
                    else f"No verified {year} completion_year records for this programme in the database."
                ),
            },
            actor=actor,
        )
    return changed, summary


def _populate_data_quality_checklist(workbook, year, actor=None):
    sheet = workbook.sheets.get(source_sheet_name="DATA_QUALITY_CHECKLIST")
    today = date.today().isoformat()
    values = {
        "D13": "In Progress",
        "F13": today,
        "G13": f"Auto-check used {year} qualification completion records only; manual school validation still required.",
        "D18": "In Progress",
        "F18": today,
        "G18": f"Council register sheet populated from {year} database records only; registrar review required before NHWA submission.",
        "D19": "Not Complete",
        "F19": today,
        "G19": "Historical trend cells are not auto-filled by the 2026-only population.",
        "D20": "Not Captured",
        "F20": today,
        "G20": "Country of primary qualification is not present in the verified 2026 source rows.",
        "D25": "In Progress",
        "F25": today,
        "G25": "Province/institution/date fields are populated where the database has verified scope metadata.",
        "D27": "Completed",
        "F27": today,
        "G27": f"All auto-populated values are labelled as {year} database records only.",
    }
    return _write_cells(sheet, values, actor=actor)


@transaction.atomic
def populate_workbooks_from_2026_registry(actor=None, year=2026, scopes=None):
    scopes = scopes or ("nursing", "medical")
    result = {}
    for workbook in NHWAWebWorkbook.objects.filter(office_scope__in=scopes).prefetch_related("sheets"):
        workbook.reporting_year = year
        workbook.save(update_fields=["reporting_year", "updated_at"])
        changed = 0
        detail = {}
        if workbook.office_scope == "nursing":
            sheet_changed, detail["council_register"] = _populate_nursing_council_register(workbook, year, actor=actor)
            changed += sheet_changed
        elif workbook.office_scope == "medical":
            sheet_changed, detail["council_register"] = _populate_medical_council_register(workbook, year, actor=actor)
            changed += sheet_changed
        sheet_changed, detail["training"] = _populate_training_school(workbook, year, actor=actor)
        changed += sheet_changed
        changed += _populate_data_quality_checklist(workbook, year, actor=actor)
        NHWAWorkbookAuditEvent.objects.create(
            workbook=workbook,
            actor=actor,
            action="CELL_UPDATED",
            details={
                "population_source": "database",
                "population_year": year,
                "changed_cells": changed,
                "scope": workbook.office_scope,
                "detail": _json_safe(detail),
                "populated_at": timezone.now().isoformat(),
            },
        )
        result[workbook.office_scope] = {
            "changed_cells": changed,
            "detail": detail,
        }
    return result
