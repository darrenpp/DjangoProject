"""Generate a governed, read-only aggregate ML planning snapshot.

This command is intentionally safe to schedule through an existing task
runner, Windows Task Scheduler, Celery beat, Airflow, or another approved
orchestrator.  It never writes to registry tables, trains on chats, or alters
an approval workflow.  Persisting the JSON report is opt-in and restricted to
the platform media directory.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.dashboard.medical_intelligence import build_medical_board_intelligence_context
from apps.dashboard.nursing_intelligence import build_nursing_workforce_intelligence_context
from apps.dashboard.workforce_forecasting import build_workforce_forecast_context


class Command(BaseCommand):
    help = (
        "Generate a local, read-only Nursing, Medical, or all-office aggregate workforce ML planning snapshot. "
        "It never writes registry records or trains on raw registry/chat data."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--scope",
            choices=("nursing", "medical", "all"),
            default="all",
            help="Regulatory aggregate scope to include. The other office is not queried for a scoped run.",
        )
        parser.add_argument(
            "--horizon-years",
            type=int,
            default=getattr(settings, "REGULATORY_ML_FORECAST_HORIZON_YEARS", 10),
            help="Requested planning horizon. The forecasting service applies its own validated bound.",
        )
        parser.add_argument(
            "--output",
            default="",
            help="Optional JSON filename or media-relative path. No file is written unless this is supplied.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Print the complete redacted aggregate snapshot to standard output.",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Exit non-zero if the requested Nursing retirement projection or Medical planning baseline is unavailable.",
        )

    @staticmethod
    def _output_path(value: str) -> Path:
        media_root = Path(settings.MEDIA_ROOT).resolve()
        requested = Path(value)
        path = requested if requested.is_absolute() else media_root / requested
        path = path.resolve()
        try:
            path.relative_to(media_root)
        except ValueError as exc:
            raise CommandError("--output must remain inside MEDIA_ROOT.") from exc
        if path.suffix.lower() != ".json":
            raise CommandError("--output must use a .json filename.")
        return path

    def handle(self, *args, **options):
        if not bool(getattr(settings, "REGULATORY_ML_ENABLED", True)):
            raise CommandError("REGULATORY_ML_ENABLED is False; no workforce ML snapshot was generated.")

        scope = options["scope"]
        kwargs = {"horizon_years": options["horizon_years"]}
        if scope == "nursing":
            kwargs["nursing_context"] = build_nursing_workforce_intelligence_context()
            kwargs["medical_context"] = {}
        elif scope == "medical":
            kwargs["nursing_context"] = {}
            kwargs["medical_context"] = build_medical_board_intelligence_context()

        snapshot = build_workforce_forecast_context(**kwargs)
        snapshot["requested_scope"] = scope
        snapshot["pipeline"] = {
            "read_only": True,
            "registry_writes": False,
            "raw_chat_training": False,
            "raw_registry_training": False,
            "operator_action_required": True,
            "schedule_note": (
                "This command may be scheduled after approved analytics refreshes. Review its aggregate source coverage and "
                "evaluation results before using a forecast in a policy or staffing process."
            ),
        }

        if options["output"]:
            output_path = self._output_path(options["output"])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=True), encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Wrote read-only aggregate ML snapshot: {output_path}"))

        nursing_available = bool((snapshot.get("nursing") or {}).get("retirement_projection", {}).get("available"))
        medical_available = bool((snapshot.get("medical") or {}).get("planning_readiness", {}).get("available"))
        if options["json"]:
            self.stdout.write(json.dumps(snapshot, indent=2, ensure_ascii=True))
        else:
            self.stdout.write(self.style.SUCCESS("Regulatory ML planning snapshot generated."))
            self.stdout.write(f"Scope: {scope}")
            self.stdout.write(f"Nursing retirement projection available: {'yes' if nursing_available else 'no'}")
            self.stdout.write(f"Medical planning baseline available: {'yes' if medical_available else 'no'}")
            self.stdout.write("No registry record, workflow, model, or chat data was changed.")

        if options["strict"]:
            unavailable = []
            if scope in {"nursing", "all"} and not nursing_available:
                unavailable.append("Nursing retirement projection")
            if scope in {"medical", "all"} and not medical_available:
                unavailable.append("Medical planning baseline")
            if unavailable:
                raise CommandError("Required governed planning input is unavailable: " + ", ".join(unavailable))
