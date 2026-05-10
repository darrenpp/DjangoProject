# OpenKM-Style Full Platform User Guide

Project: The National Department Of Health Regulatory Bodies Nursing Council & The Medical Board Online Workforce System

Date: 07 May 2026

## 1. What This Means In Simple Terms

OpenKM is a document management system. In this platform, the useful OpenKM-style functions have been built into the existing regulatory system so staff can manage official evidence and records without leaving the workforce platform.

This means the system can now support:

- Storing official documents.
- Grouping documents by Nursing Council, Medical Board, or General Registry.
- Capturing metadata.
- Keeping document versions.
- Searching document information and OCR/extracted text.
- Checking duplicate uploaded files.
- Restricting documents by role and office.
- Tracking document activity through audit events.
- Connecting evidence to practitioner, application, receipt, and reporting workflows.

## 2. Where To Access It

Authorised staff can open:

```text
/documents/search/
```

System Admin can also manage repository setup through:

```text
/admin/
```

Only System Admin should access the admin backend. Registrar and staff users should use normal dashboard and repository screens unless System Admin work is required.

## 3. Repository Structure

The repository has three root office scopes:

| Repository area | Use |
|---|---|
| General Registry | Shared or general NDOH regulatory documents that are not private to one body. |
| Nursing Council Repository | Nursing Council applications, evidence, Nursing Council receipts, Nursing Council policies, Nursing Council workflow documents, and Nursing Council source records. |
| Medical Board Repository | Medical Board applications, evidence, Medical Board receipts, CHW/doctor records, Medical Board policies, and Medical Board source records. |

Do not store Nursing Council private documents under Medical Board scope. Do not store Medical Board private documents under Nursing Council scope.

## 4. Recommended Folder Layout

The exact folder names can be adjusted by System Admin, but this structure is recommended.

For Nursing Council:

- Nursing Council Repository / Applications
- Nursing Council Repository / Receipts
- Nursing Council Repository / Qualifications
- Nursing Council Repository / Competency Evidence
- Nursing Council Repository / Overseas Applications
- Nursing Council Repository / Temporary Licences
- Nursing Council Repository / Renewals
- Nursing Council Repository / Deceased Notifications
- Nursing Council Repository / Policies and Standards
- Nursing Council Repository / Historical Imports
- Nursing Council Repository / Data Cleansing Evidence

For Medical Board:

- Medical Board Repository / Applications
- Medical Board Repository / Receipts
- Medical Board Repository / CHW Records
- Medical Board Repository / Doctor Records
- Medical Board Repository / Policies and Standards
- Medical Board Repository / Historical Imports
- Medical Board Repository / Data Cleansing Evidence

## 5. Document Metadata Standard

Every uploaded official document should have enough metadata for staff to find it later.

Recommended metadata:

| Metadata field | Example |
|---|---|
| Office scope | nursing |
| Document type | Treasury receipt |
| Practitioner name | Maria John |
| Registration number | RN-12345 |
| Practitioner number | PN-12345 |
| Application reference | APP-2026-0001 |
| Receipt number | G 4296 |
| Licence year | 2026 |
| Institution | Pacific Adventist University |
| Facility/workplace | Port Moresby General Hospital |
| Province | National Capital District |
| Source file | 2026 Current ATP-DATA Statistics & Tracking latest.xlsx |
| Source sheet | April 2026 |
| Source row | 152 |
| Confidentiality | Internal |

Do not rely only on the file name. Metadata is what makes reports, search, auditing, and cleansing easier later.

## 6. How To Upload A Paper Record

Use this process for scanned paper files:

1. Confirm which office owns the record: Nursing Council, Medical Board, or General Registry.
2. Scan the paper record clearly.
3. Save with a meaningful filename.
4. Upload the document through the repository or the relevant application/document checklist process.
5. Choose the correct folder.
6. Set the document type.
7. Add metadata.
8. Link it to the application, practitioner, receipt, or source record if available.
9. Check OCR/extracted text if OCR is used.
10. Confirm the document appears in search.

Example filename:

```text
NC_RECEIPT_MARIA_JOHN_RN12345_2026.pdf
```

## 7. Version Control

Document versions allow staff to keep a record of file changes.

Use a new version when:

- A clearer scan replaces a blurry scan.
- A certified copy replaces an uncertified copy.
- A corrected document replaces an earlier document.
- A translated copy is added.
- A missing page is added.

Do not delete the old version unless System Admin confirms it is safe. The old version helps prove what was received and when it was corrected.

## 8. Searching For Documents

Open:

```text
/documents/search/
```

Search can match:

- Title.
- Description.
- Metadata values.
- Original filename.
- Extracted/OCR text.

Good search terms include:

- Registration number.
- Practitioner number.
- Receipt number.
- ATP number.
- Licence number.
- Applicant surname.
- Institution name.
- Facility name.
- Source workbook name.

If a document cannot be found:

- Check whether it was uploaded under the correct office scope.
- Try registration number instead of name.
- Try receipt number or practitioner number.
- Ask System Admin to confirm folder and permission settings.

## 9. Duplicate Document Checks

The platform calculates a file checksum for uploaded versions. If two files have the same checksum, they are likely duplicate copies of the exact same file.

Use duplicate checks to:

- Avoid storing the same scan many times.
- Identify repeated receipt uploads.
- Confirm whether two applications are using the same evidence.
- Support duplicate-review investigation.

A duplicate file does not always mean fraud. It may mean the same document was uploaded twice by mistake. Staff must review the context before making a decision.

## 10. Access and Privacy

Access is controlled by role and office scope.

Nursing Council staff should see Nursing Council repository material only. Medical Board staff should see Medical Board repository material only. System Admin can manage configuration but should not use admin access to bypass normal business approval processes.

Public users and professionals must not access private repository documents for other people.

Sensitive documents include:

- Date of birth evidence.
- Passport.
- Police clearance.
- Medical report.
- Academic transcript.
- Receipt image.
- Internal review notes.
- Disciplinary or investigation material.

These must not be exposed through public register search or general dashboards.

## 11. Audit Trail

The document system records audit events for sensitive actions.

Audit event examples:

- Created.
- Uploaded.
- Viewed.
- Downloaded.
- Metadata updated.
- Status changed.
- Permission changed.
- Linked to record.
- OCR processed.
- Access denied.

Audit history helps answer:

- Who uploaded the file?
- When was the file uploaded?
- Was the file downloaded?
- Was metadata changed?
- Was access denied?
- Which document version is current?

## 12. How It Connects To Applications

Documents should support the application pathway.

Example Nursing Council flow:

```text
Applicant submits pathway
  -> system generates checklist
  -> applicant/staff uploads required documents
  -> staff verifies documents
  -> payment is verified
  -> competency is checked where required
  -> registrar approves or rejects
  -> licence/register is updated
  -> reports include the updated record
```

Documents should not sit separately without a business purpose. Where possible, link them to:

- Application.
- Practitioner profile.
- Receipt.
- Qualification.
- Employer verification.
- Deceased notification.
- Import batch.
- Data-quality issue.

## 13. How It Supports Data Cleansing

The repository helps data cleansing by keeping evidence visible.

Use repository documents to confirm:

- Correct spelling of names.
- Registration number.
- Practitioner number.
- Date of birth.
- Gender.
- Qualification.
- Institution.
- Receipt number.
- Payment date.
- Licence year.
- Workplace.
- Province.

When source data conflicts, the stronger evidence should be noted in the data-quality review before updating live records.

## 14. How It Supports Financial Transparency

Financial records should be stored and reported by office scope.

Nursing Council finance and Medical Board finance must stay separate.

For receipts:

- Store receipt evidence with correct office scope.
- Capture receipt number.
- Capture payment date.
- Capture amount.
- Capture source file/sheet/row for spreadsheet imports.
- Flag future date errors.
- Separate manual receipt totals from spreadsheet-imported receipt totals.

Financial exports should show:

- Office scope.
- Generated date/time.
- Exporting user.
- Manual receipt total.
- Spreadsheet receipt total.
- Combined total.
- Monthly breakdown.
- Yearly breakdown.
- Forecast basis.

## 15. How It Supports Management Reporting

The repository improves trust in reports because management can ask where figures came from.

Reports should explain:

- Source table.
- Source workbook.
- Source month.
- Latest import date.
- Latest live update.
- Whether a count is people, rows, receipts, or money.
- Remaining missing-data issues.
- Remaining duplicate-review issues.

Example:

```text
Midwife total comes from the live Midwife table.
Imported row totals come from historical licence/payment/workforce rows.
The two numbers are not the same because one person may appear in several imported rows over time.
```

## 16. Role-Based Use Of OpenKM-Style Features

| Role | Repository use |
|---|---|
| System Admin | Configure folders, permissions, repository setup, and admin management. |
| Nursing Council Registrar | Search and review Nursing Council evidence linked to Nursing Council decisions. |
| Medical Board Registrar | Search and review Medical Board evidence linked to Medical Board decisions. |
| Reviewer | Search/review assigned evidence only after operational approval. |
| Data Quality Officer | Use evidence to resolve missing data and duplicate review items within assigned scope. |
| Finance Officer | Review finance evidence and reports only through read-only finance views where permitted. |
| Public/professional users | No access to private repository documents unless the document belongs to their own permitted workflow. |

## 17. Common Mistakes To Avoid

- Uploading Nursing Council files into Medical Board folders.
- Uploading Medical Board files into Nursing Council folders.
- Leaving documents without metadata.
- Treating a payment row as a person.
- Treating a facility as a training institution.
- Overwriting verified live data with blank imported spreadsheet values.
- Approving applications before required documents are verified.
- Publishing reports without noting data-quality limitations.
- Letting reviewer users operate without registrar/System Admin approval.

## 18. Staff Checklist Before Management Reporting

Before generating a management report:

- Run missing-data review.
- Run duplicate review.
- Check date errors.
- Confirm finance office scope.
- Confirm latest source import.
- Confirm live table counts.
- Confirm imported row counts separately.
- Confirm receipt money totals separately.
- Confirm document evidence for high-risk corrections.
- Confirm report timestamp and exporting user.

## 19. Current Status

The OpenKM-style repository and records management functions are integrated and ready for controlled use. The live repository now has the General Registry, Nursing Council, and Medical Board folder structures configured, plus staff-facing upload, detail, metadata, versioning, search, OCR linkage, and audited download workflows. Legacy paper evidence still needs to be uploaded and linked by staff.

## 20. Summary

The platform now works as a registration and workforce system with OpenKM-style document management built in. It can store and search evidence, protect records by role and office, track versions, support audits, help data cleansing, support financial transparency, and strengthen management reporting.

The key discipline is this: every important record should have a source, every source should be traceable, and every decision should be connected to evidence.
