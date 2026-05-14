import pandas as pd
from django.core.management.base import BaseCommand
from django.db import transaction
from django.contrib.contenttypes.models import ContentType
from apps.workforce.models import (
    Cadre, TrainingInstitution, NursingProfessional,
    Application, Qualification
)
from apps.workforce.services.institution_classification import classify_training_institution


class Command(BaseCommand):
    help = 'Import cleaned nursing data from cleaned_combined_nursing_data.csv'

    def handle(self, *args, **options):
        file_path = 'notebooks/cleaned_combined_nursing_data.csv'

        self.stdout.write(self.style.WARNING(f"📂 Loading file: {file_path}"))
        df = pd.read_csv(file_path)

        self.stdout.write(self.style.SUCCESS(f"✅ Loaded {len(df)} records"))

        # Get ContentType for NursingProfessional
        nurse_ct = ContentType.objects.get_for_model(NursingProfessional)

        created_count = 0
        skipped_count = 0

        with transaction.atomic():
            for index, row in df.iterrows():
                try:
                    reg_no = str(row.get('reg_no', '')).strip()
                    if not reg_no or reg_no.lower() in ['nan', '']:
                        skipped_count += 1
                        continue

                    name = str(row.get('clean_name', '')).strip()
                    if not name:
                        skipped_count += 1
                        continue

                    # Split name
                    name_parts = name.split()
                    first_name = name_parts[0] if name_parts else ""
                    last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

                    # Get or create Cadre
                    qualification_text = str(row.get('QUALIFICATION', '')).strip()
                    cadre, _ = Cadre.objects.get_or_create(
                        name=qualification_text[:100] if qualification_text else "General Nursing",
                        defaults={'category': 'nursing'}
                    )

                    # Get or create Training Institution
                    institution_name = str(row.get('INSTITUTION ATTENDED', '')).strip()
                    institution = None
                    if institution_name:
                        institution_type = classify_training_institution(institution_name)
                        institution, inst_created = TrainingInstitution.objects.get_or_create(
                            name=institution_name[:200],
                            defaults={'type': institution_type},
                        )
                        if not inst_created and institution.type != institution_type:
                            institution.type = institution_type
                            institution.save(update_fields=['type'])

                    # Create or update Nursing Professional
                    professional, created = NursingProfessional.objects.update_or_create(
                        registration_number=reg_no,
                        defaults={
                            'first_name': first_name,
                            'last_name': last_name,
                            'cadre': cadre,
                            'is_active': True,
                        }
                    )

                    if created:
                        created_count += 1

                    # Create Application record
                    Application.objects.get_or_create(
                        content_type=nurse_ct,
                        object_id=professional.id,
                        form_code='NC2' if row.get('source') == 'Full' else 'NC1',
                        defaults={
                            'status': 'approved',
                            'submitted_date': pd.to_datetime(row.get('issued_date'), errors='coerce') or None,
                            'approved_date': pd.to_datetime(row.get('issued_date'), errors='coerce') or None,
                        }
                    )

                    # Optional: Create Qualification record
                    if qualification_text:
                        Qualification.objects.get_or_create(
                            content_type=nurse_ct,
                            object_id=professional.id,
                            qualification_name=qualification_text,
                            defaults={
                                'institution': institution,
                                'completion_year': row.get('YEAR')
                            }
                        )

                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"Error at row {index + 1}: {e}"))
                    skipped_count += 1

        self.stdout.write(self.style.SUCCESS(f"\n🎉 Import completed!"))
        self.stdout.write(self.style.SUCCESS(f"   ✅ New professionals created: {created_count}"))
        self.stdout.write(self.style.WARNING(f"   ⚠️  Skipped records: {skipped_count}"))
        self.stdout.write(self.style.SUCCESS(f"   📊 Total processed: {len(df)}"))
