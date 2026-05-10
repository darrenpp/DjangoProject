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
- System Admin configuration, user approval, security, and support.
- Official document repository and records management.
- Import staging, cleansing, source tracking, and live registry promotion.
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

## Non-Functional Requirements

| ID | Requirement | Target |
|---|---|---|
| NFR-001 | Availability | Business-hours availability with documented maintenance windows |
| NFR-002 | Performance | Dashboard pages should load within acceptable operational time after data indexing and query tuning |
| NFR-003 | Security | Align with NIST CSF, NIST SSDF, OWASP ASVS, OWASP Top 10, and PNG Digital Government direction |
| NFR-004 | Privacy | Users only access records within their office scope or own profile |
| NFR-005 | Auditability | Login, MFA, import, export, approval, document, and status actions must be traceable |
| NFR-006 | Maintainability | Changes must be modular, tested, documented, and approved before production |
| NFR-007 | Recoverability | Backups must be restorable and tested monthly |
| NFR-008 | Data integrity | Imported records must be staged and reviewed before becoming official live records |

## Acceptance Criteria

The platform is government-launch ready when:

- Production environment has HTTPS, secure cookies, restricted admin, MFA, and monitored backups.
- Registrars can approve/reject applications with status history and audit evidence.
- Finance reports show office-specific receipts and export user/timestamp.
- Repository documents are scoped, searchable, versioned, and audited.
- Data import outputs show source file, source sheet, row count, issue count, and approval status.
- UAT is signed by Nursing Council Registrar, Medical Board Registrar, Finance Officer, Data Quality Officer, and System Admin.
- External security test results are reviewed and remediated before go-live.
