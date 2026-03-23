from database import SessionLocal
import models

def fix_ips():
    db = SessionLocal()
    try:
        sayausi = db.query(models.Parroquia).filter(models.Parroquia.nombre == "SAYAUSÍ").first()
        if sayausi:
            sayausi.base_ip = "172.18"
            
        banos = db.query(models.Parroquia).filter(models.Parroquia.nombre == "BAÑOS").first()
        if banos:
            banos.base_ip = "172.16"
            
        db.commit()
        print("IPs base actualizadas correctamente.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    fix_ips()
