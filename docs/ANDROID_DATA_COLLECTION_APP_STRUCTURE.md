# Android Data Collection App Structure

## Purpose

Build a data collection only Android app for authorised Nursing Council and Medical Board data entry officers. The app collects new registration data in the field or office, works offline, and syncs clean draft submissions into this Django platform for registrar review.

The Android app must not approve applications, issue licences, verify payments, delete registry records, or expose dashboards. It is a controlled intake tool only.

## Platform Alignment

The app must sync into the existing platform concepts:

- Authentication: mobile JWT login through `/api/mobile/v1/auth/login/`.
- Staff scoping: user office determines available forms.
- Registration workflow: synced submissions enter Mobile Intake staging first and become official application, practitioner, employment, receipt, or repository records only after review and promotion.
- Professional records: synced person data creates or updates the correct workforce model only after validation, duplicate checks, and registrar decision.
- Supporting files: photos, ID images, certificates, competency evidence, receipts, and signatures upload through `/api/mobile/v1/submissions/{submission_uuid}/attachments/` and link to the repository only after acceptance/promotion.
- Review remains web-based: registrars and reviewers continue using the Django platform for approval, rejection, payment verification, and licence actions.

Current API note: the authoritative integration contract is under `/api/mobile/v1/`. Legacy mobile endpoints may remain as compatibility shims only.

For the detailed Nursing Council mobile form list, common payload field names, form-specific sections, attachment rules, and Android acceptance checklist, see `docs/ANDROID_NURSING_COUNCIL_FORMS_IMPLEMENTATION_BRIEF.md`.

## Local Integrated Testing

The desktop/backend and Android app are ready for controlled local integrated testing when the backend is reachable from the emulator or phone and these endpoints respond:

- `/api/mobile/v1/health/`
- `/api/mobile/v1/auth/login/`
- `/api/mobile/v1/bootstrap/`
- `/api/mobile/v1/forms/`
- `/api/mobile/v1/lookups/`
- `/api/mobile/v1/submissions/status/`
- `/api/mobile/v1/accounts/register/`
- `/api/mobile/v1/accounts/status/`

Use:

```text
Desktop browser:   http://127.0.0.1:8000/
Android emulator:  http://10.0.2.2:8000/
Physical phone:    http://YOUR-PC-IP:8000/
Django command:    python manage.py runserver 0.0.0.0:8000
```

Run this helper command from the backend project to print local URLs, firewall guidance, and API smoke-check status:

```powershell
.\.venv\Scripts\python.exe manage.py local_mobile_test_setup --check-api
```

See `docs/LOCAL_MOBILE_INTEGRATED_TESTING.md` for the full local setup and test sequence. Local hosting is not production hosting.

## User Scope

### Nursing Council Data Entry Officer

Allowed to collect:

- Graduand and provisional licence intake.
- New nurse and midwife provisional applications.
- Full licence applications after competency completion.
- Overseas nurse or midwife intake where applicable.
- Nurse aide intake if the Nursing Council office is using the mobile collection app for nurse aides.

Not allowed to collect Medical Board records.

### Medical Board Data Entry Officer

Allowed to collect:

- Medical doctor registration intake.
- Specialist application intake.
- CHW registration intake.
- Medical Board allied health professional intake.
- Facility, private health facility, and training college facility intake only if explicitly enabled for that officer.

Not allowed to collect Nursing Council records.

### System Admin

Allowed to:

- Register devices.
- Assign office scope.
- Enable or disable specific form packs.
- Revoke devices and force token logout.
- View sync errors and audit trails.

## Important Backend Gap

The current platform has dedicated models for:

- `NursingProfessional`
- `Midwife`
- `NurseAide`
- `HealthStudent`
- `MedicalDoctor`
- `CommunityHealthWorker`
- `Facility`
- `TrainingInstitution`

The platform currently does not have a dedicated `AlliedHealthProfessional` model. The Android app can still collect Allied Health Professional intake for the Medical Board, but the sync API should store those submissions as pending `Application` rows with `profession_track="allied_health"` and full details in `Application.payload` until the backend model is added. Do not force allied health workers into `MedicalDoctor` or `CommunityHealthWorker`.

## Form Packs

### Nursing Council Form Pack

Use these platform form codes.

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
| `NC3` | Renewal of Licence, optional for mobile intake |
| `NC4` | Overseas Provisional Licence Checklist |
| `NC5` | Overseas Full Registration Application |
| `NC6` | Competency for Full Licence Nursing |
| `NC7` | Competency for Full Licence Midwifery |
| `NC8` | Temporary Licence Application |
| `NC9` | Temporary Overseas Licence Checklist |
| `NC10` | Child Nursing Competency |
| `NC11` | Double Major Full Registration Checklist |

Recommended phase 1 Nursing intake:

- `G1`, `G2`, `G3`, `G4`, `G5`, `G6`, `G7`
- `NC1`
- `NC2`
- `NC6`, `NC7`

### Medical Board Form Pack

Use these platform form codes.

| Form Code | Mobile Use |
| --- | --- |
| `MD1` | Medical doctor public registration intake |
| `CHW1` | Community Health Worker registration |
| `MBSP` | Specialist registration application |
| `MBRN` | Medical Board renewal or registration detail capture |
| `MBAC` | Accreditation Checklist for Facilities |
| `MBPF` | Private Health Facilities Checklist |
| `MBTC` | Training Colleges Facilities Form |

Recommended phase 1 Medical Board intake:

- `MD1`
- `CHW1`
- `MBSP`
- Allied Health intake using `profession_track="allied_health"` in a new mobile sync payload.

Facility forms should be phase 2 because they create or update `Facility` records and need stronger duplicate and ownership controls.

## Android App Modules

### 1. Authentication Module

Responsibilities:

- Login with username and password through JWT.
- Store access and refresh tokens securely.
- Refresh tokens silently.
- Enforce officer office scope from profile data.
- Lock the app after inactivity.
- Support forced logout when the server revokes a device.

Recommended Android components:

- Kotlin.
- Jetpack Compose UI.
- Retrofit and OkHttp.
- Encrypted DataStore for tokens.
- BiometricPrompt or device PIN for local unlock.

### 2. Bootstrap and Lookup Module

Downloads read-only reference data needed for offline work:

- Available form packs by user office.
- Form definitions and form version.
- Province and district lists.
- Training institutions with type: PNG, overseas, CHW, unclear.
- Facility master records, once populated.
- Cadres and practitioner categories.
- Document requirement lists.
- Choice lists for gender, marital status, applicant type, employment status, ownership, worker type, and Medical Board practitioner categories.

The app should cache a `lookup_version` and only refresh changed lists.

### 3. Draft Collection Module

Creates local offline drafts. A draft is not a registry record until synced and accepted by the server.

Core screens:

- Officer home.
- Select office and form pack.
- Search existing person before new entry.
- Person identity.
- Contact and address.
- Qualification and institution.
- Employment, workplace, or competency placement.
- Documents and photos.
- Declaration and signature.
- Review and submit to sync queue.

Data entry design rules:

- Required fields are shown before optional fields.
- Save progress automatically.
- Allow drafts without internet.
- Use dropdowns for controlled fields.
- Allow free text only where the platform currently allows free text.
- Show "Needs review" when an institution or facility cannot be matched.

### 4. Duplicate Check Module

Runs two checks:

- Local check against unsynced drafts on the device.
- Server check when online before final sync.

Match on:

- Registration number.
- Practitioner number.
- First name, last name, date of birth.
- Phone and email.
- Institution plus completion year.
- Existing professional model where known.

Duplicate result actions:

- `new_record`: safe to sync.
- `possible_duplicate`: sync as pending with duplicate warning.
- `existing_record`: block creation unless officer changes to update/renewal flow.

### 5. Document Capture Module

Supports:

- Passport photo.
- ID document image.
- Qualification certificate.
- Transcript.
- Competency evidence.
- Employer reference.
- Receipt image, only as evidence capture, not payment verification.
- Signature image or typed signature depending on form rules.

Rules:

- Compress images before sync.
- Preserve original timestamp.
- Store SHA-256 hash for duplicate upload detection.
- Encrypt files at rest.
- Queue files separately from JSON payload.

### 6. Sync Module

Uses an outbox pattern.

Sync states:

- `draft`
- `ready_to_sync`
- `syncing`
- `synced_pending_review`
- `server_rejected`
- `needs_correction`
- `conflict`

Sync rules:

- Use client-generated UUIDs for every draft and attachment.
- Sync JSON first, then attachments.
- Make sync idempotent by sending `client_record_id`.
- Retry failed syncs with exponential backoff.
- Do not delete local drafts after sync; archive them read-only.
- Allow officer corrections when server returns validation errors.

### 7. Audit Module

Every device action should create an audit event:

- Login.
- Draft created.
- Draft edited.
- Document captured.
- Duplicate check performed.
- Sync attempted.
- Sync succeeded or failed.
- Server correction received.

Sync audit events to Django `AuditLog` or a new `MobileSyncAuditLog`.

## Local Android Database Structure

Use Room with encrypted storage.

### `mobile_user_session`

| Field | Type |
| --- | --- |
| `user_id` | string |
| `username` | string |
| `role` | string |
| `department` | string |
| `office_scope` | enum: `nursing`, `medical`, `admin` |
| `device_id` | string |
| `last_login_at` | datetime |
| `token_expires_at` | datetime |

### `lookup_item`

| Field | Type |
| --- | --- |
| `lookup_type` | string |
| `code` | string |
| `label` | string |
| `parent_code` | string nullable |
| `metadata_json` | json |
| `is_active` | boolean |
| `version` | string |

### `data_collection_draft`

| Field | Type |
| --- | --- |
| `client_record_id` | uuid |
| `office_scope` | enum |
| `form_code` | string |
| `pathway` | string |
| `profession_track` | string |
| `target_model` | string |
| `status` | enum |
| `created_by_username` | string |
| `created_at` | datetime |
| `updated_at` | datetime |
| `collected_at` | datetime |
| `collected_location_lat` | decimal nullable |
| `collected_location_lng` | decimal nullable |
| `server_application_id` | integer nullable |
| `server_professional_id` | string nullable |
| `server_validation_json` | json |

### `person_draft`

| Field | Type |
| --- | --- |
| `client_record_id` | uuid |
| `title` | string nullable |
| `first_name` | string |
| `middle_name` | string nullable |
| `last_name` | string |
| `full_name` | string |
| `gender` | enum |
| `date_of_birth` | date nullable |
| `marital_status` | string nullable |
| `nationality` | string |
| `applicant_type` | enum: `national`, `overseas` |
| `registration_no` | string nullable |
| `registration_number` | string nullable |
| `practitioner_number` | string nullable |
| `primary_phone` | string nullable |
| `email` | string nullable |
| `province` | string nullable |
| `district` | string nullable |
| `full_address` | text nullable |

### `qualification_draft`

| Field | Type |
| --- | --- |
| `client_record_id` | uuid |
| `qualification_name` | string |
| `institution_name` | string |
| `institution_id` | integer nullable |
| `institution_type` | enum: `png`, `overseas`, `chw`, `unclear` |
| `program_completed` | string |
| `date_started` | date nullable |
| `date_completed` | date nullable |
| `completion_year` | integer nullable |
| `country` | string nullable |
| `certificate_attached` | boolean |
| `transcript_attached` | boolean |

### `employment_draft`

| Field | Type |
| --- | --- |
| `client_record_id` | uuid |
| `employer_name` | string nullable |
| `facility_name` | string nullable |
| `facility_id` | integer nullable |
| `place_of_work` | string nullable |
| `workplace_address` | text nullable |
| `position_held` | string nullable |
| `employment_status` | string nullable |
| `area_of_employment` | string nullable |
| `worker_type` | string nullable |
| `duration_of_employment` | string nullable |
| `supervisor_name` | string nullable |
| `supervisor_registration_number` | string nullable |

### `application_payload_draft`

Stores form-specific fields that do not fit the core person, qualification, or employment tables.

| Field | Type |
| --- | --- |
| `client_record_id` | uuid |
| `payload_json` | json |
| `declaration_accepted` | boolean |
| `signature_text` | string nullable |
| `signature_image_attachment_id` | uuid nullable |

### `attachment_draft`

| Field | Type |
| --- | --- |
| `attachment_id` | uuid |
| `client_record_id` | uuid |
| `document_code` | string |
| `document_label` | string |
| `local_file_uri` | string |
| `mime_type` | string |
| `file_size` | integer |
| `sha256` | string |
| `captured_at` | datetime |
| `sync_status` | enum |
| `server_document_id` | integer nullable |

### `sync_outbox`

| Field | Type |
| --- | --- |
| `outbox_id` | uuid |
| `client_record_id` | uuid |
| `operation` | enum: `create_application`, `upload_attachment`, `submit_audit` |
| `payload_json` | json |
| `attempt_count` | integer |
| `last_attempt_at` | datetime nullable |
| `next_attempt_at` | datetime nullable |
| `last_error` | text nullable |

## Backend Mobile API Structure

Add these endpoints under `/workforce/api/mobile/`.

### `GET /workforce/api/mobile/bootstrap/`

Returns officer scope, enabled form packs, form fields, choice lists, document requirements, and lookup versions.

Response shape:

```json
{
  "server_time": "2026-05-12T09:00:00+10:00",
  "officer": {
    "username": "nursing_data_entry",
    "office_scope": "nursing",
    "department": "Nursing Council"
  },
  "enabled_forms": ["G1", "G2", "G3", "G4", "NC1", "NC2", "NC6"],
  "lookups": {
    "provinces": [],
    "districts": [],
    "institutions": [],
    "facilities": [],
    "cadres": [],
    "document_types": []
  }
}
```

### `POST /workforce/api/mobile/duplicate-check/`

Checks whether a draft looks like an existing person.

Request:

```json
{
  "office_scope": "nursing",
  "form_code": "NC1",
  "first_name": "Mary",
  "last_name": "Kila",
  "date_of_birth": "2001-03-18",
  "registration_no": "",
  "primary_phone": "70000000",
  "email": "mary@example.com"
}
```

Response:

```json
{
  "result": "possible_duplicate",
  "matches": [
    {
      "model": "NursingProfessional",
      "id": 123,
      "display_name": "Mary Kila",
      "registration_no": "NC-2026-001",
      "match_score": 0.86
    }
  ]
}
```

### `POST /workforce/api/mobile/sync/batch/`

Creates pending applications from offline drafts.

Request:

```json
{
  "device_id": "android-device-uuid",
  "app_version": "1.0.0",
  "client_batch_id": "uuid",
  "records": [
    {
      "client_record_id": "uuid",
      "office_scope": "nursing",
      "form_code": "NC1",
      "pathway": "local_nursing_graduate",
      "profession_track": "nursing_graduand",
      "target_model": "healthstudent",
      "person": {
        "first_name": "Mary",
        "last_name": "Kila",
        "gender": "Female",
        "date_of_birth": "2001-03-18",
        "applicant_type": "national",
        "primary_phone": "70000000",
        "email": "mary@example.com",
        "province": "National Capital District",
        "full_address": "Boroko"
      },
      "qualification": {
        "institution_name": "Pacific Adventist University School of Nursing",
        "institution_type": "png",
        "program_completed": "Diploma in General Nursing",
        "completion_year": 2026
      },
      "employment": {
        "facility_name": "",
        "place_of_work": "",
        "supervisor_name": ""
      },
      "payload": {
        "declaration_accepted": true,
        "applicant_signature": "Mary Kila"
      },
      "attachments": [
        {
          "attachment_id": "uuid",
          "document_code": "passport_photo",
          "sha256": "..."
        }
      ]
    }
  ]
}
```

Response:

```json
{
  "accepted": [
    {
      "client_record_id": "uuid",
      "server_application_id": 9001,
      "server_status": "pending"
    }
  ],
  "rejected": [],
  "needs_correction": []
}
```

### `POST /workforce/api/mobile/attachments/`

Multipart upload for files linked to an accepted `client_record_id`.

Required fields:

- `client_record_id`
- `server_application_id`
- `attachment_id`
- `document_code`
- `file`
- `sha256`

### `GET /workforce/api/mobile/sync/status/`

Returns server status for records synced by the logged-in officer or device.

## Server Mapping Rules

### Nursing Council

| Mobile Form | Target Model | Server Result |
| --- | --- | --- |
| `NC1` | `HealthStudent` or `NursingProfessional` depending pathway | Create pending provisional application |
| `G1` to `G7` | `HealthStudent` or batch payload | Create pending supporting application/form response |
| `NC2` | `NursingProfessional` or `Midwife` | Create pending full licence application |
| `NC6`, `NC7`, `NC10` | Same professional as linked application | Create pending competency application/form response |
| `NC5` | `NursingProfessional` or `Midwife` with `applicant_type="overseas"` | Create pending overseas full registration |
| `NC8` | `NursingProfessional` or `Midwife` with temporary pathway | Create pending temporary licence |

### Medical Board

| Mobile Form | Target Model | Server Result |
| --- | --- | --- |
| `MD1` | `MedicalDoctor` | Create pending medical registration application |
| `CHW1` | `CommunityHealthWorker` | Create pending CHW registration application |
| `MBSP` | `MedicalDoctor` | Create pending specialist registration application |
| Allied Health intake | pending `Application.payload` until model exists | Create pending Medical Board allied health application |
| `MBAC`, `MBPF`, `MBTC` | `Facility` | Create pending facility application when facility intake is enabled |

## Validation Rules

Minimum required fields for all new people:

- First name.
- Last name.
- Gender.
- Applicant type: national or overseas.
- Date of birth when available.
- Phone or email.
- Province or full address.
- Form code.
- Declaration accepted.

Nursing required fields:

- Institution attended.
- Program completed.
- Completion year or completion date.
- Qualification evidence for provisional and full licence forms.
- Competency supervisor details for full licence transition forms.

Medical Board required fields:

- Practitioner category.
- Initial qualification.
- Institution attended.
- Country.
- Registration or application type.
- Employment or workplace details where required.

Facility required fields:

- Facility name.
- Ownership.
- Province and district.
- Physical address.
- Contact person and contact number.
- Declaration accepted.

## Security Rules

- Require JWT authentication for every sync endpoint.
- Require server-side office scoping, not just Android UI hiding.
- Only allow mobile users with data-entry permission.
- Encrypt local database and files.
- Do not store passwords.
- Redact tokens from logs.
- Add device registration and revocation.
- Audit every sync operation.
- Reject form codes outside the officer office.
- Reject approval, rejection, payment verification, and delete actions from mobile.

## Recommended Android Package Structure

```text
pg.gov.ndoh.registrycollector
  core/
    auth/
    network/
    security/
    sync/
    database/
    audit/
  feature/
    login/
    home/
    bootstrap/
    duplicatecheck/
    nursing/
      graduand/
      provisional/
      fulllicence/
      competency/
      overseas/
    medical/
      doctor/
      specialist/
      chw/
      alliedhealth/
      facility/
    documents/
    reviewsubmit/
    syncstatus/
  data/
    local/
    remote/
    repository/
  domain/
    model/
    validation/
    mapper/
```

## Sync Lifecycle

1. Officer logs in.
2. App downloads bootstrap lookups and form definitions.
3. Officer selects Nursing Council or Medical Board form pack based on assigned scope.
4. Officer searches for an existing person.
5. Officer creates a new draft.
6. App validates fields locally.
7. App captures documents and signature.
8. App queues the draft.
9. When online, app performs duplicate check.
10. App syncs the draft to Django.
11. Django creates pending `Application` and related draft records.
12. App uploads attachments.
13. Registrar reviews in the web platform.
14. App receives final status for the officer's submitted records.

## Phase Plan

### Phase 1

- JWT login.
- Device registration.
- Nursing Council: `NC1`, `NC2`, `G1` to `G7`, `NC6`, `NC7`.
- Medical Board: `MD1`, `CHW1`, `MBSP`.
- Offline drafts.
- Duplicate check.
- Sync to pending applications.
- Attachment upload.
- Officer sync-status inbox.

### Phase 2

- Allied Health backend model and mobile form pack.
- Facility forms: `MBAC`, `MBPF`, `MBTC`.
- Institution and facility matching workflow.
- Supervisor assignment capture.
- Bulk graduand list capture.
- QR or barcode scanning for application receipts.

### Phase 3

- Advanced data quality checks.
- Field-level correction requests.
- Device fleet administration.
- Offline lookup delta sync.
- Mobile data collection analytics for supervisors.

## Acceptance Criteria

- A Nursing Council officer cannot submit Medical Board forms.
- A Medical Board officer cannot submit Nursing Council forms.
- Offline drafts survive app restart and device reboot.
- Duplicate checks run before sync when internet is available.
- Every synced record creates a pending application, not an approved licence.
- Attachments are linked to the correct pending application.
- The same `client_record_id` cannot create duplicate server applications.
- Server-side audit logs show who collected and synced each record.
- Allied Health records are not counted as doctors or CHWs unless the backend model explicitly supports that mapping.
- Facility workplace references are not counted as verified facilities unless they become `Facility` master records.
