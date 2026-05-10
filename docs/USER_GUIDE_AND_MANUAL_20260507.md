# Full Platform User Guidelines and Manual

Project: The National Department Of Health Regulatory Bodies Nursing Council & The Medical Board Online Workforce System

Date: 07 May 2026

Audience: Registrars, reviewers, finance officers, data-quality officers, System Admin, professional users, graduands, training institutions, and authorised NDOH staff.

## 1. Purpose Of This Guide

This guide explains how staff and users should use the current platform in plain language.

The platform is no longer just a set of forms or dashboards. It is now a regulatory operations system for:

- Online registration and licence workflows.
- Nursing Council and Medical Board protected workspaces.
- Practitioner profiles and workforce records.
- Applications, renewals, provisional records, full registration, temporary licences, and overseas pathways.
- Receipts, financial forecast reports, and office-separated financial tracking.
- Document repository, scanned records, metadata, versions, OCR/search text, and audit trails.
- Missing-data review, duplicate review, import cleansing, and production-readiness checks.
- Staff inbox, chat, notifications, operational access requests, and AI Staff Assistant guidance.
- Management reports, monthly analytics, yearly analytics, Word briefs, Excel workbooks, and PDF reports.

The main goal is simple: move paper and spreadsheet records into a controlled electronic registry without mixing offices, exposing private data, or trusting unverified imported rows.

## 2. The Most Important Rule

Nursing Council and Medical Board data must remain separate.

Nursing Council users must not view private Medical Board data unless they are explicitly authorised. Medical Board users must not view private Nursing Council data unless they are explicitly authorised. This is enforced by backend role checks, not just by hiding buttons.

The same principle applies to finance:

- Nursing Council receipts and forecasts must be viewed separately.
- Medical Board receipts and forecasts must be viewed separately.
- Combined or mixed totals should only be used where management has specifically requested a combined summary and the report clearly labels the source.

## 3. Current Platform Areas

| Area | What it is used for | Who normally uses it |
|---|---|---|
| Public home and login pages | Public entry, sign in, password reset, and basic system access. | All users. |
| Overall Dashboard | High-level workforce summary and reference count explanation. | System Admin, registrars, approved staff. |
| Nursing Council Portal | Nursing Council live statistics, ATP/current-year records, workflows, reports, and cleansing views. | Nursing Registrar, approved Nursing staff, System Admin. |
| Medical Board Portal | Medical Board-specific records, statistics, and workflow views. | Medical Board Registrar, approved Medical Board staff, System Admin. |
| Workforce Flow | Visual explanation of registration and workforce data movement. | Registrars, finance officer, reviewers, approved staff. |
| Financial Forecast | Manual receipts, spreadsheet receipts, monthly/yearly totals, forecast charts, and exports. | Registrar, finance officer, System Admin. |
| Records Hub | Structured table review and controlled record management. | System Admin, registrars, approved data/review staff. |
| Document Repository | OpenKM-style scanned records, versions, metadata, OCR/search, and audit logs. | Authorised staff only. |
| Production Readiness Dashboard | Remaining launch risks, data problems, security checks, and operational readiness indicators. | System Admin, registrars, project leads. |
| Staff Inbox & Chat | Internal messages, notifications, access requests, document/application follow-up. | Staff users. |
| AI Staff Assistant | Staff-only guidance for reports, workflow, imports, and data-quality questions. | Authorised staff only. |

## 4. Current Live Statistics Snapshot

These values are from the current live platform state on 07 May 2026. They will change as staff import, cleanse, approve, and update records.

| Measure | Current value | How to understand it |
|---|---:|---|
| Registered nurses | 13,493 | Live Nursing Council nurse records currently held in the registry table. |
| Midwives | 2,112 | Live midwife records currently held in the registry table. |
| Nurse aides | 800 | Live nurse aide records currently held in the registry table. |
| Graduands | 7,624 | Live graduand or health student records currently held in the system. |
| Community Health Workers | 11,562 | CHW records currently available in the wider platform data. |
| Medical doctors | 0 | Medical doctor data is still being updated or has not yet been loaded into the live medical doctor table. |
| PNG Nursing schools | 20 | Clean operational count for Nursing Council schools, separated from raw imported institution names. |
| Raw institution rows | 916 | Historical/imported institution references before final classification and cleansing. |
| Cleaned workplace references | 4,926 | Workplace/facility names cleaned from imported records. These are not all confirmed master facilities. |
| Raw workplace/address rows | 7,439 | Historical/raw workplace address references, including repeated and incomplete entries. |
| Missing-data review items | 98,055 | Records or rows with fields needing review, such as missing dates, province, gender, workplace, or institution. |
| Duplicate-review practitioners | 487 | Practitioner candidates requiring manual duplicate review before merging or confirming. |
| Nursing finance combined receipts | PGK 1,420,842.20 | Nursing Council manual and spreadsheet receipt data combined for the current finance scope. |

Important: live person counts are not the same as imported row counts. One person can appear in many imported rows because of renewals, receipts, workforce listings, or historical spreadsheet entries.

## 5. Login, Password Reset, And Account Security

Use the correct account for your role. Do not share accounts.

Login steps:

1. Open the platform in the browser.
2. Select the correct login page.
3. Enter your username and password.
4. Use Forgotten Password if you cannot remember your password.
5. After login, the system sends you to the dashboard allowed for your role.
6. If your dashboard looks empty or locked, check your Profile Overview and submit an operational access request if required.

Security rules:

- Change all testing passwords before production launch.
- Use strong passwords.
- Do not use another officer's account to approve, export, or edit records.
- System Admin and registrar accounts should use MFA before production.
- Logout when leaving the computer.
- If a password reset email is used, open the latest reset link only.
- If a reset link fails after login in another tab, reload the page and request a fresh reset link.

## 6. Profile Overview And Profile Settings

The Profile Overview explains the role of the logged-in user.

It should tell the user:

- What their role is.
- What they can access.
- What they cannot access.
- Whether they need approval before using operational tools.
- Whether they can create, read, update, or delete records.
- Whether they can approve applications or only review them.

Profile settings are kept out of the middle of the profile page. Use the Profile Settings button near the signed-in user and logout section in the top bar to open or update settings.

If your role needs higher access, do not ask someone for their password. Submit an operational access request from your profile or staff workflow screen.

## 7. Operational Access Request Workflow

Some users can log in but cannot use sensitive tools immediately. This is intentional.

Workflow:

```text
Restricted staff user logs in
  -> opens My Profile
  -> reads Profile Overview
  -> submits operational access request
  -> request appears in Staff Inbox & Chat for registrar/System Admin
  -> registrar or System Admin reviews the request
  -> request is approved or rejected
  -> user access is updated
  -> user logs out and back in if menu access needs refreshing
```

Nursing Council requests go to the Nursing Council Registrar and System Admin. Medical Board requests go to the Medical Board Registrar and System Admin.

The request is not approved automatically. This prevents reviewers, finance officers, viewers, or other staff from using high-risk tools without authority.

## 8. Role Access Guide

| Role | Main purpose | Can access | Cannot access |
|---|---|---|---|
| System Admin | Technical administration and production control. | User setup, roles, backend admin, configuration, document repository setup, bootstraps, data-quality tools, production readiness, documentation, and system checks. | Should not be used for routine registrar decisions unless officially authorised to act in that capacity. |
| Nursing Council Registrar | Official Nursing Council regulatory decision maker. | Nursing Council dashboard, applications, workflow tools, approvals, rejections, reports, data-quality views, Nursing finance, staff access requests, and Nursing documents. | Medical Board private records unless specifically authorised. |
| Medical Board Registrar | Official Medical Board regulatory decision maker. | Medical Board dashboard, Medical Board workflows, Medical Board reports, Medical Board finance, and Medical Board staff access requests. | Nursing Council private records unless specifically authorised. |
| Nursing Reviewer | Supports Nursing Council review work. | Assigned review tasks after approval, selected document checks, selected records, and access request workflow. | Final registrar decisions, unrestricted Nursing Operations before approval, admin backend, Medical Board private data. |
| Medical Reviewer | Supports Medical Board review work. | Assigned Medical Board review tasks after approval. | Final registrar decisions, unrestricted Medical Board Operations before approval, admin backend, Nursing Council private data. |
| Data Quality Officer | Cleans and checks data. | Missing-data review, duplicate review, import issue review, source row checking, cleansing notes, and selected records. | Registrar approvals, finance approvals, admin backend, and private records outside assigned scope. |
| Finance Officer | Reviews financial information without editing registry records. | Workforce Flow and separated Financial Forecast pages for Nursing Council and Medical Board. | CRUD functions, practitioner editing, application approval, admin backend, mixed uncontrolled finance views. |
| Viewer | Limited read-only user. | Public-safe or assigned views only. | CRUD, imports, approvals, exports where restricted, and private records. |
| Nurse | Professional self-service user. | Own profile, own applications, own receipts, own licence status, own documents. | Other people's records, staff dashboards, finance reports, admin backend. |
| Midwife | Professional self-service user. | Own profile, own applications, own receipts, own licence status, own documents. | Other people's records and staff-only tools. |
| Nurse Aide | Professional self-service user. | Own profile, own application/receipt status, own supporting documents. | Other people's records and registrar tools. |
| Graduand | Student or graduate pathway user. | Own graduand profile, pathway guidance, own applications, own receipts, supporting documents. | Staff dashboards, other graduands' records, registrar tools. |
| CHW | CHW self-service user. | Own CHW profile and available CHW/Medical Board information. | Nursing Council private records and staff tools. |
| Doctor | Doctor self-service user. | Own Medical Board profile and available doctor information. | Nursing Council private records and staff tools. |
| Public applicant | Public application or public register user. | Public-safe pages, own submitted information, public register search. | Private practitioner details, staff tools, admin backend. |

## 9. System Admin Guide

The System Admin is responsible for the technical health of the platform.

System Admin tasks:

- Manage users and roles.
- Restrict backend administration access to System Admin only.
- Set up or update document repository folders.
- Run setup and bootstrap commands.
- Review production readiness.
- Review security configuration.
- Review audit logs.
- Confirm backups and restore readiness.
- Support registrars with approved access changes.
- Support documentation and deployment preparation.

System Admin must not casually override regulatory decisions. Registrar decisions need proper authority, status history, and audit trails.

## 10. Nursing Council Registrar Guide

Open the Nursing Council portal from the dashboard menu.

Registrar daily tasks:

- Review live Nursing Council statistics.
- Review ATP/current-year records and recent licence records.
- Review pending, approved, rejected, and missing-information applications.
- Check document checklists.
- Check payment status.
- Check competency evidence where required.
- Check duplicate-review and missing-data issues before reports are generated.
- Review access requests from Nursing Council reviewers or staff.
- Approve, reject, or request more information using the official workflow.
- Generate monthly, yearly, finance, and management reports only after data checks.

Registrar approval rules:

- Do not approve if required documents are missing.
- Do not approve if payment is required but not verified or waived.
- Do not approve full/provisional-to-full registration if competency is required but incomplete.
- Do not approve duplicate practitioner numbers without data-quality review.
- Do not use Nursing Council regulations for Medical Board records.
- Do not make silent decisions outside the workflow.

## 11. Medical Board Registrar Guide

Medical Board work must remain separate from Nursing Council work.

Medical Board registrar tasks:

- Review Medical Board records and workflows.
- Review Medical Board finance separately from Nursing Council finance.
- Review CHW and doctor records when available.
- Review Medical Board staff access requests.
- Generate Medical Board reports using Medical Board scope only.
- Apply Medical Board rules, not Nursing Council rules.

If a Medical Board dashboard link redirects incorrectly, report it to System Admin so URL routing can be corrected without using another role's account.

## 12. Reviewer Guide

Reviewers help prepare work for the registrar.

Before operational approval:

- Reviewer can log in.
- Reviewer can see their Profile Overview.
- Reviewer can request operational access.
- Sensitive Nursing Council or Medical Board Operations remain locked.

After operational approval:

- Reviewer can review assigned records.
- Reviewer can help check documents and missing data.
- Reviewer can prepare notes for registrar review.
- Reviewer can use only the tools granted to that role.

Reviewers cannot:

- Make final registrar approval decisions unless explicitly authorised by role and business authority.
- Use admin backend.
- View another office's private data.
- Use another staff account.

## 13. Finance Officer Guide

The Finance Officer has restricted access.

Allowed pages:

- Workforce Flow.
- Nursing Council Financial Forecast page.
- Medical Board Financial Forecast page.

Finance pages must be viewed separately:

- Nursing Council finance: `/dashboard/reports/financial/?office=nursing`
- Medical Board finance: `/dashboard/reports/financial/?office=medical`

Finance Officer can:

- View manual receipts.
- View spreadsheet-imported receipts.
- View monthly and yearly totals.
- View charts and forecast outlook.
- Export finance reports where permitted.
- Check date-quality warnings and suspicious receipt rows.

Finance Officer cannot:

- Create, edit, or delete practitioner records.
- Approve or reject applications.
- Use broad CRUD tools.
- Access backend administration.
- Mix Nursing Council and Medical Board financial information in one uncontrolled report.

How to read finance figures:

- Manual Receipts come from live receipt records entered through the system.
- Spreadsheet Receipts come from imported workbook payment rows.
- Combined Total is manual receipts plus spreadsheet receipts for the selected office scope.
- Current Month Total should only count receipts in the current month.
- Current Year Total should only count receipts in the current year.
- Forecast Month should not show future years such as 2050 unless the source data contains an incorrect future date.

If a receipt date shows an impossible year, report it as a data-quality issue before publishing the report.

## 14. Data Quality Officer Guide

Data-quality work protects the platform from producing wrong management figures.

Common issues to check:

- Same name appearing more than once.
- Same licence number appearing more than once.
- Same registration number appearing more than once.
- Same practitioner number appearing more than once.
- Missing first name or surname.
- Missing gender.
- Missing date of birth.
- Missing province.
- Missing institution.
- Missing workplace or facility.
- Missing licence issue date or expiry date.
- Missing payment date or amount.
- Incorrect future dates, including accidental 2050 dates.
- Overseas or raw imported institution names mixed with PNG nursing schools.

Data-quality rules:

- Do not delete historical rows just because they are messy.
- Do not overwrite good live records with blank spreadsheet values.
- Do not create a new practitioner when a registration number or practitioner number already matches an existing person.
- Keep the source file, sheet name, row number, and correction note.
- Resolve duplicates only when evidence confirms they are the same person.

## 15. Production Readiness Dashboard

The Production Readiness Dashboard makes remaining launch risks visible.

It should be used to monitor:

- Missing-data backlog.
- Duplicate-review backlog.
- Future-date and suspicious-date issues.
- Institution and facility classification issues.
- Finance date and receipt quality issues.
- Backup and restore readiness.
- Security and role access checks.
- Documentation and training status.
- Open launch actions before production handover.

Use this dashboard during weekly readiness meetings so data problems are managed openly instead of hidden in command output.

## 16. Overall Dashboard Guide

The Overall Dashboard provides a high-level picture of the platform.

It shows:

- Medical Doctors.
- Nursing Professionals.
- Midwives.
- Nurse Aides.
- Graduands.
- Community Health Workers.
- Facilities or workplace references.
- PNG Nursing Schools.
- Training institution breakdown.
- Facility/workplace breakdown.

Important explanation:

- PNG Nursing Schools is the cleaned operational Nursing Council school count.
- Raw institution rows include legacy, overseas, duplicate, and incomplete import references.
- Facility/workplace counts may include imported workplace text and are not always confirmed master facility records.
- Use the breakdown tables before quoting institution or facility totals in management documents.

## 17. Nursing Council Dashboard Guide

The Nursing Council dashboard is the main operational screen for the Nursing Council Registrar and approved staff.

It should show:

- Current Nursing Council live statistics.
- ATP/current-year information.
- Gender distribution.
- Provincial distribution.
- Workplace and sector distribution.
- PNG nursing school and institution breakdown.
- Recent full registration and licence records.
- Provisional licence tracking and expiry view.
- Full registration and practising licence by year.
- Nursing Council Operations tools.
- Missing-data and duplicate-review links.
- Report generation buttons.

If a chart is blank:

- Check whether the source table has current records.
- Check whether the data is scoped to Nursing Council only.
- Check whether province, year, workplace, or licence dates are missing.
- Run data-quality review before assuming the count is zero.

## 18. Workforce Flow Guide

The Workforce Flow page explains how records move through the system.

Plain workflow:

```text
Applicant or staff submits data
  -> documents and receipts are attached
  -> system checks required fields
  -> reviewer checks records
  -> registrar makes official decision
  -> licence or registry record is updated
  -> dashboards and reports update
```

Finance Officer can view Workforce Flow, but cannot use it to edit practitioner records.

If Workforce Flow redirects to the wrong dashboard, report the issue. Do not use another user's account to bypass it.

## 19. Records Hub Guide

The Records Hub is used to view and manage structured data tables where authorised.

Large tables such as Applications and Receipts may load slowly because they contain many records. Use filters and search before opening large edit forms.

Best practice:

- Search first.
- Filter by office, status, year, category, or source where possible.
- Open one record at a time.
- Do not make unnecessary edits.
- Add correction notes where data is changed.
- Do not use Records Hub for registrar decisions when an application workflow exists.

## 20. Nursing Council Forms And Pathways

The Nursing Council forms page is now a pathway configuration screen, not just a PDF download page.

Configured pathway groups include:

- PNG Graduate Nurse Provisional Licence.
- PNG Graduate Midwife Full Registration.
- PNG Full Registration.
- PNG Licence Renewal.
- Provisional to Full.
- Overseas Provisional.
- Overseas Full.
- Temporary Overseas Licence.
- Child Health Specialist.
- Double Major Registration.
- Employer Verification.
- Deceased Notification.

The intended workflow is:

```text
Application pathway
  -> required form
  -> required checklist
  -> required documents
  -> required fee rule
  -> validation rules
  -> staff review
  -> registrar decision
  -> licence/register update
  -> dashboard/report update
```

Users must follow the correct pathway. For example, a midwifery graduate should not be processed as an ordinary renewal if the correct midwifery graduate pathway applies.

## 21. Application Review And Approval

Every official application should follow a controlled lifecycle.

Standard lifecycle:

```text
Draft
  -> Submitted
  -> Payment Pending or Intake Screening
  -> Missing Information or Data Quality Review if needed
  -> Technical Review
  -> Registrar Review
  -> Approved or Rejected
  -> Licence Issued or Register Updated
```

Rules:

- No silent approval.
- No undocumented decision.
- Every status change should have history.
- Every sensitive action should have audit logging.
- Required documents must be checked before registrar approval.
- Required payment must be verified or waived.
- Required declarations must be accepted.
- Required competency must be completed where applicable.
- Duplicate concerns must be resolved before publishing final counts.

## 22. Document Repository Guide

Open `/documents/search/` if authorised.

The document repository is the OpenKM-style official records area inside the platform.

It supports:

- Office-scoped folders.
- Nursing Council documents.
- Medical Board documents.
- General Registry documents.
- Scanned forms.
- Receipts.
- Qualifications.
- Letters.
- Competency documents.
- Document metadata.
- Document versions.
- Extracted OCR/search text.
- File checksum duplicate detection.
- Official record flags.
- Retention years.
- Access policies.
- Audit events.

How to use it:

1. Open the document repository.
2. Select or confirm the correct office scope.
3. Upload or locate the document.
4. Add title, description, document type, source, and metadata.
5. Link the document to the related practitioner, application, receipt, or workflow if available.
6. Add a new version instead of replacing evidence silently.
7. Search by name, reference number, receipt number, practitioner number, registration number, source text, or extracted OCR text.
8. Review duplicate checksum groups if the same file has been uploaded more than once.

Do not store Nursing Council documents under Medical Board folders. Do not store Medical Board documents under Nursing Council folders.

## 23. AI Staff Assistant Guide

The AI Staff Assistant is for authorised staff guidance.

It can help with:

- Explaining dashboard numbers.
- Choosing which report to generate.
- Explaining missing-data issues.
- Explaining import and cleansing steps.
- Suggesting what workflow action to check next.
- Helping staff understand finance, records, or document repository screens.

It cannot:

- Approve applications.
- Reject applications.
- Verify payments.
- Override role permissions.
- Replace source documents.
- Make legal, disciplinary, or final regulatory decisions.
- Change live records by itself.

Current AI setup:

- The platform defaults to a safe local rule-based assistant.
- A free local GPT-style model can be connected through Ollama if installed by ICT or System Admin.
- OpenAI is not enabled by default because it is not free and requires external API billing.
- Imported data cleansing can use offline rules first, and optional local model suggestions only when configured.

If the floating AI button blocks another button, move it before clicking the page control. If the popup opens as a full page, use the full page safely and report the popup issue for UI correction.

## 24. Import And Cleansing Guide

The platform should not trust imported spreadsheets automatically.

Correct import rule:

```text
Raw file
  -> staging
  -> validation
  -> cleansing
  -> duplicate review
  -> staff review
  -> registrar or authorised approval
  -> live registry update
  -> dashboard/report update
```

Import checks:

- Names.
- Gender.
- Date of birth.
- Registration number.
- Practitioner number.
- Licence number.
- ATP number.
- Qualification.
- Institution.
- Facility or workplace.
- Province.
- Employment status.
- Receipt number.
- Payment amount.
- Payment date.
- Source sheet.
- Source row.
- Import batch.

Good import practice:

- Preview before committing.
- Do not silently drop invalid rows.
- Do not insert unknown people directly into the live register.
- Do not overwrite verified live data with blank import values.
- Keep source file and row references.
- Send uncertain matches to duplicate review.
- Send incomplete rows to missing-data review.

## 25. Institution And Facility Breakdown Guide

Institution and facility figures must be explained carefully.

PNG Nursing Schools:

- This is the clean Nursing Council operational school count.
- Current clean count: 20.
- Government and non-government schools should be separated where known.
- Unclassified or review-required schools should remain flagged until confirmed.

Raw Training Institution Rows:

- These come from imported records.
- They may include overseas institutions, old spelling variations, duplicates, or non-nursing entries.
- Do not present raw imported institution rows as the official number of PNG nursing schools.

Facility and Workplace Rows:

- These may come from imported workplace text, address fields, CHW records, overseas records, and legacy spreadsheets.
- They must be classified into confirmed health facilities, workplaces, government, church, private, overseas, unknown, or review-required groups.
- Use breakdown tables when explaining the difference between master facilities and raw workplace references.

## 26. Financial Forecast And Reports Guide

Open the correct office-specific finance page:

- Nursing Council finance: `/dashboard/reports/financial/?office=nursing`
- Medical Board finance: `/dashboard/reports/financial/?office=medical`

Finance screens should show:

- Manual receipt total.
- Spreadsheet receipt total.
- Combined total.
- Current month total.
- Current year total.
- Completed manual receipts.
- Imported spreadsheet rows.
- Recent receipt transactions.
- Monthly trend chart.
- Yearly trend chart.
- Category breakdown.
- Forecast outlook.
- Date-quality warnings.

Export formats:

- Excel.
- PDF.
- Word.

Export rules:

- Confirm the selected office scope before exporting.
- Each export should include timestamp and exporting user.
- Each export should include NDOH logo or official heading.
- Do not publish reports with impossible future dates until reviewed.
- Explain manual receipts separately from spreadsheet receipts.
- Explain payment rows separately from practitioner counts.

## 27. Reports And Management Briefs

Reports should be generated after data-quality checks, not before.

Common reports:

- Monthly analytics.
- Yearly analytics.
- Nursing Council live statistics.
- Financial forecast.
- Production readiness.
- Minister brief.
- Registrar brief.
- Secretary brief.
- Documentation index.
- Government launch package.
- Presentation pack.

Every report should clearly state:

- Date generated.
- User who generated it if confidential.
- Office scope.
- Source table or source sheet.
- Whether figures are live people counts or imported rows.
- Whether duplicate and missing-data issues remain.
- Latest import date.
- Latest live record update date.

## 28. Presentation And Handover Documents

Generated presentation documents are stored in `docs/presentation/`.

Current presentation outputs include:

- `NDOH_Regulatory_Platform_Presentation_Pack_20260507.pdf`
- `NDOH_Regulatory_Platform_Presentation_Brief_20260507.docx`
- `NDOH_Regulatory_Platform_Documentation_Index_20260507.pdf`
- Screenshot assets for major user interfaces.
- Architecture, workflow, data-governance, and role/privacy diagrams.

Use these documents for management presentation, training, and handover. Regenerate them after major UI, role, or statistics changes.

## 29. Public Register And Public-Safe Access

Public register search must return safe fields only.

Allowed public fields:

- Full name.
- Registration number.
- Practitioner number if policy allows.
- Professional category.
- Licence status.
- Licence expiry date.
- Eligible-to-practise indicator.

Never expose publicly:

- Date of birth.
- Phone.
- Email.
- Home address.
- Passport.
- Police clearance.
- Medical report.
- Academic transcript.
- Receipt document.
- Private disciplinary notes.
- Internal review notes.

The public register is an output from the master register. It is not the source of truth.

## 30. Professional, Graduand, CHW, And Doctor User Guide

Self-service users can:

- View their own profile.
- View their own application status.
- View their own receipts.
- Submit applicable forms.
- Upload required supporting documents where enabled.
- Use Forgotten Password.
- Read fee and guideline pages.

Self-service users cannot:

- View another person's private record.
- Access staff dashboards.
- Access finance reports.
- Access document repository.
- Access Records Hub.
- Use registrar tools.
- Access backend administration.

Quick links such as handbooks, registration guidelines, and academic calendar should open the correct information page or document. If a quick link redirects to the wrong page, report it for correction.

## 31. Staff Inbox, Chat, And Notifications

Staff Inbox & Chat is used for internal operational communication.

It supports:

- Access requests.
- Enquiries.
- Review follow-up.
- Document review notices.
- Approval or rejection messages.
- Staff notifications.

Use staff chat for system workflow communication, not personal account sharing or unofficial approvals.

## 32. Daily, Weekly, And Monthly Work Routine

Daily:

- Check inbox and notifications.
- Check pending applications.
- Check missing-data or duplicate alerts.
- Check urgent finance or receipt issues.
- Check access requests if registrar or System Admin.

Weekly:

- Review production readiness dashboard.
- Review missing-data backlog.
- Review duplicate-review backlog.
- Review future-date and suspicious receipt issues.
- Review document repository records missing metadata.
- Review staff access permissions.

Monthly:

- Run data-quality checks.
- Generate monthly analytics.
- Generate financial forecast report.
- Review office-separated receipts.
- Prepare registrar or management brief.
- Check backup and restore evidence.
- Confirm source dates and latest import batches.

## 33. Privacy And Security Rules

Always follow these rules:

- Use your own account only.
- Keep Nursing Council and Medical Board data separated.
- Do not export confidential information unless required for official work.
- Do not send private data through personal email or messaging.
- Do not approve applications without required evidence.
- Do not bypass workflow because a record appears urgent.
- Do not use screenshots of private data in public presentations.
- Do not publish raw imported rows as official counts.
- Report suspicious dates, duplicate records, or unexpected access immediately.
- Keep audit trails intact.

## 34. What Not To Do

Do not:

- Share passwords.
- Use registrar accounts for reviewer work.
- Use System Admin accounts for ordinary daily processing.
- Mix Nursing Council and Medical Board finance.
- Treat payment rows as people.
- Treat imported rows as verified live records.
- Delete historical evidence without approval.
- Replace a document instead of adding a new version.
- Approve records with missing required documents.
- Ignore duplicate warnings.
- Quote facility or institution totals without checking the breakdown.

## 35. Troubleshooting Guide

If the page loads slowly:

- Use search and filters.
- Avoid opening large tables without a filter.
- Wait for charts to finish loading before clicking export.
- Report screens that repeatedly hang.

If a chart is blank:

- Check whether records exist for that office.
- Check whether required date fields are missing.
- Check whether province or category fields are blank.
- Check whether the data belongs to Nursing Council or Medical Board.

If export does not scroll in Excel:

- Save the file locally.
- Enable editing if Excel opens it in Protected View.
- Check whether panes are frozen.
- Report formatting issues so the export template can be corrected.

If CSRF or forbidden error appears:

- Reload the page.
- Do not submit an old form from browser history.
- Log out and log back in if needed.
- Use the latest form page before submitting.

If AI assistant does not answer correctly:

- Ask a specific system question.
- Include the office scope, such as Nursing Council or Medical Board.
- Use the local assistant for guidance only.
- Do not treat AI guidance as official approval.

## 36. Plain Language Data Rule For Staff

Use this sentence when explaining imports to management:

Imported rows are not automatically trusted. They are staged, validated, cleansed, reviewed, approved, then promoted into live registry records.

This protects the system from counting the same person many times or publishing incomplete historical spreadsheet data as official live statistics.

## 37. Quick Reference Commands For System Admin

Use these only from the project environment and only if authorised.

```text
python manage.py check
python manage.py test --keepdb
python manage.py bootstrap_document_repository
python manage.py ai_model_status
python manage.py ai_cleanse_import_preview path_to_file.xlsx --sheet SHEETNAME
```

Do not run destructive database commands without a verified backup and written approval.

## 38. Final Staff Checklist Before Publishing Reports

Before sending a report to management:

- Confirm the office scope.
- Confirm the date generated.
- Confirm the exporting user.
- Confirm whether figures are live counts or imported rows.
- Confirm latest source/import date.
- Confirm duplicate-review backlog.
- Confirm missing-data backlog.
- Confirm finance date warnings.
- Confirm Nursing Council and Medical Board data are not mixed.
- Confirm screenshots do not expose private data.
- Confirm the report explains limitations in plain language.

## 39. Current Launch Position

The platform is operating as a government-grade regulatory system foundation with:

- Role-based workspaces.
- Backend privacy enforcement.
- Staff access approval workflow.
- Nursing Council and Medical Board separation.
- OpenKM-style document repository.
- Financial forecast and reporting.
- Data-quality and duplicate-review visibility.
- AI Staff Assistant guidance.
- Production readiness dashboard.
- Presentation and handover documentation.

The remaining success factor is disciplined operations: staff must keep records clean, use the correct pathways, attach evidence, review duplicates, separate offices, and publish only figures that can be explained from source data.

## 40. Mobile And Tablet Use

The platform is designed to adapt to desktop, tablet, and mobile screens.

What changes on smaller screens:

- The sidebar becomes a slide-out menu opened by the menu button.
- Dashboard cards stack vertically so figures remain readable.
- Large tables become horizontally scrollable instead of overflowing off the screen.
- Charts fit inside their cards and can be scrolled where needed.
- Profile Settings and Logout labels shorten in the top bar to save space.
- Forms stack fields vertically for easier touch entry.
- The AI Staff Assistant or AI Helpdesk button can be moved so it does not cover important buttons.
- Footer contact details stack into readable lines.

Good mobile practice:

- Use the menu button to open and close the sidebar.
- Turn the tablet sideways when reviewing wide financial or registry tables.
- Use table search and filters instead of scrolling through large record sets.
- Move the AI assistant button if it covers an export or submit button.
- Avoid approving or exporting confidential reports on a public or shared mobile device.
- Use a desktop or tablet for heavy import, duplicate review, or financial reconciliation work.

If a page still looks too wide, report the page name and screen size to System Admin so that page-specific layout can be tightened.
