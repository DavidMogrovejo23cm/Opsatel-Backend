"""
@file movimientos.py
@description Gestión de movimientos internos y transferencias entre cuentas bancarias y efectivo.
"""
import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
import schemas
from database import get_db

router = APIRouter()

@router.get("/movimientos-internos")
def listar_movimientos_internos(mes: str, db: Session = Depends(get_db)):
    from .reportes import reporte_mensual

    movs = db.query(models.MovimientoInterno).filter(
        models.MovimientoInterno.mes == mes
    ).order_by(models.MovimientoInterno.id.asc()).all()

    total_efectivo_movido = sum(float(m.monto or 0) for m in movs if (m.origen or "").upper() == "EFECTIVO")
    total_pichincha_movido = sum(float(m.monto or 0) for m in movs if "PICHINCHA" in (m.origen or "").upper())
    total_jep_movido = sum(float(m.monto or 0) for m in movs if "JEP" in (m.origen or "").upper())

    total_efectivo_recibido = sum(float(m.monto or 0) for m in movs if (m.destino or "").upper() == "EFECTIVO")
    total_pichincha_recibido = sum(float(m.monto or 0) for m in movs if "PICHINCHA" in (m.destino or "").upper())
    total_jep_recibido = sum(float(m.monto or 0) for m in movs if "JEP" in (m.destino or "").upper())

    reporte = reporte_mensual(mes=mes, db=db)
    bancos_brutos = reporte.get("ingresos", {}).get("bancos", {})
    efectivo_bruto = float(bancos_brutos.get("efectivo", 0.0))
    pichincha_bruta = float(bancos_brutos.get("pichincha", 0.0))
    jep_bruta = float(bancos_brutos.get("jep", 0.0))

    efectivo_final = round(efectivo_bruto - total_efectivo_movido + total_efectivo_recibido, 2)
    pichincha_final = round(pichincha_bruta - total_pichincha_movido + total_pichincha_recibido, 2)
    jep_final = round(jep_bruta - total_jep_movido + total_jep_recibido, 2)

    return {
        "mes": mes,
        "movimientos": [
            {
                "id": m.id,
                "origen": m.origen,
                "destino": m.destino,
                "monto": float(m.monto or 0),
                "fecha": m.fecha,
                "mes": m.mes,
                "observacion": m.observacion,
                "created_at": m.created_at
            }
            for m in movs
        ],
        "totales_movidos": {
            "efectivo": round(total_efectivo_movido, 2),
            "pichincha": round(total_pichincha_movido, 2),
            "jep": round(total_jep_movido, 2)
        },
        "recaudacion_bruta": {
            "efectivo": efectivo_bruto,
            "pichincha": pichincha_bruta,
            "jep": jep_bruta
        },
        "saldos_finales": {
            "efectivo": efectivo_final,
            "pichincha": pichincha_final,
            "jep": jep_final
        }
    }


@router.post("/movimientos-internos")
def crear_movimiento_interno(data: schemas.MovimientoInternoCreate, db: Session = Depends(get_db)):
    mes = data.fecha[:7] if data.fecha and len(data.fecha) >= 7 else datetime.datetime.utcnow().strftime("%Y-%m")
    nuevo = models.MovimientoInterno(
        origen=data.origen,
        destino=data.destino,
        monto=data.monto,
        fecha=data.fecha,
        mes=mes,
        observacion=data.observacion
    )
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return nuevo


@router.put("/movimientos-internos/{mov_id}")
def actualizar_movimiento_interno(mov_id: int, data: schemas.MovimientoInternoUpdate, db: Session = Depends(get_db)):
    mov = db.query(models.MovimientoInterno).filter(models.MovimientoInterno.id == mov_id).first()
    if not mov:
        raise HTTPException(status_code=404, detail="Movimiento no encontrado")
    
    if data.origen is not None: mov.origen = data.origen
    if data.destino is not None: mov.destino = data.destino
    if data.monto is not None: mov.monto = data.monto
    if data.fecha is not None:
        mov.fecha = data.fecha
        mov.mes = data.fecha[:7] if len(data.fecha) >= 7 else mov.mes
    if data.observacion is not None: mov.observacion = data.observacion

    db.commit()
    db.refresh(mov)
    return mov


@router.delete("/movimientos-internos/{mov_id}")
def eliminar_movimiento_interno(mov_id: int, db: Session = Depends(get_db)):
    mov = db.query(models.MovimientoInterno).filter(models.MovimientoInterno.id == mov_id).first()
    if not mov:
        raise HTTPException(status_code=404, detail="Movimiento no encontrado")
    db.delete(mov)
    db.commit()
    return {"message": "Movimiento eliminado exitosamente"}
