from django.conf import settings
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.utils.cache import add_never_cache_headers
from django.utils import timezone

from apps.accounts.security import (
    audit_security_event,
    session_has_valid_mfa,
    staff_mfa_required,
)


class StaffMFAMiddleware:
    MFA_ALLOWED_PREFIXES = (
        '/accounts/mfa/',
        '/accounts/logout/',
        '/accounts/password-reset/',
        '/accounts/reset/',
        '/static/',
        '/media/',
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if (
            user
            and user.is_authenticated
            and staff_mfa_required(user)
            and not session_has_valid_mfa(request, user)
            and not request.path.startswith(self.MFA_ALLOWED_PREFIXES)
        ):
            audit_security_event('MFA_REQUIRED', user=user, request=request, details={'target_path': request.path})
            return redirect('staff_mfa_verify')

        return self.get_response(request)


class IdleSessionTimeoutMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.timeout_seconds = getattr(settings, "SESSION_COOKIE_AGE", 900)

    def __call__(self, request):
        user = getattr(request, "user", None)
        last_activity = request.session.get("last_activity")

        if user and user.is_authenticated and last_activity:
            try:
                elapsed = timezone.now().timestamp() - float(last_activity)
            except (TypeError, ValueError):
                elapsed = 0

            if elapsed > self.timeout_seconds:
                logout(request)
                request.session.flush()
                return redirect("login")

        response = self.get_response(request)

        content_type = response.get("Content-Type", "")
        if request.method == "GET" and content_type.startswith("text/html"):
            if request.path.startswith("/accounts/") or (user and user.is_authenticated):
                add_never_cache_headers(response)

        if user and user.is_authenticated:
            request.session["last_activity"] = timezone.now().timestamp()
            request.session.modified = True

        return response
