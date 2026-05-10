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
| Public user | Home page, public register search, public forms, account registration | Private records, staff dashboards, documents, receipts, imports | No |
| Nurse / Midwife / Nurse Aide | Own profile, own applications, own receipts, own messages, public guidance | Other practitioners, staff tools, exports, records hub | No |
| Graduand | Own graduand dashboard, own provisional pathway information, own applications | Staff dashboards, registrar decisions, imports | No |
| Doctor / CHW | Own Medical Board/CHW profile and applications | Nursing Council records, staff tools, other users | No |
| Reviewer | Assigned dashboard review view, staff inbox, AI Staff Assistant, limited review queues | Registrar approvals, imports, exports, operational command buttons, admin console | Yes, for elevated operations |
| Data Quality Officer | Duplicate review, missing-data review, Records Hub corrections where allowed | Registrar decisions, routine licence issue, System Admin tools | Yes, for elevated operations |
| Finance Officer | Workforce Flow, Nursing Council Financial Forecast, Medical Board Financial Forecast, finance exports | CRUD registry edits, imports, registrar approvals, admin console | Yes, for elevated operations |
| Nursing Council Registrar | Nursing Council dashboard, applications, receipts, documents, imports, reports, approvals | Medical Board private workspace unless authorised, System Admin configuration | MFA required in production |
| Medical Board Registrar | Medical Board dashboard, applications, receipts, documents, imports, reports, approvals | Nursing Council private workspace unless authorised, System Admin configuration | MFA required in production |
| System Admin | Secure Administration Console, user management, security settings, configuration, audit review | Routine regulatory approvals unless formally delegated | MFA required in production |

## Admin Console Rule

The secure administration console is reserved for System Admin only.

Registrars should use their registrar dashboards for normal operations. This keeps system configuration separate from regulatory decision-making.

## Operational Access Requests

Reviewer-style users request elevated access through My Profile.

Approval path:

```text
Reviewer submits request
  -> registrar/System Admin receives notification
  -> registrar/System Admin reviews reason
  -> approve or reject
  -> decision is recorded
  -> user access changes only if approved
```

## Finance Separation

Finance users may view both finance pages, but each page must remain office-scoped:

- `/dashboard/reports/financial/?office=nursing`
- `/dashboard/reports/financial/?office=medical`

Nursing Council and Medical Board receipts must not be merged into one uncontrolled total.

## Public Register Rule

Public register output is a safe view. It must not expose private identity, contact, medical, police, transcript, receipt, or internal review information.
