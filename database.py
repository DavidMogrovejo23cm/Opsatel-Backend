import os
from dotenv import load_dotenv

load_dotenv()
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# ========================================================================
# CONEXIÓN BACKEND -> BASE DE DATOS (MySQL Local o PostgreSQL Railway)
# ========================================================================
# DATABASE_URL es inyectada automáticamente por Railway.
# Si estás local, se usa la de XAMPP por defecto.
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "mysql+pymysql://root:@localhost/opsatel")
print(f"DATABASE_URL en uso: {SQLALCHEMY_DATABASE_URL}")

# Corrección para PostgreSQL: SQLAlchemy requiere 'postgresql://' en lugar de 'postgres://'
if SQLALCHEMY_DATABASE_URL and SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql://", 1)

# engine es el "motor" literal que mantiene la conexión viva con reconexión automática
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():

    db = SessionLocal()

    try:

        yield db

    finally:

        db.close()