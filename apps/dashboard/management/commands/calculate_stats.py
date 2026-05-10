from django.core.management.base import BaseCommand
from apps.dashboard.models import Report
from apps.workforce.models import NursingProfessional, HealthStudent, Application
from datetime import date


class Command(BaseCommand):
    help = 'Calculate and save workforce flow statistics'

    def handle(self, *args, **options):
        today = date.today()

        stats = {
            'nearing_retirement': NursingProfessional.objects.filter(
                license_expiry__lte=today.replace(year=today.year + 5)
            ).count(),
            'incoming_students': HealthStudent.objects.filter(is_graduate=False).count(),
            'new_graduates': Application.objects.filter(form_code__in=['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G7'], status='approved').count(),
        }

        Report.objects.create(
            title=f"Workforce Statistics - {today}",
            report_type='workforce_summary',
            file=None  # You can generate PDF here later
        )

        self.stdout.write(self.style.SUCCESS('Statistics calculated successfully!'))
