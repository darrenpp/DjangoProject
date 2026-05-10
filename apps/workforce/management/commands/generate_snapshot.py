from django.core.management.base import BaseCommand
from datetime import date
from apps.workforce.models import (
    WorkforceSnapshot, NursingProfessional, MedicalDoctor,
    Midwife, CommunityHealthWorker, NurseAide, HealthStudent, Application
)


class Command(BaseCommand):
    help = 'Generate yearly workforce snapshot'

    def handle(self, *args, **options):
        current_year = date.today().year
        today = date.today()

        nurses = NursingProfessional.objects.filter(is_active=True)
        doctors = MedicalDoctor.objects.filter(is_active=True)
        midwives = Midwife.objects.filter(is_active=True)
        chw = CommunityHealthWorker.objects.filter(is_active=True)
        nurse_aides = NurseAide.objects.filter(is_active=True)

        nearing_retirement = 0
        for queryset in [nurses, doctors, midwives, chw, nurse_aides]:
            for worker in queryset.exclude(date_of_birth__isnull=True).only('date_of_birth'):
                age = today.year - worker.date_of_birth.year - (
                    (today.month, today.day) < (worker.date_of_birth.month, worker.date_of_birth.day)
                )
                if age >= 55:
                    nearing_retirement += 1

        snapshot, created = WorkforceSnapshot.objects.update_or_create(
            year=current_year,
            defaults={
                'total_active_workers': (
                        nurses.count() +
                        doctors.count() +
                        midwives.count() +
                        chw.count() +
                        nurse_aides.count()
                ),
                'total_nurses': nurses.count(),
                'total_doctors': doctors.count(),
                'total_midwives': midwives.count(),
                'total_chw': chw.count(),
                'new_registrations': Application.objects.filter(
                    submitted_date__year=current_year, status='approved'
                ).count(),
                'new_graduates_joined': HealthStudent.objects.filter(
                    is_graduate=True, expected_graduation_date__year=current_year
                ).count(),
                'nearing_retirement': nearing_retirement,
            }
        )

        action = 'created' if created else 'updated'
        self.stdout.write(self.style.SUCCESS(f'Successfully {action} snapshot for year {current_year}'))
        self.stdout.write(f'Saved to WorkforceSnapshot id={snapshot.id}')
        self.stdout.write(f'Total active workers: {snapshot.total_active_workers}')
