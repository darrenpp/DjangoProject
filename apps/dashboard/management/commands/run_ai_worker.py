from django.core.management.base import BaseCommand, CommandError

from apps.dashboard.ai_worker import (
    decode_worker_job,
    process_worker_job,
    redis_client,
    redis_worker_settings,
)


class Command(BaseCommand):
    help = "Run the Redis-backed staff AI worker."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Process one queued job and exit.")
        parser.add_argument("--timeout", type=int, default=5, help="Seconds to block while waiting for a job.")

    def handle(self, *args, **options):
        config = redis_worker_settings()
        if not config["enabled"]:
            raise CommandError("AI_REDIS_WORKER_ENABLED must be true before starting the AI worker.")
        client = redis_client()
        self.stdout.write(self.style.SUCCESS(f"AI worker listening on Redis queue '{config['queue']}'"))

        while True:
            item = client.blpop(config["queue"], timeout=options["timeout"])
            if not item:
                if options["once"]:
                    self.stdout.write("No queued AI job found.")
                    return
                continue
            _queue_name, raw_payload = item
            try:
                job = decode_worker_job(raw_payload)
                result = process_worker_job(job)
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"AI worker failed to process a job: {exc}"))
                if options["once"]:
                    raise
                continue
            if result.get("ok"):
                self.stdout.write(f"Processed AI job {result['job_id']}")
            else:
                self.stderr.write(self.style.WARNING(f"AI job {result['job_id']} failed: {result.get('error', '')}"))
            if options["once"]:
                return
