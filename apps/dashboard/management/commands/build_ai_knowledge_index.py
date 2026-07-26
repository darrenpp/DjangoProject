from django.core.management.base import BaseCommand, CommandError

from apps.dashboard.assistant_rag import (
    AssistantRAGUnavailable,
    build_vector_index,
    collect_knowledge_documents,
    rag_status,
)


class Command(BaseCommand):
    help = "Build the local staff assistant RAG knowledge index from platform data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Collect and count source documents without loading the embedding model or writing an index.",
        )

    def handle(self, *args, **options):
        documents = collect_knowledge_documents()
        self.stdout.write(f"Collected knowledge documents: {len(documents)}")
        if options["dry_run"]:
            status = rag_status()
            self.stdout.write(f"RAG enabled: {'yes' if status['enabled'] else 'no'}")
            self.stdout.write(f"Index stale: {'yes' if status['index_stale'] else 'no'}")
            self.stdout.write(f"Embedding package installed: {'yes' if status['sentence_transformers_installed'] else 'no'}")
            self.stdout.write(f"Embedding model: {status['embedding_model']}")
            self.stdout.write(f"Index path: {status['index_path']}")
            return

        try:
            result = build_vector_index()
        except AssistantRAGUnavailable as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS("Assistant knowledge index built."))
        self.stdout.write(f"Documents indexed: {result['document_count']}")
        self.stdout.write(f"Embedding model: {result['embedding_model']}")
        self.stdout.write(f"Vector backend: {result['vector_backend']}")
        self.stdout.write(f"Index path: {result['index_path']}")
        self.stdout.write("Index freshness: current")
        if result["vector_backend"] == "chroma":
            self.stdout.write(f"Chroma synced: {'yes' if result['chroma_synced'] else 'no'}")
