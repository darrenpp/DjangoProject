# PNG Nursing Council and Medical Board Online Regulatory Workforce Platform

Status: Controlled operational platform foundation with active Nursing Council analytics snapshot, ICMS case management, and ongoing production readiness work

Last updated: 1 June 2026

## Overview

This platform supports online regulatory workforce management for the National Department of Health regulatory bodies. It provides separated workspaces for the PNG Nursing Council and the Medical Board, with role-based access, practitioner records, applications, registrations, receipts, documents, dashboards, reports, data-quality review, notification history, OpenKM-style document management, NHWA reporting workbooks, public FAQ/forum functions, mapped institutions/facilities, and formal ICMS complaints and discipline case management.

The platform is designed to keep Nursing Council and Medical Board data separate. This separation is enforced through backend access checks and not only through visible menu links.

## Quick Start

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py bootstrap_document_repository
.\.venv\Scripts\python.exe manage.py bootstrap_nursing_council_workflows
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py runserver
```

The canonical local virtual environment lives inside this project folder:

```powershell
cd C:\Project\regulatoryNCMB\PNG_NC_MB
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000 --noreload
```

For Android emulator or physical phone integration testing, bind Django to all local interfaces and print the mobile URLs:

```powershell
.\.venv\Scripts\python.exe manage.py bootstrap_mobile_intake
.\.venv\Scripts\python.exe manage.py local_mobile_test_setup --check-api
.\.venv\Scripts\python.exe manage.py runserver 0.0.0.0:8000
```

Use `http://10.0.2.2:8000/` from the Android emulator and `http://YOUR-PC-IP:8000/` from a phone on the same Wi-Fi. See [docs/LOCAL_MOBILE_INTEGRATED_TESTING.md](docs/LOCAL_MOBILE_INTEGRATED_TESTING.md).

## Main Access Points

| Path | Purpose |
|---|---|
| `/` | Public home and entry point |
| `/dashboard/` | Role-based dashboard redirect |
| `/dashboard/nursing-council/` | Nursing Council registrar dashboard and operations |
| `/dashboard/medical-board/` | Medical Board dashboard |
| `/dashboard/reports/financial/?office=nursing` | Nursing Council financial forecast |
| `/dashboard/reports/financial/?office=medical` | Medical Board financial forecast |
| `/dashboard/complaints/` | Formal ICMS complaint, incident, and enquiry case register |
| `/dashboard/complaints/discipline/` | Disciplinary case workflow and escalation register |
| `/dashboard/complaints/decisions/` | Formal regulatory decision register |
| `/dashboard/public/faqs/` | Public frequently asked questions |
| `/dashboard/public/forum/` | Moderated public/practitioner/staff forum entry |
| `/dashboard/public/map/` | Mapped schools, institutions, and facilities using stored coordinates |
| `/dashboard/nhwa-workbooks/` | NHWA standards/reporting workbook layer |
| `/dashboard/duplicate-reviews/` | Duplicate Review Queue with search, sort, pagination, grouped source rows, and review actions |
| `/documents/search/` | OpenKM-style repository search for authorised staff |
| `/records/` | Workforce Records Hub for authorised staff |
| `/records/nursingprofessional/` | Nursing Professionals table with registrar CRUD actions and table functions |
| `/nursing/forms/` | Public Nursing Council pathway/form entry |
| `/public/nursing-council/register/search/` | Public-safe Nursing Council register search |
| `/notifications/communications/` | Staff inbox, chat, enquiries, notification history, and operational access requests |
| `/api/mobile/v1/health/` | Mobile API health check for local Android integration testing |
| `/dashboard/mobile-intake/` | Desktop Mobile Intake Review Queue |
| `/admin/` | System Admin backend only |

## Current Analytics And Registry Snapshot

Checked on 1 June 2026 from the local database.

Nursing Council analytics now reads first from the active cleansed workbook snapshot rather than expensive live-table aggregation. `Person_Group_Key` remains an analytics grouping key only, not a legal practitioner identity.

| Nursing Council analytics metric | Count |
|---|---:|
| Active snapshot source | PNG_Nursing_Council_Integrated_Dashboard_Model.xlsx |
| Workbook generated on | 27 May 2026 |
| Total lifecycle records | 34,851 |
| Clean ATP records | 19,998 |
| Clean provisional records | 8,158 |
| Clean full-licence records | 6,695 |
| Estimated practitioner match groups | 22,765 |
| Data quality health score | 87.0% |

Operational table counts remain separate from the analytics snapshot:

| Area | Count |
|---|---:|
| Registered Nurses / Midwives / Nurse Aides / Health Students in live person tables | 0 |
| Community Health Workers | 11,594 |
| Medical Doctors | 327 |
| Applications | 0 |
| Imported licence/history rows | 53,178 |
| Receipts | 11,501 |
| Receipt amount recorded | PGK 822,882.30 |
| Missing-data review items | 57,129 |
| Duplicate-review items | 177 |
| Qualification records | 11,863 |
| Repository folders | 24 |
| Repository documents | 0 |
| Mapped entity references | 1,462 |
| Geocoded mapped entities | 0 |
| Formal ICMS complaint cases | 0 |
| Disciplinary cases | 0 |
| Regulatory decision records | 0 |

Latest completed import:

| Source file | Source kind | Processed / total rows | Completed |
|---|---|---:|---|
| PNG_Nursing_Council_Cleaned_Licence_Breakdown.xlsx + PNG_Nursing_Council_Cadre_Breakdown.xlsx | nursing_catherine_licence_breakdown | 14,853 / 18,615 | 29 May 2026 01:00 UTC |

## Core Features

- Role-based access control for System Admin, registrars, reviewers, finance, data quality, professionals, graduands, and public users.
- Nursing Council and Medical Board workspace separation.
- Nursing Council pathway configuration for application, checklist, payment, competency, declaration, review, and registrar decision flows.
- Practitioner, licence, qualification, application, receipt, import, and report management.
- Monthly/yearly analytics with source explanations.
- Nursing Council analytics snapshot import and drilldown from cleansed workbooks.
- Catherine provisional/full-licence workbook import alignment without treating workbook grouping keys as legal identities.
- Financial forecast pages separated by office scope.
- Receipt ownership linking and high-value review routing for receipts that cannot be traced to an owner.
- Staff inbox, chat, notification history, unread badge clearing, message opened/read status, and operational access requests.
- Formal ICMS complaints, incident intake, enquiry escalation, discipline workflow, and regulatory decision register.
- Public FAQ, moderated public forum, practitioner/staff forum categories, and mapped institutions/facilities.
- Google Maps display backed by locally stored verified coordinates; the map does not geocode every page load.
- NHWA toolkit as a standards/reporting layer, populated from verified platform data and never pushed back into the legal registry automatically.
- AI Staff Assistant for authorised staff guidance.
- Forgotten password flow on login pages.
- Public registration page with national emblem background and controlled role/cadre dropdowns, including separate CHW provisional and CHW full-license options.
- Records Hub for authorised staff, including registrar table functions and CRUD actions where permitted.
- Data-quality audit, duplicate review queue with DataTables functions, and import alignment tools.
- OpenKM-style document repository with folders, metadata, versions, access policies, search, checksum duplicate checks, and audit events.
- Document approval/rejection sign-off on current versions with approval audit history.

## Documentation

Start with:

- [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md)
- [docs/PLATFORM_UPDATE_BRIEF_20260601.md](docs/PLATFORM_UPDATE_BRIEF_20260601.md)
- [docs/FULL_PLATFORM_USER_GUIDE_20260601.md](docs/FULL_PLATFORM_USER_GUIDE_20260601.md)
- [docs/DATA_EXTRACTION_AND_POPULATION_GUIDE.md](docs/DATA_EXTRACTION_AND_POPULATION_GUIDE.md)
- [docs/OPENKM_Comparison_And_Roadmap.md](docs/OPENKM_Comparison_And_Roadmap.md)
- [docs/OPENKM_Project_Timeline.md](docs/OPENKM_Project_Timeline.md)
- [docs/LOCAL_MOBILE_INTEGRATED_TESTING.md](docs/LOCAL_MOBILE_INTEGRATED_TESTING.md)
- [docs/government_launch_package/README.md](docs/government_launch_package/README.md)

## Data Governance Rules

- Keep Nursing Council records in Nursing Council scope.
- Keep Medical Board records in Medical Board scope.
- Do not mix Nursing Council and Medical Board finance.
- Do not count imported rows as unique people without deduplication.
- Do not count receipt/payment rows as practitioners.
- Do not treat analytics snapshot rows as legal registry records until they are promoted through approved operational workflow.
- Do not use `Person_Group_Key` as a legal practitioner identity.
- Do not publish management statistics before duplicate and missing-data checks.
- Receipts that cannot be linked to a practitioner/application/import owner must move to high-value review.
- Keep source file, sheet, row, import batch, and correction notes for traceability.
- Use the repository and document checklist process for official evidence.
- Use the formal decision register for defensible regulatory decisions and record the authority/SOP reference, rationale, evidence summary, conditions, and appeal rights.

## Security Notes

- `/admin/` is restricted to System Admin.
- System Admin and Registrar MFA is available as a production-toggle control through `REQUIRE_STAFF_MFA=true`.
- Reviewer-style users must request and receive operational approval before higher-risk tools are unlocked.
- Finance Officer is read-only and can view Workforce Flow plus separated Nursing Council/Medical Board finance pages only.
- Public register search returns safe public fields only.
- Public complaints and public forum posts are moderated and do not change registry records.
- Temporary testing passwords must be changed before production launch.
- AI Staff Assistant is guidance only and does not replace registrar decision-making.

## Useful Commands

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py bootstrap_document_repository
.\.venv\Scripts\python.exe manage.py bootstrap_nursing_council_workflows
.\.venv\Scripts\python.exe manage.py bootstrap_nhwa_workbooks
.\.venv\Scripts\python.exe manage.py seed_engagement_platform
.\.venv\Scripts\python.exe manage.py import_nursing_analytics_snapshot --path "path\to\PNG_Nursing_Council_Integrated_Dashboard_Model.xlsx" --activate
.\.venv\Scripts\python.exe manage.py import_nursing_catherine_licence_breakdown --licence-path "path\to\PNG_Nursing_Council_Cleaned_Licence_Breakdown.xlsx" --cadre-path "path\to\PNG_Nursing_Council_Cadre_Breakdown.xlsx"
.\.venv\Scripts\python.exe manage.py link_receipts_to_individual_records --review-unmatched
.\.venv\Scripts\python.exe manage.py audit_missing_data --audit-import-rows --latest-batch
.\.venv\Scripts\python.exe manage.py audit_duplicate_records
.\.venv\Scripts\python.exe manage.py geocode_mapped_entities --limit 100
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
