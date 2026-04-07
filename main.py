from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from database import engine, Base
import models
import os
from routes import auth, clientes, extras, hoja_ruta
import rutas_configuraciones
from sync_db import sync_schema

# Sincroniza las columnas e inicializa tablas
sync_schema()
Base.metadata.create_all(bind=engine)

# Iniciar App
app = FastAPI(title="ISP Management API")

# Silenciar favicon.ico 404
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Enrutadores
app.include_router(auth.router)
app.include_router(clientes.router)
app.include_router(extras.router)
app.include_router(hoja_ruta.router)
app.include_router(rutas_configuraciones.router)

from fastapi.staticfiles import StaticFiles
os.makedirs("rutas_reportes", exist_ok=True)
os.makedirs("uploads/cedulas", exist_ok=True)
app.mount("/rutas_reportes", StaticFiles(directory="rutas_reportes"), name="rutas_reportes")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

@app.get("/")
def read_root():
    return {"message": "Bienvenido a la API de Gestión de ISP Opsatel"}
