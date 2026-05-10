from django.core.management.base import BaseCommand

from apps.documents.models import DocumentFolder


class Command(BaseCommand):
    help = "Create the default root folders for the document repository."

    ROOT_FOLDERS = [
        ("general", "General Registry"),
        ("nursing", "Nursing Council Repository"),
        ("medical", "Medical Board Repository"),
    ]

    CHILD_FOLDERS = {
        "nursing": [
            "Applications",
            "Receipts",
            "Qualifications",
            "Competency Evidence",
            "Overseas Applications",
            "Temporary Licences",
            "Renewals",
            "Deceased Notifications",
            "Policies and Standards",
            "Historical Imports",
            "Data Cleansing Evidence",
        ],
        "medical": [
            "Applications",
            "Receipts",
            "CHW Records",
            "Doctor Records",
            "Policies and Standards",
            "Historical Imports",
            "Data Cleansing Evidence",
        ],
        "general": [
            "Shared Policies",
            "Training Materials",
            "System Governance",
        ],
    }

    def handle(self, *args, **options):
        created = 0
        roots = {}
        for scope, name in self.ROOT_FOLDERS:
            folder, was_created = DocumentFolder.objects.get_or_create(
                office_scope=scope,
                parent=None,
                name=name,
                defaults={
                    "description": f"Root repository folder for the {name.lower()}.",
                    "is_active": True,
                },
            )
            roots[scope] = folder
            created += int(was_created)

        child_created = 0
        for scope, child_names in self.CHILD_FOLDERS.items():
            root = roots.get(scope)
            if not root:
                continue
            for child_name in child_names:
                _, was_created = DocumentFolder.objects.get_or_create(
                    office_scope=scope,
                    parent=root,
                    name=child_name,
                    defaults={
                        "description": f"{child_name} folder for {root.name}.",
                        "is_active": True,
                    },
                )
                child_created += int(was_created)

        self.stdout.write(self.style.SUCCESS(
            "Document repository bootstrap complete. "
            f"Root folders created: {created}. Child folders created: {child_created}."
        ))
