# 04 Security and Privacy Controls Matrix

## Standards Used

| Standard | Why it matters |
|---|---|
| NIST Cybersecurity Framework 2.0 | Provides governance, identify, protect, detect, respond, and recover structure. |
| NIST Secure Software Development Framework SP 800-218 | Provides secure development and release practices. |
| OWASP ASVS | Provides application security verification controls. |
| OWASP Top 10 | Covers common web application risks. |
| PNG Digital Government / DICT direction | Aligns hosting, cyber security, and public-sector digital operations with national direction. |

## Control Matrix

| Control area | Government-grade requirement | Platform status | Launch action |
|---|---|---|---|
| Governance | Security and privacy ownership must be assigned. | Documentation package added. | Assign NDOH ICT owner, System Admin owner, and registrar data owners. |
| MFA | System Admin and Registrar roles must use MFA. | Production-toggle email MFA implemented through `REQUIRE_STAFF_MFA=true`. | Configure production email and enable setting before go-live. |
| Role-based access | Access must be enforced in backend checks. | Implemented foundation through central role checks and scoped views. | Continue adding tests for every new workflow. |
| Admin access | Backend console must be restricted. | System Admin-only access is enforced. | Verify production superuser list monthly. |
| Password reset | Password reset must be secure and non-disclosing. | Implemented with reset tokens and neutral missing-email behavior. | Configure production email and monitor reset events. |
| Session security | Sessions must expire and avoid cached private pages. | 15-minute idle timeout and no-cache headers exist. | Confirm production timeout policy with NDOH ICT. |
| HTTPS | Production must use HTTPS only. | Security settings support `USE_HTTPS=true`. | Install certificate, enable secure cookies, HSTS, and redirect. |
| Secure cookies | Cookies must be secure and HTTP-only where appropriate. | Settings support secure cookies and HTTP-only session cookie. | Enable `USE_HTTPS=true`, `SESSION_COOKIE_SECURE=true`, `CSRF_COOKIE_SECURE=true`. |
| Audit logs | Sensitive actions must be traceable. | Workflow, document, and security audit foundations exist. | Extend audit coverage to every export/import/data-edit endpoint. |
| Document privacy | Documents must be scoped and audited. | Office-scoped repository with audit events exists. | Train staff to store official evidence only in scoped folders. |
| Public privacy | Public register must expose safe fields only. | Implemented foundation. | Review public-field policy with legal/regulatory owners. |
| Data imports | Imported data must not become trusted automatically. | Import/audit/data-quality commands exist. | Formalize staging approval workflow in operations. |
| Vulnerability scanning | Scan before handover. | Not an internal code-only task. | Run dependency and web vulnerability scans before production. |
| Penetration test | Independent test before launch. | Not an internal code-only task. | Engage independent tester and remediate findings. |
| Backup and recovery | Backups must be tested. | Documented in this package. | Run monthly restore drill and record evidence. |
| Monitoring | Production errors and security events must be reviewed. | Security audit model added. | Add production log aggregation and alerting. |

## Production Environment Security Settings

Set these before launch:

```env
DEBUG=False
USE_HTTPS=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS=True
SECURE_HSTS_PRELOAD=True
REQUIRE_STAFF_MFA=True
STAFF_MFA_TIMEOUT_SECONDS=600
ALLOWED_HOSTS=approved-domain.gov.pg
CSRF_TRUSTED_ORIGINS=https://approved-domain.gov.pg
```

## MFA Operating Rule

- MFA is mandatory for System Admin and Registrar roles in production.
- Verification codes must be sent to approved official email accounts.
- Staff without email addresses must not be granted production System Admin or Registrar access.
- MFA challenge and verification events are recorded in security audit logs.

## Privacy Rules

Never expose these through public search:

- Date of birth.
- Phone number.
- Email address.
- Home address.
- Passport number.
- Police clearance.
- Medical report.
- Academic transcript.
- Receipt image.
- Internal review notes.

## Pre-Launch Security Checklist

- Production `DEBUG=False`.
- HTTPS certificate installed.
- Secure cookies enabled.
- MFA enabled for System Admin and Registrars.
- Admin console tested with System Admin only.
- Reviewer/finance/data-quality restrictions tested.
- Public register privacy tested.
- Password reset tested using production email.
- Backup restore tested.
- Vulnerability scan completed.
- Penetration test completed.
- Critical/high findings remediated.
- Security sign-off recorded.
