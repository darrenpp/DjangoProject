from celery import shared_task
from apps.workforce.models import Application
from apps.workforce.services.data_quality import notify_expiring_licenses


@shared_task
def check_provisional_licence_expiry():
    """Run daily to notify professionals whose licence is nearing expiry."""
    return notify_expiring_licenses(days=30)


@shared_task
def send_application_notification(application_id):
    try:
        app = Application.objects.get(id=application_id)
    except Application.DoesNotExist:
        return False

    from .views import send_application_status_email

    return send_application_status_email(app)
