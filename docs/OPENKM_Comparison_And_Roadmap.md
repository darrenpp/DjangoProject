# OpenKM Comparison And Completed Platform Roadmap

Project: PNG Nursing Council and Medical Board Online Regulatory Workforce Platform

Date: Updated 1 June 2026

## 1. Purpose

This document explains how the platform now aligns with OpenKM-style document management and records management functions.

OpenKM is a document management system. Our platform is not being turned into a separate OpenKM server. Instead, the useful OpenKM concepts have been integrated into the current regulatory platform so documents, applications, practitioners, receipts, complaints, disciplinary cases, regulatory decisions, workflows, reports, and data-quality issues remain in one controlled system.

## 2. Implementation Principle

The platform uses OpenKM-style functions as system configuration and workflow support, not as a static file-download area.

The intended operating model is:

```text
Document or source record
  -> office scope
  -> metadata
  -> version/evidence
  -> search/OCR text
  -> access control
  -> linked practitioner/application/receipt
  -> linked complaint/discipline/decision where relevant
  -> approval or rejection sign-off
  -> review workflow
  -> audit event
  -> dashboard/report output
```

## 3. Current OpenKM-Style Capabilities

| OpenKM capability | Current platform implementation | Status |
|---|---|---|
| Central repository | `apps.documents` with repository folders, staff upload, detail, metadata, versions, and download. | Integrated |
| Office-scoped folders | General Registry, Nursing Council Repository, Medical Board Repository. | Implemented |
| Document metadata | `Document.metadata` stores structured metadata. | Implemented |
| Version control | `DocumentVersion` stores version number, current version, original filename, file size, checksum, and notes. | Implemented |
| OCR/search text | `DocumentVersion.extracted_text` and OCR support allow searchable text to be stored and searched. | Integrated |
| Duplicate document detection | File checksum comparison identifies duplicate uploaded files. | Integrated |
| Access policies | `DocumentAccessPolicy` supports user/role-level view, download, upload, metadata edit, and permission management flags. | Integrated |
| Audit events | `DocumentAuditEvent` tracks document actions such as created, uploaded, approved, rejected, viewed, downloaded, metadata updated, linked, OCR processed, and access denied. | Integrated |
| Approval sign-off | `DocumentApproval` records approval or rejection of controlled current versions with approver, timestamp, version, and note. | Implemented |
| Repository search | `/documents/search/` searches title, description, metadata, filenames, and extracted text with office-scope filtering. | Implemented |
| Role and privacy separation | Nursing Council, Medical Board, finance, reviewer, and admin access checks are enforced by backend role rules. | Implemented |
| Application workflow | Nursing Council pathway and checklist services connect applications, documents, payment, validation, and approval. | Integrated |
| Data quality | Missing-data review and Duplicate Review Queue support cleansing before reporting. Duplicate Review Queue includes search, sort, page length, full pagination, grouped source rows, and review actions. | Implemented |
| Records Hub | Authorised staff can inspect core registry records and administrative data. Nursing Professionals includes registrar table functions and CRUD actions where authorised. | Implemented |
| Staff inbox/chat | Notifications, notification history, unread badge clearing, read/opened message status, enquiries, and operational access requests support review and collaboration. | Implemented |
| Financial records | Manual receipts and spreadsheet receipts are separated by office scope and reported through finance pages. | Implemented |
| ICMS case records | Formal complaint, incident, and enquiry cases track triage, assignment, status, events, attachments, risk, and closure. | Implemented |
| Discipline case records | Disciplinary cases track stages, events, attachments, and escalation from complaint cases. | Implemented |
| Regulatory decision records | Formal decision records capture rationale, authority/SOP reference, evidence summary, conditions, appeal rights, maker, and dates. | Implemented |

## 4. Comparison With OpenKM

### Document Management

OpenKM provides central storage, metadata, versioning, relationships, OCR, and security.

Current platform alignment:

- Repository folder structure exists.
- Staff-facing upload and detail screens exist.
- Staff-facing metadata update, version upload, and audited download exist.
- Documents can be scoped to Nursing Council, Medical Board, or General Registry.
- Metadata can be stored on each document.
- File versions can be stored.
- Current version can be tracked.
- Current versions can be approved or rejected with notes and audit history.
- Checksums support duplicate document detection.
- OCR/extracted text can be searched.
- Role and office separation is enforced.

Remaining operational step:

- Legacy paper evidence still needs to be scanned and uploaded. The repository is ready, but historical documents are not yet fully attached to legacy practitioner records.

### Records Management

OpenKM provides classification, retention, official record declaration, archive rules, and disposal controls.

Current platform alignment:

- Documents can be marked as official records using `is_record`.
- Retention years can be stored.
- Status values include draft, active, archived, and superseded.
- Audit events create traceability.
- Practitioner/application/payment history remains available in structured tables.

Remaining operational step:

- NDOH must approve formal retention schedules and disposal rules before automated disposal can be used.

### Workflows and Automation

OpenKM provides routing, approvals, task queues, and workflow monitoring.

Current platform alignment:

- Nursing Council pathways are configured for applications and form rules.
- Checklist/document requirements can be generated by pathway.
- Payment gating and registrar approval rules exist.
- Staff inbox supports enquiries, notifications, and operational access requests.
- Notification history and mailbox read/opened status support auditable follow-up when evidence or corrections are requested.
- Registrar dashboards show operational statistics and review areas.

Remaining operational step:

- Full SLA escalation and visual workflow designer are not required for launch, but can be added after users start operating the platform.

### Collaboration

OpenKM provides discussion, annotations, and shared review.

Current platform alignment:

- Staff inbox and chat support internal review communication.
- Notifications guide users toward pending actions.
- Application notes, status history, and data-quality notes support traceability.
- ICMS and discipline case events support formal case collaboration.
- Regulatory decision records provide a controlled place for defensible outcomes.

Remaining operational step:

- Document-level comments and inline annotations can be added as a later enhancement if staff need them after launch.

### Search and Indexing

OpenKM provides full-text and metadata search.

Current platform alignment:

- Repository search checks document title, description, metadata, filename, and extracted text.
- Records Hub and dashboard search support structured records.
- OCR text can be used for scanned documents.

Remaining operational step:

- Performance tuning may be needed when many scanned documents are uploaded.

### Security and Compliance

OpenKM provides permissions, audit trails, and compliance controls.

Current platform alignment:

- System Admin only can access `/admin/`.
- Reviewers need operational approval before using higher-risk tools.
- Finance Officer has read-only finance/workforce access.
- Nursing Council and Medical Board finance can be viewed separately.
- Public register returns safe public fields only.
- Sensitive actions are linked to user identity and audit/history tables.

Remaining operational step:

- Production hosting, backup policy, retention policy, and security monitoring must be confirmed with NDOH ICT before live public deployment.

## 5. How OpenKM-Style Features Fit The Platform

| Business need | Platform feature |
|---|---|
| Store scanned paper records | Document repository and professional document/checklist uploads |
| Find documents later | Repository search and OCR/extracted text |
| Know if the file changed | Document versions and current-version flag |
| Stop staff seeing the wrong office records | Office scope and role access checks |
| Track who handled a file | Document audit events, status history, export timestamps |
| Approve or reject a controlled file | Document approval records and approved/rejected audit events |
| Connect documents to a case | Related object links, application checklist records, ICMS cases, discipline cases, and decision records |
| Manage complaints and incidents | ICMS cases, events, attachments, risk, priority, and source enquiry links |
| Manage disciplinary pathways | Disciplinary cases, stages, events, attachments, and complaint escalation |
| Record defensible decisions | Regulatory decision records with rationale, authority, evidence, conditions, and appeal rights |
| Review incomplete records | Missing-data review and duplicate-review workflows |
| Work through duplicate candidates efficiently | Duplicate Review Queue with search, sort, pagination, grouped source rows, and reviewed/merged/reopen actions |
| Maintain structured records | Records Hub table functions and authorised CRUD actions |
| Keep official evidence | `is_record`, status, retention years, and audit history |
| Support registrar approval | Checklist, payment, competency, declaration, and registrar workflow rules |
| Support finance transparency | Separate manual receipts, spreadsheet receipts, monthly/yearly totals, and office-scoped exports |

## 6. Completed Roadmap Summary

| Phase | Scope | Current status |
|---|---|---|
| Phase 1 | Repository foundation, office-scoped folders, metadata, versions, permissions, and audit. | Completed and integrated |
| Phase 2 | OCR/search integration, duplicate checksum checks, source import alignment, monthly analytics explanation. | Completed and integrated |
| Phase 3 | Workflow routing through applications, checklists, registrar review, staff inbox, access requests, and reports. | Completed and integrated |
| Phase 4 | Records governance, retention fields, archive/superseded status, privacy separation, finance separation, document sign-off, and audit discipline. | Completed and integrated |
| Phase 5 | User guide, data-cleansing guide, management reporting discipline, ICMS/discipline guidance, and launch governance documentation. | Completed documentation |

## 7. What Must Still Be Done Operationally

The system functions are available, but the data programme must continue:

- Scan and attach legacy paper evidence.
- Populate employment records from renewal and ATP data.
- Resolve missing-data review items.
- Resolve duplicate review candidates.
- Normalize institution and facility reference values.
- Link complaint, discipline, and decision evidence to the correct records.
- Use approval/rejection sign-off for controlled document versions.
- Confirm official retention schedules with NDOH ICT and management.
- Train staff before production launch.
- Change all test passwords before production launch.

## 8. Conclusion

The OpenKM-style scope has been integrated into the platform as a controlled document and records management layer. The platform now supports repository folders, document metadata, version tracking, approval/rejection sign-off, extracted-text search, checksum duplicate checks, office-scoped access, audit events, workflow support, ICMS and discipline evidence, regulatory decision records, data-quality review, staff collaboration, and separated regulatory body reporting.

The next major gains will come from disciplined use: scanning paper evidence, attaching documents to the correct records, cleaning source data, and ensuring staff follow the workflow instead of bypassing it.
