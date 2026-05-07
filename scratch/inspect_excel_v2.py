import pandas as pd
import os

file_path = "c:/Users/Dagumo/GITHUB/Opsatel-Backend/2026 ADMNISTRACION(1).xlsx"

if not os.path.exists(file_path):
    print(f"File not found: {file_path}")
else:
    xl = pd.ExcelFile(file_path)
    print(f"Sheets: {xl.sheet_names}")
    for sheet in xl.sheet_names:
        if "BALANCE" in sheet.upper() or "GASTOS" in sheet.upper() or "RESUMEN" in sheet.upper():
            print(f"\n--- Sheet: {sheet} ---")
            df = pd.read_excel(file_path, sheet_name=sheet, nrows=20)
            print(df.to_string())
