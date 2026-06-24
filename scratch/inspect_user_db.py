import pandas as pd

file_path = r"../BASE DE DATOS 2026(3).xlsx"
df = pd.read_excel(file_path)

with open("excel_inspection.txt", "w", encoding="utf-8") as f:
    f.write("Excel Columns:\n")
    f.write(str(list(df.columns)) + "\n\n")
    
    f.write("Non-null counts:\n")
    f.write(str(df.notna().sum()) + "\n\n")
    
    f.write("Sample rows where INTERNET PAY is not null:\n")
    subset = df[df["INTERNET PAY"].notna()][["nombre", "plan", "INTERNET PAY", "IPTV", "adicional", "total"]].head(30)
    f.write(subset.to_string() + "\n\n")
    
    f.write("Data types of relevant columns:\n")
    for col in ["INTERNET PAY", "IPTV", "adicional", "total", "PENDIENTE"]:
        if col in df.columns:
            f.write(f"{col}: {df[col].dtype}\n")
            unique_vals = df[col].dropna().unique()[:10]
            f.write(f"  First unique values: {list(unique_vals)}\n")
