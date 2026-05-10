from celery import shared_task
from django.core.mail import send_mail
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
        subject = f"Application Update: {app.form_code}"
        message = f"Your application ({app.form_code}) status is now: {app.status.upper()}"
        send_mail(subject, message, 'no-reply@ndoh.gov.pg', [app.professional.email])
    except:
        pass
