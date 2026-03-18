from database import SessionLocal

import models

db = SessionLocal()

try:

    clientes = db.query(models.Cliente).all()

    for i, c in enumerate(clientes):

        if c.estado is None or c.saldo is None:

            print(f"Row {i} (ID: {c.id}) has NULL: estado={c.estado}, saldo={c.saldo}")

    print("Check finished.")

except Exception as e:

    print(f"Error: {e}")

finally:

    db.close()

