from database import SessionLocal
import models
import datetime

def add_test_client():
    db = SessionLocal()
    try:
        new_client = models.Cliente(
            nombre="TEST CLIENT ANTIGRAVITY",
            cedula="0000000000",
            celular="0999999999",
            correo="test@example.com",
            direccion="Test Address",
            parroquia="Test Parroquia",
            plan="Test Plan",
            fecha_firma=str(datetime.datetime.now()),
            estado="Pendiente"
        )
        db.add(new_client)
        db.commit()
        db.refresh(new_client)
        print(f"Test client added with ID: {new_client.id}")
        
        # Verify
        clients = db.query(models.Cliente).all()
        print(f"Total clients now: {len(clients)}")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    add_test_client()
