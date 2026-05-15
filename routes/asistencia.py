from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
import models, schemas
from database import get_db
from datetime import datetime, timedelta
from .auth import get_current_user, require_role

router = APIRouter(prefix="/asistencia", tags=["asistencia"])

def get_ecuador_time():
    # Ecuador es UTC-5 fijo (sin horario de verano)
    return datetime.utcnow() - timedelta(hours=5)

@router.post("/registrar", response_model=schemas.AsistenciaResponse)
def registrar_asistencia(
    data: schemas.AsistenciaCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    # Verificar si ya registró asistencia hoy
    ahora_ec = get_ecuador_time()
    hoy = ahora_ec.strftime("%Y-%m-%d")
    existente = db.query(models.Asistencia).filter(
        models.Asistencia.usuario_id == current_user.id,
        models.Asistencia.fecha == hoy
    ).first()
    
    if existente:
        raise HTTPException(status_code=400, detail="Ya has registrado tu asistencia por hoy.")

    nueva_asistencia = models.Asistencia(
        usuario_id=current_user.id,
        nombre_usuario=current_user.username,
        fecha=hoy,
        hora_entrada=data.hora_dispositivo if data.hora_dispositivo else ahora_ec.strftime("%H:%M:%S"),
        ubicacion=data.ubicacion,
        distancia_metros=data.distancia_metros,
        dispositivo_info=data.dispositivo_info,
        biometria_validada=data.biometria_validada
    )
    db.add(nueva_asistencia)
    db.commit()
    db.refresh(nueva_asistencia)
    return nueva_asistencia

@router.get("/estado-hoy", response_model=schemas.AsistenciaStatusResponse)
def estado_asistencia_hoy(
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    ahora_ec = get_ecuador_time()
    hoy = ahora_ec.strftime("%Y-%m-%d")
    asistencia = db.query(models.Asistencia).filter(
        models.Asistencia.usuario_id == current_user.id,
        models.Asistencia.fecha == hoy
    ).first()

    if not asistencia:
        return {
            "ha_entrado": False,
            "ha_salido": False,
            "hora_entrada": None,
            "asistencia_id": None,
            "puede_salir": False
        }

    # Verificar restricción de 4 horas
    try:
        hora_ent = datetime.strptime(f"{hoy} {asistencia.hora_entrada}", "%Y-%m-%d %H:%M:%S")
        diff = ahora_ec - hora_ent
        puede_salir = diff.total_seconds() >= (4 * 3600)
        
        minutos_restantes = round((4*3600 - diff.total_seconds())/60)
        mensaje = None if puede_salir else f"Deben pasar 4 horas desde la entrada. Faltan {minutos_restantes} min."
    except:
        puede_salir = True
        mensaje = None

    return {
        "ha_entrado": True,
        "ha_salido": bool(asistencia.hora_salida),
        "hora_entrada": asistencia.hora_entrada,
        "asistencia_id": asistencia.id,
        "puede_salir": puede_salir,
        "mensaje_restriccion": mensaje
    }

@router.post("/registrar-salida", response_model=schemas.AsistenciaResponse)
def registrar_salida(
    data: schemas.AsistenciaCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    ahora_ec = get_ecuador_time()
    hoy = ahora_ec.strftime("%Y-%m-%d")
    asistencia = db.query(models.Asistencia).filter(
        models.Asistencia.usuario_id == current_user.id,
        models.Asistencia.fecha == hoy
    ).first()

    if not asistencia:
        raise HTTPException(status_code=400, detail="No has registrado entrada hoy.")
    
    if asistencia.hora_salida:
        raise HTTPException(status_code=400, detail="Ya has registrado salida hoy.")

    # Validar 4 horas
    try:
        hora_ent = datetime.strptime(f"{hoy} {asistencia.hora_entrada}", "%Y-%m-%d %H:%M:%S")
        if (ahora_ec - hora_ent).total_seconds() < (4 * 3600):
            raise HTTPException(status_code=400, detail="No han pasado 4 horas desde tu entrada.")
    except Exception as e:
        pass # Si falla el parseo por algún motivo, permitimos el paso

    asistencia.hora_salida = data.hora_dispositivo if data.hora_dispositivo else ahora_ec.strftime("%H:%M:%S")
    asistencia.ubicacion_salida = data.ubicacion
    asistencia.distancia_metros_salida = data.distancia_metros
    asistencia.biometria_salida_validada = data.biometria_validada
    
    db.commit()
    db.refresh(asistencia)
    return asistencia

@router.get("/", response_model=List[schemas.AsistenciaResponse])
def listar_asistencias(
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(require_role(["administrador"]))
):
    query = db.query(models.Asistencia)
    
    if fecha_inicio:
        query = query.filter(models.Asistencia.fecha >= fecha_inicio)
    if fecha_fin:
        query = query.filter(models.Asistencia.fecha <= fecha_fin)
        
    return query.order_by(models.Asistencia.created_at.desc()).all()
