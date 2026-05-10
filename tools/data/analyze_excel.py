#!/usr/bin/env python
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[2]

# Read the Excel file and check structure
excel_file = BASE_DIR / 'notebooks' / 'DATA_school_full_license2024_2025.xlsx'
if excel_file.exists():
    try:
        # Read first 30 rows without headers to see raw structure
        df_raw = pd.read_excel(excel_file, header=None, nrows=30)
        print('=== RAW FIRST 30 ROWS ===')
        for i in range(min(10, len(df_raw))):  # Limit to first 10 for brevity
            row = df_raw.iloc[i]
            print(f'Row {i}: {list(row)}')

        # Try to identify header row
        print('\n=== IDENTIFYING HEADER ROW ===')
        for idx in range(min(10, len(df_raw))):
            row = df_raw.iloc[idx]
            non_empty = row.dropna()
            if len(non_empty) >= 5:  # Assume header has many columns
                print(f'Potential header at row {idx}: {list(non_empty)}')

        # Based on analysis, data starts at row 2, no headers
        column_names = ['Serial', 'Name', 'Registration_Type', 'Registration_Number', 'Issued_Date', 'Institution', 'Graduation_Year', 'Qualification']
        df = pd.read_excel(excel_file, skiprows=2, header=None, names=column_names)

        # Clean the data: drop rows where Serial or Name is NaN
        df = df.dropna(subset=['Serial', 'Name'])

        print(f'\n=== DATA SHAPE AFTER CLEANING ===')
        print(f'Rows: {len(df)}, Columns: {len(df.columns)}')

        print('\n=== FIRST 20 ROWS WITH ASSIGNED HEADERS ===')
        print(df.head(20))
        print('\n=== COLUMN NAMES ===')
        for i, col in enumerate(df.columns, 1):
            print(f'{i:2d}. {col}')

        # Check data types and non-null counts
        print('\n=== DATA INFO ===')
        print(df.info())

        # Convert dates
        df['Issued_Date'] = pd.to_datetime(df['Issued_Date'], errors='coerce')
        df['Graduation_Year'] = pd.to_numeric(df['Graduation_Year'], errors='coerce')

        print('\n=== UNIQUE VALUES IN KEY COLUMNS ===')
        print('Registration_Type:', df['Registration_Type'].unique())
        print('Institution:', df['Institution'].unique()[:10])  # First 10
        print('Qualification:', df['Qualification'].unique())

    except Exception as e:
        print(f'Error: {e}')
else:
    print(f'File not found: {excel_file}')
