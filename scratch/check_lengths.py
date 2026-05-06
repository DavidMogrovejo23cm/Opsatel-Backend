import pandas as pd

file_path = "BASE DE DATOS 2026(1).xlsx"
df = pd.read_excel(file_path)

# Encontrar el valor más largo en cada columna
for col in df.columns:
    # Convertir a string y calcular largo, ignorando Nones/NaNs
    lengths = df[col].dropna().astype(str).map(len)
    if not lengths.empty:
        max_len = lengths.max()
        print(f"Columna: {col:35} Max Len: {max_len}")
    else:
        print(f"Columna: {col:35} VACIA")
