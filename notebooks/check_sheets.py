import pandas as pd

file = 'DATA_school_full_license2024_2025.xlsx'

xls = pd.ExcelFile(file)
print("Available sheets in the file:")
for sheet in xls.sheet_names:
    print(f"   → '{sheet}'")