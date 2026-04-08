import os
from sqlalchemy import create_engine, text, inspect
import models

SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "mysql+pymysql://root:@localhost/opsatel")
if SQLALCHEMY_DATABASE_URL and SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(SQLALCHEMY_DATABASE_URL)
inspector = inspect(engine)
columns = [col['name'] for col in inspector.get_columns("hoja_de_c__lculo_sin_t__tulo")]

print(f"Checking columns in table 'hoja_de_c__lculo_sin_t__tulo'...")
if 'PARROQUIA' in columns:
    print("SUCCESS: 'PARROQUIA' column found in DB.")
elif 'parroquia' in columns:
    print("SUCCESS: 'parroquia' column found in DB.")
else:
    print("ERROR: 'parroquia' column NOT found in DB.")

# Check last 3 clients specifically for parroquia field status
print("\nReading last 3 clients from DB:")
with engine.connect() as conn:
    # Use generic SQL for both MySQL/Postgres
    query = text("SELECT NUMERO, NOMBRE, PARROQUIA FROM hoja_de_c__lculo_sin_t__tulo ORDER BY NUMERO DESC LIMIT 3")
    try:
        result = conn.execute(query)
        for row in result:
            print(f"ID: {row[0]}, Name: {row[1]}, Parroquia: {row[2]}")
    except Exception as e:
        print(f"Error reading parroquia: {e}")
