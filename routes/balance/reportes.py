import os
import json
import datetime
import calendar
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from database import get_db, engine
import models
from .utils import asegurar_columnas_egresos, sincronizar_gastos_fijos_mes
from .arcotel import guardar_excel_arcotel_congelado
from .excel_generator import generar_excel_balance_anual, generar_excel_balance_mensual

router = APIRouter()


# ====================================================================
# REPORTE MENSUAL
# ====================================================================

@router.get("/reporte-mensual")
def reporte_mensual(mes: str, db: Session = Depends(get_db)):
    asegurar_columnas_egresos(db)
    try:
        year, month = map(int, mes.split("-"))
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
                elif "JEP" in banco or "GUAYAQUIL" in banco: extras_jep += pago
                else:                   extras_ef  += pago

    total_extras   = extras_ef + extras_pich + extras_jep

    # Separación contable: Recuento Normal (Operacional) excluye IPTV Plus y Clientes Extras
    total_ingresos = round(total_internet + adicional_total, 2)

    # Asegurar que para este mes, los gastos fijos activos existan (en nuevo mes arrancan como Pendiente)
    sincronizar_gastos_fijos_mes(mes, db)

    egresos_mes = db.query(models.Egreso).filter(models.Egreso.mes == mes).all()
    egresos_por_cat = {}
    total_egresos_global = 0.0
    total_egresos_pendientes = 0.0

    egresos_op_ef = egresos_op_pich = egresos_op_jep = 0.0
    egresos_iptv_ef = egresos_iptv_pich = egresos_iptv_jep = 0.0
    egresos_pr_ef = egresos_pr_pich = egresos_pr_jep = 0.0
    total_egresos_op = 0.0
    total_egresos_iptv = 0.0
    total_egresos_pr = 0.0

    for eg in egresos_mes:
        m_val = float(eg.monto or 0)
        est = (eg.estado or "Realizado").strip().capitalize()
        
        # SI ESTÁ EN PENDIENTE: no se suma a balance ni reduce los bancos
        if est == "Pendiente":
            total_egresos_pendientes += m_val
            continue

        # SI ES REALIZADO: sí se suma a balance
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
        elif metodo == "PR" or metodo.endswith(" PR") or "PROYECTO" in metodo:
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

    # Gastos fijos activos y su estado en este mes (los egresos ya fueron sincronizados arriba)
    gastos_fijos = db.query(models.GastoFijo).filter(models.GastoFijo.activo == True).all()
    total_gastos_fijos = 0.0
    total_gastos_fijos_realizados = 0.0
    total_gastos_fijos_pendientes = 0.0
    gastos_fijos_lista = []
    eg_fijos_map = {eg.gasto_fijo_id: eg for eg in egresos_mes if eg.gasto_fijo_id}

    for gf in gastos_fijos:
        monto_gf = float(gf.monto or 0)
        total_gastos_fijos += monto_gf
        eg_asoc = eg_fijos_map.get(gf.id)
        est_gf = (eg_asoc.estado if eg_asoc and eg_asoc.estado else "Pendiente").capitalize()
        if est_gf == "Realizado":
            total_gastos_fijos_realizados += monto_gf
        else:
            total_gastos_fijos_pendientes += monto_gf

        gastos_fijos_lista.append({
            "id": gf.id,
            "egreso_id": eg_asoc.id if eg_asoc else None,
            "descripcion": gf.descripcion,
            "monto": monto_gf,
            "categoria": gf.categoria,
            "metodo_pago": gf.metodo_pago,
            "notas": gf.notas,
            "estado": est_gf
        })

    proyectos = db.query(models.Proyecto).all()
    proy_dict = {p.id: p for p in proyectos}
    # Solo proyectos activos / pendientes en este mes (se excluyen los que están en estado Completado)
    proyectos_activos = [
        p for p in proyectos
        if (p.fecha_inicio or "")[:7] <= mes
        and (not p.fecha_fin or (p.fecha_fin or "")[:7] >= mes)
        and (p.estado or "").strip().lower() != "completado"
    ]
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

    # Proyectos: Ingresos vs Gastos / Inversión por mes (solo pendientes / activos, no completados)
    proy_ganancia_ef = proy_ganancia_pich = proy_ganancia_jep = 0.0

    # 1. Pagos/cuotas de proyectos registrados en este mes específico (se excluyen de proyectos completados)
    pagos_proy_mes = db.query(models.ProyectoPago).filter(
        models.ProyectoPago.fecha.like(f"{mes}%")
    ).all()
    for pago in pagos_proy_mes:
        p_rel = proy_dict.get(pago.proyecto_id)
        if p_rel and (p_rel.estado or "").strip().lower() == "completado":
            continue
        p_val = float(pago.valor or 0)
        tp = (pago.tipo_pago or 'PICHINCHA').upper().strip()
        if "JEP" in tp or "GUAYAQUIL" in tp:
            proy_ganancia_jep += p_val
        elif "EFECTIVO" in tp:
            proy_ganancia_ef += p_val
        else:
            proy_ganancia_pich += p_val

    # 2. Proyectos cuya fecha de inicio corresponde estrictamente a este mes (excluye proyectos completados)
    proyectos_mes_inicio = [
        p for p in proyectos
        if (p.fecha_inicio or "")[:7] == mes
        and (p.estado or "").strip().lower() != "completado"
    ]
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

    # 3. Gastos de proyectos para este mes específico (se excluyen de proyectos completados)
    gastos_pr_ef = round(egresos_pr_ef, 2)
    gastos_pr_pich = round(egresos_pr_pich, 2)
    gastos_pr_jep = round(egresos_pr_jep, 2)

    gastos_proy_mes = db.query(models.GastoProyecto).filter(
        models.GastoProyecto.fecha.like(f"{mes}%"),
        models.GastoProyecto.pendiente == False
    ).all()
    for gp in gastos_proy_mes:
        p_rel = proy_dict.get(gp.proyecto_id)
        if p_rel and (p_rel.estado or "").strip().lower() == "completado":
            continue
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
                 "fecha": e.fecha, "metodo_pago": e.metodo_pago, "notas": e.notas,
                 "estado": (e.estado or "Realizado").capitalize(),
                 "gasto_fijo_id": e.gasto_fijo_id}
                for e in egresos_mes
            ],
            "gastos_fijos": gastos_fijos_lista,
            "total_gastos_fijos": total_gastos_fijos,
            "total_gastos_fijos_realizados": round(total_gastos_fijos_realizados, 2),
            "total_gastos_fijos_pendientes": round(total_gastos_fijos_pendientes, 2),
            "total": round(total_egresos_op, 2),
            "total_pendientes": round(total_egresos_pendientes, 2),
            "total_global": round(total_egresos_global, 2),
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
    asegurar_columnas_egresos(db)
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
        egresos_mes_lst = [eg for eg in egresos_all if eg.mes == mes_str and (eg.estado or "Realizado").capitalize() == "Realizado"]
        t_egresos  = sum(float(eg.monto or 0) for eg in egresos_mes_lst)
        t_egresos_iptv = sum(float(eg.monto or 0) for eg in egresos_mes_lst if "IPTV" in (eg.metodo_pago or "").upper())
        balance    = t_ingresos - t_egresos
        data_mensual.append({
            "mes": mes_str, "label": meses_labels[i-1],
            "ingresos": round(t_ingresos,2), "egresos": round(t_egresos,2),
            "balance": round(balance,2), "internet": round(t_internet,2),
            "iptv": round(t_plus,2), "adicional": round(t_adic,2), "extras": round(t_extras,2),
            "egresos_iptv": round(t_egresos_iptv,2),
            "egresos_internet": round(t_egresos - t_egresos_iptv,2),
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
    file_path = generar_excel_balance_anual(anio, data)

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
                    _, total_days = calendar.monthrange(y, m)
                    active_days = (total_days - d) + 1
                    if total_days > 0 and 0 <= active_days <= total_days:
                        proporcional = round((tarifa_mensual / total_days) * active_days, 2)
            except Exception:
                proporcional = tarifa_mensual
        
        tot_pago_val = float(c.total_pago or 0)
        deuda_actual = tot_pago_val if tot_pago_val > 0 else saldo
        
        res.append({
            "id": c.id,
            "nombre": c.nombre,
            "nodo": c.nodo,
            "plan": c.plan,
            "tarifa_mensual": tarifa_mensual,
            "proporcional": proporcional,
            "saldo_total": deuda_actual,
            "estado": c.estado,
            "instalation_date": c.instalation_date,
            "bank": c.bank
        })
    
    # Ordenar por los que más deben
    res.sort(key=lambda x: x["saldo_total"], reverse=True)
    return res


# ====================================================================
# EXPORTACIÓN EXCEL REPORTE MENSUAL (INCLUYE ARCOTEL / CIERRE)
# ====================================================================

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

    # 4. Si no existe reporte cerrado o es el mes actual en curso, lo generamos dinámicamente:
    file_path = generar_excel_balance_mensual(mes, db)

    return FileResponse(
        path=file_path,
        filename=f"Balance_Opsatel_{mes}.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
