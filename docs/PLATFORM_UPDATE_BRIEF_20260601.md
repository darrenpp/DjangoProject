# Platform Update Brief

Project: PNG Nursing Council and Medical Board Online Regulatory Workforce Platform

Updated: 1 June 2026

Audience: System Admin, Nursing Council Registrar, Medical Board Registrar, reviewers, data-quality officers, finance users, support staff, and project handover leads.

## 1. Purpose

This brief records the current platform position after the May/June 2026 interface, Nursing Council analytics snapshot, Catherine workbook refresh, receipt-linking, ICMS, discipline, decision-register, NHWA, mapping, notification, registration, records, duplicate-review, and dashboard access updates.

Use this brief together with the main user guide, deployment checklist, data-cleansing plan, and government launch package.

## 2. Current Live Snapshot

Local database snapshot checked on 1 June 2026. Nursing Council analytics totals come from the active cleansed workbook snapshot and remain separate from legal registry person tables.

| Area | Count |
|---|---:|
| Nursing Council analytics lifecycle records | 34,851 |
| Clean ATP records | 19,998 |
| Clean provisional records | 8,158 |
| Clean full-licence records | 6,695 |
| Estimated practitioner match groups | 22,765 |
| Data quality health score | 87.0% |
| Registered Nurses / Midwives / Nurse Aides / Health Students in live person tables | 0 |
| Community Health Workers | 11,594 |
| Medical Doctors | 327 |
| Applications | 0 |
| Imported licence/history rows | 53,178 |
| Receipts | 11,501 |
| Receipt amount recorded | PGK 822,882.30 |
| Missing-data review items | 57,129 |
| Pending missing-data reviews | 0 |
| Duplicate-review items | 177 |
| Pending duplicate-review items | 177 |
| Qualification records | 11,863 |
| Repository folders | 24 |
| Repository documents | 0 |
| Mapped entity references | 1,462 |
| Geocoded mapped entities | 0 |
| Public FAQ entries | 5 |
| Formal ICMS complaint cases | 0 |
| Disciplinary cases | 0 |
| Regulatory decision records | 0 |

These figures are live local counts and will change as staff import, cleanse, merge, approve, and update records.

Latest completed import:

| Source file | Source kind | Processed / total rows | Completed |
|---|---|---:|---|
| PNG_Nursing_Council_Cleaned_Licence_Breakdown.xlsx + PNG_Nursing_Council_Cadre_Breakdown.xlsx | nursing_catherine_licence_breakdown | 14,853 / 18,615 | 29 May 2026 01:00 UTC |

## 3. Current Interface Updates

- Authenticated dashboards now use board-specific welcome headers:
  - Nursing Council users see `Welcome To Your PNG Nursing Council Online Platform Dashboard`.
  - Medical Board users see `Welcome To Your Medical Board Online Platform Dashboard`.
- The Papua New Guinea national emblem is used in the authenticated dashboard header and public registration guide areas.
- The public registration page includes an emblem background and a controlled Cadre dropdown instead of a free-text cadre field.
- The Cadre dropdown distinguishes CHW pathways:
  - `Medical Board - CHW Provisional Registration`.
  - `Medical Board - CHW Full License`.
- Other cadre/specialty options are labelled by board and registration pathway so applicants choose the correct record track.
- The sign-in button text contrast has been corrected for visibility.
- Standards and Compliance duplicate header content has been removed.

## 4. Notifications, Inbox, And Message Read Status

The notification bell now supports staff-style notification behaviour:

- The bell shows unread notification/message count when messages are sent.
- Opening notification history or the related inbox thread marks the relevant notification as read.
- After the message or notification has been viewed, the bell count clears.
- Registrar and admin users can view notification history.
- Applicant/professional users can view their own notification history and mailbox status.
- When a registrar opens a message from an applicant or professional, the sender's sent/inbox view reflects that the message was opened/read.
- Mailbox folders include Inbox, Sent Items, Archived, Deleted Items, Conversation History, and Notes.

## 5. Records Hub Update

The Nursing Professionals page in the Records Hub now includes registrar-facing table functions:

- Search.
- Sort.
- Page length selection.
- Pagination.
- View action.
- Edit action.
- Add New action where the role is authorised.

Records Hub remains a controlled staff tool. Staff should use it for structured record maintenance and corrections, not as a replacement for registrar decision workflows where an application approval process exists.

## 6. Duplicate Review Queue Update

The Duplicate Review Queue now includes table functions:

- Search duplicate queue.
- Sort columns.
- Page length selection.
- Full-number pagination.
- Horizontal table support for narrow screens.
- Grouped source rows visible inside each review row.
- Action buttons for `Mark Reviewed`, `Mark Merged`, and `Reopen`.

The queue should be used before publishing management figures where duplicate candidates may affect live people counts.

## 7. Financial Forecast Access Update

Financial forecast access remains separated by office scope:

- Nursing Council finance: `/dashboard/reports/financial/?office=nursing`
- Medical Board finance: `/dashboard/reports/financial/?office=medical`

Operations-approved reviewer/data-quality roles can open the financial forecast where their role and office-scope permissions allow it. Finance users remain read-only and cannot perform registry CRUD, imports, registrar approvals, or admin-console work.

## 8. Nursing Council Analytics Snapshot

The Nursing Council dashboard now reads the active cleansed analytics snapshot before falling back to live aggregation. This gives dashboard users accurate workbook-aligned analytics without treating workbook rows as legal registry records.

Snapshot rules:

- Active source: `PNG_Nursing_Council_Integrated_Dashboard_Model.xlsx`.
- Generated date: 27 May 2026.
- Active KPIs: 34,851 lifecycle records, 19,998 clean ATP, 8,158 clean provisional, 6,695 clean full licence, 87.0% data quality health score.
- Drilldowns are server-side and include Open links for authorised staff.
- `Person_Group_Key` is an analytics grouping key only.
- Catherine workbook imports are aligned into analytics/import tables and do not overwrite legal person records automatically.

## 9. ICMS, Discipline, Decisions, Documents, NHWA, And Mapping

New operational modules:

- `/dashboard/complaints/` for formal ICMS complaint, incident, and enquiry cases.
- `/dashboard/complaints/discipline/` for disciplinary case stages, events, attachments, and complaint escalation.
- `/dashboard/complaints/decisions/` for formal regulatory decision records with rationale, authority/SOP reference, evidence summary, conditions, appeal rights, and dates.
- Repository document detail now supports current-version approval/rejection with audit history.
- `/dashboard/nhwa-workbooks/` supports NHWA workbook review as a reporting layer.
- `/dashboard/public/faqs/`, `/dashboard/public/forum/`, and `/dashboard/public/map/` support public guidance, moderated discussions, and mapped reference records.

The map reads stored coordinates only. Use `geocode_mapped_entities --limit 100` or verified admin entry before public map demonstrations.

## 10. Receipt Linking

Receipt-owner matching links receipts only where evidence is strong. Unmatched, duplicate, suspicious, or high-value receipts should be reviewed immediately. Receipts remain finance evidence and must not be counted as practitioners.

## 11. Current Smoke-Test Priority

Before handover or demonstration, smoke-test these routes:

| Route | What to confirm |
|---|---|
| `/accounts/` | Emblem background, visible sign-in button, role and cadre dropdowns. |
| `/accounts/login/` | Login and forgotten-password flow. |
| `/dashboard/` | Role-based redirect. |
| `/dashboard/nursing-council/` | Nursing Council welcome header and emblem. |
| `/dashboard/medical-board/` | Medical Board welcome header and emblem. |
| `/records/nursingprofessional/` | Records Hub DataTables functions and CRUD action visibility. |
| `/dashboard/duplicate-reviews/` | Duplicate queue search, sort, page length, pagination, and action buttons. |
| `/dashboard/reports/financial/` | Financial forecast loads for authorised users and respects scope. |
| `/dashboard/nursing-council/analytics/summary/` | Active snapshot summary returns current KPIs. |
| `/dashboard/nursing-council/analytics/drilldown/` | Server-side facts return with filters and Open actions. |
| `/dashboard/complaints/` | ICMS register loads for authorised staff. |
| `/dashboard/complaints/discipline/` | Discipline register loads for authorised staff. |
| `/dashboard/complaints/decisions/` | Decision register loads for authorised staff. |
| `/dashboard/public/faqs/` | Public FAQ page loads. |
| `/dashboard/public/forum/` | Forum page loads and respects moderation/visibility. |
| `/dashboard/public/map/` | Map page loads from stored mapped entities. |
| `/dashboard/nhwa-workbooks/` | NHWA workbook centre loads for authorised staff. |
| `/notifications/communications/` | Inbox folders, unread badges, read/opened status, and notification history. |
| `/dashboard/standards-alignment/` | Standards and Compliance displays once without repeated header content. |

## 12. Documentation Regeneration Note

Markdown source documents have been updated for the current operating position. Generated PDF and Word outputs should be regenerated from the current source before formal external circulation so screenshots, counts, and generated timestamps match the live platform.
