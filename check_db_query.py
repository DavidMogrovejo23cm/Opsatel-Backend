from database import SessionLocal

import models

db = SessionLocal()

try:

    clientes = db.query(models.Cliente).all()

    print(f"Número de clientes: {len(clientes)}")

except Exception as e:

    print(f"Error querying database: {e}")

finally:

    db.close()

