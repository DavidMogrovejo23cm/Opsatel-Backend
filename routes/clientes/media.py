"""
@file media.py
@description Gestión de carga, optimización y compresión de fotos de cédula, fachada y equipos/dispositivos.
"""
import os
import shutil
import json
import logging
from datetime import datetime
from PIL import Image, ImageOps
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Form
from sqlalchemy.orm import Session

import models
from database import get_db
from routes.auth import require_role

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except Exception:
    pass

logger = logging.getLogger("opsatel.routes.clientes.media")

router = APIRouter()

def save_and_optimize_image(upload_file: UploadFile, dest_path_without_ext: str, max_dimension: int = 2048, quality: int = 85) -> str:
    """
    Guarda y optimiza una imagen subida (JPEG, PNG, WEBP, HEIC/HEIF de iPhone, etc.).
    Corrige la orientación EXIF automáticamente (vital para fotos tomadas con celulares).
    Redimensiona proporcionalmente a max_dimension y comprime en formato JPEG optimizado.
    Retorna la ruta relativa final con extensión comenzando con '/'.
    """
    os.makedirs(os.path.dirname(dest_path_without_ext), exist_ok=True)
    final_path = f"{dest_path_without_ext}.jpg"
    try:
        upload_file.file.seek(0)
        img = Image.open(upload_file.file)
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "P", "LA"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            background.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        if max(img.size) > max_dimension:
            img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

        img.save(final_path, format="JPEG", quality=quality, optimize=True)
        return f"/{final_path}"
    except Exception as e:
        logger.warning(f"Error optimizando imagen con Pillow ({e}), guardando archivo directo")
        upload_file.file.seek(0)
        ext = os.path.splitext(upload_file.filename)[1] if upload_file.filename else ".jpg"
        fallback_path = f"{dest_path_without_ext}{ext}"
        with open(fallback_path, "wb") as buffer:
            shutil.copyfileobj(upload_file.file, buffer)
        return f"/{fallback_path}"


@router.post("/{id}/upload-cedula", dependencies=[Depends(require_role(["administrador", "secretario", "tecnico"]))])
async def upload_cedula(
    id: int, 
    frontal: UploadFile = File(None), 
    posterior: UploadFile = File(None), 
    fachada: UploadFile = File(None), 
    db: Session = Depends(get_db)
):
    cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    upload_dir = "uploads/cedulas"
    os.makedirs(upload_dir, exist_ok=True)

    # Validar límite de memoria/tamaño de hasta 25 MB para cualquier foto
    MAX_FILE_SIZE = 25 * 1024 * 1024 # 25 MB
    for f_obj, f_name in [(frontal, "Frontal"), (posterior, "Posterior"), (fachada, "Fachada")]:
        if f_obj and f_obj.filename:
            f_obj.file.seek(0, os.SEEK_END)
            size = f_obj.file.tell()
            f_obj.file.seek(0)
            if size > MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=400,
                    detail=f"La foto {f_name} supera el límite máximo de 20 MB (tamaño: {round(size / (1024*1024), 2)} MB)."
                )

    timestamp = int(datetime.now().timestamp())

    if frontal and frontal.filename:
        cliente.cedula_frontal = save_and_optimize_image(frontal, f"{upload_dir}/frontal_{id}_{timestamp}")
        
    if posterior and posterior.filename:
        cliente.cedula_posterior = save_and_optimize_image(posterior, f"{upload_dir}/posterior_{id}_{timestamp}")

    if fachada and fachada.filename:
        cliente.foto_fachada = save_and_optimize_image(fachada, f"{upload_dir}/fachada_{id}_{timestamp}")
    
    db.commit()
    return {
        "message": "Imágenes subidas y optimizadas exitosamente",
        "cedula_frontal": cliente.cedula_frontal,
        "cedula_posterior": cliente.cedula_posterior,
        "foto_fachada": cliente.foto_fachada
    }


@router.post("/{id}/upload-fachada", dependencies=[Depends(require_role(["administrador", "secretario", "tecnico"]))])
async def upload_fachada(id: int, fachada: UploadFile = File(...), db: Session = Depends(get_db)):
    cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    MAX_FILE_SIZE = 25 * 1024 * 1024 # 25 MB
    if not fachada or not fachada.filename:
        raise HTTPException(status_code=400, detail="Debe seleccionar una foto de la fachada.")

    fachada.file.seek(0, os.SEEK_END)
    size = fachada.file.tell()
    fachada.file.seek(0)
    if size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"La foto de fachada supera el límite de 20 MB (tamaño: {round(size / (1024*1024), 2)} MB)."
        )

    upload_dir = "uploads/cedulas"
    os.makedirs(upload_dir, exist_ok=True)
    timestamp = int(datetime.now().timestamp())
    cliente.foto_fachada = save_and_optimize_image(fachada, f"{upload_dir}/fachada_{id}_{timestamp}")
    db.commit()

    return {
        "message": "Foto de fachada subida y optimizada exitosamente",
        "foto_fachada": cliente.foto_fachada
    }


@router.post("/{id}/upload-dispositivo", dependencies=[Depends(require_role(["administrador", "secretario", "tecnico"]))])
async def upload_dispositivo(
    id: int, 
    equipo_ont: UploadFile = File(None), 
    equipo_router: UploadFile = File(None), 
    modelo: str = Form(None),
    remove_ont: bool = Form(False),
    remove_router: bool = Form(False),
    db: Session = Depends(get_db)
):
    cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    upload_dir = "uploads/dispositivos"
    os.makedirs(upload_dir, exist_ok=True)

    # Validar límite de memoria/tamaño de hasta 25 MB
    MAX_FILE_SIZE = 25 * 1024 * 1024 # 25 MB
    for f_obj, f_name in [(equipo_ont, "Equipo Bridge/ONT"), (equipo_router, "Router")]:
        if f_obj and f_obj.filename:
            f_obj.file.seek(0, os.SEEK_END)
            size = f_obj.file.tell()
            f_obj.file.seek(0)
            if size > MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=400,
                    detail=f"La foto de {f_name} supera el límite máximo de 20 MB (tamaño: {round(size / (1024*1024), 2)} MB)."
                )

    timestamp = int(datetime.now().timestamp())

    # Leer valor previo si existe
    existing_data = {}
    if cliente.dispositivo:
        raw_val = str(cliente.dispositivo).strip()
        if raw_val.startswith("{") and raw_val.endswith("}"):
            try:
                parsed = json.loads(raw_val)
                if isinstance(parsed, dict):
                    existing_data = parsed
            except Exception:
                existing_data = {"texto": raw_val}
        else:
            existing_data = {"texto": raw_val}

    if remove_ont and "ont" in existing_data:
        old_ont = existing_data.pop("ont", None)
        if old_ont:
            old_p = str(old_ont).lstrip("/")
            if os.path.exists(old_p):
                try: os.remove(old_p)
                except Exception: pass

    if remove_router and "router" in existing_data:
        old_router = existing_data.pop("router", None)
        if old_router:
            old_p = str(old_router).lstrip("/")
            if os.path.exists(old_p):
                try: os.remove(old_p)
                except Exception: pass

    if equipo_ont and equipo_ont.filename:
        existing_data["ont"] = save_and_optimize_image(equipo_ont, f"{upload_dir}/ont_{id}_{timestamp}")

    if equipo_router and equipo_router.filename:
        existing_data["router"] = save_and_optimize_image(equipo_router, f"{upload_dir}/router_{id}_{timestamp}")

    if modelo is not None and str(modelo).strip() != "":
        existing_data["texto"] = str(modelo).strip()

    cliente.dispositivo = json.dumps(existing_data, ensure_ascii=False)
    db.commit()

    return {
        "message": "Fotos de equipos guardadas y optimizadas exitosamente en Dispositivo",
        "dispositivo": cliente.dispositivo,
        "ont": existing_data.get("ont"),
        "router": existing_data.get("router"),
        "texto": existing_data.get("texto")
    }
