# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, HTTPException
# pyrefly: ignore [missing-import]
from fastapi.responses import FileResponse
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import Session
from typing import List, Optional
# pyrefly: ignore [missing-import]
from pydantic import BaseModel
from database import get_db, engine
from .auth import require_role, get_current_user
import json
import models
import schemas
import datetime
import pandas as pd
import tempfile
import os
import re

router = APIRouter(prefix="/balance", tags=["balance"])


# ====================================================================
# SCHEMAS
# ====================================================================

class EgresoCreate(BaseModel):
    descripcion: str
    categoria: str          # "operacional", "proyecto", "nomina", "otro"
    subcategoria: Optional[str] = None   # VIATICOS, CONSTRUCCION, COMPRAS…
    monto: float
    fecha: str              # YYYY-MM-DD
    mes: str                # "2026-04"
    metodo_pago: Optional[str] = "Efectivo"
    notas: Optional[str] = None

class EgresoUpdate(BaseModel):
    descripcion: Optional[str] = None
    categoria: Optional[str] = None
    subcategoria: Optional[str] = None
    monto: Optional[float] = None
    fecha: Optional[str] = None
    mes: Optional[str] = None
    metodo_pago: Optional[str] = None
    notas: Optional[str] = None

class ProyectoCreate(BaseModel):
    nombre: str
    descripcion: Optional[str] = None
    monto_total: float
    monto_invertido: float = 0.0
    estado: str = "En progreso"
    fecha_inicio: str
    fecha_fin: Optional[str] = None
    ganancia: Optional[float] = 0.0
    banco_ganancia: Optional[str] = "Pichincha"

class ProyectoUpdate(BaseModel):
    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    monto_total: Optional[float] = None
    monto_invertido: Optional[float] = None
    estado: Optional[str] = None
    fecha_inicio: Optional[str] = None
    fecha_fin: Optional[str] = None
    ganancia: Optional[float] = None
    banco_ganancia: Optional[str] = None

class ProyectoPagoCreate(BaseModel):
    item: int = 1
    descripcion: str
    fecha: Optional[str] = None
    tipo_pago: Optional[str] = "Pichincha"
    valor: float

class ProyectoPagoUpdate(BaseModel):
    item: Optional[int] = None
    descripcion: Optional[str] = None
    fecha: Optional[str] = None
    tipo_pago: Optional[str] = None
    valor: Optional[float] = None

class GastoProyectoCreate(BaseModel):
    subcategoria: str         # VIATICOS, CONSTRUCCION, COMPRAS, HERRAJERIA…
    item: int = 1
    descripcion: str
    fecha: Optional[str] = None
    tipo_pago: Optional[str] = "Pichincha"
    valor: float
    pendiente: bool = False

class GastoProyectoUpdate(BaseModel):
    subcategoria: Optional[str] = None
    item: Optional[int] = None
    descripcion: Optional[str] = None
    fecha: Optional[str] = None
    tipo_pago: Optional[str] = None
    valor: Optional[float] = None
    pendiente: Optional[bool] = None

class ColchonCreate(BaseModel):
    descripcion: str
    monto: float
    fecha: str

class ColchonUpdate(BaseModel):
    descripcion: Optional[str] = None
    monto: Optional[float] = None
    fecha: Optional[str] = None

class ConsolidarMesRequest(BaseModel):
    mes: str
    forzar: Optional[bool] = False

class GastoFijoCreate(BaseModel):
    descripcion: str
    monto: float
    categoria: str = "operacional"   # operacional, nomina, otro
    metodo_pago: Optional[str] = "Efectivo"
    activo: bool = True
    notas: Optional[str] = None

class GastoFijoUpdate(BaseModel):
    descripcion: Optional[str] = None
    monto: Optional[float] = None
    categoria: Optional[str] = None
    metodo_pago: Optional[str] = None
    activo: Optional[bool] = None
    notas: Optional[str] = None


# ====================================================================
# EGRESOS CRUD
# ====================================================================

@router.get("/egresos")
def listar_egresos(mes: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(models.Egreso)
    if mes:
        q = q.filter(models.Egreso.mes == mes)
    return q.order_by(models.Egreso.fecha.desc()).all()

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


# ====================================================================
# PROYECTOS CRUD
# ====================================================================

@router.get("/proyectos")
def listar_proyectos(db: Session = Depends(get_db)):
    return db.query(models.Proyecto).order_by(models.Proyecto.fecha_inicio.desc()).all()

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
    # Cascade delete children
    db.query(models.ProyectoPago).filter(models.ProyectoPago.proyecto_id == id).delete()
    db.query(models.GastoProyecto).filter(models.GastoProyecto.proyecto_id == id).delete()
    db.delete(proyecto)
    db.commit()
    return {"message": "Proyecto eliminado"}


# ====================================================================
# PROYECTO PAGOS (Cuotas / Aportes)
# ====================================================================

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


# ====================================================================
# GASTOS PROYECTO (Nóminas internas por subcategoría)
# ====================================================================

@router.get("/proyectos/{proyecto_id}/gastos")
def listar_gastos_proyecto(proyecto_id: int, db: Session = Depends(get_db)):
    gastos = db.query(models.GastoProyecto)\
        .filter(models.GastoProyecto.proyecto_id == proyecto_id)\
        .order_by(models.GastoProyecto.subcategoria, models.GastoProyecto.item).all()

    # Agrupar por subcategoría
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


# ====================================================================
# COLCHON CRUD
# ====================================================================

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
        import calendar
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


# ====================================================================
# GASTOS FIJOS CRUD
# ====================================================================

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
    return obj

@router.patch("/gastos-fijos/{id}", dependencies=[Depends(require_role(["administrador"]))])
def actualizar_gasto_fijo(id: int, data: GastoFijoUpdate, db: Session = Depends(get_db)):
    obj = db.query(models.GastoFijo).filter(models.GastoFijo.id == id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Gasto fijo no encontrado")
    for k, v in data.dict(exclude_none=True).items():
        setattr(obj, k, v)
    db.commit()
    return {"message": "Gasto fijo actualizado"}

@router.delete("/gastos-fijos/{id}", dependencies=[Depends(require_role(["administrador"]))])
def eliminar_gasto_fijo(id: int, db: Session = Depends(get_db)):
    obj = db.query(models.GastoFijo).filter(models.GastoFijo.id == id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Gasto fijo no encontrado")
    db.delete(obj)
    db.commit()
    return {"message": "Gasto fijo eliminado"}


# ====================================================================
# REPORTE MENSUAL
# ====================================================================

@router.get("/reporte-mensual")
def reporte_mensual(mes: str, db: Session = Depends(get_db)):
    try:
        year, month = map(int, mes.split("-"))
        import calendar
        _, last_day = calendar.monthrange(year, month)
        start_date = datetime.datetime(year, month, 1, 0, 0, 0)
        end_date = datetime.datetime(year, month, last_day, 23, 59, 59)
        pagos_mes = db.query(models.Pago).filter(
            models.Pago.fecha_pago >= start_date,
            models.Pago.fecha_pago <= end_date,
            models.Pago.anulado == False,
            models.Pago.estado == "Completado"
        ).all()
    except Exception as e:
        pagos = db.query(models.Pago).filter(
            models.Pago.anulado == False,
            models.Pago.estado == "Completado"
        ).all()
        pagos_mes = [p for p in pagos if str(p.fecha_pago)[:7] == mes]

    internet_ef = internet_pich = internet_jep = 0.0
    plus_ef = plus_pich = plus_jep = 0.0
    adicional_ef = adicional_pich = adicional_jep = 0.0
    adicional_total = 0.0

    for p in pagos_mes:
        metodo = (p.metodo_pago or "").upper()
        m_internet = float(p.monto_internet or 0)
        m_plus    = float(p.monto_plus or 0)
        m_adic    = float(p.monto_adicional or 0)

        # Si por alguna razón es un pago antiguo donde no se separaron los componentes pero hay un monto
        if m_internet == 0 and m_plus == 0 and m_adic == 0 and float(p.monto or 0) > 0:
            m_internet = float(p.monto or 0)

        adicional_total += m_adic

        if "JEP" in metodo or "GUAYAQUIL" in metodo:
            internet_jep += m_internet
            plus_jep += m_plus
            adicional_jep += m_adic
        elif "PICHINCHA" in metodo:
            internet_pich += m_internet
            plus_pich += m_plus
            adicional_pich += m_adic
        else:
            internet_ef += m_internet
            plus_ef += m_plus
            adicional_ef += m_adic

    total_internet = internet_ef + internet_pich + internet_jep
    total_plus     = plus_ef + plus_pich + plus_jep

    extras = db.query(models.ClienteExtra).all()
    month_key = {
        "01":"enero","02":"febrero","03":"marzo","04":"abril",
        "05":"mayo","06":"junio","07":"julio","08":"agosto",
        "09":"septiembre","10":"octubre","11":"noviembre","12":"diciembre"
    }.get(mes.split("-")[1], "")

    extras_ef = extras_pich = extras_jep = 0.0
    if month_key:
        for e in extras:
            pago  = float(getattr(e, f"{month_key}_pago", 0) or 0)
            banco = (getattr(e, f"{month_key}_banco", "") or "").upper()
            if pago > 0:
                if "PICHINCHA" in banco: extras_pich += pago
                elif "JEP" in banco:    extras_jep += pago
                else:                   extras_ef  += pago

    total_extras   = extras_ef + extras_pich + extras_jep

    # Separación contable: Recuento Normal (Operacional) excluye IPTV Plus y Clientes Extras
    total_ingresos = round(total_internet + adicional_total, 2)

    egresos_mes = db.query(models.Egreso).filter(models.Egreso.mes == mes).all()
    egresos_por_cat = {}
    total_egresos_global = 0.0

    egresos_op_ef = egresos_op_pich = egresos_op_jep = 0.0
    egresos_iptv_ef = egresos_iptv_pich = egresos_iptv_jep = 0.0
    egresos_pr_ef = egresos_pr_pich = egresos_pr_jep = 0.0
    total_egresos_op = 0.0
    total_egresos_iptv = 0.0
    total_egresos_pr = 0.0

    for eg in egresos_mes:
        m_val = float(eg.monto or 0)
        total_egresos_global += m_val
        egresos_por_cat.setdefault(eg.categoria, 0.0)
        egresos_por_cat[eg.categoria] += m_val

        metodo = (eg.metodo_pago or "").upper().strip()
        if "IPTV" in metodo:
            total_egresos_iptv += m_val
            if "PICHINCHA" in metodo:
                egresos_iptv_pich += m_val
            elif "JEP" in metodo or "GUAYAQUIL" in metodo:
                egresos_iptv_jep += m_val
            else:
                egresos_iptv_ef += m_val
        elif "PR" in metodo or "PROYECTO" in metodo:
            total_egresos_pr += m_val
            if "PICHINCHA" in metodo:
                egresos_pr_pich += m_val
            elif "JEP" in metodo or "GUAYAQUIL" in metodo:
                egresos_pr_jep += m_val
            else:
                egresos_pr_ef += m_val
        else:
            total_egresos_op += m_val
            if "PICHINCHA" in metodo:
                egresos_op_pich += m_val
            elif "JEP" in metodo or "GUAYAQUIL" in metodo:
                egresos_op_jep += m_val
            else:
                egresos_op_ef += m_val

    # Gastos fijos activos: se suman siempre en cada mes (Operacionales)
    gastos_fijos = db.query(models.GastoFijo).filter(models.GastoFijo.activo == True).all()
    total_gastos_fijos = 0.0
    gastos_fijos_lista = []
    for gf in gastos_fijos:
        monto_gf = float(gf.monto or 0)
        total_gastos_fijos += monto_gf
        total_egresos_global += monto_gf
        total_egresos_op += monto_gf
        egresos_por_cat[gf.categoria] = egresos_por_cat.get(gf.categoria, 0.0) + monto_gf
        gastos_fijos_lista.append({
            "id": gf.id, "descripcion": gf.descripcion, "monto": monto_gf,
            "categoria": gf.categoria, "metodo_pago": gf.metodo_pago, "notas": gf.notas
        })
        metodo_gf = (gf.metodo_pago or "").upper().strip()
        if "PICHINCHA" in metodo_gf:
            egresos_op_pich += monto_gf
        elif "JEP" in metodo_gf or "GUAYAQUIL" in metodo_gf:
            egresos_op_jep += monto_gf
        else:
            egresos_op_ef += monto_gf

    proyectos = db.query(models.Proyecto).all()
    proyectos_activos = [p for p in proyectos if (p.fecha_inicio or "")[:7] <= mes and (not p.fecha_fin or (p.fecha_fin or "")[:7] >= mes)]
    total_proyectos = sum(float(p.monto_invertido or 0) for p in proyectos_activos)

    # Colchon total (histórico)
    colchones = db.query(models.Colchon).all()
    total_colchon = sum(float(c.monto or 0) for c in colchones)

    # Balance Neto Operacional (Recuento Normal)
    balance_neto = round(total_ingresos - total_egresos_op, 2)

    # Consolidado de Bancos Operacionales (exclusivo para Internet y Adicional Normal)
    bancos_resumen = {
        "efectivo": round(internet_ef + adicional_ef, 2),
        "pichincha": round(internet_pich + adicional_pich, 2),
        "jep": round(internet_jep + adicional_jep, 2),
        "otros": 0.0
    }

    # Consolidado PLATAFORMA (IPTV Plus + Clientes Extras)
    total_ingresos_iptv = round(total_plus + total_extras, 2)
    ingresos_iptv_ef = round(plus_ef + extras_ef, 2)
    ingresos_iptv_pich = round(plus_pich + extras_pich, 2)
    ingresos_iptv_jep = round(plus_jep + extras_jep, 2)

    egresos_iptv_ef = round(egresos_iptv_ef, 2)
    egresos_iptv_pich = round(egresos_iptv_pich, 2)
    egresos_iptv_jep = round(egresos_iptv_jep, 2)
    total_egresos_iptv = round(total_egresos_iptv, 2)

    balance_neto_iptv = round(total_ingresos_iptv - total_egresos_iptv, 2)
    iptv_resumen = {
        "ingresos": {
            "total": total_ingresos_iptv,
            "efectivo": ingresos_iptv_ef,
            "pichincha": ingresos_iptv_pich,
            "jep": ingresos_iptv_jep
        },
        "egresos": {
            "total": total_egresos_iptv,
            "efectivo": egresos_iptv_ef,
            "pichincha": egresos_iptv_pich,
            "jep": egresos_iptv_jep
        },
        "balance_neto": {
            "total": balance_neto_iptv,
            "efectivo": round(ingresos_iptv_ef - egresos_iptv_ef, 2),
            "pichincha": round(ingresos_iptv_pich - egresos_iptv_pich, 2),
            "jep": round(ingresos_iptv_jep - egresos_iptv_jep, 2)
        }
    }

    # Proyectos: Ingresos vs Gastos / Inversión por mes
    proy_ganancia_ef = proy_ganancia_pich = proy_ganancia_jep = 0.0

    # 1. Pagos/cuotas de proyectos registrados en este mes específico
    pagos_proy_mes = db.query(models.ProyectoPago).filter(
        models.ProyectoPago.fecha.like(f"{mes}%")
    ).all()
    for pago in pagos_proy_mes:
        p_val = float(pago.valor or 0)
        tp = (pago.tipo_pago or 'PICHINCHA').upper().strip()
        if "JEP" in tp or "GUAYAQUIL" in tp:
            proy_ganancia_jep += p_val
        elif "EFECTIVO" in tp:
            proy_ganancia_ef += p_val
        else:
            proy_ganancia_pich += p_val

    # 2. Proyectos cuya fecha de inicio corresponde estrictamente a este mes
    proyectos_mes_inicio = [p for p in proyectos if (p.fecha_inicio or "")[:7] == mes]
    for p in proyectos_mes_inicio:
        g_val = float(getattr(p, 'ganancia', 0) or 0)
        if g_val > 0:
            b_g = (getattr(p, 'banco_ganancia', '') or 'PICHINCHA').upper().strip()
            if "JEP" in b_g or "GUAYAQUIL" in b_g:
                proy_ganancia_jep += g_val
            elif "EFECTIVO" in b_g:
                proy_ganancia_ef += g_val
            else:
                proy_ganancia_pich += g_val

    total_ganancia_proyectos = round(proy_ganancia_ef + proy_ganancia_pich + proy_ganancia_jep, 2)

    # 3. Gastos de proyectos para este mes específico
    gastos_pr_ef = round(egresos_pr_ef, 2)
    gastos_pr_pich = round(egresos_pr_pich, 2)
    gastos_pr_jep = round(egresos_pr_jep, 2)

    gastos_proy_mes = db.query(models.GastoProyecto).filter(
        models.GastoProyecto.fecha.like(f"{mes}%"),
        models.GastoProyecto.pendiente == False
    ).all()
    for gp in gastos_proy_mes:
        gp_val = float(gp.valor or 0)
        tp = (gp.tipo_pago or 'PICHINCHA').upper().strip()
        if "JEP" in tp or "GUAYAQUIL" in tp:
            gastos_pr_jep += gp_val
        elif "EFECTIVO" in tp:
            gastos_pr_ef += gp_val
        else:
            gastos_pr_pich += gp_val

    for p in proyectos_mes_inicio:
        inv_val = float(p.monto_invertido or 0)
        if inv_val > 0:
            gastos_pr_pich += inv_val

    gastos_pr_ef = round(gastos_pr_ef, 2)
    gastos_pr_pich = round(gastos_pr_pich, 2)
    gastos_pr_jep = round(gastos_pr_jep, 2)
    total_gastos_proyectos = round(gastos_pr_ef + gastos_pr_pich + gastos_pr_jep, 2)
    balance_neto_proyectos = round(total_ganancia_proyectos - total_gastos_proyectos, 2)

    proyectos_resumen = {
        "ingresos": {
            "total": total_ganancia_proyectos,
            "efectivo": proy_ganancia_ef,
            "pichincha": proy_ganancia_pich,
            "jep": proy_ganancia_jep
        },
        "egresos": {
            "total": total_gastos_proyectos,
            "efectivo": gastos_pr_ef,
            "pichincha": gastos_pr_pich,
            "jep": gastos_pr_jep
        },
        "balance_neto": {
            "total": balance_neto_proyectos,
            "efectivo": round(proy_ganancia_ef - gastos_pr_ef, 2),
            "pichincha": round(proy_ganancia_pich - gastos_pr_pich, 2),
            "jep": round(proy_ganancia_jep - gastos_pr_jep, 2)
        }
    }

    # Cartera pendiente de clientes (Total Pendiente Morosos - Clientes Activos)
    clientes_db = db.query(models.Cliente).all()
    total_morosos_val = 0.0
    cant_morosos = 0
    for c in clientes_db:
        if getattr(c, 'cortesia_total', False):
            continue
        est = str(getattr(c, 'estado', '') or '').strip().upper()
        est = est.replace("Í", "I").replace("Ó", "O").replace("Á", "A").replace("É", "E").replace("Ú", "U")
        if est not in ["ACTIVO", "ACTIVOS"]:
            continue
        s_val = float(c.saldo or 0)
        p_val = 0.0
        try:
            p_val = float(str(c.plus or 0).replace("$", "").replace(",", ".").strip())
        except:
            pass
        a_val = 0.0
        try:
            a_val = float(str(c.adicional or 0).replace("$", "").replace(",", ".").strip())
        except:
            pass
        tot_c = float(c.total_pago or 0)
        deuda_c = tot_c if tot_c > 0 else max(0.0, s_val + p_val + a_val)
        if deuda_c > 0:
            total_morosos_val += deuda_c
            cant_morosos += 1

    total_morosos_val = round(total_morosos_val, 2)

    return {
        "mes": mes,
        "total_pendiente_morosos": total_morosos_val,
        "cantidad_morosos": cant_morosos,
        "ingresos": {
            "internet": {"total": total_internet, "efectivo": internet_ef, "pichincha": internet_pich, "jep": internet_jep},
            "iptv":     {"total": total_plus,     "efectivo": plus_ef,    "pichincha": plus_pich, "jep": plus_jep},
            "adicional": adicional_total,
            "extras":   {"total": total_extras,   "efectivo": extras_ef,  "pichincha": extras_pich, "jep": extras_jep},
            "plataforma": {"total": total_ingresos_iptv, "adicional": adicional_total, "extras": total_extras},
            "bancos": bancos_resumen,
            "total": total_ingresos,
        },
        "egresos": {
            "detalle": egresos_por_cat,
            "lista": [
                {"id": e.id, "descripcion": e.descripcion, "categoria": e.categoria,
                 "subcategoria": e.subcategoria, "monto": float(e.monto),
                 "fecha": e.fecha, "metodo_pago": e.metodo_pago, "notas": e.notas}
                for e in egresos_mes
            ],
            "gastos_fijos": gastos_fijos_lista,
            "total_gastos_fijos": total_gastos_fijos,
            "total": total_egresos_op,
            "total_global": total_egresos_global,
            "bancos": {
                "efectivo": round(egresos_op_ef, 2),
                "pichincha": round(egresos_op_pich, 2),
                "jep": round(egresos_op_jep, 2)
            }
        },
        "proyectos": {
            "lista": [
                {"id": p.id, "nombre": p.nombre, "descripcion": p.descripcion,
                 "monto_total": float(p.monto_total), "monto_invertido": float(p.monto_invertido or 0),
                 "ganancia": float(getattr(p, 'ganancia', 0) or 0),
                 "banco_ganancia": getattr(p, 'banco_ganancia', 'Pichincha') or 'Pichincha',
                 "estado": p.estado, "fecha_inicio": p.fecha_inicio, "fecha_fin": p.fecha_fin}
                for p in proyectos_activos
            ],
            "total": total_proyectos,
            "resumen": proyectos_resumen
        },
        "iptv_resumen": iptv_resumen,
        "proyectos_resumen": proyectos_resumen,
        "colchon": {
            "lista": [{"id": c.id, "descripcion": c.descripcion, "monto": float(c.monto), "fecha": c.fecha} for c in colchones],
            "total": total_colchon
        },
        "balance_neto": balance_neto,
    }


# ====================================================================
# REPORTE EXCLUSIVO DE PLATAFORMA (IPTV / EXTRAS)
# ====================================================================

@router.get("/reporte-plataforma")
def reporte_plataforma(mes: str, db: Session = Depends(get_db)):
    try:
        year, month = map(int, mes.split("-"))
        import calendar
        _, last_day = calendar.monthrange(year, month)
        start_date = datetime.datetime(year, month, 1, 0, 0, 0)
        end_date = datetime.datetime(year, month, last_day, 23, 59, 59)
        pagos_mes = db.query(models.Pago).filter(
            models.Pago.fecha_pago >= start_date,
            models.Pago.fecha_pago <= end_date,
            models.Pago.anulado == False,
            models.Pago.estado == "Completado"
        ).all()
    except Exception:
        pagos = db.query(models.Pago).filter(
            models.Pago.anulado == False,
            models.Pago.estado == "Completado"
        ).all()
        pagos_mes = [p for p in pagos if str(p.fecha_pago)[:7] == mes]

    detalle_transacciones = []
    iptv_plus_ef = iptv_plus_pich = iptv_plus_jep = iptv_plus_otros = 0.0

    for p in pagos_mes:
        m_plus = float(p.monto_plus or 0)
        if m_plus > 0:
            banco = (getattr(p, 'banco_plus', None) or getattr(p, 'metodo_pago', None) or "EFECTIVO").upper()
            if "PICHINCHA" in banco:
                iptv_plus_pich += m_plus
            elif "JEP" in banco or "GUAYAQUIL" in banco:
                iptv_plus_jep += m_plus
            elif "EFECTIVO" in banco:
                iptv_plus_ef += m_plus
            else:
                iptv_plus_otros += m_plus

            cliente_nombre = f"Cliente #{p.cliente_id}"
            try:
                if p.cliente and getattr(p.cliente, 'nombre', None):
                    cliente_nombre = p.cliente.nombre
            except Exception:
                pass

            fecha_str = mes + "-01"
            if p.fecha_pago:
                if hasattr(p.fecha_pago, 'strftime'):
                    fecha_str = p.fecha_pago.strftime("%Y-%m-%d")
                else:
                    fecha_str = str(p.fecha_pago)[:10]

            detalle_transacciones.append({
                "id": f"pago_{p.id}",
                "cliente": cliente_nombre,
                "tipo": "IPTV Plus (Pantallas Extras Cliente)",
                "banco": banco,
                "fecha": fecha_str,
                "monto": round(m_plus, 2)
            })

    total_iptv_plus = round(iptv_plus_ef + iptv_plus_pich + iptv_plus_jep + iptv_plus_otros, 2)

    extras = db.query(models.ClienteExtra).all()
    parts = mes.split("-")
    month_str = parts[1] if len(parts) > 1 else "01"
    month_key = {
        "01":"enero","02":"febrero","03":"marzo","04":"abril",
        "05":"mayo","06":"junio","07":"julio","08":"agosto",
        "09":"septiembre","10":"octubre","11":"noviembre","12":"diciembre"
    }.get(month_str, "enero")

    extras_ef = extras_pich = extras_jep = extras_otros = 0.0
    if month_key:
        for e in extras:
            pago = float(getattr(e, f"{month_key}_pago", 0) or 0)
            banco = (getattr(e, f"{month_key}_banco", "") or "EFECTIVO").upper()
            if pago > 0:
                if "PICHINCHA" in banco:
                    extras_pich += pago
                elif "JEP" in banco or "GUAYAQUIL" in banco:
                    extras_jep += pago
                elif "EFECTIVO" in banco:
                    extras_ef += pago
                else:
                    extras_otros += pago

                nombre_extra = getattr(e, 'nombre_cliente', None) or getattr(e, 'nombre', None) or f"Cliente Extra #{e.id}"
                detalle_transacciones.append({
                    "id": f"extra_{e.id}",
                    "cliente": nombre_extra,
                    "tipo": "Cliente Extra (Solo Plataforma)",
                    "banco": banco,
                    "fecha": mes + "-01",
                    "monto": round(pago, 2)
                })

    total_extras = round(extras_ef + extras_pich + extras_jep + extras_otros, 2)
    sumatoria_total = round(total_iptv_plus + total_extras, 2)

    bancos_plataforma = {
        "efectivo": round(iptv_plus_ef + extras_ef, 2),
        "pichincha": round(iptv_plus_pich + extras_pich, 2),
        "jep": round(iptv_plus_jep + extras_jep, 2),
        "otros": round(iptv_plus_otros + extras_otros, 2),
        "total": sumatoria_total
    }

    origen_plataforma = {
        "iptv_plus": total_iptv_plus,
        "clientes_extras": total_extras,
        "total": sumatoria_total
    }

    return {
        "mes": mes,
        "sumatoria_total": sumatoria_total,
        "desglose_origen": origen_plataforma,
        "desglose_bancos": bancos_plataforma,
        "transacciones": detalle_transacciones
    }


# ====================================================================
# REPORTE ANUAL
# ====================================================================

@router.get("/reporte-anual")
def reporte_anual(anio: int, db: Session = Depends(get_db)):
    meses_labels = ["Enero","Febrero","Marzo","Abril","Mayo","Junio",
                    "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]
    month_name_map = {
        "01":"enero","02":"febrero","03":"marzo","04":"abril",
        "05":"mayo","06":"junio","07":"julio","08":"agosto",
        "09":"septiembre","10":"octubre","11":"noviembre","12":"diciembre"
    }
    start_date = datetime.datetime(anio, 1, 1, 0, 0, 0)
    end_date = datetime.datetime(anio, 12, 31, 23, 59, 59)
    pagos = db.query(models.Pago).filter(
        models.Pago.fecha_pago >= start_date,
        models.Pago.fecha_pago <= end_date,
        models.Pago.anulado == False,
        models.Pago.estado == "Completado"
    ).all()
    
    extras_all = db.query(models.ClienteExtra).all()
    egresos_all = db.query(models.Egreso).filter(models.Egreso.mes.like(f"{anio}-%")).all()
    proyectos_all = db.query(models.Proyecto).all()

    data_mensual = []
    total_anual_ingresos = total_anual_egresos = total_anual_balance = 0.0

    for i in range(1, 13):
        mes_str   = f"{anio}-{i:02d}"
        month_key = month_name_map[f"{i:02d}"]
        pagos_mes = [p for p in pagos if str(p.fecha_pago)[:7] == mes_str]
        t_internet = t_plus = t_adic = 0.0
        for p in pagos_mes:
            t_internet += float(p.monto_internet or 0)
            t_plus     += float(p.monto_plus or 0)
            t_adic     += float(p.monto_adicional or 0)
        t_extras  = sum(float(getattr(e, f"{month_key}_pago", 0) or 0) for e in extras_all)
        t_ingresos = t_internet + t_plus + t_adic + t_extras
        t_egresos  = sum(float(eg.monto) for eg in egresos_all if eg.mes == mes_str)
        balance    = t_ingresos - t_egresos
        data_mensual.append({
            "mes": mes_str, "label": meses_labels[i-1],
            "ingresos": round(t_ingresos,2), "egresos": round(t_egresos,2),
            "balance": round(balance,2), "internet": round(t_internet,2),
            "iptv": round(t_plus,2), "adicional": round(t_adic,2), "extras": round(t_extras,2),
        })
        total_anual_ingresos += t_ingresos
        total_anual_egresos  += t_egresos
        total_anual_balance  += balance

    return {
        "anio": anio,
        "meses": data_mensual,
        "totales": {"ingresos": round(total_anual_ingresos,2), "egresos": round(total_anual_egresos,2), "balance": round(total_anual_balance,2)},
        "proyectos": [
            {"id": p.id, "nombre": p.nombre, "monto_total": float(p.monto_total),
             "monto_invertido": float(p.monto_invertido or 0), "estado": p.estado,
             "fecha_inicio": p.fecha_inicio, "fecha_fin": p.fecha_fin}
            for p in proyectos_all
        ],
    }

@router.get("/reporte-anual-excel")
def exportar_reporte_anual_excel(anio: int, db: Session = Depends(get_db)):
    data = reporte_anual(anio, db)
    totales = data["totales"]
    meses = data["meses"]
    proyectos = data["proyectos"]

    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Reporte Anual"
    ws.views.sheetView[0].showGridLines = True

    color_primary = "1E3A8A"
    color_header_fill = PatternFill(start_color=color_primary, end_color=color_primary, fill_type="solid")
    font_header = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    font_title = Font(name="Calibri", size=16, bold=True, color=color_primary)
    font_subtitle = Font(name="Calibri", size=11, italic=True, color="4B5563")
    font_section = Font(name="Calibri", size=13, bold=True, color=color_primary)
    font_bold = Font(name="Calibri", size=11, bold=True)
    font_regular = Font(name="Calibri", size=11)

    align_center = Alignment(horizontal="center", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center")
    align_right = Alignment(horizontal="right", vertical="center")

    thin = Side(border_style="thin", color="D1D5DB")
    double_side = Side(border_style="double", color="1E3A8A")
    thin_border = Border(left=thin, right=thin, top=thin, bottom=thin)
    total_border = Border(top=thin, bottom=double_side, left=thin, right=thin)
    fill_zebra = PatternFill(start_color="F9FAFB", end_color="F9FAFB", fill_type="solid")
    fill_total = PatternFill(start_color="EEF2FF", end_color="EEF2FF", fill_type="solid")

    # Banner de Encabezado
    ws["A1"] = "OPSATEL S.A.S."
    ws["A1"].font = font_title
    ws["A2"] = f"Reporte Financiero Anual — Período: {anio}"
    ws["A2"].font = font_subtitle
    ws["A3"] = "RUC: 0993245678001 | Reporte Oficial Consolidado Anual"
    ws["A3"].font = Font(name="Calibri", size=9, color="6B7280", italic=True)

    # ── SECCIÓN 1: RESUMEN ANUAL ──
    ws.cell(row=5, column=1, value="RESUMEN FINANCIERO ANUAL").font = font_section
    headers_resumen = ["CONCEPTO", "MONTO TOTAL"]
    for col_idx, text in enumerate(headers_resumen, 1):
        c = ws.cell(row=6, column=col_idx, value=text)
        c.fill = color_header_fill
        c.font = font_header
        c.alignment = align_center
        c.border = thin_border
    ws.row_dimensions[6].height = 24

    resumen_rows = [
        ("Ingresos Totales", totales["ingresos"]),
        ("Egresos Totales", totales["egresos"]),
        ("Balance Neto Anual", totales["balance"])
    ]

    for idx, (concept, val) in enumerate(resumen_rows, start=7):
        ws.row_dimensions[idx].height = 20
        c_concept = ws.cell(row=idx, column=1, value=concept)
        c_val = ws.cell(row=idx, column=2, value=val)
        
        is_last = (idx == 9)
        c_concept.font = font_bold if is_last else font_regular
        c_val.font = font_bold if is_last else font_regular
        
        c_concept.border = total_border if is_last else thin_border
        c_val.border = total_border if is_last else thin_border
        
        if is_last:
            c_concept.fill = fill_total
            c_val.fill = fill_total
            
        c_concept.alignment = align_left
        c_val.alignment = align_right
        c_val.number_format = '$#,##0.00'

    # ── SECCIÓN 2: EVOLUCIÓN MENSUAL ──
    start_row_mensual = 12
    ws.cell(row=start_row_mensual, column=1, value="EVOLUCIÓN MENSUAL (DETALLE POR MES)").font = font_section
    
    headers_mensual = ["MES", "INTERNET", "IPTV", "EXTRAS / ADICIONALES", "TOTAL INGRESOS", "EGRESOS", "BALANCE NETO"]
    for col_idx, text in enumerate(headers_mensual, 1):
        c = ws.cell(row=start_row_mensual + 1, column=col_idx, value=text)
        c.fill = color_header_fill
        c.font = font_header
        c.alignment = align_center
        c.border = thin_border
    ws.row_dimensions[start_row_mensual + 1].height = 26

    current_row = start_row_mensual + 2
    for r_idx, m in enumerate(meses):
        ws.row_dimensions[current_row].height = 20
        is_zebra = (r_idx % 2 == 1)
        
        row_vals = [
            (m["label"], align_left, "@"),
            (m["internet"], align_right, '$#,##0.00'),
            (m["iptv"], align_right, '$#,##0.00'),
            (m["extras"] + m["adicional"], align_right, '$#,##0.00'),
            (m["ingresos"], align_right, '$#,##0.00'),
            (m["egresos"], align_right, '$#,##0.00'),
            (m["balance"], align_right, '$#,##0.00')
        ]
        
        for c_idx, (val, align, num_fmt) in enumerate(row_vals, 1):
            cell = ws.cell(row=current_row, column=c_idx, value=val)
            cell.font = font_regular
            cell.alignment = align
            cell.border = thin_border
            cell.number_format = num_fmt
            if is_zebra:
                cell.fill = fill_zebra
                
        current_row += 1

    # Fila TOTAL ANUAL
    ws.row_dimensions[current_row].height = 22
    t_row_vals = [
        (f"TOTAL ANUAL {anio}", align_left, "@"),
        (sum(m["internet"] for m in meses), align_right, '$#,##0.00'),
        (sum(m["iptv"] for m in meses), align_right, '$#,##0.00'),
        (sum(m["extras"] + m["adicional"] for m in meses), align_right, '$#,##0.00'),
        (totales["ingresos"], align_right, '$#,##0.00'),
        (totales["egresos"], align_right, '$#,##0.00'),
        (totales["balance"], align_right, '$#,##0.00')
    ]
    for c_idx, (val, align, num_fmt) in enumerate(t_row_vals, 1):
        cell = ws.cell(row=current_row, column=c_idx, value=val)
        cell.font = font_bold
        cell.alignment = align
        cell.border = total_border
        cell.fill = fill_total
        cell.number_format = num_fmt

    # ── SECCIÓN 3: PROYECTOS Y OBRAS DEL AÑO ──
    if proyectos:
        current_row += 3
        ws.cell(row=current_row, column=1, value="PROYECTOS Y OBRAS DEL AÑO").font = font_section
        current_row += 1
        
        headers_proy = ["NOMBRE PROYECTO", "MONTO TOTAL", "MONTO INVERTIDO", "ESTADO"]
        for col_idx, text in enumerate(headers_proy, 1):
            c = ws.cell(row=current_row, column=col_idx, value=text)
            c.fill = color_header_fill
            c.font = font_header
            c.alignment = align_center
            c.border = thin_border
        ws.row_dimensions[current_row].height = 24
        current_row += 1
        
        for p_idx, p in enumerate(proyectos):
            ws.row_dimensions[current_row].height = 20
            is_zebra = (p_idx % 2 == 1)
            
            p_vals = [
                (p["nombre"], align_left, "@"),
                (p["monto_total"], align_right, '$#,##0.00'),
                (p["monto_invertido"], align_right, '$#,##0.00'),
                (p["estado"], align_center, "@")
            ]
            for c_idx, (val, align, num_fmt) in enumerate(p_vals, 1):
                cell = ws.cell(row=current_row, column=c_idx, value=val)
                cell.font = font_regular
                cell.alignment = align
                cell.border = thin_border
                cell.number_format = num_fmt
                if is_zebra:
                    cell.fill = fill_zebra
            current_row += 1

    # Auto-ajustar ancho de columnas
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col[3:]:
            val_str = str(cell.value or "")
            if cell.number_format == '$#,##0.00' and isinstance(cell.value, (int, float)):
                val_str = f"${cell.value:,.2f}"
            if len(val_str) > max_len:
                max_len = len(val_str)
        ws.column_dimensions[col_letter].width = max(max_len + 4, 15)

    temp_dir = tempfile.gettempdir()
    file_path = os.path.join(temp_dir, f"Balance_Anual_Opsatel_{anio}.xlsx")
    wb.save(file_path)

    return FileResponse(
        path=file_path,
        filename=f"Balance_Anual_Opsatel_{anio}.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# ====================================================================
# HISTORIAL DE PAGOS / DEUDAS DE CLIENTES
# ====================================================================

@router.get("/historial-clientes")
def historial_clientes(db: Session = Depends(get_db)):
    clientes = db.query(models.Cliente).all()
    planes = {p.nombre: float(p.precio) for p in db.query(models.PlanInternet).all()}
    
    def try_float(v):
        try:
            return float(str(v or 0).replace("$", "").replace(",", ".").strip())
        except:
            return 0.0

    res = []
    for c in clientes:
        # Se incluyen todos los clientes para mostrar el historial de pagos y deudas, 
        # sin importar si están suspendidos o activos.
            
        tarifa_base = 0.0
        if getattr(c, 'mantenimiento', False):
            tarifa_base = 10.00
        elif c.tercera_edad and c.precio_plan_especial is not None:
            tarifa_base = try_float(c.precio_plan_especial)
        elif c.plan in planes:
            tarifa_base = planes[c.plan]
            
        plus = try_float(c.plus)
        adicional = try_float(c.adicional)
        tarifa_mensual = tarifa_base + plus + adicional
        saldo = try_float(c.saldo)

        proporcional = tarifa_mensual
        if c.instalation_date:
            try:
                date_str = str(c.instalation_date).strip()[:10]
                dt_parts = [int(p) for p in date_str.split("-")]
                if len(dt_parts) == 3:
                    y, m, d = dt_parts
                    import calendar
                    _, total_days = calendar.monthrange(y, m)
                    active_days = (total_days - d) + 1
                    if total_days > 0 and 0 <= active_days <= total_days:
                        proporcional = round((tarifa_mensual / total_days) * active_days, 2)
            except Exception:
                proporcional = tarifa_mensual
        
        res.append({
            "id": c.id,
            "nombre": c.nombre,
            "nodo": c.nodo,
            "plan": c.plan,
            "tarifa_mensual": tarifa_mensual,
            "proporcional": proporcional,
            "saldo_total": saldo,
            "estado": c.estado,
            "instalation_date": c.instalation_date,
            "bank": c.bank
        })
    
    # Ordenar por los que más deben
    res.sort(key=lambda x: x["saldo_total"], reverse=True)
    return res

def normalizar_parroquia(parr: str) -> str:
    if not parr or not str(parr).strip():
        return "BANOS"
    p = str(parr).strip().upper()
    p = p.replace("Á", "A").replace("É", "E").replace("Í", "I").replace("Ó", "O").replace("Ú", "U")
    p = p.replace("Ñ", "N")
    if "BANO" in p:
        return "BANOS"
    if "SAYAUS" in p:
        return "SAYAUSI"
    if "YANUN" in p:
        return "YANUNCAY"
    if "JOAQUIN" in p:
        return "SAN JOAQUIN"
    if "VALLE" in p:
        return "EL VALLE"
    if "RICAURT" in p:
        return "RICAURTE"
    if "TARQUI" in p:
        return "TARQUI"
    return p if p else "BANOS"

def try_float_val(val, default=0.0):
    try:
        if val is None:
            return default
        s = str(val).replace("$", "").replace(",", ".").strip()
        return float(s) if s else default
    except Exception:
        return default

def try_int_val(val, default=0):
    try:
        if val is None:
            return default
        m = re.search(r'(\d+)', str(val))
        return int(m.group(1)) if m else default
    except Exception:
        return default

# Mapeo oficial ARCOTEL para los planes configurados en Configuraciones
MAP_COMERCIAL_TARIFAS = {
    "ESTANDAR": ("PERSONAL 100M 8:1", 100, 100),
    "100MB": ("PERSONAL 100M 8:1", 100, 100),
    "FAMILIAR": ("CONEXION ESTABLE 600M 8:1", 250, 250),
    "600MB": ("CONEXION ESTABLE 600M 8:1", 250, 250),
    "FAMILIAR +": ("FULL CONECTADO 650M 8:1", 300, 300),
    "FAMILIAR+": ("FULL CONECTADO 650M 8:1", 300, 300),
    "650MB": ("FULL CONECTADO 650M 8:1", 300, 300),
    "LAG CERO": ("LAG CERO 700M 8:1", 400, 400),
    "700MB": ("LAG CERO 700M 8:1", 400, 400),
    "GAMER PRO": ("GAMER PRO 800M 8:1", 800, 800),
    "800MB": ("GAMER PRO 800M 8:1", 800, 800),
}

CORP_OFICIALES_TARIFAS = [
    {"nombre": "CORP ESTABLE 850M 4:1", "precio": 55.20, "down": 850, "up": 850, "comp": "4:1", "tipo": "CORPORATIVO"},
    {"nombre": "CORP FULL 900M 4:1", "precio": 89.60, "down": 900, "up": 900, "comp": "4:1", "tipo": "CORPORATIVO"},
]

def generar_data_tarifas(planes, resumen_data, mes_nombre_upper: str, fecha_vigencia_val: str):
    data_tarifas = []
    nombres_agregados = set()

    # Iterar estrictamente sobre planes configurados en Configuraciones (models.PlanInternet)
    for p in planes:
        if not p.nombre:
            continue
        p_raw = p.nombre.strip()
        p_clean = p_raw.upper()
        if p_clean in nombres_agregados:
            continue
        nombres_agregados.add(p_clean)

        if p_clean in MAP_COMERCIAL_TARIFAS:
            nom_com, down_v, up_v = MAP_COMERCIAL_TARIFAS[p_clean]
        else:
            nom_com = p_raw.upper()
            if "8:1" not in nom_com and "4:1" not in nom_com:
                nom_com = f"{nom_com} {try_int_val(p.megas)}M 8:1"
            down_v = try_int_val(p.megas) or 100
            up_v = try_int_val(p.megas) or 100

        cant_cli = 0
        for r in resumen_data:
            r_plan = str(r.get("PLAN", "")).strip().upper()
            if r_plan == p_clean or (p_clean in r_plan and "TOTAL" not in r_plan and "SIN IVA" not in r_plan):
                cant_cli = int(r.get("CANTIDAD CLIENTES") or 0)
                break

        is_corp = ("CORP" in nom_com or "EMPRES" in nom_com)
        tipo_v = "CORPORATIVO" if is_corp else "RESIDENCIAL"
        comp_v = "4:1" if is_corp else "8:1"

        data_tarifas.append({
            "MES": mes_nombre_upper,
            "CIUDAD": "CUENCA",
            "NOMBRE COMERCIAL DEL PLAN TARIFARIO": nom_com,
            "FECHA DE VIGENCIA DEL PLAN TARIFARIO": fecha_vigencia_val,
            "CANTIDAD ABONADOS/CLIENTES": cant_cli,
            "TIPO (RESIDENCIAL, CORPORATIVO, CIBERCAFE)": tipo_v,
            "TARIFA MENSUAL [USD] (incluido impuestos)": float(p.precio or 0.0),
            "DOWNLINK [Mbps]": down_v,
            "UPLINK [Mbps]": up_v,
            "NIVEL DE COMPARTICIÓN [X:1]": comp_v,
            "TECNOLOGÍA (ADSL, SDSL, HFC, FTTH, WIMAX, WIFI, OTROS)": "FTTH",
            "OBSERVACIONES (Opcional)": ""
        })

    # Si no hubiera planes en BD por alguna razón, usar los estándar configurados
    if not data_tarifas:
        default_cfg = [
            ("ESTANDAR", 100, 17.25),
            ("FAMILIAR", 600, 20.54),
            ("FAMILIAR +", 650, 23.00),
            ("LAG CERO", 700, 25.00),
            ("GAMER PRO", 800, 32.20),
        ]
        for nom, meg, prec in default_cfg:
            nom_com, down_v, up_v = MAP_COMERCIAL_TARIFAS.get(nom, (f"{nom} {meg}M 8:1", meg, meg))
            cant_cli = 0
            for r in resumen_data:
                r_plan = str(r.get("PLAN", "")).strip().upper()
                if nom in r_plan and "TOTAL" not in r_plan and "SIN IVA" not in r_plan:
                    cant_cli = int(r.get("CANTIDAD CLIENTES") or 0)
                    break
            data_tarifas.append({
                "MES": mes_nombre_upper,
                "CIUDAD": "CUENCA",
                "NOMBRE COMERCIAL DEL PLAN TARIFARIO": nom_com,
                "FECHA DE VIGENCIA DEL PLAN TARIFARIO": fecha_vigencia_val,
                "CANTIDAD ABONADOS/CLIENTES": cant_cli,
                "TIPO (RESIDENCIAL, CORPORATIVO, CIBERCAFE)": "RESIDENCIAL",
                "TARIFA MENSUAL [USD] (incluido impuestos)": prec,
                "DOWNLINK [Mbps]": down_v,
                "UPLINK [Mbps]": up_v,
                "NIVEL DE COMPARTICIÓN [X:1]": "8:1",
                "TECNOLOGÍA (ADSL, SDSL, HFC, FTTH, WIMAX, WIFI, OTROS)": "FTTH",
                "OBSERVACIONES (Opcional)": ""
            })

    # Agregar los 2 planes Corporativos oficiales fijos
    for cp in CORP_OFICIALES_TARIFAS:
        if not any(cp["nombre"].upper() in str(x.get("NOMBRE COMERCIAL DEL PLAN TARIFARIO", "")).upper() for x in data_tarifas):
            cant_c = 0
            for r in resumen_data:
                r_plan = str(r.get("PLAN", "")).strip().upper()
                if cp["nombre"].split()[0] in r_plan:
                    cant_c = int(r.get("CANTIDAD CLIENTES") or 0)
                    break
            data_tarifas.append({
                "MES": mes_nombre_upper,
                "CIUDAD": "CUENCA",
                "NOMBRE COMERCIAL DEL PLAN TARIFARIO": cp["nombre"],
                "FECHA DE VIGENCIA DEL PLAN TARIFARIO": fecha_vigencia_val,
                "CANTIDAD ABONADOS/CLIENTES": cant_c,
                "TIPO (RESIDENCIAL, CORPORATIVO, CIBERCAFE)": cp["tipo"],
                "TARIFA MENSUAL [USD] (incluido impuestos)": cp["precio"],
                "DOWNLINK [Mbps]": cp["down"],
                "UPLINK [Mbps]": cp["up"],
                "NIVEL DE COMPARTICIÓN [X:1]": cp["comp"],
                "TECNOLOGÍA (ADSL, SDSL, HFC, FTTH, WIMAX, WIFI, OTROS)": "FTTH",
                "OBSERVACIONES (Opcional)": ""
            })

    return data_tarifas

def construir_datos_arcotel(mes: str, db: Session):
    parts = mes.split("-")
    clientes = db.query(models.Cliente).all()
    planes = db.query(models.PlanInternet).all()
    planes_precios = {p.nombre: try_float_val(p.precio) for p in planes if p.nombre}
    planes_megas = {}
    for p in planes:
        if p.nombre:
            planes_megas[p.nombre.strip().upper()] = try_int_val(p.megas)
    
    month_num = parts[1] if len(parts) == 2 else "01"
    month_name_en = {
        "01": "JANUARY", "02": "FEBRUARY", "03": "MARCH", "04": "APRIL",
        "05": "MAY", "06": "JUNE", "07": "JULY", "08": "AUGUST",
        "09": "SEPTEMBER", "10": "OCTOBER", "11": "NOVEMBER", "12": "DECEMBER"
    }.get(month_num, "MONTH")

    month_name_es = {
        "01": "Enero", "02": "Febrero", "03": "Marzo", "04": "Abril",
        "05": "Mayo", "06": "Junio", "07": "Julio", "08": "Agosto",
        "09": "Septiembre", "10": "Octubre", "11": "Noviembre", "12": "Diciembre"
    }.get(month_num, "Mes")
    mes_label = f"{month_name_es} {parts[0]}" if len(parts) == 2 else mes

    clientes_con_factura = []
    clientes_con_factura_ids = set()
    for c in clientes:
        fact_raw = str(c.facturas or "").strip().upper()
        cod_raw = str(c.cod or "").strip()
        is_cortesia = bool(getattr(c, 'cortesia_total', False))

        tiene_factura_normal = (fact_raw == "SI" and bool(cod_raw))
        es_cortesia_con_factura = is_cortesia and (fact_raw == "SI" or bool(cod_raw))

        if tiene_factura_normal or es_cortesia_con_factura:
            clientes_con_factura.append(c)
            clientes_con_factura_ids.add(c.id)

    # 1. Facturación Clientes
    data_clientes = []
    for c in clientes_con_factura:
        id_str = f"C{c.id:02d}" if c.id is not None else ""
        pago_mensual = try_float_val(c.pago_mensual)
        is_cortesia = bool(getattr(c, 'cortesia_total', False))
        confirmar = True if (pago_mensual > 0 or is_cortesia) else False

        plan_clean = str(c.plan or "").strip().upper()
        megas_num = planes_megas.get(plan_clean, 0)
        if megas_num == 0 and plan_clean:
            megas_num = try_int_val(plan_clean)

        plan_val = f"{megas_num}MB" if megas_num > 0 else ""
        cod_val = str(c.cod or "").strip() or id_str

        data_clientes.append({
            "ID": id_str,
            "RUC / CEDULA": str(c.cedula or "").strip(),
            "NAME": c.nombre or "",
            "DIRECTION": c.direccion or "",
            "CEL": str(c.celular or "").strip(),
            "PARISH": c.parroquia or "",
            "PLAN": plan_val,
            f"FACT {month_name_en}": "SI",
            "ESTADO": c.estado or "Pendiente",
            "CONFIRMAR": "SÍ" if confirmar else "NO",
            "FACTURAS": cod_val,
            "es_cortesia": is_cortesia,
            "pago_mensual": pago_mensual
        })
    data_clientes.sort(key=lambda x: (str(x.get("ESTADO") or ""), str(x.get("NAME") or "")))

    # 2. Reporte Usuarios (Acceso no conmutado - Líneas dedicadas)
    mes_nombre_upper = month_name_es.upper()
    data_alta_vel = []
    for c in clientes_con_factura:
        plan_clean = str(c.plan or "").strip().upper()
        megas_num = planes_megas.get(plan_clean, 0)
        if megas_num == 0 and plan_clean:
            megas_num = try_int_val(plan_clean)
        if megas_num <= 0:
            megas_num = 100
            
        kbps_val = int(megas_num * 1000)
        parroquia_val = normalizar_parroquia(c.parroquia) or "BANOS"
        
        plan_str = str(c.plan or "").upper()
        nom_str = str(c.nombre or "").upper()
        if "CORP" in plan_str or "EMPRES" in plan_str or "CORP" in nom_str:
            tipo_cli = "Corporativo"
        elif "CIBER" in plan_str or "CYBER" in plan_str:
            tipo_cli = "Cibercafé"
        else:
            tipo_cli = "Residencial"
            
        tel_val = str(c.celular or "").strip()
        if tel_val.endswith(".0"):
            tel_val = tel_val[:-2]

        data_alta_vel.append({
            "MES": mes_nombre_upper,
            "Provincia": "AZUAY",
            "Cantón": "CUENCA",
            "Parroquia": parroquia_val,
            "Nombre del Usuario": str(c.nombre or "").strip().upper(),
            "Dirección": str(c.direccion or "").strip().upper(),
            "Teléfono": tel_val,
            "Número estimado de usuarios por cuenta": 4,
            "Empresa proveedora del canal (Portador)": "NEDETEL",
            "Tipo de enlace: Cobre, Cable Coaxial, Fibra Óptica, Medio Inalámbrico": "Fibra Óptica",
            "Ancho de banda Up Link (Kbps)": kbps_val,
            "Ancho de banda Down Link (Kbps)": kbps_val,
            "Tipo de Cliente (Residencial, Corporativo, Cibercafé)": tipo_cli,
            "Nivel de Compartición": "8 : 1"
        })
    data_alta_vel.sort(key=lambda x: (str(x.get("Parroquia") or ""), str(x.get("Nombre del Usuario") or "")))

    # 3. Resumen por Plan
    pagos_todos = db.query(models.Pago).all()
    pagos_mes = [
        p for p in pagos_todos 
        if str(p.fecha_pago or "")[:7] == mes 
        and p.cliente_id in clientes_con_factura_ids 
        and not getattr(p, 'anulado', False)
    ]
    pago_por_cliente_metodo = {}
    for p in pagos_mes:
        if p.cliente_id:
            m_total = try_float_val(p.monto)
            m_parts = try_float_val(p.monto_internet) + try_float_val(p.monto_plus) + try_float_val(p.monto_adicional)
            monto_total_pago = m_total if m_total > 0 else m_parts
            metodo = str(p.metodo_pago or "Efectivo").upper()
            key = (p.cliente_id, metodo)
            pago_por_cliente_metodo[key] = pago_por_cliente_metodo.get(key, 0.0) + monto_total_pago

    planes_db_nombres = set(p.nombre for p in planes if p.nombre)
    planes_clientes_nombres = set(c.plan for c in clientes_con_factura if c.plan)
    planes_nombres = sorted(list(planes_db_nombres.union(planes_clientes_nombres)))

    resumen_data = []
    gran_total_clientes = 0
    gran_total_estimado = 0.0
    gran_total_efectivo = 0.0
    gran_total_pichincha = 0.0
    gran_total_jep = 0.0
    gran_total_reunido = 0.0

    for plan_nombre in planes_nombres:
        clientes_en_plan = [c for c in clientes_con_factura if c.plan and c.plan.strip() == plan_nombre.strip() and (str(c.estado or "").strip().upper() == "ACTIVO")]
        cant_clientes = len(clientes_en_plan)
        precio_plan = planes_precios.get(plan_nombre, 0.0)
        megas_plan = planes_megas.get(plan_nombre.strip().upper(), 0)
        generacion_estimada = cant_clientes * precio_plan
        
        efectivo_plan = 0.0
        pichincha_plan = 0.0
        jep_plan = 0.0
        for c in clientes_en_plan:
            for metodo_key, monto in pago_por_cliente_metodo.items():
                cid, met = metodo_key
                if cid == c.id:
                    if "JEP" in met:
                        jep_plan += monto
                    elif "PICHINCHA" in met:
                        pichincha_plan += monto
                    else:
                        efectivo_plan += monto
        total_reunido_plan = efectivo_plan + pichincha_plan + jep_plan
        resumen_data.append({
            "PLAN": plan_nombre,
            "MEGAS": f"{megas_plan}MB",
            "CANTIDAD CLIENTES": cant_clientes,
            "PRECIO PLAN": precio_plan,
            "GENERACION ESTIMADA": round(generacion_estimada, 2),
            "EFECTIVO": round(efectivo_plan, 2),
            "PICHINCHA": round(pichincha_plan, 2),
            "JEP": round(jep_plan, 2),
            "TOTAL REUNIDO": round(total_reunido_plan, 2),
            "DIFERENCIA": round(generacion_estimada - total_reunido_plan, 2),
            "% CUMPLIMIENTO": round((total_reunido_plan / generacion_estimada * 100) if generacion_estimada > 0 else 0.0, 1)
        })
        gran_total_clientes += cant_clientes
        gran_total_estimado += generacion_estimada
        gran_total_efectivo += efectivo_plan
        gran_total_pichincha += pichincha_plan
        gran_total_jep += jep_plan
        gran_total_reunido += total_reunido_plan

    resumen_data.append({
        "PLAN": "TOTAL GENERAL",
        "MEGAS": "",
        "CANTIDAD CLIENTES": gran_total_clientes,
        "PRECIO PLAN": 0.0,
        "GENERACION ESTIMADA": round(gran_total_estimado, 2),
        "EFECTIVO": round(gran_total_efectivo, 2),
        "PICHINCHA": round(gran_total_pichincha, 2),
        "JEP": round(gran_total_jep, 2),
        "TOTAL REUNIDO": round(gran_total_reunido, 2),
        "DIFERENCIA": round(gran_total_estimado - gran_total_reunido, 2),
        "% CUMPLIMIENTO": round((gran_total_reunido / gran_total_estimado * 100) if gran_total_estimado > 0 else 0.0, 1)
    })

    gen_estimada_sin_iva = round(gran_total_estimado / 1.15, 2)
    total_reunido_sin_iva = round(gran_total_reunido / 1.15, 2)
    diferencia_sin_iva = round(gen_estimada_sin_iva - total_reunido_sin_iva, 2)
    cumplimiento_sin_iva = round((total_reunido_sin_iva / gen_estimada_sin_iva * 100) if gen_estimada_sin_iva > 0 else 0.0, 1)

    resumen_data.append({
        "PLAN": "SIN IVA (15%)",
        "MEGAS": "",
        "CANTIDAD CLIENTES": "",
        "PRECIO PLAN": "",
        "GENERACION ESTIMADA": gen_estimada_sin_iva,
        "EFECTIVO": "",
        "PICHINCHA": "",
        "JEP": "",
        "TOTAL REUNIDO": total_reunido_sin_iva,
        "DIFERENCIA": diferencia_sin_iva,
        "% CUMPLIMIENTO": cumplimiento_sin_iva
    })

    # 4. Tarifas de Internet Fijo Dedicado (ARCOTEL) - Solo planes de Configuraciones + Corporativo
    fecha_vigencia_val = f"{month_num}/01/{parts[0]}" if len(parts) == 2 else "09/01/2026"
    data_tarifas = generar_data_tarifas(planes, resumen_data, mes_nombre_upper, fecha_vigencia_val)

    parroquias_set = sorted(list(set(str(x.get("Parroquia") or "") for x in data_alta_vel if x.get("Parroquia"))))

    kpis = {
        "total_cuentas": len(data_alta_vel),
        "total_facturacion": len(data_clientes),
        "total_estimado": round(gran_total_estimado, 2),
        "total_reunido": round(gran_total_reunido, 2),
        "parroquias": parroquias_set,
        "cant_parroquias": len(parroquias_set),
        "mes_label": mes_label,
        "mes_nombre_es": month_name_es
    }

    return {
        "mes": mes,
        "mes_label": mes_label,
        "kpis": kpis,
        "cuentas_alta_velocidad": data_alta_vel,
        "facturacion_clientes": data_clientes,
        "resumen_planes": resumen_data,
        "tarifas_planes": data_tarifas
    }

def guardar_excel_arcotel_congelado(datos: dict, mes: str, output_path: str):
    df_clientes = pd.DataFrame(datos.get("facturacion_clientes") or [])
    df_alta_vel = pd.DataFrame(datos.get("cuentas_alta_velocidad") or [])
    df_resumen = pd.DataFrame(datos.get("resumen_planes") or [])
    df_tarifas = pd.DataFrame(datos.get("tarifas_planes") or [])

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        if not df_clientes.empty:
            df_clientes.to_excel(writer, sheet_name="Facturación Clientes", index=False)
        else:
            pd.DataFrame([{"Mensaje": "Sin datos"}]).to_excel(writer, sheet_name="Facturación Clientes", index=False)

        if not df_alta_vel.empty:
            df_alta_vel.to_excel(writer, sheet_name="Reporte Usuarios", index=False)
        else:
            pd.DataFrame([{"Mensaje": "Sin datos"}]).to_excel(writer, sheet_name="Reporte Usuarios", index=False)

        if not df_resumen.empty:
            df_resumen.to_excel(writer, sheet_name="Resumen por Plan", index=False)
        else:
            pd.DataFrame([{"Mensaje": "Sin datos"}]).to_excel(writer, sheet_name="Resumen por Plan", index=False)

        if not df_tarifas.empty:
            df_tarifas.to_excel(writer, sheet_name="Tarifas Planes", index=False)

@router.get("/reporte-arcotel-preview")
def preview_reporte_arcotel(mes: str, db: Session = Depends(get_db)):
    try:
        # Asegurar tabla en BD
        try:
            models.ReporteArcotelGuardado.__table__.create(bind=engine, checkfirst=True)
        except Exception:
            pass

        # 1. Si ya está guardado/congelado en BD, servirlo tal cual
        guardado = db.query(models.ReporteArcotelGuardado).filter(models.ReporteArcotelGuardado.mes == mes).first()
        if guardado and guardado.datos_json:
            data = json.loads(guardado.datos_json)
            data["esta_guardado"] = True
            data["fecha_guardado"] = guardado.fecha_guardado.strftime("%d/%m/%Y %H:%M") if guardado.fecha_guardado else None
            return data

        # 2. Respaldo físico en disco si existiese
        backup_file = os.path.join("rutas_reportes", f"arcotel_frozen_{mes}.json")
        if os.path.exists(backup_file):
            with open(backup_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                data["esta_guardado"] = True
                return data

        # 3. Si no está guardado, generar dinámicamente
        data = construir_datos_arcotel(mes, db)
        data["esta_guardado"] = False
        return data
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error al generar preview ARCOTEL: {str(e)}")

@router.post("/reporte-arcotel/guardar")
def guardar_reporte_arcotel(payload: dict, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    mes = payload.get("mes")
    if not mes:
        raise HTTPException(status_code=400, detail="El parámetro 'mes' es requerido (ej: 2026-09)")

    try:
        models.ReporteArcotelGuardado.__table__.create(bind=engine, checkfirst=True)
    except Exception:
        pass

    existente = db.query(models.ReporteArcotelGuardado).filter(models.ReporteArcotelGuardado.mes == mes).first()
    if existente:
        return {
            "message": f"El reporte de {mes} ya está guardado y congelado permanentemente.",
            "esta_guardado": True,
            "fecha_guardado": existente.fecha_guardado.strftime("%d/%m/%Y %H:%M") if existente.fecha_guardado else None
        }

    datos = payload.get("datos")
    if not datos:
        datos = construir_datos_arcotel(mes, db)

    now = datetime.datetime.utcnow()
    datos["esta_guardado"] = True
    datos["fecha_guardado"] = now.strftime("%d/%m/%Y %H:%M")

    datos_str = json.dumps(datos, ensure_ascii=False)

    nuevo = models.ReporteArcotelGuardado(
        mes=mes,
        fecha_guardado=now,
        guardado_por=getattr(current_user, 'username', 'usuario'),
        datos_json=datos_str
    )
    db.add(nuevo)
    db.commit()

    # Guardar archivo JSON físico de respaldo
    try:
        os.makedirs("rutas_reportes", exist_ok=True)
        backup_file = os.path.join("rutas_reportes", f"arcotel_frozen_{mes}.json")
        with open(backup_file, "w", encoding="utf-8") as f:
            f.write(datos_str)
    except Exception as io_err:
        print(f"Aviso guardando JSON físico ARCOTEL: {io_err}")

    # Guardar Excel físico congelado para descarga inmediata
    try:
        excel_path = os.path.join("rutas_reportes", f"arcotel_guardado_{mes}.xlsx")
        guardar_excel_arcotel_congelado(datos, mes, excel_path)
    except Exception as exc_err:
        print(f"Aviso generando Excel congelado ARCOTEL: {exc_err}")

    return {
        "message": f"Reporte de {mes} guardado y congelado exitosamente. Sus valores no cambiarán.",
        "esta_guardado": True,
        "fecha_guardado": now.strftime("%d/%m/%Y %H:%M")
    }

@router.get("/reporte-excel")
def exportar_reporte_excel(mes: str, db: Session = Depends(get_db)):
    parts = mes.split("-")
    if len(parts) == 2:
        mes_anio_buscar = f"{parts[1]}-{parts[0]}"
    else:
        mes_anio_buscar = mes

    # 1. Si existe un archivo congelado de ARCOTEL para este mes, servirlo directamente
    arcotel_frozen_excel = os.path.join("rutas_reportes", f"arcotel_guardado_{mes}.xlsx")
    if os.path.exists(arcotel_frozen_excel):
        return FileResponse(
            path=arcotel_frozen_excel,
            filename=f"Reporte_ARCOTEL_{mes}.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    # 2. Si existe un snapshot guardado en BD, generar el Excel congelado y servirlo
    try:
        models.ReporteArcotelGuardado.__table__.create(bind=engine, checkfirst=True)
        guardado = db.query(models.ReporteArcotelGuardado).filter(models.ReporteArcotelGuardado.mes == mes).first()
        if guardado and guardado.datos_json:
            data_guardada = json.loads(guardado.datos_json)
            os.makedirs("rutas_reportes", exist_ok=True)
            guardar_excel_arcotel_congelado(data_guardada, mes, arcotel_frozen_excel)
            if os.path.exists(arcotel_frozen_excel):
                return FileResponse(
                    path=arcotel_frozen_excel,
                    filename=f"Reporte_ARCOTEL_{mes}.xlsx",
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
    except Exception as err_frozen:
        print(f"Aviso sirviendo reporte congelado ARCOTEL: {err_frozen}")

    # 3. Si existe un reporte mensual guardado para este mes ya cerrado, lo servimos directamente
    reporte_guardado = db.query(models.ReporteMensual).filter(models.ReporteMensual.mes_anio == mes_anio_buscar).first()
    if reporte_guardado and reporte_guardado.archivo_ruta_excel:
        path_rel = reporte_guardado.archivo_ruta_excel.lstrip("/")
        if os.path.exists(path_rel):
            return FileResponse(
                path=path_rel,
                filename=os.path.basename(path_rel),
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )


    # Si no existe reporte cerrado o es el mes actual en curso, lo generamos dinámicamente:
    clientes = db.query(models.Cliente).all()
    planes = db.query(models.PlanInternet).all()
    planes_precios = {p.nombre: float(p.precio) for p in planes if p.nombre}
    planes_megas = {}
    for p in planes:
        if p.nombre:
            planes_megas[p.nombre.strip().upper()] = int(p.megas or 0)
    
    # ── NOMBRES DE MES EN ESPAÑOL Y INGLÉS ──
    month_num = parts[1] if len(parts) == 2 else "01"
    month_name_en = {
        "01": "JANUARY", "02": "FEBRUARY", "03": "MARCH", "04": "APRIL",
        "05": "MAY", "06": "JUNE", "07": "JULY", "08": "AUGUST",
        "09": "SEPTEMBER", "10": "OCTOBER", "11": "NOVEMBER", "12": "DECEMBER"
    }.get(month_num, "MONTH")

    month_name_es = {
        "01": "Enero", "02": "Febrero", "03": "Marzo", "04": "Abril",
        "05": "Mayo", "06": "Junio", "07": "Julio", "08": "Agosto",
        "09": "Septiembre", "10": "Octubre", "11": "Noviembre", "12": "Diciembre"
    }.get(month_num, "Mes")
    mes_label = f"{month_name_es} {parts[0]}" if len(parts) == 2 else mes

    # ── FILTRAR SOLO CLIENTES CON FACTURA Y CÓDIGO VÁLIDO (INCLUYE CORTESÍA TOTAL CON FACTURA) ──
    clientes_con_factura = []
    clientes_con_factura_ids = set()
    for c in clientes:
        fact_raw = str(c.facturas or "").strip().upper()
        cod_raw = str(c.cod or "").strip()
        is_cortesia = bool(getattr(c, 'cortesia_total', False))

        tiene_factura_normal = (fact_raw == "SI" and bool(cod_raw))
        es_cortesia_con_factura = is_cortesia and (fact_raw == "SI" or bool(cod_raw))

        if tiene_factura_normal or es_cortesia_con_factura:
            clientes_con_factura.append(c)
            clientes_con_factura_ids.add(c.id)

    # ── HOJA 1: FACTURACIÓN CLIENTES ──
    data_clientes = []
    for c in clientes_con_factura:
        id_str = f"C{c.id:02d}" if c.id is not None else ""
        pago_mensual = float(c.pago_mensual or 0.00)
        is_cortesia = bool(getattr(c, 'cortesia_total', False))
        confirmar = True if (pago_mensual > 0 or is_cortesia) else False

        # Extraer megas del plan (en lugar de poner el nombre comercial del plan como 'LAG CERO')
        plan_clean = str(c.plan or "").strip().upper()
        megas_num = planes_megas.get(plan_clean, 0)
        if megas_num == 0 and plan_clean:
            m = re.search(r'(\d+)', plan_clean)
            if m:
                megas_num = int(m.group(1))

        plan_val = f"{megas_num}MB" if megas_num > 0 else ""
        cod_val = str(c.cod or "").strip() or id_str

        data_clientes.append({
            "ID": id_str,
            "RUC / CEDULA": str(c.cedula or "").strip(),
            "NAME": c.nombre or "",
            "DIRECTION": c.direccion or "",
            "CEL": str(c.celular or "").strip(),
            "PARISH": c.parroquia or "",
            "PLAN": plan_val,
            f"FACT {month_name_en}": "SI",
            "ESTADO": c.estado or "Pendiente",
            "CONFIRMAR": confirmar,
            "FACTURAS": cod_val
        })
    df_clientes = pd.DataFrame(data_clientes)
    if not df_clientes.empty:
        df_clientes = df_clientes.sort_values(by=["ESTADO", "NAME"])

    # ── NUEVA HOJA: REPORTE USUARIOS (FORMATO ARCOTEL - LÍNEAS DEDICADAS) ──
    mes_nombre_upper = month_name_es.upper()
    data_alta_vel = []
    for c in clientes_con_factura:
        plan_clean = str(c.plan or "").strip().upper()
        megas_num = planes_megas.get(plan_clean, 0)
        if megas_num == 0 and plan_clean:
            m = re.search(r'(\d+)', plan_clean)
            if m:
                megas_num = int(m.group(1))
        if megas_num <= 0:
            megas_num = 100
            
        kbps_val = int(megas_num * 1000)
        parroquia_val = normalizar_parroquia(c.parroquia)
        
        plan_str = str(c.plan or "").upper()
        nom_str = str(c.nombre or "").upper()
        if "CORP" in plan_str or "EMPRES" in plan_str or "CORP" in nom_str:
            tipo_cli = "Corporativo"
        elif "CIBER" in plan_str or "CYBER" in plan_str:
            tipo_cli = "Cibercafé"
        else:
            tipo_cli = "Residencial"
            
        tel_val = str(c.celular or "").strip()
        if tel_val.endswith(".0"):
            tel_val = tel_val[:-2]

        data_alta_vel.append({
            "MES": mes_nombre_upper,
            "Provincia": "AZUAY",
            "Cantón": "CUENCA",
            "Parroquia": parroquia_val,
            "Nombre del Usuario": str(c.nombre or "").strip().upper(),
            "Dirección": str(c.direccion or "").strip().upper(),
            "Teléfono": tel_val,
            "Número estimado de usuarios por cuenta": 4,
            "Empresa proveedora del canal (Portador)": "NEDETEL",
            "Tipo de enlace: Cobre, Cable Coaxial, Fibra Óptica, Medio Inalámbrico": "Fibra Óptica",
            "Ancho de banda Up Link (Kbps)": kbps_val,
            "Ancho de banda Down Link (Kbps)": kbps_val,
            "Tipo de Cliente (Residencial, Corporativo, Cibercafé)": tipo_cli,
            "Nivel de Compartición": "8 : 1"
        })

    df_alta_vel = pd.DataFrame(data_alta_vel)
    if not df_alta_vel.empty:
        df_alta_vel = df_alta_vel.sort_values(by=["Parroquia", "Nombre del Usuario"])
    else:
        df_alta_vel = pd.DataFrame(columns=[
            "MES", "Provincia", "Cantón", "Parroquia", "Nombre del Usuario", "Dirección",
            "Teléfono", "Número estimado de usuarios por cuenta",
            "Empresa proveedora del canal (Portador)",
            "Tipo de enlace: Cobre, Cable Coaxial, Fibra Óptica, Medio Inalámbrico",
            "Ancho de banda Up Link (Kbps)", "Ancho de banda Down Link (Kbps)",
            "Tipo de Cliente (Residencial, Corporativo, Cibercafé)",
            "Nivel de Compartición"
        ])

    # ── HOJA 2: RESUMEN POR PLAN (SOLO CLIENTES CON FACTURA) ──
    pagos_todos = db.query(models.Pago).all()
    pagos_mes = [
        p for p in pagos_todos 
        if str(p.fecha_pago)[:7] == mes 
        and p.cliente_id in clientes_con_factura_ids 
        and not getattr(p, 'anulado', False)
    ]
    
    pago_por_cliente = {}
    pago_por_cliente_metodo = {}
    for p in pagos_mes:
        if p.cliente_id:
            m_total = float(p.monto or 0)
            m_parts = float(p.monto_internet or 0) + float(p.monto_plus or 0) + float(p.monto_adicional or 0)
            monto_total_pago = m_total if m_total > 0 else m_parts
            pago_por_cliente[p.cliente_id] = pago_por_cliente.get(p.cliente_id, 0.0) + monto_total_pago
            metodo = (p.metodo_pago or "Efectivo").upper()
            key = (p.cliente_id, metodo)
            pago_por_cliente_metodo[key] = pago_por_cliente_metodo.get(key, 0.0) + monto_total_pago
            
    planes_db_nombres = set(p.nombre for p in planes if p.nombre)
    planes_clientes_nombres = set(c.plan for c in clientes_con_factura if c.plan)
    planes_nombres = sorted(list(planes_db_nombres.union(planes_clientes_nombres)))
    
    resumen_data = []
    gran_total_clientes = 0
    gran_total_estimado = 0.0
    gran_total_efectivo = 0.0
    gran_total_pichincha = 0.0
    gran_total_jep = 0.0
    gran_total_reunido = 0.0

    internet_ef = internet_pich = internet_jep = 0.0
    plus_ef = plus_pich = 0.0
    adicional_total = 0.0

    for p in pagos_mes:
        metodo = (p.metodo_pago or "").upper()
        m_internet = float(p.monto_internet or 0)
        m_plus    = float(p.monto_plus or 0)
        m_adic    = float(p.monto_adicional or 0)
        if m_internet == 0 and m_plus == 0 and float(p.monto or 0) > 0:
            m_internet = float(p.monto or 0)
        adicional_total += m_adic
        if "JEP" in metodo:
            internet_jep += m_internet
        elif "PICHINCHA" in metodo:
            internet_pich += m_internet
            plus_pich += m_plus
        else:
            internet_ef += m_internet
            plus_ef += m_plus

    total_internet = internet_ef + internet_pich + internet_jep
    total_plus     = plus_ef + plus_pich
    
    for plan_nombre in planes_nombres:
        clientes_en_plan = [c for c in clientes_con_factura if c.plan and c.plan.strip() == plan_nombre.strip() and (c.estado and c.estado.strip().upper() == "ACTIVO")]
        cant_clientes = len(clientes_en_plan)
        precio_plan = planes_precios.get(plan_nombre, 0.0)
        megas_plan = planes_megas.get(plan_nombre, 0)
        generacion_estimada = cant_clientes * precio_plan
        
        efectivo_plan = 0.0
        pichincha_plan = 0.0
        jep_plan = 0.0
        for c in clientes_en_plan:
            for metodo_key, monto in pago_por_cliente_metodo.items():
                cid, met = metodo_key
                if cid == c.id:
                    if "JEP" in met:
                        jep_plan += monto
                    elif "PICHINCHA" in met:
                        pichincha_plan += monto
                    else:
                        efectivo_plan += monto
        
        total_reunido_plan = efectivo_plan + pichincha_plan + jep_plan
        
        resumen_data.append({
            "PLAN": plan_nombre,
            "MEGAS": f"{megas_plan}MB",
            "CANTIDAD CLIENTES": cant_clientes,
            "PRECIO PLAN": precio_plan,
            "GENERACION ESTIMADA": round(generacion_estimada, 2),
            "EFECTIVO": round(efectivo_plan, 2),
            "PICHINCHA": round(pichincha_plan, 2),
            "JEP": round(jep_plan, 2),
            "TOTAL REUNIDO": round(total_reunido_plan, 2),
            "DIFERENCIA": round(generacion_estimada - total_reunido_plan, 2),
            "% CUMPLIMIENTO": round((total_reunido_plan / generacion_estimada * 100) if generacion_estimada > 0 else 0.0, 1)
        })
        
        gran_total_clientes += cant_clientes
        gran_total_estimado += generacion_estimada
        gran_total_efectivo += efectivo_plan
        gran_total_pichincha += pichincha_plan
        gran_total_jep += jep_plan
        gran_total_reunido += total_reunido_plan
    
    resumen_data.append({
        "PLAN": "TOTAL GENERAL",
        "MEGAS": "",
        "CANTIDAD CLIENTES": gran_total_clientes,
        "PRECIO PLAN": "",
        "GENERACION ESTIMADA": round(gran_total_estimado, 2),
        "EFECTIVO": round(gran_total_efectivo, 2),
        "PICHINCHA": round(gran_total_pichincha, 2),
        "JEP": round(gran_total_jep, 2),
        "TOTAL REUNIDO": round(gran_total_reunido, 2),
        "DIFERENCIA": round(gran_total_estimado - gran_total_reunido, 2),
        "% CUMPLIMIENTO": round((gran_total_reunido / gran_total_estimado * 100) if gran_total_estimado > 0 else 0.0, 1)
    })

    gen_estimada_sin_iva = round(gran_total_estimado / 1.15, 2)
    total_reunido_sin_iva = round(gran_total_reunido / 1.15, 2)
    diferencia_sin_iva = round(gen_estimada_sin_iva - total_reunido_sin_iva, 2)
    cumplimiento_sin_iva = round((total_reunido_sin_iva / gen_estimada_sin_iva * 100) if gen_estimada_sin_iva > 0 else 0.0, 1)

    resumen_data.append({
        "PLAN": "SIN IVA (15%)",
        "MEGAS": "",
        "CANTIDAD CLIENTES": "",
        "PRECIO PLAN": "",
        "GENERACION ESTIMADA": gen_estimada_sin_iva,
        "EFECTIVO": "",
        "PICHINCHA": "",
        "JEP": "",
        "TOTAL REUNIDO": total_reunido_sin_iva,
        "DIFERENCIA": diferencia_sin_iva,
        "% CUMPLIMIENTO": cumplimiento_sin_iva
    })
    df_resumen = pd.DataFrame(resumen_data)

    # ── HOJA TARIFAS ARCOTEL (INTERNET FIJO DEDICADO) ──
    fecha_vigencia_val = f"{month_num}/01/{parts[0]}" if len(parts) == 2 else "09/01/2026"
    data_tarifas = generar_data_tarifas(planes, resumen_data, month_name_es.upper(), fecha_vigencia_val)
    df_tarifas = pd.DataFrame(data_tarifas)

    # ── HOJA 3: DESGLOSE DE INGRESOS POR BANCO/SERVICIO ──
    extras = db.query(models.ClienteExtra).all()
    month_key = {
        "01":"enero","02":"febrero","03":"marzo","04":"abril",
        "05":"mayo","06":"junio","07":"julio","08":"agosto",
        "09":"septiembre","10":"octubre","11":"noviembre","12":"diciembre"
    }.get(month_num, "")

    extras_ef = extras_pich = extras_jep = 0.0
    if month_key:
        for e in extras:
            pago  = float(getattr(e, f"{month_key}_pago", 0) or 0)
            banco = (getattr(e, f"{month_key}_banco", "") or "").upper()
            if pago > 0:
                if "PICHINCHA" in banco: extras_pich += pago
                elif "JEP" in banco:    extras_jep += pago
                else:                   extras_ef  += pago

    total_extras = extras_ef + extras_pich + extras_jep
    total_ingresos = total_internet + total_plus + adicional_total + total_extras

    data_desglose = [
        {"CONCEPTO": "🌐 Servicio Internet", "EFECTIVO": round(internet_ef, 2), "PICHINCHA": round(internet_pich, 2), "JEP": round(internet_jep, 2), "TOTAL": round(total_internet, 2)},
        {"CONCEPTO": "📺 Servicio IPTV", "EFECTIVO": round(plus_ef, 2), "PICHINCHA": round(plus_pich, 2), "JEP": 0.0, "TOTAL": round(total_plus, 2)},
        {"CONCEPTO": "🌍 Extras / Convenios", "EFECTIVO": round(extras_ef, 2), "PICHINCHA": round(extras_pich, 2), "JEP": round(extras_jep, 2), "TOTAL": round(total_extras, 2)},
        {"CONCEPTO": "➕ Adicionales", "EFECTIVO": round(adicional_total, 2), "PICHINCHA": 0.0, "JEP": 0.0, "TOTAL": round(adicional_total, 2)},
        {"CONCEPTO": "TOTAL GENERAL", "EFECTIVO": round(internet_ef + plus_ef + extras_ef + adicional_total, 2), "PICHINCHA": round(internet_pich + plus_pich + extras_pich, 2), "JEP": round(internet_jep + extras_jep, 2), "TOTAL": round(total_ingresos, 2)}
    ]
    df_desglose = pd.DataFrame(data_desglose)

    # ── HOJA 4: EGRESOS ──
    egresos_mes = db.query(models.Egreso).filter(models.Egreso.mes == mes).all()
    egresos_data = []
    total_egresos = 0.0
    egresos_por_cat = {}

    for eg in egresos_mes:
        monto_val = float(eg.monto or 0.0)
        total_egresos += monto_val
        egresos_por_cat[eg.categoria] = egresos_por_cat.get(eg.categoria, 0.0) + monto_val
        egresos_data.append({
            "FECHA": eg.fecha or "",
            "DESCRIPCION": eg.descripcion,
            "CATEGORIA": eg.categoria.upper(),
            "SUBCATEGORIA": eg.subcategoria or "GENERAL",
            "METODO PAGO": eg.metodo_pago or "Efectivo",
            "MONTO": monto_val,
            "NOTAS": eg.notas or ""
        })

    # Gastos fijos activos
    gastos_fijos = db.query(models.GastoFijo).filter(models.GastoFijo.activo == True).all()
    for gf in gastos_fijos:
        monto_gf = float(gf.monto or 0.0)
        total_egresos += monto_gf
        egresos_por_cat[gf.categoria] = egresos_por_cat.get(gf.categoria, 0.0) + monto_gf
        egresos_data.append({
            "FECHA": f"{mes}-01",
            "DESCRIPCION": f"[FIJO] {gf.descripcion}",
            "CATEGORIA": gf.categoria.upper(),
            "SUBCATEGORIA": "GASTO RECURRENTE",
            "METODO PAGO": gf.metodo_pago or "Efectivo",
            "MONTO": monto_gf,
            "NOTAS": gf.notas or ""
        })

    df_egresos = pd.DataFrame(egresos_data)
    if not df_egresos.empty:
        df_egresos = df_egresos.sort_values(by=["CATEGORIA", "FECHA"])
        df_egresos.loc[len(df_egresos)] = {
            "FECHA": "TOTAL GENERAL", "DESCRIPCION": "", "CATEGORIA": "", "SUBCATEGORIA": "", "METODO PAGO": "",
            "MONTO": total_egresos, "NOTAS": ""
        }
    else:
        df_egresos = pd.DataFrame(columns=["FECHA", "DESCRIPCION", "CATEGORIA", "SUBCATEGORIA", "METODO PAGO", "MONTO", "NOTAS"])

    # ── HOJA 5: PROYECTOS ──
    proyectos = db.query(models.Proyecto).all()
    proyectos_data = []
    
    proyectos_activos = [p for p in proyectos if p.fecha_inicio[:7] <= mes and (not p.fecha_fin or p.fecha_fin[:7] >= mes)]
    total_proyectos = sum(float(p.monto_invertido or 0) for p in proyectos_activos)

    for p in proyectos:
        proyectos_data.append({
            "NOMBRE PROYECTO": p.nombre,
            "DESCRIPCION": p.descripcion or "",
            "MONTO TOTAL PRESUPUESTO": float(p.monto_total or 0.0),
            "MONTO INVERTIDO": float(p.monto_invertido or 0.0),
            "ESTADO": p.estado or "",
            "FECHA INICIO": p.fecha_inicio or "",
            "FECHA FIN": p.fecha_fin or ""
        })
    df_proyectos = pd.DataFrame(proyectos_data)
    if df_proyectos.empty:
        df_proyectos = pd.DataFrame(columns=["NOMBRE PROYECTO", "DESCRIPCION", "MONTO TOTAL PRESUPUESTO", "MONTO INVERTIDO", "ESTADO", "FECHA INICIO", "FECHA FIN"])
    else:
        df_proyectos.loc[len(df_proyectos)] = {
            "NOMBRE PROYECTO": "TOTAL GENERAL", "DESCRIPCION": "",
            "MONTO TOTAL PRESUPUESTO": sum(x["MONTO TOTAL PRESUPUESTO"] for x in proyectos_data),
            "MONTO INVERTIDO": sum(x["MONTO INVERTIDO"] for x in proyectos_data),
            "ESTADO": "", "FECHA INICIO": "", "FECHA FIN": ""
        }

    # ── HOJA 6: COLCHÓN DE LA EMPRESA ──
    colchon = db.query(models.Colchon).all()
    colchon_data = []
    for c in colchon:
        colchon_data.append({
            "FECHA": c.fecha or "",
            "CONCEPTO/DESCRIPCION": c.descripcion,
            "MONTO": float(c.monto or 0.0)
        })
    df_colchon = pd.DataFrame(colchon_data)
    if df_colchon.empty:
        df_colchon = pd.DataFrame(columns=["FECHA", "CONCEPTO/DESCRIPCION", "MONTO"])
    else:
        df_colchon.loc[len(df_colchon)] = {
            "FECHA": "TOTAL GENERAL", "CONCEPTO/DESCRIPCION": "",
            "MONTO": sum(x["MONTO"] for x in colchon_data)
        }

    balance_neto = total_ingresos - total_egresos - total_proyectos
    total_clientes_activos = sum(1 for c in clientes if c.estado == "Activo")
    total_clientes_suspendidos = sum(1 for c in clientes if c.estado == "Suspendido")
    total_clientes_otros = sum(1 for c in clientes if c.estado not in ("Activo", "Suspendido"))

    temp_dir = tempfile.gettempdir()
    file_path = os.path.join(temp_dir, f"Balance_Opsatel_{mes}.xlsx")
    
    with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
        df_clientes.to_excel(writer, sheet_name="Facturación Clientes", startrow=4, index=False)
        df_alta_vel.to_excel(writer, sheet_name="Reporte Usuarios", startrow=2, index=False)
        df_resumen.to_excel(writer, sheet_name="Resumen por Plan", startrow=4, index=False)
        df_tarifas.to_excel(writer, sheet_name="Tarifas ARCOTEL", startrow=2, index=False)
        df_desglose.to_excel(writer, sheet_name="Ingresos por Banco", startrow=4, index=False)
        df_egresos.to_excel(writer, sheet_name="Egresos", startrow=4, index=False)
        df_proyectos.to_excel(writer, sheet_name="Proyectos", startrow=4, index=False)
        df_colchon.to_excel(writer, sheet_name="Colchón de la Empresa", startrow=4, index=False)

    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    wb = openpyxl.load_workbook(file_path)

    color_primary = "1E3A8A"
    color_header_fill = PatternFill(start_color=color_primary, end_color=color_primary, fill_type="solid")
    font_header = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    
    font_title = Font(name="Calibri", size=16, bold=True, color=color_primary)
    font_subtitle = Font(name="Calibri", size=11, italic=True, color="4B5563")
    font_section = Font(name="Calibri", size=12, bold=True, color=color_primary)
    
    font_bold = Font(name="Calibri", size=10, bold=True)
    font_regular = Font(name="Calibri", size=10)
    
    fill_zebra = PatternFill(start_color="F9FAFB", end_color="F9FAFB", fill_type="solid")
    fill_total = PatternFill(start_color="E5E7EB", end_color="E5E7EB", fill_type="solid")
    fill_success = PatternFill(start_color="D1FAE5", end_color="D1FAE5", fill_type="solid")
    fill_danger = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")
    
    thin_border_side = Side(border_style="thin", color="D1D5DB")
    thin_border = Border(left=thin_border_side, right=thin_border_side, top=thin_border_side, bottom=thin_border_side)
    double_bottom_border = Border(
        left=thin_border_side, right=thin_border_side,
        top=thin_border_side,
        bottom=Side(border_style="double", color="1E3A8A")
    )
    
    align_center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    align_left = Alignment(horizontal="left", vertical="center")
    align_right = Alignment(horizontal="right", vertical="center")

    ws_res = wb.create_sheet(title="Resumen Ejecutivo", index=0)
    ws_res.views.sheetView[0].showGridLines = True
    
    ws_res["A1"] = "OPSATEL S.A.S."
    ws_res["A1"].font = Font(name="Calibri", size=18, bold=True, color=color_primary)
    ws_res["A2"] = "RUC: 0993245678001 | Operador de Telecomunicaciones"
    ws_res["A2"].font = font_subtitle
    ws_res["A3"] = f"REPORTE MENSUAL DE BALANCES Y FINANZAS — {mes_label.upper()}"
    ws_res["A3"].font = Font(name="Calibri", size=12, bold=True, color="374151")
    ws_res["A4"] = f"Fecha de generación: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
    ws_res["A4"].font = Font(name="Calibri", size=9, italic=True, color="6B7280")
    
    ws_res["A6"] = "1. ESTADO DE RESULTADOS MENSUAL"
    ws_res["A6"].font = font_section
    ws_res.merge_cells("A6:D6")
    
    headers_res = ["Detalle de Conceptos", "", "", "Monto ($)"]
    for col_idx, h in enumerate(headers_res, 1):
        cell = ws_res.cell(row=7, column=col_idx, value=h)
        cell.font = font_header
        cell.fill = color_header_fill
        cell.alignment = align_center if col_idx == 4 else align_left
        cell.border = thin_border
    ws_res.merge_cells("A7:C7")
    
    filas_resumen = [
        ("INGRESOS TOTALES DEL MES", total_ingresos, True, None),
        ("   (+) Recaudación Internet", total_internet, False, None),
        ("   (+) Recaudación IPTV", total_plus, False, None),
        ("   (+) Convenios y Extras", total_extras, False, None),
        ("   (+) Servicios Adicionales", adicional_total, False, None),
        ("EGRESOS TOTALES DEL MES", total_egresos, True, None),
        ("   (-) Gastos Operacionales", egresos_por_cat.get("OPERACIONAL", 0.0) + egresos_por_cat.get("operacional", 0.0), False, None),
        ("   (-) Nómina / Sueldos", egresos_por_cat.get("NOMINA", 0.0) + egresos_por_cat.get("nomina", 0.0), False, None),
        ("   (-) Inversión en Proyectos", total_proyectos, False, None),
        ("   (-) Otros Gastos", egresos_por_cat.get("OTRO", 0.0) + egresos_por_cat.get("otro", 0.0), False, None),
        ("BALANCE NETO (UTILIDAD/PÉRDIDA)", balance_neto, True, fill_success if balance_neto >= 0 else fill_danger)
    ]
    
    current_row = 8
    for desc, val, is_bold, fill_color in filas_resumen:
        ws_res.row_dimensions[current_row].height = 20
        ws_res.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=3)
        
        c_desc = ws_res.cell(row=current_row, column=1, value=desc)
        c_desc.font = font_bold if is_bold else font_regular
        c_desc.alignment = align_left
        
        for col in range(1, 4):
            ws_res.cell(row=current_row, column=col).border = thin_border
            if fill_color:
                ws_res.cell(row=current_row, column=col).fill = fill_color
                
        c_val = ws_res.cell(row=current_row, column=4, value=val)
        c_val.font = font_bold if is_bold else font_regular
        c_val.alignment = align_right
        c_val.number_format = '$#,##0.00'
        c_val.border = thin_border
        if fill_color:
            c_val.fill = fill_color
            
        current_row += 1
        
    current_row += 2
    ws_res.cell(row=current_row, column=1, value="2. ESTADÍSTICAS DE CLIENTES").font = font_section
    ws_res.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=4)
    
    current_row += 1
    for col_idx, h in enumerate(["Métrica de Gestión", "", "", "Cantidad"], 1):
        cell = ws_res.cell(row=current_row, column=col_idx, value=h)
        cell.font = font_header
        cell.fill = color_header_fill
        cell.alignment = align_center if col_idx == 4 else align_left
        cell.border = thin_border
    ws_res.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=3)
    
    clientes_res = [
        ("Clientes Activos en el Sistema", total_clientes_activos, False),
        ("Clientes Suspendidos en el Sistema", total_clientes_suspendidos, False),
        ("Otros Clientes / Pendientes", total_clientes_otros, False),
        ("TOTAL CLIENTES REGISTRADOS", total_clientes_activos + total_clientes_suspendidos + total_clientes_otros, True)
    ]
    
    current_row += 1
    for desc, val, is_bold in clientes_res:
        ws_res.row_dimensions[current_row].height = 20
        ws_res.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=3)
        
        c_desc = ws_res.cell(row=current_row, column=1, value=desc)
        c_desc.font = font_bold if is_bold else font_regular
        c_desc.alignment = align_left
        
        for col in range(1, 4):
            ws_res.cell(row=current_row, column=col).border = thin_border
            if is_bold:
                ws_res.cell(row=current_row, column=col).fill = fill_total
                
        c_val = ws_res.cell(row=current_row, column=4, value=val)
        c_val.font = font_bold if is_bold else font_regular
        c_val.alignment = align_right
        c_val.number_format = '#,##0'
        c_val.border = thin_border
        if is_bold:
            c_val.fill = fill_total
            
        current_row += 1
        
    current_row += 3
    ws_res.cell(row=current_row, column=2, value="_________________________").alignment = align_center
    ws_res.cell(row=current_row, column=4, value="_________________________").alignment = align_center
    
    current_row += 1
    ws_res.cell(row=current_row, column=2, value="Elaborado por: Contabilidad").font = font_bold
    ws_res.cell(row=current_row, column=2).alignment = align_center
    ws_res.cell(row=current_row, column=4, value="Aprobado por: Gerencia").font = font_bold
    ws_res.cell(row=current_row, column=4).alignment = align_center
    
    ws_res.column_dimensions["A"].width = 28
    ws_res.column_dimensions["B"].width = 15
    ws_res.column_dimensions["C"].width = 15
    ws_res.column_dimensions["D"].width = 18

    for sheet_name in wb.sheetnames:
        if sheet_name in ["Resumen Ejecutivo", "Reporte Usuarios"]:
            continue
        ws = wb[sheet_name]
        ws.views.sheetView[0].showGridLines = True
        
        ws["A1"] = "OPSATEL S.A.S."
        ws["A1"].font = font_title
        
        ws["A2"] = f"Reporte de {sheet_name} — Período: {mes_label}"
        ws["A2"].font = font_subtitle
        
        ws["A3"] = "RUC: 0993245678001 | Reporte Oficial para ARCOTEL"
        ws["A3"].font = Font(name="Calibri", size=9, color="6B7280", italic=True)
        
        max_row = ws.max_row
        max_col = ws.max_column
        
        ws.row_dimensions[5].height = 28
        for col in range(1, max_col + 1):
            cell = ws.cell(row=5, column=col)
            cell.fill = color_header_fill
            cell.font = font_header
            cell.alignment = align_center
            cell.border = thin_border
            
        for row in range(6, max_row + 1):
            ws.row_dimensions[row].height = 20
            is_zebra = (row % 2 == 1)
            is_total_row = False
            
            first_cell_val = str(ws.cell(row=row, column=1).value or "").strip().upper()
            if "TOTAL" in first_cell_val or "SIN IVA" in first_cell_val:
                is_total_row = True
                
            for col in range(1, max_col + 1):
                cell = ws.cell(row=row, column=col)
                cell.font = font_bold if is_total_row else font_regular
                cell.border = double_bottom_border if is_total_row else thin_border
                
                if is_total_row:
                    cell.fill = fill_total
                elif is_zebra:
                    cell.fill = fill_zebra
                
                val = cell.value
                col_name = str(ws.cell(row=5, column=col).value or "").strip().upper()
                
                # Si la columna es un identificador, código, cédula o teléfono, debe conservarse como TEXTO puro preservando ceros
                is_text_code_col = any(kw in col_name for kw in ["CEDULA", "RUC", "CEL", "TELEFONO", "COD", "FACTURAS", "FACTURA", "ID"])
                
                if is_text_code_col:
                    if val is not None and not isinstance(val, bool):
                        val_str = str(val).strip()
                        if val_str.endswith(".0"):
                            val_str = val_str[:-2]
                        cell.value = val_str
                        cell.number_format = '@'
                    cell.alignment = align_center
                elif isinstance(val, (int, float)) or (isinstance(val, str) and val.replace(".", "", 1).isdigit()):
                    try:
                        if isinstance(val, str):
                            val = float(val)
                            cell.value = val
                    except:
                        pass
                        
                    if "ID" in col_name or "NUMERO" in col_name or "CEL" in col_name or "COD" in col_name or "MEGAS" in col_name or "%" in col_name:
                        cell.alignment = align_center
                    else:
                        cell.alignment = align_right
                        
                    if "%" in col_name:
                        cell.number_format = '0.0"%"'
                    elif "CANTIDAD" in col_name or "CLIENTES" in col_name:
                        cell.number_format = '#,##0'
                    elif any(kw in col_name for kw in ["PRECIO", "MONTO", "VALOR", "SALDO", "REUNIDO", "PICHINCHA", "EFECTIVO", "JEP", "DIFERENCIA", "GENERACION", "TOTAL"]):
                        cell.number_format = '$#,##0.00'
                else:
                    if any(kw in col_name for kw in ["ID", "FECHA", "ESTADO", "CELULAR", "CONFIRMAR", "MEGAS", "RUC", "CEDULA"]) or (col_name == "PLAN" and ws.title == "Facturación Clientes"):
                        cell.alignment = align_center
                    else:
                        cell.alignment = align_left
                        
                if val is True:
                    cell.value = "SÍ"
                    cell.alignment = align_center
                elif val is False:
                    cell.value = "NO"
                    cell.alignment = align_center

        for col in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col[4:]:
                val_str = str(cell.value or "")
                if cell.number_format == '$#,##0.00' and isinstance(cell.value, (int, float)):
                    val_str = f"${cell.value:,.2f}"
                if len(val_str) > max_len:
                    max_len = len(val_str)
            ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

    # ── ESTILO OFICIAL PARA HOJA: REPORTE USUARIOS (ARCOTEL) ──
    if "Reporte Usuarios" in wb.sheetnames:
        ws_av = wb["Reporte Usuarios"]
        ws_av.views.sheetView[0].showGridLines = True

        fill_arcotel_header = PatternFill(start_color="C5C6E8", end_color="C5C6E8", fill_type="solid")
        fill_arcotel_title = PatternFill(start_color="D9D9F3", end_color="D9D9F3", fill_type="solid")
        font_arcotel_title1 = Font(name="Calibri", size=11, bold=True, color="000000")
        font_arcotel_title2 = Font(name="Calibri", size=10, bold=True, color="000000")
        font_arcotel_col = Font(name="Calibri", size=9, bold=True, color="000000")
        font_arcotel_data = Font(name="Calibri", size=9, color="000000")
        thin_dark_side = Side(border_style="thin", color="808080")
        border_arcotel = Border(left=thin_dark_side, right=thin_dark_side, top=thin_dark_side, bottom=thin_dark_side)

        # Fila 1: Título Principal
        ws_av.row_dimensions[1].height = 22
        ws_av.merge_cells("A1:N1")
        cell_t1 = ws_av["A1"]
        cell_t1.value = "REPORTE USUARIOS"
        cell_t1.font = font_arcotel_title1
        cell_t1.alignment = align_center

        # Fila 2: Subtítulo
        ws_av.row_dimensions[2].height = 20
        ws_av.merge_cells("A2:N2")
        cell_t2 = ws_av["A2"]
        cell_t2.value = "ACCESO NO CONMUTADO - LÍNEAS DEDICADAS"
        cell_t2.font = font_arcotel_title2
        cell_t2.alignment = align_center

        for col_idx in range(1, 15):
            c1 = ws_av.cell(row=1, column=col_idx)
            c1.fill = fill_arcotel_title
            c1.border = border_arcotel

            c2 = ws_av.cell(row=2, column=col_idx)
            c2.fill = fill_arcotel_title
            c2.border = border_arcotel

        # Fila 3: Cabeceras de columnas oficiales
        ws_av.row_dimensions[3].height = 36
        for col_idx in range(1, 15):
            c3 = ws_av.cell(row=3, column=col_idx)
            c3.fill = fill_arcotel_header
            c3.font = font_arcotel_col
            c3.alignment = align_center
            c3.border = border_arcotel

        # Filas de datos (fila 4 en adelante)
        for row_idx in range(4, ws_av.max_row + 1):
            ws_av.row_dimensions[row_idx].height = 19
            for col_idx in range(1, 15):
                c = ws_av.cell(row=row_idx, column=col_idx)
                c.font = font_arcotel_data
                c.border = border_arcotel

                if col_idx in [1, 2, 3, 4, 8, 9, 10, 13, 14]:
                    c.alignment = align_center
                elif col_idx in [5, 6]:
                    c.alignment = align_left
                elif col_idx == 7:
                    val_str = str(c.value or "").strip()
                    if val_str.endswith(".0"):
                        val_str = val_str[:-2]
                    c.value = val_str
                    c.number_format = '@'
                    c.alignment = align_center
                elif col_idx in [11, 12]:
                    try:
                        c.value = int(float(c.value or 0))
                    except:
                        pass
                    c.number_format = '0'
                    c.alignment = align_right

        # Ancho de columnas óptimo
        col_widths = {
            "A": 12, "B": 12, "C": 12, "D": 16, "E": 36, "F": 45,
            "G": 14, "H": 15, "I": 16, "J": 20, "K": 18, "L": 18,
            "M": 16, "N": 15
        }
        for col_letter, width in col_widths.items():
            ws_av.column_dimensions[col_letter].width = width

    # ── ESTILO OFICIAL PARA HOJA: TARIFAS ARCOTEL (INTERNET FIJO DEDICADO) ──
    if "Tarifas ARCOTEL" in wb.sheetnames:
        ws_tar = wb["Tarifas ARCOTEL"]
        ws_tar.views.sheetView[0].showGridLines = True

        fill_blue_title = PatternFill(start_color="B8CCE4", end_color="B8CCE4", fill_type="solid")
        fill_blue_header = PatternFill(start_color="DCE6F1", end_color="DCE6F1", fill_type="solid")
        font_tar_title = Font(name="Calibri", size=11, bold=True, color="000000")
        font_tar_col = Font(name="Calibri", size=9, bold=True, color="000000")
        font_tar_data = Font(name="Calibri", size=9, color="000000")
        thin_dark_side = Side(border_style="thin", color="808080")
        border_tar = Border(left=thin_dark_side, right=thin_dark_side, top=thin_dark_side, bottom=thin_dark_side)

        # Fila 1: Título "TARIFAS DE INTERNET FIJO DEDICADO"
        ws_tar.row_dimensions[1].height = 22
        ws_tar.merge_cells("A1:L1")
        cell_t = ws_tar["A1"]
        cell_t.value = "TARIFAS DE INTERNET FIJO DEDICADO"
        cell_t.font = font_tar_title
        cell_t.alignment = align_center

        for col_idx in range(1, 13):
            c = ws_tar.cell(row=1, column=col_idx)
            c.fill = fill_blue_title
            c.border = border_tar

        # Fila 2 y 3: Encabezados Multinivel
        ws_tar.row_dimensions[2].height = 20
        ws_tar.row_dimensions[3].height = 28

        ws_tar.merge_cells("A2:A3")
        ws_tar.cell(row=2, column=1, value="MES")

        ws_tar.merge_cells("B2:B3")
        ws_tar.cell(row=2, column=2, value="CIUDAD")

        ws_tar.merge_cells("C2:D2")
        ws_tar.cell(row=2, column=3, value="PLAN TARIFARIO")

        ws_tar.merge_cells("E2:G2")
        ws_tar.cell(row=2, column=5, value="CUENTAS")

        ws_tar.merge_cells("H2:K2")
        ws_tar.cell(row=2, column=8, value="CARACTERISTICAS TECNICAS")

        ws_tar.merge_cells("L2:L3")
        ws_tar.cell(row=2, column=12, value="OBSERVACIONES\n(Opcional)")

        sub_headers = [
            (3, "NOMBRE COMERCIAL DEL PLAN TARIFARIO"),
            (4, "FECHA DE VIGENCIA DEL PLAN TARIFARIO"),
            (5, "CANTIDAD ABONADOS/CLIENTES"),
            (6, "TIPO (RESIDENCIAL, CORPORATIVO, CIBERCAFE)"),
            (7, "TARIFA MENSUAL [USD]\n(incluido impuestos)"),
            (8, "DOWNLINK [Mbps]"),
            (9, "UPLINK [Mbps]"),
            (10, "NIVEL DE COMPARTICIÓN [X:1]"),
            (11, "TECNOLOGÍA\n(ADSL, SDSL, HFC, FTTH, WIMAX, WIFI, OTROS)")
        ]
        for col_idx, text in sub_headers:
            ws_tar.cell(row=3, column=col_idx, value=text)

        for r_idx in [2, 3]:
            for col_idx in range(1, 13):
                c = ws_tar.cell(row=r_idx, column=col_idx)
                c.fill = fill_blue_header
                c.font = font_tar_col
                c.alignment = align_center
                c.border = border_tar

        for row_idx in range(4, ws_tar.max_row + 1):
            ws_tar.row_dimensions[row_idx].height = 20
            for col_idx in range(1, 13):
                c = ws_tar.cell(row=row_idx, column=col_idx)
                c.font = font_tar_data
                c.border = border_tar

                if col_idx in [1, 2, 4, 5, 6, 8, 9, 10, 11, 12]:
                    c.alignment = align_center
                elif col_idx == 3:
                    c.alignment = align_left
                elif col_idx == 7:
                    c.alignment = align_right
                    c.number_format = '$#,##0.00'

        col_widths_tar = {
            "A": 12, "B": 12, "C": 32, "D": 16, "E": 15, "F": 16,
            "G": 18, "H": 16, "I": 16, "J": 16, "K": 18, "L": 18
        }
        for col_letter, width in col_widths_tar.items():
            ws_tar.column_dimensions[col_letter].width = width

    wb.save(file_path)

    return FileResponse(
        path=file_path,
        filename=f"Balance_Opsatel_{mes}.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# ====================================================================
# MOVIMIENTOS INTERNOS (TRANSFERENCIAS ENTRE BANCOS Y EFECTIVO)
# ====================================================================

@router.get("/movimientos-internos")
def listar_movimientos_internos(mes: str, db: Session = Depends(get_db)):
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
