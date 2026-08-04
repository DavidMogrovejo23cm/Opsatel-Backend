# pyrefly: ignore [missing-import]
from sqlalchemy import text, inspect
from database import engine

def force_fix_columns():
    is_postgres = "postgresql" in str(engine.url).lower()
    quote = '"' if is_postgres else '`'
    
    # 1. Tabla Clientes
    table_clientes = "hoja_de_c__lculo_sin_t__tulo"
    columns_clientes = [
        ("ONT", "VARCHAR(2000)"),
        ("SERVICIO", "VARCHAR(2000)"),
        ("BREACH", "VARCHAR(2000)"),
        ("SERVICE PORT", "VARCHAR(2000)"),
        ("PARROQUIA", "VARCHAR(100)"),
        ("IPTV_OUTPUTS", "VARCHAR(1255)")
    ]
    
    # 2. Tabla Historial Pagos
    table_pagos = "historial_pagos"
    columns_pagos = [
        ("monto_internet", "DECIMAL(10,2)"),
        ("monto_plus", "DECIMAL(10,2)"),
        ("monto_adicional", "DECIMAL(10,2)")
    ]

    # 3. Tabla Asistencias
    table_asistencias = "asistencias"
    columns_asistencias = [
        ("hora_salida", "VARCHAR(50)"),
        ("ubicacion_salida", "VARCHAR(255)"),
        ("distancia_metros_salida", "FLOAT"),
        ("biometria_salida_validada", "BOOLEAN")
    ]

    # 4. Tabla olt_tasks
    table_olt_tasks = "olt_tasks"
    columns_olt_tasks = [
        ("bulk_id", "VARCHAR(100)")
    ]

    def process_table(table_name, columns):
        inspector = inspect(engine)
        if not inspector.has_table(table_name):
            print(f"Saltando {table_name}: no existe")
            return
            
        db_cols = [c['name'] for c in inspector.get_columns(table_name)]
        print(f"Procesando {table_name}...")
        
        with engine.connect() as conn:
            for col_name, col_type in columns:
                try:
                    if col_name not in db_cols:
                        query = f'ALTER TABLE {quote}{table_name}{quote} ADD COLUMN {quote}{col_name}{quote} {col_type}'
                        print(f"Creando: {query}")
                        conn.execute(text(query))
                    else:
                        print(f"Columna {col_name} ya existe en {table_name}")
                except Exception as e:
                    print(f"AVISO en {table_name}.{col_name}: {e}")
            conn.commit()

    process_table(table_clientes, columns_clientes)
    process_table(table_pagos, columns_pagos)
    process_table(table_asistencias, columns_asistencias)
    process_table(table_olt_tasks, columns_olt_tasks)
    
    print("Reparación terminada.")

if __name__ == "__main__":
    force_fix_columns()
