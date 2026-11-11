"""
@file standardize_db_text.py
@author David Mogrovejo dmogrovejo87@gmail.com
@copyright (c) 2026 David Mogrovejo. All Rights Reserved.
@description Script de estandarización masiva de datos existentes en la BD de Opsatel.
             - Reemplaza 'ñ' y 'Ñ' por 'N'.
             - Remueve todas las tildes y diacríticos (á, é, í, ó, ú, ü, etc.).
             - Convierte todo el texto a MAYÚSCULAS en nombres, direcciones, nodos, parroquias, etc.
             Soporta SQLAlchemy (MySQL/PostgreSQL/SQLite) y conexión nativa sqlite3.
"""
import sys
import os
import sqlite3
from typing import List, Dict

# Asegurar path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from text_utils import normalize_opsatel_text

TABLES_AND_COLUMNS: Dict[str, List[str]] = {
    "hoja_de_c__lculo_sin_t__tulo": [
        "NOMBRE", "DIRECCION", "PARROQUIA", "NODO", "COMENTARIOS",
        "OBSERVACIONES", "NOTAS_PAGO", "TECNICO", "ACTIVADOR", "NAP",
        "REFERENCIA", "BANK", "BANK_PLUS", "APP", "CUENTA", "ARRIENDA"
    ],
    "clientes_extras": [
        "nombre_cliente", "observaciones", "proveedor", "contacto"
    ],
    "hoja_ruta": [
        "nombre_cliente", "ubicacion_cliente", "ubicacion_caja",
        "actividad", "observacion", "observacion_tecnico", "tecnico", "parroquia"
    ],
    "call_center_tickets": [
        "cliente_nombre", "direccion", "a_cargo", "problema", "observacion_revision"
    ],
    "comprobantes": [
        "nombre_remitente", "observaciones", "banco_origen", "banco_destino",
        "ordenante", "beneficiario"
    ]
}

def standardize_via_sqlite(db_file: str):
    print(f"\n[Modo Nativo SQLite] Conectando a {db_file}...")
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    total_updated = 0
    for table, columns in TABLES_AND_COLUMNS.items():
        # Verificar si la tabla existe
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
        if not cursor.fetchone():
            continue

        # Obtener columnas reales de la tabla
        cursor.execute(f"PRAGMA table_info({table})")
        existing_cols = {row[1].upper(): row[1] for row in cursor.fetchall()}

        valid_cols = []
        for col in columns:
            if col.upper() in existing_cols:
                valid_cols.append(existing_cols[col.upper()])

        if not valid_cols:
            continue

        # Obtener clave primaria (usualmente id o rowid)
        pk_col = "NUMERO" if "NUMERO" in existing_cols else ("id" if "id" in existing_cols else "rowid")

        select_cols = [pk_col] + valid_cols
        query = f"SELECT {', '.join(select_cols)} FROM {table}"
        cursor.execute(query)
        rows = cursor.fetchall()

        table_updated = 0
        for r in rows:
            row_id = r[0]
            updates = {}
            for idx, col in enumerate(valid_cols):
                val = r[idx + 1]
                if val and isinstance(val, str):
                    new_val = normalize_opsatel_text(val)
                    if new_val != val:
                        updates[col] = new_val

            if updates:
                set_clause = ", ".join([f"{col} = ?" for col in updates.keys()])
                params = list(updates.values()) + [row_id]
                cursor.execute(f"UPDATE {table} SET {set_clause} WHERE {pk_col} = ?", params)
                table_updated += 1

        conn.commit()
        print(f"  ✓ Tabla '{table}': {len(rows)} filas analizadas | {table_updated} actualizadas")
        total_updated += table_updated

    conn.close()
    print(f"\n✅ Total registros actualizados en SQLite: {total_updated}")

def standardize_via_sqlalchemy():
    from database import SessionLocal, engine
    import models

    db = SessionLocal()
    print(f"\n[Modo SQLAlchemy] Conectado a motor: {engine.url}")

    # 1. Clientes
    clientes_fields = [
        "nombre", "direccion", "parroquia", "nodo", "comentarios",
        "observaciones", "notas_pago", "tecnico", "activador", "nap",
        "referencia", "bank", "bank_plus", "app", "cuenta", "arrienda"
    ]
    try:
        clientes = db.query(models.Cliente).all()
        updated_c = 0
        for c in clientes:
            changed = False
            for field in clientes_fields:
                if hasattr(c, field):
                    old_val = getattr(c, field)
                    if old_val and isinstance(old_val, str):
                        new_val = normalize_opsatel_text(old_val)
                        if new_val != old_val:
                            setattr(c, field, new_val)
                            changed = True
            if changed:
                updated_c += 1
        db.commit()
        print(f"  ✓ Clientes analizados: {len(clientes)} | Actualizados: {updated_c}")
    except Exception as e:
        db.rollback()
        print(f"  ❌ Error procesando clientes: {e}")

    # 2. Extras
    extras_fields = ["nombre_cliente", "observaciones", "proveedor", "contacto"]
    try:
        extras = db.query(models.ClienteExtra).all()
        updated_e = 0
        for e in extras:
            changed = False
            for field in extras_fields:
                if hasattr(e, field):
                    old_val = getattr(e, field)
                    if old_val and isinstance(old_val, str):
                        new_val = normalize_opsatel_text(old_val)
                        if new_val != old_val:
                            setattr(e, field, new_val)
                            changed = True
            if changed:
                updated_e += 1
        db.commit()
        print(f"  ✓ Extras analizados: {len(extras)} | Actualizados: {updated_e}")
    except Exception as e:
        db.rollback()
        print(f"  ❌ Error procesando extras: {e}")

    # 3. Hoja de Ruta
    hr_fields = [
        "nombre_cliente", "ubicacion_cliente", "ubicacion_caja",
        "actividad", "observacion", "observacion_tecnico", "tecnico", "parroquia"
    ]
    try:
        tareas = db.query(models.HojaRuta).all()
        updated_hr = 0
        for t in tareas:
            changed = False
            for field in hr_fields:
                if hasattr(t, field):
                    old_val = getattr(t, field)
                    if old_val and isinstance(old_val, str):
                        new_val = normalize_opsatel_text(old_val)
                        if new_val != old_val:
                            setattr(t, field, new_val)
                            changed = True
            if changed:
                updated_hr += 1
        db.commit()
        print(f"  ✓ Tareas analizadas: {len(tareas)} | Actualizadas: {updated_hr}")
    except Exception as e:
        db.rollback()
        print(f"  ❌ Error procesando hoja de ruta: {e}")

    # 4. Call Center
    cc_fields = ["cliente_nombre", "direccion", "a_cargo", "problema", "observacion_revision"]
    try:
        tickets = db.query(models.CallCenterTicket).all()
        updated_cc = 0
        for tk in tickets:
            changed = False
            for field in cc_fields:
                if hasattr(tk, field):
                    old_val = getattr(tk, field)
                    if old_val and isinstance(old_val, str):
                        new_val = normalize_opsatel_text(old_val)
                        if new_val != old_val:
                            setattr(tk, field, new_val)
                            changed = True
            if changed:
                updated_cc += 1
        db.commit()
        print(f"  ✓ Tickets analizados: {len(tickets)} | Actualizados: {updated_cc}")
    except Exception as e:
        db.rollback()
        print(f"  ❌ Error procesando tickets call center: {e}")

    # 5. Comprobantes
    comp_fields = ["nombre_remitente", "observaciones", "banco_origen", "banco_destino", "ordenante", "beneficiario"]
    try:
        comps = db.query(models.Comprobante).all()
        updated_comp = 0
        for cp in comps:
            changed = False
            for field in comp_fields:
                if hasattr(cp, field):
                    old_val = getattr(cp, field)
                    if old_val and isinstance(old_val, str):
                        new_val = normalize_opsatel_text(old_val)
                        if new_val != old_val:
                            setattr(cp, field, new_val)
                            changed = True
            if changed:
                updated_comp += 1
        db.commit()
        print(f"  ✓ Comprobantes analizados: {len(comps)} | Actualizados: {updated_comp}")
    except Exception as e:
        db.rollback()
        print(f"  ❌ Error procesando comprobantes: {e}")

    db.close()

def main():
    print("=" * 70)
    print("🚀 INICIANDO ESTANDARIZACIÓN DE TEXTO EN BASE DE DATOS OPSATEL")
    print("Reglas aplicadas: 'ñ'/'Ñ' -> 'N' | Tildes removidas | MAYÚSCULAS")
    print("=" * 70)

    # 1. Intentar SQLAlchemy primero si el entorno lo soporta
    used_sqlalchemy = False
    try:
        import sqlalchemy
        import dotenv
        standardize_via_sqlalchemy()
        used_sqlalchemy = True
    except ImportError:
        pass

    # 2. Si hay base local opsatel.db, estandarizarla también
    sqlite_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "opsatel.db")
    if os.path.exists(sqlite_path):
        standardize_via_sqlite(sqlite_path)

    print("\n" + "=" * 70)
    print("✅ PROCESO DE ESTANDARIZACIÓN FINALIZADO EXITOSAMENTE")
    print("=" * 70)

if __name__ == "__main__":
    main()
