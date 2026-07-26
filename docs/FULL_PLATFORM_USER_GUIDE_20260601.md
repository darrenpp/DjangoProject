# Full Platform User Guide

Project: PNG Nursing Council and Medical Board Online Regulatory Workforce Platform

Last updated: 1 June 2026

## 1. Operating Principle

The platform is a controlled regulatory operations system, not a spreadsheet viewer.

Core rules:

- Nursing Council and Medical Board data stay separated by role and office scope.
- Imported workbook rows are staged and analysed before they become legal registry records.
- The Nursing Council analytics dashboard reads from the active cleansed snapshot first.
- `Person_Group_Key` is an analytics grouping key only. It is not a legal practitioner identity.
- NHWA workbooks are reporting outputs populated from verified platform data. They do not write back into the legal registry automatically.
- Receipts are financial evidence. They are not practitioner records.
- Formal complaints, discipline, and decision records must keep evidence, rationale, authority references, and audit history.

## 2. Key Areas

| Area | URL | Use |
|---|---|---|
| Main dashboard | `/dashboard/` | Role-based landing page |
| Nursing Council portal | `/dashboard/nursing-council/` | Nursing Council analytics, workflow, data quality, and operations |
| Medical Board portal | `/dashboard/medical-board/` | Medical Board workspace |
| Financial forecast | `/dashboard/reports/financial/?office=nursing` | Nursing Council receipt and forecast reporting |
| ICMS complaints | `/dashboard/complaints/` | Formal complaint, incident, and enquiry case management |
| Discipline | `/dashboard/complaints/discipline/` | Disciplinary case workflow |
| Decisions | `/dashboard/complaints/decisions/` | Formal regulatory decision register |
| Document repository | `/documents/search/` | Official evidence, versions, metadata, search, and approval sign-off |
| NHWA workbooks | `/dashboard/nhwa-workbooks/` | Standards/reporting workbook layer |
| Public FAQs | `/dashboard/public/faqs/` | Public guidance |
| Forum | `/dashboard/public/forum/` | Moderated public, practitioner, and staff discussions |
| Map | `/dashboard/public/map/` | Schools, institutions, and facilities using stored coordinates |
| Records Hub | `/records/` | Staff record maintenance where authorised |

## 3. Nursing Council Analytics

The active snapshot is `PNG_Nursing_Council_Integrated_Dashboard_Model.xlsx`, generated on 27 May 2026.

| Metric | Current value |
|---|---:|
| Total lifecycle records | 34,851 |
| Clean ATP records | 19,998 |
| Clean provisional records | 8,158 |
| Clean full-licence records | 6,695 |
| Estimated practitioner match groups | 22,765 |
| Data quality health score | 87.0% |

Use the dashboard charts for analytics and the drilldown/Open buttons for record inspection. Treat analytics records as snapshot evidence until an authorised promotion or live workflow creates the legal record.

## 4. Complaints, Discipline, and Decisions

Public and staff complaints enter the ICMS register. Staff can create cases from the complaints screen or escalate an enquiry thread using the Open ICMS Case action.

Workflow:

```text
Complaint or enquiry
  -> ICMS case
  -> triage and assignment
  -> investigation notes and attachments
  -> resolution or escalation
  -> discipline case where required
  -> formal regulatory decision
```

Disciplinary cases track stages from intake through assessment, investigation, committee review, hearing, decision, appeal/monitoring, and closure.

The regulatory decision register should be used for decisions that must be defensible later. Record the decision, rationale, authority or SOP reference, evidence summary, conditions, appeal rights, decision maker, and effective dates.

## 5. Document Repository

Use the repository for scanned application forms, receipts, qualifications, correspondence, source workbooks, investigation evidence, and signed outputs.

Required practice:

- Select the correct office scope.
- Add document type, title, metadata, and linked record where possible.
- Upload corrected files as new versions, not silent replacements.
- Approve or reject the current version when it becomes an official controlled document.
- Use audit history to confirm who uploaded, viewed, downloaded, approved, rejected, or changed a document.

## 6. Receipts

Receipt linking attempts to match recent payments to applications, practitioner records, analytics facts, or source rows using evidence such as receipt number, name, registration number, practitioner number, source row, amount, and date.

Rules:

- Accept only high-confidence matches.
- Do not attach a receipt to a person based only on a weak name match.
- Place unlinked, duplicate, suspicious, or high-value receipts into review.
- Keep Nursing Council and Medical Board receipt reporting separate.

## 7. Public, Applicant, and Practitioner Views

Public users can search public-safe register information, submit forms, read FAQs, submit moderated complaints, and view public map references.

Applicants and practitioners can use their own dashboards, applications, receipts, messages, and notification history. They cannot view other practitioners' private records.

Forum visibility is role-based:

- Public Questions are moderated before display.
- Registered Nurses, Provisional Licence, Full-Licence Applicant, and ATP Renewal forums require login and the matching user/stage.
- Staff forums are internal only.

## 8. Mapping

The map displays schools, institutions, and facilities from `MappedEntity` records.

Important rule: the page reads stored coordinates. It must not geocode every page load. Use `geocode_mapped_entities --limit 100` or verified admin entry to add coordinates.

Filters support board, type, province, cadre, and workforce count where the source data is available.

## 9. NHWA Toolkit

The NHWA toolkit is a standards/reporting layer:

```text
Registry / Analytics / Finance / Facilities
        -> NHWA workbook cells
        -> review and sign-off
        -> NHWA export/report
```

Do not use NHWA workbook values to overwrite registry records. Uncertain cells remain editable with audit and sign-off control.

## 10. Staff Role Summary

| Role | Main responsibilities |
|---|---|
| System Admin | Users, roles, MFA, migrations, bootstraps, maps, NHWA setup, backups, and secure admin |
| Registrar | Regulatory decisions, applications, ICMS oversight, discipline, reports, and final sign-off |
| Data Quality Officer | Snapshot review, missing data, duplicate review, import QA, receipt matching, and reference cleanup |
| Finance Officer | Read-only financial forecast, receipts, and exports by office scope |
| Reviewer | Assigned reviews after operational access approval |
| Public/applicant support | Help with forms, FAQs, public forum moderation path, and status guidance |

## 11. Commands

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py bootstrap_document_repository
.\.venv\Scripts\python.exe manage.py bootstrap_nursing_council_workflows
.\.venv\Scripts\python.exe manage.py bootstrap_nhwa_workbooks
.\.venv\Scripts\python.exe manage.py seed_engagement_platform
.\.venv\Scripts\python.exe manage.py import_nursing_analytics_snapshot --path "path\to\PNG_Nursing_Council_Integrated_Dashboard_Model.xlsx" --activate
.\.venv\Scripts\python.exe manage.py import_nursing_catherine_licence_breakdown --licence-path "path\to\PNG_Nursing_Council_Cleaned_Licence_Breakdown.xlsx" --cadre-path "path\to\PNG_Nursing_Council_Cadre_Breakdown.xlsx"
.\.venv\Scripts\python.exe manage.py link_receipts_to_individual_records --review-unmatched
.\.venv\Scripts\python.exe manage.py geocode_mapped_entities --limit 100
.\.venv\Scripts\python.exe manage.py check
```
