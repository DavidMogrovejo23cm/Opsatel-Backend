import pandas as pd
import os

file_path = "BASE DE DATOS 2026(1).xlsx"
print(f"Analizando archivo: {file_path}")

try:
    df = pd.read_excel(file_path)
    print(f"Total de filas: {len(df)}")
    print(f"Columnas encontradas: {df.columns.tolist()}")
    
    # Simular la búsqueda de nombres
    nombre_cols = ["NOMBRE", "NOMBRES", "CLIENTE", "NOMBRE COMPLETO"]
    found_name_col = None
    for col in df.columns:
        if col.upper().strip() in nombre_cols:
            found_name_col = col
            break
    
    if found_name_col:
        print(f"Columna de nombre identificada: {found_name_col}")
        nombres_vacios = df[found_name_col].isnull().sum()
        print(f"Filas con nombre vacío: {nombres_vacios}")
        
        # Mostrar las primeras 5 filas para ver el formato
        print("\nPrimeras 5 filas:")
        print(df.head())
    else:
        print("¡ERROR! No se encontró columna de nombre.")

except Exception as e:
    print(f"Error al leer el archivo: {e}")
