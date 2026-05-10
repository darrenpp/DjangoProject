# Presentation Pack

Project: The National Department Of Health Regulatory Bodies Nursing Council & The Medical Board Online Workforce System

Generated: 07 May 2026, 08:40 AM

## 1. Plain-Language Overview

This system is a government regulatory operations platform. It helps the National Department of Health, the PNG Nursing Council, and the Medical Board manage applications, practitioner records, licences, qualifications, documents, receipts, imports, data-quality issues, dashboards, reports, and staff workflows.

The simple rule is:

**Imported rows are not automatically trusted. They are staged, validated, cleansed, reviewed, approved, then promoted into live registry records.**

## 2. Current Live Statistics

| Statistic | Current total | Meaning |
| --- | --- | --- |
| Registered Nurses | 13,493 | Live person records in the Nursing Council nurse table. |
| Midwives | 2,112 | Live person records in the Nursing Council midwife table. |
| Nurse Aides | 800 | Live person records in the Nursing Council nurse aide table. |
| Graduands / Health Students | 7,624 | Live pipeline records for graduands and health students. |
| Community Health Workers | 11,562 | Medical Board / CHW scope records currently loaded. |
| Medical Doctors | 0 | Medical Board doctor records currently loaded. |
| Applications | 13,843 | All application records currently stored. |
| Receipts | 11,340 | Manual receipt records. Total amount: PGK 811284.30. |
| Imported Licence / History Rows | 96,806 | Operational and historical spreadsheet rows; one person can have multiple rows. |
| Qualifications | 25,376 | Qualification records currently stored. |
| Missing Data Review Items | 98,055 | Open data-quality items that staff still need to review. |
| Duplicate Review Items | 487 | Open possible duplicate records requiring staff review. |

## 3. Source And Recency

- Latest import batch: 2026 Current ATP-DATA Statistics & Tracking latest.xlsx
- Latest import status: completed
- Latest import completed at: 2026-05-06 13:42:58.198279+00:00
- Latest workbook sheet: 2026 ATP PMGH (RG)
- Latest workbook rows processed: 99

## 4. Nursing Council Institution And Facility Breakdown

| Breakdown item | Count |
| --- | --- |
| Recognised PNG nursing schools | 20 |
| Government nursing schools | 9 |
| Non-government nursing schools | 10 |
| Ownership review still needed | 1 |
| Raw institution rows | 916 |
| CHW training references | 281 |
| Overseas institution references | 293 |
| Local nursing-like names needing cleansing | 30 |
| Cleaned workplace references from imports | 4926 |
| Raw distinct workplace addresses | 7439 |

## 5. Application Status Totals

| Status | Current total |
| --- | --- |
| Approved | 13,819 |
| Pending | 21 |
| Rejected | 3 |

## 6. Imported Record Activity Mix

| Record activity | Current total |
| --- | --- |
| Full | 6,430 |
| Payment | 23,752 |
| Practicing License | 24,143 |
| Provisional | 9,206 |
| Temporary | 82 |
| Workforce Listing | 33,193 |

## 7. Document Management / OpenKM-Style Repository

| Repository item | Current total |
| --- | --- |
| Folders | 24 |
| Documents | 0 |
| Versions | 0 |
| Document audit events | 0 |
| Legacy professional uploads | 0 |

## 8. Workflow Configuration

| Configuration item | Current total |
| --- | --- |
| Application pathways | 12 |
| Dynamic form definitions | 18 |
| Document requirements | 55 |

## 9. Nursing Council Finance Summary

| Financial item | Current value |
| --- | --- |
| Manual completed receipts | 0 |
| Manual completed total | PGK 0.00 |
| Spreadsheet receipt rows | 23030 |
| Spreadsheet receipt total | PGK 1420842.20 |
| Combined total | PGK 1420842.20 |
| Date-quality issues | 14 |

## 10. AI Assistant Position

- Current AI mode: Local Offline Assistant
- Current AI detail: Using rule-based, offline staff guidance and cleansing checks.
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
| Records Hub | /records/ | assets\screenshots\records_hub.png |
| Nursing Forms Portal | /nursing/forms/ | assets\screenshots\nursing_forms.png |
| Public Nursing Register Search | /public/nursing-council/register/search/ | assets\screenshots\public_register.png |
| Nurse User Portal | /dashboard/nurse/ | assets\screenshots\nurse_portal.png |
| Graduand User Portal | /dashboard/student/ | assets\screenshots\graduand_portal.png |
| Doctor User Portal | /dashboard/doctor/ | assets\screenshots\doctor_portal.png |

## 13. Presentation Talking Points

- The platform is already operating as a structured registry, workflow, reporting, finance, and records-management system.
- Nursing Council and Medical Board workspaces are separated to support privacy and proper regulatory governance.
- The system now shows clean institution counts separately from raw historical reference rows.
- The biggest ongoing risk is data quality from old paper files and legacy spreadsheets, not the user interface itself.
- Staff should use the Production Readiness dashboard, duplicate review, missing-data review, and import preview tools before publishing management statistics.
- Free local GPT support is available through Ollama or an approved internal model server, with safe fallback to local rules.
