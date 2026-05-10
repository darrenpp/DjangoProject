import pandas as pd

input_file = 'DATA_school_full_license2024_2025.xlsx'

xls = pd.ExcelFile(input_file)
print("Sheet names:", xls.sheet_names)

for sheet in xls.sheet_names[:2]:  # Limit to first 2
    df = pd.read_excel(input_file, sheet_name=sheet, header=3, nrows=5)
    print(f"\nSheet: {sheet}")
    print("Columns:", list(df.columns))
    print("First 5 rows:")
    print(df.head())
