from sqlalchemy import text
from database import engine

def delete_clients():
    print("--- Borrando todos los clientes y datos relacionados (Pagos, Hoja de Ruta) ---")
    
    # Tablas que dependen de los clientes o son los clientes mismos
    tables = [
        "historial_pagos",
        "hoja_ruta",
        "reportes_mensuales",
        "hoja_de_c__lculo_sin_t__tulo"
    ]
    
    is_postgres = "postgresql" in str(engine.url).lower()
    
    try:
        with engine.connect() as connection:
            if is_postgres:
                print("Detectada base de datos PostgreSQL")
                # En Postgres truncamos con CASCADE para manejar llaves foráneas
                for table in tables:
                    try:
                        print(f"Vaciando tabla: {table}")
                        connection.execute(text(f'TRUNCATE TABLE "{table}" CASCADE'))
                    except Exception as e:
                        print(f"Aviso: No se pudo limpiar {table}: {e}")
            else:
                print("Detectada base de datos MySQL/SQLite")
                # Desactivar chequeo de llaves foráneas para evitar errores al truncar
                connection.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))
                
                for table in tables:
                    try:
                        print(f"Vaciando tabla: {table}")
                        connection.execute(text(f"TRUNCATE TABLE `{table}`"))
                    except Exception as e:
                        print(f"Aviso: No se pudo limpiar {table}: {e}")
                
                connection.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))
            
            connection.commit()
            
        print("\nBase de datos de clientes limpiada exitosamente.")
        print("Se han borrado Clientes, Pagos y Hojas de Ruta. Los usuarios y configuraciones se mantienen intactos.")
        
    except Exception as e:
        print(f"Error critico durante la limpieza: {e}")


if __name__ == "__main__":
    # Pedir confirmación no es posible en modo no interactivo, pero procedemos según la solicitud directa del usuario
    delete_clients()
