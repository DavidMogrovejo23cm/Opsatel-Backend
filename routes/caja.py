# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, HTTPException, status
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import Session
from database import get_db
from .auth import get_current_user, require_role
import models
import schemas
from datetime import datetime
from typing import Optional

router = APIRouter(prefix="/caja", tags=["caja"])

@router.post("/apertura", response_model=schemas.TurnoCajaResponse, dependencies=[Depends(require_role(["administrador", "secretario"]))])
def abrir_caja(
    data: schemas.TurnoCajaCreate,
    current_user: models.Usuario = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Verificar si el usuario ya tiene un turno abierto
    turno_activo = db.query(models.TurnoCaja).filter(
        models.TurnoCaja.usuario_id == current_user.id,
        models.TurnoCaja.estado == "Abierto"
    ).first()
    
    if turno_activo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ya tienes un turno de caja abierto. Debes cerrarlo antes de abrir uno nuevo."
        )
        
    nuevo_turno = models.TurnoCaja(
        usuario_id=current_user.id,
        fecha_apertura=datetime.utcnow(),
        efectivo_apertura=data.efectivo_apertura,
        pichincha_apertura=data.pichincha_apertura,
        jep_apertura=data.jep_apertura,
        estado="Abierto"
    )
    
    db.add(nuevo_turno)
    db.commit()
    db.refresh(nuevo_turno)
    return nuevo_turno

@router.post("/cierre", response_model=schemas.TurnoCajaResponse, dependencies=[Depends(require_role(["administrador", "secretario"]))])
def cerrar_caja(
    data: schemas.TurnoCajaClose,
    current_user: models.Usuario = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Obtener el turno abierto
    turno = db.query(models.TurnoCaja).filter(
        models.TurnoCaja.usuario_id == current_user.id,
        models.TurnoCaja.estado == "Abierto"
    ).first()
    
    if not turno:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No se encontró ningún turno de caja abierto para tu usuario."
        )
        
    # Calcular cobros registrados en este turno
    pagos_normales = db.query(models.Pago).filter(
        models.Pago.turnocaja_id == turno.id,
        models.Pago.estado == "Completado",
        models.Pago.anulado == False
    ).all()
    
    pagos_extras = db.query(models.PagoExtra).filter(
        models.PagoExtra.turnocaja_id == turno.id,
        models.PagoExtra.estado == "Completado",
        models.PagoExtra.anulado == False
    ).all()
    
    efectivo_cobrado = 0.0
    pichincha_cobrado = 0.0
    jep_cobrado = 0.0
    
    for p in pagos_normales:
        metodo = (p.metodo_pago or "").upper()
        monto = float(p.monto or 0)
        if "PICHINCHA" in metodo:
            pichincha_cobrado += monto
        elif "JEP" in metodo:
            jep_cobrado += monto
        else:
            efectivo_cobrado += monto
            
    for p in pagos_extras:
        metodo = (p.metodo_pago or "").upper()
        monto = float(p.monto or 0)
        if "PICHINCHA" in metodo:
            pichincha_cobrado += monto
        elif "JEP" in metodo:
            jep_cobrado += monto
        else:
            efectivo_cobrado += monto
            
    # Calcular saldos esperados
    turno.efectivo_cierre = float(turno.efectivo_apertura) + efectivo_cobrado
    turno.pichincha_cierre = float(turno.pichincha_apertura) + pichincha_cobrado
    turno.jep_cierre = float(turno.jep_apertura) + jep_cobrado
    
    # Asignar conteo físico real
    turno.efectivo_real = data.efectivo_real
    turno.pichincha_real = data.pichincha_real
    turno.jep_real = data.jep_real
    
    turno.estado = "Cerrado"
    turno.fecha_cierre = datetime.utcnow()
    turno.observaciones = data.observaciones
    
    db.commit()
    db.refresh(turno)
    return turno

@router.get("/estado-actual", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def obtener_estado_actual(
    current_user: models.Usuario = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    turno = db.query(models.TurnoCaja).filter(
        models.TurnoCaja.usuario_id == current_user.id,
        models.TurnoCaja.estado == "Abierto"
    ).first()
    
    if not turno:
        return {"estado": "Sin_Turno"}
        
    # Calcular en tiempo real lo acumulado
    pagos_normales = db.query(models.Pago).filter(
        models.Pago.turnocaja_id == turno.id,
        models.Pago.estado == "Completado",
        models.Pago.anulado == False
    ).all()
    
    pagos_extras = db.query(models.PagoExtra).filter(
        models.PagoExtra.turnocaja_id == turno.id,
        models.PagoExtra.estado == "Completado",
        models.PagoExtra.anulado == False
    ).all()
    
    efectivo_cobrado = 0.0
    pichincha_cobrado = 0.0
    jep_cobrado = 0.0
    
    for p in pagos_normales:
        metodo = (p.metodo_pago or "").upper()
        monto = float(p.monto or 0)
        if "PICHINCHA" in metodo:
            pichincha_cobrado += monto
        elif "JEP" in metodo:
            jep_cobrado += monto
        else:
            efectivo_cobrado += monto
            
    for p in pagos_extras:
        metodo = (p.metodo_pago or "").upper()
        monto = float(p.monto or 0)
        if "PICHINCHA" in metodo:
            pichincha_cobrado += monto
        elif "JEP" in metodo:
            jep_cobrado += monto
        else:
            efectivo_cobrado += monto
            
    return {
        "estado": "Abierto",
        "turno": {
            "id": turno.id,
            "usuario_id": turno.usuario_id,
            "usuario_username": current_user.username,
            "fecha_apertura": turno.fecha_apertura,
            "efectivo_apertura": float(turno.efectivo_apertura),
            "pichincha_apertura": float(turno.pichincha_apertura),
            "jep_apertura": float(turno.jep_apertura),
            "efectivo_esperado": float(turno.efectivo_apertura) + efectivo_cobrado,
            "pichincha_esperado": float(turno.pichincha_apertura) + pichincha_cobrado,
            "jep_esperado": float(turno.jep_apertura) + jep_cobrado,
            "efectivo_cobrado": efectivo_cobrado,
            "pichincha_cobrado": pichincha_cobrado,
            "jep_cobrado": jep_cobrado
        }
    }
