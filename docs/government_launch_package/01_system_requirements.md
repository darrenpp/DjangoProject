# 01 System Requirements

## Objective

Deliver a government-grade regulatory operations system for the National Department of Health regulatory bodies, supporting the Nursing Council and the Medical Board as separated but centrally governed workspaces.

## Business Scope

The platform must support:

- Public account registration and professional self-service.
- Nursing Council application, registration, renewal, licence, workforce, and document workflows.
- Medical Board application, registration, licence, workforce, and financial workflows.
- Registrar approval and rejection decisions.
- Reviewer screening and data-quality review.
- Finance receipt tracking and financial forecast reporting.
- Receipt-owner matching and unmatched/high-value receipt review.
- System Admin configuration, user approval, security, and support.
- Official document repository and records management.
- Import staging, cleansing, source tracking, and live registry promotion.
- Nursing Council analytics snapshot import and drilldown from cleansed workbooks.
- NHWA workbook reporting and sign-off.
- Formal ICMS complaints, discipline workflow, and regulatory decision records.
- Public FAQ, moderated forum, and mapped institution/facility references.
- Notification history, unread badge clearing, mailbox folders, and opened/read message status.
- Records Hub table functions and authorised CRUD actions.
- Duplicate Review Queue table functions and review actions.
- Controlled public registration role/cadre routing.
- Management reports, monthly analytics, yearly analytics, financial reports, and ministerial briefs.

## Functional Requirements

| ID | Requirement | Current status |
|---|---|---|
| FR-001 | Separate Nursing Council and Medical Board dashboards, reports, and financial data. | Implemented foundation |
| FR-002 | Enforce backend role checks, not only hidden buttons. | Implemented foundation |
| FR-003 | Provide public-safe register search. | Implemented foundation |
| FR-004 | Provide application intake and status tracking. | Implemented foundation |
| FR-005 | Require document checklist, payment, review, registrar decision, and licence update. | Implemented foundation |
| FR-006 | Store every official status change in status history. | Implemented foundation |
| FR-007 | Store sensitive actions in audit logs. | Implemented foundation, expanding |
| FR-008 | Provide OpenKM-style repository for scanned records, receipts, qualifications, letters, and competencies. | Implemented foundation |
| FR-009 | Provide OCR/search and duplicate document checksum detection. | Implemented foundation |
| FR-010 | Provide data cleansing and duplicate-review workflows. | Implemented foundation |
| FR-011 | Provide finance forecast and office-specific financial exports. | Implemented foundation |
| FR-012 | Require production MFA for System Admin and Registrar roles. | Implemented as production-toggle control |
| FR-013 | Provide formal documentation, user guide, training guide, deployment plan, and support model. | Implemented in this package |
| FR-014 | Provide notification history, unread badge clearing, and mailbox opened/read status. | Implemented foundation |
| FR-015 | Provide registrar Records Hub table search, sorting, pagination, and CRUD controls where authorised. | Implemented foundation |
| FR-016 | Provide Duplicate Review Queue search, sorting, page length, pagination, grouped source rows, and reviewed/merged/reopen actions. | Implemented foundation |
| FR-017 | Provide controlled public registration Role/Cadre dropdowns, including separate CHW provisional and full-license pathways. | Implemented foundation |
| FR-018 | Provide Nursing Council analytics snapshots and server-side drilldown from cleansed workbooks. | Implemented foundation |
| FR-019 | Provide formal ICMS complaint and incident case management. | Implemented foundation |
| FR-020 | Provide disciplinary case workflow and complaint escalation. | Implemented foundation |
| FR-021 | Provide formal regulatory decision register. | Implemented foundation |
| FR-022 | Provide document approval/rejection sign-off for controlled repository versions. | Implemented foundation |
| FR-023 | Provide NHWA workbook reporting layer without registry write-back. | Implemented foundation |
| FR-024 | Provide public FAQ, moderated forum, and mapped reference pages. | Implemented foundation |
| FR-025 | Provide receipt-owner matching and unmatched/high-value receipt review routing. | Implemented foundation |

## Non-Functional Requirements

| ID | Requirement | Target |
|---|---|---|
| NFR-001 | Availability | Business-hours availability with documented maintenance windows |
| NFR-002 | Performance | Dashboard pages should load within acceptable operational time after data indexing and query tuning |
| NFR-003 | Security | Align with NIST CSF, NIST SSDF, OWASP ASVS, OWASP Top 10, and PNG Digital Government direction |
| NFR-004 | Privacy | Users only access records within their office scope or own profile |
| NFR-005 | Auditability | Login, MFA, import, export, approval, document, case, decision, receipt-linking, and status actions must be traceable |
| NFR-006 | Maintainability | Changes must be modular, tested, documented, and approved before production |
| NFR-007 | Recoverability | Backups must be restorable and tested monthly |
| NFR-008 | Data integrity | Imported records must be staged and reviewed before becoming official live records |

## Acceptance Criteria

The platform is government-launch ready when:

- Production environment has HTTPS, secure cookies, restricted admin, MFA, and monitored backups.
- Registrars can approve/reject applications with status history and audit evidence.
- Finance reports show office-specific receipts and export user/timestamp.
- Repository documents are scoped, searchable, versioned, and audited.
- Controlled repository versions can be approved or rejected with notes.
- ICMS, discipline, and decision workflows are office-scoped and auditable.
- Nursing Council analytics snapshot KPIs match source workbook totals before publication.
- NHWA workbook exports are reviewed and signed off without writing values back to registry records.
- Public FAQ, forum, complaint, and map pages do not expose private practitioner data.
- Receipt-owner links are accepted only where evidence is strong; unmatched or suspicious receipts remain in review.
- Data import outputs show source file, source sheet, row count, issue count, and approval status.
- Notification and mailbox workflows show correct unread/read/opened status.
- Records Hub and Duplicate Review Queue table functions work for authorised users.
- Public registration routes applicants to the correct role/cadre pathway.
- UAT is signed by Nursing Council Registrar, Medical Board Registrar, Finance Officer, Data Quality Officer, and System Admin.
- External security test results are reviewed and remediated before go-live.
