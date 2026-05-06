import pandas as pd
import os
import re

file_path = "BASE DE DATOS 2026(1).xlsx"
print(f"Analizando archivo: {file_path}")

try:
    df = pd.read_excel(file_path)
    df = df.replace([pd.NA, float('nan')], None)
    print(f"Total de filas: {len(df)}")
    
    # Identificar columnas
    columnas = {col.upper().strip(): col for col in df.columns if isinstance(col, str)}
    
    # Simular la lógica de validación de upload_database
    errores_count = 0
    detalles = []
    
    for index, row in df.iterrows():
        nombre = None
        for alias in ["NOMBRE", "NOMBRES", "CLIENTE", "NOMBRE COMPLETO"]:
            if alias in columnas:
                val = row[columnas[alias]]
                if val:
                    nombre = str(val).strip()
                    break
        
        if not nombre:
            # Estos se saltan con 'continue' en el código original, no cuentan como errores
            continue
            
        # Simular mapeo de campos y conversiones que podrían fallar
        try:
            # Aquí simulamos posibles fallos de tipos o restricciones
            # Por ejemplo, campos numéricos
            numeric_fields = ["saldo", "precio_plan_especial", "pago_mensual"]
            for field in numeric_fields:
                # Buscar alias para el campo numérico
                # (Simplificado para el script)
                pass
            
            # Si llegamos aquí sin excepción, la fila "pasaría" la lógica básica
            # Pero el fallo real suele ser en el commit a la DB (Unique constraints, length, etc.)
            pass
        except Exception as e:
            errores_count += 1
            detalles.append(f"Fila {index+2}: {str(e)}")

    print(f"Simulación completada. Filas con nombre: {len(df) - df.iloc[:, 1].isnull().sum()}") # Ajustado según el primer análisis
    
    # Mostrar una muestra de datos de las filas que podrían estar fallando
    # El usuario dijo 221 errores. 182+11=193 exitos. 193+221=414 total.
    # Vamos a ver la fila 194 en adelante.
    print("\nContenido de la fila 194 en adelante (posibles fallos):")
    print(df.iloc[193:203, :5]) # Primeras 5 columnas de 10 filas

except Exception as e:
    print(f"Error crítico: {e}")
