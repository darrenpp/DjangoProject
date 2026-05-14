import pandas as pd
import numpy as np
import re
from pathlib import Path

# ====================== CONFIG ======================
input_file = Path(__file__).resolve().parent / "DATA_school_full_license2024_2025.xlsx"
output_dir = Path(".")
output_dir.mkdir(exist_ok=True)

print("🚀 Starting data cleansing for both sheets...\n")

# ====================== LOAD BOTH SHEETS ======================
prov_df = pd.read_excel(input_file, sheet_name="PROV REGO 17,18,19 & 20, 21", header=3)
full_df = pd.read_excel(input_file, sheet_name="FULL REGO 2009 - current", header=3)

print(f"Loaded Provisional sheet: {len(prov_df):,} rows")
print(f"Loaded Full sheet: {len(full_df):,} rows")

# ====================== BASIC CLEANING ======================
def clean_name(name):
    if pd.isna(name):
        return ""
    name = str(name).strip()
    name = re.sub(r'\s+', ' ', name)  # Remove extra spaces
    return name.title()

for df in [prov_df, full_df]:
    if 'NAME' in df.columns:
        df['clean_name'] = df['NAME'].apply(clean_name)
    if 'REG NO' in df.columns:
        df['reg_no'] = df['REG NO'].astype(str).str.strip()
    if 'ISSUED DATE' in df.columns:
        df['issued_date'] = pd.to_datetime(df['ISSUED DATE'], errors='coerce')

# Create a unique key for duplicate detection
for df in [prov_df, full_df]:
    df['duplicate_key'] = df['clean_name'] + " | " + df.get('reg_no', pd.Series([""]*len(df)))

# ====================== COMBINE BOTH SHEETS ======================
prov_df['source'] = 'Provisional'
full_df['source'] = 'Full'

combined = pd.concat([prov_df, full_df], ignore_index=True)

# ====================== 1. DUPLICATES ======================
duplicates = combined[combined.duplicated(subset=['duplicate_key'], keep=False)].sort_values('duplicate_key')

print(f"Found {len(duplicates)} duplicate records (including originals)")

duplicates.to_csv(output_dir / "DUPLICATES_combined.csv", index=False)
print("✅ DUPLICATES_combined.csv created")

# ====================== 2. MISSING INFORMATION ======================
missing_list = []

for idx, row in combined.iterrows():
    issues = []
    if pd.isna(row.get('clean_name')) or row.get('clean_name') == "":
        issues.append("Missing Name")
    if pd.isna(row.get('reg_no')) or str(row.get('reg_no')).strip() in ["", "nan"]:
        issues.append("Missing Reg No")
    if pd.isna(row.get('issued_date')):
        issues.append("Missing Issued Date")
    if pd.isna(row.get('QUALIFICATION')) or str(row.get('QUALIFICATION')).strip() in ["", "nan"]:
        issues.append("Missing Qualification")

    if issues:
        missing_list.append({
            'Row_Number': idx + 1,   # Excel row number (approximate)
            'Sheet': row['source'],
            'Name': row.get('clean_name'),
            'Reg_No': row.get('reg_no'),
            'Issued_Date': row.get('issued_date'),
            'Missing_Fields': ", ".join(issues)
        })

missing_df = pd.DataFrame(missing_list)
missing_df.to_csv(output_dir / "MISSING_information.csv", index=False)
print(f"✅ MISSING_information.csv created ({len(missing_df)} records with issues)")

# ====================== 3. CLEANED COMBINED DATA ======================
# Keep only useful columns and drop exact duplicate rows
cleaned = combined.drop_duplicates(subset=['duplicate_key']).copy()

# Final column selection
final_columns = ['clean_name', 'reg_no', 'issued_date', 'QUALIFICATION', 'source',
                 'INSTITUTION ATTENDED', 'YEAR', 'duplicate_key']

cleaned = cleaned[[col for col in final_columns if col in cleaned.columns]]

cleaned.to_csv(output_dir / "cleaned_combined_nursing_data.csv", index=False)
print("✅ cleaned_combined_nursing_data.csv created")

print("\n🎉 All files generated successfully in the current folder!")
print("Files created:")
print("   • DUPLICATES_combined.csv")
print("   • MISSING_information.csv")
print("   • cleaned_combined_nursing_data.csv")
