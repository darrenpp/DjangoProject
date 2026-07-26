# 10 Staff Training Guide

## Training Goal

Train staff to use the system as a controlled regulatory operations platform, not as a simple spreadsheet replacement.

## Training Groups

| Group | Training focus |
|---|---|
| Public/applicant support staff | Account help, password reset, public forms, applicant guidance |
| Registrars | Dashboards, approvals, reports, office separation, audit responsibility |
| Reviewers | Review queues, missing data, ICMS/discipline tasks, document checks, notification history, access-request process |
| Finance users | Receipt review, financial forecast, separated office finance, receipt-owner review, exports |
| Data-quality officers | Duplicate Review Queue, missing data, analytics snapshot drilldown, receipt matching, import source traceability, mapped references, Records Hub corrections where allowed |
| System Admin | Users, roles, MFA, secure console, backups, deployment checks, NHWA setup, map setup, FAQ/forum configuration |

## Core Messages For All Staff

- Do not mix Nursing Council and Medical Board data.
- Do not treat imported rows as automatically correct.
- Do not publish statistics before audit and review.
- Do not download or share confidential exports without approval.
- Use the document repository for official evidence.
- Use metadata so documents can be found later.
- Use the staff inbox/chat and notification history for auditable communication.
- Let unread notification counts clear through the proper read/opened workflow instead of ignoring stale badges.
- Use controlled Role/Cadre dropdown choices when helping public applicants register.
- Use the ICMS, discipline, and decision registers for complaints, conduct matters, and formal decisions.
- Do not use analytics snapshot rows, NHWA workbook values, or forum posts to overwrite legal registry records automatically.
- Use stored, verified coordinates for maps. Do not geocode every page load.

## Registrar Training

Registrars must be able to:

- Open their correct regulatory dashboard.
- Review application status.
- Check required documents.
- Confirm payment/waiver status.
- Review duplicate/missing data warnings.
- Use Duplicate Review Queue search, sort, page length, grouped source rows, and reviewed/merged/reopen actions.
- Use Records Hub table functions and CRUD actions only where authorised.
- Approve or reject with reason.
- Confirm licence/register update.
- Generate reports after data updates.
- Explain source dates and live counts.
- Open ICMS cases and disciplinary cases within office scope.
- Record formal regulatory decisions with rationale, authority/SOP reference, evidence summary, conditions, appeal rights, and effective dates.
- Approve or reject controlled repository documents.
- Use MFA in production.

## Reviewer Training

Reviewers must be able to:

- Understand what they can and cannot access.
- Submit operational access request if higher access is needed.
- Review assigned records.
- Check documents and metadata.
- Flag missing data.
- Open notification history and mailbox threads so unread counts and opened/read status update correctly.
- Open assigned ICMS or discipline tasks where delegated.
- Escalate matters only through the formal workflow.
- Avoid registrar-only decisions.

## Finance Training

Finance users must be able to:

- Open Nursing Council financial forecast.
- Open Medical Board financial forecast.
- Keep the two finance scopes separate.
- Understand manual receipts versus spreadsheet-imported receipts.
- Generate PDF/Excel/Word financial reports.
- Review receipt-owner links where delegated.
- Identify unmatched, duplicate, suspicious, or high-value receipts and route them for review.
- Explain monthly/yearly totals and data-source limitations.

## Data-Quality Training

Data-quality users must be able to:

- Run missing-data audits.
- Review duplicate candidates.
- Use Duplicate Review Queue table search, sorting, pagination, and grouped source row details.
- Check registration number, practitioner number, licence number, names, dates, institution, facility, and province.
- Record correction notes.
- Review the active Nursing Council analytics snapshot and explain that `Person_Group_Key` is not a legal practitioner ID.
- Validate Catherine workbook refresh totals without overwriting legal registry person records.
- Maintain mapped schools, institutions, and facilities as verified local reference records.
- Avoid deleting records without approval and evidence.

## Public Registration Support Training

Support staff must be able to explain:

- Which role a user should choose during account registration.
- Which cadre/pathway a user should choose.
- The difference between `Medical Board - CHW Provisional Registration` and `Medical Board - CHW Full License`.
- Why a graduand may not yet have a registration number.
- Why an existing practitioner should enter a licence or registration number for matching.
- Why the registrar must correct wrong route selections before a record becomes active.

## Notification And Mailbox Training

Staff must practise:

- Reading the notification bell count.
- Opening notification history.
- Opening a mailbox thread from a notification.
- Confirming the unread badge clears after viewing.
- Confirming sent messages show opened/read status when the recipient opens the thread.
- Using Inbox, Sent Items, Archived, Deleted Items, Conversation History, and Notes folders.

## Document Repository Training

Staff must practise:

- Uploading a scanned receipt.
- Uploading a qualification.
- Adding metadata.
- Linking to a practitioner or application.
- Searching by receipt number.
- Uploading a corrected version.
- Approving a controlled current version with an authority/SOP note.
- Rejecting a wrong or incomplete version with a correction note.
- Reading audit trail.

## Complaints, Discipline, And Decision Training

Staff must practise:

- Submitting a public complaint and confirming it enters ICMS without changing registry data.
- Creating a staff ICMS case.
- Opening an ICMS case from an enquiry thread.
- Adding status notes and attachments.
- Escalating a complaint to discipline where required.
- Recording a regulatory decision and linking the evidence summary.
- Closing a case with a clear outcome and audit trail.

## NHWA, Map, FAQ, And Forum Training

Staff must practise:

- Opening the NHWA workbook centre and understanding that it is a reporting layer.
- Reviewing populated NHWA cells without pushing values back into registry records.
- Opening the public map and confirming it reads stored coordinates.
- Checking mapped entity records before public demonstration.
- Reviewing FAQ entries.
- Moderating public forum posts and keeping staff forums internal.

## System Admin Training

System Admin must be able to:

- Manage accounts and role approvals.
- Enforce MFA.
- Review security audit events.
- Restrict secure console access.
- Confirm backups.
- Deploy approved releases.
- Support password reset/email configuration.
- Configure and verify Google Maps API key only through environment variables.
- Run geocoding as a controlled command or enter verified coordinates manually.
- Maintain documentation and change logs.

## Training Evidence

Each training session should record:

- Date.
- Trainer.
- Attendees.
- Role group.
- Topics covered.
- Issues raised.
- Follow-up actions.
- Attendance sign-off.
