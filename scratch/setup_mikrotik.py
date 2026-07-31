from database import SessionLocal
import models  # <-- Cambiado: importa models completo, el cual ya contiene OLTConfig y Cliente

def setup_mikrotik_credentials():
    db = SessionLocal()
    try:
        # Accedemos a OLTConfig desde models
        olts = db.query(models.OLTConfig).all()
        if not olts:
            print("No se encontraron registros de OLT en la tabla 'olt_config'.")
            return
        
        for olt in olts:
            olt.mikrotik_host = "172.25.0.2"
            olt.mikrotik_port = 8728
            olt.mikrotik_username = "OPSATEL"
            olt.mikrotik_password = "84Cn$7y9UMF.@"
            print(f"✓ Configurado MikroTik para OLT: {olt.nombre}")
        
        db.commit()
        print("¡Credenciales de MikroTik guardadas exitosamente en la Base de Datos!")
    except Exception as e:
        db.rollback()
        print(f"Error al guardar credenciales: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    setup_mikrotik_credentials()