# OpenKM-Style Platform Test Guide

Project: The National Department Of Health Regulatory Bodies Nursing Council & The Medical Board Online Workforce System

Last updated: 07 May 2026

## 1. Purpose

This guide explains how to test the OpenKM-style repository and related platform functions now integrated across the system.

It covers:

- Repository foundation.
- OCR/extracted text and search.
- Document duplicate checks.
- Staff inbox/chat.
- Operational access requests.
- Role privacy.
- Financial scope separation.
- Reporting readiness.

## 2. Repository Foundation Tests

### Confirm root folders

Open the Secure Administration Console as System Admin:

```text
/admin/
```

Check:

```text
Documents > Document folders
```

Expected root folders:

- General Registry.
- Nursing Council Repository.
- Medical Board Repository.

### Create a scoped folder

Create a child folder under Nursing Council Repository, for example:

```text
2026 Incoming Scans
```

Expected result:

- Folder saves successfully.
- Folder remains in Nursing Council scope.

### Create a repository document

Create a document under the test folder.

Expected result:

- Document saves successfully.
- Office scope is correct.
- Status can be draft, active, archived, or superseded.
- Metadata can be stored.

### Add a document version

Upload a sample file as a version.

Expected result:

- Version is created.
- File size is stored.
- Checksum is stored.
- Current-version flag is correct.

## 3. Search and OCR Tests

Open:

```text
/documents/search/
```

Search by:

- Document title.
- Metadata value.
- Original filename.
- Extracted/OCR text if present.
- Receipt number or registration number if included in extracted text.

Expected result:

- System Admin can search all scopes.
- Nursing Council staff see Nursing Council/general documents only.
- Medical Board staff see Medical Board/general documents only.
- Unauthorised users receive restricted access.

## 4. Duplicate Document Test

Upload the same file twice as separate document versions.

Expected result:

- The checksum is the same.
- Repository search can identify duplicate checksum groups.
- Staff can investigate whether the repeated file is acceptable or accidental.

## 5. Staff Inbox and Operational Access Tests

Open:

```text
/notifications/communications/
```

Test:

1. Log in as a restricted reviewer.
2. Open My Profile.
3. Submit an operational access request.
4. Log in as Nursing Council Registrar or System Admin.
5. Open Staff Inbox & Chat.
6. Confirm the request appears.
7. Approve or reject the request.
8. Log back in as the reviewer and confirm access changes according to approval status.

Expected result:

- Request is not lost.
- Request is visible to the correct registrar/System Admin.
- Approval updates the user's operational access status.
- Rejection keeps restricted tools locked.

## 6. Finance Scope Tests

Open:

```text
/dashboard/reports/financial/?office=nursing
/dashboard/reports/financial/?office=medical
```

Expected result:

- Nursing Council finance shows Nursing Council figures only.
- Medical Board finance shows Medical Board figures only.
- Finance Officer can view separated finance pages and Workforce Flow.
- Finance Officer cannot use CRUD functions, registrar approval tools, imports, or admin backend.
- Exports show office scope, timestamp, and exporting user.

## 7. Role Privacy Tests

Check these role rules:

- Nursing Council Registrar cannot see Medical Board private workflow records.
- Medical Board Registrar cannot see Nursing Council private workflow records.
- Reviewer cannot access full operations until approved.
- Public users cannot access private repository documents.
- `/admin/` is System Admin only.
- Public register search returns safe fields only.

## 8. Data-Quality and Reporting Tests

Run:

```powershell
.\.venv\Scripts\python.exe manage.py audit_missing_data --audit-import-rows --latest-batch
.\.venv\Scripts\python.exe manage.py audit_duplicate_records
```

Expected result:

- Missing-data review items are created or updated.
- Duplicate-review candidates are visible for staff review.
- Reports explain live people counts separately from imported row counts.
- Suspicious future dates are flagged for review.

## 9. Automated Test Commands

Run:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test apps.documents.tests --keepdb
.\.venv\Scripts\python.exe manage.py test apps.accounts.tests apps.dashboard.tests apps.workforce.tests apps.notifications.tests --keepdb
```

Expected result:

- Commands complete without errors.

## 10. Key Routes To Smoke Test

- `/dashboard/`
- `/dashboard/nursing-council/`
- `/dashboard/medical-board/`
- `/dashboard/reports/financial/?office=nursing`
- `/dashboard/reports/financial/?office=medical`
- `/documents/search/`
- `/ocr/import/`
- `/notifications/communications/`
- `/notifications/enquiries/`
- `/accounts/profile/`
- `/records/`
- `/nursing/forms/`
- `/public/nursing-council/register/search/`

## 11. Notes

- The old phrase "Phase 1 and Phase 2" referred to the first repository and OCR/search build-out.
- The current platform now also includes access-request workflow, finance separation, role explanations, and updated documentation.
- Keep using this guide for smoke testing, but use the main user manual for staff training.
