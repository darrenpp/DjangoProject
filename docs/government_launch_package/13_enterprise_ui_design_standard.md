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
- Use cards for grouped information.
- Use tables for records and auditable data.
- Use dashboard number cards only for high-value totals.
- Use explanatory text beside reports, finance figures, and imports.
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
- What must be reviewed before management reporting?

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

## Report Display Rules

Reports must show:

- Office scope.
- Generated date/time.
- Exporting user where applicable.
- Live count versus imported row count.
- Source file/date where applicable.
- Remaining data-quality limitations.

## Production UI Gate

Before launch:

- Smoke-test public home, login, MFA, dashboard, records hub, document repository, financial forecast, public register, profile, and admin console.
- Confirm no placeholder/debug/test labels remain visible.
- Confirm Nursing Council and Medical Board screens are visually consistent but data-separated.
- Confirm mobile layout is acceptable.
