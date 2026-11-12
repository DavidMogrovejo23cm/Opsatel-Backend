"""
@file proyectos.py
@description Gestión de Proyectos, Cuotas/Pagos de Proyecto y Gastos/Nóminas de Proyecto.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
from database import get_db
from routes.auth import require_role
from .schemas import (
    ProyectoCreate, ProyectoUpdate,
    ProyectoPagoCreate, ProyectoPagoUpdate,
    GastoProyectoCreate, GastoProyectoUpdate
)

router = APIRouter()

# --------------------------------------------------------------------
# PROYECTOS CRUD
# --------------------------------------------------------------------

@router.get("/proyectos")
def listar_proyectos(db: Session = Depends(get_db)):
    proyectos = db.query(models.Proyecto).order_by(models.Proyecto.fecha_inicio.desc()).all()
    return sorted(
        proyectos,
        key=lambda p: (1 if (p.estado or "").strip().lower() == "completado" else 0)
    )


@router.post("/proyectos", dependencies=[Depends(require_role(["administrador"]))])
def crear_proyecto(data: ProyectoCreate, db: Session = Depends(get_db)):
    proyecto = models.Proyecto(**data.dict())
    db.add(proyecto)
    db.commit()
    db.refresh(proyecto)
    return proyecto


@router.patch("/proyectos/{id}", dependencies=[Depends(require_role(["administrador"]))])
def actualizar_proyecto(id: int, data: ProyectoUpdate, db: Session = Depends(get_db)):
    proyecto = db.query(models.Proyecto).filter(models.Proyecto.id == id).first()
    if not proyecto:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    for k, v in data.dict(exclude_none=True).items():
        setattr(proyecto, k, v)
    db.commit()
    return {"message": "Proyecto actualizado"}


@router.delete("/proyectos/{id}", dependencies=[Depends(require_role(["administrador"]))])
def eliminar_proyecto(id: int, db: Session = Depends(get_db)):
    proyecto = db.query(models.Proyecto).filter(models.Proyecto.id == id).first()
    if not proyecto:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    db.query(models.ProyectoPago).filter(models.ProyectoPago.proyecto_id == id).delete()
    db.query(models.GastoProyecto).filter(models.GastoProyecto.proyecto_id == id).delete()
    db.delete(proyecto)
    db.commit()
    return {"message": "Proyecto eliminado"}


# --------------------------------------------------------------------
# PROYECTO PAGOS (Cuotas / Aportes)
# --------------------------------------------------------------------

@router.get("/proyectos/{proyecto_id}/pagos")
def listar_proyecto_pagos(proyecto_id: int, db: Session = Depends(get_db)):
    return db.query(models.ProyectoPago)\
        .filter(models.ProyectoPago.proyecto_id == proyecto_id)\
        .order_by(models.ProyectoPago.id).all()


@router.post("/proyectos/{proyecto_id}/pagos", dependencies=[Depends(require_role(["administrador"]))])
def crear_proyecto_pago(proyecto_id: int, data: ProyectoPagoCreate, db: Session = Depends(get_db)):
    pago = models.ProyectoPago(proyecto_id=proyecto_id, **data.dict())
    db.add(pago)
    db.commit()
    db.refresh(pago)
    return pago


@router.patch("/proyectos/{proyecto_id}/pagos/{pago_id}", dependencies=[Depends(require_role(["administrador"]))])
def actualizar_proyecto_pago(proyecto_id: int, pago_id: int, data: ProyectoPagoUpdate, db: Session = Depends(get_db)):
    pago = db.query(models.ProyectoPago).filter(
        models.ProyectoPago.id == pago_id,
        models.ProyectoPago.proyecto_id == proyecto_id
    ).first()
    if not pago:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    for k, v in data.dict(exclude_none=True).items():
        setattr(pago, k, v)
    db.commit()
    return {"message": "Pago actualizado"}


@router.delete("/proyectos/{proyecto_id}/pagos/{pago_id}", dependencies=[Depends(require_role(["administrador"]))])
def eliminar_proyecto_pago(proyecto_id: int, pago_id: int, db: Session = Depends(get_db)):
    pago = db.query(models.ProyectoPago).filter(
        models.ProyectoPago.id == pago_id,
        models.ProyectoPago.proyecto_id == proyecto_id
    ).first()
    if not pago:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    db.delete(pago)
    db.commit()
    return {"message": "Pago eliminado"}


# --------------------------------------------------------------------
# GASTOS PROYECTO
# --------------------------------------------------------------------

@router.get("/proyectos/{proyecto_id}/gastos")
def listar_gastos_proyecto(proyecto_id: int, db: Session = Depends(get_db)):
    gastos = db.query(models.GastoProyecto)\
        .filter(models.GastoProyecto.proyecto_id == proyecto_id)\
        .order_by(models.GastoProyecto.subcategoria, models.GastoProyecto.item).all()

    grouped = {}
    for g in gastos:
        cat = g.subcategoria or "GENERAL"
        if cat not in grouped:
            grouped[cat] = {"items": [], "subtotal": 0.0}
        grouped[cat]["items"].append({
            "id":          g.id,
            "item":        g.item,
            "descripcion": g.descripcion,
            "fecha":       g.fecha,
            "tipo_pago":   g.tipo_pago,
            "valor":       float(g.valor or 0),
            "pendiente":   g.pendiente,
        })
        if not g.pendiente:
            grouped[cat]["subtotal"] += float(g.valor or 0)

    total = sum(v["subtotal"] for v in grouped.values())
    return {"grupos": grouped, "total": total, "flat": [
        {
            "id":          g.id,
            "subcategoria": g.subcategoria,
            "item":        g.item,
            "descripcion": g.descripcion,
            "fecha":       g.fecha,
            "tipo_pago":   g.tipo_pago,
            "valor":       float(g.valor or 0),
            "pendiente":   g.pendiente,
        } for g in gastos
    ]}


@router.post("/proyectos/{proyecto_id}/gastos", dependencies=[Depends(require_role(["administrador"]))])
def crear_gasto_proyecto(proyecto_id: int, data: GastoProyectoCreate, db: Session = Depends(get_db)):
    gasto = models.GastoProyecto(proyecto_id=proyecto_id, **data.dict())
    db.add(gasto)
    db.commit()
    db.refresh(gasto)
    return gasto


@router.patch("/proyectos/{proyecto_id}/gastos/{gasto_id}", dependencies=[Depends(require_role(["administrador"]))])
def actualizar_gasto_proyecto(proyecto_id: int, gasto_id: int, data: GastoProyectoUpdate, db: Session = Depends(get_db)):
    gasto = db.query(models.GastoProyecto).filter(
        models.GastoProyecto.id == gasto_id,
        models.GastoProyecto.proyecto_id == proyecto_id
    ).first()
    if not gasto:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")
    for k, v in data.dict(exclude_none=True).items():
        setattr(gasto, k, v)
    db.commit()
    return {"message": "Gasto actualizado"}


@router.delete("/proyectos/{proyecto_id}/gastos/{gasto_id}", dependencies=[Depends(require_role(["administrador"]))])
def eliminar_gasto_proyecto(proyecto_id: int, gasto_id: int, db: Session = Depends(get_db)):
    gasto = db.query(models.GastoProyecto).filter(
        models.GastoProyecto.id == gasto_id,
        models.GastoProyecto.proyecto_id == proyecto_id
    ).first()
    if not gasto:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")
    db.delete(gasto)
    db.commit()
    return {"message": "Gasto eliminado"}
