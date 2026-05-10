# 11 Maintenance, SLA, and Change Request Model

## Maintenance Purpose

Maintenance keeps the platform stable, secure, updated, backed up, and aligned with changing regulatory operations.

## Monthly Maintenance Tasks

- Review user accounts and access approvals.
- Review System Admin users.
- Review security audit events.
- Review failed login/MFA activity.
- Review backup success.
- Perform backup restore drill.
- Run missing-data audit.
- Run duplicate audit.
- Review finance date errors and suspicious receipt rows.
- Confirm reports generate correctly.
- Review document repository metadata gaps.
- Apply security patches and dependency updates.
- Update documentation where workflows changed.

## Recommended SLA

| Service item | Target |
|---|---|
| Critical production outage | Same-day emergency response |
| High-impact workflow failure | Same business day investigation |
| Medium issue | 2-3 business days |
| Low issue / wording / UI adjustment | Planned maintenance release |
| Monthly health check | Once per month |
| Backup restore test | Once per month |
| Security review | Quarterly or after major change |

## Change Request Process

```text
Request submitted
  -> classify as bug, enhancement, report, security, data, or training
  -> assess risk, affected roles, affected data, and estimated cost
  -> approve or reject
  -> implement in development
  -> test
  -> deploy to staging/UAT
  -> user sign-off
  -> deploy to production
  -> update documentation
```

## Change Request Form Fields

- Request title.
- Requested by.
- Date requested.
- Regulatory body affected.
- User roles affected.
- Description.
- Business reason.
- Urgency.
- Data affected.
- Reports affected.
- Privacy/security risk.
- Acceptance criteria.
- Approved by.
- Target release.
- Completion evidence.

## Pricing Model For Future Work

Recommended commercial structure:

- Monthly maintenance retainer.
- Separate fee for new modules.
- Separate fee for major data cleansing.
- Separate fee for training.
- Separate fee for penetration testing support/remediation.
- Separate fee for deployment/migration to NDOH ICT infrastructure.

## Change Categories

| Category | Example | Approval required |
|---|---|---|
| Bug fix | Broken export, incorrect redirect, chart loading issue | System Admin / product owner |
| Data correction | Cleansing duplicate or correcting institution | Registrar/data owner |
| Report update | New ministerial table or finance breakdown | Registrar/finance owner |
| Security change | MFA, access restriction, audit expansion | System Admin and NDOH ICT |
| New workflow | New pathway, new licence type, new approval step | Registrar and project owner |
| Infrastructure | Server, database, backup, domain, email | NDOH ICT |

## Release Notes

Every production release should record:

- Version/date.
- Changes included.
- Database migrations.
- Settings changed.
- Tests run.
- Known issues.
- Rollback plan.
- Approved by.
