# Data Cleansing and Import Alignment Plan

Project: The National Department Of Health Regulatory Bodies Nursing Council & The Medical Board Online Workforce System

Date: 07 May 2026

## 1. Purpose

This document explains how existing paper records, spreadsheets, historical registers, ATP workbooks, N-DATA files, payment rows, qualifications, facilities, institutions, and practitioner profiles must be cleaned and aligned with the current platform.

The goal is not to delete historical data. The goal is to protect the live registry by separating raw source rows from verified live practitioner records.

The safe data flow is:

```text
Raw paper record or spreadsheet
  -> scan/OCR or workbook upload
  -> import staging/history rows
  -> validation and duplicate checks
  -> missing-data review
  -> staff correction
  -> registrar approval where required
  -> live practitioner/licence/employment/receipt update
  -> dashboard/report update
```

## 2. Current Database Snapshot

Live snapshot checked on 07 May 2026:

| Area | Current count |
|---|---:|
| Registered Nurses | 13,493 |
| Midwives | 2,112 |
| Nurse Aides | 800 |
| Graduands / Health Students | 7,624 |
| Community Health Workers | 11,562 |
| Medical Doctors | 0 |
| Applications | 13,843 |
| Imported licence/history rows | 96,806 |
| Receipts | 11,340 |
| Missing-data review items | 79,519 |
| Employment records | 0 |
| Professional document uploads | 0 |
| Qualification records | 25,376 |
| Repository folders | 24 |
| Repository documents | 0 |
| Pending operational access requests | 1 |

## 3. Important Reporting Rule

Always explain the difference between people, rows, receipts, and source files.

| Type | Meaning |
|---|---|
| Live registry people count | Unique people stored in the main practitioner tables. This is used for current workforce totals. |
| Imported licence/history rows | Operational or historical rows. One person can appear many times because of renewals, payments, workforce listings, or licence events. |
| Receipt/payment rows | Money transaction records. These must never be counted as people. |
| Current-year ATP rows | Current Authority To Practice records. These are important for recent workforce and payment tracking but still require matching and validation. |
| Manual receipts | Receipts recorded directly in the live system. |
| Spreadsheet receipts | Receipts imported from payment spreadsheets. |
| Missing-data review items | Records requiring staff correction before statistics can be fully trusted. |

## 4. Main Data Gaps

### Professional Records

| Record group | Major gaps |
|---|---|
| Registered Nurses | Missing gender, date of birth, practitioner number, province, and licence expiry information in many legacy records. |
| Midwives | Missing gender, date of birth, practitioner number, and province in part of the dataset. |
| Nurse Aides | Missing gender, date of birth, practitioner number, email, and phone in part of the dataset. |
| Graduands | Most legacy graduand rows need gender, date of birth, practitioner number, and province completion. |
| CHWs | CHW data is still being updated and must remain in the Medical Board/CHW scope, not Nursing Council scope. |

### Employment

Employment records are currently empty. This is the biggest workforce-planning gap.

The employed/unemployed dashboard cannot be treated as complete until renewals, ATP imports, or staff data entry populate:

- Employment status.
- Employer.
- Facility/workplace.
- Province.
- District where available.
- Position title.
- Workforce function.
- Sector: government, church, private, NGO, or other.
- Start date where available.

### Qualifications

Qualification records exist, but many still need:

- Linked institution.
- Standard institution name.
- Completion year.
- Completed date.
- Professional category mapping.

### Documents

Legacy professional document uploads are currently not attached in the live document tables. New evidence should be captured through the document/checklist/repository process going forward.

Documents should be stored with:

- Office scope.
- Document type.
- Related person/application where applicable.
- Metadata.
- Source notes.
- Version.
- Audit trail.

## 5. Source Files To Align

Current and recent source files include:

- `2026 Current ATP-DATA Statistics & Tracking latest.xlsx`
- `YEAR 2026 FULL REGISTRATION RECORD.(1).xlsx`
- `CHW 1985-2026 DATABASE CURRENTLY UPDATING.xlsx`
- `2026 Current N-DATA Statistics & Tracking - SECTIONS (Autosaved).xlsx`

The ATP workbook is the current priority source for:

- Current Authority To Practice.
- Workplace.
- Sector.
- Payment.
- Receipt references.
- Recent 2026 status.

## 6. Cleansing Priority 1: Identity Matching

Clean identity and matching fields first because they prevent duplicate records.

Required matching fields:

- First name.
- Surname.
- Registration number.
- Practitioner number.
- Date of birth where available.
- Gender.
- Professional category.
- Source file, sheet, and row.

Matching order:

1. Match by registration number.
2. If missing, match by practitioner number.
3. If both are missing, match by name, date of birth, institution, province, workplace, and source row.
4. If uncertain, send the record to duplicate review.

Rules:

- Do not create a new live practitioner record when a likely match already exists.
- Do not merge records just because names are similar.
- Do not overwrite verified values with blank imported values.
- Keep old source rows for audit and traceability.

## 7. Cleansing Priority 2: Licence and Date Accuracy

Clean:

- Issue date.
- Payment date.
- Expiry date.
- Licence year.
- Record type.
- Licence category.
- Provisional/full/temporary/renewal status.

Flag date errors such as:

- Future dates beyond the current reporting year unless officially valid.
- Year 2050 or similar accidental spreadsheet conversion errors.
- Payment dates earlier than reasonable source period.
- Expiry date before issue date.
- Temporary licence without start or end date.

Rules:

- Provisional licence expiry should follow the applicable Nursing Council rule, normally 6 months where configured.
- Annual practising licence/ATP should map to the correct year.
- Temporary licence must have start and end date.
- Historical rows stay historical unless staff confirms they should update the live profile.

## 8. Cleansing Priority 3: Employment and Workplace

Employment is required for meaningful workforce planning.

For employed practitioners, capture:

- Employment status.
- Employer name.
- Facility/workplace name.
- Province.
- District where available.
- Position title.
- Workforce function.
- Employment sector.
- Start date where available.

For unemployed practitioners, capture:

- Unemployment reason.
- Province of residence.
- Availability for deployment.

Sector categories should be standardised as:

- Government.
- Church.
- Private.
- NGO.
- Overseas.
- Other / unknown.

## 9. Cleansing Priority 4: Institutions and Facilities

Training institutions and health facilities must not be mixed.

Rules:

- Verified Nursing Council training schools must be counted separately from all general institutions and facilities.
- Overseas institutions must be separated from PNG institutions.
- Government institutions must be separated from church/private/non-government institutions.
- Facilities/workplaces must not inflate the official Nursing Council school count.
- Facility totals should explain whether they include hospitals, clinics, overseas workplaces, imported workplace names, or unverified raw source values.

Recommended reference categories:

- Verified Nursing Council training institution.
- PNG health facility.
- Overseas institution.
- Overseas facility/workplace.
- Government institution/facility.
- Church institution/facility.
- Private institution/facility.
- Unknown or unverified source value.

## 10. Cleansing Priority 5: Receipts and Finance

Receipt records must be separated by regulatory body.

Rules:

- Nursing Council receipts must feed only Nursing Council finance reports.
- Medical Board receipts must feed only Medical Board finance reports.
- Manual receipts must be shown separately from spreadsheet receipts.
- Spreadsheet receipt row totals must be reported as money totals, not row counts, unless the report clearly labels them as row counts.
- Exported financial reports must show office scope, exporting user, and timestamp.
- Suspicious receipt dates, such as 2050, must be flagged for correction before management reporting.

## 11. Import Alignment Rules

Every import must follow a controlled process:

1. Upload workbook or scanned source.
2. Parse rows into staging/history records.
3. Preserve source file name, sheet name, row number, import batch, and import timestamp.
4. Normalize names, dates, gender, province, institution, workplace, category, and fee values.
5. Validate required fields.
6. Detect duplicate people, duplicate registration numbers, duplicate practitioner numbers, and duplicate receipts.
7. Show preview of clean rows, warnings, and rejected rows.
8. Commit only valid rows.
9. Send incomplete rows to missing-data review.
10. Keep uncertain rows out of live practitioner totals until reviewed.
11. Update live registry only after matching and approval rules are satisfied.

## 12. Paper Record To Electronic Record Workflow

For raw paper files:

1. Sort paper record by person and application type.
2. Scan the record clearly.
3. Save using a standard filename with name, registration number where known, document type, and year.
4. Upload into the correct office-scoped repository or application checklist.
5. Assign document type and metadata.
6. Run OCR where appropriate.
7. Review OCR text for registration number, receipt number, ATP number, and licence number.
8. Match the document to the existing practitioner/application.
9. If no safe match exists, create a data-quality issue.
10. Do not mark the record as verified until staff confirms source evidence.

## 13. Duplicate Review Rules

Send records to duplicate review when:

- Same registration number appears on more than one person.
- Same practitioner number appears on more than one person.
- Same name and similar date of birth appear in multiple records.
- Same person appears across full registration, renewal, ATP, workforce listing, and payment sheets.
- Same receipt reference appears with conflicting amount or date.

Resolve duplicates by:

- Comparing source file, sheet, and row.
- Comparing registration/practitioner number.
- Comparing date of birth, institution, province, and workplace.
- Preserving the strongest verified record.
- Keeping historical rows linked as history rather than deleting them.
- Recording the decision in review notes or audit history.

## 14. What Must Not Be Done

Avoid these unsafe actions:

- Do not delete historical import rows just because they are incomplete.
- Do not overwrite live verified data with blank spreadsheet values.
- Do not create a new person when registration number or practitioner number already matches an existing profile.
- Do not mix Nursing Council and Medical Board imports.
- Do not count imported payment rows as practitioners.
- Do not count imported licence rows as unique practitioners without deduplication.
- Do not use unverified facility/workplace names as official Nursing Council school counts.
- Do not publish reports before major date errors and duplicate candidates are reviewed.

## 15. Clean Data Acceptance Criteria

A record is ready for live registry use when:

- Person is matched or safely created.
- Office scope is correct.
- Professional category is correct.
- Registration number or practitioner number is present, or officially marked unknown.
- Licence type and licence period are clear.
- Payment is verified or waived if required.
- Employment status is captured for renewals or ATP updates.
- Institution and facility values are normalized.
- Missing-data review is resolved or formally deferred.
- Duplicate candidates are resolved or formally linked.
- Source file, sheet, and row are traceable.
- Status history or audit notes explain manual corrections.

## 16. Recommended Cleansing Schedule

### Week 1: Core Identity

- Resolve duplicate registration/practitioner numbers.
- Normalize names.
- Normalize province spelling.
- Fill missing surname/first name where source rows contain full names.

### Week 2: Licence and ATP

- Validate 2026 ATP workbook rows.
- Correct future date issues.
- Map ATP records to live practitioner profiles.
- Separate current ATP rows from historical imported rows.

### Week 3: Employment and Workplace

- Populate employment status from ATP and renewal records.
- Standardize workplace, facility, province, and sector.
- Separate government, church, private, NGO, overseas, and unknown workplaces.

### Week 4: Institutions and Qualifications

- Standardize institution names.
- Mark verified Nursing Council schools separately from facilities and overseas institutions.
- Fill graduation/completion year where the source contains it.

### Week 5: Documents and Evidence

- Attach scanned evidence to current applications and high-priority legacy records.
- Use repository metadata and checklist links.
- Record document source and version.

### Week 6: Management Reporting

- Run missing-data audit.
- Run duplicate audit.
- Generate corrected monthly analytics.
- Explain live counts, source dates, historical rows, receipt totals, and remaining data-quality limitations.

## 17. Management Reporting Standard

Every report should include:

- Report date.
- Exporting user.
- Office scope.
- Source tables.
- Latest live update.
- Latest source import.
- People count.
- Historical/imported row count.
- Receipt money total.
- Missing-data limitations.
- Duplicate-review limitations.
- Any major correction notes, such as removed future date errors or separated institution/facility counts.
