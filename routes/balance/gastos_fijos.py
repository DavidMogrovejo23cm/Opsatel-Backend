"""
@file gastos_fijos.py
@description Gestión de catálogo de gastos fijos y sincronización periódica.
"""
import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
from database import get_db
from routes.auth import require_role
from .schemas import GastoFijoCreate, GastoFijoUpdate
from .utils import sincronizar_gastos_fijos_mes

router = APIRouter()

@router.get("/gastos-fijos")
def listar_gastos_fijos(db: Session = Depends(get_db)):
    return [
        {
            "id": g.id, "descripcion": g.descripcion, "monto": float(g.monto),
            "categoria": g.categoria, "metodo_pago": g.metodo_pago,
            "activo": g.activo, "notas": g.notas
        }
        for g in db.query(models.GastoFijo).order_by(models.GastoFijo.id).all()
    ]


@router.post("/gastos-fijos", dependencies=[Depends(require_role(["administrador"]))])
def crear_gasto_fijo(data: GastoFijoCreate, db: Session = Depends(get_db)):
    obj = models.GastoFijo(**data.dict())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    if obj.activo:
        mes_actual = datetime.date.today().strftime("%Y-%m")
        sincronizar_gastos_fijos_mes(mes_actual, db)
    return obj


@router.patch("/gastos-fijos/{id}", dependencies=[Depends(require_role(["administrador"]))])
def actualizar_gasto_fijo(id: int, data: GastoFijoUpdate, db: Session = Depends(get_db)):
    obj = db.query(models.GastoFijo).filter(models.GastoFijo.id == id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Gasto fijo no encontrado")
    for k, v in data.dict(exclude_none=True).items():
        setattr(obj, k, v)
    db.commit()
    
    # Si se desactiva (activo=False), eliminar los egresos que todavía estén 'Pendiente'
    if data.activo is False:
        db.query(models.Egreso).filter(
            models.Egreso.gasto_fijo_id == id,
            models.Egreso.estado == "Pendiente"
        ).delete(synchronize_session=False)
        db.commit()
    elif obj.activo:
        mes_actual = datetime.date.today().strftime("%Y-%m")
        sincronizar_gastos_fijos_mes(mes_actual, db)

    return {"message": "Gasto fijo actualizado"}


@router.delete("/gastos-fijos/{id}", dependencies=[Depends(require_role(["administrador"]))])
def eliminar_gasto_fijo(id: int, db: Session = Depends(get_db)):
    obj = db.query(models.GastoFijo).filter(models.GastoFijo.id == id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Gasto fijo no encontrado")
    # Limpiar egresos pendientes asociados
    db.query(models.Egreso).filter(
        models.Egreso.gasto_fijo_id == id,
        models.Egreso.estado == "Pendiente"
    ).delete(synchronize_session=False)
    # A los ya realizados, desvincular el ID para preservar el historial contable
    db.query(models.Egreso).filter(models.Egreso.gasto_fijo_id == id).update({"gasto_fijo_id": None})
    db.delete(obj)
    db.commit()
    return {"message": "Gasto fijo eliminado"}
