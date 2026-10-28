"""
@file notificaciones.py
@description Rutas de gestión de notificaciones de cambios en Comentarios y Observaciones de clientes activos
@copyright (c) 2026 Opsatel.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, desc
from typing import List, Optional
from datetime import datetime
import models
from database import get_db
from .auth import get_current_user

router = APIRouter(prefix="/notificaciones", tags=["notificaciones"])

def _asegurar_tabla_notificaciones(db: Session):
    """Verifica si la tabla está vacía y siembra cambios existentes en clientes activos para primer uso"""
    try:
        total = db.query(models.NotificacionCliente).count()
        if total == 0:
            clientes_activos = db.query(models.Cliente).filter(
                func.lower(models.Cliente.estado) == "activo",
                or_(
                    (models.Cliente.comentarios.isnot(None)) & (models.Cliente.comentarios != ""),
                    (models.Cliente.observaciones.isnot(None)) & (models.Cliente.observaciones != "")
                )
            ).order_by(models.Cliente.id.desc()).limit(20).all()

            for c in clientes_activos:
                if c.comentarios and str(c.comentarios).strip():
                    db.add(models.NotificacionCliente(
                        cliente_id=c.id,
                        cliente_nombre=c.nombre or f"Cliente #{c.id}",
                        cliente_ip=c.ip or "",
                        campo="Comentario",
                        valor_anterior="",
                        valor_nuevo=str(c.comentarios).strip(),
                        usuario="sistema",
                        leido=False,
                        fecha=datetime.utcnow()
                    ))
                if c.observaciones and str(c.observaciones).strip():
                    db.add(models.NotificacionCliente(
                        cliente_id=c.id,
                        cliente_nombre=c.nombre or f"Cliente #{c.id}",
                        cliente_ip=c.ip or "",
                        campo="Observación",
                        valor_anterior="",
                        valor_nuevo=str(c.observaciones).strip(),
                        usuario="sistema",
                        leido=False,
                        fecha=datetime.utcnow()
                    ))
            db.commit()
    except Exception as e:
        print(f"Aviso al sembrar notificaciones iniciales: {e}")
        db.rollback()

@router.get("/")
@router.get("")
def listar_notificaciones(
    solo_no_leidas: bool = Query(True, description="Filtrar solo notificaciones no leídas"),
    limit: int = Query(100, description="Límite de resultados"),
    db: Session = Depends(get_db)
):
    _asegurar_tabla_notificaciones(db)
    
    query = db.query(models.NotificacionCliente)
    if solo_no_leidas:
        query = query.filter(models.NotificacionCliente.leido == False)
        
    notificaciones = query.order_by(desc(models.NotificacionCliente.fecha)).limit(limit).all()
    
    unread_count = db.query(models.NotificacionCliente).filter(models.NotificacionCliente.leido == False).count()
    
    return {
        "unread_count": unread_count,
        "total": len(notificaciones),
        "notificaciones": [
            {
                "id": n.id,
                "cliente_id": n.cliente_id,
                "cliente_nombre": n.cliente_nombre or "Cliente sin nombre",
                "cliente_ip": n.cliente_ip or "Sin IP",
                "campo": n.campo,
                "valor_anterior": n.valor_anterior or "",
                "valor_nuevo": n.valor_nuevo or "",
                "usuario": n.usuario or "sistema",
                "leido": n.leido,
                "fecha": n.fecha.isoformat() if n.fecha else datetime.utcnow().isoformat()
            }
            for n in notificaciones
        ]
    }

@router.get("/count")
def contador_no_leidas(db: Session = Depends(get_db)):
    _asegurar_tabla_notificaciones(db)
    count = db.query(models.NotificacionCliente).filter(models.NotificacionCliente.leido == False).count()
    return {"count": count}

@router.patch("/{id}/marcar-leida")
@router.patch("/{id}/leida")
def marcar_como_leida(id: int, db: Session = Depends(get_db)):
    notif = db.query(models.NotificacionCliente).filter(models.NotificacionCliente.id == id).first()
    if not notif:
        raise HTTPException(status_code=404, detail="Notificación no encontrada")
    
    notif.leido = True
    db.commit()
    
    unread_count = db.query(models.NotificacionCliente).filter(models.NotificacionCliente.leido == False).count()
    return {
        "message": "Notificación marcada como leída",
        "id": id,
        "unread_count": unread_count
    }

@router.patch("/marcar-todas-leidas")
def marcar_todas_leidas(db: Session = Depends(get_db)):
    count = db.query(models.NotificacionCliente).filter(models.NotificacionCliente.leido == False).update(
        {"leido": True},
        synchronize_session=False
    )
    db.commit()
    return {
        "message": "Todas las notificaciones han sido marcadas como leídas",
        "marcadas": count,
        "unread_count": 0
    }

@router.delete("/{id}")
def eliminar_notificacion(id: int, db: Session = Depends(get_db)):
    notif = db.query(models.NotificacionCliente).filter(models.NotificacionCliente.id == id).first()
    if not notif:
        raise HTTPException(status_code=404, detail="Notificación no encontrada")
    db.delete(notif)
    db.commit()
    return {"message": "Notificación eliminada"}
