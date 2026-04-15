from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from database import engine, Base
import models
import os
from routes import auth, clientes, extras, hoja_ruta, tickets
import rutas_configuraciones
from sync_db import sync_schema
from force_fix import force_fix_columns

# Sincroniza las columnas e inicializa tablas
sync_schema() 
force_fix_columns() # Fuerza la ampliación de campos críticos
Base.metadata.create_all(bind=engine)

# Iniciar App
app = FastAPI(title="ISP Management API")

# Silenciar favicon.ico 404
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://opsatel-frontend.vercel.app",
        "https://opsatel-frontend-production.up.railway.app",
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:3000",
        "*",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Enrutadores
app.include_router(auth.router)
app.include_router(clientes.router)
app.include_router(extras.router)
app.include_router(hoja_ruta.router)
app.include_router(tickets.router)
app.include_router(rutas_configuraciones.router)

from fastapi.staticfiles import StaticFiles
os.makedirs("rutas_reportes", exist_ok=True)
os.makedirs("uploads/cedulas", exist_ok=True)
app.mount("/rutas_reportes", StaticFiles(directory="rutas_reportes"), name="rutas_reportes")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

@app.get("/")
def read_root():
    return {"message": "Bienvenido a la API de Gestión de ISP Opsatel"}

# ========================================================================
# AUTO-CREAR ADMIN AL INICIAR (SEEDING)
# ========================================================================
from database import SessionLocal
from auth_utils import get_password_hash

def seed_admin():
    db = SessionLocal()
    try:
        admin = db.query(models.Usuario).filter(models.Usuario.username == "david").first()
        if not admin:
            print("Seeding: Creando usuario admin por defecto...")
            nuevo_admin = models.Usuario(
                username="david",
                password_hash=get_password_hash("admin123"),
                rol="administrador"
            )
            db.add(nuevo_admin)
            db.commit()
            print("Seeding: Usuario 'david' creado exitosamente.")
    except Exception as e:
        print(f"Error en seeding: {e}")
    finally:
        db.close()

# Ejecutar el seeding
seed_admin()
