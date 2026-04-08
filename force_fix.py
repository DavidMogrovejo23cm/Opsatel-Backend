from sqlalchemy import text
from database import engine

def force_fix_columns():
    is_postgres = "postgresql" in str(engine.url).lower()
    quote = '"' if is_postgres else '`'
    table = "hoja_de_c__lculo_sin_t__tulo"
    
    columns_to_fix = [
        ("ONT", 2000),
        ("SERVICIO", 2000),
        ("BREACH", 2000),
        ("SERVICE PORT", 2000)
    ]
    
    print(f"Iniciando reparación forzada en {table} ({'Postgres' if is_postgres else 'MySQL'})...")
    
    with engine.connect() as conn:
        for col_name, size in columns_to_fix:
            try:
                if is_postgres:
                    query = f'ALTER TABLE {quote}{table}{quote} ALTER COLUMN {quote}{col_name}{quote} TYPE VARCHAR({size})'
                else:
                    query = f'ALTER TABLE {quote}{table}{quote} MODIFY COLUMN {quote}{col_name}{quote} VARCHAR({size})'
                
                print(f"Ejecutando: {query}")
                conn.execute(text(query))
                print(f"OK: {col_name}")
            except Exception as e:
                print(f"ERROR en {col_name}: {e}")
        conn.commit()
    print("Reparación terminada.")

if __name__ == "__main__":
    force_fix_columns()
