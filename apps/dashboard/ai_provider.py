import asyncio
import importlib.util
import inspect
import json
import os
import re
import urllib.error
import urllib.request
import uuid

from asgiref.sync import async_to_sync
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
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "label": {"type": "string"},
                    "detail": {"type": "string"},
                    "url": {"type": "string"},
                },
                "required": ["label", "detail", "url"],
            },
            "maxItems": 6,
        },
    },
    # Sources are attached by the server from the authorised retrieval set.
    # Keeping them optional here lets small local models return valid structured
    # answers without being trusted to manufacture citations.
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
    except json.JSONDecodeError as initial_error:
        # Smaller local models occasionally prefix or suffix an otherwise valid
        # structured answer with a short explanation.  Recover one JSON object
        # rather than discarding a grounded response and forcing a fallback.
        object_start = text.find("{")
        if object_start >= 0:
            try:
                payload, _position = json.JSONDecoder().raw_decode(text[object_start:])
            except json.JSONDecodeError:
                pass
            else:
                if isinstance(payload, dict):
                    return payload
        raise AIProviderError(f"{provider_label} response was not valid JSON.") from initial_error


def _ollama_base_url():
    return str(getattr(settings, "AI_OLLAMA_BASE_URL", "") or "http://127.0.0.1:11434").rstrip("/")


def _google_adk_package_available():
    try:
        return importlib.util.find_spec("google.adk") is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def ai_provider_status():
    from apps.dashboard.assistant_rag import rag_status
    from apps.dashboard.ai_worker import redis_worker_status

    configured_provider = str(getattr(settings, "AI_ASSISTANT_PROVIDER", "local") or "local").lower()
    external_enabled = bool(getattr(settings, "AI_ASSISTANT_EXTERNAL_ENABLED", False))
    local_llm_enabled = bool(getattr(settings, "AI_ASSISTANT_LOCAL_LLM_ENABLED", False))
    localai_enabled = bool(getattr(settings, "AI_ASSISTANT_LOCALAI_ENABLED", False))
    ollama_enabled = bool(getattr(settings, "AI_ASSISTANT_OLLAMA_ENABLED", False))
    google_adk_enabled = bool(getattr(settings, "AI_GOOGLE_ADK_ENABLED", False))
    has_openai_key = bool(getattr(settings, "OPENAI_API_KEY", ""))
    has_google_api_key = bool(getattr(settings, "GOOGLE_API_KEY", ""))
    local_llm_base_url = str(getattr(settings, "AI_LOCAL_LLM_BASE_URL", "") or "").strip()
    local_llm_model = str(getattr(settings, "AI_LOCAL_LLM_MODEL", "") or "").strip()
    localai_base_url = str(getattr(settings, "AI_LOCALAI_BASE_URL", "") or "").strip()
    localai_model = str(getattr(settings, "AI_LOCALAI_MODEL", "") or "").strip()
    has_localai_api_key = bool(getattr(settings, "AI_LOCALAI_API_KEY", ""))
    ollama_model = str(getattr(settings, "AI_OLLAMA_MODEL", "") or "").strip()
    ollama_base_url = _ollama_base_url()
    google_adk_model = str(getattr(settings, "AI_GOOGLE_ADK_MODEL", "") or "").strip()
    google_adk_installed = _google_adk_package_available()
    rag = rag_status()
    worker = redis_worker_status()
    redis_worker_enabled = bool(worker.get("enabled"))
    redis_worker_ready = bool(worker.get("configured") and worker.get("model_configured"))
    if configured_provider == "redis_worker" and redis_worker_ready:
        mode = "redis_worker"
        label = "Queued Local AI Worker"
        detail = "Using the platform Redis queue and Django AI worker for scoped staff-assistant responses."
    elif configured_provider == "redis_worker" and not redis_worker_enabled:
        mode = "local_fallback"
        label = "Local Offline Assistant"
        detail = "Redis worker mode was requested, but AI_REDIS_WORKER_ENABLED is false."
    elif configured_provider == "redis_worker" and not worker.get("redis_package_available"):
        mode = "local_fallback"
        label = "Local Offline Assistant"
        detail = "Redis worker mode was requested, but the redis Python package is not installed."
    elif configured_provider == "redis_worker" and not worker.get("url"):
        mode = "local_fallback"
        label = "Local Offline Assistant"
        detail = "Redis worker mode was requested, but AI_REDIS_URL is not configured."
    elif configured_provider == "redis_worker" and not worker.get("model_configured"):
        mode = "local_fallback"
        label = "Local Offline Assistant"
        detail = worker.get("model_detail") or "Redis worker model is not configured."
    elif configured_provider == "google_adk" and google_adk_enabled and has_google_api_key and google_adk_model and google_adk_installed:
        mode = "google_adk"
        label = "Google ADK Agent"
        detail = "Using a Google ADK Gemini agent for approved assistant responses."
    elif configured_provider == "google_adk" and not google_adk_enabled:
        mode = "local_fallback"
        label = "Local Offline Assistant"
        detail = "Google ADK agent mode was requested, but the ADK switch is disabled."
    elif configured_provider == "google_adk" and not has_google_api_key:
        mode = "local_fallback"
        label = "Local Offline Assistant"
        detail = "Google ADK agent mode was requested, but no GOOGLE_API_KEY is configured."
    elif configured_provider == "google_adk" and not google_adk_model:
        mode = "local_fallback"
        label = "Local Offline Assistant"
        detail = "Google ADK agent mode was requested, but no ADK model is configured."
    elif configured_provider == "google_adk" and not google_adk_installed:
        mode = "local_fallback"
        label = "Local Offline Assistant"
        detail = "Google ADK agent mode was requested, but the google-adk package is not installed."
    elif configured_provider == "openai" and external_enabled and has_openai_key:
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
    elif configured_provider == "localai" and localai_enabled and localai_base_url and localai_model:
        mode = "localai"
        label = "LocalAI Assistant"
        detail = "Using a LocalAI endpoint for staff-only assistance."
    elif configured_provider == "localai" and not localai_enabled:
        mode = "local_fallback"
        label = "Local Offline Assistant"
        detail = "LocalAI mode was requested, but the LocalAI switch is disabled."
    elif configured_provider == "localai" and not localai_base_url:
        mode = "local_fallback"
        label = "Local Offline Assistant"
        detail = "LocalAI mode was requested, but no LocalAI endpoint is configured."
    elif configured_provider == "localai" and not localai_model:
        mode = "local_fallback"
        label = "Local Offline Assistant"
        detail = "LocalAI mode was requested, but no LocalAI model is configured."
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
        "localai_enabled": localai_enabled,
        "ollama_enabled": ollama_enabled,
        "google_adk_enabled": google_adk_enabled,
        "openai_ready": mode == "openai",
        "local_llm_ready": mode == "local_llm",
        "localai_ready": mode == "localai",
        "ollama_ready": mode == "ollama",
        "google_adk_ready": mode == "google_adk",
        "live_model_ready": mode in {"ollama", "local_llm", "localai", "openai", "google_adk", "redis_worker"},
        "model": getattr(settings, "OPENAI_MODEL", ""),
        "local_model": local_llm_model,
        "local_endpoint_configured": bool(local_llm_base_url),
        "localai_model": localai_model,
        "localai_endpoint_configured": bool(localai_base_url),
        "localai_base_url": localai_base_url,
        "localai_api_key_configured": has_localai_api_key,
        "ollama_model": ollama_model,
        "ollama_base_url": ollama_base_url,
        "google_adk_model": google_adk_model,
        "google_adk_installed": google_adk_installed,
        "google_api_key_configured": has_google_api_key,
        "redis_worker_enabled": redis_worker_enabled,
        "redis_worker_ready": mode == "redis_worker",
        "redis_worker_url_configured": bool(worker.get("url")),
        "redis_worker_queue": worker.get("queue", ""),
        "redis_worker_model_provider": worker.get("model_provider", ""),
        "redis_worker_model_configured": bool(worker.get("model_configured")),
        "redis_worker_detail": worker.get("model_detail", ""),
        "rag": rag,
        "rag_enabled": rag["enabled"],
        "rag_ready": rag["ready"],
        "rag_detail": rag["detail"],
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


def call_localai_json(*, system_prompt, user_payload, schema, schema_name, timeout=None):
    status = ai_provider_status()
    if status["mode"] != "localai":
        raise AIProviderError(status["detail"])

    base_url = str(getattr(settings, "AI_LOCALAI_BASE_URL", "") or "").rstrip("/")
    if base_url.endswith("/v1/chat/completions"):
        endpoint = base_url
    else:
        endpoint = f"{base_url}/v1/chat/completions"
    model = getattr(settings, "AI_LOCALAI_MODEL", "")
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
    local_api_key = str(getattr(settings, "AI_LOCALAI_API_KEY", "") or "").strip()
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
        raise AIProviderError(f"LocalAI request failed: {exc}") from exc

    try:
        response_text = raw_payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AIProviderError("LocalAI response did not include chat content.") from exc
    return _json_from_model_text(response_text, "LocalAI")


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
            # Keep CPU-based local replies within the staff interaction timeout.
            "num_predict": max(96, min(int(getattr(settings, "AI_OLLAMA_NUM_PREDICT", 240) or 240), 512)),
            "num_ctx": max(1024, min(int(getattr(settings, "AI_OLLAMA_NUM_CTX", 2048) or 2048), 8192)),
        },
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    "Return JSON only. "
                    f"Schema name: {schema_name}. "
                    "Keep the answer concise: at most 120 words, four bullets, three links, and three suggestions. "
                    "Omit the sources field because the platform attaches verified sources. "
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


def _json_safe_payload(value):
    return json.loads(json.dumps(value, ensure_ascii=True, default=str))


def _load_google_adk_runtime():
    try:
        from google.adk import Agent as AgentClass
    except ImportError:
        try:
            from google.adk.agents import Agent as AgentClass
        except ImportError:
            try:
                from google.adk.agents import LlmAgent as AgentClass
            except ImportError:
                from google.adk.agents.llm_agent import Agent as AgentClass

    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    return AgentClass, Runner, InMemorySessionService, types


def _extract_google_adk_event_text(event):
    is_final_response = getattr(event, "is_final_response", None)
    if callable(is_final_response) and not is_final_response():
        return ""

    content = getattr(event, "content", None)
    parts = getattr(content, "parts", None) or []
    text_parts = []
    for part in parts:
        text = getattr(part, "text", "")
        if text:
            text_parts.append(str(text))
    return "\n".join(text_parts).strip()


async def _create_google_adk_session(session_service, *, app_name, user_id, session_id):
    try:
        created_session = session_service.create_session(
            app_name=app_name,
            user_id=user_id,
            session_id=session_id,
        )
    except TypeError:
        created_session = session_service.create_session(
            app_name=app_name,
            user_id=user_id,
            state={},
            session_id=session_id,
        )
    if inspect.isawaitable(created_session):
        await created_session


async def _run_google_adk_agent(*, agent, Runner, InMemorySessionService, types, prompt):
    app_name = "ndoh_regulatory_platform"
    user_id = "staff_ai"
    session_id = f"session_{uuid.uuid4().hex}"
    session_service = InMemorySessionService()
    await _create_google_adk_session(
        session_service,
        app_name=app_name,
        user_id=user_id,
        session_id=session_id,
    )
    runner = Runner(agent=agent, app_name=app_name, session_service=session_service)
    content = types.Content(role="user", parts=[types.Part(text=prompt)])
    final_response_text = ""

    async def collect_async_events(events):
        response_text = ""
        async for event in events:
            event_text = _extract_google_adk_event_text(event)
            if event_text:
                response_text = event_text
        return response_text

    def collect_sync_events(events):
        response_text = ""
        for event in events:
            event_text = _extract_google_adk_event_text(event)
            if event_text:
                response_text = event_text
        return response_text

    if hasattr(runner, "run_async"):
        events = runner.run_async(user_id=user_id, session_id=session_id, new_message=content)
        if inspect.isawaitable(events):
            events = await events
        if hasattr(events, "__aiter__"):
            final_response_text = await collect_async_events(events)
        else:
            final_response_text = collect_sync_events(events)
    else:
        events = runner.run(user_id=user_id, session_id=session_id, new_message=content)
        if inspect.isawaitable(events):
            events = await events
        final_response_text = collect_sync_events(events)

    return final_response_text


async def _run_google_adk_agent_with_timeout(**kwargs):
    timeout = kwargs.pop("timeout")
    return await asyncio.wait_for(_run_google_adk_agent(**kwargs), timeout=timeout)


def call_google_adk_json(*, system_prompt, user_payload, schema, schema_name, timeout=None, extra_tools=None):
    status = ai_provider_status()
    if status["mode"] != "google_adk":
        raise AIProviderError(status["detail"])

    timeout = timeout or int(getattr(settings, "AI_ASSISTANT_TIMEOUT_SECONDS", 20))
    google_api_key = str(getattr(settings, "GOOGLE_API_KEY", "") or "").strip()
    model = str(getattr(settings, "AI_GOOGLE_ADK_MODEL", "") or "").strip()
    os.environ["GOOGLE_API_KEY"] = google_api_key

    try:
        AgentClass, Runner, InMemorySessionService, types = _load_google_adk_runtime()
    except ImportError as exc:
        raise AIProviderError("Google ADK runtime is not installed.") from exc

    safe_payload = _json_safe_payload(user_payload)

    def get_supplied_context() -> dict:
        """Return the scoped platform context approved for this assistant turn."""
        return _json_safe_payload(safe_payload.get("scoped_context", {}))

    def get_local_fallback_answer() -> dict:
        """Return the deterministic local answer generated before the live model call."""
        return _json_safe_payload(safe_payload.get("local_fallback_answer", {}))

    def get_allowed_links() -> list:
        """Return only the navigation links supplied by the platform for this turn."""
        local_answer = safe_payload.get("local_fallback_answer", {})
        return _json_safe_payload(local_answer.get("links", []))

    instruction = (
        f"{system_prompt}\n\n"
        "You are an agent embedded in the NDOH regulatory platform. "
        "Use only the supplied request payload and tools. Do not change records, approve applications, "
        "or claim that an action was completed. Return JSON only, without markdown fences. "
        f"The JSON must match schema name '{schema_name}' and this schema: "
        f"{json.dumps(schema, ensure_ascii=True)}"
    )
    prompt = (
        "Prepare the assistant response for this Django platform request. "
        "Use get_supplied_context, get_local_fallback_answer, get_allowed_links, and any approved "
        "read-only database lookup tools when they are relevant. "
        f"Request payload: {json.dumps(safe_payload, ensure_ascii=True, default=str)}"
    )
    agent_tools = [
        get_supplied_context,
        get_local_fallback_answer,
        get_allowed_links,
        *(extra_tools or []),
    ]

    agent = AgentClass(
        model=model,
        name="ndoh_regulatory_assistant",
        description="Government regulatory platform assistant for scoped user interaction.",
        instruction=instruction,
        tools=agent_tools,
    )

    try:
        response_text = async_to_sync(_run_google_adk_agent_with_timeout)(
            agent=agent,
            Runner=Runner,
            InMemorySessionService=InMemorySessionService,
            types=types,
            prompt=prompt,
            timeout=timeout,
        )
    except (asyncio.TimeoutError, TimeoutError) as exc:
        raise AIProviderError("Google ADK request timed out.") from exc
    except Exception as exc:
        raise AIProviderError(f"Google ADK request failed: {exc}") from exc

    if not response_text:
        raise AIProviderError("Google ADK response did not include structured text.")
    return _json_from_model_text(response_text, "Google ADK")


def call_redis_worker_json(*, system_prompt, user_payload, schema, schema_name, timeout=None):
    status = ai_provider_status()
    if status["mode"] != "redis_worker":
        raise AIProviderError(status["detail"])
    from apps.dashboard.ai_worker import AIWorkerError, submit_redis_ai_request

    try:
        return submit_redis_ai_request(
            system_prompt=system_prompt,
            user_payload=user_payload,
            schema=schema,
            schema_name=schema_name,
            timeout=timeout,
        )
    except AIWorkerError as exc:
        raise AIProviderError(str(exc)) from exc
    except Exception as exc:
        raise AIProviderError(f"Redis AI worker request failed: {exc}") from exc


def get_ollama_models(timeout=2):
    request = urllib.request.Request(f"{_ollama_base_url()}/api/tags", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise AIProviderError(f"Ollama health check failed: {exc}") from exc
    return [model.get("name", "") for model in payload.get("models", []) if model.get("name")]


def get_localai_models(timeout=2):
    base_url = str(getattr(settings, "AI_LOCALAI_BASE_URL", "") or "").rstrip("/")
    if not base_url:
        raise AIProviderError("LocalAI base URL is not configured.")
    request = urllib.request.Request(f"{base_url}/v1/models", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise AIProviderError(f"LocalAI health check failed: {exc}") from exc

    model_rows = []
    for model in payload.get("data", []):
        if isinstance(model, dict):
            model_name = model.get("id") or model.get("name")
            if model_name:
                model_rows.append(model_name)
    if not model_rows:
        for model in payload.get("models", []):
            if isinstance(model, dict):
                model_name = model.get("name") or model.get("id")
            else:
                model_name = str(model)
            if model_name:
                model_rows.append(model_name)
    return model_rows


def call_configured_ai_json(*, system_prompt, user_payload, schema, schema_name, timeout=None, extra_tools=None):
    status = ai_provider_status()
    if status["mode"] == "redis_worker":
        return call_redis_worker_json(
            system_prompt=system_prompt,
            user_payload=user_payload,
            schema=schema,
            schema_name=schema_name,
            timeout=timeout,
        )
    if status["mode"] == "google_adk":
        return call_google_adk_json(
            system_prompt=system_prompt,
            user_payload=user_payload,
            schema=schema,
            schema_name=schema_name,
            timeout=timeout,
            extra_tools=extra_tools,
        )
    if status["mode"] == "openai":
        return call_openai_json(
            system_prompt=system_prompt,
            user_payload=user_payload,
            schema=schema,
            schema_name=schema_name,
            timeout=timeout,
        )
    if status["mode"] == "localai":
        return call_localai_json(
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
    def compact_text(value, limit=240):
        text = " ".join(str(value or "").split())
        return text[:limit]

    def compact_sources(rows, limit=3):
        return [
            {
                "label": compact_text(row.get("label"), 120),
                "detail": compact_text(row.get("detail"), 180),
            }
            for row in (rows or [])[:limit]
            if isinstance(row, dict) and row.get("label")
        ]

    def compact_pathways(payload):
        if not isinstance(payload, dict):
            return {}
        rows = []
        for row in (payload.get("pathways") or [])[:4]:
            if not isinstance(row, dict):
                continue
            rows.append({
                key: compact_text(row.get(key), 100)
                for key in ("primary_form_code", "pathway_name", "creates_licence_type", "checklist_code")
                if row.get(key)
            })
        return {"pathways": rows} if rows else {}

    safe_context = {
        "scope": context.get("scope"),
        "scope_label": context.get("scope_label"),
        "agent_label": context.get("agent_label"),
        "pending_application_count": context.get("pending_application_count", 0),
        "missing_review_count": context.get("missing_review_count", 0),
        "duplicate_review_count": context.get("duplicate_review_count", 0),
        "open_enquiry_count": context.get("open_enquiry_count", 0),
        "document_review_count": context.get("document_review_count", 0),
    }
    if context.get("assistant_memory"):
        safe_context["assistant_memory"] = [
            {
                "kind": compact_text(row.get("kind"), 50),
                "text": compact_text(row.get("text"), 220),
            }
            for row in context["assistant_memory"][:2]
            if isinstance(row, dict)
        ]
    if context.get("assistant_retrieval_sources"):
        safe_context["assistant_retrieval_sources"] = compact_sources(context["assistant_retrieval_sources"])
    if context.get("lapsed_renewal_summary"):
        safe_context["lapsed_renewal_summary"] = compact_text(context["lapsed_renewal_summary"], 320)
    if context.get("scope_policy"):
        safe_context["scope_policy"] = context["scope_policy"]
    if context.get("nursing_pathway_context"):
        safe_context["nursing_pathway_context"] = compact_pathways(context["nursing_pathway_context"])
    if context.get("nursing_cadre_context"):
        safe_context["nursing_cadre_context"] = {
            "dataflow_steps": [compact_text(item, 160) for item in (context["nursing_cadre_context"].get("dataflow_steps") or [])[:3]],
        }
    if isinstance(context.get("regulatory_ai_route"), dict):
        route = context["regulatory_ai_route"]
        agent = route.get("agent") if isinstance(route.get("agent"), dict) else {}
        safe_context["regulatory_ai_route"] = {
            "status": compact_text(route.get("status"), 30),
            "scope": compact_text(route.get("scope"), 30),
            "requested_domain": compact_text(route.get("requested_domain"), 30),
            "agent": {
                "id": compact_text(agent.get("id"), 60),
                "label": compact_text(agent.get("label"), 100),
            } if agent else None,
            "allowed_tool_names": [
                compact_text(tool.get("name"), 100)
                for tool in (route.get("allowed_tools") or [])[:5]
                if isinstance(tool, dict) and tool.get("name")
            ],
            "requires_citations": bool(route.get("requires_citations")),
            "requires_human_approval": bool(route.get("requires_human_approval")),
            "execution_mode": compact_text(route.get("execution_mode"), 40),
            "prohibited_capabilities": [
                compact_text(item, 80)
                for item in (route.get("prohibited_capabilities") or [])[:6]
            ],
        }
    return safe_context


def _safe_local_fallback_answer(response):
    """Keep a deterministic backup useful without duplicating large source payloads."""
    return {
        "title": str(response.get("title") or "")[:160],
        "answer": str(response.get("answer") or "")[:600],
        "bullets": [str(item)[:200] for item in (response.get("bullets") or [])[:4]],
        "links": list(response.get("links") or [])[:3],
        "suggestions": [str(item)[:160] for item in (response.get("suggestions") or [])[:3]],
    }


def maybe_generate_live_staff_response(user, question, context, local_response):
    from apps.dashboard.staff_ai_record_tools import build_staff_ai_record_lookup_tools

    status = ai_provider_status()
    local_response["ai_provider"] = status
    if local_response.pop("_skip_live_model", False):
        local_response["model_generated"] = False
        return local_response
    if status["mode"] not in {"google_adk", "openai", "ollama", "local_llm", "localai", "redis_worker"}:
        local_response["model_generated"] = False
        return local_response

    system_prompt = (
        "You are the Staff AI Assistant for a government regulatory workforce system. "
        "You may only answer questions about staff operations, applications, imports, "
        "data cleansing, duplicate review, reports, documents, payments, and role access. "
        "Do not provide general chat. Do not invent data. Do not expose private records. "
        "Use only the supplied scoped counts and the user's question. If the question asks "
        "for an action that changes data, explain that staff must review and approve in the platform. "
        "First determine whether the question belongs to Nursing Council or Medical Board scope. "
        "Do not mix Nursing Council analytics into Medical Board answers, and do not mix Medical Board records "
        "into Nursing Council answers unless the user has all-office admin scope. "
        "For direct registry record lookup requests, use only the approved read-only lookup tool and summarize "
        "only the fields returned by that tool. Never request or expose raw SQL, raw import payloads, DOB, "
        "contact details, full addresses, or payment amounts. "
        "For Nursing Council questions, use the supplied pathway and cadre/dataflow context so NC1/NC2/NC3, "
        "provisional, full licence, ATP, and cadre breakdown answers follow the platform source documents. "
        "Ground your answer in the supplied verified sources; never invent a source or URL. "
        "The platform attaches the verified source list after your response. "
        "The supplied regulatory_ai_route is a policy contract selected by the platform supervisor, not a permission to use arbitrary tools. "
        "Stay within its scope and listed read-only tool names; never use a prohibited capability or claim an agent changed a record. "
        "Every answer is decision support only: staff must verify the cited source and retain final approval, "
        "licensing, legal, clinical, and payment decisions. Treat lapsed-renewal and possible deceased signals as review candidates only."
    )
    user_payload = {
        "role": getattr(user, "role", ""),
        "department": getattr(user, "department", ""),
        "question": question,
        "scoped_context": _safe_staff_context(context),
        "local_fallback_answer": _safe_local_fallback_answer(local_response),
    }
    try:
        live_response = call_configured_ai_json(
            system_prompt=system_prompt,
            user_payload=user_payload,
            schema=STAFF_AI_RESPONSE_SCHEMA,
            schema_name="staff_ai_response",
            extra_tools=build_staff_ai_record_lookup_tools(user),
        )
    except AIProviderError as exc:
        local_response["ai_provider"] = {
            **status,
            "mode": "local_fallback",
            "label": "Local Offline Assistant",
            "detail": f"Live AI fallback used: {exc}",
        }
        local_response["model_generated"] = False
        return local_response

    live_response["ai_provider"] = status
    live_response["model_generated"] = True
    return live_response
