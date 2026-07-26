from collections import defaultdict
from pathlib import Path
import re

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from apps.dashboard.models import Receipt
from apps.dashboard.report_freshness import mark_report_generated
from apps.workforce.models import (
    CommunityHealthWorker,
    Facility,
    HealthStudent,
    Location,
    MedicalDoctor,
    Midwife,
    MissingDataReview,
    NurseAide,
    NursingProfessional,
    PracticingLicenseRecord,
    Qualification,
    TrainingInstitution,
)
from apps.workforce.services.data_quality import audit_imported_license_rows, audit_professional_profiles


SENTINELS = {
    '',
    '-',
    '--',
    '---',
    'N/A',
    'NA',
    'NONE',
    'NULL',
    'NIL',
    'UNKNOWN',
    'UNKNOW',
    'NOT KNOWN',
    'TBA',
    'TBC',
    '?',
}

PROVINCE_ALIASES = {
    'NCD': 'National Capital District',
    'N.C.D': 'National Capital District',
    'N.C.D.': 'National Capital District',
    'NATIONAL CAPITAL': 'National Capital District',
    'NATIONAL CAPITAL DISTRICT': 'National Capital District',
    'CENTRAL': 'Central Province',
    'EAST NEW BRITAIN': 'East New Britain Province',
    'ENB': 'East New Britain Province',
    'EAST SEPIK': 'East Sepik Province',
    'EASTERN HIGHLANDS': 'Eastern Highlands Province',
    'EHP': 'Eastern Highlands Province',
    'ENGA': 'Enga Province',
    'GULF': 'Gulf Province',
    'HELA': 'Hela Province',
    'JIWAKA': 'Jiwaka Province',
    'MADANG': 'Madang Province',
    'MANUS': 'Manus Province',
    'MILNE BAY': 'Milne Bay Province',
    'MOROBE': 'Morobe Province',
    'NEW IRELAND': 'New Ireland Province',
    'ORO': 'Oro Province',
    'NORTHERN': 'Oro Province',
    'SANDAUN': 'Sandaun Province',
    'WEST SEPIK': 'Sandaun Province',
    'SIMBU': 'Chimbu Province',
    'CHIMBU': 'Chimbu Province',
    'SHP': 'Southern Highlands Province',
    'SOUTHERN HIGHLANDS': 'Southern Highlands Province',
    'WESTERN': 'Western Province',
    'WESTERN HIGHLANDS': 'Western Highlands Province',
    'WHP': 'Western Highlands Province',
    'WEST NEW BRITAIN': 'West New Britain Province',
    'WNB': 'West New Britain Province',
    'AUTONOMOUS REGION OF BOUGAINVILLE': 'Autonomous Region of Bougainville',
    'AROB': 'Autonomous Region of Bougainville',
    'BOUGAINVILLE': 'Autonomous Region of Bougainville',
}

GENDER_ALIASES = {
    'M': 'Male',
    'MALE': 'Male',
    'F': 'Female',
    'FEMALE': 'Female',
}

TEXT_MODELS = (
    NursingProfessional,
    Midwife,
    NurseAide,
    HealthStudent,
    MedicalDoctor,
    CommunityHealthWorker,
    PracticingLicenseRecord,
    Qualification,
    Facility,
    TrainingInstitution,
    Location,
    Receipt,
)


def _collapse_spaces(value):
    return re.sub(r'\s+', ' ', str(value).replace('\xa0', ' ')).strip()


def _clean_string(field, value):
    if value is None:
        return None

    cleaned = _collapse_spaces(value)
    if cleaned.upper() in SENTINELS:
        if getattr(field, 'unique', False) and not getattr(field, 'null', False):
            return cleaned
        return None if getattr(field, 'null', False) else ''

    field_name = field.name.lower()
    if field_name in {'email'}:
        return cleaned.lower()
    if field_name in {'province'}:
        return PROVINCE_ALIASES.get(cleaned.upper(), cleaned)
    if field_name in {'gender'}:
        return GENDER_ALIASES.get(cleaned.upper(), cleaned)
    if field_name in {
        'registration_no',
        'registration_number',
        'practitioner_number',
        'license_number',
        'licence_number',
        'receipt_number',
        'official_receipt_no',
        'reference_number',
        'atp_number',
        'code',
    }:
        return cleaned.upper()
    return cleaned


class Command(BaseCommand):
    help = (
        "Prepare production data safely by normalizing whitespace, sentinel values, provinces, "
        "gender values, emails, and key reference numbers, then running data-readiness audits."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Apply safe normalization changes. Default is dry-run only.',
        )
        parser.add_argument(
            '--skip-audit',
            action='store_true',
            help='Skip missing-data and import-row audit after normalization.',
        )
        parser.add_argument(
            '--write-report',
            action='store_true',
            help='Write a markdown production-readiness report under docs/reports.',
        )

    def _normalize_model(self, model, *, apply_changes=False):
        scanned = 0
        changed_records = 0
        changed_fields = 0
        skipped_unique_conflicts = 0
        field_changes = defaultdict(int)
        text_fields = [
            field
            for field in model._meta.fields
            if field.get_internal_type() in {'CharField', 'TextField', 'EmailField'}
        ]

        for obj in model.objects.all().iterator(chunk_size=1000):
            scanned += 1
            updates = []
            for field in text_fields:
                old_value = getattr(obj, field.name)
                new_value = _clean_string(field, old_value)
                if old_value != new_value:
                    if (
                        getattr(field, 'unique', False)
                        and new_value not in {None, ''}
                        and model.objects.exclude(pk=obj.pk).filter(**{field.name: new_value}).exists()
                    ):
                        skipped_unique_conflicts += 1
                        continue
                    setattr(obj, field.name, new_value)
                    updates.append(field.name)
                    field_changes[field.name] += 1

            if updates:
                changed_records += 1
                changed_fields += len(updates)
                if apply_changes:
                    obj.save(update_fields=updates)

        return {
            'model': model._meta.label,
            'scanned': scanned,
            'changed_records': changed_records,
            'changed_fields': changed_fields,
            'skipped_unique_conflicts': skipped_unique_conflicts,
            'field_changes': dict(sorted(field_changes.items())),
        }

    def _duplicate_summary(self):
        summary = {}
        for model in (NursingProfessional, Midwife, NurseAide, HealthStudent, MedicalDoctor, CommunityHealthWorker):
            model_summary = {}
            for field_name in ('registration_no', 'registration_number'):
                if not any(field.name == field_name for field in model._meta.fields):
                    continue
                duplicate_groups = (
                    model.objects
                    .exclude(**{f'{field_name}__isnull': True})
                    .exclude(**{field_name: ''})
                    .values(field_name)
                    .annotate(total=Count('id'))
                    .filter(total__gt=1)
                    .count()
                )
                model_summary[field_name] = duplicate_groups
            summary[model._meta.label] = model_summary
        return summary

    def _date_issue_summary(self):
        today = timezone.localdate()
        return {
            'future_import_issued_dates': PracticingLicenseRecord.objects.filter(issued_date__gt=today).count(),
            'future_import_payment_dates': PracticingLicenseRecord.objects.filter(payment_date__gt=today).count(),
            'old_import_issued_dates_before_2000': PracticingLicenseRecord.objects.filter(issued_date__lt='2000-01-01').count(),
            'old_import_payment_dates_before_2000': PracticingLicenseRecord.objects.filter(payment_date__lt='2000-01-01').count(),
            'future_receipt_dates': Receipt.objects.filter(receipt_date__gt=timezone.now()).count(),
        }

    def _write_report(self, results):
        report_dir = Path('docs') / 'reports'
        report_dir.mkdir(parents=True, exist_ok=True)
        timestamp = timezone.localtime().strftime('%Y%m%d_%H%M%S')
        path = report_dir / f'production_data_readiness_{timestamp}.md'
        lines = [
            '# Production Data Readiness Report',
            '',
            f'Generated: {timezone.localtime():%Y-%m-%d %H:%M:%S %Z}',
            f"Mode: {'APPLIED' if results['applied'] else 'DRY RUN'}",
            '',
            '## Safe Normalization',
            '',
            '| Model | Scanned | Records with changes | Field changes |',
            '|---|---:|---:|---:|',
        ]
        for row in results['normalization']:
            lines.append(
                f"| {row['model']} | {row['scanned']} | {row['changed_records']} | {row['changed_fields']} |"
            )
        lines.extend([
            '',
            '## Skipped Unique-Identifier Conflicts',
            '',
            '| Model | Skipped field changes |',
            '|---|---:|',
        ])
        for row in results['normalization']:
            lines.append(f"| {row['model']} | {row['skipped_unique_conflicts']} |")
        lines.extend([
            '',
            '## Date Issue Summary',
            '',
            '| Issue | Count |',
            '|---|---:|',
        ])
        for key, value in results['date_issues'].items():
            lines.append(f"| {key.replace('_', ' ').title()} | {value} |")
        lines.extend([
            '',
            '## Duplicate Summary',
            '',
            '| Model | Field | Duplicate groups |',
            '|---|---|---:|',
        ])
        for model_label, fields in results['duplicates'].items():
            for field_name, value in fields.items():
                lines.append(f'| {model_label} | {field_name} | {value} |')
        if results.get('profile_audit'):
            lines.extend([
                '',
                '## Missing Data Audit',
                '',
                f"- Profiles reviewed: {results['profile_audit']['reviewed']}",
                f"- Missing-data reviews created: {results['profile_audit']['created']}",
                f"- Missing-data reviews updated: {results['profile_audit']['updated']}",
                f"- Missing-data reviews resolved: {results['profile_audit']['resolved']}",
                f"- Open missing-data reviews: {results['profile_audit']['open_reviews']}",
            ])
        if results.get('import_audit'):
            lines.extend([
                '',
                '## Imported Row Audit',
                '',
                f"- Import rows reviewed: {results['import_audit']['reviewed']}",
                f"- Import-row reviews created: {results['import_audit']['created']}",
                f"- Import-row reviews updated: {results['import_audit']['updated']}",
            ])
        lines.extend([
            '',
            '## Production Rule',
            '',
            'Imported rows are not automatically trusted. They are staged, validated, cleansed, reviewed, approved, then promoted into live registry records.',
        ])
        path.write_text('\n'.join(lines), encoding='utf-8')
        return path

    def handle(self, *args, **options):
        apply_changes = options['apply']
        results = {
            'applied': apply_changes,
            'normalization': [],
            'date_issues': {},
            'duplicates': {},
            'profile_audit': None,
            'import_audit': None,
            'open_missing_reviews': MissingDataReview.objects.exclude(status='resolved').count(),
        }

        self.stdout.write('Production data preparation started.')
        self.stdout.write('Mode: APPLY changes' if apply_changes else 'Mode: DRY RUN only')

        with transaction.atomic():
            for model in TEXT_MODELS:
                row = self._normalize_model(model, apply_changes=apply_changes)
                results['normalization'].append(row)
                self.stdout.write(
                    f"{row['model']}: {row['scanned']} scanned, "
                    f"{row['changed_records']} records would change, {row['changed_fields']} field changes, "
                    f"{row['skipped_unique_conflicts']} unique conflicts skipped."
                )
            if not apply_changes:
                transaction.set_rollback(True)

        if not options['skip_audit']:
            results['profile_audit'] = audit_professional_profiles(send_notifications=False)
            results['import_audit'] = audit_imported_license_rows()

        results['date_issues'] = self._date_issue_summary()
        results['duplicates'] = self._duplicate_summary()

        for key, value in results['date_issues'].items():
            if value:
                self.stdout.write(self.style.WARNING(f"{key}: {value}"))

        duplicate_total = sum(sum(fields.values()) for fields in results['duplicates'].values())
        if duplicate_total:
            self.stdout.write(self.style.WARNING(f"Duplicate identifier groups still requiring review: {duplicate_total}"))

        if results['profile_audit']:
            self.stdout.write(self.style.SUCCESS(
                "Profile audit: "
                f"{results['profile_audit']['reviewed']} reviewed, "
                f"{results['profile_audit']['open_reviews']} open reviews."
            ))
        if results['import_audit']:
            self.stdout.write(self.style.SUCCESS(
                "Import-row audit: "
                f"{results['import_audit']['reviewed']} reviewed, "
                f"{results['import_audit']['created']} created, "
                f"{results['import_audit']['updated']} updated."
            ))

        if options['write_report']:
            path = self._write_report(results)
            mark_report_generated('production_readiness', scope='all', output_label=str(path))
            self.stdout.write(self.style.SUCCESS(f"Production readiness report written: {path}"))

        self.stdout.write(self.style.SUCCESS(
            'Production data preparation completed. '
            + ('Safe normalizations were applied.' if apply_changes else 'No data was changed because this was a dry run.')
        ))
