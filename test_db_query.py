from sqlalchemy.orm import Session

from database import engine, SessionLocal

import models



def test_query():

    db = SessionLocal()

    try:

        clientes = db.query(models.Cliente).all()

        print(f"Total clientes: {len(clientes)}")

        if clientes:

            print(f"Primer cliente: {clientes[0].nombre}")

    except Exception as e:

        print(f"Error en la consulta: {e}")

    finally:

        db.close()



if __name__ == "__main__":

    test_query()

