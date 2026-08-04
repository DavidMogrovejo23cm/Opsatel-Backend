# pyrefly: ignore [missing-import]
from fastapi import FastAPI, Response, Request
# pyrefly: ignore [missing-import]
from fastapi.middleware.cors import CORSMiddleware
# pyrefly: ignore [missing-import]
from fastapi.responses import JSONResponse
# pyrefly: ignore [missing-import]
from fastapi.exceptions import RequestValidationError
# pyrefly: ignore [missing-import]
from starlette.exceptions import HTTPException as StarletteHTTPException
from database import engine, Base
import models
import os
import sys
import time
import pymysql
# pyrefly: ignore [missing-import]
from sqlalchemy.exc import OperationalError as SQLAlchemyOperationalError
from pymysql.err import OperationalError as PyMySQLOperationalError
from sync_db import sync_schema
from force_fix import force_fix_columns
import observability
import discovery_models
import inventory_models
from routes import discovery, sync, workflows
from routes.bulk_activation import bulk_router

# Iniciar App
app = FastAPI(title="ISP Management API")
app.add_middleware(observability.CorrelationIdMiddleware)
app.include_router(observability.router)
app.include_router(discovery.router)
app.include_router(sync.router)
app.include_router(workflows.router)
app.include_router(bulk_router)
observability.setup_json_logging()






# Función para inicializar la base de datos de forma segura
def wait_for_db(host='db', port=3306, max_attempts=30, delay=2):
    import urllib.parse
    
    db_host = host
    db_port = port
    db_user = os.getenv('MYSQL_USER', 'root')
    db_pass = os.getenv('MYSQL_ROOT_PASSWORD', '')
    db_name = os.getenv('MYSQL_DATABASE', '')
    
    database_url = os.getenv('DATABASE_URL', '')
    if database_url:
        try:
            parsed = urllib.parse.urlparse(database_url)
            if parsed.scheme.startswith("mysql"):
                if parsed.hostname:
                    db_host = parsed.hostname
                if parsed.port:
                    db_port = parsed.port
                if parsed.username:
                    db_user = parsed.username
                if parsed.password:
                    db_pass = parsed.password
                if parsed.path:
                    db_name = parsed.path.lstrip("/")
        except Exception as e:
            print(f"Error parsing DATABASE_URL in main.py: {e}")

    # Limpiar posibles caracteres de retorno de carro (\r) de Windows
    if db_host: db_host = str(db_host).strip().replace("\r", "")
    if db_user: db_user = str(db_user).strip().replace("\r", "")
    if db_pass: db_pass = str(db_pass).strip().replace("\r", "")
    if db_name: db_name = str(db_name).strip().replace("\r", "")
    if db_port:
        try:
            db_port = int(str(db_port).strip().replace("\r", ""))
        except ValueError:
            db_port = 3306

    attempts = 0
    while attempts < max_attempts:
        try:
            conn = pymysql.connect(
                host=db_host,
                user=db_user,
                password=db_pass,
                database=db_name,
                port=db_port,
                connect_timeout=5
            )
            conn.close()
            print('MySQL está listo para conexiones.')
            return True
        except PyMySQLOperationalError as e:
            attempts += 1
            print(f'MySQL no listo ({attempts}/{max_attempts}): {e}')
            time.sleep(delay)
        except Exception as e:
            attempts += 1
            print(f'Error al verificar MySQL ({attempts}/{max_attempts}): {e}')
            time.sleep(delay)
    return False


def init_db(max_retries=12, retry_interval=5):
    if not wait_for_db():
        print('No se pudo conectar a MySQL después de los intentos. Abortando inicialización.')
        return

    attempts = 0
    while True:
        try:
            print('Sincronizando esquema...')
            sync_schema()
            print('Aplicando parches de columnas...')
            force_fix_columns()
            print('Creando tablas si no existen...')
            Base.metadata.create_all(bind=engine)
            print('Base de datos lista.')

            # Corregir formatos inconsistentes (.0) en clientes existentes
            try:
                from database import SessionLocal
                from routes.clientes import clean_existing_database_formats
                db = SessionLocal()
                try:
                    clean_existing_database_formats(db)
                finally:
                    db.close()
            except Exception as migration_error:
                print(f'Error al ejecutar automigración de formatos: {migration_error}')
            return

        except (SQLAlchemyOperationalError, PyMySQLOperationalError) as e:
            attempts += 1
            print(f'Error inicializando base de datos ({attempts}/{max_retries}): {e}')
            if attempts >= max_retries:
                print('No se pudo inicializar la base de datos después de varios intentos. Revise la conectividad y las credenciales.')
                return
            print(f'Reintentando en {retry_interval} segundos...')
            time.sleep(retry_interval)
        except Exception as e:
            print(f'Error inicializando base de datos: {e}')
            return

# Ejecutar inicialización ANTES de importar rutas
init_db()

from routes import auth, clientes, extras, hoja_ruta, tickets, callcenter, balance, asistencia, whatsapp, olt_tasks
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
app.include_router(asistencia.router)
app.include_router(whatsapp.router)
app.include_router(olt_tasks.router)

# pyrefly: ignore [missing-import]
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
from scheduler import iniciar_scheduler
import pytz
from datetime import datetime

# Zona horaria Ecuador
ECUADOR_TZ = pytz.timezone('America/Guayaquil')

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

# ========================================================================
# SEED: Programación WhatsApp de prueba (si no existe)
# ========================================================================
def seed_whatsapp_config():
    db = SessionLocal()
    try:
        existing = db.query(models.WhatsAppConfiguracion).first()
        if not existing:
            # Por defecto, programamos el mensaje de prueba a las 16:05
            prueba_hora = '16:05'
            prueba_mensaje = 'ESTE ES UN MENSAJE DE PRUEBA NO RESPONDER'
            print(f"Seeding: Creando configuración WhatsApp programada {prueba_hora}")
            cfg = models.WhatsAppConfiguracion(
                hora_programada=prueba_hora,
                mensaje_programado=prueba_mensaje,
                activo=True,
                enviar_a_todos=True,
                fecha_creacion=datetime.now(ECUADOR_TZ)
            )
            db.add(cfg)
            db.commit()
            print("Seeding: Configuración WhatsApp creada.")
    except Exception as e:
        print(f"Error en seed_whatsapp_config: {e}")
    finally:
        db.close()

seed_whatsapp_config()

# ========================================================================
# INICIAR SCHEDULER PARA TAREAS AUTOMÁTICAS
# ========================================================================
iniciar_scheduler()

# ========================================================================
# AUTO-INICIAR EL PUENTE DE WHATSAPP (NODE.JS) EN SEGUNDO PLANO
# ========================================================================
import subprocess
import threading

def iniciar_puente_whatsapp():
    provider = os.getenv("WHATSAPP_PROVIDER", "local-bridge")
    if provider != "local-bridge":
        print(f"Omitiendo inicio automático del puente local de WhatsApp porque WHATSAPP_PROVIDER es '{provider}'")
        return

    bridge_url = os.getenv("WHATSAPP_BRIDGE_URL", "http://localhost:3001")
    port = "3001"
    if "localhost:" in bridge_url:
        port = bridge_url.split("localhost:")[-1].split("/")[0]
    elif "127.0.0.1:" in bridge_url:
        port = bridge_url.split("127.0.0.1:")[-1].split("/")[0]

    env = os.environ.copy()
    env["PORT"] = port

    print(f"Iniciando puente de WhatsApp (Node.js) en puerto {port}...")
    try:
        process = subprocess.Popen(
            ["node", "whatsapp_bridge.js"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env
        )
        
        app.state.whatsapp_bridge_process = process

        def read_logs():
            for line in iter(process.stdout.readline, ""):
                print(f"[WhatsApp Bridge Output] {line.strip()}")
            process.stdout.close()

        log_thread = threading.Thread(target=read_logs, daemon=True)
        log_thread.start()
        print("Subproceso del puente local de WhatsApp iniciado y monitoreado.")
    except Exception as e:
        print(f"Error al iniciar el puente de WhatsApp (Node.js): {e}")

@app.on_event("startup")
async def startup_bridge():
    iniciar_puente_whatsapp()

@app.on_event("shutdown")
async def shutdown_bridge():
    if hasattr(app.state, "whatsapp_bridge_process"):
        print("Terminando subproceso del puente de WhatsApp...")
        app.state.whatsapp_bridge_process.terminate()

