# 08 Testing, QA, and UAT Checklist

## Testing Principle

A government-grade system is not proven only by clicking screens. It needs repeatable test evidence, role-based access tests, import tests, report tests, security tests, and signed UAT.

## Automated Test Evidence

Run before handover:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test apps.accounts.tests apps.dashboard.tests apps.workforce.tests apps.notifications.tests apps.documents.tests --keepdb
```

## Unit Test Areas

- User registration.
- Password reset.
- MFA challenge and verification.
- Role access helpers.
- Workflow validation rules.
- Document repository permissions.
- Document audit events.
- Financial report calculations.
- Data-quality duplicate detection.

## Integration Test Areas

- Login -> MFA -> dashboard.
- Application submission -> checklist -> review -> registrar decision.
- Receipt verification -> registrar review unlock.
- Document upload -> metadata -> version -> download -> audit trail.
- Import -> missing-data audit -> duplicate review -> report refresh.
- Finance export -> audit timestamp/user -> return to correct page.
- Public register search -> safe public fields only.

## Role Access Tests

| Test | Expected result |
|---|---|
| Nursing Registrar opens Nursing Council dashboard | Allowed |
| Nursing Registrar opens Medical Board private workflow | Denied unless authorised |
| Medical Board Registrar opens Medical Board dashboard | Allowed |
| Medical Board Registrar opens Nursing private workflow | Denied unless authorised |
| Reviewer opens operational command tools before approval | Locked |
| Finance user opens Workforce Flow | Allowed |
| Finance user opens Nursing financial forecast | Allowed |
| Finance user opens Medical financial forecast | Allowed |
| Finance user attempts CRUD registry edit | Denied |
| Public user opens repository document | Denied |
| System Admin opens secure administration console | Allowed |
| Registrar opens secure administration console | Denied |

## Import Tests

For each workbook:

- Upload sample.
- Confirm batch created.
- Confirm row count.
- Confirm source file and sheet captured.
- Confirm invalid rows flagged.
- Confirm duplicate candidates flagged.
- Confirm future-date errors flagged.
- Confirm no row is silently dropped.
- Confirm live registry totals update only after approved import/promotion process.

## Report Calculation Tests

Check:

- Live people counts are separate from imported rows.
- Receipt totals are separate from practitioner counts.
- Nursing Council finance is separate from Medical Board finance.
- Monthly totals use correct date fields.
- Yearly totals exclude bad future dates.
- Exported reports show source date, generation timestamp, and exporting user.

## Security Tests

- Password reset does not disclose missing email addresses.
- System Admin and Registrar MFA works when `REQUIRE_STAFF_MFA=true`.
- Secure cookies enabled in production.
- CSRF protection works for POST forms.
- Admin console restricted to System Admin.
- Public register does not expose private fields.
- Access denied attempts are audited where implemented.

## UAT Sign-Off

| Sign-off role | Must test |
|---|---|
| Nursing Council Registrar | Nursing workflows, reports, approvals, repository evidence, public register |
| Medical Board Registrar | Medical workspace separation, medical reports, approvals, finance separation |
| Finance Officer | Nursing and Medical financial forecasts, exports, receipt explanations |
| Data Quality Officer | Missing-data audit, duplicate review, source traceability, cleansing SOP |
| System Admin | User roles, MFA, admin console, backups, deployment checklist |

## UAT Decision

Use one of these outcomes:

- Approved for production.
- Approved with minor issues.
- Not approved until listed issues are fixed.

All issues must have owner, severity, target date, and closure evidence.
