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

                    # Ejecutar el ALTER TABLE
                    try:
                        query = f"ALTER TABLE `{table_name}` ADD COLUMN `{column.name}` {col_type}"
                        conn.execute(text(query))
                        print(f"Columna {table_name}.{column.name} añadida exitosamente.")
                    except Exception as e:
                        print(f"Error al añadir columna {table_name}.{column.name}: {e}")
        
        conn.commit()

if __name__ == "__main__":
    sync_schema()
