from django.core.cache import cache
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.dashboard.report_freshness import mark_import_batch_reports_stale
from apps.workforce.models import DataImportBatch


@receiver(post_save, sender=DataImportBatch)
def mark_reports_stale_after_completed_import(sender, instance, **kwargs):
    if instance.status != 'completed':
        return

    completed_key = instance.completed_at.isoformat() if instance.completed_at else 'completed'
    cache_key = f'report-freshness:import-batch-marked:{instance.pk}:{completed_key}'
    if cache.get(cache_key):
        return

    def mark_once():
        mark_import_batch_reports_stale(instance)
        cache.set(cache_key, True, 60 * 60 * 24 * 30)

    transaction.on_commit(mark_once)
