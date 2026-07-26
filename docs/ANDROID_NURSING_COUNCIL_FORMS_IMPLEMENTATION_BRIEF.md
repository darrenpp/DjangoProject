# Android Nursing Council Forms Implementation Brief

This brief is for the Android Studio coding pair agent implementing the Nursing Council form pack in the offline-first mobile data collection app.

The backend is the source of truth. The Android app collects drafts and evidence only. It must not approve, issue, publish, or promote records. All submissions go through `/api/mobile/v1/` into backend mobile intake staging for review.

## Authoritative Backend Contract

Use these endpoints:

| Purpose | Endpoint |
| --- | --- |
| Login | `POST /api/mobile/v1/auth/login/` |
| Bootstrap forms and lookups | `GET /api/mobile/v1/bootstrap/` |
| Forms only | `GET /api/mobile/v1/forms/` |
| Lookups only | `GET /api/mobile/v1/lookups/` |
| Duplicate check | `POST /api/mobile/v1/duplicates/check/` |
| Create submission | `POST /api/mobile/v1/submissions/` |
| Upload attachment | `POST /api/mobile/v1/submissions/{submission_uuid}/attachments/` |
| Refresh status | `GET /api/mobile/v1/submissions/status/?device_id=...` |
| Register local account | `POST /api/mobile/v1/accounts/register/` |
| Local account status | `GET /api/mobile/v1/accounts/status/` |
| Health | `GET /api/mobile/v1/health/` |

For local USB device testing with `adb reverse tcp:8000 tcp:8000`, the app base URL is:

```text
http://127.0.0.1:8000/
```

For Android emulator testing:

```text
http://10.0.2.2:8000/
```

## Current Enabled Nursing Council Mobile Forms

The current local backend has 12 enabled Nursing Council mobile schemas, all with schema version `2026.05.19`:

| Form Code | Form Name | Enabled Now |
| --- | --- | --- |
| `G1` | Graduate Nurses Checklist | Yes |
| `G2` | List of New Graduate Nurses | Yes |
| `G3` | Graduate Vitae | Yes |
| `G4` | Statement of Competency - Nurses | Yes |
| `G5` | Statement of Competency - Midwives | Yes |
| `G6` | Graduate Midwives Checklist | Yes |
| `G7` | List of Graduate Midwives | Yes |
| `NC1` | Application for Provisional Licence | Yes |
| `NC2` | Application for Full Licence | Yes |
| `NC3` | Renewal of Licence | Yes |
| `NC6` | Competency for Full Licence Nursing | Yes |
| `NC7` | Competency for Full Licence Midwifery | Yes |

The Android app must display only forms returned by `enabled_forms` from `/api/mobile/v1/bootstrap/` or `/api/mobile/v1/forms/`. Do not allow submission of a disabled or missing backend form code.

## Wider Nursing Council Form Catalog

The desktop platform also recognises the wider Nursing Council catalog below. The Android app can include local UI definitions for these codes, but keep them hidden or disabled until the backend returns them as enabled.

| Form Code | Mobile Use |
| --- | --- |
| `G1` | Graduate Nurses Checklist |
| `G2` | List of New Graduate Nurses for Provisional Licence |
| `G3` | Graduate Vitae |
| `G4` | Statement of Competency for Graduate Nurses |
| `G5` | Statement of Competency for Graduate Midwives |
| `G6` | Graduate Midwives Checklist |
| `G7` | List of Graduate Midwives for Licence to Practise |
| `NC1` | Application for Provisional Licence |
| `NC2` | Application for Full Licence |
| `NC3` | Renewal of Licence |
| `NC4` | Overseas Provisional Licence Checklist |
| `NC5` | Overseas Full Registration Application |
| `NC6` | Competency for Full Licence Nursing |
| `NC7` | Competency for Full Licence Midwifery |
| `NC8` | Temporary Licence Application |
| `NC9` | Temporary Overseas Licence Checklist |
| `NC10` | Child Nursing Competency |
| `NC11` | Double Major Full Registration Checklist |

## Required Common Payload Fields

The backend currently requires these top-level payload fields for all enabled mobile forms:

| Field | Required | Notes |
| --- | --- | --- |
| `first_name` | Yes | Applicant given name |
| `surname` | Yes | Family name. `last_name` is accepted but send `surname` too |
| `gender` | Yes | Use controlled values from the app |
| `date_of_birth` | Yes | ISO date, `YYYY-MM-DD` |
| `province` | Yes | From backend lookup where possible |

The Android app should also capture and send these top-level fields whenever available because duplicate checking, review, promotion, and reporting depend on them:

| Field | Notes |
| --- | --- |
| `title` | Mr, Ms, Mrs, Dr, Sr, etc. |
| `middle_name` | Optional |
| `full_name` | Generated display name, optional |
| `nationality` | Default `PNG` for national applicants |
| `applicant_type` | `national` or `overseas` |
| `registration_number` | Primary Nursing Council registration number |
| `registration_no` | Compatibility alias if existing local code uses this name |
| `practitioner_number` | Practitioner number when available |
| `licence_number` | Licence or ATP reference |
| `license_number` | Compatibility alias if existing local code uses US spelling |
| `provisional_licence_number` | For NC2 and full licence transition |
| `previous_licence_number` | For renewal or temporary licence records |
| `cadre` | General Nurse, Midwife, Nurse Aide, Specialist Nurse, etc. |
| `cadre_name` | Same value as `cadre` when needed by backend |
| `specialty_area` | Specialist or child nursing area where applicable |
| `primary_phone` | Applicant phone |
| `phone` | Compatibility alias |
| `email` | Applicant email |
| `district` | From backend lookup where possible |
| `full_address` | Postal or residential address |
| `employment_status` | `employed`, `unemployed`, `inactive`, `retired`, `deceased`, `overseas`, `unknown` |
| `employment_sector` | `public`, `church`, `private`, `ngo`, `overseas`, `unknown` |
| `employer_name` | Employer or sponsoring institution |
| `facility_id` | Backend facility id when matched |
| `facility` | Facility name shown in backend queue |
| `facility_name_raw` | Raw user-entered workplace/facility name |
| `position_title` | Current role or position |
| `workforce_function` | Clinical, teaching, admin, specialist, etc. |
| `start_date` | Employment start date |
| `end_date` | Employment end date if not current |
| `is_current` | Boolean |
| `receipt_number` | Payment receipt number |
| `receipt_date` | Date paid |
| `amount_paid` | Numeric amount |
| `payment_method` | Cash, EFTPOS, bank deposit, etc. |
| `declaration_accepted` | Must be true before sync |
| `signature_text` | Applicant or supervisor name |
| `signed_at` | ISO datetime |

Use `snake_case` keys. Critical matching fields must stay top-level. Additional form-specific fields may be nested under `form_details`, but duplicate and review fields should be duplicated at the top level when they are important.

## Form-Specific Sections

### G1 - Graduate Nurses Checklist

Capture:

- Identity and contact fields.
- Training institution name and id where matched.
- Program completed.
- Completion year and graduation date.
- Cohort or class year.
- Checklist booleans:
  - `valid_id_checked`
  - `passport_photo_checked`
  - `transcript_checked`
  - `completion_letter_checked`
  - `qualification_certificate_checked`
  - `receipt_checked`
  - `nc1_application_ready`
- Registrar or data officer note.
- Attachments: identity, qualification evidence, transcript, completion letter, receipt, passport photo.

### G2 - List of New Graduate Nurses for Provisional Licence

Capture one draft per graduate, not one draft for the whole spreadsheet.

- Identity and contact fields.
- School or institution name.
- Cohort year.
- Student number if available.
- Program completed.
- Recommended for provisional licence: boolean.
- Batch/list reference.
- Attachments: identity, school list evidence, qualification evidence.

### G3 - Graduate Vitae

Capture:

- Identity and contact fields.
- Education history.
- Qualification name.
- Institution attended.
- Program start and completion dates.
- Clinical placements.
- Skills summary.
- Referee names and contacts.
- Declaration.
- Attachments: vitae document, certificates, transcript, ID.

### G4 - Statement of Competency - Nurses

Capture:

- Applicant identity and registration/provisional reference.
- Supervisor name.
- Supervisor registration number.
- Supervisor position and facility.
- Assessment date.
- Competency ratings for:
  - clinical practice
  - infection prevention
  - medication safety
  - documentation
  - ethics and professional conduct
  - communication
  - emergency response
  - public health/community practice
- Overall assessment outcome: competent, not yet competent, needs review.
- Supervisor declaration and signature.
- Attachments: signed competency statement, supervisor evidence, facility confirmation.

### G5 - Statement of Competency - Midwives

Capture:

- Applicant identity and registration/provisional reference.
- Supervisor and facility fields.
- Assessment date.
- Competency ratings for:
  - antenatal care
  - intrapartum care
  - postnatal care
  - newborn care
  - emergency obstetric response
  - family planning
  - community midwifery
  - documentation and ethics
- Overall assessment outcome.
- Supervisor declaration and signature.
- Attachments: signed competency statement and supporting evidence.

### G6 - Graduate Midwives Checklist

Capture:

- Identity and contact fields.
- Midwifery training institution.
- Program completed.
- Completion year and graduation date.
- Checklist booleans for ID, transcript, completion letter, certificate, receipt, competency statement.
- Attachments: identity, transcript, certificate, completion letter, receipt, passport photo.

### G7 - List of Graduate Midwives for Licence to Practise

Capture one draft per graduate midwife.

- Identity and contact fields.
- Institution name.
- Cohort year.
- Program completed.
- Recommended for licence to practise: boolean.
- Batch/list reference.
- Attachments: list evidence, qualification evidence, identity.

### NC1 - Application for Provisional Licence

Capture:

- Identity and contact fields.
- Applicant type: national or overseas.
- Cadre/profession track.
- Qualification details.
- Institution attended.
- Completion date/year.
- Receipt number and payment evidence.
- Supporting document checklist.
- Applicant declaration and signature.
- Attachments: identity, qualification evidence, licence/certificate evidence, receipt, passport photo.

### NC2 - Application for Full Licence

Capture:

- Identity and contact fields.
- Provisional licence number.
- Registration number if already assigned.
- Practitioner number if assigned.
- Current employer/workplace details.
- Competency evidence reference.
- Receipt number and payment evidence.
- Declaration and signature.
- Attachments: identity, provisional licence, competency evidence, qualification evidence, receipt.

### NC3 - Renewal of Licence

Capture:

- Identity and contact fields.
- Registration number.
- Practitioner number.
- Licence number or ATP number.
- Renewal year.
- Current employment/workplace fields.
- Continuing practice evidence.
- CPD/continuing education summary if available.
- Receipt number and payment evidence.
- Declaration and signature.
- Attachments: identity, current licence/ATP, receipt, CPD/evidence documents.

### NC4 - Overseas Provisional Licence Checklist

Keep disabled unless backend enables it.

Capture:

- Identity and contact fields.
- Country of training.
- Overseas institution.
- Qualification name.
- Overseas registration/licence details.
- Verification of good standing.
- English language or official communication evidence where required.
- Checklist booleans for identity, qualifications, verification, receipt, declaration.
- Attachments: overseas qualification, overseas licence, good standing letter, ID, receipt.

### NC5 - Overseas Full Registration Application

Keep disabled unless backend enables it.

Capture:

- Identity and contact fields.
- Applicant type `overseas`.
- Overseas registration number.
- Overseas licence number.
- Country and regulator name.
- PNG employer or sponsor where applicable.
- Qualification and experience details.
- Verification status.
- Receipt and declaration.
- Attachments: identity, overseas licence, qualifications, good standing letter, employer support, receipt.

### NC6 - Competency for Full Licence Nursing

Capture:

- Applicant identity and provisional/full licence references.
- Supervisor name, registration number, role, and facility.
- Assessment period start and end.
- Competency ratings for core nursing practice areas.
- Comments per competency area.
- Overall recommendation.
- Supervisor declaration and signature.
- Applicant acknowledgement.
- Attachments: signed competency form, supervisor evidence, workplace confirmation.

### NC7 - Competency for Full Licence Midwifery

Capture:

- Applicant identity and licence references.
- Supervisor name, registration number, role, and facility.
- Assessment period.
- Competency ratings for midwifery practice areas.
- Case/practice log summary where available.
- Overall recommendation.
- Supervisor declaration and signature.
- Attachments: signed competency form, case log evidence, workplace confirmation.

### NC8 - Temporary Licence Application

Keep disabled unless backend enables it.

Capture:

- Identity and contact fields.
- Temporary licence purpose.
- Proposed start and end dates.
- Employer, sponsor, or host facility.
- Overseas/current licence details.
- Scope of practice requested.
- Receipt and declaration.
- Attachments: identity, current licence, employer/sponsor letter, qualifications, receipt.

### NC9 - Temporary Overseas Licence Checklist

Keep disabled unless backend enables it.

Capture:

- Identity and contact fields.
- Country of current registration.
- Current overseas regulator.
- Temporary work purpose and host facility.
- Checklist booleans for good standing, current licence, ID, qualifications, receipt, declaration.
- Attachments: current overseas licence, good standing letter, ID, qualification evidence, sponsor letter, receipt.

### NC10 - Child Nursing Competency

Keep disabled unless backend enables it.

Capture:

- Applicant identity and licence references.
- Child nursing specialty area.
- Supervisor details.
- Competency ratings for child health, paediatric assessment, medication safety, family communication, emergency response, documentation, safeguarding.
- Overall recommendation.
- Attachments: signed competency statement and supporting evidence.

### NC11 - Double Major Full Registration Checklist

Keep disabled unless backend enables it.

Capture:

- Identity and contact fields.
- Primary qualification/cadre.
- Second major/specialty.
- Institution and program details for both major areas.
- Competency evidence for both major areas.
- Checklist booleans for transcript, certificates, supervisor statements, receipt, ID.
- Registrar review notes.
- Attachments: certificates, transcript, competency evidence, receipt, ID.

## Attachment Rules

The backend currently allows:

- `image/jpeg`
- `image/png`
- `application/pdf`

Maximum file size:

```text
20 MB
```

Common attachment document types:

| Document Type | Required By |
| --- | --- |
| `identity` | All enabled forms |
| `receipt` | Optional in schema, but should be captured when payment is involved |
| `qualification` | Graduation, provisional, full licence, overseas forms |
| `licence_certificate` | `NC1`, `NC2`, `NC6`, `NC7`, and similar licence/competency forms |
| `passport_photo` | Recommended for applications |
| `transcript` | Graduate and qualification forms |
| `competency_statement` | Competency forms |
| `good_standing` | Overseas and temporary forms |
| `employer_support` | Employment, temporary, and overseas forms |

The app must queue attachments offline and upload them after the submission receives a `server_submission_id`.

## Submission Payload Shape

Send one submission per form/draft:

```json
{
  "idempotency_key": "R8YXC08WKHR-localDraftUuid-v1",
  "device_id": "R8YXC08WKHR",
  "local_draft_id": "localDraftUuid",
  "local_version": 1,
  "office_scope": "nursing",
  "form_code": "NC3",
  "schema_version": "2026.05.19",
  "created_offline_at": "2026-05-22T09:30:00+10:00",
  "payload": {
    "first_name": "Mary",
    "surname": "Example",
    "gender": "female",
    "date_of_birth": "1990-01-01",
    "registration_number": "N12345",
    "practitioner_number": "P12345",
    "licence_number": "L12345",
    "cadre": "General Nurse",
    "employment_status": "employed",
    "employment_sector": "public",
    "province": "National Capital District",
    "district": "NCD",
    "facility": "Port Moresby General Hospital",
    "facility_name_raw": "Port Moresby General Hospital",
    "position_title": "Registered Nurse",
    "receipt_number": "R123456",
    "declaration_accepted": true,
    "signature_text": "Mary Example",
    "form_details": {
      "renewal_year": "2026",
      "continuing_practice_summary": "Currently practicing in public facility."
    }
  }
}
```

## Android Implementation Requirements

1. Build the Form Library from `/api/mobile/v1/bootstrap/` or `/api/mobile/v1/forms/`.
2. Use backend `schema_version` from each enabled form. Do not hardcode `2026.05.19` except as a local fallback.
3. Store offline drafts in Room with `local_draft_id`, `local_version`, `form_code`, `schema_version`, `sync_status`, payload JSON, and attachment queue.
4. Use a step-by-step UI:
   - Identity
   - Contact
   - Qualification
   - Employment
   - Form Details
   - Attachments
   - Review and Declaration
5. Use dropdowns for lookup-driven fields: province, district, facility, cadre, employment status, employment sector, document type.
6. Validate required backend fields before sync: `first_name`, `surname`, `gender`, `date_of_birth`, `province`.
7. Validate full form-specific fields before marking a draft ready.
8. Run duplicate check before final sync where connectivity is available.
9. Generate idempotency keys as `deviceId-localDraftId-v{localVersion}`.
10. Never create duplicate submissions when sync is retried.
11. Upload attachments after the server returns `server_submission_id`.
12. Refresh `/api/mobile/v1/submissions/status/` after sync and show backend statuses in Sync Inbox.
13. Show `NEEDS_CORRECTION`, `REJECTED`, `ACCEPTED`, and `PROMOTED` exactly as returned by the backend.
14. Do not let the mobile app approve or issue licences.
15. Do not submit Medical Board forms under Nursing Council scope.

## Acceptance Checklist For Android Pair Agent

- Login works with a mobile collector account.
- Form Library shows the 12 enabled Nursing Council forms from backend bootstrap.
- Disabled local catalog forms are hidden or clearly disabled.
- Each form captures identity, contact, qualification, employment, payment, declaration, and attachments.
- Drafts work offline.
- Attachments are stored offline and queued.
- Submission sync sends correct `/api/mobile/v1/submissions/` payload.
- Attachment sync uses `/api/mobile/v1/submissions/{submission_uuid}/attachments/`.
- Duplicate check works for name, date of birth, registration number, practitioner number, and licence number.
- Backend Mobile Intake Review Queue receives synced submissions.
- Android Sync Inbox shows backend correction/rejection/acceptance status.
- No mobile draft affects reports until backend review accepts or promotes it.
