from .services import build_staff_notification_summary


def staff_notifications(request):
    user = getattr(request, "user", None)
    summary = build_staff_notification_summary(user)
    return {
        "staff_notification_summary": summary,
        "staff_notification_items": summary.get("items", []),
        "staff_notification_count": summary.get("count", 0),
    }
