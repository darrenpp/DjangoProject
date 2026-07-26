# 06 Workflow Engine Specification

## Core Workflow Rule

No silent approvals. No undocumented edits. Every official decision must have status history and audit evidence.

This applies to application decisions, complaint/discipline decisions, document sign-off, receipt-owner links, and NHWA/reporting sign-off.

## Standard Application Workflow

```text
Application submitted
  -> document checklist generated
  -> payment or waiver verified
  -> reviewer screening
  -> registrar decision
  -> licence issued, renewed, closed, rejected, or held
  -> public/statistical dashboard updated
  -> audit trail retained
```

## ICMS And Discipline Workflow

```text
Complaint / incident / enquiry
  -> ICMS case
  -> triage and assignment
  -> investigation notes and attachments
  -> resolved / closed / withdrawn
  -> disciplinary case where required
  -> committee review / hearing / decision
  -> regulatory decision record
  -> monitoring or closure
```

Rules:

- Public submissions do not change registry records automatically.
- Office scope must match the responsible regulatory body.
- High-risk or critical cases should be assigned and tracked until closure.
- Discipline escalation must preserve the source ICMS case link.
- Final outcomes must be recorded in the decision register when a defensible regulatory decision is required.

## Required Statuses

Recommended official status vocabulary:

- Draft.
- Submitted.
- Payment pending.
- Intake screening.
- Missing information.
- Data-quality review.
- Technical review.
- Supervisor review.
- Registrar review.
- ICMS triage.
- Investigation.
- Committee review.
- Hearing.
- Decision issued.
- Appeal / monitoring.
- Approved.
- Rejected.
- Withdrawn.
- Licence issued.
- Active.
- Renewal due.
- Expired.
- Suspended.
- Revoked.
- Deceased.

## Checklist Gating

An application should not move to registrar decision until:

- Required identity fields are complete.
- Required documents are uploaded or officially waived.
- Required receipt/payment is verified or waived.
- Duplicate checks are completed.
- Missing-data items are cleared or accepted with documented exception.
- Required competency or supervisor assessment is complete.
- Office scope is correct.

## Registrar Decision Controls

Registrar approval must:

- Update application status.
- Create status history.
- Create audit log.
- Issue, renew, close, or update licence record where applicable.
- Update dashboards and reports.
- Keep source evidence linked.

Registrar rejection must:

- Record reason.
- Update application status.
- Create status history.
- Create audit log.
- Notify applicant or staff queue where appropriate.

## Regulatory Decision Controls

A formal decision record should capture:

- Decision type and status.
- Subject name and identifier.
- Decision text.
- Rationale.
- Authority, policy, or SOP reference.
- Evidence summary.
- Conditions or restrictions.
- Appeal rights.
- Decision maker.
- Effective and expiry dates where applicable.

## Licence Lifecycle

```text
Provisional
  -> full registration
  -> practising licence renewal
  -> renewal due
  -> expired / suspended / revoked / deceased
```

Rules:

- One practitioner should not have duplicate active licence periods for the same office/category.
- Provisional licence should close when full registration is approved.
- Temporary licence must have start and end dates.
- Deceased practitioners must not renew unless registrar formally reopens the profile.

## Workflow Audit Events

Minimum events:

- Application created.
- Application submitted.
- Document uploaded.
- Document verified/rejected/waived.
- Payment verified/waived.
- Status changed.
- Data-quality issue created/resolved.
- Registrar approved.
- Registrar rejected.
- Licence created/renewed/expired/suspended/revoked.
- Practitioner marked deceased.
- Report exported.
- Complaint case created/updated/closed.
- Complaint escalated to discipline.
- Discipline case stage changed.
- Regulatory decision created/finalised.
- Document approved/rejected.
- Receipt linked to owner or routed for review.
- NHWA workbook populated/signed off/exported.

## Workflow Performance Measures

Track:

- Applications submitted this month.
- Pending intake screening.
- Pending payment verification.
- Pending registrar approval.
- Missing-information backlog.
- Duplicate-review backlog.
- Approved this month.
- Rejected this month.
- Average days from submitted to decision.
- Renewals due within 30/60/90 days.
- Open ICMS cases by risk and age.
- Open disciplinary cases by stage.
- Decisions missing authority/SOP reference.
- Documents awaiting approval/rejection.
- Receipts awaiting owner review.
- NHWA workbooks awaiting sign-off.
