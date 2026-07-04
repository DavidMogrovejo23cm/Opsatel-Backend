import sys
from database import SessionLocal
import models

db = SessionLocal()
try:
    olts = db.query(models.OLTConfig).all()
    print(f"Total OLTs found: {len(olts)}")
    for olt in olts:
        print(f"ID: {olt.id}")
        print(f"Nombre: {olt.nombre}")
        print(f"Host: {olt.host}")
        print(f"Port: {olt.port}")
        print(f"Username: {olt.username}")
        print(f"Password: {olt.password}")
        print(f"Active: {olt.active}")
        print(f"Nodo Asociado: {olt.nodo_asociado}")
        print("-" * 30)
except Exception as e:
    print(f"Error: {e}")
finally:
    db.close()
