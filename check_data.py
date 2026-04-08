import os
from sqlalchemy import create_engine, text

SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "mysql+pymysql://root:@localhost/opsatel")
if SQLALCHEMY_DATABASE_URL and SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(SQLALCHEMY_DATABASE_URL)
with engine.connect() as conn:
    result = conn.execute(text("SELECT NUMERO, NOMBRE, PARROQUIA FROM hoja_de_c__lculo_sin_t__tulo ORDER BY NUMERO DESC LIMIT 5"))
    print("Last 5 clients:")
    for row in result:
        print(f"ID: {row[0]}, Name: {row[1]}, Parroquia: {row[2]}")
