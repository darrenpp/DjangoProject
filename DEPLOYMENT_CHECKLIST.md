# Deployment Checklist

Project: PNG Nursing Council and Medical Board Online Regulatory Workforce Platform

Last updated: 1 June 2026

## 1. Deployment Status

The platform foundation is ready for controlled operational use, subject to final production hosting, security, backup, password, and staff-training checks.

## 2. Pre-Deployment Technical Checks

- [ ] Confirm production database connection.
- [ ] Confirm `DEBUG=False`.
- [ ] Confirm production `ALLOWED_HOSTS`.
- [ ] Confirm HTTPS/SSL certificate.
- [ ] Confirm secure `SECRET_KEY` and environment variables.
- [ ] Confirm email backend for password reset.
- [ ] Confirm static file collection.
- [ ] Confirm media/document storage location.
- [ ] Confirm backup and restore process.
- [ ] Confirm server monitoring and log retention.
- [ ] Confirm NDOH ICT hosting approval.

## 3. Required Commands

Run before release:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py bootstrap_reference_data
.\.venv\Scripts\python.exe manage.py bootstrap_document_repository
.\.venv\Scripts\python.exe manage.py bootstrap_nursing_council_workflows
.\.venv\Scripts\python.exe manage.py bootstrap_nhwa_workbooks
.\.venv\Scripts\python.exe manage.py seed_engagement_platform
.\.venv\Scripts\python.exe manage.py check
```

Run for data-quality readiness:

```powershell
.\.venv\Scripts\python.exe manage.py audit_missing_data --audit-import-rows --latest-batch
.\.venv\Scripts\python.exe manage.py audit_duplicate_records
.\.venv\Scripts\python.exe manage.py link_receipts_to_individual_records --review-unmatched
```

Run for local Android integrated testing only:

```powershell
.\.venv\Scripts\python.exe manage.py bootstrap_mobile_intake
.\.venv\Scripts\python.exe manage.py local_mobile_test_setup --check-api
.\.venv\Scripts\python.exe manage.py runserver 0.0.0.0:8000
```

Use `http://10.0.2.2:8000/` for the Android emulator and `http://YOUR-PC-IP:8000/` for a physical phone on the same Wi-Fi. This is for controlled local testing only, not production hosting.

## 4. Access and Security Checklist

- [ ] System Admin can access `/admin/`.
- [ ] Registrar users cannot access `/admin/` unless also System Admin.
- [ ] Nursing Council users cannot view Medical Board private data.
- [ ] Medical Board users cannot view Nursing Council private data.
- [ ] Finance Officer can view Workforce Flow.
- [ ] Finance Officer can view Nursing Council finance separately.
- [ ] Finance Officer can view Medical Board finance separately.
- [ ] Finance Officer cannot use CRUD, registrar approvals, imports, or admin backend.
- [ ] Reviewer users cannot access full operations until approved.
- [ ] Operational access request appears in Staff Inbox & Chat.
- [ ] Registrar/System Admin can approve or reject operational access request.
- [ ] Public register search returns safe fields only.
- [ ] Forgotten-password flow sends email successfully.
- [ ] Sign-in button text remains visible against the portal background.
- [ ] Notification bell unread count appears when messages/notifications are sent.
- [ ] Notification bell unread count clears after the user opens notification history or the related message thread.
- [ ] Registrar opening an inbox thread marks the sender's sent/inbox status as opened/read.
- [ ] Registrar and System Admin users can view notification history.
- [ ] Nursing Council staff can open `/dashboard/complaints/`, `/dashboard/complaints/discipline/`, and `/dashboard/complaints/decisions/`.
- [ ] Medical Board-only users cannot access Nursing Council complaint or analytics data unless authorised.
- [ ] Public users can open `/dashboard/complaints/submit/` without private staff access.
- [ ] Public forum posts and public complaint submissions are moderated before publication or staff action.
- [ ] Public map and FAQ pages do not expose private practitioner data.
- [ ] Test passwords are changed before production launch.

## 5. Dashboard Smoke Tests

- [ ] `/dashboard/` redirects correctly by role.
- [ ] `/dashboard/nursing-council/` loads for Nursing Council Registrar.
- [ ] `/dashboard/medical-board/` loads for Medical Board Registrar.
- [ ] `/dashboard/reports/financial/?office=nursing` loads and shows Nursing Council figures only.
- [ ] `/dashboard/reports/financial/?office=medical` loads and shows Medical Board figures only.
- [ ] `/dashboard/reports/financial/` loads for approved operations/data-quality reviewer roles where allowed by role and scope.
- [ ] `/dashboard/duplicate-reviews/` loads for authorised registrar/admin/data-quality users.
- [ ] Duplicate Review Queue shows search, sort, page length, full pagination, grouped source rows, and Mark Reviewed/Mark Merged/Reopen actions.
- [ ] `/documents/search/` loads for authorised staff.
- [ ] `/records/` loads for authorised staff.
- [ ] `/records/nursingprofessional/` shows registrar table functions: search, sort, pagination, View, Edit, and Add New where authorised.
- [ ] `/nursing/forms/` loads for public/applicant use.
- [ ] `/accounts/` registration shows the emblem background and controlled Role/Cadre dropdowns.
- [ ] Cadre dropdown distinguishes CHW provisional registration from CHW full license.
- [ ] `/public/nursing-council/register/search/` returns public-safe output.
- [ ] `/notifications/communications/` shows notifications, notification history, enquiries, folders, read/opened message status, and access requests.
- [ ] `/dashboard/standards-alignment/` shows Standards and Compliance once without repeated header content.
- [ ] `/api/mobile/v1/health/` returns status `ok` for local mobile integration testing.
- [ ] `/api/mobile/v1/bootstrap/`, `/forms/`, `/lookups/`, `/submissions/status/`, and `/accounts/status/` are reachable from the Android emulator or phone after mobile login.
- [ ] `/dashboard/mobile-intake/` receives synced mobile submissions for registrar review.
- [ ] `/dashboard/nursing-council/analytics/summary/` returns the active Nursing Council snapshot summary.
- [ ] `/dashboard/nursing-council/analytics/drilldown/` returns paginated facts and Open links for authorised staff.
- [ ] `/dashboard/complaints/` shows the ICMS register for authorised staff.
- [ ] `/dashboard/complaints/discipline/` shows disciplinary cases for authorised staff.
- [ ] `/dashboard/complaints/decisions/` shows regulatory decisions for authorised staff.
- [ ] `/dashboard/public/faqs/` loads for public users.
- [ ] `/dashboard/public/forum/` loads and respects moderation/role visibility.
- [ ] `/dashboard/public/map/` loads from stored mapped entities and does not geocode on page load.
- [ ] `/dashboard/nhwa-workbooks/` loads for authorised NHWA users.
- [ ] Nursing Council dashboards show `Welcome To Your PNG Nursing Council Online Platform Dashboard` with the PNG emblem.
- [ ] Medical Board dashboards show `Welcome To Your Medical Board Online Platform Dashboard` with the PNG emblem.

## 6. Report Export Checklist

- [ ] Monthly analytics PDF generates.
- [ ] Monthly analytics Excel generates and is scrollable/readable.
- [ ] Financial forecast PDF generates.
- [ ] Financial forecast Excel generates and is scrollable/readable.
- [ ] Financial forecast Word report generates.
- [ ] Exports show office scope.
- [ ] Exports show timestamp.
- [ ] Exports show exporting user.
- [ ] Exports explain live people counts separately from imported rows.
- [ ] Exports explain manual receipts separately from spreadsheet receipts.

## 7. Data Readiness Checklist

- [ ] Latest ATP workbook imported into correct scope.
- [ ] Latest N-DATA workbook imported into Nursing Council scope.
- [ ] Medical Board workbook imported into Medical Board scope only.
- [ ] Future date errors reviewed.
- [ ] Duplicate registration numbers reviewed.
- [ ] Duplicate practitioner numbers reviewed.
- [ ] Duplicate Review Queue page functions tested after each import.
- [ ] Missing gender/date of birth/province/practitioner-number gaps reviewed.
- [ ] Employment records population plan confirmed.
- [ ] Institution and facility names separated and standardised.
- [ ] Government, church, private, overseas, and unknown facility/institution categories reviewed.
- [ ] Active Nursing Council analytics snapshot exists and is the only active snapshot.
- [ ] Active snapshot KPIs match the cleansed workbook totals: 34,851 lifecycle records, 19,998 ATP, 8,158 provisional, and 6,695 full licence.
- [ ] Catherine cleaned licence and cadre workbook import completed without overwriting legal registry person records.
- [ ] Receipts have been linked only where owner confidence is high.
- [ ] Unmatched, duplicate, suspicious, or high-value receipts appear in review.
- [ ] NHWA web workbooks are populated from verified data and do not push values back into the registry.
- [ ] Mapped schools, institutions, and facilities have verified coordinates before public map demonstration.

## 8. OpenKM-Style Repository Checklist

- [ ] Repository root folders exist.
- [ ] Nursing Council Repository is available.
- [ ] Medical Board Repository is available.
- [ ] General Registry folder is available.
- [ ] Staff can search repository documents.
- [ ] Document metadata standard is agreed.
- [ ] Current document upload pilot completed.
- [ ] Duplicate checksum detection checked.
- [ ] Document audit events reviewed.
- [ ] Current-version document approval/rejection flow tested.
- [ ] Document approval notes capture authority, meeting, SOP, or rejection reason.
- [ ] Retention policy discussed with NDOH ICT/management.

## 9. Training Checklist

- [ ] System Admin trained.
- [ ] Nursing Council Registrar trained.
- [ ] Medical Board Registrar trained.
- [ ] Reviewer users trained on approval request process.
- [ ] Finance Officer trained on read-only separated finance views.
- [ ] Data Quality Officer trained on missing-data and duplicate-review workflow.
- [ ] Registrars trained on notification history, inbox read/opened status, and clearing unread badges.
- [ ] Registrar users trained on Records Hub table functions and when to use workflow decisions instead of direct CRUD.
- [ ] Registrar and reviewers trained on ICMS case creation, enquiry escalation, discipline escalation, and regulatory decision recording.
- [ ] Staff trained on document approval/rejection sign-off.
- [ ] Data Quality and Finance trained on receipt-owner linking and high-value receipt review.
- [ ] Staff trained on NHWA workbook review/sign-off/export flow.
- [ ] Staff trained that Google Maps coordinates must be stored and verified locally before display.
- [ ] Public support staff trained on role/cadre dropdown choices, including CHW provisional versus full-license selection.
- [ ] Public/professional user guidance confirmed.
- [ ] OpenKM-style repository guide shared.
- [ ] Data cleansing/import alignment guide shared.

## 10. Go-Live Decision

Go-live should proceed only when:

- Technical checks pass.
- Access/security smoke tests pass.
- Reports generate correctly.
- Password reset works.
- Test passwords are changed.
- NDOH ICT confirms hosting/security.
- Backup/restore is confirmed.
- Staff training is completed.
- Data-quality limitations are documented for management.
