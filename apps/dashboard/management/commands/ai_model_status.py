from django.core.management.base import BaseCommand

from apps.dashboard.ai_provider import AIProviderError, ai_provider_status, get_ollama_models


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

        if status["mode"] == "local":
            self.stdout.write(self.style.SUCCESS("The safe local rule-based assistant is active. No external API or model server is being used."))
        elif status["mode"] == "local_fallback":
            self.stdout.write(self.style.WARNING("The platform is using the safe local fallback assistant."))
        else:
            self.stdout.write(self.style.SUCCESS("A live model provider is configured."))
