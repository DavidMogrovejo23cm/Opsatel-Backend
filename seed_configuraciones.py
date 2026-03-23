from database import SessionLocal
import models

def seed_data():
    db = SessionLocal()
    try:
        # Parroquia BAÑOS
        banos = db.query(models.Parroquia).filter(models.Parroquia.nombre == "BAÑOS").first()
        if not banos:
            banos = models.Parroquia(nombre="BAÑOS")
            db.add(banos)
            db.commit()
            db.refresh(banos)
            print("Parroquia BAÑOS creada.")
        else:
            print("Parroquia BAÑOS ya existia.")
        
        # Parroquia SAYAUSÍ
        sayausi = db.query(models.Parroquia).filter(models.Parroquia.nombre == "SAYAUSÍ").first()
        if not sayausi:
            sayausi = models.Parroquia(nombre="SAYAUSÍ")
            db.add(sayausi)
            db.commit()
            db.refresh(sayausi)
            print("Parroquia SAYAUSÍ creada.")
        else:
            print("Parroquia SAYAUSÍ ya existia.")
            
        # Puertos para SAYAUSÍ (11 puertos)
        puertos_sayausi_agregados = 0
        for i in range(1, 12):
            puerto_nombre = f"Puerto {i}"
            puerto = db.query(models.Puerto).filter(models.Puerto.nombre == puerto_nombre, models.Puerto.parroquia_id == sayausi.id).first()
            if not puerto:
                db.add(models.Puerto(nombre=puerto_nombre, parroquia_id=sayausi.id))
                puertos_sayausi_agregados += 1
        print(f"Se agregaron {puertos_sayausi_agregados} puertos nuevos a SAYAUSÍ.")
        
        # Puertos para BAÑOS (15 puertos)
        puertos_banos_agregados = 0
        for i in range(1, 16):
            puerto_nombre = f"Puerto {i}"
            puerto = db.query(models.Puerto).filter(models.Puerto.nombre == puerto_nombre, models.Puerto.parroquia_id == banos.id).first()
            if not puerto:
                db.add(models.Puerto(nombre=puerto_nombre, parroquia_id=banos.id))
                puertos_banos_agregados += 1
        print(f"Se agregaron {puertos_banos_agregados} puertos nuevos a BAÑOS.")
                
        # Planes existentes (según hardcoded previo)
        planes_iniciales = [
            ("100mb", 17.25),
            ("600mb", 17.87),
            ("700mb", 21.73),
            ("800mb", 32.20)
        ]
        planes_agregados = 0
        for nombre, precio in planes_iniciales:
            plan = db.query(models.PlanInternet).filter(models.PlanInternet.nombre == nombre).first()
            if not plan:
                db.add(models.PlanInternet(nombre=nombre, precio=precio))
                planes_agregados += 1

        db.commit()
        print(f"Migración completada. {planes_agregados} planes agregados.")
    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_data()
