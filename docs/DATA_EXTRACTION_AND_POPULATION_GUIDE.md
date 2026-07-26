# Data Extraction and Population Guide

Project: PNG Nursing Council and Medical Board Online Regulatory Workforce Platform

Last updated: 1 June 2026

## 1. Purpose

This guide explains how source data should be extracted, imported, reviewed, and populated into the current platform without damaging live registry statistics.

The current system supports:

- Nursing Council and Medical Board separated workspaces.
- Reference data setup.
- Bulk spreadsheet imports.
- Nursing Council analytics snapshot imports from the cleansed dashboard workbook.
- Catherine cleaned provisional/full-licence and cadre workbook alignment.
- ATP/N-DATA/Medical Board workbook handling.
- Receipt-owner matching and high-value review routing.
- Missing-data review.
- Duplicate review queue with search, sort, pagination, grouped source rows, and review actions.
- Records Hub review with search, sort, pagination, and authorised CRUD actions.
- OpenKM-style document repository.
- NHWA standards/reporting workbooks.
- Mapped institutions/facilities using locally stored verified coordinates.
- Monthly/yearly reporting.

## 2. Safe Population Flow

Use this flow for every new data source:

```text
Source file or paper record
  -> extract/scan
  -> import staging or historical rows
  -> analytics snapshot table where the source is an analytical workbook
  -> validate fields
  -> detect duplicates
  -> create missing-data review items
  -> staff correction
  -> registrar approval where required
  -> live registry update
  -> dashboard/report update
```

Do not import raw files directly into final live counts without validation.

For the Nursing Council analytics workbook, use this separate flow:

```text
PNG_Nursing_Council_Integrated_Dashboard_Model.xlsx
  -> DataImportBatch provenance
  -> NursingAnalyticsSnapshot
  -> NursingLifecycleFact and metric tables
  -> active snapshot flag
  -> dashboard summary and server-side drilldown
```

This flow gives the dashboard accurate analytics from the cleansed workbook but does not create legal practitioner identities. `Person_Group_Key` remains an analytics grouping key only.

## 3. Bootstrap Required Reference Data

Run:

```powershell
.\.venv\Scripts\python.exe manage.py bootstrap_reference_data
.\.venv\Scripts\python.exe manage.py bootstrap_document_repository
.\.venv\Scripts\python.exe manage.py bootstrap_nursing_council_workflows
.\.venv\Scripts\python.exe manage.py bootstrap_nhwa_workbooks
.\.venv\Scripts\python.exe manage.py seed_engagement_platform
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
.\.venv\Scripts\python.exe manage.py import_nursing_analytics_snapshot --path "path\to\PNG_Nursing_Council_Integrated_Dashboard_Model.xlsx" --activate
.\.venv\Scripts\python.exe manage.py import_nursing_catherine_licence_breakdown --licence-path "path\to\PNG_Nursing_Council_Cleaned_Licence_Breakdown.xlsx" --cadre-path "path\to\PNG_Nursing_Council_Cadre_Breakdown.xlsx"
.\.venv\Scripts\python.exe manage.py link_receipts_to_individual_records --review-unmatched
```

Use only the command intended for the dataset. Do not use a Nursing Council import command for Medical Board data.

The current active Nursing Council analytics source is `PNG_Nursing_Council_Integrated_Dashboard_Model.xlsx`, generated on 27 May 2026, with 34,851 lifecycle records, 19,998 clean ATP records, 8,158 clean provisional records, 6,695 clean full-licence records, and an 87.0% data quality health score.

The latest Catherine workbook refresh completed on 29 May 2026 and processed 14,853 of 18,615 rows from `PNG_Nursing_Council_Cleaned_Licence_Breakdown.xlsx` and `PNG_Nursing_Council_Cadre_Breakdown.xlsx`. It should be treated as an analytics/import-alignment refresh unless a later workflow explicitly promotes rows into the legal registry.

## 5. Records Hub

Authorised users can review populated records from:

```text
/records/
```

Use filters and search on large tables such as Applications and Receipts. Restricted users may not see Records Hub if their role does not allow CRUD or data-quality review.

For Nursing Professionals:

```text
/records/nursingprofessional/
```

Authorised registrar users should see search, sorting, page length, pagination, View, Edit, and Add New controls. Use these controls for controlled record maintenance and corrections, not to bypass application review decisions.

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
- File hash where the source command supports it.
- Active snapshot flag where the source is an analytics snapshot.
- Raw payload/source lineage where the row is used for analytics drilldown.

This is needed so staff can explain where management statistics came from.

## 8. Data Quality After Import

After import, run:

```powershell
.\.venv\Scripts\python.exe manage.py audit_missing_data --audit-import-rows --latest-batch
.\.venv\Scripts\python.exe manage.py audit_duplicate_records
.\.venv\Scripts\python.exe manage.py link_receipts_to_individual_records --review-unmatched
```

Review the results before generating reports.

Open the duplicate queue after each duplicate audit:

```text
/dashboard/duplicate-reviews/
```

Use the table functions to search, sort, page through cases, inspect grouped source rows, then mark each case reviewed, merged, or reopened.

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

Receipt-owner matching rules:

- Link only high-confidence receipt matches to applications, practitioner records, analytics facts, or source rows.
- Do not link a receipt on name similarity alone when registration number, practitioner number, source row, amount, or date evidence conflicts.
- Put unlinked, duplicate, suspicious, or high-value receipts into review immediately.
- Keep the original receipt row and matching evidence for audit.

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

For maps, store verified coordinates in `MappedEntity` records. Do not geocode every map page load. Use:

```powershell
.\.venv\Scripts\python.exe manage.py geocode_mapped_entities --limit 100
```

or enter verified coordinates through admin/review screens.

## 11. OpenKM-Style Document Population

For scanned paper evidence:

1. Scan the document.
2. Upload it to the correct office-scoped repository or checklist.
3. Add metadata.
4. Link it to the practitioner, application, receipt, or source row where possible.
5. Use OCR/extracted text to support search.
6. Keep document versions instead of replacing evidence silently.
7. Approve or reject the current version when it becomes controlled evidence.

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
- Active Nursing Council analytics snapshot source and generated date.
- Whether a figure comes from the legal registry, analytics snapshot, workbook import, or NHWA reporting layer.

Use the monthly analytics and financial forecast pages only after data-quality checks have been reviewed.

## 13. NHWA Population Rule

NHWA workbooks are populated from verified platform data for reporting and sign-off:

```text
Registry / Analytics / Finance / Facilities
        -> NHWA workbook cells
        -> review and sign-off
        -> NHWA export/report
```

Do not use NHWA workbook values to overwrite registry records automatically. Uncertain fields should remain editable with audit logs and checklist sign-off.
