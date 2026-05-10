from django.core.management.base import BaseCommand
import csv
from apps.workforce.models import Cadre, Location, TrainingInstitution


class Command(BaseCommand):
    help = 'Import initial data (Provinces, Cadres, Institutions)'

    def handle(self, *args, **options):
        # Import Cadres
        cadres = ['Registered Nurse', 'Enrolled Nurse', 'Midwife', 'Community Health Worker',
                  'Medical Doctor', 'Allied Health Professional']
        for name in cadres:
            Cadre.objects.get_or_create(name=name)

        # Import Provinces (sample)
        provinces = [
            ('National Capital District', 'Port Moresby'),
            ('Central', 'Kwikila'),
            ('Morobe', 'Lae'),
            ('Western Highlands', 'Mt Hagen'),
            ('East New Britain', 'Kokopo'),
            # Add all 22 from your Excel
        ]
        for prov, dist in provinces:
            Location.objects.get_or_create(province=prov, district=dist)

        self.stdout.write(self.style.SUCCESS('Initial data imported successfully!'))
