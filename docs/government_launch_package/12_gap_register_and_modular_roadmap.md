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
| Data quality | Missing-data and duplicate-review tools exist. |
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
| Broader audit coverage still expanding | Medium | Add audit events to all imports, exports, and high-risk edits | Developer / System Admin |
| Live employment data still dependent on clean ATP/renewal capture | Medium | Continue ATP alignment and make renewal employment capture mandatory | Registrar / Data Quality |

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
- Duplicate-review SOP.
- Institution/facility/province normalization.

### Module 3: Workflow Control

Status: Started.

Deliverables:

- Checklist gating.
- Payment gating.
- Reviewer queue.
- Registrar approval.
- Licence lifecycle.
- Status history and audit trail.

### Module 4: Records Management

Status: Started.

Deliverables:

- Office-scoped repository.
- Metadata.
- Versions.
- OCR/search.
- Retention.
- Audit events.
- Link evidence to applications/practitioners.

### Module 5: Reporting and Finance

Status: Started.

Deliverables:

- Monthly analytics.
- Yearly analytics.
- Financial forecast.
- Export timestamp/user tracking.
- Source-date explanations.
- Ministerial/registrar brief generation.

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
