# 06 Workflow Engine Specification

## Core Workflow Rule

No silent approvals. No undocumented edits. Every official decision must have status history and audit evidence.

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
