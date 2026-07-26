from django.core.management.base import BaseCommand
import csv
from apps.workforce.models import Cadre, Location, TrainingInstitution


class Command(BaseCommand):
    help = 'Import initial data (Provinces, Cadres, Institutions)'

    def handle(self, *args, **options):
        # Import Cadres
        cadres = [
            ('Registered Nurse', 'nursing'),
            ('Enrolled Nurse', 'nursing'),
            ('Midwife', 'midwifery'),
            ('Community Health Worker', 'chw'),
            ('Medical Doctor', 'medical'),
            ('Allied Health Professional', 'medical'),
        ]
        for name, category in cadres:
            Cadre.objects.update_or_create(name=name, defaults={'category': category})

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
