from __future__ import annotations

import csv
import html
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "generated_reports" / "formal_valuation_evidence_pack"
DATE = "June 9, 2026"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def copy_evidence_assets() -> tuple[int, int]:
    (PACK / "screenshots").mkdir(parents=True, exist_ok=True)
    (PACK / "diagrams").mkdir(parents=True, exist_ok=True)

    sources = [
        (ROOT / "docs" / "presentation" / "assets" / "screenshots", PACK / "screenshots"),
        (ROOT / "docs" / "presentation" / "assets" / "diagrams", PACK / "diagrams"),
        (ROOT / "docs" / "system_brief_assets", PACK / "screenshots"),
    ]

    for src_dir, dest_dir in sources:
        if not src_dir.exists():
            continue
        for src in src_dir.glob("*.png"):
            dest = dest_dir / src.name
            if dest.exists():
                dest = dest_dir / f"{src.stem}_brief{src.suffix}"
            shutil.copy2(src, dest)

    return (
        len(list((PACK / "screenshots").glob("*.png"))),
        len(list((PACK / "diagrams").glob("*.png"))),
    )


def build_model_inventory() -> list[dict[str, str | int]]:
    class_re = re.compile(r"^class\s+(\w+)\(([^)]*)\):")
    all_classes: list[tuple[str, Path, int, str, str]] = []
    for path in sorted((ROOT / "apps").glob("*/models.py")):
        app = path.parent.name
        for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            match = class_re.match(line.strip())
            if match:
                all_classes.append((app, path, line_no, match.group(1), match.group(2)))

    known_model_classes: set[str] = set()
    changed = True
    while changed:
        changed = False
        for _, _, _, name, bases in all_classes:
            base_names = [base.strip().split(".")[-1] for base in bases.split(",")]
            direct = "models.Model" in bases or "AbstractUser" in bases or "AbstractBaseUser" in bases
            inherited = any(base in known_model_classes for base in base_names)
            if (direct or inherited) and name not in known_model_classes:
                known_model_classes.add(name)
                changed = True

    rows: list[dict[str, str | int]] = []
    for app, path, line_no, name, bases in all_classes:
        if name in known_model_classes:
            rows.append(
                {
                    "app": app,
                    "entity": name,
                    "base": bases,
                    "source": str(path.relative_to(ROOT)),
                    "line": line_no,
                }
            )

    with (PACK / "database_entity_inventory.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["app", "entity", "base", "source", "line"])
        writer.writeheader()
        writer.writerows(rows)

    return rows


def build_route_inventory() -> list[dict[str, str | int]]:
    route_re = re.compile(r"path\((['\"])(.*?)\1\s*,\s*([^,)]+)")
    rows: list[dict[str, str | int]] = []
    for path in sorted(ROOT.rglob("urls.py")):
        if any(part in {".venv", "__pycache__"} for part in path.parts):
            continue
        for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if "path(" not in line and "re_path(" not in line:
                continue
            route = ""
            target = line.strip()
            match = route_re.search(line)
            if match:
                route = match.group(2)
                target = match.group(3).strip()
            rows.append(
                {
                    "source": str(path.relative_to(ROOT)),
                    "line": line_no,
                    "route": route,
                    "target": target,
                }
            )

    with (PACK / "url_surface_inventory.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["source", "line", "route", "target"])
        writer.writeheader()
        writer.writerows(rows)

    return rows


def line_count(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
    except Exception:
        return 0


def build_code_inventory() -> tuple[int, int, int, int]:
    runtime_files: list[Path] = []
    for ext in ("*.py", "*.html", "*.js", "*.css"):
        runtime_files.extend(ROOT.rglob(ext))

    excluded_parts = {
        ".venv",
        ".git",
        "__pycache__",
        "migrations",
        "adminlte",
        "vendor",
        "media",
        "logs",
        "docs",
        "generated_reports",
        "maps",
        "leaflet",
        "bootstrap",
        "jquery",
        "datatables",
    }

    filtered = []
    for path in runtime_files:
        rel = str(path.relative_to(ROOT))
        if set(path.parts) & excluded_parts:
            continue
        if "static\\css\\adminlte" in rel or "static\\js\\Chart.js" in rel:
            continue
        filtered.append(path)

    runtime_loc = sum(line_count(path) for path in filtered)

    evidence_files: list[Path] = []
    for ext in ("*.py", "*.html", "*.js", "*.css", "*.md", "*.kt", "*.java", "*.xml"):
        evidence_files.extend(ROOT.rglob(ext))

    evidence_filtered = []
    for path in evidence_files:
        rel = str(path.relative_to(ROOT))
        if any(part in {".venv", ".git", "__pycache__", "migrations", "adminlte", "vendor", "media", "logs", "generated_reports"} for part in path.parts):
            continue
        if "docs\\presentation\\assets\\html" in rel or "docs\\system_brief_assets\\html" in rel:
            continue
        if "static\\css\\adminlte" in rel or "static\\js\\Chart.js" in rel:
            continue
        evidence_filtered.append(path)

    evidence_loc = 0
    with (PACK / "code_inventory.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Path", "Lines"])
        writer.writeheader()
        for path in sorted(evidence_filtered):
            lines = line_count(path)
            evidence_loc += lines
            writer.writerow({"Path": str(path.relative_to(ROOT)), "Lines": lines})

    return len(filtered), runtime_loc, len(evidence_filtered), evidence_loc


def write_markdown_reports(
    screenshots_count: int,
    diagrams_count: int,
    models: list[dict[str, str | int]],
    routes: list[dict[str, str | int]],
    runtime_files: int,
    runtime_loc: int,
    evidence_files: int,
    evidence_loc: int,
) -> None:
    screenshots = sorted((PACK / "screenshots").glob("*.png"))
    diagrams = sorted((PACK / "diagrams").glob("*.png"))

    write(
        PACK / "00_evidence_pack_index.md",
        f"""
# Formal Valuation Evidence Pack

Prepared: {DATE}

Project: PNG Medical Board & Nursing Council Regulatory Agencies Platform

## Pack Contents

- 01_system_feature_list_and_screenshots.md
- 02_architecture_and_deployment_model.md
- 03_database_entity_overview.md
- 04_code_inventory_and_test_report.md
- 05_mobile_app_api_demonstration_evidence.md
- 06_user_acceptance_testing_report_template.md
- 07_security_privacy_assessment_report.md
- 08_data_migration_and_cleansing_report.md
- 09_training_guides_and_operational_manuals.md
- 10_maintenance_and_support_plan.md
- 11_exchange_rate_and_market_cost_assumptions.md
- code_inventory.csv
- database_entity_inventory.csv
- url_surface_inventory.csv
- screenshots/
- diagrams/

## Current Evidence Status

| Evidence Item | Status |
| --- | --- |
| System feature list and screenshots | Prepared, with screenshots copied into pack |
| Architecture diagram and deployment model | Prepared, with existing diagrams and Mermaid diagrams |
| Database/entity overview | Prepared from Django model inventory |
| Code inventory and test report | Prepared; 225 tests passed |
| Mobile app/API demonstration evidence | Prepared; health endpoint smoke check passed |
| User acceptance testing report | Template prepared; formal business sign-off pending |
| Security/privacy assessment | Internal readiness prepared; independent testing pending |
| Data migration and cleansing report | Prepared from import/cleansing capabilities and test output |
| Training guides and operational manuals | Existing docs indexed; production runbook gaps noted |
| Maintenance and support plan | Prepared |
| Exchange-rate and market-cost assumptions | Prepared using current sources checked on {DATE} |

## Important Qualification

This pack supports a valuation discussion. It is not a formal independent valuation, audit, penetration test, legal certification, or procurement quote. The highest valuation range should be defended only after independent security testing, formal UAT sign-off, production deployment evidence, and registrar/system-owner acceptance.
""",
    )

    screenshot_list = "\n".join(f"- screenshots/{path.name}" for path in screenshots[:45])
    write(
        PACK / "01_system_feature_list_and_screenshots.md",
        f"""
# 01 System Feature List And Screenshot Evidence

Prepared: {DATE}

## Feature Summary

The platform is a government health regulatory registry and workflow system for the PNG Medical Board and Nursing Council. It is more than a public website because it supports registration, licensing, record review, public verification, mobile intake, staff approvals, documents, complaints, analytics, and regulatory governance.

## Major Feature Areas

- Public home page and public-safe register search.
- Nursing Council portal, forms, provisional/full licence/ATP pathway support, analytics, frequent records, and practitioner drilldown.
- Medical Board portal, medical practitioner and CHW pathway separation, board-specific dashboards, and records workflows.
- Professional user portals for nurses, doctors, CHWs, nurse aides, graduands/students, and viewer roles.
- Staff registration, login, MFA readiness, dual approval, operational access requests, notifications, and staff inbox.
- System Admin dashboard, configuration surfaces, records hub, production readiness, and support tooling.
- Records Hub CRUD and reference tables with office-scope controls.
- Data import, cleansing, duplicate review, missing-data review, source traceability, and analytics snapshots.
- Document repository with metadata, versions, approval actions, search, OCR support, and audit events.
- Complaints/ICMS-style case register, disciplinary workflow, and regulatory decision register.
- NHWA workbook/reporting toolkit and standards alignment pages.
- Public FAQ, forum, and mapping views for schools, institutions, and facilities.
- Mobile intake API for Android app integration: login, bootstrap, forms, lookups, duplicate check, submissions, attachments, account registration, account status, and health endpoint.
- AI staff assistant/import-cleansing support with local fallback readiness.

## Screenshot Evidence

Screenshots copied into `screenshots/`: {screenshots_count} PNG files.

Representative screenshots include:

{screenshot_list}
""",
    )

    diagram_list = "\n".join(f"- diagrams/{path.name}" for path in diagrams)
    write(
        PACK / "02_architecture_and_deployment_model.md",
        f"""
# 02 Architecture Diagram And Deployment Model

Prepared: {DATE}

## Architecture Summary

The platform follows a Django web application architecture with role-based web portals, public routes, mobile API endpoints, PostgreSQL data storage, media/document storage, notification workflows, and optional AI assistant integration.

## Main Components

- Web users: public users, professional users, registrar/staff users, system administrators.
- Android app: connects through `/api/mobile/v1/` endpoints for mobile intake and account workflows.
- Django backend: URL routing, views, templates, role access, workflow services, imports, analytics, notifications, document repository, complaints, and AI assistant services.
- Database: PostgreSQL in the current test/development environment.
- Storage: local media/document upload storage in development; production should use approved NDOH ICT storage and backup controls.
- External services: email/SMS if configured, maps, AI provider if enabled, and production HTTPS/domain.

## Deployment Model

### Local/UAT

- Run Django on `0.0.0.0:8000` for Android phone testing on the same Wi-Fi.
- Android emulator uses `http://10.0.2.2:8000/`.
- Physical Android phone uses the PC LAN IP, confirmed by the helper as `http://192.168.137.142:8000/` in the current environment.
- Local HTTP is for testing only.

### Production

- NDOH ICT-approved hosting.
- HTTPS domain and valid TLS certificate.
- Production email service.
- Secure environment variables.
- Backups and restore drills.
- Vulnerability scan and independent penetration test.
- Registrar, finance, data-quality, system admin, and mobile UAT sign-off.
- Monitoring, support desk, incident response, and change control.

## Existing Diagram Evidence

Existing PNG diagrams copied into `diagrams/`: {diagrams_count} files.

{diagram_list}
""",
    )

    write(
        PACK / "diagrams" / "enterprise_architecture_evidence.mmd",
        """
flowchart LR
  Public[Public Users] --> Web[Django Web Platform]
  Professionals[Professional Users] --> Web
  Staff[Registrars and Staff] --> Web
  Admin[System Admin] --> Web
  Android[Android Mobile App] --> MobileAPI[Mobile API /api/mobile/v1]
  MobileAPI --> Web
  Web --> RBAC[Role and Office Scope Controls]
  Web --> Workflow[Registration, Licence, ATP, Review Workflows]
  Web --> Docs[Document Repository and OCR]
  Web --> Complaints[Complaints, Discipline, Decision Registers]
  Web --> Analytics[Analytics, NHWA, Reports]
  Web --> DB[(PostgreSQL Database)]
  Web --> Media[(Media and Document Storage)]
  Web --> Notify[Notifications and Email]
  Web --> Maps[Maps and Public Verification]
  Web --> AI[AI Staff Assistant Optional]
""",
    )
    write(
        PACK / "diagrams" / "deployment_model_evidence.mmd",
        """
flowchart TD
  Dev[Developer PC / Local UAT] --> Runserver[Django runserver 0.0.0.0:8000]
  Runserver --> Browser[Desktop Browser]
  Runserver --> Emulator[Android Emulator 10.0.2.2]
  Runserver --> Phone[Physical Phone on Same Wi-Fi]
  Runserver --> LocalDB[(Local/PostgreSQL Database)]
  Runserver --> LocalMedia[(Local Media Uploads)]
  Prod[Production Target] --> Hosting[NDOH ICT Approved Hosting]
  Hosting --> HTTPS[HTTPS Domain and TLS]
  Hosting --> ProdDB[(Managed Database)]
  Hosting --> Backups[Backups and Restore Drills]
  Hosting --> Monitoring[Monitoring, Logs, Support]
  Hosting --> Security[Vulnerability Scan and Penetration Test]
""",
    )

    entities_by_app: dict[str, list[str]] = {}
    for row in models:
        entities_by_app.setdefault(str(row["app"]), []).append(str(row["entity"]))
    sections = []
    for app, entities in sorted(entities_by_app.items()):
        sections.append(f"## {app} ({len(entities)} entities)")
        sections.extend(f"- {entity}" for entity in entities)
        sections.append("")
    write(
        PACK / "03_database_entity_overview.md",
        f"""
# 03 Database And Entity Overview

Prepared: {DATE}

## Summary

The Django model inventory identifies {len(models)} model/entity classes across {len(entities_by_app)} application modules. These include user/account controls, workforce registry records, application pathways, documents, notifications, complaints, analytics, mobile intake, NHWA workbook data, OCR documents, and common review queues.

Detailed CSV: `database_entity_inventory.csv`.

{chr(10).join(sections)}
""",
    )

    write(
        PACK / "04_code_inventory_and_test_report.md",
        f"""
# 04 Code Inventory And Test Report

Prepared: {DATE}

## Code Inventory

- Runtime application source files counted: {runtime_files}
- Runtime application source lines counted: {runtime_loc:,}
- Broader evidence/source/documentation inventory files: {evidence_files}
- Broader evidence/source/documentation inventory lines: {evidence_loc:,}
- Model/entity classes identified: {len(models)}
- URL route declarations captured: {len(routes)}

Detailed CSV files:

- `code_inventory.csv`
- `database_entity_inventory.csv`
- `url_surface_inventory.csv`

## Test Report

Command executed:

```powershell
C:\\Project\\DjangoProject\\ndoh\\Scripts\\python.exe manage.py test --keepdb
```

Result:

- Django found 225 tests.
- System check identified no issues.
- Ran 225 tests in 643.567 seconds.
- Final result: OK.
- Existing PostgreSQL test database was preserved with `--keepdb`.

## Note

An initial non-keepdb test attempt stopped because the existing PostgreSQL test database `test_ndoh_registry` already existed and Django requested interactive confirmation. The successful evidence run used `--keepdb` to avoid an interactive prompt.
""",
    )

    write(
        PACK / "05_mobile_app_api_demonstration_evidence.md",
        f"""
# 05 Mobile App And API Demonstration Evidence

Prepared: {DATE}

## Mobile API Surface

The project exposes the Android/mobile API at `/api/mobile/v1/`.

Confirmed endpoints include:

- `/api/mobile/v1/auth/login/`
- `/api/mobile/v1/bootstrap/`
- `/api/mobile/v1/forms/`
- `/api/mobile/v1/lookups/`
- `/api/mobile/v1/duplicates/check/`
- `/api/mobile/v1/submissions/`
- `/api/mobile/v1/submissions/<submission_uuid>/attachments/`
- `/api/mobile/v1/submissions/status/`
- `/api/mobile/v1/accounts/register/`
- `/api/mobile/v1/accounts/status/`
- `/api/mobile/v1/health/`

## Local Demonstration Evidence

Command executed:

```powershell
C:\\Project\\DjangoProject\\ndoh\\Scripts\\python.exe manage.py local_mobile_test_setup --check-api
```

Observed result:

- Desktop browser URL: `http://127.0.0.1:8000/`
- Android emulator URL: `http://10.0.2.2:8000/`
- Physical phone URL candidate: `http://192.168.137.142:8000/`
- `DEBUG=True`
- `LOCAL_MOBILE_TESTING=True`
- `ALLOWED_HOSTS=127.0.0.1, localhost, testserver, 10.0.2.2, 192.168.137.142`
- Enabled mobile form schemas: 22
- Health endpoint result: OK for `/api/mobile/v1/health/`

## Demonstration Script

1. Start backend with `python manage.py runserver 0.0.0.0:8000`.
2. Open desktop platform and log in as authorised staff.
3. Open Android app using emulator URL or same-Wi-Fi phone URL.
4. Log in from the mobile app.
5. Fetch bootstrap, forms, and lookups.
6. Create a draft submission.
7. Attach a document/photo.
8. Sync to backend.
9. Confirm the desktop Mobile Intake Review Queue receives the submission.
10. Accept, reject, or request correction from the desktop review interface.
11. Refresh the Android status inbox and confirm backend status is returned.
""",
    )

    write(
        PACK / "06_user_acceptance_testing_report_template.md",
        f"""
# 06 User Acceptance Testing Report Template

Prepared: {DATE}

## Purpose

This report is for registrar, system admin, finance, data-quality, professional user, public user, and mobile-app acceptance testing before formal platform valuation or production launch.

## UAT Sign-Off Matrix

| Area | Role Responsible | Test Status | Evidence | Sign-Off |
| --- | --- | --- | --- | --- |
| Public home and public register search | Public/Registrar | Pending | Screenshot/search result | |
| Nursing Council registration pathway | Nursing Registrar | Pending | Application record and approval log | |
| Medical Board registration pathway | Medical Board Registrar | Pending | Application record and approval log | |
| Staff account approval workflow | Registrar/System Admin | Pending | Notification and account status | |
| Professional user account linking | Registrar/Professional user | Pending | Linked profile and record | |
| Mobile app submission sync | Mobile tester/Registrar | Pending | Mobile submission and desktop review queue | |
| Document repository upload/version/approval | Records officer | Pending | Document audit log | |
| Complaints/discipline/decision workflow | Registrar/Reviewer | Pending | Case and decision record | |
| Duplicate/missing-data review | Data Quality Officer | Pending | Reviewed queue item | |
| Receipts and finance view | Finance Officer | Pending | Receipt record/report | |
| Reports/export functions | Registrar/Admin | Pending | PDF/Excel/DOCX export | |
| Security login/MFA/password reset | System Admin | Pending | Audit event/log | |

## UAT Result

- Overall status: Pending formal user sign-off.
- Known blockers: To be completed during live UAT.
- Reviewer comments: To be added.
- Final decision: Approve / approve with conditions / reject.
""",
    )

    write(
        PACK / "07_security_privacy_assessment_report.md",
        f"""
# 07 Security And Privacy Assessment Report

Prepared: {DATE}

## Assessment Position

This is an internal readiness assessment, not an independent penetration test. The existing government launch package already includes a security and privacy controls matrix and role access matrix. Formal valuation should still require independent security review before the highest valuation range is defended.

## Positive Evidence

- Role-based dashboard access and office separation for Nursing Council and Medical Board workflows.
- Staff account approval workflow and operational access requests.
- MFA readiness for privileged roles in production configuration.
- Password reset and login controls.
- Security audit event model.
- Document repository audit events and approval/rejection workflow.
- Application status history and regulatory audit logs.
- Public-safe register search separated from staff-only records.
- Local mobile testing mode separated from production guidance.

## Required Production Evidence

- Independent vulnerability scan.
- Independent penetration test.
- HTTPS certificate and approved production domain.
- Production email configuration.
- Secure secret/environment variable management.
- Backup and restore drill evidence.
- Privacy impact assessment for practitioner and applicant records.
- Role/access review signed by both registrars and system admin.
- Incident response and breach notification procedure.

## Framework Reference

NIST Cybersecurity Framework 2.0 is used as the assessment reference for governance, risk management, access control, protection, detection, response, and recovery evidence.
""",
    )

    write(
        PACK / "08_data_migration_and_cleansing_report.md",
        f"""
# 08 Data Migration And Cleansing Report

Prepared: {DATE}

## Data Evidence Summary

The platform includes data import, cleansing, analytics snapshot, duplicate review, missing-data review, source traceability, and receipt ownership linkage functions. Existing test output confirms import paths for Nursing Council lifecycle snapshot data and Catherine licence verification overlay logic were exercised during the test suite.

## Observed Test Evidence

The successful test run exercised workflows that printed evidence such as:

- Nursing Council analytics snapshot imports.
- Lifecycle KPI summaries including total lifecycle records, ATP records, provisional records, full licence records, data-quality health score, and practitioner match groups.
- Catherine Nursing licence verification overlay import/reuse.
- Receipt ownership linkage and high-value review routing.

## Data Governance Principle

Imported rows should not be automatically treated as legal registry records. They are staged, validated, cleansed, reviewed, approved, and then promoted into operational records where authorised.

## Required Formal Evidence

- Source workbook/data register.
- Import batch log.
- Source hash or file fingerprint.
- Row counts imported, rejected, staged, cleansed, and promoted.
- Duplicate review decisions.
- Missing-data review decisions.
- Registrar approval evidence for promoted legal records.
- Data dictionary and field mapping.
- Public/private data classification.
""",
    )

    write(
        PACK / "09_training_guides_and_operational_manuals.md",
        f"""
# 09 Training Guides And Operational Manuals

Prepared: {DATE}

## Existing Documentation Evidence

The project already contains a government launch package and operational documentation under `docs/`.

Key existing documents include:

- `docs/government_launch_package/01_system_requirements.md`
- `docs/government_launch_package/02_technical_architecture.md`
- `docs/government_launch_package/03_data_governance_and_dictionary.md`
- `docs/government_launch_package/04_security_privacy_controls_matrix.md`
- `docs/government_launch_package/05_role_access_matrix.md`
- `docs/government_launch_package/06_workflow_engine_spec.md`
- `docs/government_launch_package/07_document_records_management_sop.md`
- `docs/government_launch_package/08_testing_qa_uat_checklist.md`
- `docs/government_launch_package/09_deployment_backup_support_plan.md`
- `docs/government_launch_package/10_staff_training_guide.md`
- `docs/government_launch_package/11_maintenance_sla_change_request.md`
- `docs/government_launch_package/12_gap_register_and_modular_roadmap.md`
- `docs/government_launch_package/13_enterprise_ui_design_standard.md`
- `docs/government_launch_package/14_ai_staff_assistant_and_import_cleansing.md`
- `docs/government_launch_package/15_free_local_gpt_setup.md`
- `docs/LOCAL_MOBILE_INTEGRATED_TESTING.md`
- `docs/FULL_PLATFORM_USER_GUIDE_20260601.md`
- `docs/PHASE1_PHASE2_TEST_GUIDE.md`

## Operational Manual Gaps To Finalise

- Production runbook with named owners.
- Registrar daily operations checklist.
- Finance officer receipt review checklist.
- Data quality officer cleansing checklist.
- Mobile app field-user quick guide.
- Disaster recovery drill result.
- Helpdesk escalation and incident response procedure.
""",
    )

    write(
        PACK / "10_maintenance_and_support_plan.md",
        f"""
# 10 Maintenance And Support Plan

Prepared: {DATE}

## Support Model

The platform should have a formal support model because it performs regulatory operations and contains sensitive professional/applicant records.

## Recommended Roles

- System owner: NDOH/regulatory bodies executive sponsor.
- Business owners: Nursing Council Registrar and Medical Board Registrar.
- Technical owner: System Admin/NDOH ICT.
- Application support: developer or contracted support team.
- Data quality owner: designated data quality officer.
- Security owner: NDOH ICT/security lead.
- Records owner: document repository/records officer.

## Support Tiers

| Tier | Scope | Target |
| --- | --- | --- |
| Tier 1 | User support, password help, navigation, basic form issues | Same business day |
| Tier 2 | Workflow, data, document, receipt, role/access, and mobile sync issues | 1-3 business days |
| Tier 3 | Code defects, deployment, integrations, security, backups, performance | As prioritised by severity |

## Maintenance Activities

- Monthly backup verification.
- Quarterly access review.
- Quarterly dependency/security update review.
- Quarterly data-quality review.
- Annual vulnerability scan and penetration test.
- Annual disaster recovery drill.
- Annual review of fee structures, pathways, forms, role matrix, and public register content.

## Budget Assumption

Annual maintenance should be budgeted at approximately 15%-25% of the original development/replacement value, adjusted upward for high-compliance, security-sensitive, or under-documented environments.
""",
    )

    write(
        PACK / "11_exchange_rate_and_market_cost_assumptions.md",
        f"""
# 11 Exchange-Rate And Market-Cost Assumptions

Prepared: {DATE}

## Exchange Rate

Bank of Papua New Guinea showed Kina Exchange Rate USD 0.2288, last updated 08 June 2026. This implies approximately K4.37 per USD.

Formula: 1 / 0.2288 = 4.3706 PGK per USD.

Source: https://www.bankpng.gov.pg/

## Government Cost Estimation Reference

The GAO Cost Estimating and Assessment Guide is used as a public-sector reference for reliable, documented, risk-aware program cost estimates, including software cost estimating and analysis of alternatives.

Source: https://www.gao.gov/products/gao-20-195g

## Intangible Asset Reference

IFRS IAS 38 is used as the reference for internally generated intangible assets and software/development expenditure recognition. Formal accounting treatment should be confirmed by finance/audit professionals.

Source: https://www.ifrs.org/issued-standards/list-of-standards/ias-38-intangible-assets/

## Cybersecurity Reference

NIST Cybersecurity Framework 2.0 is used as the security-readiness reference for reducing cybersecurity risk.

Source: https://www.nist.gov/cyberframework

## Market-Cost Benchmarks

- FWC 2026 app cost guide lists enterprise/regulated apps such as healthtech at approximately USD $500k-$1.2m+ for US onshore builds, with maintenance around 15%-20% per year.
- AppStudio 2026 enterprise mobile app guide lists custom enterprise mobile solutions around USD $100k-$500k, and mission-critical/regulated systems around USD $400k-$1m+.
- Adevs 2026 software maintenance guide lists annual maintenance commonly around 15%-25% of original development budget.

Sources:

- https://fwctecnologia.com/en/blog/post/app-development-cost-us-2026
- https://www.appstudio.ca/blog/enterprise-app-development-cost/
- https://adevs.com/blog/software-maintenance-costs/

## Assumption Warning

These are benchmark assumptions for valuation support, not binding quotes. A formal procurement valuation should obtain vendor quotes, confirm exchange rates on the pricing date, and apply PNG public-sector procurement rules.
""",
    )


def make_docx(
    screenshots_count: int,
    diagrams_count: int,
    models_count: int,
    routes_count: int,
    runtime_files: int,
    runtime_loc: int,
    evidence_files: int,
    evidence_loc: int,
) -> Path:
    ns_w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

    def xesc(value: str) -> str:
        return html.escape(str(value), quote=False)

    def run(text: str, bold: bool = False, size: int | None = None, color: str | None = None) -> str:
        props = []
        if bold:
            props.append("<w:b/>")
        if size:
            props.append(f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>')
        if color:
            props.append(f'<w:color w:val="{color}"/>')
        rpr = f"<w:rPr>{''.join(props)}</w:rPr>" if props else ""
        return f'<w:r>{rpr}<w:t xml:space="preserve">{xesc(text)}</w:t></w:r>'

    def para(text: str = "", style: str | None = None, bold: bool = False, size: int | None = None, color: str | None = None, after: int = 140) -> str:
        ppr = [f'<w:spacing w:after="{after}"/>']
        if style:
            ppr.insert(0, f'<w:pStyle w:val="{style}"/>')
        return f"<w:p><w:pPr>{''.join(ppr)}</w:pPr>{run(text, bold=bold, size=size, color=color)}</w:p>"

    def bullet(text: str) -> str:
        return para("- " + text, after=60)

    def table(rows: list[list[str]], widths: list[int]) -> str:
        grid = "".join(f'<w:gridCol w:w="{width}"/>' for width in widths)
        border = (
            '<w:tblBorders><w:top w:val="single" w:sz="8" w:space="0" w:color="B8C7D3"/>'
            '<w:left w:val="single" w:sz="8" w:space="0" w:color="B8C7D3"/>'
            '<w:bottom w:val="single" w:sz="8" w:space="0" w:color="B8C7D3"/>'
            '<w:right w:val="single" w:sz="8" w:space="0" w:color="B8C7D3"/>'
            '<w:insideH w:val="single" w:sz="8" w:space="0" w:color="B8C7D3"/>'
            '<w:insideV w:val="single" w:sz="8" w:space="0" w:color="B8C7D3"/></w:tblBorders>'
        )
        xml = [f'<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/><w:tblLayout w:type="fixed"/>{border}</w:tblPr><w:tblGrid>{grid}</w:tblGrid>']
        for row_index, row in enumerate(rows):
            xml.append("<w:tr>")
            for col_index, cell in enumerate(row):
                shade = '<w:shd w:fill="EAF2F7"/>' if row_index == 0 else ""
                xml.append(f'<w:tc><w:tcPr><w:tcW w:w="{widths[col_index]}" w:type="dxa"/>{shade}</w:tcPr>{para(cell, bold=(row_index == 0), after=45)}</w:tc>')
            xml.append("</w:tr>")
        xml.append("</w:tbl>")
        return "".join(xml)

    body: list[str] = []
    body.append(para("Formal Valuation Evidence Pack", style="Title", bold=True, size=40, color="0B2A45", after=100))
    body.append(para("PNG Medical Board & Nursing Council Regulatory Agencies Platform", style="Subtitle", size=24, color="145A63", after=100))
    body.append(para(f"Prepared: {DATE}", color="4B6475", after=220))
    body.append(para("Purpose", style="Heading1", bold=True, size=28, color="0B2A45"))
    body.append(para("This evidence pack supports a formal valuation discussion for the platform. It brings together feature evidence, architecture, database/entity inventory, code metrics, test results, mobile API evidence, UAT requirements, security/privacy readiness, data migration and cleansing evidence, training documentation, maintenance planning, and exchange-rate/market-cost assumptions."))
    body.append(para("Evidence Status", style="Heading1", bold=True, size=28, color="0B2A45"))
    body.append(
        table(
            [
                ["Evidence item", "Prepared status"],
                ["System feature list and screenshots", f"Prepared; {screenshots_count} screenshots copied"],
                ["Architecture diagram and deployment model", f"Prepared; {diagrams_count} existing diagrams copied plus Mermaid diagrams"],
                ["Database/entity overview", f"Prepared; {models_count} model/entity classes identified"],
                ["Code inventory and test report", "Prepared; 225 Django tests passed in 643.567 seconds"],
                ["Mobile app/API demonstration evidence", "Prepared; local helper confirmed 22 mobile schemas and health endpoint OK"],
                ["UAT report", "Template prepared; formal sign-off pending"],
                ["Security/privacy assessment", "Internal readiness prepared; independent scan/penetration test pending"],
                ["Data migration and cleansing report", "Prepared from import/cleansing capabilities and test output"],
                ["Training and operational manuals", "Existing launch-package docs indexed"],
                ["Maintenance/support plan", "Prepared"],
                ["Exchange-rate and market-cost assumptions", "Prepared using current web sources checked on June 9, 2026"],
            ],
            [4200, 6200],
        )
    )
    body.append(para("Technical Evidence Summary", style="Heading1", bold=True, size=28, color="0B2A45"))
    body.append(
        table(
            [
                ["Metric", "Value"],
                ["Runtime app source files", str(runtime_files)],
                ["Runtime app source lines", f"{runtime_loc:,}"],
                ["Broader evidence/source/docs inventory files", str(evidence_files)],
                ["Broader evidence/source/docs inventory lines", f"{evidence_loc:,}"],
                ["Model/entity classes", str(models_count)],
                ["URL route declarations captured", str(routes_count)],
                ["Django tests", "225 passed"],
                ["Mobile form schemas", "22 enabled"],
            ],
            [4300, 6200],
        )
    )
    body.append(para("Key Platform Evidence", style="Heading1", bold=True, size=28, color="0B2A45"))
    for item in [
        "Two-agency regulatory platform for Nursing Council and Medical Board functions.",
        "Role-based portals for public, professional, registrar/staff, finance, data quality, reviewer, and system admin users.",
        "Public register search, maps, public FAQ/forum, and public-safe verification services.",
        "Application, licence, ATP/practising certificate, records hub, receipt, document, complaint, and decision-register workflows.",
        "Mobile intake API for Android app connection and local same-Wi-Fi testing.",
        "Data import, cleansing, duplicate review, missing-data review, analytics snapshots, and NHWA reporting layer.",
        "Government launch package with architecture, security, role access, testing, deployment, training, maintenance, and AI assistant documentation.",
    ]:
        body.append(bullet(item))
    body.append(para("Qualification", style="Heading1", bold=True, size=28, color="0B2A45"))
    body.append(para("This is an internal evidence pack, not an independent valuation, audit, legal certification, or procurement quote. The highest valuation range should be defended only after independent security testing, formal UAT sign-off, production hosting evidence, and registrar/system-owner acceptance.", bold=True, color="0B2A45"))
    body.append(para("References", style="Heading1", bold=True, size=28, color="0B2A45"))
    for item in [
        "Bank of Papua New Guinea exchange rate: https://www.bankpng.gov.pg/",
        "GAO Cost Estimating and Assessment Guide: https://www.gao.gov/products/gao-20-195g",
        "IFRS IAS 38 Intangible Assets: https://www.ifrs.org/issued-standards/list-of-standards/ias-38-intangible-assets/",
        "NIST Cybersecurity Framework: https://www.nist.gov/cyberframework",
        "FWC 2026 app cost guide: https://fwctecnologia.com/en/blog/post/app-development-cost-us-2026",
        "AppStudio 2026 enterprise app development cost guide: https://www.appstudio.ca/blog/enterprise-app-development-cost/",
        "Adevs 2026 software maintenance guide: https://adevs.com/blog/software-maintenance-costs/",
    ]:
        body.append(bullet(item))

    sect = '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1200" w:right="1000" w:bottom="1200" w:left="1000" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>'
    document_xml = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="{ns_w}" xmlns:xml="http://www.w3.org/XML/1998/namespace"><w:body>{"".join(body)}{sect}</w:body></w:document>'
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>"""
    doc_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""
    styles = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{ns_w}">
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:rFonts w:ascii="Aptos" w:hAnsi="Aptos"/><w:sz w:val="22"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="40"/><w:color w:val="0B2A45"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:basedOn w:val="Normal"/><w:rPr><w:sz w:val="24"/><w:color w:val="145A63"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="28"/><w:color w:val="0B2A45"/></w:rPr></w:style>
</w:styles>"""
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    core = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>Formal Valuation Evidence Pack</dc:title>
  <dc:subject>PNG Medical Board and Nursing Council Regulatory Agencies Platform</dc:subject>
  <dc:creator>Codex</dc:creator>
  <cp:lastModifiedBy>Codex</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">{created}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{created}</dcterms:modified>
</cp:coreProperties>"""
    app = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Codex OpenXML Generator</Application>
</Properties>"""

    docx_path = PACK / "formal_valuation_evidence_pack_summary.docx"
    with ZipFile(docx_path, "w", ZIP_DEFLATED) as zip_file:
        zip_file.writestr("[Content_Types].xml", content_types)
        zip_file.writestr("_rels/.rels", rels)
        zip_file.writestr("word/document.xml", document_xml)
        zip_file.writestr("word/_rels/document.xml.rels", doc_rels)
        zip_file.writestr("word/styles.xml", styles)
        zip_file.writestr("docProps/core.xml", core)
        zip_file.writestr("docProps/app.xml", app)
    return docx_path


def make_zip() -> Path:
    zip_path = ROOT / "generated_reports" / "formal_valuation_evidence_pack_20260609.zip"
    if zip_path.exists():
        zip_path.unlink()
    with ZipFile(zip_path, "w", ZIP_DEFLATED) as zip_file:
        for file in PACK.rglob("*"):
            if file.is_file():
                zip_file.write(file, file.relative_to(PACK.parent))
    return zip_path


def main() -> None:
    if PACK.exists():
        pack_resolved = PACK.resolve()
        allowed_parent = (ROOT / "generated_reports").resolve()
        if allowed_parent not in pack_resolved.parents:
            raise RuntimeError(f"Refusing to rebuild unexpected pack path: {pack_resolved}")
        shutil.rmtree(PACK)
    PACK.mkdir(parents=True, exist_ok=True)
    screenshots_count, diagrams_count = copy_evidence_assets()
    models = build_model_inventory()
    routes = build_route_inventory()
    runtime_files, runtime_loc, evidence_files, evidence_loc = build_code_inventory()
    write_markdown_reports(
        screenshots_count,
        diagrams_count,
        models,
        routes,
        runtime_files,
        runtime_loc,
        evidence_files,
        evidence_loc,
    )
    docx_path = make_docx(
        screenshots_count,
        diagrams_count,
        len(models),
        len(routes),
        runtime_files,
        runtime_loc,
        evidence_files,
        evidence_loc,
    )
    zip_path = make_zip()
    print(f"PACK={PACK}")
    print(f"DOCX={docx_path}")
    print(f"ZIP={zip_path}")
    print(
        "SUMMARY="
        f"screenshots:{screenshots_count}; diagrams:{diagrams_count}; "
        f"models:{len(models)}; routes:{len(routes)}; "
        f"runtime_files:{runtime_files}; runtime_loc:{runtime_loc}; "
        f"evidence_files:{evidence_files}; evidence_loc:{evidence_loc}"
    )


if __name__ == "__main__":
    main()
