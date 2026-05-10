from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from apps.common.models import DuplicateReviewQueue
from apps.workforce.models import (
    CommunityHealthWorker,
    HealthStudent,
    MedicalDoctor,
    Midwife,
    NurseAide,
    NursingProfessional,
    PracticingLicenseRecord,
)


LIVE_MODELS = [
    NursingProfessional,
    Midwife,
    MedicalDoctor,
    CommunityHealthWorker,
    NurseAide,
    HealthStudent,
]

EXACT_DUPLICATE_FIELDS = [
    "target_model",
    "record_type",
    "record_year",
    "full_name",
    "first_name",
    "last_name",
    "registration_no",
    "practitioner_number",
    "applicant_type",
    "qualification_name",
    "category",
    "institution_name",
    "workplace_address",
    "province",
    "issued_date",
    "payment_date",
    "amount",
    "reference_number",
    "payment_method",
]


class Command(BaseCommand):
    help = (
        "Audit imported duplicate records, remove exact duplicate PracticingLicenseRecord "
        "rows safely, and rebuild duplicate review queue entries for remaining suspicious groups."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Delete exact duplicate imported rows and rebuild duplicate review queue entries.",
        )
        parser.add_argument(
            "--report-dir",
            default="docs/reports",
            help="Directory where cleanup reports should be written.",
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        report_dir = Path(options["report_dir"])
        report_dir.mkdir(parents=True, exist_ok=True)

        timestamp = timezone.localtime().strftime("%Y%m%d_%H%M%S")
        practicing_ct = ContentType.objects.get_for_model(PracticingLicenseRecord)

        exact_duplicate_plan = self._scan_exact_duplicate_records()
        live_registry_summary = self._scan_live_registry_duplicates()
        queue_before = DuplicateReviewQueue.objects.filter(
            content_type=practicing_ct,
            status="pending",
        ).count()

        deleted_rows = 0
        rebuilt_review_count = 0

        if apply_changes:
            deleted_rows = self._apply_exact_duplicate_cleanup(practicing_ct, exact_duplicate_plan)
            rebuilt_review_count = self._rebuild_practicing_record_duplicate_reviews(practicing_ct)
        else:
            rebuilt_review_count = self._count_review_groups_after_cleanup()

        queue_after = DuplicateReviewQueue.objects.filter(
            content_type=practicing_ct,
            status="pending",
        ).count()

        summary = {
            "generated_at": timezone.localtime().isoformat(),
            "apply_changes": apply_changes,
            "practicing_license_record_total": PracticingLicenseRecord.objects.count(),
            "exact_duplicate_group_count": exact_duplicate_plan["group_count"],
            "exact_duplicate_rows_found": exact_duplicate_plan["rows_found"],
            "exact_duplicate_rows_deleted": deleted_rows,
            "same_name_registration_review_groups_current_scan": self._count_groups_for_identifier("registration_no"),
            "same_name_practitioner_review_groups_current_scan": self._count_groups_for_identifier("practitioner_number"),
            "pending_review_queue_before": queue_before,
            "pending_review_queue_after": queue_after,
            "review_groups_detected_current_scan": rebuilt_review_count,
            "live_registry_summary": live_registry_summary,
            "exact_duplicate_examples": exact_duplicate_plan["examples"],
        }

        report_paths = self._write_reports(report_dir, timestamp, summary)

        self.stdout.write(self.style.SUCCESS("Duplicate audit complete."))
        self.stdout.write(
            f"Exact duplicate groups: {summary['exact_duplicate_group_count']}, "
            f"rows found: {summary['exact_duplicate_rows_found']}, "
            f"rows deleted: {summary['exact_duplicate_rows_deleted']}."
        )
        self.stdout.write(
            f"Pending imported-record duplicate reviews before: {queue_before}, after: {queue_after}. "
            f"Review groups detected after cleanup: {rebuilt_review_count}."
        )
        self.stdout.write(f"Report written to: {report_paths['markdown']}")
        self.stdout.write(f"JSON summary written to: {report_paths['json']}")
        self.stdout.write(f"CSV samples written to: {report_paths['csv']}")

    def _normalize(self, value):
        if value is None:
            return ""
        if isinstance(value, str):
            return " ".join(value.strip().split())
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return value

    def _scan_live_registry_duplicates(self):
        summary = []
        for model in LIVE_MODELS:
            same_reg_no = model.objects.exclude(registration_no__isnull=True).exclude(registration_no="").values(
                "first_name",
                "middle_name",
                "last_name",
                "registration_no",
            ).annotate(total=Count("id")).filter(total__gt=1).count()

            same_reg_number = model.objects.exclude(registration_number__isnull=True).exclude(registration_number="").values(
                "first_name",
                "middle_name",
                "last_name",
                "registration_number",
            ).annotate(total=Count("id")).filter(total__gt=1).count()

            summary.append({
                "model": model.__name__,
                "total_records": model.objects.count(),
                "same_name_registration_no_groups": same_reg_no,
                "same_name_registration_number_groups": same_reg_number,
            })
        return summary

    def _scan_exact_duplicate_records(self):
        examples = []
        group_count = 0
        rows_found = 0

        current_key = None
        current_ids = []
        current_row = None
        duplicate_groups = []

        queryset = PracticingLicenseRecord.objects.values("id", *EXACT_DUPLICATE_FIELDS).order_by(
            *EXACT_DUPLICATE_FIELDS,
            "id",
        )

        for row in queryset.iterator(chunk_size=5000):
            key = tuple(self._normalize(row[field]) for field in EXACT_DUPLICATE_FIELDS)
            if key != current_key:
                if current_key is not None and len(current_ids) > 1:
                    group_count += 1
                    rows_found += len(current_ids) - 1
                    duplicate_groups.append({
                        "keep_id": current_ids[0],
                        "delete_ids": current_ids[1:],
                        "sample": current_row,
                    })
                    if len(examples) < 50:
                        examples.append({
                            "keep_id": current_ids[0],
                            "delete_ids": current_ids[1:],
                            "duplicate_count": len(current_ids),
                            "target_model": current_row["target_model"],
                            "record_type": current_row["record_type"],
                            "record_year": current_row["record_year"],
                            "full_name": current_row["full_name"],
                            "registration_no": current_row["registration_no"],
                            "practitioner_number": current_row["practitioner_number"],
                            "reference_number": current_row["reference_number"],
                        })
                current_key = key
                current_ids = [row["id"]]
                current_row = row
            else:
                current_ids.append(row["id"])

        if current_key is not None and len(current_ids) > 1:
            group_count += 1
            rows_found += len(current_ids) - 1
            duplicate_groups.append({
                "keep_id": current_ids[0],
                "delete_ids": current_ids[1:],
                "sample": current_row,
            })
            if len(examples) < 50:
                examples.append({
                    "keep_id": current_ids[0],
                    "delete_ids": current_ids[1:],
                    "duplicate_count": len(current_ids),
                    "target_model": current_row["target_model"],
                    "record_type": current_row["record_type"],
                    "record_year": current_row["record_year"],
                    "full_name": current_row["full_name"],
                    "registration_no": current_row["registration_no"],
                    "practitioner_number": current_row["practitioner_number"],
                    "reference_number": current_row["reference_number"],
                })

        return {
            "group_count": group_count,
            "rows_found": rows_found,
            "groups": duplicate_groups,
            "examples": examples,
        }

    def _apply_exact_duplicate_cleanup(self, practicing_ct, plan):
        deleted_rows = 0
        with transaction.atomic():
            DuplicateReviewQueue.objects.filter(
                content_type=practicing_ct,
                status="pending",
            ).delete()

            for group in plan["groups"]:
                keep_id = group["keep_id"]
                delete_ids = group["delete_ids"]
                if delete_ids:
                    DuplicateReviewQueue.objects.filter(
                        content_type=practicing_ct,
                        object_id__in=delete_ids,
                    ).update(object_id=keep_id)
                    deleted_rows += len(delete_ids)
                    PracticingLicenseRecord.objects.filter(id__in=delete_ids).delete()
        return deleted_rows

    def _is_meaningful_identifier(self, value):
        if not value:
            return False
        text = " ".join(str(value).strip().split()).upper()
        if text in {"TBA", "GD", "PG", "G", "OO", "O"}:
            return False
        return any(character.isdigit() for character in text)

    def _iter_review_groups(self):
        seen = set()

        reg_groups = (
            PracticingLicenseRecord.objects.exclude(registration_no="")
            .values("target_model", "record_type", "record_year", "full_name", "registration_no")
            .annotate(total=Count("id"))
            .filter(total__gt=1)
            .order_by("-total")
        )
        for row in reg_groups.iterator(chunk_size=2000):
            key = (
                "registration_no",
                row["target_model"],
                row["record_type"],
                row["record_year"],
                row["full_name"],
                row["registration_no"],
            )
            if key in seen:
                continue
            seen.add(key)
            yield {
                "match_type": "same_name_same_registration_no_same_year_type",
                "key": key,
                "target_model": row["target_model"],
                "record_type": row["record_type"],
                "record_year": row["record_year"],
                "full_name": row["full_name"],
                "identifier": row["registration_no"],
                "identifier_field": "registration_no",
                "member_count": row["total"],
            }

        practitioner_groups = (
            PracticingLicenseRecord.objects.exclude(practitioner_number="")
            .values("target_model", "record_type", "record_year", "full_name", "practitioner_number")
            .annotate(total=Count("id"))
            .filter(total__gt=1)
            .order_by("-total")
        )
        for row in practitioner_groups.iterator(chunk_size=2000):
            if not self._is_meaningful_identifier(row["practitioner_number"]):
                continue
            key = (
                "practitioner_number",
                row["target_model"],
                row["record_type"],
                row["record_year"],
                row["full_name"],
                row["practitioner_number"],
            )
            if key in seen:
                continue
            seen.add(key)
            yield {
                "match_type": "same_name_same_practitioner_no_same_year_type",
                "key": key,
                "target_model": row["target_model"],
                "record_type": row["record_type"],
                "record_year": row["record_year"],
                "full_name": row["full_name"],
                "identifier": row["practitioner_number"],
                "identifier_field": "practitioner_number",
                "member_count": row["total"],
            }

    def _count_groups_for_identifier(self, identifier_field):
        total = 0
        for group in self._iter_review_groups():
            if group["identifier_field"] == identifier_field:
                total += 1
        return total

    def _count_review_groups_after_cleanup(self):
        return sum(1 for _ in self._iter_review_groups())

    def _rebuild_practicing_record_duplicate_reviews(self, practicing_ct):
        created = 0
        with transaction.atomic():
            DuplicateReviewQueue.objects.filter(
                content_type=practicing_ct,
                status="pending",
            ).delete()

            for group in self._iter_review_groups():
                filters = {
                    "target_model": group["target_model"],
                    "record_type": group["record_type"],
                    "record_year": group["record_year"],
                    "full_name": group["full_name"],
                    group["identifier_field"]: group["identifier"],
                }
                member_ids = list(
                    PracticingLicenseRecord.objects.filter(**filters)
                    .order_by("id")
                    .values_list("id", flat=True)
                )
                if len(member_ids) < 2:
                    continue

                DuplicateReviewQueue.objects.create(
                    content_type=practicing_ct,
                    object_id=member_ids[0],
                    suspected_duplicate={
                        "audit_type": group["match_type"],
                        "target_model": group["target_model"],
                        "record_type": group["record_type"],
                        "record_year": group["record_year"],
                        "full_name": group["full_name"],
                        "identifier_field": group["identifier_field"],
                        "identifier_value": group["identifier"],
                        "member_ids": member_ids,
                        "member_count": len(member_ids),
                    },
                    similarity_score=1.0,
                )
                created += 1
        return created

    def _write_reports(self, report_dir, timestamp, summary):
        markdown_path = report_dir / f"duplicate_cleanup_report_{timestamp}.md"
        json_path = report_dir / f"duplicate_cleanup_report_{timestamp}.json"
        csv_path = report_dir / f"duplicate_cleanup_exact_examples_{timestamp}.csv"

        markdown_lines = [
            "# Duplicate Cleanup Report",
            "",
            f"- Generated: {summary['generated_at']}",
            f"- Apply mode: {summary['apply_changes']}",
            f"- PracticingLicenseRecord total after run: {summary['practicing_license_record_total']}",
            f"- Exact duplicate groups found: {summary['exact_duplicate_group_count']}",
            f"- Exact duplicate rows found: {summary['exact_duplicate_rows_found']}",
            f"- Exact duplicate rows deleted: {summary['exact_duplicate_rows_deleted']}",
            f"- Same-name + registration number review groups in current scan: {summary['same_name_registration_review_groups_current_scan']}",
            f"- Same-name + practitioner number review groups in current scan: {summary['same_name_practitioner_review_groups_current_scan']}",
            f"- Pending duplicate review queue before: {summary['pending_review_queue_before']}",
            f"- Pending duplicate review queue after: {summary['pending_review_queue_after']}",
            f"- Remaining review groups queued in current scan: {summary['review_groups_detected_current_scan']}",
            "",
            "## Live Registry Duplicate Scan",
            "",
        ]
        for row in summary["live_registry_summary"]:
            markdown_lines.append(
                f"- {row['model']}: {row['total_records']} records, "
                f"{row['same_name_registration_no_groups']} same-name+registration_no groups, "
                f"{row['same_name_registration_number_groups']} same-name+registration_number groups."
            )

        markdown_lines.extend([
            "",
            "## Exact Duplicate Imported Record Examples",
            "",
            "| Target Model | Record Type | Year | Full Name | Registration No | Practitioner No | Duplicate Count | Keep ID | Delete IDs |",
            "| --- | --- | --- | --- | --- | --- | ---: | ---: | --- |",
        ])
        for example in summary["exact_duplicate_examples"][:25]:
            markdown_lines.append(
                f"| {example['target_model']} | {example['record_type']} | {example['record_year']} | "
                f"{example['full_name']} | {example['registration_no']} | {example['practitioner_number']} | "
                f"{example['duplicate_count']} | {example['keep_id']} | {', '.join(str(value) for value in example['delete_ids'][:8])} |"
            )

        markdown_path.write_text("\n".join(markdown_lines), encoding="utf-8")
        json_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "target_model",
                    "record_type",
                    "record_year",
                    "full_name",
                    "registration_no",
                    "practitioner_number",
                    "reference_number",
                    "duplicate_count",
                    "keep_id",
                    "delete_ids",
                ],
            )
            writer.writeheader()
            for example in summary["exact_duplicate_examples"]:
                writer.writerow({
                    **example,
                    "delete_ids": ", ".join(str(value) for value in example["delete_ids"]),
                })

        return {
            "markdown": markdown_path,
            "json": json_path,
            "csv": csv_path,
        }
