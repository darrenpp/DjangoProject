from django.core.management.base import BaseCommand

from apps.workforce.services.nursing_council_workflows import ensure_nursing_council_configuration


class Command(BaseCommand):
    help = "Seed PNG Nursing Council pathway, form, checklist, fee, policy, and declaration configuration."

    def handle(self, *args, **options):
        summary = ensure_nursing_council_configuration()
        self.stdout.write(self.style.SUCCESS("Seeded Nursing Council workflow configuration"))
        self.stdout.write(f"Regulatory body: {summary['regulatory_body']}")
        self.stdout.write(f"Pathways: {summary['pathways']}")
        self.stdout.write(f"Forms: {summary['forms']}")
        self.stdout.write(f"Document requirements: {summary['document_requirements']}")
        self.stdout.write(f"Fee schedules: {summary['fees']}")
        self.stdout.write(f"Declarations: {summary['declarations']}")
