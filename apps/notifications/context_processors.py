from .services import build_staff_notification_summary, build_user_notification_summary


def staff_notifications(request):
    user = getattr(request, "user", None)
    summary = build_staff_notification_summary(user)
    user_summary = build_user_notification_summary(user)
    return {
        "staff_notification_summary": summary,
        "staff_notification_items": summary.get("items", []),
        "staff_notification_count": summary.get("count", 0),
        "notification_summary": user_summary,
        "notification_items": user_summary.get("items", []),
        "notification_count": user_summary.get("count", 0),
        "notification_unread_items": user_summary.get("unread_items", []),
        "notification_history_items": user_summary.get("history_items", []),
        "notification_current_items": user_summary.get("current_items", []),
        "notification_unread_count": user_summary.get("unread_total_count", user_summary.get("unread_notification_count", 0)),
    }
