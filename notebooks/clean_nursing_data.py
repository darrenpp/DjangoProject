import pandas as pd
import re
from datetime import timedelta

# ====================== CONFIG ======================
input_file = 'DATA_school_full_license2024_2025.xlsx'

print("🚀 Starting data cleansing for both sheets...\n")

# ====================== LOAD BOTH SHEETS ======================
prov_df = pd.read_excel(input_file, sheet_name='PROV REGO 17,18,19 & 20, 21', header=3)
full_df = pd.read_excel(input_file, sheet_name='FULL REGO 2009 - current', header=3)

print("Provisional sheet columns:", len(prov_df.columns), list(prov_df.columns)[:5])
print("Full sheet columns:", len(full_df.columns), list(full_df.columns)[:5])
print()

prov_df['source_sheet'] = 'Provisional'
prov_df['original_row'] = prov_df.index + 5

full_df['source_sheet'] = 'Full'
full_df['original_row'] = full_df.index + 5

print(f"Loaded Provisional sheet: {len(prov_df):,} rows")
print(f"Loaded Full sheet: {len(full_df):,} rows\n")


# ====================== CLEAN NAMES ======================
def clean_name(name):
    if pd.isna(name) or str(name).strip() == "":
        return ""
    name = str(name).strip()
    name = re.sub(r'\s+', ' ', name)
    return name.title()


for df in [prov_df, full_df]:
    if 'NAME' in df.columns:
        df['full_name'] = df['NAME'].apply(clean_name)
        df['first_name'] = df['full_name'].apply(lambda x: x.split()[0] if x else "")
        df['last_name'] = df['full_name'].apply(lambda x: ' '.join(x.split()[1:]) if x else "")

# ====================== ROBUST DATE CONVERSION ======================
for df in [prov_df, full_df]:
    col = 'ISSUED DATE'
    if col in df.columns:
        # First try direct conversion
        df['issued_date'] = pd.to_datetime(df[col], errors='coerce')

        # If most are still NaT, try Excel serial number conversion if column is numeric
        if df['issued_date'].isna().sum() > len(df) * 0.5:
            if pd.api.types.is_numeric_dtype(df[col]):
                df['issued_date'] = pd.to_datetime(df[col], errors='coerce', origin='1899-12-30', unit='D')
            else:
                print(f"Warning: Cannot convert {col} to dates using origin, column is not numeric")

print("Date conversion completed.\n")

# ====================== ESTIMATE EXPIRY DATE ======================
for df in [prov_df, full_df]:
    df['expiry_date'] = pd.NaT
    mask = df['issued_date'].notna()
    # Provisional ≈ 6 months, Full ≈ 3 years
    provisional_mask = mask & df.get('LICENSE', pd.Series([''] * len(df))).astype(str).str.contains('Provisional',
                                                                                                         na=False)
    full_mask = mask & ~df.get('LICENSE', pd.Series([''] * len(df))).astype(str).str.contains('Provisional',
                                                                                                   na=False)

    df.loc[provisional_mask, 'expiry_date'] = df['issued_date'] + timedelta(days=180)
    df.loc[full_mask, 'expiry_date'] = df['issued_date'] + timedelta(days=1095)

# ====================== DUPLICATES ======================
print("🔍 Finding duplicates across both sheets...")

combined = pd.concat([prov_df, full_df], ignore_index=True)
combined['duplicate_key'] = combined['full_name'].astype(str) + " | " + combined['NO.'].astype(str)

duplicates = combined[combined.duplicated(subset=['duplicate_key'], keep=False)].copy()
duplicates = duplicates.sort_values(['duplicate_key', 'source_sheet', 'original_row'])

print(f"✅ Found {len(duplicates):,} duplicate records\n")

# ====================== MISSING INFORMATION ======================
print("📋 Generating missing information report...")

missing_list = []
for df in [prov_df, full_df]:
    for idx, row in df.iterrows():
        issues = []
        if pd.isna(row.get('full_name')) or str(row.get('full_name', '')).strip() == "":
            issues.append("Missing Name")
        elif not row.get('first_name') or not row.get('last_name'):
            issues.append("Missing First/Last Name split")
        if pd.isna(row.get('issued_date')):
            issues.append("Missing Issued Date")
        if pd.isna(row.get('expiry_date')):
            issues.append("Missing Expiry Date")
        if issues:
            missing_list.append({
                'source_sheet': row['source_sheet'],
                'original_row': int(row['original_row']),
                'full_name': row.get('full_name', ''),
                'reg_no': row.get('NO.', ''),
                'missing_fields': ", ".join(issues)
            })

missing_df = pd.DataFrame(missing_list)

# ====================== SAVE FILES ======================
duplicates.to_csv('DUPLICATES_combined.csv', index=False)
missing_df.to_csv('MISSING_information.csv', index=False)
combined.to_csv('cleaned_combined_nursing_data.csv', index=False)

print("\n🎉 CLEANING COMPLETED!")
print(f"   • Duplicates found          : {len(duplicates):,} → DUPLICATES_combined.csv")
print(f"   • Records with missing info : {len(missing_df):,} → MISSING_information.csv")
print(f"   • Clean combined data       : cleaned_combined_nursing_data.csv")
print("\nYou can now open these files in Excel.")