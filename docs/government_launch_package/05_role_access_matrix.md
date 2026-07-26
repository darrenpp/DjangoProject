# 05 Role Access Matrix

## Access Principles

- Users must only access what their role and office scope require.
- Nursing Council users must not access Medical Board private records unless explicitly authorised.
- Medical Board users must not access Nursing Council private records unless explicitly authorised.
- Professionals and applicants can only access their own records.
- Finance users are read-only and must view Nursing Council and Medical Board finance separately.
- Reviewers must request approval before higher-risk operational tools unlock.
- System Admin manages configuration and security, not routine registrar decisions.

## Role Matrix

| Role | Can access | Cannot access | Approval required |
|---|---|---|---|
| Public user | Home page, public register search, public forms, account registration, FAQs, public map, moderated public forum, public complaint submission | Private records, staff dashboards, documents, receipts, imports, unmoderated forum publication | No |
| Nurse / Midwife / Nurse Aide | Own profile, own applications, own receipts, own messages, own notification history, public guidance, eligible practitioner forum areas | Other practitioners, staff tools, exports, records hub | No |
| Graduand | Own graduand dashboard, own provisional pathway information, own applications, own messages and notification history, eligible provisional/applicant forum areas | Staff dashboards, registrar decisions, imports | No |
| Doctor / CHW | Own Medical Board/CHW profile and applications, own messages and notification history | Nursing Council records, staff tools, other users | No |
| Reviewer | Assigned dashboard review view, staff inbox, notification history, AI Staff Assistant, limited review queues, assigned ICMS/discipline tasks | Registrar approvals, imports, exports, operational command buttons, admin console | Yes, for elevated operations |
| Data Quality Officer | Duplicate Review Queue, missing-data review, analytics snapshot drilldowns, receipt matching review, mapped reference cleanup, Records Hub corrections where allowed, scoped financial forecast where operations-approved | Registrar decisions, routine licence issue, System Admin tools | Yes, for elevated operations |
| Finance Officer | Workforce Flow, Nursing Council Financial Forecast, Medical Board Financial Forecast, finance exports, receipt-owner review where assigned | CRUD registry edits, imports, registrar approvals, admin console, practitioner clinical/demographic analytics outside approved finance scope | Yes, for elevated operations |
| Nursing Council Registrar | Nursing Council dashboard, applications, receipts, documents, imports, reports, approvals, ICMS, discipline, regulatory decisions, NHWA nursing workbooks | Medical Board private workspace unless authorised, System Admin configuration | MFA required in production |
| Medical Board Registrar | Medical Board dashboard, applications, receipts, documents, imports, reports, approvals, ICMS, discipline, regulatory decisions, NHWA medical workbooks | Nursing Council private workspace unless authorised, System Admin configuration | MFA required in production |
| System Admin | Secure Administration Console, user management, security settings, configuration, audit review, NHWA/bootstrap/map setup, forum/FAQ configuration | Routine regulatory approvals unless formally delegated | MFA required in production |

## Admin Console Rule

The secure administration console is reserved for System Admin only.

Registrars should use their registrar dashboards for normal operations. This keeps system configuration separate from regulatory decision-making.

## Operational Access Requests

Reviewer-style users request elevated access through My Profile.

Approval path:

```text
Reviewer submits request
  -> registrar/System Admin receives notification and bell count
  -> registrar/System Admin reviews reason
  -> approve or reject
  -> decision is recorded
  -> user access changes only if approved
```

Opening notification history or the related inbox thread should clear the unread notification count. Message senders should see opened/read status after the recipient opens the thread.

## Finance Separation

Finance users may view both finance pages, but each page must remain office-scoped:

- `/dashboard/reports/financial/?office=nursing`
- `/dashboard/reports/financial/?office=medical`

Nursing Council and Medical Board receipts must not be merged into one uncontrolled total.

## Public Registration Cadre Rule

The registration page must use controlled dropdown choices for Role and Cadre. CHW choices must distinguish:

- `Medical Board - CHW Provisional Registration`
- `Medical Board - CHW Full License`

This prevents provisional CHW applicants and already licensed CHW practitioners from being routed into the same review path.

## Public Register Rule

Public register output is a safe view. It must not expose private identity, contact, medical, police, transcript, receipt, or internal review information.

## ICMS, Forum, and Map Access

- Public complaint submissions are accepted through the public form, but staff must triage and moderate before any internal action changes a record.
- Public forum posts are moderated before display.
- Practitioner and applicant forums require login and matching role/stage where configured.
- Staff forums are internal-only.
- The public map shows reference schools, institutions, and facilities from stored coordinates only. It must not expose private practitioner details.
