"""Keep the assistant's knowledge index aligned with approved platform content."""

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.dashboard.assistant_rag import mark_knowledge_index_stale
from apps.dashboard.models import FAQCategory, FAQEntry, RegistrationGuideline
from apps.workforce.models import (
    ApplicationPathway,
    DynamicFormDefinition,
    FeeSchedule,
    PolicyDocument,
    RegulatoryBody,
)


KNOWLEDGE_SOURCE_MODELS = (
    FAQCategory,
    FAQEntry,
    RegistrationGuideline,
    RegulatoryBody,
    ApplicationPathway,
    DynamicFormDefinition,
    FeeSchedule,
    PolicyDocument,
)


def _mark_after_commit(sender, instance, **_kwargs):
    """Never rebuild embeddings during a failed or uncommitted database write."""
    label = sender._meta.label
    primary_key = getattr(instance, "pk", "")
    transaction.on_commit(lambda: mark_knowledge_index_stale(f"{label}:{primary_key}"))


for _knowledge_model in KNOWLEDGE_SOURCE_MODELS:
    post_save.connect(
        _mark_after_commit,
        sender=_knowledge_model,
        dispatch_uid=f"assistant_knowledge_stale_save:{_knowledge_model._meta.label_lower}",
    )
    post_delete.connect(
        _mark_after_commit,
        sender=_knowledge_model,
        dispatch_uid=f"assistant_knowledge_stale_delete:{_knowledge_model._meta.label_lower}",
    )
