from sqlalchemy import create_engine, text
from database import engine, Base
import models
from create_users import create_initial_admin
from seed_configuraciones import seed_data

def full_reset():
    print("⚠️  Iniciando reseteo TOTAL de la base de datos...")
    
    # 1. Obtener nombres de todas las tablas definidas en los modelos
    # Base.metadata.create_all(bind=engine) # Asegura que metadata sepa de las tablas
    tables = [
        "historial_pagos",
        "historial_pagos_extras",
        "hoja_ruta",
        "tickets_desarrollo",
        "reportes_mensuales",
        "hoja_de_c__lculo_sin_t__tulo",
        "clientes_extras",
        "usuarios",
        "puertos",
        "nodos",
        "planes_internet",
        "bancos",
        "finanzas_base",
        "parroquias"
    ]
    
    with engine.connect() as connection:
        # Desactivar chequeo de llaves foráneas para poder truncar todo
        connection.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))
        
        for table in tables:
            try:
                print(f"🧹 Limpiando tabla: {table}")
                connection.execute(text(f"TRUNCATE TABLE `{table}`"))
            except Exception as e:
                print(f"No se pudo limpiar {table} (tal vez no existe aún): {e}")
        
        # Volver a activar chequeo
        connection.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))
        connection.commit()
    
    print("✅ Tablas vaciadas y contadores reiniciados.")
    
    # 2. Recrear usuarios base (admin/admin123)
    print("👤 Recreando usuarios...")
    create_initial_admin()
    
    # 3. Recrear configuraciones base (Nodos, Puertos, Planes)
    print("⚙️  Cargando configuraciones base...")
    seed_data()
    
    print("\n✨ ¡SISTEMA RESTAURADO EXITOSAMENTE!")
    print("Ahora puedes entrar con admin / admin123 y todo empezará desde el ID 1.")

if __name__ == "__main__":
    full_reset()
