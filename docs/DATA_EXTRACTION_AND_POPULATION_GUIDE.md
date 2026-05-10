# Data Extraction and Population Guide

Project: The National Department Of Health Regulatory Bodies Nursing Council & The Medical Board Online Workforce System

Last updated: 07 May 2026

## 1. Purpose

This guide explains how source data should be extracted, imported, reviewed, and populated into the current platform without damaging live registry statistics.

The current system supports:

- Nursing Council and Medical Board separated workspaces.
- Reference data setup.
- Bulk spreadsheet imports.
- ATP/N-DATA/Medical Board workbook handling.
- Missing-data review.
- Duplicate review.
- Records Hub review.
- OpenKM-style document repository.
- Monthly/yearly reporting.

## 2. Safe Population Flow

Use this flow for every new data source:

```text
Source file or paper record
  -> extract/scan
  -> import staging or historical rows
  -> validate fields
  -> detect duplicates
  -> create missing-data review items
  -> staff correction
  -> registrar approval where required
  -> live registry update
  -> dashboard/report update
```

Do not import raw files directly into final live counts without validation.

## 3. Bootstrap Required Reference Data

Run:

```powershell
.\.venv\Scripts\python.exe manage.py bootstrap_reference_data
.\.venv\Scripts\python.exe manage.py bootstrap_document_repository
.\.venv\Scripts\python.exe manage.py bootstrap_nursing_council_workflows
```

These commands prepare:

- Cadres.
- Document types.
- Training institutions.
- Provinces and locations.
- Nursing Council pathways/forms/checklists.
- Repository root folders for General Registry, Nursing Council, and Medical Board.

## 4. Current Import Commands

Use the command that matches the source type:

```powershell
.\.venv\Scripts\python.exe manage.py import_atp_workbook --path "path\to\2026 Current ATP-DATA Statistics & Tracking latest.xlsx"
.\.venv\Scripts\python.exe manage.py import_ndata_workbook --path "path\to\nursing-ndata.xlsx"
.\.venv\Scripts\python.exe manage.py import_medical_board_workbook --path "path\to\medical-board.xlsx"
.\.venv\Scripts\python.exe manage.py import_full_registrations --path "path\to\full-registration.xlsx"
.\.venv\Scripts\python.exe manage.py import_provisional_licenses --path "path\to\provisional.xlsx"
.\.venv\Scripts\python.exe manage.py import_provisional_graduands --path "path\to\graduands.xlsx"
.\.venv\Scripts\python.exe manage.py import_workforce_files --path "path\to\folder"
```

Use only the command intended for the dataset. Do not use a Nursing Council import command for Medical Board data.

## 5. Records Hub

Authorised users can review populated records from:

```text
/records/
```

Use filters and search on large tables such as Applications and Receipts. Restricted users may not see Records Hub if their role does not allow CRUD or data-quality review.

## 6. CSV/Excel Folder Imports

For generic workforce file imports, place files in one folder and name each file using the expected model slug, for example:

- `nursingprofessional.csv`
- `midwife.xlsx`
- `nurseaide.xlsx`
- `healthstudent.csv`
- `location.xlsx`

Then run:

```powershell
.\.venv\Scripts\python.exe manage.py import_workforce_files --path notebooks\csv_templates
```

## 7. Required Source Tracking

Every imported row should preserve:

- Source file.
- Source sheet.
- Source row.
- Import batch.
- Imported by user or command context.
- Import timestamp.
- Office scope.
- Record type.

This is needed so staff can explain where management statistics came from.

## 8. Data Quality After Import

After import, run:

```powershell
.\.venv\Scripts\python.exe manage.py audit_missing_data --audit-import-rows --latest-batch
.\.venv\Scripts\python.exe manage.py audit_duplicate_records
```

Review the results before generating reports.

## 9. Date and Finance Checks

Flag suspicious values before publishing:

- Future years such as 2050.
- Expiry date before issue date.
- Payment date outside the source period.
- Missing receipt number.
- Missing amount.
- Duplicate receipt reference.
- Spreadsheet receipt totals mixed with manual receipt totals.

Finance must remain separated:

- Nursing Council finance: `/dashboard/reports/financial/?office=nursing`
- Medical Board finance: `/dashboard/reports/financial/?office=medical`

## 10. Institution and Facility Checks

Do not mix training institutions and health facilities.

Separate:

- Verified Nursing Council training schools.
- PNG health facilities.
- Overseas institutions.
- Overseas workplaces.
- Government facilities/institutions.
- Church facilities/institutions.
- Private facilities/institutions.
- Unknown or unverified source values.

## 11. OpenKM-Style Document Population

For scanned paper evidence:

1. Scan the document.
2. Upload it to the correct office-scoped repository or checklist.
3. Add metadata.
4. Link it to the practitioner, application, receipt, or source row where possible.
5. Use OCR/extracted text to support search.
6. Keep document versions instead of replacing evidence silently.

Open repository search:

```text
/documents/search/
```

## 12. Reporting After Population

Reports must explain:

- Live people counts.
- Imported row counts.
- Receipt money totals.
- Source file and source month.
- Latest completed import.
- Latest live update.
- Remaining missing-data issues.
- Remaining duplicate-review issues.

Use the monthly analytics and financial forecast pages only after data-quality checks have been reviewed.
