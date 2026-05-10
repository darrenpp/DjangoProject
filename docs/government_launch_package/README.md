# Government Launch Package

Project: The National Department Of Health Regulatory Bodies Nursing Council & The Medical Board Online Workforce System

Date: 07 May 2026

## Purpose

This folder turns the platform into a formal government-grade regulatory operations package. It explains the system architecture, data governance, security controls, workflow engine, document repository, testing evidence, deployment plan, support model, and change-control process expected from an enterprise software delivery.

## Package Modules

- [01 System Requirements](01_system_requirements.md)
- [02 Technical Architecture](02_technical_architecture.md)
- [03 Data Governance and Data Dictionary](03_data_governance_and_dictionary.md)
- [04 Security and Privacy Controls Matrix](04_security_privacy_controls_matrix.md)
- [05 Role Access Matrix](05_role_access_matrix.md)
- [06 Workflow Engine Specification](06_workflow_engine_spec.md)
- [07 Document and Records Management SOP](07_document_records_management_sop.md)
- [08 Testing, QA, and UAT Checklist](08_testing_qa_uat_checklist.md)
- [09 Deployment, Backup, and Support Plan](09_deployment_backup_support_plan.md)
- [10 Staff Training Guide](10_staff_training_guide.md)
- [11 Maintenance, SLA, and Change Request Model](11_maintenance_sla_change_request.md)
- [12 Gap Register and Modular Roadmap](12_gap_register_and_modular_roadmap.md)
- [13 Enterprise UI Design Standard](13_enterprise_ui_design_standard.md)
- [14 AI Staff Assistant and Import Cleansing Guide](14_ai_staff_assistant_and_import_cleansing.md)
- [15 Free Local GPT Setup Guide](15_free_local_gpt_setup.md)

## Core Government Rule

Imported rows are not automatically trusted. They are staged, validated, cleansed, reviewed, approved, then promoted into live registry records.

## Standards Alignment

This package aligns the platform with:

- NIST Cybersecurity Framework 2.0: https://www.nist.gov/cyberframework
- NIST Secure Software Development Framework SP 800-218: https://csrc.nist.gov/pubs/sp/800/218/final
- OWASP Application Security Verification Standard: https://owasp.org/www-project-application-security-verification-standard/
- OWASP Top 10: https://owasp.org/Top10/
- PNG Digital Government / DICT cyber security direction: https://www.digital.gov.pg/

## Current Implementation Position

Implemented foundations:

- Nursing Council and Medical Board workspace separation.
- Role-based dashboard access.
- System Admin-only secure administration console.
- Secure password reset.
- Production-toggle MFA for System Admin and Registrar roles.
- Security audit event model for login and MFA evidence.
- Application status history and regulatory audit logs.
- OpenKM-style document repository with metadata, versions, OCR/search support, office scope, and audit events.
- Financial forecast separation by office scope.
- Data-quality audits and duplicate-review workflows.
- Staff inbox, notifications, chat, and operational access request workflow.

Launch gates still required:

- NDOH ICT hosting review and approval.
- Production email service configuration.
- Production HTTPS certificate and domain.
- Backup restore drill.
- Vulnerability scan.
- Independent penetration test.
- Registrar, finance, data-quality, and System Admin UAT sign-off.
