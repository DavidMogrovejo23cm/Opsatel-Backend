"""
@file colchon.py
@description Gestión del fondo de reserva (Colchón) y consolidación mensual de superávit.
"""
from typing import List
import datetime
import calendar
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
from database import get_db
from routes.auth import require_role
from .schemas import ColchonCreate, ColchonUpdate, ConsolidarMesRequest

router = APIRouter()

@router.get("/colchon", response_model=List[dict])
def listar_colchon(db: Session = Depends(get_db)):
    return [
        {"id": c.id, "descripcion": c.descripcion, "monto": float(c.monto), "fecha": c.fecha}
        for c in db.query(models.Colchon).order_by(models.Colchon.fecha.desc()).all()
    ]


@router.post("/colchon", dependencies=[Depends(require_role(["administrador"]))])
def crear_colchon(data: ColchonCreate, db: Session = Depends(get_db)):
    obj = models.Colchon(**data.dict())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/colchon/resumen")
def resumen_colchon(db: Session = Depends(get_db)):
    colchones = db.query(models.Colchon).order_by(models.Colchon.fecha.desc(), models.Colchon.id.desc()).all()
    total_aportes = sum(float(c.monto or 0) for c in colchones)

    all_movs = db.query(models.MovimientoInterno).order_by(models.MovimientoInterno.fecha.desc(), models.MovimientoInterno.id.desc()).all()
    movs_desde_colchon = []
    movs_hacia_colchon = []
    total_retirado = 0.0
    total_ingresado_movs = 0.0

    for m in all_movs:
        orig = (m.origen or "").lower().strip()
        dest = (m.destino or "").lower().strip()
        es_orig_colchon = "colch" in orig or "reserva" in orig
        es_dest_colchon = "colch" in dest or "reserva" in dest
        val = float(m.monto or 0)

        if es_orig_colchon and not es_dest_colchon:
            total_retirado += val
            movs_desde_colchon.append({
                "id": m.id, "destino": m.destino, "monto": val,
                "fecha": m.fecha, "mes": m.mes, "observacion": m.observacion
            })
        elif es_dest_colchon and not es_orig_colchon:
            total_ingresado_movs += val
            movs_hacia_colchon.append({
                "id": m.id, "origen": m.origen, "monto": val,
                "fecha": m.fecha, "mes": m.mes, "observacion": m.observacion
            })

    saldo_disponible = round(total_aportes + total_ingresado_movs - total_retirado, 2)

    return {
        "saldo_disponible": saldo_disponible,
        "total_aportes": round(total_aportes, 2),
        "total_ingresado_movs": round(total_ingresado_movs, 2),
        "total_retirado": round(total_retirado, 2),
        "lista": [
            {"id": c.id, "descripcion": c.descripcion, "monto": float(c.monto), "fecha": c.fecha}
            for c in colchones
        ],
        "movimientos_desde_colchon": movs_desde_colchon,
        "movimientos_hacia_colchon": movs_hacia_colchon
    }


@router.post("/colchon/consolidar-mes", dependencies=[Depends(require_role(["administrador"]))])
def consolidar_mes_colchon(data: ConsolidarMesRequest, db: Session = Depends(get_db)):
    mes = data.mes.strip()
    if not mes or len(mes) < 7:
        raise HTTPException(status_code=400, detail="Formato de mes inválido (debe ser YYYY-MM)")

    registro_existente = db.query(models.Colchon).filter(
        models.Colchon.descripcion.like(f"%Superávit Mes {mes}%")
    ).first()

    if registro_existente and not data.forzar:
        raise HTTPException(
            status_code=400, 
            detail=f"El superávit del período {mes} ya fue consolidado previamente en el Colchón (${float(registro_existente.monto):.2f})."
        )

    try:
        from .reportes import reporte_mensual
        rep = reporte_mensual(mes=mes, db=db)
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Error al calcular el balance del mes {mes}: {str(err)}")

    bal_op = float(rep.get("balance_neto", 0.0) or 0.0)
    bal_iptv = float(rep.get("iptv_resumen", {}).get("balance_neto", {}).get("total", 0.0) or 0.0)
    bal_proy = float(rep.get("proyectos_resumen", {}).get("balance_neto", {}).get("total", 0.0) or 0.0)

    total_superavit = round(bal_op + bal_iptv + bal_proy, 2)

    if total_superavit <= 0:
        raise HTTPException(
            status_code=400,
            detail=f"El período {mes} no generó un superávit neto positivo (Operacional: ${bal_op:.2f}, IPTV: ${bal_iptv:.2f}, Proy: ${bal_proy:.2f}). Total neto: ${total_superavit:.2f}"
        )

    try:
        year, month = map(int, mes.split("-"))
        _, last_day = calendar.monthrange(year, month)
        fecha_asiento = f"{year:04d}-{month:02d}-{last_day:02d}"
    except Exception:
        fecha_asiento = datetime.datetime.utcnow().strftime("%Y-%m-%d")

    desc_asiento = f"Superávit Mes {mes} (Operacional: ${bal_op:.2f}, IPTV: ${bal_iptv:.2f}, Proy: ${bal_proy:.2f})"

    if registro_existente and data.forzar:
        registro_existente.descripcion = desc_asiento
        registro_existente.monto = total_superavit
        registro_existente.fecha = fecha_asiento
        db.commit()
        db.refresh(registro_existente)
        asiento = registro_existente
    else:
        asiento = models.Colchon(
            descripcion=desc_asiento,
            monto=total_superavit,
            fecha=fecha_asiento
        )
        db.add(asiento)
        db.commit()
        db.refresh(asiento)

    return {
        "message": f"Superávit de {mes} por ${total_superavit:.2f} consolidado con éxito al Colchón / Fondo de Reserva.",
        "asiento": {
            "id": asiento.id,
            "descripcion": asiento.descripcion,
            "monto": float(asiento.monto),
            "fecha": asiento.fecha
        },
        "detalles": {
            "operacional": bal_op,
            "iptv": bal_iptv,
            "proyectos": bal_proy,
            "total_superavit": total_superavit
        }
    }


@router.patch("/colchon/{id}", dependencies=[Depends(require_role(["administrador"]))])
def actualizar_colchon(id: int, data: ColchonUpdate, db: Session = Depends(get_db)):
    obj = db.query(models.Colchon).filter(models.Colchon.id == id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Registro de colchón no encontrado")
    for k, v in data.dict(exclude_none=True).items():
        setattr(obj, k, v)
    db.commit()
    return {"message": "Colchón actualizado"}


@router.delete("/colchon/{id}", dependencies=[Depends(require_role(["administrador"]))])
def eliminar_colchon(id: int, db: Session = Depends(get_db)):
    obj = db.query(models.Colchon).filter(models.Colchon.id == id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Registro de colchón no encontrado")
    db.delete(obj)
    db.commit()
    return {"message": "Colchón eliminado"}
