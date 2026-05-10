# OpenKM-Style Project Timeline

Project: The National Department Of Health Regulatory Bodies Nursing Council & The Medical Board Online Workforce System

Date: 07 May 2026

## 1. Objective

Deliver OpenKM-style document management, records management, workflow control, search, audit, and governance inside the current regulatory platform without breaking Nursing Council and Medical Board operations.

This timeline is now written as the completed platform timeline plus the operational post-launch programme.

## 2. Delivery Method

Each phase followed this safe-release pattern:

1. Inspect existing models, views, URLs, dashboards, reports, and role checks.
2. Reuse existing architecture where possible.
3. Add isolated modules only where the current system could not safely represent the feature.
4. Preserve Nursing Council and Medical Board separation.
5. Add or update database migrations.
6. Add management commands for repeatable setup.
7. Run system checks and targeted tests.
8. Update documentation and user guidance.

## 3. Completed Timeline

### Phase 1: Document Repository Foundation

Status: Completed and integrated

Delivered:

- `apps.documents` module.
- `DocumentFolder` model.
- `Document` model.
- `DocumentVersion` model.
- `DocumentAccessPolicy` model.
- `DocumentAuditEvent` model.
- Office scopes: General Registry, Nursing Council, Medical Board.
- Bootstrap command: `bootstrap_document_repository`.
- Admin management for folders, documents, versions, access policies, and audit events.

Outcome:

- The system now has a central OpenKM-style repository integrated into staff screens.
- Nursing Council and Medical Board documents can be scoped separately.
- Documents can store metadata, official record flags, retention years, versions, extracted text, and audit events.

### Phase 2: OCR, Indexing, Search, and Duplicate Detection

Status: Completed and integrated

Delivered:

- Repository search route: `/documents/search/`.
- Search by title, description, metadata, original filename, and extracted text.
- OCR/extracted-text field available on document versions.
- SHA-256 checksum generation for uploaded document versions.
- Duplicate checksum grouping for repository search results.
- Reference extraction helper for receipt numbers, ATP numbers, registration numbers, practitioner numbers, licence numbers, and years.

Outcome:

- Staff can search repository records by normal document details and OCR text where available.
- Duplicate file detection is ready for scanned and uploaded documents.

### Phase 3: Workflow and Staff Review Integration

Status: Completed and integrated

Delivered:

- Nursing Council pathway configuration service.
- Form pathway configuration for NC/G-style workflows.
- Checklist/document requirements connected to application review.
- Registrar approval and rejection workflows.
- Employer verification and deceased practitioner workflow tools.
- Staff inbox, chat, notification, and operational access request workflow.
- Reviewer access lock until approval by registrar or System Admin.
- Finance Officer restricted to read-only finance and workforce views.
- Linked repository evidence displayed on application detail review screens.

Outcome:

- Documents and records now sit inside controlled regulatory workflows rather than being treated as static downloads.
- Staff requests for operational access are visible to the registrar and System Admin.
- Registrar review can open repository evidence from the application detail screen.

### Phase 4: Records Governance, Security, and Compliance

Status: Completed and integrated

Delivered:

- System Admin only restriction for `/admin/`.
- Nursing Council and Medical Board backend access separation.
- Finance forecast separation by office scope.
- Public register safe-field rules.
- Profile Overview role explanations.
- Export timestamp/user tracking for confidential outputs.
- Data-quality and duplicate-review workflow guidance.
- Repository official record and retention fields.

Outcome:

- The platform has the practical security and governance controls needed for controlled launch preparation.
- Sensitive records are not managed only through visible menu hiding; backend checks enforce access.

### Phase 5: Documentation, Training, and Launch Readiness

Status: Completed documentation

Delivered:

- Updated documentation index.
- Updated role-based user guide and manual.
- Updated data-cleansing and import alignment plan.
- Updated OpenKM comparison and roadmap.
- New OpenKM-style completed-platform user guide.
- Management reporting standards for live counts, imported rows, payment rows, source dates, and data-quality limitations.

Outcome:

- Staff have a plain-language reference for system use, data governance, OpenKM-style document management, and reporting discipline.

## 4. Post-Launch Operational Timeline

### Week 1: Staff Training and Account Confirmation

Tasks:

- Confirm all staff accounts and roles.
- Change testing passwords.
- Train registrars, finance, reviewers, data-quality officers, and System Admin.
- Demonstrate operational access request workflow.
- Demonstrate Nursing Council and Medical Board separation.

### Week 2: Document Repository Pilot

Tasks:

- Scan a small set of current applications and receipts.
- Upload to correct office-scoped repository.
- Add metadata and document type.
- Link documents to application/practitioner records where applicable.
- Search using title, metadata, and extracted text.
- Confirm no cross-office leakage.

### Week 3: Data Cleansing Sprint

Tasks:

- Run missing-data audit.
- Run duplicate audit.
- Review future date issues such as accidental 2050 dates.
- Normalize provinces, institutions, facilities, and sectors.
- Start ATP-to-employment alignment.

### Week 4: Finance and Reporting Validation

Tasks:

- Compare manual receipts with spreadsheet receipts.
- Confirm Nursing Council finance and Medical Board finance are separate.
- Generate monthly analytics.
- Generate financial forecast reports.
- Check export timestamps and exporting user.
- Confirm report explanations are clear for management.

### Week 5: Management Review

Tasks:

- Present current live statistics.
- Present remaining data-quality gaps.
- Present OpenKM-style repository process.
- Present privacy and role access model.
- Confirm deployment readiness with NDOH ICT.

## 5. Success Criteria

The OpenKM-style implementation is successful when:

- Staff store official evidence in the correct office-scoped repository.
- Documents have metadata and versions where appropriate.
- Scanned documents can be searched.
- Duplicate document checks identify repeated uploads.
- Registrar review uses checklist, payment, competency, and source evidence.
- Finance reports separate Nursing Council and Medical Board receipts.
- Public users cannot view private records.
- Reviewers cannot access high-risk tools until approved.
- Reports explain live people counts separately from imported row counts.
- Data-quality issues are reviewed before management statistics are published.

## 6. Governance Checkpoints

Review these monthly:

- Role access and approval requests.
- Nursing Council and Medical Board data separation.
- Open repository documents without metadata.
- Duplicate uploaded documents.
- Missing-data review backlog.
- Duplicate practitioner backlog.
- Finance date errors and suspicious receipt rows.
- Report source dates and latest import batch.
- Backup and restore readiness.
- User training needs.

## 7. Current Position

The OpenKM-style system foundation is complete and integrated into the platform. The remaining work is operational adoption: scanning paper records, attaching legacy evidence, cleaning historical data, training users, confirming NDOH ICT hosting/security, and enforcing disciplined reporting practices.
