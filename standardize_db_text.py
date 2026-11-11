"""
@file standardize_db_text.py
@author David Mogrovejo dmogrovejo87@gmail.com
@copyright (c) 2026 David Mogrovejo. All Rights Reserved.
@description Script de estandarización masiva de datos existentes en la BD de Opsatel.
             - Reemplaza 'ñ' y 'Ñ' por 'N'.
             - Remueve todas las tildes y diacríticos (á, é, í, ó, ú, ü, etc.).
             - Convierte todo el texto a MAYÚSCULAS en nombres, direcciones, nodos, parroquias, etc.
             Soporta SQLAlchemy (MySQL/PostgreSQL/SQLite) y conexión nativa sqlite3 para TODAS las tablas.
"""
import sys
import os
import sqlite3
from typing import List, Dict

# Asegurar path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from text_utils import normalize_opsatel_text

def standardize_via_sqlite(db_file: str):
    print(f"\n[Modo Nativo SQLite] Conectando a {db_file}...")
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    tables = [r[0] for r in cursor.fetchall()]

    total_updated = 0
    for table in tables:
        cursor.execute(f"PRAGMA table_info({table})")
        columns_info = cursor.fetchall()
        
        # Filtrar columnas de texto
        text_cols = []
        pk_col = "id"
        for col in columns_info:
            cid, name, col_type, notnull, dflt_value, pk = col
            if pk == 1:
                pk_col = name
            col_type_upper = (col_type or "").upper()
            if any(t in col_type_upper for t in ["CHAR", "TEXT", "CLOB", "VARCHAR", "STRING"]) or not col_type_upper:
                # Excluir contraseñas hash o binarios
                if name.lower() not in ["password", "hashed_password", "token", "jwt", "hash_imagen", "signature"]:
                    text_cols.append(name)

        if not text_cols:
            continue

        query = f"SELECT [{pk_col}], {', '.join([f'[{c}]' for c in text_cols])} FROM [{table}]"
        try:
            cursor.execute(query)
            rows = cursor.fetchall()
        except Exception as e:
            continue

        table_updated = 0
        for r in rows:
            row_id = r[0]
            updates = {}
            for idx, col_name in enumerate(text_cols):
                val = r[idx + 1]
                if val and isinstance(val, str):
                    new_val = normalize_opsatel_text(val)
                    if new_val != val:
                        updates[col_name] = new_val

            if updates:
                set_clause = ", ".join([f"[{c}] = ?" for c in updates.keys()])
                params = list(updates.values()) + [row_id]
                cursor.execute(f"UPDATE [{table}] SET {set_clause} WHERE [{pk_col}] = ?", params)
                table_updated += 1

        if table_updated > 0:
            conn.commit()
            print(f"  ✓ Tabla '{table}': {table_updated} filas actualizadas")
            total_updated += table_updated

    conn.close()
    print(f"\n✅ Total registros actualizados en SQLite: {total_updated}")

def standardize_via_sqlalchemy():
    from database import SessionLocal, engine, Base
    import models
    from sqlalchemy import text, inspect

    db = SessionLocal()
    print(f"\n[Modo SQLAlchemy] Conectado a motor: {engine.url}")

    inspector = inspect(engine)
    table_names = inspector.get_table_names()

    total_updated = 0
    for table in table_names:
        columns = inspector.get_columns(table)
        text_cols = []
        pk_cols = [c['name'] for c in columns if c.get('primary_key')]
        pk_col = pk_cols[0] if pk_cols else "id"

        for col in columns:
            col_name = col['name']
            col_type = str(col.get('type', '')).upper()
            if any(t in col_type for t in ["CHAR", "TEXT", "VARCHAR", "STRING"]):
                if col_name.lower() not in ["password", "hashed_password", "token", "jwt", "hash_imagen", "signature"]:
                    text_cols.append(col_name)

        if not text_cols:
            continue

        select_cols_str = f"`{pk_col}`, " + ", ".join([f"`{c}`" for c in text_cols])
        try:
            result = db.execute(text(f"SELECT {select_cols_str} FROM `{table}`")).fetchall()
        except Exception as e:
            continue

        table_updated = 0
        for r in result:
            row_id = r[0]
            updates = {}
            for idx, col_name in enumerate(text_cols):
                val = r[idx + 1]
                if val and isinstance(val, str):
                    new_val = normalize_opsatel_text(val)
                    if new_val != val:
                        updates[col_name] = new_val

            if updates:
                set_clause = ", ".join([f"`{c}` = :{c}" for c in updates.keys()])
                params = {**updates, "pk_val": row_id}
                db.execute(text(f"UPDATE `{table}` SET {set_clause} WHERE `{pk_col}` = :pk_val"), params)
                table_updated += 1

        if table_updated > 0:
            try:
                db.commit()
                print(f"  ✓ Tabla '{table}': {table_updated} filas actualizadas")
                total_updated += table_updated
            except Exception as e:
                db.rollback()
                print(f"  ❌ Error haciendo commit en tabla '{table}': {e}")

    db.close()
    print(f"\n✅ Total registros actualizados en SQLAlchemy: {total_updated}")

def main():
    print("=" * 70)
    print("🚀 INICIANDO ESTANDARIZACION DE TEXTO EN BASE DE DATOS OPSATEL")
    print("Reglas aplicadas: 'ñ'/'Ñ' -> 'N' | Tildes removidas | MAYUSCULAS")
    print("=" * 70)

    # 1. Intentar SQLAlchemy si las dependencias existen
    try:
        import sqlalchemy
        import dotenv
        standardize_via_sqlalchemy()
    except Exception as e:
        print(f"Aviso SQLAlchemy: {e}")

    # 2. Base de datos SQLite local si existe
    sqlite_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "opsatel.db")
    if os.path.exists(sqlite_path):
        standardize_via_sqlite(sqlite_path)

    print("\n" + "=" * 70)
    print("✅ PROCESO DE ESTANDARIZACION FINALIZADO EXITOSAMENTE")
    print("=" * 70)

if __name__ == "__main__":
    main()
