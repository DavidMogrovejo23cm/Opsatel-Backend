from sqlalchemy import text, inspect
from database import engine

def force_fix_columns():
    is_postgres = "postgresql" in str(engine.url).lower()
    quote = '"' if is_postgres else '`'
    table = "hoja_de_c__lculo_sin_t__tulo"
    
    # (Nombre, Tamaño, ¿Es Nuevo?)
    columns_to_handle = [
        ("ONT", 2000),
        ("SERVICIO", 2000),
        ("BREACH", 2000),
        ("SERVICE PORT", 2000),
        ("PARROQUIA", 100)
    ]
    
    inspector = inspect(engine)
    db_cols = [c['name'] for c in inspector.get_columns(table)]
    
    print(f"Iniciando reparación forzada en {table} ({'Postgres' if is_postgres else 'MySQL'})...")
    
    with engine.connect() as conn:
        for col_name, size in columns_to_handle:
            try:
                if col_name not in db_cols:
                    # Crear si no existe
                    query = f'ALTER TABLE {quote}{table}{quote} ADD COLUMN {quote}{col_name}{quote} VARCHAR({size})'
                    print(f"Creando: {query}")
                else:
                    # Ampliar si ya existe
                    if is_postgres:
                        query = f'ALTER TABLE {quote}{table}{quote} ALTER COLUMN {quote}{col_name}{quote} TYPE VARCHAR({size})'
                    else:
                        query = f'ALTER TABLE {quote}{table}{quote} MODIFY COLUMN {quote}{col_name}{quote} VARCHAR({size})'
                    print(f"Ampliando: {query}")
                
                conn.execute(text(query))
                print(f"OK: {col_name}")
            except Exception as e:
                print(f"AVISO en {col_name}: {e}")
        conn.commit()
    print("Reparación terminada.")

if __name__ == "__main__":
    force_fix_columns()
