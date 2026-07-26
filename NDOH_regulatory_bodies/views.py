from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

def home_view(request):
    """
    Home page view for portal selection
    """
    return render(request, 'home.html')


def csrf_failure(request, reason=""):
    message = "Your page security token expired or the page became stale. Please reload the page and try again."
    wants_json = (
        request.path.startswith("/notifications/helpdesk/api/")
        or request.path.startswith("/dashboard/execute-command/")
        or request.content_type == "application/json"
        or "application/json" in request.headers.get("Accept", "")
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
    )
    if wants_json:
        return JsonResponse({"error": message, "reason": reason}, status=403)

    messages.error(request, message)
    referrer = request.META.get("HTTP_REFERER", "")
    if referrer and url_has_allowed_host_and_scheme(
        referrer,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(referrer)
    if getattr(request.user, "is_authenticated", False):
        return redirect("user_profile")
    return redirect("login")
