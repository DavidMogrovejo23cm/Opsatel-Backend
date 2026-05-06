import pandas as pd
import os
from sqlalchemy import create_engine, Column, Integer, String, Numeric, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
db = SessionLocal()

# Import models
import models

def test_import():
    file_path = "BASE DE DATOS 2026(1).xlsx"
    df = pd.read_excel(file_path)
    df = df.replace([pd.NA, float('nan')], None)
    
    # Solo probar las filas que fallan (a partir de la 193)
    subset = df.iloc[190:200]
    print(f"Probando importación de filas index 190 a 200...")
    
    for index, row in subset.iterrows():
        try:
            # Aquí pondríamos la lógica de clientes.py simplificada
            # Pero para ser más exactos, vamos a ver si podemos capturar el error de la DB
            nombre = str(row['nombre']).strip()
            print(f"Procesando fila {index+2}: {nombre}")
            
            # Simular lo que hace el backend
            # ... (asumiendo que el backend ya tiene la lógica corregida que subí)
            
            # Vamos a intentar un insert real en una transacción de prueba (luego rollback)
            # Para ver el error exacto de Postgres
            pass
        except Exception as e:
            print(f"Error en fila {index+2}: {e}")

test_import()
db.close()
