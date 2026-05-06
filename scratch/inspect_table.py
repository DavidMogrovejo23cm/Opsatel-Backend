from sqlalchemy import create_engine, inspect
import os
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)
inspector = inspect(engine)

table_name = "hoja_de_c__lculo_sin_t__tulo"
print(f"Inspeccionando tabla: {table_name}")
columns = inspector.get_columns(table_name)
for col in columns:
    print(f"Columna: {col['name']}, Tipo: {col['type']}, Nullable: {col['nullable']}, Default: {col['default']}")

pk = inspector.get_pk_constraint(table_name)
print(f"Primary Key: {pk}")

unique = inspector.get_unique_constraints(table_name)
print(f"Unique Constraints: {unique}")

indexes = inspector.get_indexes(table_name)
print(f"Indexes: {indexes}")
