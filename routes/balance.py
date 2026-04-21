from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from database import get_db
from .auth import require_role
import models
import datetime

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

class ProyectoUpdate(BaseModel):
    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    monto_total: Optional[float] = None
    monto_invertido: Optional[float] = None
    estado: Optional[str] = None
    fecha_inicio: Optional[str] = None
    fecha_fin: Optional[str] = None

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
# REPORTE MENSUAL
# ====================================================================

@router.get("/reporte-mensual")
def reporte_mensual(mes: str, db: Session = Depends(get_db)):
    pagos = db.query(models.Pago).all()
    pagos_mes = [p for p in pagos if str(p.fecha_pago)[:7] == mes]

    internet_ef = internet_pich = internet_jep = 0.0
    plus_ef = plus_pich = 0.0
    adicional_total = 0.0

    for p in pagos_mes:
        metodo = (p.metodo_pago or "").upper()
        m_internet = float(p.monto_internet or 0)
        m_plus    = float(p.monto_plus or 0)
        m_adic    = float(p.monto_adicional or 0)
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
    total_ingresos = total_internet + total_plus + adicional_total + total_extras

    egresos_mes = db.query(models.Egreso).filter(models.Egreso.mes == mes).all()
    egresos_por_cat = {}
    total_egresos = 0.0
    for eg in egresos_mes:
        egresos_por_cat.setdefault(eg.categoria, 0.0)
        egresos_por_cat[eg.categoria] += float(eg.monto)
        total_egresos += float(eg.monto)

    proyectos = db.query(models.Proyecto).all()
    proyectos_activos = [p for p in proyectos if p.fecha_inicio[:7] <= mes and (not p.fecha_fin or p.fecha_fin[:7] >= mes)]
    total_proyectos = sum(float(p.monto_invertido or 0) for p in proyectos_activos)

    balance_neto = total_ingresos - total_egresos - total_proyectos

    return {
        "mes": mes,
        "ingresos": {
            "internet": {"total": total_internet, "efectivo": internet_ef, "pichincha": internet_pich, "jep": internet_jep},
            "iptv":     {"total": total_plus,     "efectivo": plus_ef,    "pichincha": plus_pich},
            "adicional": adicional_total,
            "extras":   {"total": total_extras,   "efectivo": extras_ef,  "pichincha": extras_pich, "jep": extras_jep},
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
            "total": total_egresos,
        },
        "proyectos": {
            "lista": [
                {"id": p.id, "nombre": p.nombre, "descripcion": p.descripcion,
                 "monto_total": float(p.monto_total), "monto_invertido": float(p.monto_invertido or 0),
                 "estado": p.estado, "fecha_inicio": p.fecha_inicio, "fecha_fin": p.fecha_fin}
                for p in proyectos_activos
            ],
            "total": total_proyectos,
        },
        "balance_neto": balance_neto,
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
    pagos = db.query(models.Pago).all()
    extras_all = db.query(models.ClienteExtra).all()
    egresos_all = db.query(models.Egreso).all()
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
