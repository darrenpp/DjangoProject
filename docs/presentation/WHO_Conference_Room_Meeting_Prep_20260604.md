# WHO Conference Room Meeting Prep

Meeting: Regulatory Boards Database and New Software System  
Venue: WHO Conference Room, Level 4  
Date: Thursday, 4 June 2026  
Time: 10:00 AM - 12:00 PM  
Prepared for: NDOH Regulatory Boards platform presentation

## 1. Meeting Objective

Use the meeting to show that the platform is no longer just a database viewer. It is now a controlled regulatory operations platform for the Nursing Council and Medical Board, covering registry records, applications, licence workflows, analytics, receipts, documents, complaints, discipline, NHWA reporting, public guidance, and mapped references.

The key message:

> The system protects legal registry integrity while making legacy and cleansed data useful for analytics, reporting, decision support, and data-quality work.

## 2. Main Story To Tell

1. The old problem was fragmented records, spreadsheets, paper files, inconsistent complaint handling, weak audit trails, and limited reporting.
2. The platform now separates Nursing Council and Medical Board workspaces and applies role-based access.
3. Imported spreadsheets are not blindly turned into legal records. They are staged, checked, cleansed, reviewed, and only promoted through controlled workflows.
4. Nursing Council analytics now reads from the active cleansed workbook snapshot for accurate reporting, while legal person records remain protected.
5. The system now includes the governance pieces needed for regulatory maturity: document control, ICMS complaints, discipline cases, decision records, finance reporting, receipt review, NHWA workbooks, FAQs, forums, and maps.
6. The remaining work is operational: verified coordinates, staff UAT, data-owner sign-off, production hosting/security, policy approval, and continuing data-quality cleanup.

## 3. Two-Hour Run Sheet

| Time | Segment | Purpose |
|---|---|---|
| 10:00 - 10:05 | Welcome and purpose | Confirm the meeting is about the database and new system readiness. |
| 10:05 - 10:15 | Current problem and governance risk | Explain fragmented records, weak audit trails, and why a controlled platform is needed. |
| 10:15 - 10:30 | Platform overview | Show public portal, login, role-based dashboard, and board separation. |
| 10:30 - 10:50 | Nursing Council analytics | Show snapshot KPIs, charts, drilldowns, and explain legal-registry separation. |
| 10:50 - 11:05 | Regulatory operations | Show Records Hub, workflow tools, document repository, duplicate review, missing-data/data-quality position. |
| 11:05 - 11:20 | Finance and receipts | Show financial forecast and receipt-owner linking/high-value review logic. |
| 11:20 - 11:35 | ICMS, discipline, decisions, NHWA | Show formal case management and reporting alignment. |
| 11:35 - 11:45 | Public/practitioner services | Show public register, FAQs, forum, forms, and map page. |
| 11:45 - 11:55 | Roadmap and decisions needed | Explain what must be signed off before production. |
| 11:55 - 12:00 | Close | Confirm next steps, owners, and date for UAT/sign-off. |

## 4. Recommended Live Demo Path

Keep the demo controlled. Do not click randomly through every menu.

1. Public entry
   - `/`
   - `/accounts/login/`
   - Message: public users and staff start from clear separated pathways.

2. Role-based landing
   - `/dashboard/`
   - Message: the system redirects users according to role and office scope.

3. Nursing Council dashboard
   - `/dashboard/nursing-council/`
   - Show: executive stats, analytics snapshot, charts, workflow tools.
   - Say: Nursing Council analytics comes from the active cleansed workbook snapshot.

4. Nursing analytics drilldown
   - `/dashboard/nursing-council/analytics/summary/`
   - `/dashboard/nursing-council/analytics/drilldown/`
   - Show: server-side filtered facts and Open actions.

5. Records Hub
   - `/records/`
   - `/records/nursingprofessional/`
   - Show: search, sort, pagination, View/Edit controls where authorised.

6. Finance
   - `/dashboard/reports/financial/?office=nursing`
   - Show: Nursing Council-only finance view.
   - Say: finance rows and receipts are evidence, not practitioner counts.

7. Complaints, discipline, and decisions
   - `/dashboard/complaints/`
   - `/dashboard/complaints/discipline/`
   - `/dashboard/complaints/decisions/`
   - Show: formal ICMS path and defensible regulatory decision records.

8. NHWA
   - `/dashboard/nhwa-workbooks/`
   - Say: NHWA is a reporting layer populated from verified platform data. It does not overwrite the registry.

9. Public guidance and engagement
   - `/dashboard/public/faqs/`
   - `/dashboard/public/forum/`
   - `/dashboard/public/map/`
   - Say: public posts are moderated; map uses stored verified coordinates.

## 5. Key Statistics To Quote

Use these as the current presentation figures from the 1 June 2026 documentation pack.

| Area | Figure |
|---|---:|
| Nursing Council analytics lifecycle records | 34,851 |
| Clean ATP records | 19,998 |
| Clean provisional records | 8,158 |
| Clean full-licence records | 6,695 |
| Estimated practitioner match groups | 22,765 |
| Data quality health score | 87.0% |
| Imported licence/history rows | 53,178 |
| Receipts | 11,501 |
| Receipt amount recorded | PGK 822,882.30 |
| Qualification records | 11,863 |
| Missing-data review items | 57,129 |
| Duplicate-review items | 177 |
| Repository folders | 24 |
| Mapped entity references | 1,462 |
| Public FAQ entries | 5 |

Important explanation:

- Nursing Council cleansed workbook analytics and legal live practitioner tables are intentionally separate.
- `Person_Group_Key` is an analytics grouping key only.
- Spreadsheet rows, receipt rows, and ATP cycle rows must not be counted as unique legal practitioners unless promoted or linked through approved workflow.

## 6. What To Say About The 0 Live Nursing Person Tables

If asked why live Nursing Council person tables show 0 nurses/midwives/nurse aides, answer:

> The cleansed Nursing Council workbook has been loaded into the analytics snapshot so the dashboard can report accurate workforce and lifecycle statistics immediately. We deliberately did not push those rows straight into the legal person registry because the workbook uses grouping keys and historical rows, not verified legal practitioner identities. The next step is controlled promotion: match, verify, resolve duplicates, attach receipts/documents, then create or update legal practitioner records through approved workflows.

This is a strength, not a failure. It prevents the platform from creating false legal identities from spreadsheet data.

## 7. Questions You Should Be Ready For

| Question | Strong answer |
|---|---|
| Is the system live? | It is operating locally as a controlled platform foundation with active data, workflows, analytics, and role separation. Production launch still needs hosting/security/UAT sign-off. |
| Are Nursing Council and Medical Board records mixed? | No. They are separated by office scope and backend access checks, not only by hidden menu items. |
| Can imported workbooks overwrite the registry? | No. Imports feed staging, analytics, review, and reporting layers. Legal records require controlled workflow promotion. |
| Why not use `Person_Group_Key` as the practitioner ID? | It is useful for analytics matching, but it is not a legal identity. The system treats it as grouping evidence only. |
| What about complaints and discipline? | ICMS complaints, discipline cases, evidence attachments, events, and formal decision records are now module-supported. |
| How are receipts handled? | Receipts link only where evidence is strong. Unmatched, suspicious, duplicate, or high-value receipts go to review. |
| Does the platform support NHWA? | Yes. NHWA workbooks are a reporting layer populated from verified records and reviewed before export/sign-off. |
| Does the Google map call Google on every page load? | No. Coordinates are stored locally after verification. The page reads local stored coordinates. |
| Why are map markers not fully populated yet? | The reference list exists, but verified coordinates still need to be geocoded or entered before public map demonstration. |
| What still needs policy work? | Legislation, formal SOP approval, document-control policy, operational sign-off, and staff change management remain governance tasks outside software alone. |

## 8. Decisions To Ask For

Close the meeting by asking for specific decisions:

1. Nominate Nursing Council and Medical Board data owners for UAT and sign-off.
2. Confirm which legacy workbook becomes the official starting snapshot for each board.
3. Approve a data-quality review workflow for duplicates, missing fields, and receipt mismatches.
4. Approve the production hosting/security path.
5. Confirm who will own SOP and policy approval for complaints, discipline, documents, and registry decisions.
6. Approve a verified-coordinate exercise for schools, institutions, and facilities before public map release.
7. Set a target date for UAT completion and production readiness review.

## 9. Materials To Bring

Use these files from the project:

- `docs/presentation/NDOH_Regulatory_Platform_Presentation_Pack_20260601.pdf`
- `docs/presentation/NDOH_Regulatory_Platform_Presentation_Brief_20260601.docx`
- `docs/presentation/NDOH_Regulatory_Platform_Documentation_Index_20260601.pdf`
- `docs/NDOH_Full_Scope_Platform_User_Guide_20260601.pdf`
- `docs/NDOH_Government_Launch_Package_20260601.pdf`
- `docs/PLATFORM_UPDATE_BRIEF_20260601.md`
- `docs/DATA_EXTRACTION_AND_POPULATION_GUIDE.md`
- This prep file: `docs/presentation/WHO_Conference_Room_Meeting_Prep_20260604.md`

Bring:

- Laptop charger.
- HDMI/USB-C adapter.
- Offline copies of the PDF and screenshots.
- Test login accounts already checked.
- Browser bookmarks for the demo routes.
- A fallback PDF-only demo in case the network or local server fails.

## 10. Pre-Meeting Technical Checklist

Run these checks on Wednesday 3 June 2026 or early Thursday 4 June 2026:

```powershell
cd C:\Project\regulatoryNCMB\PNG_NC_MB
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py showmigrations
```

Open these pages once before the meeting:

- `/accounts/login/`
- `/dashboard/`
- `/dashboard/nursing-council/`
- `/dashboard/reports/financial/?office=nursing`
- `/records/nursingprofessional/`
- `/dashboard/complaints/`
- `/dashboard/complaints/discipline/`
- `/dashboard/complaints/decisions/`
- `/dashboard/nhwa-workbooks/`
- `/dashboard/public/faqs/`
- `/dashboard/public/forum/`
- `/dashboard/public/map/`

If showing the map, either:

- run `geocode_mapped_entities --limit 100` before the meeting, or
- be clear that the reference list is ready but verified coordinates are still being populated.

## 11. Opening Statement

Use this if you need a concise start:

> Thank you for making time today. The purpose of this presentation is to show the current Regulatory Boards Database and software system, explain how it protects Nursing Council and Medical Board data, and agree on the next steps for production readiness. The platform is not just a spreadsheet replacement. It is a controlled regulatory operations system covering registry records, applications, licence workflows, analytics, receipts, documents, complaints, discipline, NHWA reporting, public guidance, and role-based access.

## 12. Closing Statement

Use this to end the meeting:

> The system foundation is in place. The next decision is not whether the platform can support the regulatory workflow; it can. The next decision is how we complete formal UAT, assign data owners, verify remaining data-quality items, approve SOPs, and move into a controlled production rollout.
