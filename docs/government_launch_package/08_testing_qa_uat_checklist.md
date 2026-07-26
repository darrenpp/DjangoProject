# 08 Testing, QA, and UAT Checklist

## Testing Principle

A government-grade system is not proven only by clicking screens. It needs repeatable test evidence, role-based access tests, import tests, report tests, security tests, and signed UAT.

## Automated Test Evidence

Run before handover:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test apps.accounts.tests apps.dashboard.tests apps.workforce.tests apps.notifications.tests apps.documents.tests apps.complaints --keepdb
```

## Unit Test Areas

- User registration.
- Password reset.
- MFA challenge and verification.
- Role access helpers.
- Workflow validation rules.
- Document repository permissions.
- Document audit events.
- Document approval and rejection sign-off.
- Formal ICMS complaint case permissions and workflow.
- Disciplinary case escalation and workflow.
- Regulatory decision register creation and detail view.
- Nursing Council analytics snapshot summary and drilldown.
- Receipt-owner matching and unmatched review routing.
- Forum, FAQ, and map role/public visibility.
- NHWA workbook bootstrap and population permissions.
- Financial report calculations.
- Data-quality duplicate detection.
- Notification read/opened status and unread bell clearing.
- Public registration Role/Cadre dropdown routing.
- Records Hub DataTables and registrar CRUD action visibility.
- Duplicate Review Queue DataTables and review actions.

## Integration Test Areas

- Login -> MFA -> dashboard.
- Application submission -> checklist -> review -> registrar decision.
- Receipt verification -> registrar review unlock.
- Document upload -> metadata -> version -> download -> audit trail.
- Import -> missing-data audit -> duplicate review -> report refresh.
- Duplicate review queue -> search/sort/page -> grouped source row review -> mark reviewed/merged/reopen.
- Registrar opens applicant message -> sender sees opened/read status -> notification bell count clears.
- Public registration -> select CHW provisional or CHW full license -> account/application routes to the correct review path.
- Records Hub Nursing Professionals -> search/sort/page -> view/edit/add new according to role.
- Finance export -> audit timestamp/user -> return to correct page.
- Public register search -> safe public fields only.
- Public complaint submission -> ICMS case -> staff triage.
- Enquiry thread -> Open ICMS Case -> complaint case detail.
- ICMS case -> escalate to discipline -> disciplinary case detail.
- Discipline case -> regulatory decision record.
- Repository document -> upload version -> approve/reject -> audit event.
- Analytics chart/filter -> server-side drilldown -> Open fact detail.
- Receipt matching command -> linked records where high-confidence -> unmatched receipts in review.
- Map page -> reads locally stored coordinates and does not geocode on load.
- NHWA workbook -> populate from verified data -> review/sign-off -> export package.

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
| Operations-approved data-quality reviewer opens financial forecast | Allowed where role and scope permit |
| Finance user attempts CRUD registry edit | Denied |
| Public user opens repository document | Denied |
| System Admin opens secure administration console | Allowed |
| Registrar opens secure administration console | Denied |
| Public user opens public complaint form | Allowed |
| Public user opens staff ICMS register | Denied |
| Nursing registrar opens Nursing Council ICMS cases | Allowed |
| Medical-only user opens Nursing Council analytics drilldown | Denied unless authorised |
| Public user posts forum content | Saved for moderation |
| Public user opens private practitioner forum | Denied |

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
- Confirm analytics snapshot import creates one active Nursing Council snapshot.
- Confirm active snapshot KPIs match 34,851 lifecycle records, 19,998 ATP, 8,158 provisional, and 6,695 full licence.
- Confirm Catherine workbook import does not overwrite legal practitioner identity records.
- Confirm NHWA workbook population does not push values back into registry tables.

## Report Calculation Tests

Check:

- Live people counts are separate from imported rows.
- Receipt totals are separate from practitioner counts.
- Nursing Council finance is separate from Medical Board finance.
- Financial forecast route opens for authorised finance, registrar, System Admin, and approved operations/data-quality users as configured.
- Monthly totals use correct date fields.
- Yearly totals exclude bad future dates.
- Exported reports show source date, generation timestamp, and exporting user.
- Nursing Council dashboard states active analytics snapshot source and generated date.
- Reports distinguish legal registry tables from analytics snapshots, workbook imports, NHWA workbooks, and receipt ledgers.

## Security Tests

- Password reset does not disclose missing email addresses.
- System Admin and Registrar MFA works when `REQUIRE_STAFF_MFA=true`.
- Secure cookies enabled in production.
- CSRF protection works for POST forms.
- Admin console restricted to System Admin.
- Public register does not expose private fields.
- Access denied attempts are audited where implemented.
- Notification history and message thread opens clear unread counts.
- Registrar/admin notification history is available.
- Public forum and public complaint content does not publish or affect registry records without moderation.
- Complaint, discipline, and decision pages enforce office scope.
- Map page does not expose private practitioner details.

## Interface Regression Tests

- Nursing Council dashboard header shows `Welcome To Your PNG Nursing Council Online Platform Dashboard`.
- Medical Board dashboard header shows `Welcome To Your Medical Board Online Platform Dashboard`.
- Dashboard headers display the PNG emblem without cropping the main image beyond recognition.
- Registration page displays the emblem background and the form guide remains readable.
- Sign-in button text is visible.
- Standards and Compliance page does not repeat the standards header block.
- Duplicate Review Queue table has no full-width `colspan` detail row that would break DataTables.
- Nursing Professionals table includes pagination and CRUD controls for authorised registrar users.
- Nursing Council analytics area contains executive strip, charts, collapsed raw tables, and server-side drilldown URLs.
- Complaint, discipline, and decision registers have Open/detail actions.
- Document detail page shows approval history and approve/reject actions for authorised users.
- Public FAQ, forum, and map pages load without staff-only data leakage.

## UAT Sign-Off

| Sign-off role | Must test |
|---|---|
| Nursing Council Registrar | Nursing workflows, reports, approvals, repository evidence, public register |
| Medical Board Registrar | Medical workspace separation, medical reports, approvals, finance separation |
| Finance Officer | Nursing and Medical financial forecasts, exports, receipt explanations |
| Data Quality Officer | Missing-data audit, duplicate review, source traceability, cleansing SOP |
| ICMS / Reviewer Staff | Complaint triage, enquiry escalation, discipline escalation, decision evidence |
| System Admin | User roles, MFA, admin console, backups, deployment checklist |

## UAT Decision

Use one of these outcomes:

- Approved for production.
- Approved with minor issues.
- Not approved until listed issues are fixed.

All issues must have owner, severity, target date, and closure evidence.
