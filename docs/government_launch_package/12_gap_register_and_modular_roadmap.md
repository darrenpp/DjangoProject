# 12 Gap Register and Modular Roadmap

## Purpose

This register separates completed platform foundations from launch gates and future enterprise enhancements. This prevents the project from being oversold while still showing clear government-grade progress.

## Current Foundations Completed

| Area | Current position |
|---|---|
| Workspace separation | Nursing Council and Medical Board are separated through dashboard and backend scope checks. |
| Role-based access | Central role helpers and locked reviewer/finance flows exist. |
| Password reset | Secure password reset flow exists. |
| MFA | Production-toggle MFA added for System Admin and Registrar roles. |
| Security audit | Login and MFA security audit event model added. |
| Workflow audit | Regulatory status history and audit log foundations exist. |
| Document repository | Office-scoped OpenKM-style repository exists with metadata, versions, search, checksum duplicate checks, and audit events. |
| Financial forecast | Nursing Council and Medical Board finance pages are office-scoped. |
| Data quality | Missing-data tools and Duplicate Review Queue exist with table search, sort, pagination, grouped source rows, and review actions. |
| Records Hub | Nursing Professionals table supports registrar-facing search, sorting, pagination, View, Edit, and Add New actions where authorised. |
| Notifications and inbox | Notification history, unread badge clearing, mailbox folders, and read/opened message status are implemented. |
| Registration UI | Public registration uses controlled Role/Cadre dropdowns and distinguishes CHW provisional from CHW full-license pathways. |
| Dashboard identity | Authenticated Nursing Council and Medical Board headers use board-specific welcome text and PNG emblem identity. |
| Nursing analytics snapshot | Active cleansed Nursing Council snapshot drives dashboard KPIs, charts, and server-side drilldowns. |
| Catherine workbook alignment | Cleaned provisional/full-licence and cadre workbooks are imported as an analytics/import-alignment layer without overwriting legal person records. |
| ICMS complaints | Formal complaint, incident, and enquiry case register exists with staff/public intake and case events. |
| Discipline workflow | Dedicated disciplinary case workflow exists with stages, events, attachments, and complaint escalation. |
| Regulatory decision register | Formal decision records capture rationale, authority/SOP reference, evidence summary, conditions, appeal rights, and effective dates. |
| Document sign-off | Repository document versions support approval/rejection decisions and audit events. |
| NHWA reporting layer | NHWA workbooks are bootstrapped and populated from verified platform data as reporting/sign-off outputs. |
| Public engagement | Public FAQs, moderated forum categories, and public map reference pages exist. |
| Mapping reference layer | Mapped schools, institutions, and facilities are stored locally; Google Maps reads stored verified coordinates. |
| Receipt linking | Receipt-owner matching supports high-confidence links and routes unmatched/suspicious receipts for review. |
| Documentation | User guide, OpenKM guide, data cleansing plan, and government launch package exist. |

## Launch Gate Gaps

| Gap | Risk | Required action | Owner |
|---|---|---|---|
| Production hosting not yet approved by NDOH ICT | High | Confirm server, domain, HTTPS, backup, monitoring, and deployment process | NDOH ICT / System Admin |
| MFA not enabled in local/dev by default | Medium | Set `REQUIRE_STAFF_MFA=true` in production | System Admin |
| Production email not configured | High | Configure SMTP for password reset and MFA | NDOH ICT / System Admin |
| Penetration test not completed | High | Engage independent tester and remediate findings | Project owner / NDOH ICT |
| Vulnerability scan not completed | High | Run dependency and web app scans before handover | System Admin / ICT |
| Backup restore drill not completed | High | Restore latest backup into test environment and record evidence | NDOH ICT |
| Full UAT sign-off not recorded | High | Obtain sign-off from registrar, finance, data quality, System Admin | Project owner |
| Broader audit coverage still expanding | Medium | Continue adding audit events to all imports, exports, receipt-linking decisions, case decisions, and high-risk edits | Developer / System Admin |
| Live employment data still dependent on clean ATP/renewal capture | Medium | Continue ATP alignment and make renewal employment capture mandatory | Registrar / Data Quality |
| No verified map coordinates yet for public demonstration | Medium | Geocode or manually enter verified coordinates and record verification status before public launch | System Admin / Data Quality |
| Complaint/discipline SOP adoption still required | High | Train staff and approve SOPs for ICMS triage, discipline escalation, decision recording, and closure standards | Registrar / Management |
| NHWA sign-off process needs operational ownership | Medium | Assign NHWA reviewers and require checklist completion before export/sign-off | Registrar / Data Quality / Finance |
| Receipt unmatched review backlog can affect finance defensibility | High | Run receipt-owner linking regularly and review unmatched/high-value receipts | Finance / Data Quality |
| Generated PDFs/Word briefs may still contain older screenshots or counts | Medium | Regenerate presentation pack, user guide PDF, and brief outputs from updated Markdown before external circulation | System Admin / Project owner |

## Modular Enterprise Roadmap

### Module 1: Security Hardening

Status: Started.

Deliverables:

- MFA production toggle.
- Security audit events.
- HTTPS production settings.
- Admin restriction verification.
- Vulnerability scan.
- Penetration test.

### Module 2: Data Governance

Status: Started.

Deliverables:

- Data dictionary.
- Import staging rule.
- Source traceability.
- Missing-data SOP.
- Duplicate Review Queue SOP.
- Institution/facility/province normalization.

### Module 3: Workflow Control

Status: Implemented foundation; SOP adoption required.

Deliverables:

- Checklist gating.
- Payment gating.
- Reviewer queue.
- Registrar approval.
- Licence lifecycle.
- Status history and audit trail.
- ICMS complaint case intake and triage.
- Disciplinary case escalation.
- Regulatory decision register.

### Module 4: Records Management

Status: Implemented foundation; operational document upload and sign-off required.

Deliverables:

- Office-scoped repository.
- Metadata.
- Versions.
- OCR/search.
- Retention.
- Audit events.
- Approval/rejection sign-off for controlled versions.
- Link evidence to applications/practitioners.
- Link evidence to complaint, discipline, and decision cases.

### Module 5: Reporting and Finance

Status: Started.

Deliverables:

- Monthly analytics.
- Yearly analytics.
- Financial forecast.
- Export timestamp/user tracking.
- Source-date explanations.
- Ministerial/registrar brief generation.
- Active Nursing Council analytics snapshot reporting.
- NHWA workbook population, review, sign-off, and export.
- Receipt-owner matching and high-value unmatched receipt review.

### Module 7: Public Engagement And Mapping

Status: Implemented foundation; content and coordinate verification required.

Deliverables:

- Public FAQ entries.
- Moderated public forum.
- Practitioner and staff forum categories.
- Mapped schools, institutions, and facilities.
- Google Maps display using locally stored verified coordinates.
- Verification workflow for mapped entities.

### Module 6: Deployment and Operations

Status: Documentation ready; production action required.

Deliverables:

- Dev/staging/production environments.
- Backup/restore environment.
- Deployment guide.
- Monitoring.
- Support model.
- Change request process.

## Definition of Done For Government Launch

The system should not be declared production-live until:

- All critical launch gates are closed.
- MFA is enabled for production System Admin and Registrars.
- Production email works.
- HTTPS and secure cookies are enabled.
- Backup restore drill is completed.
- Vulnerability scan and penetration test are completed.
- UAT is signed.
- Staff training is delivered.
- Production support owner is assigned.
