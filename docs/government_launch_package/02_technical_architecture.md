# 02 Technical Architecture

## Enterprise Architecture View

```mermaid
flowchart LR
    Public[Public users and applicants]
    Professionals[Nurses, midwives, nurse aides, doctors, CHWs, graduands]
    Registrars[Registrars]
    Reviewers[Reviewers and data-quality officers]
    Finance[Finance users]
    Admin[System Admin]

    Web[Secure Web Platform]
    RBAC[Role-Based Access and MFA]
    Workflow[Regulatory Workflow Engine]
    Docs[OpenKM-Style Document Repository]
    Cases[ICMS, Discipline, and Decisions]
    NHWA[NHWA Reporting Workbooks]
    Map[Mapped Reference Layer]
    Reports[Reporting and Analytics Engine]
    AI[AI Staff Assistant]
    Email[Email and Notification System]
    DB[(Primary PostgreSQL Database)]
    Backup[(Backup and Restore Server)]
    GovHost[Future Government Hosting Environment]

    Public --> Web
    Professionals --> Web
    Registrars --> Web
    Reviewers --> Web
    Finance --> Web
    Admin --> Web

    Web --> RBAC
    RBAC --> Workflow
    RBAC --> Docs
    RBAC --> Cases
    RBAC --> NHWA
    RBAC --> Map
    RBAC --> Reports
    RBAC --> AI
    Workflow --> DB
    Docs --> DB
    Cases --> DB
    NHWA --> DB
    Map --> DB
    Reports --> DB
    AI --> DB
    Workflow --> Email
    DB --> Backup
    Web --> GovHost
    DB --> GovHost
    Backup --> GovHost
```

## Regulatory Workspace Separation

```mermaid
flowchart TB
    User[Authenticated user]
    Access[Backend access checks]
    Nursing[Nursing Council workspace]
    Medical[Medical Board workspace]
    General[General Registry workspace]

    NursingData[(Nursing records, receipts, documents, cases, analytics, reports)]
    MedicalData[(Medical records, receipts, documents, cases, reports)]
    GeneralData[(Shared public/reference data, FAQs, forums, maps)]

    User --> Access
    Access -->|Nursing role or approved scope| Nursing
    Access -->|Medical role or approved scope| Medical
    Access -->|System Admin / approved shared scope| General
    Nursing --> NursingData
    Medical --> MedicalData
    General --> GeneralData
```

## Application-To-Licence Workflow Architecture

```mermaid
sequenceDiagram
    participant Applicant
    participant Portal
    participant Checklist
    participant Finance
    participant Reviewer
    participant Registrar
    participant LicenceRegister
    participant Reports
    participant Audit

    Applicant->>Portal: Submit application
    Portal->>Checklist: Generate required documents
    Checklist->>Portal: Validate uploaded evidence
    Portal->>Finance: Verify receipt or waiver
    Finance->>Audit: Record payment verification
    Portal->>Reviewer: Send for screening
    Reviewer->>Audit: Record review action
    Reviewer->>Registrar: Forward complete file
    Registrar->>Audit: Approve or reject
    Registrar->>LicenceRegister: Issue, renew, close, or update licence
    LicenceRegister->>Reports: Refresh dashboards and statistics
```

## Import Staging Architecture

```mermaid
flowchart LR
    Raw[Raw paper records and spreadsheets]
    Upload[Import upload]
    Stage[Staging/import tables]
    Validate[Validation and normalization]
    Issues[Missing data and duplicate review]
    Approve[Registrar or authorised staff approval]
    Live[Live registry records]
    Snapshot[Analytics snapshot / reporting tables]
    Reports[Dashboards and reports]
    Audit[Source and audit trail]

    Raw --> Upload
    Upload --> Stage
    Stage --> Validate
    Validate -->|Clean rows| Approve
    Validate -->|Problems found| Issues
    Issues --> Approve
    Approve --> Live
    Stage --> Snapshot
    Live --> Reports
    Snapshot --> Reports
    Stage --> Audit
    Approve --> Audit
```

## Deployment Architecture

```mermaid
flowchart TB
    Dev[Development environment]
    UAT[Staging / UAT environment]
    Prod[Production environment]
    Backup[Backup / restore environment]
    ICT[NDOH ICT monitoring and hosting]

    Dev -->|tested release branch| UAT
    UAT -->|signed UAT release| Prod
    Prod --> Backup
    Backup -->|monthly restore drill| UAT
    Prod --> ICT
    Backup --> ICT
```

## Main Components

| Component | Responsibility |
|---|---|
| Public portal | Public sign-in, registration, password reset, register search, help guidance |
| Staff dashboards | Registrar, reviewer, finance, data-quality, and System Admin work areas |
| Workflow engine | Application statuses, checklist gating, payment gating, registrar decisions, licence actions |
| Document repository | Official record storage, metadata, OCR/search, versions, approval/rejection sign-off, retention, office scope, audit events |
| Case management layer | ICMS complaint cases, disciplinary cases, regulatory decisions, case events, attachments, and evidence links |
| Data import layer | Source tracking, staging rows, analytics snapshots, workbook import, ATP/N-DATA alignment, Catherine workbook alignment, cleansing queues |
| NHWA reporting layer | NHWA workbook templates, population from verified data, review, sign-off, and export |
| Mapping/reference layer | Mapped schools, institutions, facilities, aliases, verification status, and stored coordinates |
| Reporting engine | Monthly analytics, yearly analytics, active Nursing Council snapshot analytics, financial forecast, management brief outputs |
| Security layer | Role checks, MFA, secure password reset, secure cookies, session timeout, admin restriction |
| Notification layer | Staff inbox, chat, mailbox folders, notification history, unread badge clearing, opened/read status, operational access requests, email notifications |
| Records table layer | Records Hub and duplicate-review queue table functions for authorised registrar, admin, reviewer, and data-quality workflows |
| Database | Master registry, application, licence, receipt, document, case, decision, NHWA, map, audit, import, and user data |
| Backup server | Scheduled database and media backups with restore testing |
| Government hosting | Future production hosting under approved NDOH ICT infrastructure |
