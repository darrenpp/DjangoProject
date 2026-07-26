from importlib.util import find_spec

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.dashboard.ai_provider import AIProviderError, ai_provider_status, get_ollama_models, get_localai_models
from apps.dashboard.ai_worker import redis_client


class Command(BaseCommand):
    help = "Check the configured staff AI provider and local free GPT model availability."

    def add_arguments(self, parser):
        parser.add_argument(
            "--timeout",
            type=int,
            default=2,
            help="Seconds to wait for local model server health checks.",
        )

    def handle(self, *args, **options):
        status = ai_provider_status()
        self.stdout.write(f"Configured provider: {status['configured_provider']}")
        self.stdout.write(f"Active mode: {status['mode']}")
        self.stdout.write(f"Label: {status['label']}")
        self.stdout.write(f"Detail: {status['detail']}")
        rag = status.get("rag", {})
        self.stdout.write(f"RAG enabled: {'yes' if rag.get('enabled') else 'no'}")
        self.stdout.write(f"RAG ready: {'yes' if rag.get('ready') else 'no'}")
        self.stdout.write(f"RAG index stale: {'yes' if rag.get('index_stale') else 'no'}")
        self.stdout.write(f"RAG detail: {rag.get('detail', 'not configured')}")
        if rag.get("enabled"):
            self.stdout.write(f"Embedding model: {rag.get('embedding_model') or 'not configured'}")
            self.stdout.write(f"Embedding local-only: {'yes' if rag.get('embedding_local_files_only') else 'no'}")
            self.stdout.write(f"Vector backend: {rag.get('vector_backend') or 'local_json'}")
            self.stdout.write(f"Index path: {rag.get('index_path') or 'not configured'}")
            self.stdout.write(f"Indexed documents: {rag.get('index_document_count', 0)}")
            self.stdout.write(f"sentence-transformers installed: {'yes' if rag.get('sentence_transformers_installed') else 'no'}")
            self.stdout.write(f"chromadb installed: {'yes' if rag.get('chromadb_installed') else 'no'}")

        self.stdout.write(f"Regulatory aggregate ML enabled: {'yes' if getattr(settings, 'REGULATORY_ML_ENABLED', True) else 'no'}")
        self.stdout.write(f"Regulatory ML scikit-learn enabled: {'yes' if getattr(settings, 'REGULATORY_ML_USE_SCIKIT_LEARN', True) else 'no'}")
        self.stdout.write(f"scikit-learn installed: {'yes' if find_spec('sklearn') else 'no'}")
        self.stdout.write(f"Raw registry/chat ML training enabled: {'yes' if getattr(settings, 'REGULATORY_ML_ALLOW_TRAINING', False) else 'no'}")
        self.stdout.write(f"Aggregate ML cache seconds: {getattr(settings, 'REGULATORY_ML_CACHE_SECONDS', 300)}")
        self.stdout.write(f"Aggregate ML forecast horizon: {getattr(settings, 'REGULATORY_ML_FORECAST_HORIZON_YEARS', 10)} years")

        if status["configured_provider"] == "google_adk":
            self.stdout.write(f"Google ADK model: {status['google_adk_model'] or 'not configured'}")
            self.stdout.write(f"google-adk package installed: {'yes' if status['google_adk_installed'] else 'no'}")
            self.stdout.write(f"GOOGLE_API_KEY configured: {'yes' if status['google_api_key_configured'] else 'no'}")
            if status["google_adk_ready"]:
                self.stdout.write(self.style.SUCCESS("Google ADK is ready for live assistant responses."))
            else:
                self.stdout.write(self.style.WARNING("Google ADK is not ready; the platform will use the safe local fallback assistant."))
            return

        if status["configured_provider"] == "redis_worker":
            self.stdout.write(f"Redis worker enabled: {'yes' if status['redis_worker_enabled'] else 'no'}")
            self.stdout.write(f"Redis URL configured: {'yes' if status['redis_worker_url_configured'] else 'no'}")
            self.stdout.write(f"Redis queue: {status['redis_worker_queue'] or 'not configured'}")
            self.stdout.write(f"Worker model provider: {status['redis_worker_model_provider'] or 'not configured'}")
            self.stdout.write(f"Worker model configured: {'yes' if status['redis_worker_model_configured'] else 'no'}")
            self.stdout.write(f"Worker detail: {status['redis_worker_detail'] or status['detail']}")
            try:
                redis_client(socket_timeout=options["timeout"]).ping()
            except Exception as exc:
                self.stdout.write(self.style.WARNING(f"Redis is not reachable yet: {exc}"))
                self.stdout.write(self.style.WARNING("Start Redis and run `python manage.py run_ai_worker` before relying on queued live AI responses."))
                return
            if status["redis_worker_ready"]:
                self.stdout.write(self.style.SUCCESS("Redis is reachable. Start or keep running `python manage.py run_ai_worker`."))
            else:
                self.stdout.write(self.style.WARNING("Redis is reachable, but worker mode is not fully configured."))
            return

        if status["configured_provider"] == "ollama":
            self.stdout.write(f"Ollama URL: {status['ollama_base_url']}")
            self.stdout.write(f"Ollama model: {status['ollama_model'] or 'not configured'}")
            try:
                models = get_ollama_models(timeout=options["timeout"])
            except AIProviderError as exc:
                self.stdout.write(self.style.WARNING(str(exc)))
                self.stdout.write(self.style.WARNING("Ollama is not reachable yet. Start Ollama and pull a model before enabling live GPT chats."))
                return
            if models:
                self.stdout.write(self.style.SUCCESS("Ollama is reachable. Installed models:"))
                for model in models:
                    self.stdout.write(f"- {model}")
            else:
                self.stdout.write(self.style.WARNING("Ollama is reachable, but no local models are installed."))
            return

        if status["configured_provider"] == "localai":
            self.stdout.write(f"LocalAI URL: {status['localai_base_url'] or 'not configured'}")
            self.stdout.write(f"LocalAI model: {status['localai_model'] or 'not configured'}")
            try:
                models = get_localai_models(timeout=options["timeout"])
            except AIProviderError as exc:
                self.stdout.write(self.style.WARNING(str(exc)))
                self.stdout.write(self.style.WARNING("LocalAI is not reachable yet. Start LocalAI and load a model before enabling live GPT chats."))
                return
            if models:
                self.stdout.write(self.style.SUCCESS("LocalAI is reachable. Installed models:"))
                for model in models:
                    self.stdout.write(f"- {model}")
            else:
                self.stdout.write(self.style.WARNING("LocalAI is reachable, but no local models are installed."))
            return

        if status["mode"] == "local":
            self.stdout.write(self.style.SUCCESS("The safe local rule-based assistant is active. No external API or model server is being used."))
        elif status["mode"] == "local_fallback":
            self.stdout.write(self.style.WARNING("The platform is using the safe local fallback assistant."))
        else:
            self.stdout.write(self.style.SUCCESS("A live model provider is configured."))
