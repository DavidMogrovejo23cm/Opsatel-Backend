from sqlalchemy.orm import Session

from database import SessionLocal

import models

import schemas



def test_pago():

    db = SessionLocal()

    try:

                                              

        cliente_id = 32

        pago_data = schemas.PagoCreate(monto=20.0, metodo_pago="APP", mes_correspondiente="2024-03")

        

        cliente = db.query(models.Cliente).filter(models.Cliente.id == cliente_id).first()

        if not cliente:

            print("Cliente 32 no encontrado")

            return

            

        nuevo_pago = models.Pago(

            cliente_id=cliente_id,

            monto=pago_data.monto,

            metodo_pago=pago_data.metodo_pago,

            mes_correspondiente=pago_data.mes_correspondiente,

            referencia="Test script"

        )

        db.add(nuevo_pago)

        cliente.saldo = 0

        db.commit()

        print("Pago registrado con éxito")

    except Exception as e:

        print(f"Error: {e}")

    finally:

        db.close()



if __name__ == "__main__":

    test_pago()

