# System Status Report

Project: The National Department Of Health Regulatory Bodies Nursing Council & The Medical Board Online Workforce System

Generated: 07 May 2026

## Executive Summary

The platform is operational as an online workforce, registration, finance, document, reporting, and data-quality system for the National Department of Health regulatory bodies.

The current system supports separated Nursing Council and Medical Board workspaces, role-based access, registrar dashboards, staff inbox/chat, operational access requests, financial forecast pages, monthly analytics, import tracking, duplicate review, missing-data review, public-safe register search, forgotten-password support, and OpenKM-style document repository functions.

The platform foundation is launch-ready for controlled operational use. Production launch still requires NDOH ICT hosting/security confirmation, final staff training, test password replacement, data-cleansing sign-off, and backup/restore confirmation.

## Current Live Snapshot

Checked on 07 May 2026:

| Area | Count |
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
| Qualification records | 25,376 |
| Professional document uploads | 0 |
| Repository folders | 24 |
| Repository documents | 0 |
| User accounts | 14 |
| Pending operational access requests | 1 |

## Current Capability Status

| Capability | Status | Notes |
|---|---|---|
| Authentication and forgotten password | Operational | Login pages include forgotten-password flow. |
| Role-based access | Operational | Backend access checks separate Nursing Council, Medical Board, finance, reviewer, admin, and public users. |
| System Admin backend | Operational | `/admin/` is restricted to System Admin. |
| Nursing Council dashboard | Operational | Includes live statistics, workflow tools, reports, ATP/analytics support, and data-quality links. |
| Medical Board dashboard | Operational | Protected Medical Board workspace. |
| Reviewer access controls | Operational | Reviewers can request operational access; access must be approved by registrar/System Admin. |
| Finance Officer controls | Operational | Finance Officer has read-only Workforce Flow and separated finance pages only. |
| Financial forecast | Operational | Nursing Council and Medical Board views are separated by office scope. |
| Monthly/yearly analytics | Operational | Reports explain live counts, imported rows, source dates, and data-quality limitations. |
| Data-quality review | Operational | Missing-data and duplicate-review workflows are available. |
| Import alignment | Operational | ATP/N-DATA/Medical Board import commands and audit tools are available. |
| OpenKM-style repository | Integrated | Staff-facing upload, detail, metadata, version, search, download audit, scoped access, checksums, and OCR linkage are implemented. |
| Public register search | Operational | Returns safe public fields only. |
| AI Staff Assistant | Operational guidance | Available to authorised staff as guidance only. |

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

Production requirements before live deployment:

- Set `DEBUG=False`.
- Confirm production `ALLOWED_HOSTS`.
- Use HTTPS.
- Confirm backup and restore.
- Confirm email backend for password reset.
- Change all testing passwords.
- Review audit logging and access policies with NDOH ICT.
- Confirm hosting environment and security monitoring.

## Data Quality Position

The system contains substantial live registry and historical import data. However, management reporting must continue to explain:

- Live people counts are different from imported historical row counts.
- Receipt/payment rows are money records, not people.
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
- Repository search screen.
- Staff-facing upload, detail, metadata update, version upload, and audited download.

Operational adoption still required:

- Scan legacy paper evidence.
- Upload and tag documents.
- Link documents to applications, practitioners, receipts, and import batches.
- Confirm retention rules with NDOH ICT and management.

## Recommended Next Actions

1. Resolve pending operational access requests.
2. Complete staff training using the updated user manuals.
3. Run missing-data and duplicate audits before management reporting.
4. Continue ATP-to-employment alignment.
5. Correct suspicious future dates in financial/imported records.
6. Begin controlled document repository pilot with current applications and receipts.
7. Confirm production hosting, backups, and security with NDOH ICT.
8. Change all test passwords before go-live.
