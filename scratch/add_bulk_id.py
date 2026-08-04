import database
# pyrefly: ignore [missing-import]
from sqlalchemy import text

db = database.SessionLocal()
try:
    print("Aplicando migración a la base de datos...")
    db.execute(text("ALTER TABLE olt_tasks ADD COLUMN bulk_id VARCHAR(100) NULL"))
    db.commit()
    print("Columna bulk_id añadida con éxito!")
except Exception as e:
    db.rollback()
    print("Aviso/Error agregando columna:", e)
finally:
    db.close()
