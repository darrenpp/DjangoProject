import calendar
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd


WORKBOOK_PATH = Path("notebooks") / "Provional_Cleansed_data2009_2026.xlsx"
DEFAULT_SHEET = "Provisional_License_Data2009_26"
OUTPUT_CLEAN = Path("notebooks") / "provisional_graduands_cleaned.csv"
OUTPUT_ISSUES = Path("notebooks") / "provisional_graduands_quality_issues.csv"
OUTPUT_SUMMARY = Path("notebooks") / "provisional_graduands_summary.txt"

VALID_MIN_YEAR = 2009
VALID_MAX_YEAR = 2026

FOREIGN_KEYWORDS = [
    "america", "american", "philippines", "philippine", "philipine", "india",
    "italy", "fiji", "china", "australia", "auckland", "new zealand", "new zealand", "new zeland", "nz",
    "uk", "united kingdom", "usa", "united states", "kenya", "uganda", "japan",
    "malaysia", "singapore", "canada", "indonesia", "thailand",
]

MONTH_FIXES = {
    "Agu": "Aug",
    "Ago": "Aug",
    "Sept": "Sep",
    "Set": "Sep",
    "Mac": "Mar",
}


@dataclass
class CleanseResult:
    cleaned: pd.DataFrame
    issues: pd.DataFrame


def normalize_text(value):
    if pd.isna(value):
        return ""
    text = str(value).strip()
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_name(value):
    text = normalize_text(value)
    if not text:
        return ""
    return text.title()


def split_name(full_name):
    parts = normalize_text(full_name).split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def safe_date(year_value, month_value, day_value):
    if pd.isna(year_value):
        return pd.NaT
    year_value = int(year_value)
    month_value = max(1, min(12, int(month_value)))
    max_day = calendar.monthrange(year_value, month_value)[1]
    day_value = max(1, min(max_day, int(day_value)))
    return pd.Timestamp(date(year_value, month_value, day_value))


def parse_issued_date(raw_value, graduation_year):
    if pd.isna(raw_value):
        return pd.NaT, "missing_issued_date"

    if isinstance(raw_value, pd.Timestamp):
        parsed = raw_value
    else:
        text = normalize_text(raw_value)
        if not text or text.lower() == "nan":
            return pd.NaT, "missing_issued_date"

        for bad, good in MONTH_FIXES.items():
            text = text.replace(bad, good)

        if re.match(r"^\d{4}-\d{2}-\d{2}( \d{2}:\d{2}:\d{2}(\.\d+)?)?$", text):
            parsed = pd.to_datetime(text, errors="coerce", dayfirst=False)
            if not pd.isna(parsed):
                parsed = pd.Timestamp(parsed).normalize()
                if parsed.year < VALID_MIN_YEAR and pd.notna(graduation_year):
                    repaired = safe_date(int(graduation_year), parsed.month, parsed.day)
                    return repaired, "repaired_placeholder_year"
                if parsed.year > VALID_MAX_YEAR and pd.notna(graduation_year):
                    repaired = safe_date(int(graduation_year), parsed.month, parsed.day)
                    return repaired, "repaired_future_year"
                return parsed, "valid"

        special = re.match(r"^(\d{1,2})\s+([A-Za-z]{3})\s*-\s*(\d{2})$", text)
        if special:
            day_value = int(special.group(1))
            month_text = special.group(2)
            year_value = int(f"20{special.group(3)}")
            month_value = pd.to_datetime(month_text, format="%b", errors="coerce")
            if not pd.isna(month_value):
                parsed = safe_date(year_value, month_value.month, day_value)
                if not pd.isna(parsed):
                    return parsed, "normalized_text_date"

        parsed = pd.NaT
        for dayfirst in (True, False):
            attempt = pd.to_datetime(text, errors="coerce", dayfirst=dayfirst)
            if not pd.isna(attempt):
                parsed = attempt
                break

    if pd.isna(parsed):
        return pd.NaT, "unparsed_issued_date"

    parsed = pd.Timestamp(parsed).normalize()

    if parsed.year < VALID_MIN_YEAR and pd.notna(graduation_year):
        repaired = safe_date(int(graduation_year), parsed.month, parsed.day)
        return repaired, "repaired_placeholder_year"

    if parsed.year > VALID_MAX_YEAR and pd.notna(graduation_year):
        repaired = safe_date(int(graduation_year), parsed.month, parsed.day)
        return repaired, "repaired_future_year"

    return parsed, "valid"


def infer_applicant_type(institution_name):
    institution_lower = normalize_text(institution_name).lower()
    if any(keyword in institution_lower for keyword in FOREIGN_KEYWORDS):
        return "overseas"
    return "national"


def infer_profession_track(qualification_name):
    qualification_lower = normalize_text(qualification_name).lower()
    if "midw" in qualification_lower:
        return "midwifery"
    return "nursing"


def cleanse_workbook(workbook_path=WORKBOOK_PATH, sheet_name=DEFAULT_SHEET):
    df = pd.read_excel(workbook_path, sheet_name=sheet_name)
    df.columns = [normalize_text(col) for col in df.columns]

    required_columns = [
        "ID", "Name", "License Type", "Provisional/No", "Issued_Date",
        "Institution_Attended", "Year", "Qualification",
    ]
    missing = [col for col in required_columns if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")

    for col in ["Name", "License Type", "Institution_Attended", "Qualification"]:
        df[col] = df[col].apply(normalize_text)

    df["source_id"] = pd.to_numeric(df["ID"], errors="coerce")
    df["provisional_no"] = pd.to_numeric(df["Provisional/No"], errors="coerce")
    df["graduation_year"] = pd.to_numeric(df["Year"], errors="coerce")
    df["full_name"] = df["Name"].apply(normalize_name)
    df["institution_name"] = df["Institution_Attended"].apply(normalize_text)
    df["qualification_name"] = df["Qualification"].apply(normalize_text)

    df = df[
        (df["full_name"] != "") &
        (df["License Type"].str.contains("Provisional", case=False, na=False)) &
        (df["provisional_no"].notna())
    ].copy()

    issued_values = df.apply(
        lambda row: parse_issued_date(row["Issued_Date"], row["graduation_year"]),
        axis=1,
    )
    df["issued_date"] = [item[0] for item in issued_values]
    df["issued_date_status"] = [item[1] for item in issued_values]

    name_parts = df["full_name"].apply(split_name)
    df["first_name"] = [part[0] for part in name_parts]
    df["last_name"] = [part[1] for part in name_parts]

    df["applicant_type"] = df["institution_name"].apply(infer_applicant_type)
    df["profession_track"] = df["qualification_name"].apply(infer_profession_track)
    df["pathway"] = df.apply(
        lambda row: (
            "overseas_midwife" if row["applicant_type"] == "overseas" and row["profession_track"] == "midwifery"
            else "overseas_nurse" if row["applicant_type"] == "overseas"
            else "local_midwifery_graduate" if row["profession_track"] == "midwifery"
            else "local_nursing_graduate"
        ),
        axis=1,
    )

    def build_registration_no(row):
        if pd.notna(row["source_id"]):
            return f"GRAD-PROV-{int(row['source_id'])}"
        return f"GRAD-PROVNO-{int(row['provisional_no'])}"

    df["registration_no"] = df.apply(build_registration_no, axis=1)
    df["dedupe_key"] = df["registration_no"]
    df = df.drop_duplicates(subset=["dedupe_key"], keep="first").copy()

    issues = []
    for _, row in df.iterrows():
        row_issues = []
        if pd.isna(row["issued_date"]):
            row_issues.append("Missing or invalid issued date")
        if not row["institution_name"]:
            row_issues.append("Missing institution")
        if not row["qualification_name"]:
            row_issues.append("Missing qualification")
        if pd.isna(row["graduation_year"]):
            row_issues.append("Missing graduation year")
        if row["issued_date_status"] != "valid":
            row_issues.append(f"Issued date status: {row['issued_date_status']}")
        if row_issues:
            issues.append({
                "registration_no": row["registration_no"],
                "source_id": row["source_id"],
                "full_name": row["full_name"],
                "provisional_no": row["provisional_no"],
                "issued_date_raw": row["Issued_Date"],
                "issued_date_clean": row["issued_date"],
                "issues": "; ".join(row_issues),
            })

    cleaned = df[
        [
            "registration_no",
            "source_id",
            "full_name",
            "first_name",
            "last_name",
            "provisional_no",
            "issued_date",
            "issued_date_status",
            "institution_name",
            "graduation_year",
            "qualification_name",
            "applicant_type",
            "profession_track",
            "pathway",
        ]
    ].copy()

    return CleanseResult(cleaned=cleaned, issues=pd.DataFrame(issues))


def export_outputs(result: CleanseResult):
    result.cleaned.to_csv(OUTPUT_CLEAN, index=False)
    result.issues.to_csv(OUTPUT_ISSUES, index=False)

    summary_lines = [
        "Provisional Graduands Cleansing Summary",
        f"Cleaned records: {len(result.cleaned)}",
        f"Quality issue records: {len(result.issues)}",
        f"National records: {(result.cleaned['applicant_type'] == 'national').sum()}",
        f"Overseas records: {(result.cleaned['applicant_type'] == 'overseas').sum()}",
        f"Nursing track: {(result.cleaned['profession_track'] == 'nursing').sum()}",
        f"Midwifery track: {(result.cleaned['profession_track'] == 'midwifery').sum()}",
        f"Missing issued dates: {result.cleaned['issued_date'].isna().sum()}",
        f"Unique institutions: {result.cleaned['institution_name'].nunique()}",
    ]
    OUTPUT_SUMMARY.write_text("\n".join(summary_lines), encoding="utf-8")


if __name__ == "__main__":
    result = cleanse_workbook()
    export_outputs(result)
    print(f"Cleaned records written to: {OUTPUT_CLEAN}")
    print(f"Quality issues written to: {OUTPUT_ISSUES}")
    print(f"Summary written to: {OUTPUT_SUMMARY}")
