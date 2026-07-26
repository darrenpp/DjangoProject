from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from apps.dashboard.models import ReportFreshnessState


REPORT_LABELS = dict(ReportFreshnessState.REPORT_KEY_CHOICES)
SCOPE_LABELS = dict(ReportFreshnessState.SCOPE_CHOICES)

DATA_DEPENDENT_REPORT_KEYS = (
    'monthly_analytics',
    'yearly_analytics',
    'financial_forecast',
    'registered_nurses',
    'minister_brief',
    'registrar_secretary_brief',
    'production_readiness',
)

NURSING_REPORT_KEYS = {
    'monthly_analytics',
    'yearly_analytics',
    'financial_forecast',
    'registered_nurses',
    'minister_brief',
    'registrar_secretary_brief',
    'production_readiness',
}
MEDICAL_REPORT_KEYS = {
    'monthly_analytics',
    'yearly_analytics',
    'financial_forecast',
    'minister_brief',
    'registrar_secretary_brief',
    'production_readiness',
}


def normalize_scope(scope):
    return scope if scope in {'nursing', 'medical'} else 'all'


def scopes_affected_by_change(scope):
    scope = normalize_scope(scope)
    if scope == 'nursing':
        return ('nursing', 'all')
    if scope == 'medical':
        return ('medical', 'all')
    return ('all', 'nursing', 'medical')


def report_keys_for_scope(scope):
    scope = normalize_scope(scope)
    if scope == 'nursing':
        return DATA_DEPENDENT_REPORT_KEYS
    if scope == 'medical':
        return tuple(key for key in DATA_DEPENDENT_REPORT_KEYS if key != 'registered_nurses')
    return DATA_DEPENDENT_REPORT_KEYS


def scope_for_import_batch(batch):
    source = f"{getattr(batch, 'source_kind', '')} {getattr(batch, 'source_file_name', '')}".lower()
    if any(token in source for token in ('medical', 'doctor', 'chw', 'community health worker')):
        return 'medical'
    if any(token in source for token in ('nursing', 'n-data', 'ndata', 'atp', 'licence', 'license', 'provisional', 'midwife', 'nurse')):
        return 'nursing'
    return 'all'


def invalidate_dashboard_report_caches():
    # The dashboard uses many dynamic cache keys. Clearing the local cache keeps
    # readiness, analytics, and export summaries aligned after official data changes.
    cache.clear()


def mark_report_data_changed(scope=None, reason='', source_label=''):
    scope = normalize_scope(scope)
    now = timezone.now()
    updated_states = []
    invalidate_dashboard_report_caches()

    with transaction.atomic():
        for affected_scope in scopes_affected_by_change(scope):
            for report_key in report_keys_for_scope(affected_scope):
                state, _created = ReportFreshnessState.objects.select_for_update().get_or_create(
                    report_key=report_key,
                    scope=affected_scope,
                )
                state.data_version += 1
                state.last_data_changed_at = now
                state.last_data_change_reason = reason[:255]
                state.last_data_change_source = source_label[:255]
                state.save(update_fields=[
                    'data_version',
                    'last_data_changed_at',
                    'last_data_change_reason',
                    'last_data_change_source',
                    'updated_at',
                ])
                updated_states.append(state)
    return updated_states


def mark_import_batch_reports_stale(batch):
    source_label = getattr(batch, 'source_file_name', '') or getattr(batch, 'source_kind', '') or f"Import batch {batch.pk}"
    return mark_report_data_changed(
        scope=scope_for_import_batch(batch),
        reason='Import batch completed',
        source_label=source_label,
    )


def mark_report_generated(report_key, scope=None, user=None, output_label=''):
    scope = normalize_scope(scope)
    now = timezone.now()
    state, _created = ReportFreshnessState.objects.get_or_create(
        report_key=report_key,
        scope=scope,
    )
    state.last_generated_at = now
    state.last_generated_by = user if getattr(user, 'is_authenticated', False) else None
    state.last_generated_output = output_label[:255]
    state.save(update_fields=[
        'last_generated_at',
        'last_generated_by',
        'last_generated_output',
        'updated_at',
    ])
    return state


def report_freshness_rows(scope=None):
    scope = normalize_scope(scope)
    visible_scopes = ('all', scope) if scope in {'nursing', 'medical'} else ('all', 'nursing', 'medical')
    rows = []
    for visible_scope in visible_scopes:
        for report_key in report_keys_for_scope(visible_scope):
            state, _created = ReportFreshnessState.objects.get_or_create(
                report_key=report_key,
                scope=visible_scope,
            )
            rows.append({
                'report_key': report_key,
                'label': REPORT_LABELS.get(report_key, report_key.replace('_', ' ').title()),
                'scope': visible_scope,
                'scope_label': SCOPE_LABELS.get(visible_scope, visible_scope.title()),
                'data_version': state.data_version,
                'last_data_changed_at': state.last_data_changed_at,
                'last_data_change_reason': state.last_data_change_reason,
                'last_data_change_source': state.last_data_change_source,
                'last_generated_at': state.last_generated_at,
                'last_generated_output': state.last_generated_output,
                'is_stale': state.is_stale,
            })
    return rows
