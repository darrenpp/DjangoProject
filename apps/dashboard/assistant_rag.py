import hashlib
import importlib.util
import json
import math
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.urls import NoReverseMatch, reverse
from django.utils import timezone


INDEX_VERSION = 2
INDEX_CACHE_SECONDS = 120
DEFAULT_SOURCE_LIMIT = 6


class AssistantRAGUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class KnowledgeDocument:
    document_id: str
    source_type: str
    label: str
    text: str
    detail: str
    scope: str = "shared"
    audience: str = "staff"
    url_name: str = ""
    url: str = ""
    updated_at: str = ""


def _setting_bool(name, default=False):
    return bool(getattr(settings, name, default))


def _index_path():
    configured = str(getattr(settings, "AI_ASSISTANT_RAG_INDEX_PATH", "") or "").strip()
    if configured:
        return Path(configured)
    return Path(settings.BASE_DIR) / "media" / "ai_knowledge" / "staff_assistant_index.json"


def _stale_marker_path():
    """Return the small durable marker used to prevent stale RAG answers."""
    index_path = _index_path()
    return index_path.with_name(f"{index_path.stem}.stale.json")


def mark_knowledge_index_stale(reason=""):
    """Mark the index stale after an authoritative knowledge source changes.

    The next retrieval rebuilds the index when auto-build is enabled.  We keep a
    marker beside the index rather than doing expensive embedding work inside a
    database save transaction.
    """
    if not _setting_bool("AI_ASSISTANT_RAG_ENABLED", False):
        return False
    marker_path = _stale_marker_path()
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "marked_at": timezone.now().isoformat(),
        "reason": _clean_text(reason, limit=240),
    }
    temporary_path = marker_path.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
    temporary_path.replace(marker_path)
    cache.delete(_index_cache_key(_index_path()))
    return True


def knowledge_index_is_stale():
    return _stale_marker_path().exists()


def _clear_knowledge_index_stale_marker():
    try:
        _stale_marker_path().unlink()
    except FileNotFoundError:
        pass


def _embedding_model_name():
    return str(
        getattr(settings, "AI_ASSISTANT_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
        or "sentence-transformers/all-MiniLM-L6-v2"
    )


def _vector_backend():
    return str(getattr(settings, "AI_ASSISTANT_RAG_VECTOR_BACKEND", "local_json") or "local_json").lower()


def _chroma_path():
    configured = str(getattr(settings, "AI_ASSISTANT_CHROMA_PATH", "") or "").strip()
    if configured:
        return Path(configured)
    return _index_path().parent / "chroma"


def _chroma_collection_name():
    return str(getattr(settings, "AI_ASSISTANT_CHROMA_COLLECTION", "staff_assistant_knowledge") or "staff_assistant_knowledge")


def _sentence_transformers_available():
    try:
        return importlib.util.find_spec("sentence_transformers") is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _chromadb_available():
    try:
        return importlib.util.find_spec("chromadb") is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _reverse_or_blank(url_name):
    if not url_name:
        return ""
    try:
        return reverse(url_name)
    except NoReverseMatch:
        return ""


def _clean_text(value, limit=4000):
    text = " ".join(str(value or "").split())
    if limit and len(text) > limit:
        return text[:limit].rsplit(" ", 1)[0]
    return text


def _stable_id(*parts):
    raw = ":".join(str(part or "") for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _body_scope(regulatory_body):
    text = f"{getattr(regulatory_body, 'code', '')} {getattr(regulatory_body, 'name', '')}".lower()
    if "nurs" in text:
        return "nursing"
    if "medical" in text or "doctor" in text or "chw" in text:
        return "medical"
    return "shared"


def _audience_scope(audience):
    if audience in {"nurse", "nurse_aide", "graduand"}:
        return "nursing"
    if audience in {"doctor", "chw"}:
        return "medical"
    return "shared"


def _form_url_name(scope):
    if scope == "medical":
        return "medical_board_form_register"
    if scope == "nursing":
        return "nursing_forms_portal"
    return ""


def _json_preview(value, limit=900):
    if value in (None, "", [], {}):
        return ""
    try:
        text = json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)
    except TypeError:
        text = str(value)
    return _clean_text(text, limit=limit)


def _doc_from_parts(*, source_type, pk, label, detail, text, scope, audience="staff", url_name="", url="", updated_at=""):
    label = _clean_text(label, limit=220)
    text = _clean_text(text)
    if not label or not text:
        return None
    return KnowledgeDocument(
        document_id=_stable_id(source_type, pk, updated_at, label),
        source_type=source_type,
        label=label,
        text=text,
        detail=_clean_text(detail, limit=260),
        scope=scope or "shared",
        audience=audience or "staff",
        url_name=url_name or "",
        url=url or _reverse_or_blank(url_name),
        updated_at=str(updated_at or ""),
    )


def collect_knowledge_documents():
    from apps.dashboard.models import FAQEntry, RegistrationGuideline
    from apps.workforce.models import (
        ApplicationPathway,
        DynamicFormDefinition,
        FeeSchedule,
        PolicyDocument,
    )

    max_documents = int(getattr(settings, "AI_ASSISTANT_RAG_MAX_DOCUMENTS", 800) or 800)
    documents = []

    def add(document):
        if document and len(documents) < max_documents:
            documents.append(document)

    for faq in (
        FAQEntry.objects
        .select_related("category")
        .filter(is_published=True, category__is_active=True)
        .order_by("category__display_order", "display_order", "question")[:max_documents]
    ):
        category = faq.category
        add(_doc_from_parts(
            source_type="faq",
            pk=faq.pk,
            label=f"FAQ: {faq.question}",
            detail=faq.answer,
            text=f"{category.name}. {category.description}. {faq.question}. {faq.answer}. {faq.keywords}",
            scope=category.office_scope or "shared",
            audience=category.audience or "public",
            url_name="public_faqs",
            updated_at=faq.updated_at.isoformat() if faq.updated_at else "",
        ))

    for guideline in RegistrationGuideline.objects.filter(is_active=True).order_by("display_order", "code"):
        scope = _audience_scope(guideline.audience)
        add(_doc_from_parts(
            source_type="registration_guideline",
            pk=guideline.pk,
            label=f"Guideline: {guideline.code} {guideline.title}",
            detail=guideline.summary,
            text=f"{guideline.code}. {guideline.title}. {guideline.summary}. Required fields {_json_preview(guideline.required_fields)}.",
            scope=scope,
            audience="staff" if guideline.audience == "general" else "practitioner",
            url_name=guideline.action_url_name,
        ))

    for pathway in ApplicationPathway.objects.select_related("regulatory_body").filter(active=True).order_by("regulatory_body__name", "sort_order"):
        scope = _body_scope(pathway.regulatory_body)
        add(_doc_from_parts(
            source_type="application_pathway",
            pk=pathway.pk,
            label=f"Pathway: {pathway.pathway_code} {pathway.pathway_name}",
            detail=f"Primary form {pathway.primary_form_code}; checklist {pathway.checklist_code}; licence {pathway.creates_licence_type or 'not specified'}.",
            text=(
                f"{pathway.regulatory_body.name}. {pathway.pathway_code}. {pathway.pathway_name}. "
                f"Applicant type {pathway.applicant_type}. Primary form {pathway.primary_form_code}. "
                f"Checklist {pathway.checklist_code}. Fee rule {pathway.fee_rule_code}. "
                f"Creates licence type {pathway.creates_licence_type}. "
                f"Requires payment {pathway.requires_payment}. Requires registrar approval {pathway.requires_registrar_approval}. "
                f"{_json_preview(pathway.configuration)}"
            ),
            scope=scope,
            audience="public" if pathway.public_visible else "staff",
            url_name=_form_url_name(scope),
        ))

    for form in DynamicFormDefinition.objects.select_related("regulatory_body", "pathway").filter(active=True).order_by("regulatory_body__name", "form_code", "-version"):
        scope = _body_scope(form.regulatory_body)
        add(_doc_from_parts(
            source_type="dynamic_form",
            pk=form.pk,
            label=f"Form {form.form_code}: {form.form_name}",
            detail=f"Dynamic form version {form.version} for {form.regulatory_body.name}.",
            text=(
                f"{form.regulatory_body.name}. {form.form_code}. {form.form_name}. Version {form.version}. "
                f"Pathway {getattr(form.pathway, 'pathway_name', '')}. "
                f"Required documents {_json_preview(form.required_documents)}. "
                f"Fields {_json_preview(form.fields)}. Validation {_json_preview(form.validation_rules)}."
            ),
            scope=scope,
            audience="practitioner",
            url_name=_form_url_name(scope),
        ))

    for fee in FeeSchedule.objects.select_related("regulatory_body", "pathway").filter(active=True).order_by("regulatory_body__name", "fee_rule_code"):
        scope = _body_scope(fee.regulatory_body)
        add(_doc_from_parts(
            source_type="fee",
            pk=fee.pk,
            label=f"Fee: {fee.label}",
            detail=f"{fee.amount} {fee.currency}; rule {fee.fee_rule_code}.",
            text=(
                f"{fee.regulatory_body.name}. {fee.fee_rule_code}. {fee.label}. "
                f"Applicant type {fee.applicant_type}. Amount {fee.amount} {fee.currency}. "
                f"Pathway {getattr(fee.pathway, 'pathway_name', '')}."
            ),
            scope=scope,
            audience="practitioner",
            url_name="fee_structure",
        ))

    for policy in PolicyDocument.objects.select_related("regulatory_body").filter(active=True).order_by("regulatory_body__name", "code", "-version"):
        scope = _body_scope(policy.regulatory_body)
        add(_doc_from_parts(
            source_type="policy",
            pk=policy.pk,
            label=f"Policy: {policy.code} {policy.title}",
            detail=f"{policy.regulatory_body.name}; version {policy.version}.",
            text=f"{policy.regulatory_body.name}. {policy.code}. {policy.title}. Version {policy.version}. {policy.document_url}",
            scope=scope,
            audience="staff",
            url=policy.document_url,
        ))

    return documents


@lru_cache(maxsize=2)
def _embedding_model(model_name):
    from sentence_transformers import SentenceTransformer

    try:
        return SentenceTransformer(
            model_name,
            local_files_only=_setting_bool("AI_ASSISTANT_EMBEDDING_LOCAL_FILES_ONLY", True),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise AssistantRAGUnavailable(
            "The configured local embedding model is unavailable. Install it during deployment before enabling RAG."
        ) from exc


def _embed_texts(texts):
    if not _sentence_transformers_available():
        raise AssistantRAGUnavailable("The sentence-transformers package is not installed.")
    model = _embedding_model(_embedding_model_name())
    embeddings = model.encode(list(texts), normalize_embeddings=True)
    if hasattr(embeddings, "tolist"):
        embeddings = embeddings.tolist()
    return [[float(value) for value in embedding] for embedding in embeddings]


def _indexed_document_payload(document, embedding):
    payload = asdict(document)
    payload["embedding"] = embedding
    return payload


def _sync_chroma_collection(documents, embeddings):
    if _vector_backend() != "chroma" or not _chromadb_available():
        return False

    import chromadb

    client = chromadb.PersistentClient(path=str(_chroma_path()))
    collection = client.get_or_create_collection(
        name=_chroma_collection_name(),
        metadata={"hnsw:space": "cosine"},
    )
    collection.upsert(
        ids=[document.document_id for document in documents],
        embeddings=embeddings,
        documents=[document.text for document in documents],
        metadatas=[
            {
                "source_type": document.source_type,
                "label": document.label,
                "detail": document.detail,
                "scope": document.scope,
                "audience": document.audience,
                "url_name": document.url_name,
                "url": document.url,
                "updated_at": document.updated_at,
            }
            for document in documents
        ],
    )
    return True


def build_vector_index():
    documents = collect_knowledge_documents()
    if not documents:
        raise AssistantRAGUnavailable("No assistant knowledge documents are available to index.")

    embeddings = _embed_texts([document.text for document in documents])
    payload = {
        "version": INDEX_VERSION,
        "generated_at": timezone.now().isoformat(),
        "embedding_model": _embedding_model_name(),
        "embedding_local_files_only": _setting_bool("AI_ASSISTANT_EMBEDDING_LOCAL_FILES_ONLY", True),
        "document_count": len(documents),
        "documents": [
            _indexed_document_payload(document, embedding)
            for document, embedding in zip(documents, embeddings)
        ],
    }
    path = _index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    chroma_synced = _sync_chroma_collection(documents, embeddings)
    cache.delete(_index_cache_key(path))
    _clear_knowledge_index_stale_marker()
    return {
        "index_path": str(path),
        "document_count": len(documents),
        "embedding_model": _embedding_model_name(),
        "vector_backend": _vector_backend(),
        "chroma_synced": chroma_synced,
    }


def _index_cache_key(path):
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = "missing"
    return f"assistant-rag-index:{path}:{mtime}"


def _load_index():
    path = _index_path()
    if not path.exists():
        return None
    cache_key = _index_cache_key(path)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    cache.set(cache_key, payload, INDEX_CACHE_SECONDS)
    return payload


def _scope_allowed(document_scope, user_scope):
    document_scope = document_scope or "shared"
    user_scope = user_scope or "public"
    if document_scope == "shared":
        return True
    if user_scope == "all":
        return document_scope in {"nursing", "medical", "all"}
    return document_scope == user_scope


def _audience_allowed(document_audience, public):
    if public:
        return document_audience in {"public", "practitioner"}
    return document_audience in {"staff", "public", "practitioner", "general"}


def _cosine_score(left, right):
    if not left or not right:
        return 0.0
    total = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for index, left_value in enumerate(left):
        right_value = right[index] if index < len(right) else 0.0
        total += left_value * right_value
        left_norm += left_value * left_value
        right_norm += right_value * right_value
    if not left_norm or not right_norm:
        return 0.0
    return total / (math.sqrt(left_norm) * math.sqrt(right_norm))


def _as_source(row, score):
    detail = row.get("detail") or row.get("text", "")
    if score:
        detail = f"{detail} Match score {score:.2f}."
    return {
        "label": row.get("label", ""),
        "detail": _clean_text(detail, limit=220),
        "url": row.get("url") or _reverse_or_blank(row.get("url_name")),
    }


def _as_source_from_metadata(metadata, score):
    detail = metadata.get("detail") or ""
    if score:
        detail = f"{detail} Match score {score:.2f}."
    return {
        "label": metadata.get("label", ""),
        "detail": _clean_text(detail, limit=220),
        "url": metadata.get("url") or _reverse_or_blank(metadata.get("url_name")),
    }


def _dedupe_sources(sources):
    seen = set()
    deduped = []
    for source in sources:
        key = (source.get("label"), source.get("url"))
        if not source.get("label") or key in seen:
            continue
        seen.add(key)
        deduped.append(source)
    return deduped


def _retrieve_chroma_sources(query_embedding, *, scope, public, limit, min_score):
    if _vector_backend() != "chroma" or not _chromadb_available():
        return []
    try:
        import chromadb

        client = chromadb.PersistentClient(path=str(_chroma_path()))
        collection = client.get_collection(name=_chroma_collection_name())
        result = collection.query(
            query_embeddings=[query_embedding],
            n_results=max(limit * 4, 12),
            include=["metadatas", "distances"],
        )
    except Exception:
        return []

    sources = []
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]
    for index, metadata in enumerate(metadatas):
        if not _scope_allowed(metadata.get("scope"), scope):
            continue
        if not _audience_allowed(metadata.get("audience"), public):
            continue
        distance = float(distances[index]) if index < len(distances) else 1.0
        score = max(0.0, 1.0 - distance)
        if score >= min_score:
            sources.append(_as_source_from_metadata(metadata, score))
        if len(sources) >= limit:
            break
    return _dedupe_sources(sources)


def retrieve_vector_sources(*, question, scope="public", public=False, limit=DEFAULT_SOURCE_LIMIT):
    if not _setting_bool("AI_ASSISTANT_RAG_ENABLED", False):
        return []
    question = _clean_text(question, limit=1000)
    if not question:
        return []
    if not _sentence_transformers_available():
        return []

    payload = _load_index()
    index_stale = knowledge_index_is_stale()
    if (payload is None or index_stale) and _setting_bool("AI_ASSISTANT_RAG_AUTO_BUILD", True):
        try:
            build_vector_index()
        except (AssistantRAGUnavailable, ImportError, OSError, RuntimeError, ValueError):
            return []
        payload = _load_index()
        index_stale = knowledge_index_is_stale()
    if index_stale:
        # Do not quietly answer from a known stale policy, fee, or pathway index.
        return []
    if not payload or payload.get("embedding_model") != _embedding_model_name():
        return []

    try:
        query_embedding = _embed_texts([question])[0]
    except (AssistantRAGUnavailable, ImportError, OSError, RuntimeError, ValueError):
        # Retrieval supplements deterministic local answers. A missing or
        # offline embedding model must not prevent staff or public help.
        return []
    min_score = float(getattr(settings, "AI_ASSISTANT_RAG_MIN_SCORE", 0.18) or 0.18)
    chroma_sources = _retrieve_chroma_sources(
        query_embedding,
        scope=scope,
        public=public,
        limit=limit,
        min_score=min_score,
    )
    if chroma_sources:
        return chroma_sources

    matches = []
    for row in payload.get("documents", []):
        if not _scope_allowed(row.get("scope"), scope):
            continue
        if not _audience_allowed(row.get("audience"), public):
            continue
        score = _cosine_score(query_embedding, row.get("embedding") or [])
        if score >= min_score:
            matches.append((score, row))
    matches.sort(key=lambda item: item[0], reverse=True)
    return _dedupe_sources([_as_source(row, score) for score, row in matches[:limit]])


def rag_status():
    path = _index_path()
    payload = _load_index()
    enabled = _setting_bool("AI_ASSISTANT_RAG_ENABLED", False)
    sentence_transformers_installed = _sentence_transformers_available()
    index_ready = bool(payload and payload.get("embedding_model") == _embedding_model_name())
    index_stale = knowledge_index_is_stale()
    ready = enabled and sentence_transformers_installed and index_ready and not index_stale
    if ready:
        detail = f"Vector knowledge index ready with {payload.get('document_count', 0)} documents."
    elif not enabled:
        detail = "RAG knowledge search is disabled."
    elif not sentence_transformers_installed:
        detail = "Install sentence-transformers to enable local embeddings."
    elif index_stale:
        detail = "Knowledge sources changed; rebuild the assistant index before relying on vector answers."
    elif not index_ready:
        detail = "Build the assistant knowledge index before enabling vector answers."
    else:
        detail = "RAG knowledge search is not ready."
    return {
        "enabled": enabled,
        "ready": ready,
        "detail": detail,
        "vector_backend": _vector_backend(),
        "embedding_model": _embedding_model_name(),
        "embedding_local_files_only": _setting_bool("AI_ASSISTANT_EMBEDDING_LOCAL_FILES_ONLY", True),
        "sentence_transformers_installed": sentence_transformers_installed,
        "chromadb_installed": _chromadb_available(),
        "chroma_path": str(_chroma_path()),
        "chroma_collection": _chroma_collection_name(),
        "index_path": str(path),
        "index_exists": path.exists(),
        "index_stale": index_stale,
        "stale_marker_path": str(_stale_marker_path()),
        "index_document_count": int(payload.get("document_count", 0)) if payload else 0,
        "auto_build": _setting_bool("AI_ASSISTANT_RAG_AUTO_BUILD", True),
    }
