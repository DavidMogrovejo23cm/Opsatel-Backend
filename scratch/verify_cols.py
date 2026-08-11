# pyrefly: ignore [missing-import]
from sqlalchemy import create_engine, inspect
import os
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

load_dotenv()
engine = create_engine(os.getenv('DATABASE_URL'))
inspector = inspect(engine)
cols = inspector.get_columns('hoja_de_c__lculo_sin_t__tulo')
for c in cols:
    if c['name'].upper() in ['CELULAR', 'CEDULA', 'CORREO', 'DIRECCION']:
        print(f"{c['name']}: {c['type']}")
