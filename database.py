from sqlalchemy import create_engine

from sqlalchemy.ext.declarative import declarative_base

from sqlalchemy.orm import sessionmaker

# ========================================================================
# CONEXIÓN BACKEND -> BASE DE DATOS (MySQL)
# ========================================================================
# Este string configura cómo SQLAlchemy "habla" con el motor de base de datos local.
# Si cambias la base a un servidor online (AWS, HostGator), modifica esta credencial:
# FORMATO: "mysql+pymysql://<usuario>:<contraseña>@<host>/<nombre_base_datos>"
SQLALCHEMY_DATABASE_URL = "mysql+pymysql://root:@localhost/opsatel"

# engine es el "motor" literal que mantiene la conexión viva con MySQL.
engine = create_engine(
    SQLALCHEMY_DATABASE_URL
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():

    db = SessionLocal()

    try:

        yield db

    finally:

        db.close()