import openpyxl

wb = openpyxl.load_workbook(r"../BASE DE DATOS 2026(3).xlsx", data_only=False)
sheet = wb.active

print("Sheet name:", sheet.title)

# Let's find column indices
cols = [cell.value for cell in sheet[1]]
print("Headers:", cols)

# Let's inspect some rows for PENDIENTE, IPTV, adicional, total, plan, INTERNET PAY
target_cols = ["PENDIENTE", "IPTV", "adicional", "total", "plan", "INTERNET PAY"]
col_indices = {name: cols.index(name) + 1 for name in target_cols if name in cols}

print("Column indices:", col_indices)

# Check the first 10 rows with data_only=False (formulas themselves)
print("\nFirst 15 rows (with Formulas):")
for r in range(2, 17):
    row_vals = {name: sheet.cell(row=r, column=idx).value for name, idx in col_indices.items()}
    print(f"Row {r}: {row_vals}")

# Check with data_only=True (evaluated values)
wb_val = openpyxl.load_workbook(r"../BASE DE DATOS 2026(3).xlsx", data_only=True)
sheet_val = wb_val.active
print("\nFirst 15 rows (Evaluated Values):")
for r in range(2, 17):
    row_vals = {name: sheet_val.cell(row=r, column=idx).value for name, idx in col_indices.items()}
    print(f"Row {r}: {row_vals}")
