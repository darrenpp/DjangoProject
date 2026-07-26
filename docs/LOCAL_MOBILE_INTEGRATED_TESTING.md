# Local Mobile Integrated Testing Guide

Updated: 22 May 2026

This guide is for controlled local testing between the Django desktop/backend platform and the Android offline-first intake app. It is not a production hosting guide.

## Target Setup

```text
Laptop / PC
├── Django desktop/backend platform
│   └── http://127.0.0.1:  8000/
├── Local database
├── Local media/document uploads
└── Android Studio
    ├── Emulator base URL: http://10.0.2.2:8000/
    └── Physical phone base URL: http://YOUR-PC-IP:8000/
```

Inside an Android emulator, `localhost` means the emulator itself. Use `http://10.0.2.2:8000/` for emulator testing.

## Start The Backend

From the project root:

```powershell
cd C:\Project\regulatoryNCMB\PNG_NC_MB
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py bootstrap_document_repository
.\.venv\Scripts\python.exe manage.py bootstrap_nursing_council_workflows
.\.venv\Scripts\python.exe manage.py bootstrap_mobile_intake
.\.venv\Scripts\python.exe manage.py runserver 0.0.0.0:8000
```

Use `0.0.0.0:8000` for Android testing. Binding only to `127.0.0.1:8000` is fine for the laptop browser, but phones and emulators may not reach it.

## Local Helper Command

Run:

```powershell
.\.venv\Scripts\python.exe manage.py local_mobile_test_setup --check-api
```

The command prints:

- Desktop browser URL.
- Android emulator URL.
- Physical phone URL candidates based on local IPv4 addresses.
- API smoke endpoints.
- Windows Firewall rule for port `8000`.
- `adb reverse` USB fallback command.
- Current enabled mobile form schema count.

## Local Settings Behavior

When `DEBUG=True`, the project enables `LOCAL_MOBILE_TESTING=True` by default. This automatically adds:

- `127.0.0.1`
- `localhost`
- `testserver`
- `10.0.2.2`
- detected local private IPv4 addresses

to `ALLOWED_HOSTS`, and adds local HTTP origins to `CSRF_TRUSTED_ORIGINS`.

For production, set:

```env
DJANGO_DEBUG=False
LOCAL_MOBILE_TESTING=False
USE_HTTPS=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SECURE_SSL_REDIRECT=True
REQUIRE_STAFF_MFA=True
```

## Android Base URLs

Use build-specific base URLs:

```kotlin
// Emulator
const val API_BASE_URL = "http://10.0.2.2:8000/"

// Physical phone on same Wi-Fi
const val API_BASE_URL = "http://YOUR-PC-IP:8000/"

// Production later
const val API_BASE_URL = "https://approved-domain.gov.pg/"
```

Debug builds can allow cleartext HTTP:

```xml
<uses-permission android:name="android.permission.INTERNET" />

<application
    android:usesCleartextTraffic="true">
</application>
```

Production Android builds must use HTTPS only.

## Physical Phone Firewall Rule

If a phone cannot open the local login page, run PowerShell as Administrator:

```powershell
netsh advfirewall firewall add rule name="Django Local Test 8000" dir=in action=allow protocol=TCP localport=8000
```

Then test from the phone browser:

```text
http://YOUR-PC-IP:8000/accounts/login/
```

## USB Fallback

If Wi-Fi or firewall setup is unreliable:

```bash
adb devices
adb reverse tcp:8000 tcp:8000
```

Then the phone app can use:

```text
http://127.0.0.1:8000/
```

## Mobile API Endpoints To Smoke Test

Unauthenticated:

```text
/api/mobile/v1/health/
```

Authenticated mobile account:

```text
/api/mobile/v1/auth/login/
/api/mobile/v1/bootstrap/
/api/mobile/v1/forms/
/api/mobile/v1/lookups/
/api/mobile/v1/duplicates/check/
/api/mobile/v1/submissions/
/api/mobile/v1/submissions/status/
/api/mobile/v1/accounts/register/
/api/mobile/v1/accounts/status/
```

## Integrated Test Sequence

1. Start Django with `runserver 0.0.0.0:8000`.
2. Open the desktop platform in the laptop browser.
3. Log in as System Admin or Registrar.
4. Confirm Nursing Council dashboard loads.
5. Confirm Medical Board dashboard loads.
6. Run `bootstrap_mobile_intake` and confirm enabled mobile forms exist.
7. Start Android emulator.
8. Set Android API base URL to `http://10.0.2.2:8000/`.
9. Log in from Android with a mobile-approved account.
10. Fetch bootstrap, forms, and lookups.
11. Confirm NC1, NC2, NC3, NC6, NC7, graduate, CHW provisional, and CHW full licence forms appear where enabled and scoped.
12. Create one NC3 draft offline.
13. Add one attachment.
14. Sync draft to backend.
15. Confirm the desktop Mobile Intake Review Queue receives the submission.
16. Request correction, reject, or accept from desktop.
17. Refresh Android Sync Inbox.
18. Confirm Android shows the backend status.

## Common Problems

| Problem | Cause | Fix |
| --- | --- | --- |
| Emulator cannot connect | App uses `localhost` | Use `http://10.0.2.2:8000/` |
| Phone cannot connect | Firewall or wrong IP | Use `ipconfig`, same Wi-Fi, allow TCP 8000 |
| Django Bad Request | Host missing | Enable local testing or add IP to `ALLOWED_HOSTS` |
| App blocks HTTP | Android cleartext disabled | Enable cleartext only for debug |
| Forms hidden | Schemas not bootstrapped or role-scoped out | Run `bootstrap_mobile_intake`, verify user role and office scope |
| Sync duplicates | Missing idempotency key | Use `deviceId-localDraftId-version` |
| Attachments fail | File type/size/media config | Check allowed MIME type, size, and `MEDIA_ROOT` |

## Safety Rule

Local hosting is for developer testing, controlled mobile integration testing, UAT preparation, workflow testing, demos, and data-cleansing checks only.

Do not treat local hosting as production. Production still requires NDOH ICT hosting approval, HTTPS/domain, production email, backup restore drill, vulnerability scan, penetration test, UAT sign-off, staff training, and support ownership.
