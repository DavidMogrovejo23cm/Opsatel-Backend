from sqlalchemy.orm import Session
from database import SessionLocal, engine
import models, auth_utils

def create_initial_admin():
    # Sync tables
    models.Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        # Check if admin already exists
        admin = db.query(models.Usuario).filter(models.Usuario.username == "admin").first()
        if not admin:
            admin_user = models.Usuario(
                username="admin",
                password_hash=auth_utils.get_password_hash("admin123"),
                rol="administrador"
            )
            db.add(admin_user)
            db.commit()
            print("Usuario administrador creado: admin / admin123")
        else:
            print("El usuario admin ya existe")
            
        # Create other roles for testing
        if not db.query(models.Usuario).filter(models.Usuario.username == "secretario").first():
            sec_user = models.Usuario(
                username="secretario",
                password_hash=auth_utils.get_password_hash("sec123"),
                rol="secretario"
            )
            db.add(sec_user)
            db.commit()
            print("Usuario secretario creado: secretario / sec123")

        if not db.query(models.Usuario).filter(models.Usuario.username == "tecnico").first():
            tec_user = models.Usuario(
                username="tecnico",
                password_hash=auth_utils.get_password_hash("tec123"),
                rol="tecnico"
            )
            db.add(tec_user)
            db.commit()
            print("Usuario tecnico creado: tecnico / tec123")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    create_initial_admin()
