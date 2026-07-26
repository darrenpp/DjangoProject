from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.common.models import DuplicateReviewQueue
from apps.workforce.models import (
    AuditLog,
    CommunityHealthWorker,
    DataImportBatch,
    HealthStudent,
    MedicalDoctor,
    Midwife,
    NurseAide,
    NursingProfessional,
    PracticingLicenseRecord,
)


PLACEHOLDER_VALUES = {
    "",
    "-",
    "--",
    "N/A",
    "NA",
    "NONE",
    "NULL",
    "NAN",
    "NAT",
    "UNKNOWN",
    "TBA",
    "TBD",
    "NOT AVAILABLE",
    "NOT APPLICABLE",
    "...",
}

NURSING_TARGETS = {"nursingprofessional", "midwife", "nurseaide", "healthstudent"}
MEDICAL_TARGETS = {"medicaldoctor", "communityhealthworker"}
CATEGORY_RECORD_TYPES = {
    "atp": {
        "label": "ATP / Practicing Licence",
        "record_types": {"practicing_license"},
    },
    "full_license": {
        "label": "Full-Licence",
        "record_types": {"full"},
    },
    "provisional_graduands": {
        "label": "Provisional / Graduands",
        "record_types": {"provisional"},
    },
}
LIVE_MODELS = (
    ("nursing", "Nursing Professional", NursingProfessional),
    ("nursing", "Midwife", Midwife),
    ("nursing", "Nurse Aide", NurseAide),
    ("nursing", "Graduand / Health Student", HealthStudent),
    ("medical", "Medical Doctor", MedicalDoctor),
    ("medical", "Community Health Worker", CommunityHealthWorker),
)
EXACT_IMPORT_DUPLICATE_FIELDS = (
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
)


def normalize_text(value) -> str:
    return " ".join(str(value or "").strip().split())


def normalize_identifier(value) -> str:
    text = normalize_text(value)
    if text.upper() in PLACEHOLDER_VALUES:
        return ""
    return re.sub(r"[^A-Z0-9]+", "", text.upper())


def normalize_name(value) -> str:
    text = normalize_text(value)
    if text.upper() in PLACEHOLDER_VALUES:
        return ""
    return re.sub(r"[^A-Z ]+", "", text.upper()).strip()


def clean_string(value) -> str:
    text = normalize_text(value)
    return "" if text.upper() in PLACEHOLDER_VALUES else text


def _scope_for_target(target_model: str, source_kind: str = "") -> str:
    target = (target_model or "").lower()
    if target in MEDICAL_TARGETS or source_kind == "medical_board_workbook":
        return "medical"
    if target in NURSING_TARGETS:
        return "nursing"
    return "other"


class Command(BaseCommand):
    help = (
        "Cleanse safe registry text values and calculate corrected distinct worker totals "
        "for ATP, full-licence, and provisional/graduand categories."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--scope",
            choices=("all", "nursing", "medical"),
            default="all",
            help="Limit the worker-total report to one office scope.",
        )
        parser.add_argument(
            "--year",
            type=int,
            default=timezone.localdate().year,
            help="Current reporting year to highlight. Use 0 for all years only.",
        )
        parser.add_argument(
            "--apply-safe-normalization",
            action="store_true",
            help="Trim/collapse text and clear placeholder values where this does not create identifier conflicts.",
        )
        parser.add_argument(
            "--apply-exact-import-dedupe",
            action="store_true",
            help="Delete exact duplicate PracticingLicenseRecord rows only. Keeps the lowest id in each exact group.",
        )
        parser.add_argument(
            "--report-dir",
            default="docs/reports",
            help="Directory where reports should be written.",
        )

    def handle(self, *args, **options):
        scope = options["scope"]
        report_year = options["year"] or None
        apply_safe_normalization = options["apply_safe_normalization"]
        apply_exact_import_dedupe = options["apply_exact_import_dedupe"]
        report_dir = Path(options["report_dir"])
        report_dir.mkdir(parents=True, exist_ok=True)
        timestamp = timezone.localtime().strftime("%Y%m%d_%H%M%S")

        self.stdout.write("Registry worker-total cleanse started.")
        self.stdout.write(
            "Mode: "
            + (
                "APPLY selected safe cleanup"
                if apply_safe_normalization or apply_exact_import_dedupe
                else "DRY RUN only"
            )
        )

        normalization_summary = self._normalize_registry_text(apply_changes=apply_safe_normalization)
        exact_duplicate_plan = self._find_exact_import_duplicates(scope)
        exact_duplicate_deleted = 0

        if apply_exact_import_dedupe:
            exact_duplicate_deleted = self._delete_exact_import_duplicates(exact_duplicate_plan)

        live_summary, live_duplicate_rows, live_weak_identity_rows = self._live_registry_summary(scope)
        import_summary, duplicate_identity_rows, weak_identity_rows = self._imported_category_summary(
            scope=scope,
            report_year=report_year,
        )

        summary = {
            "generated_at": timezone.localtime().isoformat(),
            "scope": scope,
            "report_year": report_year,
            "applied_safe_normalization": apply_safe_normalization,
            "applied_exact_import_dedupe": apply_exact_import_dedupe,
            "safe_normalization": normalization_summary,
            "official_live_registry": live_summary,
            "imported_license_categories": import_summary,
            "exact_import_duplicate_groups": len(exact_duplicate_plan),
            "exact_import_duplicate_rows_to_delete": sum(len(group["delete_ids"]) for group in exact_duplicate_plan),
            "exact_import_duplicate_rows_deleted": exact_duplicate_deleted,
            "live_duplicate_identity_group_count": len(live_duplicate_rows),
            "live_weak_or_missing_identity_count": len(live_weak_identity_rows),
            "identity_duplicate_group_count": len(duplicate_identity_rows),
            "weak_or_missing_identity_count": len(weak_identity_rows),
            "data_rule": (
                "Official live worker counts come from active professional tables. "
                "Imported licence rows are counted as distinct people only after identifiers are collapsed; "
                "payments and workforce-listing rows are not counted as registered workers."
            ),
        }
        paths = self._write_reports(
            report_dir=report_dir,
            timestamp=timestamp,
            summary=summary,
            live_duplicate_rows=live_duplicate_rows,
            live_weak_identity_rows=live_weak_identity_rows,
            duplicate_identity_rows=duplicate_identity_rows,
            weak_identity_rows=weak_identity_rows,
        )

        if apply_safe_normalization or apply_exact_import_dedupe:
            AuditLog.objects.create(
                action="registry_worker_totals_cleanse",
                entity_type="workforce.registry",
                entity_id="all" if scope == "all" else scope,
                new_values_json={
                    "safe_normalization": apply_safe_normalization,
                    "exact_import_dedupe": apply_exact_import_dedupe,
                    "exact_duplicate_rows_deleted": exact_duplicate_deleted,
                    "report": str(paths["markdown"]),
                },
            )

        self.stdout.write(self.style.SUCCESS("Registry worker-total cleanse complete."))
        self._print_category_totals(import_summary)
        self.stdout.write(
            f"Live duplicate identity groups requiring registrar review: {summary['live_duplicate_identity_group_count']}."
        )
        self.stdout.write(
            f"Exact duplicate import groups: {summary['exact_import_duplicate_groups']}; "
            f"rows deleted: {summary['exact_import_duplicate_rows_deleted']}."
        )
        self.stdout.write(f"Report written to: {paths['markdown']}")
        self.stdout.write(f"JSON written to: {paths['json']}")
        self.stdout.write(f"Live duplicate identity CSV written to: {paths['live_duplicate_csv']}")
        self.stdout.write(f"Live weak/missing identity CSV written to: {paths['live_weak_csv']}")
        self.stdout.write(f"Duplicate identity CSV written to: {paths['duplicate_csv']}")
        self.stdout.write(f"Weak/missing identity CSV written to: {paths['weak_csv']}")

    def _scope_import_queryset(self, scope):
        queryset = PracticingLicenseRecord.objects.select_related("batch", "sheet")
        if scope == "medical":
            return queryset.filter(
                Q(target_model__in=MEDICAL_TARGETS)
                | Q(batch__source_kind="medical_board_workbook")
            )
        if scope == "nursing":
            return queryset.filter(target_model__in=NURSING_TARGETS).exclude(
                batch__source_kind="medical_board_workbook"
            )
        return queryset

    def _scope_live_model(self, model_scope, scope) -> bool:
        return scope == "all" or model_scope == scope

    def _identity_for_import(self, record):
        target = (record.target_model or "other").lower()
        registration_no = normalize_identifier(record.registration_no)
        practitioner_no = normalize_identifier(record.practitioner_number)
        full_name = normalize_name(record.full_name or f"{record.first_name} {record.last_name}")
        date_of_birth = record.date_of_birth.isoformat() if record.date_of_birth else ""

        if registration_no:
            return "strong_registration", f"{target}:registration:{registration_no}"
        if practitioner_no:
            return "strong_practitioner", f"{target}:practitioner:{practitioner_no}"
        if full_name and date_of_birth:
            return "strong_name_dob", f"{target}:name_dob:{full_name}:{date_of_birth}"
        if full_name:
            return "weak_name_only", f"{target}:name:{full_name}"
        return "missing_identity", f"{target}:missing:{record.id}"

    def _identity_for_live(self, obj, label):
        registration_no = normalize_identifier(getattr(obj, "registration_no", ""))
        registration_number = normalize_identifier(getattr(obj, "registration_number", ""))
        full_name = normalize_name(f"{getattr(obj, 'first_name', '')} {getattr(obj, 'last_name', '')}")
        date_of_birth = obj.date_of_birth.isoformat() if getattr(obj, "date_of_birth", None) else ""

        if registration_no:
            return "strong_registration", f"{label}:registration:{registration_no}"
        if registration_number:
            return "strong_registration_number", f"{label}:registration_number:{registration_number}"
        if full_name and date_of_birth:
            return "strong_name_dob", f"{label}:name_dob:{full_name}:{date_of_birth}"
        if full_name:
            return "weak_name_only", f"{label}:name:{full_name}"
        return "missing_identity", f"{label}:missing:{obj.id}"

    def _live_registry_summary(self, scope):
        rows = []
        totals = Counter()
        live_duplicate_rows = []
        live_weak_identity_rows = []
        for model_scope, label, model in LIVE_MODELS:
            if not self._scope_live_model(model_scope, scope):
                continue
            identities = defaultdict(list)
            active_queryset = model.objects.filter(is_active=True)
            for obj in active_queryset.iterator(chunk_size=2000):
                strength, key = self._identity_for_live(obj, label)
                identities[(strength, key)].append(obj)
                if strength in {"weak_name_only", "missing_identity"}:
                    live_weak_identity_rows.append(self._live_identity_row(model_scope, label, obj, strength, key))

            strong_total = sum(
                1
                for (strength, _key), objects in identities.items()
                if strength.startswith("strong") and objects
            )
            weak_total = sum(1 for (strength, _key) in identities if strength == "weak_name_only")
            missing_total = sum(1 for (strength, _key) in identities if strength == "missing_identity")
            duplicate_groups = sum(1 for objects in identities.values() if len(objects) > 1)
            for (strength, key), objects in identities.items():
                if len(objects) > 1:
                    live_duplicate_rows.append(
                        self._live_duplicate_row(model_scope, label, model.__name__, objects, strength, key)
                    )
            row = {
                "scope": model_scope,
                "category": label,
                "model": model.__name__,
                "raw_active_rows": active_queryset.count(),
                "trusted_distinct_workers": strong_total,
                "estimated_distinct_workers_including_name_only": strong_total + weak_total,
                "weak_name_only_identities": weak_total,
                "missing_identity_rows": missing_total,
                "duplicate_identity_groups": duplicate_groups,
            }
            rows.append(row)
            totals["raw_active_rows"] += row["raw_active_rows"]
            totals["trusted_distinct_workers"] += row["trusted_distinct_workers"]
            totals["estimated_distinct_workers_including_name_only"] += row[
                "estimated_distinct_workers_including_name_only"
            ]
            totals["weak_name_only_identities"] += row["weak_name_only_identities"]
            totals["missing_identity_rows"] += row["missing_identity_rows"]
            totals["duplicate_identity_groups"] += row["duplicate_identity_groups"]

        return {
            "rows": rows,
            "totals": dict(totals),
        }, live_duplicate_rows, live_weak_identity_rows

    def _live_identity_row(self, model_scope, label, obj, strength, key):
        return {
            "scope": model_scope,
            "category": label,
            "model": obj.__class__.__name__,
            "record_id": obj.id,
            "identity_strength": strength,
            "identity_key": key,
            "full_name": f"{getattr(obj, 'first_name', '')} {getattr(obj, 'last_name', '')}".strip(),
            "registration_no": getattr(obj, "registration_no", "") or "",
            "registration_number": getattr(obj, "registration_number", "") or "",
            "province": getattr(obj, "province", "") or "",
        }

    def _live_duplicate_row(self, model_scope, label, model_name, objects, strength, key):
        first = objects[0]
        return {
            "scope": model_scope,
            "category": label,
            "model": model_name,
            "identity_strength": strength,
            "identity_key": key,
            "row_count": len(objects),
            "record_ids": ",".join(str(obj.id) for obj in objects),
            "full_name": f"{getattr(first, 'first_name', '')} {getattr(first, 'last_name', '')}".strip(),
            "registration_no": getattr(first, "registration_no", "") or "",
            "registration_number": getattr(first, "registration_number", "") or "",
            "province": getattr(first, "province", "") or "",
        }

    def _imported_category_summary(self, scope, report_year):
        base_queryset = self._scope_import_queryset(scope).filter(
            record_type__in={
                record_type
                for category in CATEGORY_RECORD_TYPES.values()
                for record_type in category["record_types"]
            }
        )
        report_year_queryset = base_queryset.filter(record_year=report_year) if report_year else base_queryset.none()
        summary = {}
        duplicate_identity_rows = []
        weak_identity_rows = []

        for category_key, category_config in CATEGORY_RECORD_TYPES.items():
            category_queryset = base_queryset.filter(record_type__in=category_config["record_types"])
            all_years = self._summarize_import_queryset(
                category_queryset,
                category_key,
                "all_years",
                duplicate_identity_rows,
                weak_identity_rows,
            )
            selected_year = self._summarize_import_queryset(
                report_year_queryset.filter(record_type__in=category_config["record_types"]),
                category_key,
                str(report_year) if report_year else "not_requested",
                duplicate_identity_rows,
                weak_identity_rows,
            ) if report_year else None
            summary[category_key] = {
                "label": category_config["label"],
                "all_years": all_years,
                "report_year": selected_year,
            }
        return summary, duplicate_identity_rows, weak_identity_rows

    def _summarize_import_queryset(self, queryset, category_key, period_label, duplicate_rows, weak_rows):
        identities = defaultdict(list)
        target_counter = Counter()
        source_counter = Counter()
        record_year_counter = Counter()
        raw_rows = 0

        for record in queryset.iterator(chunk_size=5000):
            raw_rows += 1
            source_kind = getattr(record.batch, "source_kind", "") if record.batch_id else ""
            scope = _scope_for_target(record.target_model, source_kind)
            strength, key = self._identity_for_import(record)
            identities[(strength, key)].append(record)
            target_counter[record.target_model or "other"] += 1
            source_counter[source_kind or "unknown"] += 1
            record_year_counter[str(record.record_year or "No year")] += 1
            if strength in {"weak_name_only", "missing_identity"}:
                weak_rows.append(self._import_identity_row(record, category_key, period_label, strength, key, scope))

        trusted_distinct = sum(
            1
            for (strength, _key), records in identities.items()
            if strength.startswith("strong") and records
        )
        weak_distinct = sum(1 for (strength, _key) in identities if strength == "weak_name_only")
        missing_rows = sum(len(records) for (strength, _key), records in identities.items() if strength == "missing_identity")

        for (strength, key), records in identities.items():
            if len(records) <= 1:
                continue
            duplicate_rows.append(self._import_duplicate_row(records, category_key, period_label, strength, key))

        return {
            "raw_rows": raw_rows,
            "trusted_distinct_workers": trusted_distinct,
            "estimated_distinct_workers_including_name_only": trusted_distinct + weak_distinct,
            "weak_name_only_identities": weak_distinct,
            "missing_identity_rows": missing_rows,
            "duplicate_identity_groups": sum(1 for records in identities.values() if len(records) > 1),
            "duplicate_rows_collapsed": sum(max(len(records) - 1, 0) for records in identities.values()),
            "by_target_model": dict(sorted(target_counter.items())),
            "by_source_kind": dict(sorted(source_counter.items())),
            "by_record_year": dict(sorted(record_year_counter.items())),
        }

    def _import_identity_row(self, record, category_key, period_label, strength, key, scope):
        return {
            "category": category_key,
            "period": period_label,
            "scope": scope,
            "record_id": record.id,
            "source_kind": getattr(record.batch, "source_kind", "") if record.batch_id else "",
            "source_sheet": record.source_sheet_name,
            "source_row": record.source_row,
            "target_model": record.target_model,
            "record_year": record.record_year,
            "identity_strength": strength,
            "identity_key": key,
            "full_name": record.full_name,
            "registration_no": record.registration_no,
            "practitioner_number": record.practitioner_number,
            "category_label": record.category,
        }

    def _import_duplicate_row(self, records, category_key, period_label, strength, key):
        first = records[0]
        return {
            "category": category_key,
            "period": period_label,
            "identity_strength": strength,
            "identity_key": key,
            "row_count": len(records),
            "record_ids": ",".join(str(record.id) for record in records),
            "target_model": first.target_model,
            "record_years": ",".join(sorted({str(record.record_year or "") for record in records})),
            "full_name": first.full_name,
            "registration_no": first.registration_no,
            "practitioner_number": first.practitioner_number,
            "source_sheets": "; ".join(sorted({record.source_sheet_name for record in records if record.source_sheet_name})),
        }

    def _normalize_registry_text(self, apply_changes):
        model_summaries = []
        text_models = [model for _scope, _label, model in LIVE_MODELS] + [PracticingLicenseRecord]
        with transaction.atomic():
            for model in text_models:
                text_fields = [
                    field
                    for field in model._meta.fields
                    if field.get_internal_type() in {"CharField", "TextField", "EmailField"}
                ]
                scanned = 0
                changed_records = 0
                changed_fields = 0
                skipped_unique_conflicts = 0
                field_changes = Counter()
                for obj in model.objects.all().iterator(chunk_size=2000):
                    scanned += 1
                    updates = []
                    for field in text_fields:
                        current = getattr(obj, field.name)
                        cleaned = clean_string(current)
                        if field.max_length:
                            cleaned = cleaned[:field.max_length]
                        if getattr(field, "null", False) and cleaned == "":
                            cleaned_value = None
                        else:
                            cleaned_value = cleaned
                        if current == cleaned_value:
                            continue
                        if (
                            getattr(field, "unique", False)
                            and cleaned_value not in {None, ""}
                            and model.objects.exclude(pk=obj.pk).filter(**{field.name: cleaned_value}).exists()
                        ):
                            skipped_unique_conflicts += 1
                            continue
                        setattr(obj, field.name, cleaned_value)
                        updates.append(field.name)
                        field_changes[field.name] += 1
                    if updates:
                        changed_records += 1
                        changed_fields += len(updates)
                        if apply_changes:
                            obj.save(update_fields=updates)
                model_summaries.append(
                    {
                        "model": model.__name__,
                        "scanned": scanned,
                        "changed_records": changed_records,
                        "changed_fields": changed_fields,
                        "skipped_unique_conflicts": skipped_unique_conflicts,
                        "field_changes": dict(sorted(field_changes.items())),
                    }
                )
            if not apply_changes:
                transaction.set_rollback(True)
        return model_summaries

    def _find_exact_import_duplicates(self, scope):
        groups = defaultdict(list)
        queryset = self._scope_import_queryset(scope).values("id", *EXACT_IMPORT_DUPLICATE_FIELDS).order_by("id")
        for row in queryset.iterator(chunk_size=5000):
            key = tuple(self._normalize_duplicate_value(row[field]) for field in EXACT_IMPORT_DUPLICATE_FIELDS)
            groups[key].append(row["id"])
        duplicate_plan = []
        for ids in groups.values():
            if len(ids) < 2:
                continue
            ids.sort()
            duplicate_plan.append({"keep_id": ids[0], "delete_ids": ids[1:]})
        return duplicate_plan

    def _normalize_duplicate_value(self, value):
        if value is None:
            return ""
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return normalize_text(value)

    def _delete_exact_import_duplicates(self, duplicate_plan):
        practicing_ct = ContentType.objects.get_for_model(PracticingLicenseRecord)
        deleted = 0
        with transaction.atomic():
            for group in duplicate_plan:
                delete_ids = group["delete_ids"]
                if not delete_ids:
                    continue
                DuplicateReviewQueue.objects.filter(content_type=practicing_ct, object_id__in=delete_ids).delete()
                deleted += PracticingLicenseRecord.objects.filter(id__in=delete_ids).delete()[0]
        return deleted

    def _write_reports(
        self,
        report_dir,
        timestamp,
        summary,
        live_duplicate_rows,
        live_weak_identity_rows,
        duplicate_identity_rows,
        weak_identity_rows,
    ):
        json_path = report_dir / f"registry_worker_totals_{timestamp}.json"
        md_path = report_dir / f"registry_worker_totals_{timestamp}.md"
        live_duplicate_csv_path = report_dir / f"registry_worker_totals_live_duplicate_identities_{timestamp}.csv"
        live_weak_csv_path = report_dir / f"registry_worker_totals_live_weak_missing_identities_{timestamp}.csv"
        duplicate_csv_path = report_dir / f"registry_worker_totals_duplicate_identities_{timestamp}.csv"
        weak_csv_path = report_dir / f"registry_worker_totals_weak_missing_identities_{timestamp}.csv"

        json_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
        md_path.write_text(self._markdown_report(summary), encoding="utf-8")
        self._write_csv(live_duplicate_csv_path, live_duplicate_rows)
        self._write_csv(live_weak_csv_path, live_weak_identity_rows)
        self._write_csv(duplicate_csv_path, duplicate_identity_rows)
        self._write_csv(weak_csv_path, weak_identity_rows)
        return {
            "json": json_path,
            "markdown": md_path,
            "live_duplicate_csv": live_duplicate_csv_path,
            "live_weak_csv": live_weak_csv_path,
            "duplicate_csv": duplicate_csv_path,
            "weak_csv": weak_csv_path,
        }

    def _markdown_report(self, summary):
        lines = [
            "# Registry Worker Totals Cleanse",
            "",
            f"Generated at: {summary['generated_at']}",
            f"Scope: {summary['scope']}",
            f"Highlighted report year: {summary['report_year'] or 'All years only'}",
            f"Safe normalization applied: {summary['applied_safe_normalization']}",
            f"Exact import dedupe applied: {summary['applied_exact_import_dedupe']}",
            "",
            "## Official Live Registry Counts",
            "",
            "| Scope | Category | Raw active rows | Trusted distinct workers | Estimated incl. name-only | Weak identities | Missing identity rows | Duplicate groups |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
        for row in summary["official_live_registry"]["rows"]:
            lines.append(
                "| {scope} | {category} | {raw_active_rows} | {trusted_distinct_workers} | "
                "{estimated_distinct_workers_including_name_only} | {weak_name_only_identities} | "
                "{missing_identity_rows} | {duplicate_identity_groups} |".format(**row)
            )
        totals = summary["official_live_registry"]["totals"]
        lines.append(
            "| all selected | Total | {raw_active_rows} | {trusted_distinct_workers} | "
            "{estimated_distinct_workers_including_name_only} | {weak_name_only_identities} | "
            "{missing_identity_rows} | {duplicate_identity_groups} |".format(**totals)
        )
        lines.extend(["", "## Imported Licence Category Counts", ""])
        lines.append(
            "| Category | Period | Raw rows | Trusted distinct workers | Estimated incl. name-only | Duplicate rows collapsed | Weak identities | Missing identity rows |"
        )
        lines.append("|---|---|---:|---:|---:|---:|---:|---:|")
        for category in summary["imported_license_categories"].values():
            for period_name in ("all_years", "report_year"):
                data = category.get(period_name)
                if not data:
                    continue
                lines.append(
                    f"| {category['label']} | {period_name.replace('_', ' ')} | "
                    f"{data['raw_rows']} | {data['trusted_distinct_workers']} | "
                    f"{data['estimated_distinct_workers_including_name_only']} | "
                    f"{data['duplicate_rows_collapsed']} | {data['weak_name_only_identities']} | "
                    f"{data['missing_identity_rows']} |"
                )
        lines.extend(
            [
                "",
                "## Cleanup Findings",
                "",
                f"- Exact duplicate import groups: {summary['exact_import_duplicate_groups']}",
                f"- Exact duplicate import rows to delete: {summary['exact_import_duplicate_rows_to_delete']}",
                f"- Exact duplicate import rows deleted: {summary['exact_import_duplicate_rows_deleted']}",
                f"- Live duplicate identity groups requiring registrar review: {summary['live_duplicate_identity_group_count']}",
                f"- Live weak or missing identities requiring source review: {summary['live_weak_or_missing_identity_count']}",
                f"- Duplicate identity groups across imported licence categories: {summary['identity_duplicate_group_count']}",
                f"- Weak or missing identity rows requiring source review: {summary['weak_or_missing_identity_count']}",
                "",
                "## Counting Rule",
                "",
                summary["data_rule"],
                "",
                "Rows with missing identifiers were not invented. They are listed for source verification before they are trusted as registered workers.",
            ]
        )
        return "\n".join(lines)

    def _write_csv(self, path, rows):
        if not rows:
            path.write_text("", encoding="utf-8")
            return
        fieldnames = list(rows[0].keys())
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def _print_category_totals(self, import_summary):
        self.stdout.write("Corrected imported licence category totals:")
        for category in import_summary.values():
            data = category.get("report_year") or category["all_years"]
            self.stdout.write(
                f"- {category['label']}: {data['trusted_distinct_workers']} trusted distinct workers "
                f"({data['raw_rows']} raw rows; {data['duplicate_rows_collapsed']} duplicate rows collapsed)"
            )
