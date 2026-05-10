# 03 Data Governance and Data Dictionary

## Core Data Governance Rule

Imported rows are not automatically trusted. They are staged, validated, cleansed, reviewed, approved, then promoted into live registry records.

## Data Lifecycle

```text
Raw paper/spreadsheet/source file
  -> import batch
  -> staged import rows
  -> validation and normalization
  -> missing-data/duplicate review
  -> authorised approval
  -> live registry record
  -> report/dashboard/public-safe output
```

## Source Evidence Requirements

Every imported or corrected record should keep:

- Source file name.
- Source sheet name.
- Source row number where available.
- Import batch.
- Import date.
- Imported by user.
- Data-quality issue notes.
- Reviewer or registrar decision where required.

## Data Dictionary

| Field | Plain meaning | System use | Governance rule |
|---|---|---|---|
| Registration number | The official registration identifier issued by the regulatory body. | Used to match practitioners, public register search, renewals, reports, and duplicate review. | Must be unique within the correct regulatory body unless approved as a historical duplicate exception. |
| Practitioner number | Internal practitioner identifier used to track one person across records. | Used for matching imports, licence rows, applications, and duplicates. | Duplicate practitioner numbers must be blocked or sent to data-quality review. |
| Licence number | Identifier for a specific licence or authority to practise. | Used for renewal, full registration, temporary licence, and practising licence tracking. | Do not create duplicate active licence periods for the same practitioner. |
| ATP | Authority To Practice record or current practising authority data. | Used for current workforce statistics, recent licence tracking, and employment alignment. | ATP data must be imported with source file, date, category, and review status. |
| Qualification | Education, award, certificate, or professional credential. | Supports registration eligibility, pathway decisions, and specialist recognition. | Qualification records should include institution, award title, completion year, and source evidence. |
| Receipt | Payment evidence for application, renewal, registration, or licence. | Used by finance and registrar workflow gating. | Receipt rows must be separated by Nursing Council and Medical Board office scope. |
| Source sheet | Workbook tab or dataset sheet where imported row came from. | Supports traceability and management explanations. | Reports must explain whether a total came from live registry or imported historical rows. |
| Import batch | Group of rows imported together from one source file or workbook. | Used for rollback review, audit, and recent data-source explanation. | Each batch must record source kind, imported date, completed status, and row totals. |
| Province | Provincial location linked to person, workplace, facility, or institution. | Used in geographic distribution and workforce planning. | Must be normalized to approved PNG province names. |
| Facility | Health workplace, hospital, clinic, or employer facility. | Used for employment, workforce distribution, and employer verification. | Facility names must be standardized and classified by sector where possible. |
| Institution | Training school, nursing college, university, or awarding body. | Used for graduand, qualification, and education pipeline reporting. | Nursing Council local training institutions must be separated from overseas institutions and health facilities. |
| Employment status | Whether a practitioner is employed, unemployed, inactive, retired, deceased, or unknown. | Used for workforce planning and renewal validation. | Renewal workflows should require employment status before approval. |
| Employment sector | Public, church, private, NGO, overseas, or unknown workplace category. | Used in workforce-sector reporting. | Must be selected from a controlled list, not free text where avoidable. |
| Professional category | Nurse, midwife, nurse aide, doctor, CHW, allied health, graduand, specialist, etc. | Used for dashboards, role alignment, pathways, and counts. | Must remain inside correct regulatory body scope. |
| Application status | Current stage of a submitted application. | Drives review queues and registrar action. | Every official status change must write status history. |
| Document type | Receipt, qualification, competency, transcript, ID, police clearance, medical report, letter, etc. | Drives checklists and repository metadata. | Required documents must be verified, rejected, waived, or marked pending. |
| Office scope | General, Nursing Council, or Medical Board. | Separates records, receipts, documents, reports, and access. | Cross-office access must be denied unless explicitly authorised. |

## Trusted Versus Untrusted Data

| Data type | Trust level | Required action |
|---|---|---|
| Raw paper records | Untrusted until captured and verified | Scan, index, extract, validate, and attach to source record |
| Spreadsheet imports | Untrusted until reviewed | Stage, normalize, run duplicate/missing-data checks, then approve |
| Live registry records | Operational source of truth | Protect with role checks, audit changes, and reconcile regularly |
| Public register output | Public-safe view only | Expose only name, registration number, category, status, and expiry where policy allows |
| Management reports | Decision-support output | Show source date, live count date, and limitations |

## Data Quality Controls

Minimum checks before promotion to live registry:

- Required identity fields exist.
- Registration/practitioner/licence numbers are valid or flagged.
- Duplicate name plus registration/practitioner/licence number reviewed.
- Date fields are realistic and not future-date errors such as accidental 2050 dates.
- Province, institution, facility, sector, and category are normalized.
- Receipt rows have amount, date, reference, source, and office scope.
- Qualification rows have institution, award, and completion year where available.
- Reviewer notes explain unresolved exceptions.

## Production Data Preparation Command

Use the production data preparation command before handover and after major imports:

```powershell
.\.venv\Scripts\python.exe manage.py prepare_production_data --write-report
```

This runs in dry-run mode by default. It reports what would be normalized without changing the database.

To apply safe non-destructive normalization:

```powershell
.\.venv\Scripts\python.exe manage.py prepare_production_data --apply --skip-audit --write-report
```

The command safely normalizes:

- Leading/trailing spaces.
- Repeated internal spaces.
- Known placeholder values such as `N/A`, `UNKNOWN`, `TBA`, and `-`.
- Province naming where the mapping is obvious.
- Gender values such as `M/F`.
- Email casing.
- Key reference-number casing.

The command does not invent missing facts and does not overwrite suspicious date values. Those remain in missing-data, duplicate-review, or date-issue reports for staff review.

## Management Reporting Rule

Reports must separate:

- Live people counts.
- Imported historical row counts.
- Receipt/payment row counts.
- Current month activity.
- Current year activity.
- Latest source file and source date.
- Cleansing limitations.
