# 13 Enterprise UI Design Standard

## Purpose

This design standard defines the production look and usability rules for the government regulatory operations platform.

## Design Direction

The interface should feel:

- Official.
- Calm.
- Clear.
- Evidence-based.
- Accessible.
- Suitable for registrars, finance users, reviewers, and public users.

It should not feel like a test site, template demo, or experimental dashboard.

## Visual System

| Token | Use |
|---|---|
| Navy | Primary government header/sidebar identity |
| Teal/green | Approved, active, primary workflow action |
| Gold | Warnings, important notices, official highlight |
| Red | Rejected, failed, expired, critical risk |
| White cards | Main content blocks |
| Light grey-blue surface | Page background and table context |

The shared production stylesheet is:

```text
static/css/government-enterprise.css
```

Admin console styling is:

```text
static/css/ndoh-admin.css
```

## Layout Rules

- Keep side navigation consistent.
- Keep top-bar account/settings/logout actions predictable.
- Keep the notification bell beside the signed-in user area and clear unread counts when notifications or threads are opened.
- Use cards for grouped information.
- Use tables for records and auditable data.
- Use DataTables-style search, sort, pagination, and page length controls for large registrar queues.
- Use dashboard number cards only for high-value totals.
- Use executive insight strips for analytics snapshots before raw tables.
- Keep raw tables collapsed below analytics, filters, maps, and work queues unless staff explicitly drills down.
- Use explanatory text beside reports, finance figures, and imports.
- Use maps only for verified reference locations and make clear when coordinates are missing.
- Avoid decorative clutter that competes with official data.

## Accessibility Rules

- Text must have strong contrast.
- Buttons must be visually clear and readable.
- Do not rely on color alone to communicate status.
- Tables must have readable headings.
- Forms must have labels.
- Mobile screens must remain usable.

## Workflow Clarity Rules

Every operational page should answer:

- What is this page for?
- Who is allowed to use it?
- What should the user do first?
- What happens after clicking a button?
- What data source is being shown?
- Is this legal registry data, an analytics snapshot, a workbook import, an NHWA output, or a receipt ledger?
- What must be reviewed before management reporting?

## Board Header Rules

Authenticated board dashboards must identify the user's platform clearly:

- Nursing Council: `Welcome To Your PNG Nursing Council Online Platform Dashboard`.
- Medical Board: `Welcome To Your Medical Board Online Platform Dashboard`.

The PNG national emblem may be used as a subtle dashboard header background. It must remain recognisable, must not cover important text, and must not make the header unreadable.

Public registration and guide areas may also use the emblem as a background identity mark, but forms must remain readable and usable.

## Status Display Rules

Use standard status language:

- Pending.
- Under Review.
- Missing Information.
- Approved.
- Rejected.
- Active.
- Expired.
- Suspended.
- Resolved.
- Opened.
- Read.
- Triage.
- Investigating.
- Escalated.
- Closed.
- Final.
- Superseded.

## Report Display Rules

Reports must show:

- Office scope.
- Generated date/time.
- Exporting user where applicable.
- Live count versus imported row count.
- Source file/date where applicable.
- Remaining data-quality limitations.
- Active analytics snapshot source and generated date where applicable.
- NHWA/reporting sign-off status where applicable.
- Public map coordinate verification status where applicable.

## Production UI Gate

Before launch:

- Smoke-test public home, login, MFA, dashboard, records hub, document repository, financial forecast, public register, profile, and admin console.
- Smoke-test ICMS complaints, discipline, decision register, NHWA workbook centre, public FAQs, public forum, and public map.
- Confirm no placeholder/debug/test labels remain visible.
- Confirm Nursing Council and Medical Board screens are visually consistent but data-separated.
- Confirm sign-in button text is visible.
- Confirm registration Role/Cadre dropdowns render correctly and distinguish CHW provisional from CHW full license.
- Confirm Nursing Professionals and Duplicate Review Queue tables have search, sort, page length, and pagination controls.
- Confirm Standards and Compliance does not show repeated standards header content.
- Confirm analytics charts do not crowd or overlap the sidebar/top bar.
- Confirm public forum moderation states are visually clear.
- Confirm map pages do not show private practitioner information.
- Confirm mobile layout is acceptable.
