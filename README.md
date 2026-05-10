# The National Department Of Health Regulatory Bodies Nursing Council & The Medical Board Online Workforce System

Status: Launch-ready platform foundation with ongoing data cleansing and operational adoption

Last updated: 07 May 2026

## Overview

This platform supports online regulatory workforce management for the National Department of Health regulatory bodies. It provides separated workspaces for the Nursing Council and the Medical Board, with role-based access, practitioner records, applications, registrations, receipts, documents, dashboards, reports, data-quality review, and OpenKM-style document management.

The platform is designed to keep Nursing Council and Medical Board data separate. This separation is enforced through backend access checks and not only through visible menu links.

## Quick Start

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py bootstrap_document_repository
.\.venv\Scripts\python.exe manage.py bootstrap_nursing_council_workflows
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py runserver
```

## Main Access Points

| Path | Purpose |
|---|---|
| `/` | Public home and entry point |
| `/dashboard/` | Role-based dashboard redirect |
| `/dashboard/nursing-council/` | Nursing Council registrar dashboard and operations |
| `/dashboard/medical-board/` | Medical Board dashboard |
| `/dashboard/reports/financial/?office=nursing` | Nursing Council financial forecast |
| `/dashboard/reports/financial/?office=medical` | Medical Board financial forecast |
| `/documents/search/` | OpenKM-style repository search for authorised staff |
| `/records/` | Workforce Records Hub for authorised staff |
| `/nursing/forms/` | Public Nursing Council pathway/form entry |
| `/public/nursing-council/register/search/` | Public-safe Nursing Council register search |
| `/notifications/communications/` | Staff inbox, chat, enquiries, and operational access requests |
| `/admin/` | System Admin backend only |

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
| Repository folders | 24 |
| Repository documents | 0 |
| User accounts | 14 |
| Pending operational access requests | 1 |

## Core Features

- Role-based access control for System Admin, registrars, reviewers, finance, data quality, professionals, graduands, and public users.
- Nursing Council and Medical Board workspace separation.
- Nursing Council pathway configuration for application, checklist, payment, competency, declaration, review, and registrar decision flows.
- Practitioner, licence, qualification, application, receipt, import, and report management.
- Monthly/yearly analytics with source explanations.
- Financial forecast pages separated by office scope.
- Staff inbox, chat, notifications, and operational access requests.
- AI Staff Assistant for authorised staff guidance.
- Forgotten password flow on login pages.
- Records Hub for authorised staff.
- Data-quality audit, duplicate review, and import alignment tools.
- OpenKM-style document repository with folders, metadata, versions, access policies, search, checksum duplicate checks, and audit events.

## Documentation

Start with:

- [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md)
- [docs/USER_GUIDE_AND_MANUAL_20260507.md](docs/USER_GUIDE_AND_MANUAL_20260507.md)
- [docs/DATA_CLEANSING_AND_IMPORT_ALIGNMENT_PLAN_20260507.md](docs/DATA_CLEANSING_AND_IMPORT_ALIGNMENT_PLAN_20260507.md)
- [docs/OPENKM_FULL_PLATFORM_USER_GUIDE_20260507.md](docs/OPENKM_FULL_PLATFORM_USER_GUIDE_20260507.md)
- [docs/OPENKM_Comparison_And_Roadmap.md](docs/OPENKM_Comparison_And_Roadmap.md)
- [docs/OPENKM_Project_Timeline.md](docs/OPENKM_Project_Timeline.md)
- [docs/government_launch_package/README.md](docs/government_launch_package/README.md)

## Data Governance Rules

- Keep Nursing Council records in Nursing Council scope.
- Keep Medical Board records in Medical Board scope.
- Do not mix Nursing Council and Medical Board finance.
- Do not count imported rows as unique people without deduplication.
- Do not count receipt/payment rows as practitioners.
- Do not publish management statistics before duplicate and missing-data checks.
- Keep source file, sheet, row, import batch, and correction notes for traceability.
- Use the repository and document checklist process for official evidence.

## Security Notes

- `/admin/` is restricted to System Admin.
- System Admin and Registrar MFA is available as a production-toggle control through `REQUIRE_STAFF_MFA=true`.
- Reviewer-style users must request and receive operational approval before higher-risk tools are unlocked.
- Finance Officer is read-only and can view Workforce Flow plus separated Nursing Council/Medical Board finance pages only.
- Public register search returns safe public fields only.
- Temporary testing passwords must be changed before production launch.
- AI Staff Assistant is guidance only and does not replace registrar decision-making.

## Useful Commands

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py bootstrap_document_repository
.\.venv\Scripts\python.exe manage.py bootstrap_nursing_council_workflows
.\.venv\Scripts\python.exe manage.py audit_missing_data --audit-import-rows --latest-batch
.\.venv\Scripts\python.exe manage.py audit_duplicate_records
.\.venv\Scripts\python.exe manage.py prepare_production_data --write-report
.\.venv\Scripts\python.exe manage.py reset_platform_users --confirm
```

## Launch Readiness

The platform foundation is ready for controlled operational use, but production launch should still include:

- NDOH ICT hosting/security review.
- Backup and restore confirmation.
- Password reset of all test accounts.
- Staff training.
- Data-cleansing sign-off.
- Confirmation of official document retention rules.
- Review of pending operational access requests.
