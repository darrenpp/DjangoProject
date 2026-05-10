from pathlib import Path
import re

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


BASE_DIR = Path(__file__).resolve().parents[1]
DOCS_DIR = BASE_DIR / "docs"
LOGO_PATH = BASE_DIR / "static" / "img" / "NDOH_LOGO.png"
PROJECT_TITLE = "The National Department Of Health Regulatory Bodies Nursing Council & The Medical Board Online Workforce System"
DATE_TEXT = "07 May 2026"


styles = getSampleStyleSheet()
styles.add(ParagraphStyle(
    name="CoverTitle",
    parent=styles["Title"],
    fontName="Helvetica-Bold",
    fontSize=18,
    leading=23,
    alignment=TA_CENTER,
    spaceAfter=16,
    textColor=colors.HexColor("#073B4C"),
))
styles.add(ParagraphStyle(
    name="CoverSub",
    parent=styles["Normal"],
    fontSize=11,
    leading=15,
    alignment=TA_CENTER,
    textColor=colors.HexColor("#34495E"),
))
styles.add(ParagraphStyle(
    name="HeadingOne",
    parent=styles["Heading1"],
    fontName="Helvetica-Bold",
    fontSize=15,
    leading=18,
    spaceBefore=14,
    spaceAfter=8,
    textColor=colors.HexColor("#0B5D5E"),
))
styles.add(ParagraphStyle(
    name="HeadingTwo",
    parent=styles["Heading2"],
    fontName="Helvetica-Bold",
    fontSize=12,
    leading=15,
    spaceBefore=10,
    spaceAfter=6,
    textColor=colors.HexColor("#12324A"),
))
styles.add(ParagraphStyle(
    name="BodyClean",
    parent=styles["BodyText"],
    fontSize=9.2,
    leading=12.5,
    spaceAfter=5,
))
styles.add(ParagraphStyle(
    name="Small",
    parent=styles["BodyText"],
    fontSize=8,
    leading=10,
))
styles.add(ParagraphStyle(
    name="CodeBlock",
    parent=styles["Code"],
    fontName="Courier",
    fontSize=7.5,
    leading=9.5,
    backColor=colors.HexColor("#F3F6F7"),
    borderColor=colors.HexColor("#D9E2E4"),
    borderWidth=0.4,
    borderPadding=5,
    spaceBefore=4,
    spaceAfter=6,
))


def xml_escape(text):
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def clean_inline(text):
    text = xml_escape(text)
    text = re.sub(r"`([^`]+)`", r"<font name='Courier'>\1</font>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", text)
    return text


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#12324A"))
    canvas.drawString(1.5 * cm, 1.1 * cm, "Confidential official system guidance - NDOH regulatory platform")
    canvas.drawRightString(19.5 * cm, 1.1 * cm, f"Page {doc.page}")
    canvas.restoreState()


def cover(title, subtitle):
    story = []
    if LOGO_PATH.exists():
        story.append(Image(str(LOGO_PATH), width=2.8 * cm, height=2.8 * cm))
        story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph("PAPUA NEW GUINEA NATIONAL DEPARTMENT OF HEALTH", styles["CoverSub"]))
    story.append(Paragraph(PROJECT_TITLE, styles["CoverTitle"]))
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph(title, styles["CoverTitle"]))
    story.append(Paragraph(subtitle, styles["CoverSub"]))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(f"Generated: {DATE_TEXT}", styles["CoverSub"]))
    story.append(PageBreak())
    return story


def simple_table(headers, rows, col_widths=None):
    data = [[Paragraph(clean_inline(cell), styles["Small"]) for cell in headers]]
    for row in rows:
        data.append([Paragraph(clean_inline(cell), styles["Small"]) for cell in row])
    table = Table(data, colWidths=col_widths, hAlign="LEFT", repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B7A75")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5D8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F8F8")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def markdown_to_flowables(markdown_text):
    story = []
    lines = markdown_text.splitlines()
    bullet_buffer = []
    table_buffer = []
    code_buffer = []
    in_code = False

    def flush_bullets():
        nonlocal bullet_buffer
        if bullet_buffer:
            items = [
                ListItem(Paragraph(clean_inline(item), styles["BodyClean"]), leftIndent=10)
                for item in bullet_buffer
            ]
            story.append(ListFlowable(items, bulletType="bullet", leftIndent=16))
            story.append(Spacer(1, 0.1 * cm))
            bullet_buffer = []

    def flush_table():
        nonlocal table_buffer
        if table_buffer:
            rows = []
            for row in table_buffer:
                cells = [cell.strip() for cell in row.strip("|").split("|")]
                if all(set(cell.replace(":", "").strip()) <= {"-"} for cell in cells):
                    continue
                rows.append(cells)
            if rows:
                width = 17.2 * cm / max(1, len(rows[0]))
                story.append(simple_table(rows[0], rows[1:], [width] * len(rows[0])))
                story.append(Spacer(1, 0.15 * cm))
            table_buffer = []

    def flush_code():
        nonlocal code_buffer
        if code_buffer:
            story.append(Paragraph("<br/>".join(xml_escape(line) for line in code_buffer), styles["CodeBlock"]))
            code_buffer = []

    for raw_line in lines:
        line = raw_line.rstrip()
        if line.strip().startswith("```"):
            if in_code:
                flush_code()
                in_code = False
            else:
                flush_bullets()
                flush_table()
                in_code = True
            continue
        if in_code:
            code_buffer.append(line)
            continue
        if not line.strip():
            flush_bullets()
            flush_table()
            continue
        if line.startswith("|"):
            flush_bullets()
            table_buffer.append(line)
            continue
        flush_table()
        if line.startswith("# "):
            flush_bullets()
            story.append(Paragraph(clean_inline(line[2:].strip()), styles["HeadingOne"]))
        elif line.startswith("## "):
            flush_bullets()
            story.append(Paragraph(clean_inline(line[3:].strip()), styles["HeadingOne"]))
        elif line.startswith("### "):
            flush_bullets()
            story.append(Paragraph(clean_inline(line[4:].strip()), styles["HeadingTwo"]))
        elif line.startswith("- "):
            bullet_buffer.append(line[2:].strip())
        elif re.match(r"^\d+\.\s+", line):
            bullet_buffer.append(re.sub(r"^\d+\.\s+", "", line).strip())
        else:
            flush_bullets()
            story.append(Paragraph(clean_inline(line), styles["BodyClean"]))

    flush_bullets()
    flush_table()
    flush_code()
    return story


def build_pdf(output_path, title, subtitle, sections):
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=1.4 * cm,
        leftMargin=1.4 * cm,
        topMargin=1.4 * cm,
        bottomMargin=1.7 * cm,
    )
    story = cover(title, subtitle)
    for index, (section_title, body) in enumerate(sections):
        if index:
            story.append(PageBreak())
        story.append(Paragraph(section_title, styles["HeadingOne"]))
        if isinstance(body, str):
            story.extend(markdown_to_flowables(body))
        else:
            story.extend(body)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def implementation_audit_flowables():
    rows = [
        ["Phase 1 Repository Foundation", "Completed and integrated", "apps.documents models, admin, URLs, staff screens, bootstrap_document_repository, 24 folders."],
        ["Phase 2 OCR/Search/Duplicate", "Completed and integrated", "DocumentVersion extracted text, OCR linkage, reference extraction, repository search, checksum duplicate grouping."],
        ["Phase 3 Workflow/Staff Review", "Completed and integrated", "Nursing Council workflow config, checklist review, linked repository evidence on application detail, inbox/access requests."],
        ["Phase 4 Governance/Security", "Completed and integrated", "System Admin-only admin, office scope separation, finance separation, public-safe register, audit events."],
        ["Phase 5 Documentation/Training", "Completed", "Updated manuals, cleansing guide, OpenKM guide, project timeline, and generated PDF handover guides."],
    ]
    flowables = [
        Paragraph("Implementation Audit Against OpenKM Timeline", styles["HeadingTwo"]),
        simple_table(["Timeline area", "Status", "Where implemented"], rows, [4.8 * cm, 3.6 * cm, 8.8 * cm]),
        Spacer(1, 0.2 * cm),
        Paragraph("Plain-language conclusion: the OpenKM-style functions are integrated into the platform. The remaining work is operational adoption: staff must scan paper records, upload evidence, tag metadata, link documents to applications or practitioners, and keep data-quality review active.", styles["BodyClean"]),
    ]
    return flowables


def plain_staff_quick_guide():
    rows = [
        ["System Admin", "Set up users, repository folders, access rules, bootstraps, backups, and production settings."],
        ["Registrar", "Review applications, open linked evidence, verify checklist/payment/competency, approve or reject, and generate reports."],
        ["Reviewer", "Request operational access first. After approval, help review assigned records and evidence only within scope."],
        ["Data Quality Officer", "Review missing data, duplicates, source rows, and repository evidence before reports are published."],
        ["Finance Officer", "Use separated Nursing Council and Medical Board financial forecast pages. Do not edit records or mix office figures."],
        ["Professional / Applicant", "Use own portal, own applications, own receipts, and public-safe forms. Cannot view other people's private records."],
    ]
    return [
        Paragraph("How Staff Use The Platform In Plain Language", styles["HeadingTwo"]),
        simple_table(["Staff group", "What to do"], rows, [4.3 * cm, 12.9 * cm]),
        Spacer(1, 0.2 * cm),
        Paragraph("For documents: open Document Repository, upload the scanned evidence, choose the right office scope, add metadata, link it to the application or practitioner, run OCR if needed, and use the audit trail to prove who viewed, uploaded, downloaded, or changed the record.", styles["BodyClean"]),
    ]


def main():
    user_guide_sections = [
        ("OpenKM Timeline Implementation Check", implementation_audit_flowables()),
        ("Plain Language Staff Guide", plain_staff_quick_guide()),
        ("Main User Manual", (DOCS_DIR / "USER_GUIDE_AND_MANUAL_20260507.md").read_text(encoding="utf-8")),
        ("OpenKM-Style Document Repository Guide", (DOCS_DIR / "OPENKM_FULL_PLATFORM_USER_GUIDE_20260507.md").read_text(encoding="utf-8")),
        ("Data Cleansing And Import Alignment", (DOCS_DIR / "DATA_CLEANSING_AND_IMPORT_ALIGNMENT_PLAN_20260507.md").read_text(encoding="utf-8")),
        ("OpenKM Project Timeline", (DOCS_DIR / "OPENKM_Project_Timeline.md").read_text(encoding="utf-8")),
    ]
    build_pdf(
        DOCS_DIR / "NDOH_Full_Scope_Platform_User_Guide_20260507.pdf",
        "Full-Scope Platform User Guide",
        "Plain-language guide for staff, registrars, administrators, finance, data quality, and document repository users.",
        user_guide_sections,
    )

    documentation_index_sections = [
        ("Documentation Index", (BASE_DIR / "DOCUMENTATION_INDEX.md").read_text(encoding="utf-8")),
        ("Deployment Checklist", (BASE_DIR / "DEPLOYMENT_CHECKLIST.md").read_text(encoding="utf-8")),
        ("System Status Report", (BASE_DIR / "docs" / "status" / "SYSTEM_STATUS_REPORT.md").read_text(encoding="utf-8")),
        ("Project Completion Report", (BASE_DIR / "docs" / "status" / "PROJECT_COMPLETION_REPORT.md").read_text(encoding="utf-8")),
    ]
    build_pdf(
        DOCS_DIR / "NDOH_Documentation_Index_20260507.pdf",
        "Documentation Index",
        "Guide to the current documentation set, operational references, technical files, key screens, and launch checks.",
        documentation_index_sections,
    )

    print(DOCS_DIR / "NDOH_Full_Scope_Platform_User_Guide_20260507.pdf")
    print(DOCS_DIR / "NDOH_Documentation_Index_20260507.pdf")


if __name__ == "__main__":
    main()
