from fastapi import FastAPI

from fastapi.middleware.cors import CORSMiddleware

from database import engine, Base

import models

from routes import auth, clientes, extras



                                                                       

# Sincroniza las columnas (añade lo que falte automáticamente)
from sync_db import sync_schema
sync_schema()

# Inicializa las tablas en MySQL automáticamente (si no existen)
Base.metadata.create_all(bind=engine)

# ========================================================================
# MOTOR CENTRAL DE LA API (FastAPI)
# ========================================================================
app = FastAPI(title="ISP Management API")

# ========================================================================
# SISTEMA DE SEGURIDAD CORS
# ========================================================================
# Esto es crítico para que 'opsatelFrontend' (que corre en un puerto distinto o IP distinta) 
# tenga permiso de consultar esta API sin ser bloqueado por el navegador web.
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
]



app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"], # Permite GET, POST, PATCH, DELETE, etc.
    allow_headers=["*"],
)

# Enrutador: Conecta todo el archivo 'clientes.py' hacia la raíz de la app
from routes import clientes, auth
import rutas_configuraciones

app.include_router(auth.router)
app.include_router(clientes.router)
app.include_router(extras.router)
app.include_router(rutas_configuraciones.router)

from fastapi.staticfiles import StaticFiles
import os
os.makedirs("rutas_reportes", exist_ok=True)
os.makedirs("uploads/cedulas", exist_ok=True)
app.mount("/rutas_reportes", StaticFiles(directory="rutas_reportes"), name="rutas_reportes")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")



@app.get("/")

def read_root():

    return {"message": "Bienvenido a la API de Gestión de ISP Opsatel"}

