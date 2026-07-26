import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.test.utils import override_settings
from django.utils import timezone

from apps.dashboard.ai_evaluation import assess_staff_ai_response, cases_for_scope
from apps.dashboard.staff_ai import build_staff_ai_chat_response, build_staff_ai_context


class Command(BaseCommand):
    help = (
        "Evaluate a configured staff-AI model against non-sensitive Nursing, Medical, or Admin acceptance cases. "
        "It does not persist chat history or use feedback as training data."
    )

    def add_arguments(self, parser):
        parser.add_argument('--username', help='Existing staff username whose authorised scope will be evaluated.')
        parser.add_argument('--dry-run', action='store_true', help='List the cases for a scope without calling a model.')
        parser.add_argument('--scope', choices=('nursing', 'medical', 'all'), help='Scope to list with --dry-run.')
        parser.add_argument('--ollama-model', help='Temporarily evaluate this installed Ollama model; it does not change .env.')
        parser.add_argument('--local-only', action='store_true', help='Evaluate deterministic local guidance without a live generation model.')
        parser.add_argument('--skip-rag', action='store_true', help='Temporarily skip RAG to isolate model-generation checks when evaluating a candidate.')
        parser.add_argument('--strict', action='store_true', help='Exit non-zero unless every required safety and quality check passes.')
        parser.add_argument('--output', help='Optional JSON report path. Defaults to media/ai_evaluations/.')

    def handle(self, *args, **options):
        if options['dry_run']:
            scope = options['scope'] or 'nursing'
            for case in cases_for_scope(scope):
                self.stdout.write(f"{case.case_id}: {case.question}")
            self.stdout.write(self.style.SUCCESS(f"Listed {len(cases_for_scope(scope))} {scope} evaluation cases."))
            return

        username = (options['username'] or '').strip()
        if not username:
            raise CommandError('--username is required unless --dry-run is used.')
        user = get_user_model().objects.filter(username=username).first()
        if not user:
            raise CommandError(f'No staff user was found for username {username!r}.')

        scope = build_staff_ai_context(user, detailed=False).get('scope')
        if scope not in {'nursing', 'medical', 'all'}:
            raise CommandError('The selected user does not have a staff assistant scope that can be evaluated.')
        cases = cases_for_scope(scope)
        if not cases:
            raise CommandError(f'No evaluation cases are configured for {scope!r}.')

        override_values = {}
        if options['local_only']:
            override_values.update({
                'AI_ASSISTANT_PROVIDER': 'local',
                'AI_ASSISTANT_OLLAMA_ENABLED': False,
                'AI_ASSISTANT_LOCALAI_ENABLED': False,
                'AI_ASSISTANT_LOCAL_LLM_ENABLED': False,
                'AI_GOOGLE_ADK_ENABLED': False,
                # This is a fast deterministic safety baseline, not a model-promotion run.
                'AI_ASSISTANT_RAG_ENABLED': False,
            })
        elif options['ollama_model']:
            override_values.update({
                'AI_ASSISTANT_PROVIDER': 'ollama',
                'AI_ASSISTANT_OLLAMA_ENABLED': True,
                'AI_OLLAMA_MODEL': options['ollama_model'].strip(),
            })
        if options['skip_rag']:
            override_values['AI_ASSISTANT_RAG_ENABLED'] = False

        with override_settings(**override_values):
            report_cases = []
            for case in cases:
                response = build_staff_ai_chat_response(user, case.question, persist=False)
                assessment = assess_staff_ai_response(
                    case,
                    response,
                    require_live_model=not options['local_only'] and case.live_model_required,
                )
                report_cases.append(assessment)
                label = self.style.SUCCESS('PASS') if assessment['passed'] else self.style.ERROR('FAIL')
                self.stdout.write(f"{label} {case.case_id}")

        passed = sum(1 for item in report_cases if item['passed'])
        report = {
            'generated_at': timezone.now().isoformat(),
            'username': user.username,
            'scope': scope,
            'candidate_model': options['ollama_model'] or 'configured provider',
            'local_only': bool(options['local_only']),
            'rag_skipped': bool(options['skip_rag'] or options['local_only']),
            'pass_rate': round(passed / len(report_cases), 3),
            'passed': passed,
            'total': len(report_cases),
            'promotion_gate': 'Pass every scope, citation, privacy, and boundary check before changing the production model.',
            'cases': report_cases,
        }
        output_path = Path(options['output']) if options['output'] else (
            Path(settings.BASE_DIR) / 'media' / 'ai_evaluations' / f"staff-ai-{scope}-{timezone.now():%Y%m%d-%H%M%S}.json"
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding='utf-8')
        self.stdout.write(f"Evaluation report: {output_path}")
        self.stdout.write(f"Pass rate: {passed}/{len(report_cases)} ({report['pass_rate']:.1%})")
        if options['strict'] and passed != len(report_cases):
            raise CommandError('Model evaluation did not meet the all-check promotion gate.')
