import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import json
from database import SessionLocal
import models

db = SessionLocal()
try:
    tasks = db.query(models.OLTTask).order_by(models.OLTTask.id.desc()).limit(15).all()
    print("=== ULTIMAS 15 TAREAS OLT ===")
    for t in tasks:
        print(f"ID: {t.id}")
        print(f"  Acción: {t.action}")
        print(f"  Estado: {t.status}")
        print(f"  Error: {t.error_message}")
        print(f"  Respuesta corta: {t.response[:200] if t.response else None}")
        print("-" * 50)
finally:
    db.close()
