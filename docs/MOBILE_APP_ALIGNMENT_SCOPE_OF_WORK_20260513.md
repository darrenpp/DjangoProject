# Mobile App Alignment Scope of Work

Date: 2026-05-13  
System: NDOH Regulatory Bodies Nursing Council and Medical Board Online Workforce System  
Audience: Android Studio implementation agent

## Copy-Paste Agent Instruction

Use this instruction when assigning work to the Android Studio agent:

```text
You are building the Android data collection app for the NDOH Regulatory Bodies Workforce System. Align the mobile app with the current Django web platform, not with an invented API or standalone workflow.

Build a data collection only app. The mobile app must authenticate staff, download office-scoped form packs and lookup data, collect offline drafts, perform duplicate checks, sync pending applications, upload attachments, and show sync status. It must not approve applications, reject applications, issue licences, verify payments, delete records, edit dashboards, or bypass registrar review.

Use JWT login at /accounts/token/ and /accounts/token/refresh/. Use the current mobile API under /workforce/api/mobile/ or /api/mobile/. All synced records must become pending Application rows on the web platform. Attachments must be uploaded after the JSON sync and linked to the pending application through the server attachment endpoint.

Respect office boundaries strictly. A Medical Board officer may only collect Medical Board forms. A Nursing Council officer may only collect Nursing Council forms. Server-side scoping already exists, but the Android UI must also hide invalid forms and prevent invalid drafts before sync.

Implement offline-first collection with Room, encrypted local storage, an outbox sync queue, idempotent client_record_id values, attachment hashing, and clear sync-state handling. Follow this scope of work exactly.
```

## Current Web Platform Stage

The Django web platform currently provides:

- JWT authentication through `/accounts/token/` and `/accounts/token/refresh/`.
- User profile API through `/accounts/profile/api/`.
- Staff/professional read API through `/workforce/api/staff/`.
- Mobile sync API through both:
  - `/workforce/api/mobile/...`
  - `/api/mobile/...`
- Office-scoped Records Hub for web registrars.
- Separate Medical Board and Nursing Council scoping.
- Pending `Application` records as the intake queue for registrar review.
- `ApplicationFormResponse` records for submitted form JSON.
- Document Repository upload support for mobile attachments.
- `AuditLog` entries for mobile sync and mobile attachment upload.

The Android app must treat the Django web platform as the source of truth. The app must not create final professional licences directly.

## Primary Goal

Build an Android app that lets approved staff collect registration data offline and sync it into the Django platform for review.

The app must support:

- Staff login.
- Office-scoped bootstrap.
- Form pack selection.
- Offline draft creation.
- Local duplicate warning.
- Server duplicate check.
- JSON sync to pending application.
- Attachment upload.
- Sync status tracking.
- Local audit trail.

The app must not support:

- Approval.
- Rejection.
- Licence issue.
- Payment verification.
- Registry delete.
- Dashboard management.
- Generic record editing.

## Recommended Android Stack

Use:

- Kotlin.
- Jetpack Compose.
- Material 3.
- Retrofit.
- OkHttp.
- Kotlin serialization or Moshi.
- Room for local database.
- EncryptedSharedPreferences or Encrypted DataStore for tokens and device identity.
- SQLCipher or an equivalent encrypted Room strategy for local drafts if available.
- WorkManager for background sync.
- CameraX or Android Photo Picker for evidence capture.
- BiometricPrompt or device credential for local app unlock.

Do not build the app as a WebView wrapper.

## Runtime Environments

For Android Emulator:

- Django local base URL: `http://10.0.2.2:8000`

For a physical Android phone on the same network:

- Use the Windows host LAN IP, for example `http://192.168.x.x:8000`.
- Ensure Django `ALLOWED_HOSTS` permits the host IP during development.

For production:

- Use HTTPS only.
- Pin base URL through build config.
- Do not hard-code local development URLs in production builds.

## Authentication

### Login

Endpoint:

```text
POST /accounts/token/
```

Request:

```json
{
  "username": "medical_board_registrar",
  "password": "password"
}
```

Response:

```json
{
  "access": "jwt-access-token",
  "refresh": "jwt-refresh-token"
}
```

Store:

- Access token securely.
- Refresh token securely.
- Token expiry time.
- Device UUID.
- Last login time.

### Refresh

Endpoint:

```text
POST /accounts/token/refresh/
```

Request:

```json
{
  "refresh": "jwt-refresh-token"
}
```

Use refreshed access tokens automatically before calling mobile APIs.

### Profile

Endpoint:

```text
GET /accounts/profile/api/
```

Use this to cache:

- `id`
- `username`
- `email`
- `role`
- `department`
- `phone`
- `registration_number`
- `license_number`

Do not decide office scope using only local string matching. Always call mobile bootstrap after login because the backend returns the actual allowed mobile office scope.

## Authorization Rules

Mobile sync is only for approved staff/operations users. The backend currently allows users who pass `can_manage_regulatory_operations`.

Expected allowed users:

- System Admin.
- Registrar with approved role.
- Operations-approved reviewer.

Expected denied users:

- Public applicants.
- Nurses, doctors, CHWs, nurse aides, graduands acting as applicants.
- Finance-only users.
- View-only users.

The Android app must show an access-denied screen if bootstrap returns HTTP 403.

## Current Mobile Endpoints

Use these endpoints. Prefer `/workforce/api/mobile/...` in the Android app because it matches the existing workforce namespace.

Equivalent root API routes also exist under `/api/mobile/...`.

### Bootstrap

```text
GET /workforce/api/mobile/bootstrap/
GET /workforce/api/mobile/bootstrap/?office_scope=medical
GET /workforce/api/mobile/bootstrap/?office_scope=nursing
```

Authorization:

```text
Authorization: Bearer <access-token>
```

Purpose:

- Confirms mobile access.
- Returns officer office scope.
- Returns enabled form codes.
- Returns form definitions where configured.
- Returns lookup data for offline use.

Expected response:

```json
{
  "server_time": "2026-05-13T10:00:00+10:00",
  "officer": {
    "username": "medical_board_registrar",
    "office_scope": "medical",
    "department": "Medical Board",
    "assigned_scopes": ["medical"]
  },
  "enabled_forms": ["CHW1", "MBAC", "MBPF", "MBRN", "MBSP", "MBTC", "MD1", "MD2"],
  "form_definitions": [],
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

Android requirements:

- Cache the full bootstrap result.
- Refresh bootstrap at login and when user taps refresh lookups.
- Use `enabled_forms` to build the home screen.
- Use `lookups` to populate dropdowns.
- Never show a form not returned by bootstrap.

### Duplicate Check

```text
POST /workforce/api/mobile/duplicate-check/
```

Request:

```json
{
  "office_scope": "medical",
  "form_code": "CHW1",
  "target_model": "communityhealthworker",
  "first_name": "Ally",
  "last_name": "Mark",
  "date_of_birth": "1985-01-01",
  "registration_no": "CHW-13567",
  "primary_phone": "70000000",
  "email": "ally@example.test"
}
```

Response when possible duplicate:

```json
{
  "result": "possible_duplicate",
  "form_code": "CHW1",
  "matches": [
    {
      "model": "CommunityHealthWorker",
      "id": 123,
      "display_name": "Ally Mark",
      "registration_no": "CHW-13567",
      "match_score": 0.98
    }
  ]
}
```

Response when no match:

```json
{
  "result": "new_record",
  "form_code": "CHW1",
  "matches": []
}
```

Android requirements:

- Run local duplicate check first against local unsynced drafts.
- Run server duplicate check before sync when online.
- If `possible_duplicate`, show a warning and require officer acknowledgement.
- Do not block sync unless the server returns a validation error.
- Include duplicate warning details in the final draft payload if the officer proceeds.

### Sync Batch

```text
POST /workforce/api/mobile/sync/batch/
```

Purpose:

- Creates pending `Application` records only.
- Creates an `ApplicationFormResponse`.
- Writes mobile sync audit log.
- Does not create an approved licence.
- Does not verify payment.
- Does not delete or overwrite registry records.

Request:

```json
{
  "device_id": "android-device-uuid",
  "app_version": "1.0.0",
  "client_batch_id": "batch-uuid",
  "records": [
    {
      "client_record_id": "record-uuid",
      "office_scope": "medical",
      "form_code": "CHW1",
      "pathway": "medical_board",
      "profession_track": "community_health_worker",
      "target_model": "communityhealthworker",
      "person": {
        "first_name": "Ally",
        "middle_name": "",
        "last_name": "Mark",
        "gender": "Male",
        "date_of_birth": "1985-01-01",
        "applicant_type": "national",
        "primary_phone": "70000000",
        "email": "ally@example.test",
        "province": "National Capital District",
        "district": "Port Moresby",
        "full_address": "Port Moresby"
      },
      "qualification": {
        "institution_name": "Rumginae",
        "institution_type": "chw",
        "program_completed": "Community Health Worker",
        "completion_year": 2026
      },
      "employment": {
        "facility_name": "Port Moresby General Hospital",
        "place_of_work": "Hospital",
        "position_held": "CHW"
      },
      "payload": {
        "declaration_accepted": true,
        "applicant_signature": "Ally Mark",
        "duplicate_acknowledged": false
      },
      "attachments": [
        {
          "attachment_id": "attachment-uuid",
          "document_code": "id_document",
          "sha256": "file-hash"
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
      "client_record_id": "record-uuid",
      "server_application_id": 9001,
      "server_status": "pending"
    }
  ],
  "rejected": [],
  "needs_correction": []
}
```

Idempotent response when the same `client_record_id` is sent again:

```json
{
  "accepted": [
    {
      "client_record_id": "record-uuid",
      "server_application_id": 9001,
      "server_status": "pending",
      "idempotent": true
    }
  ],
  "rejected": [],
  "needs_correction": []
}
```

Android requirements:

- Generate `client_record_id` as UUID when draft is created.
- Never regenerate `client_record_id` after retry.
- Generate `client_batch_id` for each sync attempt group.
- Send only records whose local status is `ready_to_sync`.
- If accepted, store `server_application_id`.
- If idempotent, treat as success and update local status.
- If rejected, keep draft editable and show rejection detail.
- If needs correction, keep draft editable and highlight missing fields.

### Attachment Upload

```text
POST /workforce/api/mobile/attachments/
Content-Type: multipart/form-data
```

Required multipart fields:

- `client_record_id`
- `server_application_id`
- `attachment_id`
- `document_code`
- `sha256`
- `file`

Example fields:

```text
client_record_id=record-uuid
server_application_id=9001
attachment_id=attachment-uuid
document_code=id_document
sha256=file-hash
file=@id_document.jpg
```

Response:

```json
{
  "client_record_id": "record-uuid",
  "server_application_id": 9001,
  "document_id": 44,
  "repository_id": "repository-uuid",
  "version_id": 62
}
```

Android requirements:

- Upload attachments only after sync batch accepts the record.
- Use one request per attachment.
- Store returned `document_id`, `repository_id`, and `version_id`.
- Retry failed attachment uploads independently from JSON sync.
- Do not send attachments for a record without `server_application_id`.
- Recalculate SHA-256 before upload if file was edited or compressed.

### Sync Status

```text
GET /workforce/api/mobile/sync/status/
GET /workforce/api/mobile/sync/status/?client_record_id=record-uuid
GET /workforce/api/mobile/sync/status/?device_id=android-device-uuid
```

Response:

```json
{
  "count": 1,
  "results": [
    {
      "client_record_id": "record-uuid",
      "server_application_id": 9001,
      "form_code": "CHW1",
      "office_scope": "medical",
      "server_status": "pending",
      "submitted_date": "2026-05-13",
      "approved_date": null,
      "reviewer_notes": "Synced from Android mobile data collection by medical_board_registrar."
    }
  ]
}
```

Android requirements:

- Poll status manually through a Sync Status screen.
- Optionally run background status refresh through WorkManager.
- Update local read-only archive when server status changes.
- Do not expose approval/rejection buttons.

## Office Scope Rules

### Medical Board Scope

Allowed form codes:

- `MD1`
- `MD2`
- `CHW1`
- `MBSP`
- `MBRN`
- `MBAC`
- `MBPF`
- `MBTC`

Allowed target models:

- `medicaldoctor`
- `communityhealthworker`
- `facility`
- `traininginstitution`
- `alliedhealth`
- `other`

Important Medical Board rule:

- Allied Health has no dedicated backend model yet.
- Collect Allied Health as `target_model="alliedhealth"` and `profession_track="allied_health"`.
- Store all Allied Health details in `payload`.
- Do not map Allied Health into `MedicalDoctor` or `CommunityHealthWorker`.

### Nursing Council Scope

Allowed form codes:

- `G1`
- `G2`
- `G3`
- `G4`
- `G5`
- `G6`
- `G7`
- `NC1`
- `NC2`
- `NC3`
- `NC4`
- `NC5`
- `NC6`
- `NC7`
- `NC8`
- `NC9`
- `NC10`
- `NC11`

Allowed target models:

- `nursingprofessional`
- `midwife`
- `nurseaide`
- `healthstudent`
- `graduand`
- `other`

Important Nursing Council rule:

- Use `healthstudent` or `graduand` for graduand/provisional intake.
- Use `nursingprofessional` for nurse registration and renewal.
- Use `midwife` for midwifery intake.
- Use `nurseaide` only for nurse aide intake.

## Mobile Form Packs

### Phase 1 Forms

Build these first.

Medical Board:

- `MD1`: Medical doctor registration intake.
- `CHW1`: Community Health Worker registration.
- `MBSP`: Specialist registration application.
- Allied Health intake as Medical Board payload-only draft.

Nursing Council:

- `G1`: Graduate Nurses Checklist.
- `G2`: Graduate Nurse Batch List.
- `G3`: Graduate Vitae.
- `G4`: Nurse Competency Statement.
- `G5`: Midwife Competency Statement.
- `G6`: Graduate Midwives Checklist.
- `G7`: Graduate Midwife Batch List.
- `NC1`: Provisional Licence.
- `NC2`: Full Licence.
- `NC6`: Full Licence Nursing Competency.
- `NC7`: Full Licence Midwifery Competency.

### Phase 2 Forms

Build after Phase 1 is stable.

Medical Board:

- `MBRN`: Renewal and registration detail capture.
- `MBAC`: Facility accreditation checklist.
- `MBPF`: Private health facility checklist.
- `MBTC`: Training college facility form.

Nursing Council:

- `NC3`: Renewal of Licence.
- `NC4`: Overseas provisional checklist.
- `NC5`: Overseas full registration.
- `NC8`: Temporary licence.
- `NC9`: Temporary overseas checklist.
- `NC10`: Child nursing competency.
- `NC11`: Double major checklist.

## Local Database Scope

Use Room tables that match the server sync payload.

Minimum tables:

- `mobile_user_session`
- `lookup_cache`
- `draft_record`
- `draft_person`
- `draft_qualification`
- `draft_employment`
- `draft_payload`
- `draft_attachment`
- `sync_outbox`
- `local_audit_event`

### `draft_record`

Required fields:

- `client_record_id`: UUID primary key.
- `office_scope`: `medical` or `nursing`.
- `form_code`: server form code.
- `pathway`: server pathway.
- `profession_track`: server profession track.
- `target_model`: server target model.
- `status`: local sync status.
- `server_application_id`: nullable integer.
- `created_by_username`.
- `created_at`.
- `updated_at`.
- `last_sync_error`.

Recommended local statuses:

- `draft`
- `ready_to_sync`
- `duplicate_warning`
- `syncing_json`
- `json_synced`
- `syncing_attachments`
- `synced_pending_review`
- `needs_correction`
- `server_rejected`
- `conflict`
- `archived`

### `draft_person`

Required fields:

- `client_record_id`
- `first_name`
- `middle_name`
- `last_name`
- `gender`
- `date_of_birth`
- `applicant_type`
- `registration_no`
- `registration_number`
- `practitioner_number`
- `primary_phone`
- `email`
- `province`
- `district`
- `full_address`

### `draft_qualification`

Required fields:

- `client_record_id`
- `qualification_name`
- `institution_name`
- `institution_id`
- `institution_type`
- `program_completed`
- `date_started`
- `date_completed`
- `completion_year`
- `country`
- `certificate_attached`
- `transcript_attached`

### `draft_attachment`

Required fields:

- `attachment_id`
- `client_record_id`
- `document_code`
- `document_label`
- `local_file_uri`
- `mime_type`
- `file_size`
- `sha256`
- `captured_at`
- `sync_status`
- `server_document_id`
- `repository_id`
- `version_id`

## UI Scope

### Login Screen

Fields:

- Username.
- Password.

Actions:

- Login.
- Show server connection error.
- Show invalid credential error.

After successful login:

- Save tokens.
- Call profile API.
- Call mobile bootstrap API.
- Navigate to officer home.

### Officer Home

Show:

- Signed in user.
- Department.
- Office scope.
- Sync status counts.
- Available form packs.

Actions:

- New draft.
- Drafts.
- Ready to sync.
- Sync status.
- Refresh lookups.
- Logout.

Do not show:

- Web dashboard cards.
- Approval queues.
- Financial screens.
- Records Hub.

### Draft List

Tabs:

- Drafts.
- Ready to sync.
- Needs correction.
- Synced pending review.
- Archived.

Each row:

- Applicant name.
- Form code.
- Office scope.
- Local status.
- Last updated.
- Attachment count.

### Form Entry Screens

Use a stepper flow:

1. Person identity.
2. Contact and address.
3. Qualification or training.
4. Employment or workplace.
5. Form-specific fields.
6. Attachments.
7. Declaration and signature.
8. Review.

Rules:

- Autosave after every field update.
- Validate required fields before moving to review.
- Do not require internet during draft entry.
- Use dropdowns for bootstrap lookups.
- Use free-text only where lookup match is not available.
- Mark unmatched institution/facility as "Needs review".

### Duplicate Check Screen

Show:

- Local duplicates.
- Server duplicates.
- Match score.
- Existing registration number.
- Existing model.

Actions:

- Back and correct.
- Continue with duplicate acknowledgement.
- Cancel draft.

### Review and Submit Screen

Show:

- All captured sections.
- Missing required fields.
- Duplicate warning state.
- Attachment status.
- Declaration checkbox.

Actions:

- Mark ready to sync.
- Save draft.
- Edit section.

### Sync Screen

Show:

- Pending JSON sync count.
- Pending attachment count.
- Last successful sync.
- Last error.

Actions:

- Sync now.
- Retry failed.
- View server status.

## Payload Mapping Rules

Always send these top-level fields per record:

- `client_record_id`
- `office_scope`
- `form_code`
- `pathway`
- `profession_track`
- `target_model`
- `person`
- `qualification`
- `employment`
- `payload`
- `attachments`

Use `payload` for all fields that do not map cleanly to person, qualification, or employment.

Examples:

- Checklist answers.
- Declarations.
- Signature text.
- Specialist category.
- Practitioner category.
- Worker type.
- Facility inspection fields.
- Duplicate acknowledgement.
- GPS collection metadata.
- Data entry officer notes.

Do not flatten every field into the top level. The backend expects grouped JSON.

## Required Validation

### All Drafts

Required:

- `client_record_id`
- `office_scope`
- `form_code`
- `target_model`
- First name or full name.
- Last name where applicable.
- Applicant type.
- Declaration accepted before marking ready to sync.

Recommended:

- Gender.
- Date of birth.
- Phone or email.
- Province or full address.

### Medical Board

For `CHW1`:

- First name.
- Last name.
- Registration number or CHW/community ID if available.
- Training level.
- Institution attended.
- Province or address.
- Declaration accepted.

For `MD1`:

- First name.
- Last name.
- Practitioner category.
- Initial qualification.
- Institution attended.
- Country.
- Contact details.
- Declaration accepted.

For `MBSP`:

- Doctor name.
- Specialty.
- Practitioner stream.
- Qualification summary.
- Supporting document placeholder.
- Declaration accepted.

For Allied Health:

- First name.
- Last name.
- Allied health category.
- Initial qualification.
- Institution attended.
- Country.
- Contact details.
- `target_model="alliedhealth"`.
- `profession_track="allied_health"`.

### Nursing Council

For `G1` to `G7`:

- Full name or first and last name.
- Institution.
- Program completed.
- Completion year or completion date.
- Province or address.
- Declaration accepted.

For `NC1`:

- First name.
- Last name.
- Applicant type.
- Institution.
- Program completed.
- Qualification evidence placeholder.
- Declaration accepted.

For `NC2`:

- Registration number if existing.
- Person details.
- Competency evidence placeholder.
- Employer or supervisor details where applicable.
- Declaration accepted.

For `NC6` and `NC7`:

- Linked applicant details.
- Competency domain responses.
- Supervisor name.
- Supervisor assessment.
- Declaration accepted.

## Attachment Rules

Capture supported file types:

- JPG.
- PNG.
- PDF.

Recommended maximums:

- Photo images: compress to under 1 MB where possible.
- Document scans: under 5 MB where possible.
- PDFs: under 10 MB where possible.

For each attachment:

- Generate `attachment_id` UUID.
- Store local file securely.
- Compute SHA-256.
- Store `document_code`.
- Show sync status.

Upload order:

1. Sync JSON record.
2. Save `server_application_id`.
3. Upload attachments one at a time.
4. Save server document IDs.
5. Mark record `synced_pending_review` only when required attachments are uploaded.

## Security Requirements

The Android app must:

- Use HTTPS outside local development.
- Store tokens in encrypted storage.
- Store local drafts and files encrypted.
- Lock after inactivity.
- Avoid logging tokens or personal data.
- Redact sensitive data from crash logs.
- Require re-login when refresh fails.
- Validate office scope locally and rely on server validation too.
- Prevent screenshots on sensitive screens if feasible.
- Keep synced records read-only unless server sends a correction.

The Android app must not:

- Store passwords.
- Share tokens between users.
- Submit forms outside bootstrap scope.
- Upload attachments before JSON sync is accepted.
- Delete server records.
- Call web generic records endpoints for mobile data collection.

## Error Handling

Handle:

- HTTP 400: show validation message and mark draft `needs_correction`.
- HTTP 401: refresh token and retry once; if still failing, require login.
- HTTP 403: show access denied; do not retry automatically.
- HTTP 404: show missing server record; keep draft in conflict state.
- HTTP 500: keep in outbox and retry later.
- Network timeout: keep in outbox and retry later.

Outbox retry:

- Use exponential backoff.
- Do not duplicate JSON sync because `client_record_id` is idempotent.
- Do not duplicate attachment upload if server IDs are already stored.

## Testing Scope

The Android agent must build tests for:

- Login success.
- Login failure.
- Token refresh.
- Bootstrap medical scope.
- Bootstrap nursing scope.
- Medical user cannot see Nursing forms.
- Nursing user cannot see Medical forms.
- Draft autosave.
- Draft survives app restart.
- Local duplicate detection.
- Server duplicate check request/response parsing.
- Sync batch accepted response.
- Idempotent sync response.
- Rejected cross-office sync.
- Attachment upload after JSON sync.
- Sync status refresh.
- Offline outbox retry.

Manual test scenarios:

1. Medical Board registrar logs in and sees only `MD1`, `MD2`, `CHW1`, `MBSP`, `MBRN`, `MBAC`, `MBPF`, `MBTC`.
2. Nursing Council registrar logs in and sees only `G1` to `G7` and `NC1` to `NC11`.
3. Medical Board registrar tries to submit `NC1`; app blocks locally and backend rejects if forced.
4. Nursing Council registrar tries to submit `CHW1`; app blocks locally and backend rejects if forced.
5. CHW draft sync creates pending application.
6. Same CHW `client_record_id` sync again returns idempotent success.
7. Attachment uploads only after `server_application_id` exists.
8. Sync status shows server application status as `pending`.

## Deliverables

The Android agent must deliver:

- Kotlin Android project modules matching the recommended package structure.
- Retrofit API client for auth, profile, bootstrap, duplicate check, sync batch, attachment upload, and sync status.
- Room schema and migrations for local drafts.
- Encrypted token and draft storage.
- Compose UI screens for login, home, draft forms, review, duplicate check, sync, and status.
- Outbox sync worker.
- Attachment capture and upload flow.
- Unit tests.
- Instrumented tests for main flows where practical.
- A short `MOBILE_INTEGRATION_NOTES.md` in the Android project explaining base URL configuration and test accounts used.

## Integration Checklist

Before calling the mobile app aligned with the web platform, confirm:

- Login uses `/accounts/token/`.
- Bootstrap uses `/workforce/api/mobile/bootstrap/`.
- Android home screen is based on `enabled_forms`.
- Drafts include stable `client_record_id`.
- Sync uses `/workforce/api/mobile/sync/batch/`.
- Attachments use `/workforce/api/mobile/attachments/`.
- Status uses `/workforce/api/mobile/sync/status/`.
- Cross-office submission is blocked in UI.
- Cross-office submission is rejected by backend if forced.
- Mobile records appear in Django as pending `Application` rows.
- Attachments appear in the Django document repository linked to the application.
- No mobile screen can approve, reject, verify payment, issue licence, or delete records.

## Known Backend Limitations To Respect

- There is no dedicated `AlliedHealthProfessional` model yet.
- Device registration/revocation endpoints are not implemented yet.
- Bootstrap returns available dynamic form definitions where configured, but some forms still need local Android layouts based on the form code.
- Facility master data may be incomplete; unmatched facilities must be sent in payload for web review.
- Training institution data may include imported legacy names that need review; unmatched names must not become verified institutions automatically.

## Backend Follow-Up Items For Later

These are not blockers for Phase 1, but the Android agent should leave extension points:

- Dedicated device registration endpoint.
- Device revocation and forced logout.
- Delta lookup sync with lookup versioning.
- Backend Allied Health model.
- Field-level correction API.
- Push notification for correction requests.
- QR code receipt capture.
- Supervisor-specific competency sign-off workflow.

