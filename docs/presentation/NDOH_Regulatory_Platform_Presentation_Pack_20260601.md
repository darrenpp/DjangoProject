# Presentation Pack

Project: PNG Nursing Council and Medical Board Online Regulatory Workforce Platform

Generated: 1 June 2026

## 1. Plain-Language Overview

This system is a government regulatory operations platform. It helps the National Department of Health, the PNG Nursing Council, and the Medical Board manage applications, practitioner records, licences, qualifications, documents, receipts, imports, data-quality issues, dashboards, reports, and staff workflows.

The simple rule is:

**Imported rows are not automatically trusted. They are staged, validated, cleansed, reviewed, approved, then promoted into live registry records.**

## 2. Nursing Council Cleansed Analytics Totals

| Statistic | Current total | Meaning |
| --- | --- | --- |
| Nursing Council total lifecycle records | 34,851 | Cleansed analytics snapshot rows across provisional, full licence, and ATP lifecycle stages. |
| Clean ATP records | 19,998 | Cleansed Authority to Practice records from the active Nursing Council analytics snapshot. |
| Clean provisional records | 8,158 | Cleansed provisional licence records from the active Nursing Council analytics snapshot. |
| Clean full-licence records | 6,695 | Cleansed full-licence records from the active Nursing Council analytics snapshot. |
| Estimated practitioner match groups | 22,765 | Analytics grouping count used for workforce analysis; not a legal practitioner ID. |
| Data quality health score | 87.0% | Current cleansed-data quality score for the active Nursing Council analytics snapshot. |

These are the current Nursing Council figures after the cleanse. They come from the active cleansed analytics snapshot, not from the legal live person tables. The legal registry remains protected until records are promoted through approved workflow.

## 2A. Cleansed Nursing Council Cadre / Stage Breakdown

| Cadre | Provisional | Full licence | ATP | Total |
| --- | --- | --- | --- | --- |
| Registered Nurse | 0 | 5,535 | 9,413 | 14,948 |
| Nursing Graduand | 7,862 | 0 | 0 | 7,862 |
| Nursing | 0 | 0 | 5,191 | 5,191 |
| Midwife | 0 | 0 | 2,176 | 2,176 |
| Nurse Aide | 0 | 0 | 2,056 | 2,056 |
| Midwifery | 0 | 990 | 0 | 990 |
| Paediatric Nurse | 2 | 2 | 506 | 510 |
| Unclassified / Missing qualification | 148 | 161 | 0 | 309 |
| Unclassified / Other Cadre | 0 | 0 | 212 | 212 |
| Mental Health Nurse | 26 | 1 | 140 | 167 |
| Community Health Worker (CHW) | 0 | 0 | 158 | 158 |
| Midwifery Graduand | 96 | 0 | 0 | 96 |
| Unclassified / Missing Cadre | 0 | 0 | 89 | 89 |
| Enrolled Nurse | 1 | 0 | 50 | 51 |

## 3. Source And Recency

- Latest import batch: Medical Board legacy workbooks
- Latest import status: completed
- Latest import completed at: 2026-06-18 01:31:40.065466+00:00
- Latest workbook sheet: 10. CHW DATABASE 1985-2025::CHWS FILE
- Latest workbook rows processed: 830
- Active Nursing Council analytics source: PNG_Nursing_Council_Integrated_Dashboard_Model.xlsx
- Active Nursing Council analytics generated on: 2026-05-27

## 3A. Operational Live Registry And Platform Counts

| Statistic | Current total | Meaning |
| --- | --- | --- |
| Live legal RN person table | 1 | Operational NursingProfessional rows only; not the cleansed Nursing Council analytics total. |
| Live legal midwife person table | 0 | Operational Midwife rows only; not the cleansed Nursing Council analytics total. |
| Live legal nurse aide person table | 0 | Operational NurseAide rows only; not the cleansed Nursing Council analytics total. |
| Live legal graduand/student table | 0 | Operational HealthStudent rows only; not the cleansed provisional analytics total. |
| Community Health Workers | 11,752 | Medical Board / CHW scope records currently loaded. |
| Medical Doctors | 517 | Medical Board doctor records currently loaded. |
| Applications | 1 | All application records currently stored. |
| Receipts | 11,501 | Receipt records currently stored. Total amount: PGK 822882.30. |
| Imported Licence / History Rows | 129,690 | Operational and historical spreadsheet rows; one person can have multiple rows. |
| Qualifications | 12,412 | Qualification records currently stored. |
| Missing Data Review Items | 95,276 | Data-quality items created for review and correction. |
| Pending Missing Data Review Items | 0 | Missing-data items still pending. |
| Duplicate Review Items | 177 | Possible duplicate records requiring staff review. |
| Pending Duplicate Review Items | 177 | Duplicate-review items still pending. |

`Person_Group_Key` is used for analytics grouping only. It is not a legal practitioner identity.

## 4. Nursing Council Institution And Facility Breakdown

| Breakdown item | Count |
| --- | --- |
| Recognised PNG nursing schools | 20 |
| Government nursing schools | 9 |
| Non-government nursing schools | 10 |
| Ownership review still needed | 1 |
| Raw institution rows | 948 |
| CHW training references | 296 |
| Overseas institution references | 303 |
| Local nursing-like names needing cleansing | 190 |
| Cleaned workplace references from imports | 5636 |
| Raw distinct workplace addresses | 8156 |

## 5. Application Status Totals

| Status | Current total |
| --- | --- |
| Pending | 1 |

## 6. Imported Record Activity Mix

| Record activity | Current total |
| --- | --- |
| Full | 7,546 |
| Payment | 12,308 |
| Practicing License | 19,298 |
| Provisional | 4,891 |
| Temporary | 41 |
| Workforce Listing | 85,606 |

## 7. Document Management / OpenKM-Style Repository

| Repository item | Current total |
| --- | --- |
| Folders | 24 |
| Documents | 0 |
| Versions | 0 |
| Document audit events | 0 |
| Document approvals/rejections | 0 |
| Legacy professional uploads | 0 |

## 8. Workflow Configuration

| Configuration item | Current total |
| --- | --- |
| Application pathways | 12 |
| Dynamic form definitions | 18 |
| Document requirements | 60 |
| ICMS complaint cases | 0 |
| Disciplinary cases | 0 |
| Regulatory decision records | 0 |

## 9. Nursing Council Finance Summary

| Financial item | Current value |
| --- | --- |
| Manual completed receipts | 0 |
| Manual completed total | PGK 0.00 |
| Spreadsheet receipt rows | 8082 |
| Spreadsheet receipt total | PGK 537936.30 |
| Combined total | PGK 537936.30 |
| Date-quality issues | 6 |

## 9A. Public Engagement And Mapping

| Item | Current total |
| --- | --- |
| Mapped entity references | 1462 |
| Mapped entities with stored coordinates | 0 |
| FAQ entries | 5 |
| Forum topics | 0 |

Google Maps reads locally stored coordinates. The page does not geocode every load.

## 10. AI Assistant Position

- Current AI mode: LocalAI Assistant
- Current AI detail: Using a LocalAI endpoint for staff-only assistance.
- Free local GPT ready: False
- Model configured: Local rule-based mode

The AI assistant is for staff guidance only. It does not approve applications, issue licences, or write imported rows directly into live registry records.

## 11. Diagrams

- Enterprise Architecture: assets\diagrams\enterprise_architecture.png
- Regulatory Workflow: assets\diagrams\regulatory_workflow.png
- Data Governance Flow: assets\diagrams\data_governance_flow.png
- Role Access And Privacy: assets\diagrams\role_access_privacy.png

## 12. Current Interface Screenshots

| Screen | System path | Screenshot file |
| --- | --- | --- |
| Public Home Page | / | assets\screenshots\public_home.png |
| Login Page | /accounts/login/ | assets\screenshots\login.png |
| Overall Dashboard | /dashboard/ | assets\screenshots\overall_dashboard.png |
| Production Readiness Dashboard | /dashboard/production-readiness/ | assets\screenshots\production_readiness.png |
| Nursing Council Registrar Dashboard | /dashboard/nursing-council/ | assets\screenshots\nursing_council_dashboard.png |
| Medical Board Dashboard | /dashboard/medical-board/ | assets\screenshots\medical_board_dashboard.png |
| Workforce Flow | /dashboard/flow/ | assets\screenshots\workforce_flow.png |
| Financial Forecast | /dashboard/reports/financial/?office=nursing | assets\screenshots\financial_forecast.png |
| Staff AI Assistant | /dashboard/staff-ai/ | assets\screenshots\staff_ai.png |
| Document Repository Search | /documents/search/ | assets\screenshots\documents_search.png |
| ICMS Complaints Register | /dashboard/complaints/ | assets\screenshots\complaints_icms.png |
| Disciplinary Case Register | /dashboard/complaints/discipline/ | assets\screenshots\disciplinary_cases.png |
| Regulatory Decision Register | /dashboard/complaints/decisions/ | assets\screenshots\decision_register.png |
| NHWA Workbook Centre | /dashboard/nhwa-workbooks/ | assets\screenshots\nhwa_workbooks.png |
| Public FAQs | /dashboard/public/faqs/ | assets\screenshots\public_faqs.png |
| Public And Practitioner Forum | /dashboard/public/forum/ | assets\screenshots\public_forum.png |
| Mapped Schools, Institutions, and Facilities | /dashboard/public/map/ | assets\screenshots\public_map.png |
| Records Hub | /records/ | assets\screenshots\records_hub.png |
| Nursing Professionals Records Table | /records/nursingprofessional/ | assets\screenshots\nursing_professionals.png |
| Duplicate Review Queue | /dashboard/duplicate-reviews/ | assets\screenshots\duplicate_review_queue.png |
| Staff Inbox and Notifications | /notifications/communications/ | assets\screenshots\staff_notifications.png |
| Nursing Forms Portal | /nursing/forms/ | assets\screenshots\nursing_forms.png |
| Public Nursing Register Search | /public/nursing-council/register/search/ | assets\screenshots\public_register.png |
| Nurse User Portal | /dashboard/nurse/ | assets\screenshots\nurse_portal.png |
| Graduand User Portal | /dashboard/student/ | assets\screenshots\graduand_portal.png |
| Doctor User Portal | /dashboard/doctor/ | assets\screenshots\doctor_portal.png |

## 13. Presentation Talking Points

- The platform is already operating as a structured registry, workflow, reporting, finance, and records-management system.
- Nursing Council and Medical Board workspaces are separated to support privacy and proper regulatory governance.
- Board-specific dashboards now show the correct Nursing Council or Medical Board welcome header with PNG emblem identity.
- Public registration now uses controlled Role/Cadre dropdowns, including separate CHW provisional and CHW full-license pathways.
- Notification history, unread badge clearing, and opened/read mailbox status are now part of the operational workflow.
- Records Hub and Duplicate Review Queue now include table search, sorting, page length, and pagination functions for registrar/data-quality work.
- Formal ICMS complaints, discipline workflow, and regulatory decision register now support defensible case management.
- Repository documents can be approved or rejected as controlled current versions.
- Nursing Council analytics are powered by an active cleansed snapshot and server-side drilldowns.
- NHWA workbooks are a reporting layer populated from verified platform data and do not overwrite legal registry records automatically.
- Public FAQs, moderated forums, and mapped institutions/facilities provide a cleaner public and practitioner experience.
- The system now shows clean institution counts separately from raw historical reference rows.
- The biggest ongoing risk is data quality from old paper files and legacy spreadsheets, not the user interface itself.
- Staff should use the Production Readiness dashboard, duplicate review, missing-data review, and import preview tools before publishing management statistics.
- Free local GPT support is available through Ollama or an approved internal model server, with safe fallback to local rules.
