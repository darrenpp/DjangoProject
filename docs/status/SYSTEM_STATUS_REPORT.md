# System Status Report

Project: PNG Nursing Council and Medical Board Online Regulatory Workforce Platform

Generated: Updated 1 June 2026

## Executive Summary

The platform is operational as an online workforce, registration, finance, document, reporting, and data-quality system for the National Department of Health regulatory bodies.

The current system supports separated Nursing Council and Medical Board workspaces, role-based access, board-specific registrar dashboards, Nursing Council analytics snapshots, staff inbox/chat, notification history, read/opened message status, operational access requests, financial forecast pages, monthly analytics, import tracking, duplicate review queue, missing-data review, receipt-owner linking, public-safe register search, forgotten-password support, controlled public registration role/cadre routing, Records Hub table functions, OpenKM-style document repository functions, formal ICMS complaints, discipline workflows, regulatory decision records, NHWA workbook reporting, public FAQs/forums, and mapped institution/facility references.

The platform foundation is launch-ready for controlled operational use. Production launch still requires NDOH ICT hosting/security confirmation, final staff training, test password replacement, data-cleansing sign-off, and backup/restore confirmation.

## Current Live Snapshot

Checked on 1 June 2026:

| Area | Count |
|---|---:|
| Nursing Council analytics lifecycle records | 34,851 |
| Clean ATP records | 19,998 |
| Clean provisional records | 8,158 |
| Clean full-licence records | 6,695 |
| Estimated practitioner match groups | 22,765 |
| Data quality health score | 87.0% |
| Registered Nurses / Midwives / Nurse Aides / Health Students in live person tables | 0 |
| Community Health Workers | 11,594 |
| Medical Doctors | 327 |
| Applications | 0 |
| Imported licence/history rows | 53,178 |
| Receipts | 11,501 |
| Receipt amount recorded | PGK 822,882.30 |
| Missing-data review items | 57,129 |
| Pending missing-data reviews | 0 |
| Duplicate-review items | 177 |
| Pending duplicate-review items | 177 |
| Qualification records | 11,863 |
| Professional document uploads | 0 |
| Repository folders | 24 |
| Repository documents | 0 |
| Mapped entity references | 1,462 |
| Geocoded mapped entities | 0 |
| Public FAQ entries | 5 |
| Formal ICMS complaint cases | 0 |
| Disciplinary cases | 0 |
| Regulatory decision records | 0 |

## Current Capability Status

| Capability | Status | Notes |
|---|---|---|
| Authentication and forgotten password | Operational | Login pages include forgotten-password flow. |
| Role-based access | Operational | Backend access checks separate Nursing Council, Medical Board, finance, reviewer, admin, and public users. |
| System Admin backend | Operational | `/admin/` is restricted to System Admin. |
| Nursing Council dashboard | Operational | Includes live statistics, workflow tools, reports, ATP/analytics support, and data-quality links. |
| Medical Board dashboard | Operational | Protected Medical Board workspace. |
| Board-specific dashboard headers | Operational | Nursing Council and Medical Board dashboards show board-specific welcome text with PNG emblem identity. |
| Public registration role/cadre routing | Operational | Registration uses controlled dropdowns and separates CHW provisional from CHW full-license pathways. |
| Reviewer access controls | Operational | Reviewers can request operational access; access must be approved by registrar/System Admin. |
| Finance Officer controls | Operational | Finance Officer has read-only Workforce Flow and separated finance pages only. |
| Financial forecast | Operational | Nursing Council and Medical Board views are separated by office scope. |
| Nursing Council analytics snapshot | Operational | Active cleansed workbook snapshot drives executive KPIs, Chart.js datasets, and server-side drilldown. |
| Catherine workbook alignment | Operational | Cleaned provisional/full-licence and cadre workbooks are imported without overwriting legal registry identities. |
| Monthly/yearly analytics | Operational | Reports explain live counts, imported rows, source dates, and data-quality limitations. |
| Data-quality review | Operational | Missing-data workflow and Duplicate Review Queue are available with search, sort, page length, pagination, grouped source rows, and review actions. |
| Receipt-owner linking | Operational foundation | Matching command links high-confidence receipts and routes unmatched/suspicious receipts to review. |
| Records Hub table functions | Operational | Nursing Professionals table includes registrar-facing table functions and CRUD actions where authorised. |
| Import alignment | Operational | ATP/N-DATA/Medical Board import commands and audit tools are available. |
| OpenKM-style repository | Integrated | Staff-facing upload, detail, metadata, version, approval/rejection sign-off, search, download audit, scoped access, checksums, and OCR linkage are implemented. |
| ICMS complaints | Operational foundation | Public/staff complaint intake, case list/detail, case events, attachments, risk/priority, and enquiry escalation are implemented. |
| Discipline workflow | Operational foundation | Disciplinary case list/detail, stage tracking, events, attachments, and complaint escalation are implemented. |
| Regulatory decisions | Operational foundation | Decision register captures rationale, authority/SOP reference, evidence summary, conditions, appeal rights, maker, and dates. |
| NHWA workbooks | Operational foundation | Toolkit is available as a standards/reporting layer populated from verified platform data. |
| Public FAQ/forum/map | Operational foundation | Public FAQs, moderated forums, and mapped references are available; map still needs verified coordinates. |
| Public register search | Operational | Returns safe public fields only. |
| AI Staff Assistant | Operational guidance | Available to authorised staff as guidance only. |
| Notification history and read status | Operational | Bell count, notification history, mailbox folders, read/opened status, and unread clearing are implemented. |

## Security Position

Implemented controls:

- CSRF protection.
- Django password hashing.
- Role-based access control.
- Office-scope separation.
- System Admin-only admin backend.
- Public-safe register output.
- Finance read-only restrictions.
- Reviewer operational approval workflow.
- Session timeout middleware.
- Export timestamp/user tracking for confidential reports.
- Office-scoped ICMS, discipline, and decision access checks.
- Public complaint/forum moderation boundaries.
- Document approval/rejection audit history.

Production requirements before live deployment:

- Set `DEBUG=False`.
- Confirm production `ALLOWED_HOSTS`.
- Use HTTPS.
- Confirm backup and restore.
- Confirm email backend for password reset.
- Change all testing passwords.
- Review audit logging and access policies with NDOH ICT.
- Confirm hosting environment and security monitoring.
- Confirm Google Maps API key restrictions and coordinate verification process.

## Data Quality Position

The system contains substantial live registry and historical import data. However, management reporting must continue to explain:

- Live people counts are different from imported historical row counts.
- Receipt/payment rows are money records, not people.
- Analytics snapshot rows are dashboard evidence, not legal registry identities.
- `Person_Group_Key` is an analytics grouping key only.
- NHWA workbook values are reporting/sign-off outputs, not registry updates.
- Employment records still require population from ATP and renewal workflows.
- Legacy document uploads are not yet fully attached to historical practitioner records.
- Missing-data review and duplicate-review backlogs must be worked through before final authoritative statistics are published.

## OpenKM-Style Document Management Status

Implemented:

- Repository folder structure with 24 folders.
- Office scope.
- Document metadata.
- Document versions.
- Extracted text search field.
- File checksum duplicate detection.
- Role/user access policy model.
- Document audit events.
- Document approval and rejection records.
- Repository search screen.
- Staff-facing upload, detail, metadata update, version upload, and audited download.

Operational adoption still required:

- Scan legacy paper evidence.
- Upload and tag documents.
- Link documents to applications, practitioners, receipts, and import batches.
- Link evidence to ICMS, discipline, and regulatory decision records where relevant.
- Confirm retention rules with NDOH ICT and management.

## Recommended Next Actions

1. Resolve pending operational access requests.
2. Complete staff training using the updated user manuals.
3. Run missing-data, duplicate, receipt-linking, and analytics snapshot checks before management reporting.
4. Work through the 177 pending duplicate-review items before relying on final people counts.
5. Continue ATP-to-employment alignment.
6. Correct suspicious future dates in financial/imported records.
7. Begin controlled document repository pilot with current applications, receipts, complaints, discipline files, and decision records.
8. Verify map coordinates before public demonstration.
9. Complete ICMS, discipline, decision-register, document-approval, NHWA, and receipt-linking UAT.
10. Regenerate PDF/Word briefs and screenshots from updated Markdown before external circulation.
11. Confirm production hosting, backups, and security with NDOH ICT.
12. Change all test passwords before go-live.
