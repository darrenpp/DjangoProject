import json
import re
import urllib.error
import urllib.request

from django.conf import settings


STAFF_AI_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "answer": {"type": "string"},
        "bullets": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 6,
        },
        "links": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "label": {"type": "string"},
                    "url": {"type": "string"},
                },
                "required": ["label", "url"],
            },
            "maxItems": 5,
        },
        "suggestions": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 4,
        },
    },
    "required": ["title", "answer", "bullets", "links", "suggestions"],
}


class AIProviderError(RuntimeError):
    pass


def _json_from_model_text(text, provider_label):
    text = str(text or "").strip()
    if not text:
        raise AIProviderError(f"{provider_label} response was empty.")
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise AIProviderError(f"{provider_label} response was not valid JSON.") from exc


def _ollama_base_url():
    return str(getattr(settings, "AI_OLLAMA_BASE_URL", "") or "http://127.0.0.1:11434").rstrip("/")


def ai_provider_status():
    configured_provider = str(getattr(settings, "AI_ASSISTANT_PROVIDER", "local") or "local").lower()
    external_enabled = bool(getattr(settings, "AI_ASSISTANT_EXTERNAL_ENABLED", False))
    local_llm_enabled = bool(getattr(settings, "AI_ASSISTANT_LOCAL_LLM_ENABLED", False))
    ollama_enabled = bool(getattr(settings, "AI_ASSISTANT_OLLAMA_ENABLED", False))
    has_openai_key = bool(getattr(settings, "OPENAI_API_KEY", ""))
    local_llm_base_url = str(getattr(settings, "AI_LOCAL_LLM_BASE_URL", "") or "").strip()
    local_llm_model = str(getattr(settings, "AI_LOCAL_LLM_MODEL", "") or "").strip()
    ollama_model = str(getattr(settings, "AI_OLLAMA_MODEL", "") or "").strip()
    ollama_base_url = _ollama_base_url()
    if configured_provider == "openai" and external_enabled and has_openai_key:
        mode = "openai"
        label = "Live OpenAI GPT"
        detail = "External GPT responses are enabled for approved staff only."
    elif configured_provider == "ollama" and ollama_enabled and ollama_model:
        mode = "ollama"
        label = "Free Local GPT"
        detail = "Using a local Ollama model server for staff-only assistance."
    elif configured_provider == "ollama" and not ollama_enabled:
        mode = "local_fallback"
        label = "Local Offline Assistant"
        detail = "Free local GPT mode was requested, but the Ollama switch is disabled."
    elif configured_provider == "ollama" and not ollama_model:
        mode = "local_fallback"
        label = "Local Offline Assistant"
        detail = "Free local GPT mode was requested, but no Ollama model is configured."
    elif configured_provider == "local_llm" and local_llm_enabled and local_llm_base_url and local_llm_model:
        mode = "local_llm"
        label = "Private Offline GPT"
        detail = "Using an approved internal model server for staff-only assistance."
    elif configured_provider == "local_llm" and not local_llm_enabled:
        mode = "local_fallback"
        label = "Local Offline Assistant"
        detail = "Private GPT mode was requested, but the local model switch is disabled."
    elif configured_provider == "local_llm" and not local_llm_base_url:
        mode = "local_fallback"
        label = "Local Offline Assistant"
        detail = "Private GPT mode was requested, but no local model endpoint is configured."
    elif configured_provider == "local_llm" and not local_llm_model:
        mode = "local_fallback"
        label = "Local Offline Assistant"
        detail = "Private GPT mode was requested, but no local model name is configured."
    elif configured_provider == "openai" and not has_openai_key:
        mode = "local_fallback"
        label = "Local Offline Assistant"
        detail = "OpenAI mode was requested, but no API key is configured."
    elif configured_provider == "openai" and not external_enabled:
        mode = "local_fallback"
        label = "Local Offline Assistant"
        detail = "External GPT calls are disabled by platform settings."
    else:
        mode = "local"
        label = "Local Offline Assistant"
        detail = "Using rule-based, offline staff guidance and cleansing checks."
    return {
        "configured_provider": configured_provider,
        "mode": mode,
        "label": label,
        "detail": detail,
        "external_enabled": external_enabled,
        "local_llm_enabled": local_llm_enabled,
        "ollama_enabled": ollama_enabled,
        "openai_ready": mode == "openai",
        "local_llm_ready": mode == "local_llm",
        "ollama_ready": mode == "ollama",
        "live_model_ready": mode in {"ollama", "local_llm", "openai"},
        "model": getattr(settings, "OPENAI_MODEL", ""),
        "local_model": local_llm_model,
        "local_endpoint_configured": bool(local_llm_base_url),
        "ollama_model": ollama_model,
        "ollama_base_url": ollama_base_url,
    }


def _extract_response_text(payload):
    if payload.get("output_text"):
        return payload["output_text"]
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                return content["text"]
    return ""


def call_openai_json(*, system_prompt, user_payload, schema, schema_name, timeout=None):
    status = ai_provider_status()
    if status["mode"] != "openai":
        raise AIProviderError(status["detail"])

    api_key = getattr(settings, "OPENAI_API_KEY", "")
    model = getattr(settings, "OPENAI_MODEL", "") or "gpt-5.4-mini"
    timeout = timeout or int(getattr(settings, "AI_ASSISTANT_TIMEOUT_SECONDS", 20))
    request_payload = {
        "model": model,
        "store": False,
        "input": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=True, default=str),
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "schema": schema,
                "strict": True,
            }
        },
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(request_payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw_payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise AIProviderError(f"OpenAI request failed: {exc}") from exc

    response_text = _extract_response_text(raw_payload)
    if not response_text:
        raise AIProviderError("OpenAI response did not include structured text.")
    return _json_from_model_text(response_text, "OpenAI")


def call_local_llm_json(*, system_prompt, user_payload, schema, schema_name, timeout=None):
    status = ai_provider_status()
    if status["mode"] != "local_llm":
        raise AIProviderError(status["detail"])

    base_url = str(getattr(settings, "AI_LOCAL_LLM_BASE_URL", "") or "").rstrip("/")
    if base_url.endswith("/v1/chat/completions"):
        endpoint = base_url
    else:
        endpoint = f"{base_url}/v1/chat/completions"
    model = getattr(settings, "AI_LOCAL_LLM_MODEL", "")
    timeout = timeout or int(getattr(settings, "AI_ASSISTANT_TIMEOUT_SECONDS", 20))
    request_payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    "Return JSON only using this schema name: "
                    f"{schema_name}. Schema: {json.dumps(schema, ensure_ascii=True)}. "
                    f"Payload: {json.dumps(user_payload, ensure_ascii=True, default=str)}"
                ),
            },
        ],
        "response_format": {"type": "json_object"},
    }
    headers = {"Content-Type": "application/json"}
    local_api_key = str(getattr(settings, "AI_LOCAL_LLM_API_KEY", "") or "").strip()
    if local_api_key:
        headers["Authorization"] = f"Bearer {local_api_key}"

    request = urllib.request.Request(
        endpoint,
        data=json.dumps(request_payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw_payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise AIProviderError(f"Local model request failed: {exc}") from exc

    try:
        response_text = raw_payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AIProviderError("Local model response did not include chat content.") from exc
    return _json_from_model_text(response_text, "Local model")


def call_ollama_json(*, system_prompt, user_payload, schema, schema_name, timeout=None):
    status = ai_provider_status()
    if status["mode"] != "ollama":
        raise AIProviderError(status["detail"])

    endpoint = f"{_ollama_base_url()}/api/chat"
    model = getattr(settings, "AI_OLLAMA_MODEL", "")
    timeout = timeout or int(getattr(settings, "AI_ASSISTANT_TIMEOUT_SECONDS", 20))
    request_payload = {
        "model": model,
        "stream": False,
        "format": schema,
        "keep_alive": getattr(settings, "AI_OLLAMA_KEEP_ALIVE", "10m"),
        "options": {
            "temperature": 0,
        },
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    "Return JSON only. "
                    f"Schema name: {schema_name}. "
                    f"Payload: {json.dumps(user_payload, ensure_ascii=True, default=str)}"
                ),
            },
        ],
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(request_payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw_payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise AIProviderError(f"Ollama request failed: {exc}") from exc

    response_text = ""
    if isinstance(raw_payload.get("message"), dict):
        response_text = raw_payload["message"].get("content", "")
    if not response_text:
        response_text = raw_payload.get("response", "")
    return _json_from_model_text(response_text, "Ollama")


def get_ollama_models(timeout=2):
    request = urllib.request.Request(f"{_ollama_base_url()}/api/tags", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise AIProviderError(f"Ollama health check failed: {exc}") from exc
    return [model.get("name", "") for model in payload.get("models", []) if model.get("name")]


def call_configured_ai_json(*, system_prompt, user_payload, schema, schema_name, timeout=None):
    status = ai_provider_status()
    if status["mode"] == "openai":
        return call_openai_json(
            system_prompt=system_prompt,
            user_payload=user_payload,
            schema=schema,
            schema_name=schema_name,
            timeout=timeout,
        )
    if status["mode"] == "ollama":
        return call_ollama_json(
            system_prompt=system_prompt,
            user_payload=user_payload,
            schema=schema,
            schema_name=schema_name,
            timeout=timeout,
        )
    if status["mode"] == "local_llm":
        return call_local_llm_json(
            system_prompt=system_prompt,
            user_payload=user_payload,
            schema=schema,
            schema_name=schema_name,
            timeout=timeout,
        )
    raise AIProviderError(status["detail"])


def _safe_staff_context(context):
    return {
        "scope": context.get("scope"),
        "scope_label": context.get("scope_label"),
        "agent_label": context.get("agent_label"),
        "pending_application_count": context.get("pending_application_count", 0),
        "missing_review_count": context.get("missing_review_count", 0),
        "duplicate_review_count": context.get("duplicate_review_count", 0),
        "open_enquiry_count": context.get("open_enquiry_count", 0),
        "document_review_count": context.get("document_review_count", 0),
    }


def maybe_generate_live_staff_response(user, question, context, local_response):
    status = ai_provider_status()
    local_response["ai_provider"] = status
    if status["mode"] not in {"openai", "ollama", "local_llm"}:
        return local_response

    system_prompt = (
        "You are the Staff AI Assistant for a government regulatory workforce system. "
        "You may only answer questions about staff operations, applications, imports, "
        "data cleansing, duplicate review, reports, documents, payments, and role access. "
        "Do not provide general chat. Do not invent data. Do not expose private records. "
        "Use only the supplied scoped counts and the user's question. If the question asks "
        "for an action that changes data, explain that staff must review and approve in the platform."
    )
    user_payload = {
        "role": getattr(user, "role", ""),
        "department": getattr(user, "department", ""),
        "question": question,
        "scoped_context": _safe_staff_context(context),
        "local_fallback_answer": local_response,
    }
    try:
        live_response = call_configured_ai_json(
            system_prompt=system_prompt,
            user_payload=user_payload,
            schema=STAFF_AI_RESPONSE_SCHEMA,
            schema_name="staff_ai_response",
        )
    except AIProviderError as exc:
        local_response["ai_provider"] = {
            **status,
            "mode": "local_fallback",
            "label": "Local Offline Assistant",
            "detail": f"Live GPT fallback used: {exc}",
        }
        return local_response

    live_response["ai_provider"] = status
    return live_response
