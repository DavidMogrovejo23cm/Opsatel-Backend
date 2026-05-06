from sqlalchemy import inspect, text
from database import engine, Base
import models

def sync_schema():
    """
    Compara las columnas de TODOS los modelos con las tablas reales en la base de datos
    y agrega las que falten o amplia las que necesiten más espacio (Postgres/MySQL).
    """
    inspector = inspect(engine)
    
    with engine.connect() as conn:
        for table_name, table in Base.metadata.tables.items():
            if not inspector.has_table(table_name):
                continue
                
            db_columns_info = {col['name']: col for col in inspector.get_columns(table_name)}
            db_columns = list(db_columns_info.keys())
            model_columns = table.columns
            
            for column in model_columns:
                col_type = str(column.type).split('(')[0] 
                if hasattr(column.type, 'length') and column.type.length:
                    col_type = f"{col_type}({column.type.length})"
                
                if "NUMERIC" in col_type.upper(): col_type = "DECIMAL(10,2)"
                if "INTEGER" in col_type.upper(): col_type = "INT"
                if "BOOLEAN" in col_type.upper(): col_type = "BOOLEAN"

                is_postgres = "postgresql" in str(engine.url).lower()
                quote = '"' if is_postgres else '`'

                if column.name not in db_columns:
                    print(f"Detectada columna faltante en {table_name}: {column.name}. Sincronizando...")
                    try:
                        query = f"ALTER TABLE {quote}{table_name}{quote} ADD COLUMN {quote}{column.name}{quote} {col_type}"
                        print(f"Ejecutando: {query}")
                        conn.execute(text(query))
                        print(f"Columna {table_name}.{column.name} añadida exitosamente.")
                    except Exception as e:
                        print(f"Error al añadir columna {table_name}.{column.name}: {e}")
                else:
                    # Si ya existe, comprobamos si necesitamos ampliarla (ej: de 50 a 1000)
                    db_col = db_columns_info[column.name]
                    model_length = getattr(column.type, 'length', None)
                    
                    # Para Postgres/SQLAlchemy, el largo puede estar en col['type'].length o col['length']
                    db_length = getattr(db_col['type'], 'length', None)
                    if db_length is None:
                        db_length = db_col.get('length')

                    if model_length and db_length and int(model_length) > int(db_length):
                        print(f"Detectada necesidad de ampliación en {table_name}.{column.name}: {db_length} -> {model_length}")
                        try:
                            if is_postgres:
                                alter_query = f"ALTER TABLE {quote}{table_name}{quote} ALTER COLUMN {quote}{column.name}{quote} TYPE {col_type}"
                            else:
                                alter_query = f"ALTER TABLE {quote}{table_name}{quote} MODIFY COLUMN {quote}{column.name}{quote} {col_type}"
                            print(f"Ejecutando: {alter_query}")
                            conn.execute(text(alter_query))
                            print(f"Columna {table_name}.{column.name} actualizada a {col_type}.")
                        except Exception as e:
                            print(f"Error al actualizar tipo de {column.name}: {e}")
        
        conn.commit()

if __name__ == "__main__":
    sync_schema()
