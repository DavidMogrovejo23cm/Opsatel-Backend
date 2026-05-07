from fastapi import FastAPI, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from database import engine, Base
import models
import os
from sync_db import sync_schema
from force_fix import force_fix_columns
# Iniciar App
app = FastAPI(title="ISP Management API")

# Función para inicializar la base de datos de forma segura
def init_db():
    try:
        print("Sincronizando esquema...")
        sync_schema() 
        print("Aplicando parches de columnas...")
        force_fix_columns() 
        print("Creando tablas si no existen...")
        Base.metadata.create_all(bind=engine)
        print("Base de datos lista.")
    except Exception as e:
        print(f"Error inicializando base de datos: {e}")

# Ejecutar inicialización ANTES de importar rutas
init_db()

from routes import auth, clientes, extras, hoja_ruta, tickets, callcenter, balance
import rutas_configuraciones

# ========================================================================
# CORS HEADERS - Aplicar en TODAS las respuestas incluyendo errores 500
# ========================================================================
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "*",
    "Access-Control-Allow-Headers": "*",
}

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=CORS_HEADERS
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()},
        headers=CORS_HEADERS
    )

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    import traceback
    print(f"Error no controlado: {traceback.format_exc()}")
    return JSONResponse(
        status_code=500,
        content={"detail": f"Error interno del servidor: {str(exc)}"},
        headers=CORS_HEADERS
    )

# Silenciar favicon.ico 404
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)

# Rutas ya importadas arriba

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
app.include_router(callcenter.router)
app.include_router(balance.router)
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
