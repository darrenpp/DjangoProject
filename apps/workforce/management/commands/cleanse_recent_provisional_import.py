from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.common.models import DuplicateReviewQueue
from apps.workforce.models import Application, MissingDataReview, NursingProfessional, Qualification


IMPORT_MARKER = "Provional_Cleansed_data2009_2026.xlsx"
IMPORT_SOURCE_LABEL = "Provisional licence import cleanup"
PLACEHOLDER_VALUES = {"", "-", "--", "N/A", "NA", "NONE", "NULL", "NAN", "NAT", "UNKNOWN", "TBA", "TBD", "..."}
STRING_FIELDS = (
    "first_name",
    "middle_name",
    "last_name",
    "applicant_type",
    "registration_no",
    "gender",
    "marital_status",
    "nationality",
    "primary_phone",
    "email",
    "province",
    "registration_number",
    "qualification_level",
)
NULL_WHEN_EMPTY_FIELDS = {"registration_number"}
REQUIRED_FIELDS = (
    ("first_name", "First name"),
    ("last_name", "Last name"),
    ("registration_no", "Registration number"),
    ("email", "Email address"),
    ("primary_phone", "Phone number"),
    ("gender", "Gender"),
    ("date_of_birth", "Date of birth"),
    ("province", "Province"),
    ("qualification_level", "Qualification"),
    ("license_expiry_date", "Licence expiry date"),
)


def normalize_text(value):
    return " ".join(str(value or "").strip().split())


def normalize_key(value):
    return normalize_text(value).casefold()


def clean_value(value):
    text = normalize_text(value)
    return "" if text.upper() in PLACEHOLDER_VALUES else text


def missing(value):
    if value is None:
        return True
    if isinstance(value, str):
        return clean_value(value) == ""
    return False


class Command(BaseCommand):
    help = (
        "Clean the recently imported provisional licence rows by removing exact duplicate "
        "professional records and opening missing-data reviews for unresolved blank cells."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Apply duplicate removal and missing-review updates.")
        parser.add_argument("--report-dir", default="docs/reports", help="Directory for cleanup reports.")
        parser.add_argument("--marker", default=IMPORT_MARKER, help="Application reviewer note marker for the import.")

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        report_dir = Path(options["report_dir"])
        report_dir.mkdir(parents=True, exist_ok=True)
        marker = options["marker"]
        timestamp = timezone.localtime().strftime("%Y%m%d_%H%M%S")

        professional_ct = ContentType.objects.get_for_model(NursingProfessional)
        applications = Application.objects.filter(
            content_type=professional_ct,
            form_code="NC1",
            reviewer_notes__icontains=marker,
        ).only("id", "object_id", "reviewer_notes")
        scoped_ids = list(applications.values_list("object_id", flat=True))
        professionals = list(NursingProfessional.objects.filter(id__in=scoped_ids).order_by("id"))

        duplicate_groups = self._find_duplicate_groups(professional_ct, professionals)
        missing_distribution, missing_rows = self._missing_summary(professionals)

        normalized_fields = 0
        deleted_professionals = 0
        missing_reviews_created = 0
        missing_reviews_updated = 0
        resolved_reviews = 0

        if apply_changes:
            with transaction.atomic():
                normalized_fields = self._normalize_professionals(professionals)
                deleted_professionals = self._delete_duplicates(professional_ct, duplicate_groups)
                remaining = list(NursingProfessional.objects.filter(id__in=scoped_ids).order_by("id"))
                missing_reviews_created, missing_reviews_updated, resolved_reviews = self._upsert_missing_reviews(
                    professional_ct,
                    remaining,
                )
                missing_distribution, missing_rows = self._missing_summary(remaining)

        summary = {
            "generated_at": timezone.localtime().isoformat(),
            "apply_changes": apply_changes,
            "import_marker": marker,
            "scoped_professionals": len(professionals),
            "duplicate_groups": len(duplicate_groups),
            "duplicate_rows_to_delete": sum(len(group["delete_ids"]) for group in duplicate_groups),
            "duplicate_rows_deleted": deleted_professionals,
            "normalized_text_fields": normalized_fields,
            "missing_review_rows": len(missing_rows),
            "missing_reviews_created": missing_reviews_created,
            "missing_reviews_updated": missing_reviews_updated,
            "missing_reviews_resolved": resolved_reviews,
            "missing_field_distribution": dict(missing_distribution),
            "duplicate_examples": duplicate_groups[:25],
            "missing_examples": missing_rows[:50],
        }
        paths = self._write_reports(report_dir, timestamp, summary)

        self.stdout.write(self.style.SUCCESS("Recent provisional import cleanup complete."))
        self.stdout.write(
            f"Scoped professionals: {summary['scoped_professionals']}. "
            f"Duplicate groups: {summary['duplicate_groups']}; "
            f"rows deleted: {summary['duplicate_rows_deleted']}."
        )
        self.stdout.write(
            f"Missing-data reviews: {summary['missing_review_rows']} rows still need source verification. "
            f"Created: {missing_reviews_created}; updated: {missing_reviews_updated}; resolved: {resolved_reviews}."
        )
        self.stdout.write(f"Report written to: {paths['markdown']}")
        self.stdout.write(f"JSON summary written to: {paths['json']}")
        self.stdout.write(f"CSV detail written to: {paths['csv']}")

    def _qualification_signature(self, professional_ct, professional):
        qualification = (
            Qualification.objects.filter(content_type=professional_ct, object_id=professional.id)
            .select_related("institution")
            .order_by("id")
            .first()
        )
        if not qualification:
            return ("", "", "")
        institution_name = qualification.institution.name if qualification.institution else qualification.institution_name
        return (
            normalize_key(qualification.qualification_name),
            str(qualification.completion_year or ""),
            normalize_key(institution_name),
        )

    def _duplicate_key(self, professional_ct, professional):
        return (
            normalize_key(professional.first_name),
            normalize_key(professional.last_name),
            str(professional.date_issued or ""),
            normalize_key(professional.applicant_type),
            normalize_key(professional.qualification_level),
            *self._qualification_signature(professional_ct, professional),
        )

    def _find_duplicate_groups(self, professional_ct, professionals):
        groups = defaultdict(list)
        for professional in professionals:
            key = self._duplicate_key(professional_ct, professional)
            if key[0] and key[1]:
                groups[key].append(professional)

        duplicate_groups = []
        for members in groups.values():
            if len(members) < 2:
                continue
            members.sort(key=lambda item: item.id)
            keep = members[0]
            delete = members[1:]
            duplicate_groups.append(
                {
                    "keep_id": keep.id,
                    "keep_registration_no": keep.registration_no,
                    "delete_ids": [item.id for item in delete],
                    "delete_registration_nos": [item.registration_no for item in delete],
                    "full_name": f"{keep.first_name} {keep.last_name}".strip(),
                    "date_issued": keep.date_issued.isoformat() if keep.date_issued else "",
                    "qualification": keep.qualification_level,
                }
            )
        return duplicate_groups

    def _normalize_professionals(self, professionals):
        updated_fields = 0
        max_lengths = {
            field.name: getattr(field, "max_length", None)
            for field in NursingProfessional._meta.fields
            if field.name in STRING_FIELDS
        }
        for professional in professionals:
            changed = []
            for field_name in STRING_FIELDS:
                current = getattr(professional, field_name, "")
                cleaned = clean_value(current)
                max_length = max_lengths.get(field_name)
                if max_length:
                    cleaned = cleaned[:max_length]
                if field_name in NULL_WHEN_EMPTY_FIELDS and cleaned == "":
                    cleaned = None
                if current != cleaned:
                    setattr(professional, field_name, cleaned)
                    changed.append(field_name)
            if changed:
                professional.save(update_fields=[*changed, "updated_at"])
                updated_fields += len(changed)
        return updated_fields

    def _delete_duplicates(self, professional_ct, duplicate_groups):
        deleted_count = 0
        for group in duplicate_groups:
            delete_ids = group["delete_ids"]
            if not delete_ids:
                continue
            Application.objects.filter(content_type=professional_ct, object_id__in=delete_ids).delete()
            Qualification.objects.filter(content_type=professional_ct, object_id__in=delete_ids).delete()
            MissingDataReview.objects.filter(content_type=professional_ct, object_id__in=delete_ids).delete()
            DuplicateReviewQueue.objects.filter(content_type=professional_ct, object_id__in=delete_ids).delete()
            deleted_count += NursingProfessional.objects.filter(id__in=delete_ids).delete()[0]
        return deleted_count

    def _missing_fields_for(self, professional):
        return [label for field_name, label in REQUIRED_FIELDS if missing(getattr(professional, field_name, None))]

    def _missing_summary(self, professionals):
        distribution = Counter()
        rows = []
        for professional in professionals:
            fields = self._missing_fields_for(professional)
            if not fields:
                continue
            distribution.update(fields)
            rows.append(
                {
                    "id": professional.id,
                    "registration_no": professional.registration_no or "",
                    "full_name": f"{professional.first_name} {professional.last_name}".strip(),
                    "missing_fields": fields,
                }
            )
        return distribution, rows

    def _severity(self, fields):
        if len(fields) >= 5:
            return "high"
        if len(fields) >= 3:
            return "medium"
        return "low"

    def _upsert_missing_reviews(self, professional_ct, professionals):
        created = 0
        updated = 0
        resolved = 0
        for professional in professionals:
            fields = self._missing_fields_for(professional)
            if fields:
                _review, was_created = MissingDataReview.objects.update_or_create(
                    content_type=professional_ct,
                    object_id=professional.id,
                    defaults={
                        "full_name": f"{professional.first_name} {professional.last_name}".strip()[:255],
                        "registration_no": (professional.registration_no or "")[:100],
                        "email": professional.email or "",
                        "professional_type": "Nursing Professional",
                        "missing_fields": fields,
                        "missing_count": len(fields),
                        "source_label": IMPORT_SOURCE_LABEL,
                        "status": "under_review",
                        "severity": self._severity(fields),
                        "resolved_at": None,
                    },
                )
                if was_created:
                    created += 1
                else:
                    updated += 1
            else:
                resolved += MissingDataReview.objects.filter(
                    content_type=professional_ct,
                    object_id=professional.id,
                ).exclude(status="resolved").update(
                    status="resolved",
                    missing_fields=[],
                    missing_count=0,
                    resolved_at=timezone.now(),
                )
        return created, updated, resolved

    def _write_reports(self, report_dir, timestamp, summary):
        json_path = report_dir / f"recent_provisional_import_cleanup_{timestamp}.json"
        md_path = report_dir / f"recent_provisional_import_cleanup_{timestamp}.md"
        csv_path = report_dir / f"recent_provisional_import_missing_{timestamp}.csv"

        json_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
        md_path.write_text(
            "\n".join(
                [
                    "# Recent Provisional Import Cleanup",
                    "",
                    f"Generated at: {summary['generated_at']}",
                    f"Applied changes: {summary['apply_changes']}",
                    f"Scoped professionals: {summary['scoped_professionals']}",
                    f"Duplicate groups: {summary['duplicate_groups']}",
                    f"Duplicate rows deleted: {summary['duplicate_rows_deleted']}",
                    f"Rows still requiring missing-data review: {summary['missing_review_rows']}",
                    "",
                    "## Missing Field Distribution",
                    *[
                        f"- {field}: {count}"
                        for field, count in sorted(summary["missing_field_distribution"].items())
                    ],
                    "",
                    "Note: missing values were not invented. They were standardised and queued for source verification.",
                ]
            ),
            encoding="utf-8",
        )
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["id", "registration_no", "full_name", "missing_fields"])
            writer.writeheader()
            for row in summary["missing_examples"]:
                writer.writerow({**row, "missing_fields": "; ".join(row["missing_fields"])})
        return {"json": json_path, "markdown": md_path, "csv": csv_path}
