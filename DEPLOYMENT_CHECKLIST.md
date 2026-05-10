# Deployment Checklist

Project: The National Department Of Health Regulatory Bodies Nursing Council & The Medical Board Online Workforce System

Last updated: 07 May 2026

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
.\.venv\Scripts\python.exe manage.py check
```

Run for data-quality readiness:

```powershell
.\.venv\Scripts\python.exe manage.py audit_missing_data --audit-import-rows --latest-batch
.\.venv\Scripts\python.exe manage.py audit_duplicate_records
```

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
- [ ] Test passwords are changed before production launch.

## 5. Dashboard Smoke Tests

- [ ] `/dashboard/` redirects correctly by role.
- [ ] `/dashboard/nursing-council/` loads for Nursing Council Registrar.
- [ ] `/dashboard/medical-board/` loads for Medical Board Registrar.
- [ ] `/dashboard/reports/financial/?office=nursing` loads and shows Nursing Council figures only.
- [ ] `/dashboard/reports/financial/?office=medical` loads and shows Medical Board figures only.
- [ ] `/documents/search/` loads for authorised staff.
- [ ] `/records/` loads for authorised staff.
- [ ] `/nursing/forms/` loads for public/applicant use.
- [ ] `/public/nursing-council/register/search/` returns public-safe output.
- [ ] `/notifications/communications/` shows notifications, enquiries, and access requests.

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
- [ ] Missing gender/date of birth/province/practitioner-number gaps reviewed.
- [ ] Employment records population plan confirmed.
- [ ] Institution and facility names separated and standardised.
- [ ] Government, church, private, overseas, and unknown facility/institution categories reviewed.

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
- [ ] Retention policy discussed with NDOH ICT/management.

## 9. Training Checklist

- [ ] System Admin trained.
- [ ] Nursing Council Registrar trained.
- [ ] Medical Board Registrar trained.
- [ ] Reviewer users trained on approval request process.
- [ ] Finance Officer trained on read-only separated finance views.
- [ ] Data Quality Officer trained on missing-data and duplicate-review workflow.
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
