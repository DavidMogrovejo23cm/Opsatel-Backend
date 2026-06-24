from database import SessionLocal
import models

db = SessionLocal()
try:
    planes = db.query(models.PlanInternet).all()
    print("Registered Plans:")
    for p in planes:
        print(f"ID: {p.id}, Nombre: {p.nombre}, Megas: {p.megas}, Precio: {p.precio}, Pantallas: {p.pantallas}")
finally:
    db.close()
