import json
import uuid
import urllib.error
import urllib.request

from django.conf import settings


class AIWorkerError(RuntimeError):
    pass


def _redis_module():
    try:
        import redis
    except ImportError as exc:
        raise AIWorkerError("The redis Python package is not installed.") from exc
    return redis


def redis_worker_settings():
    return {
        "enabled": bool(getattr(settings, "AI_REDIS_WORKER_ENABLED", False)),
        "url": str(getattr(settings, "AI_REDIS_URL", "") or "").strip(),
        "queue": str(getattr(settings, "AI_REDIS_WORKER_QUEUE", "staff_ai_requests") or "staff_ai_requests").strip(),
        "result_prefix": str(getattr(settings, "AI_REDIS_WORKER_RESULT_PREFIX", "staff_ai_result:") or "staff_ai_result:").strip(),
        "timeout": int(getattr(settings, "AI_REDIS_WORKER_TIMEOUT_SECONDS", 25)),
        "result_ttl": int(getattr(settings, "AI_REDIS_WORKER_RESULT_TTL_SECONDS", 120)),
        "socket_timeout": int(getattr(settings, "AI_REDIS_WORKER_SOCKET_TIMEOUT_SECONDS", 5)),
        "model_provider": str(getattr(settings, "AI_REDIS_WORKER_MODEL_PROVIDER", "local") or "local").lower(),
    }


def redis_worker_available():
    config = redis_worker_settings()
    if not config["enabled"] or not config["url"] or not config["queue"]:
        return False
    try:
        _redis_module()
    except AIWorkerError:
        return False
    return True


def redis_worker_status():
    config = redis_worker_settings()
    model_provider = config["model_provider"]
    model_config = redis_worker_model_config(model_provider)
    return {
        **config,
        "redis_package_available": _redis_package_available(),
        "configured": redis_worker_available(),
        "model_configured": model_config["configured"],
        "model_detail": model_config["detail"],
    }


def _redis_package_available():
    try:
        _redis_module()
    except AIWorkerError:
        return False
    return True


def redis_client(socket_timeout=None):
    config = redis_worker_settings()
    if not config["url"]:
        raise AIWorkerError("AI_REDIS_URL is not configured.")
    redis = _redis_module()
    timeout = socket_timeout or config["socket_timeout"]
    return redis.Redis.from_url(config["url"], socket_timeout=timeout, socket_connect_timeout=timeout)


def submit_redis_ai_request(*, system_prompt, user_payload, schema, schema_name, timeout=None):
    config = redis_worker_settings()
    if not redis_worker_available():
        raise AIWorkerError("Redis worker mode is not enabled or Redis is not configured.")
    job_id = uuid.uuid4().hex
    result_key = f"{config['result_prefix']}{job_id}"
    request_payload = {
        "job_id": job_id,
        "system_prompt": system_prompt,
        "user_payload": user_payload,
        "schema": schema,
        "schema_name": schema_name,
    }
    client = redis_client()
    client.rpush(config["queue"], json.dumps(request_payload, ensure_ascii=True, default=str))
    client.expire(result_key, config["result_ttl"])
    response = client.blpop(result_key, timeout=timeout or config["timeout"])
    if not response:
        raise AIWorkerError("Redis AI worker timed out before returning a response.")
    _key, raw_payload = response
    client.delete(result_key)
    try:
        payload = json.loads(raw_payload.decode("utf-8") if isinstance(raw_payload, bytes) else raw_payload)
    except (TypeError, ValueError) as exc:
        raise AIWorkerError("Redis AI worker returned invalid JSON.") from exc
    if not payload.get("ok"):
        raise AIWorkerError(payload.get("error") or "Redis AI worker failed.")
    return payload.get("response") or {}


def publish_worker_result(job_id, payload):
    config = redis_worker_settings()
    result_key = f"{config['result_prefix']}{job_id}"
    client = redis_client()
    client.rpush(result_key, json.dumps(payload, ensure_ascii=True, default=str))
    client.expire(result_key, config["result_ttl"])


def decode_worker_job(raw_payload):
    if isinstance(raw_payload, bytes):
        raw_payload = raw_payload.decode("utf-8")
    try:
        job = json.loads(raw_payload)
    except (TypeError, ValueError) as exc:
        raise AIWorkerError("Worker job was not valid JSON.") from exc
    if not job.get("job_id"):
        raise AIWorkerError("Worker job did not include a job_id.")
    return job


def process_worker_job(job):
    job_id = job["job_id"]
    try:
        response = call_worker_model_json(
            system_prompt=job.get("system_prompt", ""),
            user_payload=job.get("user_payload") or {},
            schema=job.get("schema") or {},
            schema_name=job.get("schema_name") or "staff_ai_response",
        )
        publish_worker_result(job_id, {"ok": True, "response": response})
        return {"ok": True, "job_id": job_id}
    except Exception as exc:
        publish_worker_result(job_id, {"ok": False, "error": str(exc)})
        return {"ok": False, "job_id": job_id, "error": str(exc)}


def redis_worker_model_config(provider=None):
    provider = (provider or redis_worker_settings()["model_provider"]).lower()
    if provider == "local":
        return {"configured": True, "detail": "Worker returns the platform local fallback answer."}
    if provider == "ollama":
        model = str(getattr(settings, "AI_REDIS_WORKER_MODEL", "") or getattr(settings, "AI_OLLAMA_MODEL", "") or "").strip()
        base_url = str(getattr(settings, "AI_REDIS_WORKER_MODEL_BASE_URL", "") or getattr(settings, "AI_OLLAMA_BASE_URL", "") or "").strip()
        return {
            "configured": bool(model and base_url),
            "detail": "Ollama worker model configured." if model and base_url else "Ollama worker requires model and base URL.",
        }
    if provider == "localai":
        model = str(getattr(settings, "AI_REDIS_WORKER_MODEL", "") or getattr(settings, "AI_LOCALAI_MODEL", "") or "").strip()
        base_url = str(getattr(settings, "AI_REDIS_WORKER_MODEL_BASE_URL", "") or getattr(settings, "AI_LOCALAI_BASE_URL", "") or "").strip()
        return {
            "configured": bool(model and base_url),
            "detail": "LocalAI worker model configured." if model and base_url else "LocalAI worker requires model and base URL.",
        }
    if provider == "local_llm":
        model = str(getattr(settings, "AI_REDIS_WORKER_MODEL", "") or getattr(settings, "AI_LOCAL_LLM_MODEL", "") or "").strip()
        base_url = str(getattr(settings, "AI_REDIS_WORKER_MODEL_BASE_URL", "") or getattr(settings, "AI_LOCAL_LLM_BASE_URL", "") or "").strip()
        return {
            "configured": bool(model and base_url),
            "detail": "Private local worker model configured." if model and base_url else "Private local worker requires model and base URL.",
        }
    if provider == "openai":
        model = str(getattr(settings, "AI_REDIS_WORKER_MODEL", "") or getattr(settings, "OPENAI_MODEL", "") or "").strip()
        api_key = str(getattr(settings, "AI_REDIS_WORKER_MODEL_API_KEY", "") or getattr(settings, "OPENAI_API_KEY", "") or "").strip()
        return {
            "configured": bool(model and api_key),
            "detail": "OpenAI worker model configured." if model and api_key else "OpenAI worker requires model and API key.",
        }
    return {"configured": False, "detail": f"Unsupported Redis worker model provider: {provider}."}


def call_worker_model_json(*, system_prompt, user_payload, schema, schema_name):
    provider = redis_worker_settings()["model_provider"]
    if provider == "local":
        fallback = user_payload.get("local_fallback_answer") if isinstance(user_payload, dict) else None
        if fallback:
            return fallback
        raise AIWorkerError("No local fallback answer was supplied to the worker.")
    if provider == "ollama":
        return _call_ollama_worker_json(system_prompt=system_prompt, user_payload=user_payload, schema=schema, schema_name=schema_name)
    if provider in {"localai", "local_llm", "openai"}:
        return _call_openai_compatible_worker_json(
            provider=provider,
            system_prompt=system_prompt,
            user_payload=user_payload,
            schema=schema,
            schema_name=schema_name,
        )
    raise AIWorkerError(f"Unsupported Redis worker model provider: {provider}.")


def _json_from_model_text(text, provider_label):
    text = str(text or "").strip()
    if not text:
        raise AIWorkerError(f"{provider_label} response was empty.")
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise AIWorkerError(f"{provider_label} response was not valid JSON.") from exc


def _request_json(endpoint, payload, headers, timeout):
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise AIWorkerError(f"Worker model request failed: {exc}") from exc


def _call_openai_compatible_worker_json(*, provider, system_prompt, user_payload, schema, schema_name):
    timeout = int(getattr(settings, "AI_REDIS_WORKER_MODEL_TIMEOUT_SECONDS", 30))
    model = str(getattr(settings, "AI_REDIS_WORKER_MODEL", "") or "").strip()
    base_url = str(getattr(settings, "AI_REDIS_WORKER_MODEL_BASE_URL", "") or "").rstrip("/")
    api_key = str(getattr(settings, "AI_REDIS_WORKER_MODEL_API_KEY", "") or "").strip()

    if provider == "openai":
        model = model or str(getattr(settings, "OPENAI_MODEL", "") or "").strip()
        api_key = api_key or str(getattr(settings, "OPENAI_API_KEY", "") or "").strip()
        endpoint = base_url or "https://api.openai.com/v1/chat/completions"
    elif provider == "localai":
        model = model or str(getattr(settings, "AI_LOCALAI_MODEL", "") or "").strip()
        base_url = base_url or str(getattr(settings, "AI_LOCALAI_BASE_URL", "") or "").rstrip("/")
        api_key = api_key or str(getattr(settings, "AI_LOCALAI_API_KEY", "") or "").strip()
        endpoint = base_url if base_url.endswith("/v1/chat/completions") else f"{base_url}/v1/chat/completions"
    else:
        model = model or str(getattr(settings, "AI_LOCAL_LLM_MODEL", "") or "").strip()
        base_url = base_url or str(getattr(settings, "AI_LOCAL_LLM_BASE_URL", "") or "").rstrip("/")
        api_key = api_key or str(getattr(settings, "AI_LOCAL_LLM_API_KEY", "") or "").strip()
        endpoint = base_url if base_url.endswith("/v1/chat/completions") else f"{base_url}/v1/chat/completions"

    if not model or not endpoint:
        raise AIWorkerError(f"{provider} worker model is not fully configured.")

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
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
    raw_payload = _request_json(endpoint, payload, headers, timeout)
    try:
        response_text = raw_payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AIWorkerError(f"{provider} worker response did not include chat content.") from exc
    return _json_from_model_text(response_text, provider)


def _call_ollama_worker_json(*, system_prompt, user_payload, schema, schema_name):
    timeout = int(getattr(settings, "AI_REDIS_WORKER_MODEL_TIMEOUT_SECONDS", 30))
    base_url = str(getattr(settings, "AI_REDIS_WORKER_MODEL_BASE_URL", "") or getattr(settings, "AI_OLLAMA_BASE_URL", "") or "").rstrip("/")
    model = str(getattr(settings, "AI_REDIS_WORKER_MODEL", "") or getattr(settings, "AI_OLLAMA_MODEL", "") or "").strip()
    if not base_url or not model:
        raise AIWorkerError("Ollama worker model is not fully configured.")
    raw_payload = _request_json(
        f"{base_url}/api/chat",
        {
            "model": model,
            "stream": False,
            "format": schema,
            "options": {"temperature": 0},
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
        },
        {"Content-Type": "application/json"},
        timeout,
    )
    response_text = ""
    if isinstance(raw_payload.get("message"), dict):
        response_text = raw_payload["message"].get("content", "")
    if not response_text:
        response_text = raw_payload.get("response", "")
    return _json_from_model_text(response_text, "Ollama worker")
