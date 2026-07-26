from uuid import uuid4

from django.core.cache import cache
from django.db.models import Q
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from apps.dashboard.models import (
    AssistantConversation,
    AssistantMemory,
    AssistantMessage,
    FAQEntry,
    RegistrationGuideline,
)
from apps.dashboard.assistant_rag import retrieve_vector_sources
from apps.workforce.models import ApplicationPathway, DynamicFormDefinition, FeeSchedule


ASSISTANT_MEMORY_LIMIT = 5
ASSISTANT_SOURCE_LIMIT = 6


def normalize_assistant_session_id(value):
    value = "".join(ch for ch in str(value or "") if ch.isalnum() or ch in {"-", "_"}).strip()
    if len(value) >= 12:
        return value[:64]
    return uuid4().hex


def get_or_create_assistant_conversation(
    *,
    session_id="",
    assistant_kind,
    user=None,
    browser_session_key="",
    scope="public",
    role="",
):
    session_id = normalize_assistant_session_id(session_id)
    defaults = {
        "assistant_kind": assistant_kind,
        "user": user if getattr(user, "is_authenticated", False) else None,
        "browser_session_key": browser_session_key or "",
        "scope": scope or "public",
        "role": role or "",
    }
    conversation, created = AssistantConversation.objects.get_or_create(
        session_id=session_id,
        defaults=defaults,
    )
    update_fields = []
    for field, value in defaults.items():
        if field == "user" and value is None:
            continue
        if getattr(conversation, field) != value:
            setattr(conversation, field, value)
            update_fields.append(field)
    if update_fields:
        conversation.save(update_fields=update_fields + ["updated_at"])
    return conversation, created


def recent_assistant_history(conversation, limit=ASSISTANT_MEMORY_LIMIT):
    if not conversation:
        return []
    messages = conversation.messages.order_by("-created_at")[: limit * 2]
    return [
        {
            "role": message.role,
            "content": message.content[:600],
            "created_at": message.created_at.isoformat(),
        }
        for message in reversed(list(messages))
    ]


def assistant_memory_rows(*, assistant_kind, user=None, browser_session_key="", scope="public", limit=ASSISTANT_MEMORY_LIMIT):
    queryset = AssistantMemory.objects.filter(
        assistant_kind=assistant_kind,
        scope=scope or "public",
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
    if getattr(user, "is_authenticated", False):
        queryset = queryset.filter(user=user)
    else:
        queryset = queryset.filter(user__isnull=True, browser_session_key=browser_session_key or "")
    return [
        {
            "kind": row.memory_kind,
            "key": row.memory_key,
            "text": row.memory_text[:500],
            "updated_at": row.updated_at.isoformat(),
        }
        for row in queryset.order_by("-updated_at")[:limit]
    ]


def _summarize_focus(question, response):
    title = response.get("title") or "Assistant question"
    answer = response.get("answer") or ""
    return f"Last topic: {title}. User asked: {question[:240]}. Assistant answered: {answer[:320]}"


def record_assistant_turn(
    *,
    conversation,
    question,
    response,
    assistant_kind,
    user=None,
    browser_session_key="",
    scope="public",
):
    if not conversation:
        return None
    sources = response.get("sources") or []
    AssistantMessage.objects.create(
        conversation=conversation,
        role="user",
        content=question or "",
    )
    assistant_message = AssistantMessage.objects.create(
        conversation=conversation,
        role="assistant",
        content=response.get("answer") or "",
        payload=response,
        sources=sources,
    )
    conversation.last_question = question or ""
    conversation.title = response.get("title") or conversation.title
    conversation.last_sources = sources
    conversation.summary = _summarize_focus(question or "", response)
    conversation.save(update_fields=["last_question", "title", "last_sources", "summary", "updated_at"])

    owner = user if getattr(user, "is_authenticated", False) else None
    AssistantMemory.objects.update_or_create(
        assistant_kind=assistant_kind,
        user=owner,
        browser_session_key="" if owner else browser_session_key or "",
        scope=scope or "public",
        memory_kind="recent_focus",
        memory_key="last_topic",
        defaults={
            "memory_text": conversation.summary,
            "source_conversation": conversation,
            "expires_at": None,
        },
    )
    return assistant_message


def serialize_sources(sources):
    serialized = []
    seen = set()
    for source in sources or []:
        label = str(source.get("label") or "").strip()
        detail = str(source.get("detail") or "").strip()
        url = str(source.get("url") or "").strip()
        if not label:
            continue
        key = (label, url)
        if key in seen:
            continue
        seen.add(key)
        serialized.append({"label": label, "detail": detail, "url": url})
    return serialized[:ASSISTANT_SOURCE_LIMIT]


def _reverse_or_blank(url_name):
    if not url_name:
        return ""
    try:
        return reverse(url_name)
    except NoReverseMatch:
        return ""


def retrieve_assistant_sources(*, question, scope="public", public=False):
    cache_key = f"assistant-retrieval:{scope}:{public}:{hash(question or '')}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    text = " ".join(str(question or "").lower().split())
    words = [word for word in text.split() if len(word) >= 3][:8]
    query = Q()
    for word in words:
        query |= Q(question__icontains=word) | Q(answer__icontains=word) | Q(keywords__icontains=word)

    sources = []
    faq_scope = ["shared"]
    if scope in {"nursing", "medical"}:
        faq_scope.append(scope)
    elif scope == "all":
        faq_scope += ["nursing", "medical"]
    faq_audience = ["public", "practitioner"] if public else ["staff", "practitioner", "public"]
    if query:
        for faq in (
            FAQEntry.objects
            .select_related("category")
            .filter(query, is_published=True, category__is_active=True, category__audience__in=faq_audience, category__office_scope__in=faq_scope)
            .order_by("category__display_order", "display_order")[:3]
        ):
            sources.append({
                "label": f"FAQ: {faq.question}",
                "detail": faq.answer[:180],
                "url": _reverse_or_blank("public_faqs"),
            })

    guideline_query = Q()
    for word in words:
        guideline_query |= Q(title__icontains=word) | Q(summary__icontains=word) | Q(code__icontains=word)
    if guideline_query:
        audiences = ["general"]
        if scope == "nursing":
            audiences += ["nurse", "nurse_aide", "graduand"]
        elif scope == "medical":
            audiences += ["doctor", "chw"]
        for guide in RegistrationGuideline.objects.filter(guideline_query, is_active=True, audience__in=audiences).order_by("display_order")[:2]:
            sources.append({
                "label": f"Guideline: {guide.code} {guide.title}",
                "detail": guide.summary[:180],
                "url": _reverse_or_blank(guide.action_url_name),
            })

    if scope in {"nursing", "all"} and any(token in text for token in ("form", "licence", "license", "renew", "provisional", "temporary", "overseas", "atp", "cadre", "nc1", "nc2", "nc3")):
        for form in DynamicFormDefinition.objects.filter(
            regulatory_body__code="PNG_NURSING_COUNCIL",
            active=True,
        ).filter(Q(form_code__icontains=text[:10]) | Q(form_name__icontains=" ".join(words[:3]))).order_by("form_code")[:3]:
            sources.append({
                "label": f"Nursing form {form.form_code}: {form.form_name}",
                "detail": "Dynamic Nursing Council form definition.",
                "url": _reverse_or_blank("nursing_forms_portal"),
            })
        for pathway in ApplicationPathway.objects.filter(
            regulatory_body__code="PNG_NURSING_COUNCIL",
            active=True,
            public_visible=True,
        ).filter(Q(pathway_name__icontains=" ".join(words[:3])) | Q(primary_form_code__icontains=text[:6])).order_by("sort_order")[:2]:
            sources.append({
                "label": f"Pathway: {pathway.pathway_name}",
                "detail": f"Primary form {pathway.primary_form_code}; checklist {pathway.checklist_code}.",
                "url": _reverse_or_blank("nursing_forms_portal"),
            })

    if scope in {"medical", "all"} and any(token in text for token in ("form", "licence", "license", "renew", "doctor", "specialist", "chw", "community health worker", "medical board", "facility", "md1", "md2", "mbsp")):
        medical_body_filter = Q(regulatory_body__code__icontains="MEDICAL") | Q(regulatory_body__name__icontains="Medical Board")
        for form in DynamicFormDefinition.objects.filter(
            medical_body_filter,
            active=True,
        ).filter(Q(form_code__icontains=text[:10]) | Q(form_name__icontains=" ".join(words[:3]))).order_by("form_code")[:3]:
            sources.append({
                "label": f"Medical Board form {form.form_code}: {form.form_name}",
                "detail": "Dynamic Medical Board form definition.",
                "url": _reverse_or_blank("medical_board_form_register"),
            })
        for pathway in ApplicationPathway.objects.filter(
            medical_body_filter,
            active=True,
            public_visible=True,
        ).filter(Q(pathway_name__icontains=" ".join(words[:3])) | Q(primary_form_code__icontains=text[:6])).order_by("sort_order")[:2]:
            sources.append({
                "label": f"Medical Board pathway: {pathway.pathway_name}",
                "detail": f"Primary form {pathway.primary_form_code}; checklist {pathway.checklist_code}.",
                "url": _reverse_or_blank("medical_board_form_register"),
            })

    if any(token in text for token in ("fee", "payment", "receipt", "cost", "amount")):
        fees = FeeSchedule.objects.filter(active=True)
        if scope == "nursing":
            fees = fees.filter(regulatory_body__code="PNG_NURSING_COUNCIL")
        elif scope == "medical":
            fees = fees.filter(Q(regulatory_body__code__icontains="MEDICAL") | Q(regulatory_body__name__icontains="Medical Board"))
        for fee in fees.select_related("regulatory_body").order_by("fee_rule_code")[:3]:
            sources.append({
                "label": f"Fee: {fee.label}",
                "detail": f"{fee.amount} {fee.currency}",
                "url": _reverse_or_blank("fee_structure"),
            })

    sources.extend(retrieve_vector_sources(question=question, scope=scope, public=public, limit=ASSISTANT_SOURCE_LIMIT))
    sources = serialize_sources(sources)
    cache.set(cache_key, sources, 120)
    return sources
