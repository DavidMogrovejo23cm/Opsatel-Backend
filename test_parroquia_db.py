import os
import requests
import json

# Local test
url = "http://localhost:8000/clientes/"
# Assuming someone is logged in or bypassing auth for local test (or just use the DB directly)
# Actually, I'll use the DB directly to test if saving works.

from sqlalchemy import create_engine, text
from database import SQLALCHEMY_DATABASE_URL

engine = create_engine(SQLALCHEMY_DATABASE_URL)

with engine.connect() as conn:
    print("Inserting test client directly into DB...")
    # Map fields to column names
    query = text("""
        INSERT INTO hoja_de_c__lculo_sin_t__tulo 
        (NOMBRE, CEDULA, PARROQUIA, ESTADO, NODO, PLAN, CELULAR, DIRECCION, FECHA_FIRMA) 
        VALUES 
        ('TEST PARROQUIA', '0102030405', 'SAN JOAQUIN', 'Pendiente', 'NODO TEST', 'PLAN TEST', '0999999999', 'DIR TEST', '2026-05-20')
    """)
    conn.execute(query)
    conn.commit()
    print("Insert finished.")

print("\nVerifying last client:")
with engine.connect() as conn:
    result = conn.execute(text("SELECT NUMERO, NOMBRE, PARROQUIA FROM hoja_de_c__lculo_sin_t__tulo ORDER BY NUMERO DESC LIMIT 1"))
    for row in result:
        print(f"ID: {row[0]}, Name: {row[1]}, Parroquia: {row[2]}")
