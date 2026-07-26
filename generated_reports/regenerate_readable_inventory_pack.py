from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import xlsxwriter


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "generated_reports" / "formal_valuation_evidence_pack"
GRAPHICS = PACK / "inventory_graphics"
DATE_TEXT = "9 June 2026"

TEXT_EXTENSIONS = {".py", ".html", ".js", ".css", ".md", ".txt", ".json", ".xml", ".yml", ".yaml"}
EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    ".idea",
    ".vscode",
    "migrations",
    "media",
    "logs",
    "generated_reports",
    "staticfiles",
    "node_modules",
}
EXCLUDED_PATH_TOKENS = (
    "static\\css\\adminlte",
    "static/js/adminlte",
    "static\\js\\Chart.js",
    "docs\\presentation\\assets\\html",
    "docs\\system_brief_assets\\html",
)

APP_LABELS = {
    "accounts": "Accounts, roles, approvals, and security",
    "common": "Common review utilities",
    "competency": "Competency assessment",
    "complaints": "Complaints, discipline, and decisions",
    "dashboard": "Dashboards, reports, maps, and analytics",
    "documents": "Document repository and records management",
    "mobile_intake": "Mobile intake API and review queue",
    "nhwa_workbooks": "NHWA workbook and reporting toolkit",
    "notifications": "Notifications, enquiries, and helpdesk",
    "ocr": "OCR and document import",
    "workforce": "Registry, licensing, applications, and workforce data",
}

PREFIX_BY_SOURCE = {
    "apps\\accounts\\urls.py": "/accounts/",
    "apps\\common\\record_urls.py": "/records/",
    "apps\\complaints\\urls.py": "/dashboard/complaints/",
    "apps\\dashboard\\urls.py": "/dashboard/",
    "apps\\documents\\urls.py": "/documents/",
    "apps\\mobile_intake\\urls.py": "/api/mobile/v1/",
    "apps\\nhwa_workbooks\\urls.py": "/dashboard/nhwa-workbooks/",
    "apps\\notifications\\urls.py": "/notifications/",
    "apps\\ocr\\urls.py": "/ocr/",
    "apps\\workforce\\urls.py": "/workforce/",
}


def font(size=22, bold=False):
    candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/calibrib.ttf" if bold else "C:/Windows/Fonts/calibri.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def is_excluded(path: Path) -> bool:
    rel = str(path.relative_to(ROOT))
    if any(part in EXCLUDED_PARTS for part in path.parts):
        return True
    if path.name == "__init__.py":
        return True
    return any(token in rel for token in EXCLUDED_PATH_TOKENS)


def line_count(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
    except Exception:
        return 0


def clean_route(prefix: str, route: str) -> str:
    joined = f"{prefix.rstrip('/')}/{route.lstrip('/')}"
    joined = re.sub(r"/+", "/", joined)
    return joined if joined.startswith("/") else f"/{joined}"


def area_for_path(path: Path) -> tuple[str, str]:
    rel = path.relative_to(ROOT)
    parts = rel.parts
    if len(parts) >= 2 and parts[0] == "apps":
        app = parts[1]
        return APP_LABELS.get(app, app.replace("_", " ").title()), app
    if parts[0] == "NDOH_regulatory_bodies":
        return "Project settings, root URLs, and middleware", "project"
    if parts[0] == "templates":
        return "Shared templates and public UI", "templates"
    if parts[0] == "static":
        return "Static UI assets", "static"
    if parts[0] == "docs":
        return "Documentation and launch evidence", "docs"
    return "Project support files", parts[0]


def file_type(path: Path) -> str:
    mapping = {
        ".py": "Python code",
        ".html": "HTML template",
        ".js": "JavaScript",
        ".css": "CSS styling",
        ".md": "Markdown documentation",
        ".txt": "Text documentation",
        ".json": "JSON/config data",
        ".xml": "XML/config data",
        ".yml": "YAML/config data",
        ".yaml": "YAML/config data",
    }
    return mapping.get(path.suffix.lower(), path.suffix.lower().lstrip(".").upper())


def purpose_for_path(path: Path) -> tuple[str, str, str]:
    rel = path.relative_to(ROOT)
    name = path.name.lower()
    parts = {part.lower() for part in rel.parts}
    if "tests" in parts or name.startswith("test"):
        return "Automated test coverage", "Quality evidence", "Shows regression and workflow test coverage."
    if name == "models.py":
        return "Database/entity definitions", "Data model evidence", "Defines the core records and relationships used by the platform."
    if name in {"views.py", "api_views.py"}:
        return "Web and API request handling", "Runtime functionality", "Implements pages, staff workflows, and API endpoints."
    if name in {"urls.py", "api_urls.py"}:
        return "URL/API routing", "System surface evidence", "Shows the public, staff, API, and workflow entry points."
    if name in {"forms.py", "serializers.py"}:
        return "Input validation and form handling", "Workflow validation", "Controls submitted data and API payload validation."
    if "services" in parts:
        return "Business rules and workflow services", "Workflow logic", "Contains operational logic for imports, reviews, approvals, sync, and reporting."
    if "management" in parts:
        return "Management command", "Operations tooling", "Supports bootstrapping, imports, maintenance, or controlled test setup."
    if path.suffix.lower() == ".html":
        return "User interface template", "User workflow evidence", "Renders a public, professional, or staff-facing screen."
    if path.suffix.lower() in {".css", ".js"}:
        return "Frontend asset", "User interface evidence", "Supports responsive layout, charts, tables, and interaction."
    if path.suffix.lower() in {".md", ".txt"}:
        return "Documentation", "Governance evidence", "Supports training, launch, architecture, testing, or operational handover."
    return "Support file", "Support evidence", "Supports configuration, data, or project operation."


def entity_domain(entity: str, app: str) -> tuple[str, str, str]:
    lower = entity.lower()
    if app == "accounts" or any(token in lower for token in ("user", "mfa", "security", "access")):
        return "Access control and security", "Security/account entity", "Controls users, approvals, MFA, access requests, or audit events."
    if app == "mobile_intake" or lower.startswith("mobile"):
        return "Mobile intake", "Mobile/API entity", "Supports Android/mobile account, device, form, submission, attachment, sync, or promotion workflows."
    if app == "documents" or "document" in lower:
        return "Document repository", "Records/document entity", "Supports controlled documents, versions, approvals, access policy, and audit evidence."
    if app == "complaints" or any(token in lower for token in ("complaint", "disciplinary", "decision")):
        return "Complaints and discipline", "Regulatory case entity", "Supports complaints, discipline, case events, attachments, and formal decision records."
    if app == "nhwa_workbooks" or lower.startswith("nhwa"):
        return "NHWA reporting", "Workbook/reporting entity", "Supports NHWA workbook templates, entries, and audit history."
    if app == "dashboard" and any(token in lower for token in ("analytics", "metric", "snapshot", "fact", "index")):
        return "Analytics and reporting", "Analytics entity", "Supports dashboards, lifecycle facts, metrics, and reporting outputs."
    if app == "dashboard" and any(token in lower for token in ("mapped", "facilityalias", "institutionalias", "faq", "forum")):
        return "Public engagement and mapping", "Public information entity", "Supports public FAQs, forum, mapped facilities, schools, and aliases."
    if app == "dashboard" and "receipt" in lower:
        return "Finance and receipts", "Finance entity", "Supports receipt tracking, ownership linking, and payment evidence review."
    if app == "workforce" and any(token in lower for token in ("application", "checklist", "pathway", "status", "fee", "licence", "license")):
        return "Registration and licensing workflow", "Workflow entity", "Supports applications, pathways, checklists, fees, licence documents, and lifecycle status."
    if app == "workforce" and any(token in lower for token in ("professional", "doctor", "nurse", "midwife", "student", "worker")):
        return "Professional registry", "Registry entity", "Stores health professional, cadre, and workforce registry records."
    if app == "workforce":
        return "Registry reference data", "Reference/master-data entity", "Stores facilities, locations, institutions, document requirements, import batches, and audit logs."
    if app == "ocr":
        return "OCR and import", "OCR entity", "Supports document OCR and import evidence."
    if app == "common":
        return "Common review queues", "Review entity", "Supports duplicate review, deceased review, and shared data-quality workflows."
    if app == "competency":
        return "Competency assessment", "Assessment entity", "Supports competency review evidence."
    return "Platform support", "Support entity", "Supports platform operation."


def route_area_and_purpose(source: str, full_route: str, target: str) -> tuple[str, str, str]:
    route = full_route.lower()
    src = source.lower()
    if route.startswith("/api/mobile"):
        return "Mobile API", "Mobile/API", "Android/mobile intake authentication, lookup, form, submission, attachment, and status workflow."
    if "/public/" in route or route in {"/", "/home/"} or "public" in target.lower():
        return "Public access", "Public", "Public-safe home, register search, maps, FAQs, forum, or public forms."
    if route.startswith("/admin"):
        return "Django admin", "System admin", "Django administration console."
    if route.startswith("/accounts"):
        return "Accounts and profile", "Auth/profile", "Login, registration, approval, profile, password reset, MFA, or access request workflow."
    if route.startswith("/documents"):
        return "Document repository", "Staff/document", "Document repository search, upload, versioning, approval, and download workflow."
    if "complaints" in route:
        return "Complaints and discipline", "Staff/regulatory", "Complaints, discipline, incident case, and decision-register workflow."
    if route.startswith("/dashboard"):
        return "Staff dashboards and reports", "Staff dashboard", "Role-based dashboard, reports, analytics, maps, review queues, or operational workflow."
    if route.startswith("/api/") or "api" in src:
        return "API surface", "API", "Application programming interface used by platform clients."
    if route.startswith("/workforce"):
        return "Workforce registry workflow", "Staff/workforce", "Registration, application, professional record, import, and approval workflow."
    if route.startswith("/records"):
        return "Records Hub", "Staff/records", "Controlled record and reference-table management."
    if route.startswith("/notifications"):
        return "Notifications and helpdesk", "Staff/support", "Notifications, enquiries, communications, and helpdesk workflow."
    if route.startswith("/ocr"):
        return "OCR import", "Staff/import", "OCR import and document extraction workflow."
    return "Platform routing", "Route", "Platform route or mounted application surface."


def build_code_inventory() -> list[dict[str, str | int]]:
    rows = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_EXTENSIONS or is_excluded(path):
            continue
        area, component = area_for_path(path)
        purpose, evidence_type, evidence_use = purpose_for_path(path)
        rows.append(
            {
                "Area": area,
                "Component": component,
                "Inventory Type": evidence_type,
                "File Type": file_type(path),
                "Purpose": purpose,
                "Evidence Use": evidence_use,
                "Lines": line_count(path),
                "Path": str(path.relative_to(ROOT)),
            }
        )
    return rows


def build_entity_inventory() -> list[dict[str, str | int]]:
    class_re = re.compile(r"^class\s+(\w+)\(([^)]*)\):")
    all_classes: list[tuple[str, Path, int, str, str]] = []
    for path in sorted((ROOT / "apps").glob("*/models.py")):
        app = path.parent.name
        for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            match = class_re.match(line.strip())
            if match:
                all_classes.append((app, path, line_no, match.group(1), match.group(2)))

    known_model_classes: set[str] = set()
    changed = True
    while changed:
        changed = False
        for _, _, _, name, bases in all_classes:
            base_names = [base.strip().split(".")[-1] for base in bases.split(",")]
            direct = "models.Model" in bases or "AbstractUser" in bases or "AbstractBaseUser" in bases
            inherited = any(base in known_model_classes for base in base_names)
            if (direct or inherited) and name not in known_model_classes:
                known_model_classes.add(name)
                changed = True

    rows = []
    for app, path, line_no, name, bases in all_classes:
        if name not in known_model_classes:
            continue
        domain, entity_type, purpose = entity_domain(name, app)
        rows.append(
            {
                "App": app,
                "Domain": domain,
                "Entity": name,
                "Entity Type": entity_type,
                "Plain English Purpose": purpose,
                "Source": str(path.relative_to(ROOT)),
                "Line": line_no,
                "Base": bases,
            }
        )
    return rows


def build_route_inventory() -> list[dict[str, str | int]]:
    route_re = re.compile(r"path\((['\"])(.*?)\1\s*,\s*([^,)]+)")
    rows = []
    for path in sorted(ROOT.rglob("urls.py")) + sorted(ROOT.rglob("record_urls.py")):
        if is_excluded(path):
            continue
        source = str(path.relative_to(ROOT))
        prefix = PREFIX_BY_SOURCE.get(source, "/")
        for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if "path(" not in line and "re_path(" not in line:
                continue
            local_route = ""
            target = line.strip()
            match = route_re.search(line)
            if match:
                local_route = match.group(2)
                target = match.group(3).strip()
            full_route = clean_route(prefix, local_route)
            area, access, purpose = route_area_and_purpose(source, full_route, target)
            rows.append(
                {
                    "Area": area,
                    "Access Level": access,
                    "Full Route": full_route,
                    "Local Route": local_route or "(index)",
                    "Target": target,
                    "Purpose": purpose,
                    "Source": source,
                    "Line": line_no,
                }
            )
    return rows


def write_csv(path: Path, rows: list[dict[str, str | int]], fields: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    output_path = path
    try:
        handle = output_path.open("w", newline="", encoding="utf-8-sig")
    except PermissionError:
        output_path = path.with_name(f"{path.stem}_readable{path.suffix}")
        print(f"LOCKED={path}")
        print(f"FALLBACK={output_path}")
        handle = output_path.open("w", newline="", encoding="utf-8-sig")
    with handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return output_path


def summary_rows(rows: list[dict[str, str | int]], key: str, sum_key: str | None = None) -> list[dict[str, str | int]]:
    counts = Counter(str(row[key]) for row in rows)
    sums: defaultdict[str, int] = defaultdict(int)
    if sum_key:
        for row in rows:
            sums[str(row[key])] += int(row.get(sum_key) or 0)
    output = []
    for item, count in counts.most_common():
        row: dict[str, str | int] = {key: item, "Count": count}
        if sum_key:
            row[f"Total {sum_key}"] = sums[item]
        output.append(row)
    return output


def draw_bar_chart(data: list[tuple[str, int]], title: str, path: Path, value_label: str) -> None:
    width, height = 1500, max(650, 180 + len(data) * 54)
    margin_left, margin_right, margin_top, margin_bottom = 430, 110, 110, 70
    chart_width = width - margin_left - margin_right
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title_font = font(34, bold=True)
    label_font = font(20)
    small_font = font(17)
    draw.text((40, 32), title, fill=(10, 43, 69), font=title_font)
    draw.text((40, 76), f"Generated {DATE_TEXT}", fill=(80, 98, 110), font=small_font)
    max_value = max((value for _, value in data), default=1)
    y = margin_top
    colors = [(20, 90, 99), (22, 116, 92), (176, 126, 36), (22, 105, 140)]
    for index, (label, value) in enumerate(data):
        bar_width = int((value / max_value) * chart_width) if max_value else 0
        draw.text((40, y + 8), label[:46], fill=(20, 32, 44), font=label_font)
        color = colors[index % len(colors)]
        draw.rounded_rectangle(
            (margin_left, y, margin_left + bar_width, y + 32),
            radius=8,
            fill=color,
        )
        draw.text((margin_left + bar_width + 14, y + 5), f"{value:,} {value_label}", fill=(20, 32, 44), font=small_font)
        y += 54
    draw.line((margin_left, margin_top - 12, margin_left, height - margin_bottom), fill=(210, 220, 226), width=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def draw_overview_card(metrics: dict[str, int], path: Path) -> None:
    image = Image.new("RGB", (1600, 900), (246, 250, 252))
    draw = ImageDraw.Draw(image)
    title_font = font(42, bold=True)
    metric_font = font(42, bold=True)
    label_font = font(22, bold=True)
    body_font = font(18)
    draw.text((60, 44), "Inventory Evidence Dashboard", fill=(10, 43, 69), font=title_font)
    draw.text((60, 98), f"Readable inventory pack generated {DATE_TEXT}", fill=(70, 91, 105), font=body_font)
    cards = [
        ("Source files", metrics["source_files"], "Clean code and documentation inventory"),
        ("Source lines", metrics["source_lines"], "Total readable source and evidence lines"),
        ("Entities", metrics["entities"], "Django model/entity definitions"),
        ("Routes", metrics["routes"], "Public, staff, API, and workflow URL surfaces"),
        ("Graphics", metrics["graphics"], "PNG charts plus Excel workbook charts"),
        ("Summaries", metrics["summaries"], "Business-readable summary CSV files"),
    ]
    card_w, card_h = 460, 210
    start_x, start_y = 60, 170
    for idx, (label, value, note) in enumerate(cards):
        col = idx % 3
        row = idx // 3
        x = start_x + col * 510
        y = start_y + row * 260
        fill = (255, 255, 255)
        outline = (202, 218, 226)
        draw.rounded_rectangle((x, y, x + card_w, y + card_h), radius=18, fill=fill, outline=outline, width=2)
        draw.text((x + 28, y + 26), f"{value:,}", fill=(20, 90, 99), font=metric_font)
        draw.text((x + 28, y + 90), label, fill=(10, 43, 69), font=label_font)
        draw.text((x + 28, y + 128), note, fill=(70, 91, 105), font=body_font)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def write_excel(
    code_rows: list[dict[str, str | int]],
    entity_rows: list[dict[str, str | int]],
    route_rows: list[dict[str, str | int]],
    code_summary: list[dict[str, str | int]],
    entity_summary: list[dict[str, str | int]],
    route_summary: list[dict[str, str | int]],
    graphics: list[Path],
) -> Path:
    workbook_path = PACK / "formal_valuation_inventory_readable.xlsx"
    workbook = xlsxwriter.Workbook(str(workbook_path))
    header = workbook.add_format({"bold": True, "bg_color": "#0A2B45", "font_color": "white", "border": 1})
    wrap = workbook.add_format({"text_wrap": True, "valign": "top"})
    number = workbook.add_format({"num_format": "#,##0"})
    title = workbook.add_format({"bold": True, "font_size": 16, "font_color": "#0A2B45"})

    def add_table(sheet_name: str, rows: list[dict[str, str | int]], fields: list[str], widths: list[int]) -> None:
        ws = workbook.add_worksheet(sheet_name[:31])
        for col, field in enumerate(fields):
            ws.write(0, col, field, header)
            ws.set_column(col, col, widths[col], wrap)
        for row_idx, row in enumerate(rows, 1):
            for col, field in enumerate(fields):
                value = row.get(field, "")
                fmt = number if isinstance(value, int) else wrap
                ws.write(row_idx, col, value, fmt)
        ws.autofilter(0, 0, len(rows), len(fields) - 1)
        ws.freeze_panes(1, 0)

    add_table(
        "Code Inventory",
        code_rows,
        ["Area", "Component", "Inventory Type", "File Type", "Purpose", "Evidence Use", "Lines", "Path"],
        [34, 18, 22, 18, 28, 44, 12, 64],
    )
    add_table(
        "Database Entities",
        entity_rows,
        ["App", "Domain", "Entity", "Entity Type", "Plain English Purpose", "Source", "Line", "Base"],
        [18, 28, 28, 24, 48, 42, 10, 24],
    )
    add_table(
        "URL Surface",
        route_rows,
        ["Area", "Access Level", "Full Route", "Local Route", "Target", "Purpose", "Source", "Line"],
        [28, 18, 42, 30, 34, 54, 42, 10],
    )

    summary = workbook.add_worksheet("Summary Charts")
    summary.write("A1", "Readable Platform Inventory Summary", title)
    summary.write("A2", f"Generated {DATE_TEXT}")

    def write_summary_block(start_row: int, start_col: int, label: str, rows: list[dict[str, str | int]], key: str, value_key: str) -> tuple[int, int]:
        summary.write(start_row, start_col, label, header)
        summary.write(start_row, start_col + 1, value_key, header)
        for idx, row in enumerate(rows, start_row + 1):
            summary.write(idx, start_col, row[key])
            summary.write(idx, start_col + 1, row[value_key], number)
        return start_row + 1, start_row + len(rows)

    c_first, c_last = write_summary_block(4, 0, "Code area", code_summary, "Area", "Total Lines")
    e_first, e_last = write_summary_block(4, 4, "Entity domain", entity_summary, "Domain", "Count")
    r_first, r_last = write_summary_block(4, 8, "Route access", route_summary, "Access Level", "Count")

    chart1 = workbook.add_chart({"type": "bar"})
    chart1.add_series({"name": "Lines", "categories": ["Summary Charts", c_first, 0, c_last, 0], "values": ["Summary Charts", c_first, 1, c_last, 1]})
    chart1.set_title({"name": "Code Lines By Area"})
    chart1.set_legend({"none": True})
    summary.insert_chart("A22", chart1, {"x_scale": 1.4, "y_scale": 1.3})

    chart2 = workbook.add_chart({"type": "column"})
    chart2.add_series({"name": "Entities", "categories": ["Summary Charts", e_first, 4, e_last, 4], "values": ["Summary Charts", e_first, 5, e_last, 5]})
    chart2.set_title({"name": "Entities By Domain"})
    chart2.set_legend({"none": True})
    summary.insert_chart("I22", chart2, {"x_scale": 1.25, "y_scale": 1.3})

    chart3 = workbook.add_chart({"type": "pie"})
    chart3.add_series({"name": "Routes", "categories": ["Summary Charts", r_first, 8, r_last, 8], "values": ["Summary Charts", r_first, 9, r_last, 9]})
    chart3.set_title({"name": "Routes By Access Level"})
    summary.insert_chart("A43", chart3, {"x_scale": 1.2, "y_scale": 1.2})

    images = workbook.add_worksheet("PNG Graphics")
    images.write("A1", "Generated PNG graphics", title)
    row = 3
    for graphic in graphics:
        images.write(row, 0, graphic.name)
        images.insert_image(row + 1, 0, str(graphic), {"x_scale": 0.42, "y_scale": 0.42})
        row += 24

    workbook.close()
    return workbook_path


def main() -> None:
    PACK.mkdir(parents=True, exist_ok=True)
    GRAPHICS.mkdir(parents=True, exist_ok=True)

    code_rows = build_code_inventory()
    entity_rows = build_entity_inventory()
    route_rows = build_route_inventory()

    code_csv_path = write_csv(PACK / "code_inventory.csv", code_rows, ["Area", "Component", "Inventory Type", "File Type", "Purpose", "Evidence Use", "Lines", "Path"])
    entity_csv_path = write_csv(PACK / "database_entity_inventory.csv", entity_rows, ["App", "Domain", "Entity", "Entity Type", "Plain English Purpose", "Source", "Line", "Base"])
    route_csv_path = write_csv(PACK / "url_surface_inventory.csv", route_rows, ["Area", "Access Level", "Full Route", "Local Route", "Target", "Purpose", "Source", "Line"])

    code_summary = summary_rows(code_rows, "Area", "Lines")
    entity_summary = summary_rows(entity_rows, "Domain")
    route_summary = summary_rows(route_rows, "Access Level")
    # Rename one summary key for easier Excel chart labels.
    for row in code_summary:
        row["Total Lines"] = row.pop("Total Lines")

    write_csv(PACK / "code_inventory_summary_by_area.csv", code_summary, ["Area", "Count", "Total Lines"])
    write_csv(PACK / "database_entity_summary_by_domain.csv", entity_summary, ["Domain", "Count"])
    write_csv(PACK / "url_surface_summary_by_access.csv", route_summary, ["Access Level", "Count"])

    top_code = [(str(row["Area"]), int(row["Total Lines"])) for row in code_summary[:12]]
    top_entities = [(str(row["Domain"]), int(row["Count"])) for row in entity_summary]
    top_routes = [(str(row["Access Level"]), int(row["Count"])) for row in route_summary]

    code_chart = GRAPHICS / "code_lines_by_area.png"
    entity_chart = GRAPHICS / "database_entities_by_domain.png"
    route_chart = GRAPHICS / "url_routes_by_access_level.png"
    overview_chart = GRAPHICS / "inventory_evidence_dashboard.png"
    draw_bar_chart(top_code, "Code And Documentation Lines By Area", code_chart, "lines")
    draw_bar_chart(top_entities, "Database Entities By Functional Domain", entity_chart, "entities")
    draw_bar_chart(top_routes, "URL Routes By Access Level", route_chart, "routes")
    draw_overview_card(
        {
            "source_files": len(code_rows),
            "source_lines": sum(int(row["Lines"]) for row in code_rows),
            "entities": len(entity_rows),
            "routes": len(route_rows),
            "graphics": 4,
            "summaries": 3,
        },
        overview_chart,
    )
    graphics = [overview_chart, code_chart, entity_chart, route_chart]
    workbook_path = write_excel(code_rows, entity_rows, route_rows, code_summary, entity_summary, route_summary, graphics)

    readme = PACK / "inventory_readme.md"
    readme.write_text(
        f"""# Readable Inventory Pack

Generated: {DATE_TEXT}

This folder contains regenerated business-readable inventory files for the formal valuation evidence pack.

## Main inventory files

- `{code_csv_path.name}`: clean source/documentation inventory with area, component, purpose, evidence use, line count, and path.
- `{entity_csv_path.name}`: Django model/entity inventory with functional domain and plain-English purpose.
- `{route_csv_path.name}`: public, staff, API, mobile, records, documents, and workflow URL surface inventory.

## Summary files

- `code_inventory_summary_by_area.csv`
- `database_entity_summary_by_domain.csv`
- `url_surface_summary_by_access.csv`

## Graphics and workbook

- `inventory_graphics/inventory_evidence_dashboard.png`
- `inventory_graphics/code_lines_by_area.png`
- `inventory_graphics/database_entities_by_domain.png`
- `inventory_graphics/url_routes_by_access_level.png`
- `formal_valuation_inventory_readable.xlsx`

## Current counts

- Inventory files: {len(code_rows):,}
- Inventory lines: {sum(int(row["Lines"]) for row in code_rows):,}
- Database/entity rows: {len(entity_rows):,}
- URL route rows: {len(route_rows):,}
""",
        encoding="utf-8",
    )

    print(f"CODE_CSV={code_csv_path}")
    print(f"ENTITY_CSV={entity_csv_path}")
    print(f"ROUTE_CSV={route_csv_path}")
    print(f"WORKBOOK={workbook_path}")
    print(f"GRAPHICS={GRAPHICS}")
    print(f"SUMMARY=files:{len(code_rows)} lines:{sum(int(row['Lines']) for row in code_rows)} entities:{len(entity_rows)} routes:{len(route_rows)}")


if __name__ == "__main__":
    main()
