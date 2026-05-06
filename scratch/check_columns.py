import os
from sqlalchemy import create_engine, text

SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL")
if SQLALCHEMY_DATABASE_URL and SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql://", 1)

if not SQLALCHEMY_DATABASE_URL:
    print("DATABASE_URL not set")
    exit(1)

engine = create_engine(SQLALCHEMY_DATABASE_URL)
with engine.connect() as conn:
    print("Checking table columns...")
    try:
        # Check columns of the table
        result = conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'hoja_de_c__lculo_sin_t__tulo'
        """))
        columns = [row[0] for row in result]
        print(f"Columns in hoja_de_c__lculo_sin_t__tulo: {columns}")
    except Exception as e:
        print(f"Error: {e}")
