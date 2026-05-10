import pandas as pd
import re
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

# Import your actual models (adjust if your models are in different apps)
from apps.workforce.models import (
    NursingProfessional,
    Application,
    Qualification,
    PostingHistory,
    Cadre
)


# If Qualification is in another app, use this instead:
# from apps.competency.models import Qualification


class Command(BaseCommand):
    help = 'Import ALL Nursing Council records (Provisional + Full) into the database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            help='Path to Excel file',
            default='notebooks/DATA_school_full_license2024_2025.xlsx'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be imported without actually importing',
        )

    def handle(self, *args, **options):
        file_path = options['file']
        dry_run = options['dry_run']

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No data will be saved'))

        self.stdout.write(self.style.SUCCESS(f"🚀 Starting full import of Nursing Council data from {file_path}..."))

        try:
            # Load the Excel file starting from row 4 (skip headers, data starts at row 4)
            df = pd.read_excel(file_path, header=None, skiprows=4)  # Skip first 4 rows

            # Set proper column names based on the data structure
            column_names = [
                'row_num', 'NAME', 'REGISTRATION', 'PRO', 'REG NO',
                'ISSUED DATE', 'INSTITUTION ATTENDED', 'YEAR', 'QUALIFICATION',
                'col9', 'col10', 'col11', 'col12'
            ]
            df.columns = column_names

            # Filter out rows that don't have valid data
            df = df.dropna(subset=['NAME']).copy()
            df = df[df['NAME'].astype(str).str.len() > 2].copy()  # Remove very short names
            df = df[df['NAME'].astype(str).str.lower() != 'name'].copy()  # Remove header rows

            self.stdout.write(f"Loaded {len(df):,} total records after cleaning")

            # Split into provisional and full based on REGISTRATION column
            prov_df = df[df['REGISTRATION'].astype(str).str.contains('Provisional', case=False, na=False)].copy()
            full_df = df[~df['REGISTRATION'].astype(str).str.contains('Provisional', case=False, na=False)].copy()

            self.stdout.write(f"Provisional records: {len(prov_df):,}")
            self.stdout.write(f"Full records: {len(full_df):,}")

            if not dry_run:
                with transaction.atomic():
                    self.import_sheet(prov_df, is_provisional=True)
                    self.import_sheet(full_df, is_provisional=False)
            else:
                # Dry run - just count
                prov_count = self.count_importable(prov_df)
                full_count = self.count_importable(full_df)
                self.stdout.write(f"Dry run: Would import {prov_count:,} provisional + {full_count:,} full = {prov_count + full_count:,} total records")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error loading file: {e}'))
            import traceback
            traceback.print_exc()
            return

        self.stdout.write(self.style.SUCCESS("🎉 Import completed successfully!"))

    def clean_name(self, name):
        if pd.isna(name) or str(name).strip() == "":
            return "", ""
        name = re.sub(r'\s+', ' ', str(name).strip()).title()
        parts = name.split()
        return parts[0], " ".join(parts[1:]) if len(parts) > 1 else ""

    def import_sheet(self, df, is_provisional=True):
        sheet_type = "Provisional" if is_provisional else "Full"
        count = 0

        for idx, row in df.iterrows():
            try:
                first_name, last_name = self.clean_name(row.get('NAME', ''))
                reg_no = str(row.get('REG NO', '')).strip()

                if not reg_no or not first_name:
                    continue

                # Generate a unique registration number if not provided
                registration_no = f"PNG-{reg_no}"
                
                # Create or get Professional
                professional, created = NursingProfessional.objects.get_or_create(
                    registration_no=reg_no or registration_no,
                    defaults={
                        'first_name': first_name,
                        'last_name': last_name,
                        'registration_no': registration_no,
                        'gender': 'Female',  # Default, can be updated later
                    }
                )

                count += 1
                if count % 500 == 0:
                    self.stdout.write(f"Processed {count:,} {sheet_type} records...")

            except Exception as e:
                self.stdout.write(self.style.WARNING(f"Skipped row {idx + 5} ({reg_no}): {e}"))

        self.stdout.write(self.style.SUCCESS(f"✅ Imported {count:,} records from {sheet_type} sheet"))

    def count_importable(self, df):
        count = 0
        for idx, row in df.iterrows():
            try:
                reg_no = str(row.get('REG NO', '')).strip()
                first_name = row.get('NAME', '').strip()

                if reg_no and first_name:
                    count += 1
            except:
                continue
        return count
