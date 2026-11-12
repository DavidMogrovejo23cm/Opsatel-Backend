"""
@file egresos.py
@description Endpoints CRUD para gestión de egresos operativos y de proyectos.
"""
from typing import Optional
import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
from database import get_db
from routes.auth import require_role
from .schemas import EgresoCreate, EgresoUpdate
from .utils import sincronizar_gastos_fijos_mes

router = APIRouter()

@router.get("/egresos")
def listar_egresos(mes: Optional[str] = None, db: Session = Depends(get_db)):
    if mes:
        sincronizar_gastos_fijos_mes(mes, db)
    else:
        mes_actual = datetime.date.today().strftime("%Y-%m")
        sincronizar_gastos_fijos_mes(mes_actual, db)

    q = db.query(models.Egreso)
    if mes:
        q = q.filter(models.Egreso.mes == mes)
    return q.order_by(models.Egreso.fecha.desc(), models.Egreso.id.desc()).all()


@router.post("/egresos", dependencies=[Depends(require_role(["administrador"]))])
def crear_egreso(data: EgresoCreate, db: Session = Depends(get_db)):
    egreso = models.Egreso(**data.dict())
    db.add(egreso)
    db.commit()
    db.refresh(egreso)
    return egreso


@router.patch("/egresos/{id}", dependencies=[Depends(require_role(["administrador"]))])
def actualizar_egreso(id: int, data: EgresoUpdate, db: Session = Depends(get_db)):
    egreso = db.query(models.Egreso).filter(models.Egreso.id == id).first()
    if not egreso:
        raise HTTPException(status_code=404, detail="Egreso no encontrado")
    for k, v in data.dict(exclude_none=True).items():
        setattr(egreso, k, v)
    db.commit()
    return {"message": "Egreso actualizado"}


@router.delete("/egresos/{id}", dependencies=[Depends(require_role(["administrador"]))])
def eliminar_egreso(id: int, db: Session = Depends(get_db)):
    egreso = db.query(models.Egreso).filter(models.Egreso.id == id).first()
    if not egreso:
        raise HTTPException(status_code=404, detail="Egreso no encontrado")
    db.delete(egreso)
    db.commit()
    return {"message": "Egreso eliminado"}
