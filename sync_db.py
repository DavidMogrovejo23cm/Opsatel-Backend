from sqlalchemy import inspect, text
from database import engine, Base
import models

def sync_schema():
    """
    Compara las columnas de TODOS los modelos con las tablas reales en la base de datos
    y agrega las que falten automáticamente.
    """
    inspector = inspect(engine)
    
    with engine.connect() as conn:
        # Iterar sobre todas las tablas definidas en los modelos
        for table_name, table in Base.metadata.tables.items():
            if not inspector.has_table(table_name):
                # Si la tabla no existe, la dejamos para create_all()
                continue
                
            # Obtener columnas actuales en la DB para esta tabla
            db_columns = [col['name'] for col in inspector.get_columns(table_name)]
            
            # Obtener columnas definidas en el modelo
            model_columns = table.columns
            
            for column in model_columns:
                # Si la columna existe en el modelo pero NO en la DB, la creamos.
                if column.name not in db_columns:
                    print(f"Detectada columna faltante en {table_name}: {column.name}. Sincronizando...")
                    
                    # Traducir el tipo de la columna de SQLAlchemy a SQL
                    col_type = str(column.type).split('(')[0] 
                    
                    if hasattr(column.type, 'length') and column.type.length:
                        col_type = f"{col_type}({column.type.length})"
                    
                    if "NUMERIC" in col_type.upper():
                        col_type = "DECIMAL(10,2)"
                    
                    if "INTEGER" in col_type.upper():
                        col_type = "INT"

                    # Ejecutar el ALTER TABLE con sintaxis compatible (sin backticks para Postgres)
                    is_postgres = "postgresql" in str(engine.url)
                    quote = '"' if is_postgres else '`'
                    
                    try:
                        query = f"ALTER TABLE {quote}{table_name}{quote} ADD COLUMN {quote}{column.name}{quote} {col_type}"
                        conn.execute(text(query))
                        print(f"Columna {table_name}.{column.name} añadida exitosamente.")
                    except Exception as e:
                        # Si ya existe, intentamos actualizar el tipo/longitud
                        try:
                            if is_postgres:
                                alter_query = f"ALTER TABLE {quote}{table_name}{quote} ALTER COLUMN {quote}{column.name}{quote} TYPE {col_type}"
                            else:
                                alter_query = f"ALTER TABLE {quote}{table_name}{quote} MODIFY COLUMN {quote}{column.name}{quote} {col_type}"
                            conn.execute(text(alter_query))
                            print(f"Columna {table_name}.{column.name} actualizada a {col_type}.")
                        except Exception as e2:
                            print(f"Aviso: {table_name}.{column.name} ya existe y no se pudo alterar: {e2}")
        
        conn.commit()

if __name__ == "__main__":
    sync_schema()
