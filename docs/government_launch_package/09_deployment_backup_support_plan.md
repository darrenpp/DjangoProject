# 09 Deployment, Backup, and Support Plan

## Environment Model

| Environment | Purpose | Data rule |
|---|---|---|
| Development | Build and local testing | May use sanitized sample data |
| Staging / UAT | Registrar and staff testing before release | Use controlled copy or sanitized production-like data |
| Production | Live government operations | Real data only; restricted access |
| Backup / Restore | Recovery testing | Encrypted backup copies; tested monthly |

## Release Flow

```text
Development change
  -> automated checks
  -> developer testing
  -> staging deployment
  -> UAT sign-off
  -> production deployment window
  -> post-deployment smoke test
  -> release notes filed
```

## Production Deployment Requirements

- NDOH ICT hosting approval.
- Approved domain and HTTPS certificate.
- PostgreSQL production database.
- Secure media/document storage.
- SMTP email service for password reset and MFA.
- Backup location separate from production server.
- Environment variables configured securely.
- `DEBUG=False`.
- `REQUIRE_STAFF_MFA=True`.
- System Admin account confirmed.
- Test/default passwords removed.

## Backup Plan

Backup these:

- PostgreSQL database.
- Media/document uploads.
- Environment configuration record.
- Static release package.
- Generated official reports where required.

Minimum schedule:

- Daily database backup.
- Daily media backup.
- Weekly full backup.
- Monthly restore drill.
- Backup retention aligned with NDOH ICT policy.

## Restore Drill

Monthly:

1. Select latest backup.
2. Restore into backup/restore environment.
3. Confirm login works.
4. Confirm dashboards load.
5. Confirm repository documents open.
6. Confirm reports generate.
7. Record restore start time, finish time, and issues.
8. File restore evidence.

## Monitoring

Monitor:

- Login failures.
- MFA failures.
- Admin console access.
- Import errors.
- Report/export failures.
- Background command failures.
- Database storage usage.
- Media storage usage.
- Backup success/failure.
- Application errors.

## Production Smoke Test

After deployment:

- Open home page.
- Log in as System Admin using MFA.
- Log in as Nursing Registrar using MFA.
- Open Nursing Council dashboard.
- Open Medical Board dashboard.
- Open financial forecast for Nursing.
- Open financial forecast for Medical.
- Open document repository.
- Run public register search.
- Confirm `/admin/` denies non-System Admin users.

## Support Channels

Recommended:

- Level 1: Registrar office super users.
- Level 2: System Admin / ICT application support.
- Level 3: Developer/vendor technical support.

## Incident Categories

| Severity | Example | Response target |
|---|---|---|
| Critical | System unavailable, data exposure, login outage | Immediate response |
| High | Registrar cannot approve, finance exports broken, document repository inaccessible | Same business day |
| Medium | Report display issue, single workflow bug, import row issue | 2-3 business days |
| Low | Text correction, minor UI improvement, non-urgent enhancement | Planned release |

## Disaster Recovery Objective

Initial recommended targets:

- Recovery Time Objective: within 24 hours for controlled launch.
- Recovery Point Objective: last daily backup.

These targets should be tightened after NDOH ICT confirms infrastructure and staffing.
