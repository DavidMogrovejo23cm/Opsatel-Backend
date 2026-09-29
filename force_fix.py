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
        ("IPTV_OUTPUTS", "VARCHAR(1255)"),
        ("CORTESIA_TOTAL", "BOOLEAN DEFAULT FALSE"),
        ("MANTENIMIENTO", "BOOLEAN DEFAULT FALSE")
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

    # 5. Tabla clientes_eliminados
    table_eliminados = "clientes_eliminados"
    columns_eliminados = [
        ("estado_mikrotik", "VARCHAR(50)")
    ]

    # 6. Tabla usuarios
    table_usuarios = "usuarios"
    columns_usuarios = [
        ("acceso_general_sin_clave", "BOOLEAN DEFAULT FALSE")
    ]

    # 7. Tabla proyectos_balance
    table_proyectos = "proyectos_balance"
    columns_proyectos = [
        ("ganancia", "DECIMAL(10,2) DEFAULT 0.00"),
        ("banco_ganancia", "VARCHAR(50) DEFAULT 'Pichincha'")
    ]

    # 8. Tabla whatsapp_configuracion
    table_whatsapp_config = "whatsapp_configuracion"
    columns_whatsapp_config = [
        ("filtro_clientes", "VARCHAR(50) DEFAULT 'todos'")
    ]

    process_table(table_clientes, columns_clientes)
    process_table(table_pagos, columns_pagos)
    process_table(table_asistencias, columns_asistencias)
    process_table(table_olt_tasks, columns_olt_tasks)
    process_table(table_eliminados, columns_eliminados)
    process_table(table_usuarios, columns_usuarios)
    process_table(table_proyectos, columns_proyectos)
    process_table(table_whatsapp_config, columns_whatsapp_config)
    
    # Ampliar columnas existentes que requieren mayor tamaño
    modify_columns = [
        ("hoja_de_c__lculo_sin_t__tulo", "CLAVE", "TEXT"),
        ("hoja_de_c__lculo_sin_t__tulo", "RED", "VARCHAR(255)"),
        ("hoja_de_c__lculo_sin_t__tulo", "UBICACION", "TEXT"),
        ("hoja_de_c__lculo_sin_t__tulo", "DISPOSITIVO", "VARCHAR(255)"),
        ("hoja_de_c__lculo_sin_t__tulo", "TECNICO", "VARCHAR(255)"),
        ("hoja_de_c__lculo_sin_t__tulo", "ACTIVADOR", "VARCHAR(255)"),
        ("hoja_de_c__lculo_sin_t__tulo", "PARROQUIA", "VARCHAR(255)"),
        ("hoja_de_c__lculo_sin_t__tulo", "ONT", "TEXT"),
        ("hoja_de_c__lculo_sin_t__tulo", "SERVICIO", "TEXT"),
        ("hoja_de_c__lculo_sin_t__tulo", "BREACH", "TEXT"),
        ("hoja_de_c__lculo_sin_t__tulo", "SERVICE PORT", "TEXT"),
        ("hoja_de_c__lculo_sin_t__tulo", "IPTV_OUTPUTS", "TEXT"),
    ]
    inspector = inspect(engine)
    with engine.connect() as conn:
        for tbl, col, col_type in modify_columns:
            if not inspector.has_table(tbl):
                continue
            cols = [c['name'] for c in inspector.get_columns(tbl)]
            if col in cols:
                try:
                    if is_postgres:
                        query = f'ALTER TABLE "{tbl}" ALTER COLUMN "{col}" TYPE {col_type}'
                    else:
                        query = f'ALTER TABLE `{tbl}` MODIFY COLUMN `{col}` {col_type}'
                    conn.execute(text(query))
                except Exception as e:
                    print(f"AVISO ampliando {tbl}.{col}: {e}")
        conn.commit()

    print("Reparación terminada.")

if __name__ == "__main__":
    force_fix_columns()
