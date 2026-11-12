"""
@file reports.py
@description Generación de reportes mensuales y consulta de historial de reportes.
"""
import os
import re
import logging
from datetime import datetime
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
from database import get_db
from routes.auth import require_role
from config_manager import get_config, save_config
from routes.balance import normalizar_parroquia
from .utils import try_float, sync_cliente_balances

logger = logging.getLogger("opsatel.routes.clientes.reports")

router = APIRouter()

@router.get("/reportes/historial")
def listar_reportes(db: Session = Depends(get_db)):
    try:
        data = db.query(models.ReporteMensual).order_by(models.ReporteMensual.fecha_generacion.desc()).all()
        return data
    except Exception as e:
        logger.warning(f"Error listando reportes: {e}")
        return []


@router.post("/reportes/generar", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def generar_reporte_mensual(db: Session = Depends(get_db)):
    config_sys = get_config()
    current_month = datetime.now().strftime("%Y-%m")
    
    if config_sys.get("ultimo_cierre") == current_month:
        raise HTTPException(status_code=400, detail="El Cierre de Mes ya fue realizado este mes. Solo se puede hacer una vez por mes.")
    
    clientes = db.query(models.Cliente).all()
    
    month_num = current_month.split("-")[1]
    month_name_en = {
        "01": "JANUARY", "02": "FEBRUARY", "03": "MARCH", "04": "APRIL",
        "05": "MAY", "06": "JUNE", "07": "JULY", "08": "AUGUST",
        "09": "SEPTEMBER", "10": "OCTOBER", "11": "NOVEMBER", "12": "DECEMBER"
    }.get(month_num, "MONTH")

    # Obtener planes y precios
    planes = db.query(models.PlanInternet).all()
    planes_precios = {p.nombre: float(p.precio) for p in planes if p.nombre}
    planes_megas = {}
    for p in planes:
        if p.nombre:
            planes_megas[p.nombre.strip().upper()] = int(p.megas or 0)
    
    # ── FILTRAR SOLO CLIENTES CON FACTURA Y CÓDIGO VÁLIDO ──
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
    data = []
    for c in clientes_con_factura:
        id_str = f"C{c.id:02d}" if c.id is not None else ""
        pago_mensual = float(c.pago_mensual or 0.00)
        is_cortesia = bool(getattr(c, 'cortesia_total', False))
        confirmar = True if (pago_mensual > 0 or is_cortesia) else False

        plan_clean = str(c.plan or "").strip().upper()
        megas_num = planes_megas.get(plan_clean, 0)
        if megas_num == 0 and plan_clean:
            m = re.search(r'(\d+)', plan_clean)
            if m:
                megas_num = int(m.group(1))

        plan_val = f"{megas_num}MB" if megas_num > 0 else ""
        cod_val = str(c.cod or "").strip() or id_str

        data.append({
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
            "FACTURAS": cod_val,
        })
        
    df_clientes = pd.DataFrame(data)

    # ── HOJA: CUENTAS ALTA VELOCIDAD (ARCOTEL) ──
    month_name_es = {
        "01": "ENERO", "02": "FEBRERO", "03": "MARZO", "04": "ABRIL",
        "05": "MAYO", "06": "JUNIO", "07": "JULIO", "08": "AGOSTO",
        "09": "SEPTIEMBRE", "10": "OCTUBRE", "11": "NOVIEMBRE", "12": "DICIEMBRE"
    }.get(month_num, "MES")

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
            "MES": month_name_es,
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
    
    # ── HOJA 2: RESUMEN POR PLAN ──
    pagos_todos = db.query(models.Pago).all()
    pagos_mes_actual = [
        p for p in pagos_todos 
        if str(p.fecha_pago)[:7] == current_month 
        and p.cliente_id in clientes_con_factura_ids 
        and not getattr(p, 'anulado', False)
    ]
    
    pago_por_cliente_metodo = {}
    for p in pagos_mes_actual:
        if p.cliente_id:
            m_total = float(p.monto or 0)
            m_parts = float(p.monto_internet or 0) + float(p.monto_plus or 0) + float(p.monto_adicional or 0)
            monto_total_pago = m_total if m_total > 0 else m_parts
            metodo = (p.metodo_pago or "Efectivo").upper()
            key = (p.cliente_id, metodo)
            pago_por_cliente_metodo[key] = pago_por_cliente_metodo.get(key, 0.0) + monto_total_pago
            
    planes_nombres = sorted(list(set(c.plan for c in clientes_con_factura if c.plan)))
    
    resumen_data = []
    gran_total_clientes = 0
    gran_total_estimado = 0.0
    gran_total_efectivo = 0.0
    gran_total_pichincha = 0.0
    gran_total_jep = 0.0
    gran_total_reunido = 0.0
    
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
            "TOTAL REUNIDO": round(total_reunido_plan, 2)
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
        "TOTAL REUNIDO": round(gran_total_reunido, 2)
    })
    df_resumen = pd.DataFrame(resumen_data)
    
    # ── HOJA 3: EGRESOS ──
    egresos_mes = db.query(models.Egreso).filter(models.Egreso.mes == current_month).all()
    egresos_data = []
    for eg in egresos_mes:
        egresos_data.append({
            "FECHA": eg.fecha or "",
            "DESCRIPCION": eg.descripcion,
            "CATEGORIA": eg.categoria,
            "SUBCATEGORIA": eg.subcategoria or "",
            "METODO PAGO": eg.metodo_pago or "Efectivo",
            "MONTO": float(eg.monto or 0.0),
            "NOTAS": eg.notas or ""
        })
    df_egresos = pd.DataFrame(egresos_data)
    if df_egresos.empty:
        df_egresos = pd.DataFrame(columns=["FECHA", "DESCRIPCION", "CATEGORIA", "SUBCATEGORIA", "METODO PAGO", "MONTO", "NOTAS"])

    # ── HOJA 4: PROYECTOS ──
    proyectos = db.query(models.Proyecto).all()
    proyectos_data = []
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

    # ── HOJA 5: COLCHÓN DE LA EMPRESA ──
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

    os.makedirs("rutas_reportes", exist_ok=True)
    
    mes_actual = datetime.now().strftime("%m-%Y")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"Reporte_{mes_actual}_{timestamp}.xlsx"
    file_path = os.path.join("rutas_reportes", file_name)
    
    with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
        df_clientes.to_excel(writer, sheet_name="Facturación Clientes", index=False)
        df_alta_vel.to_excel(writer, sheet_name="Reporte Usuarios", index=False)
        df_resumen.to_excel(writer, sheet_name="Resumen por Plan", index=False)
        df_egresos.to_excel(writer, sheet_name="Egresos", index=False)
        df_proyectos.to_excel(writer, sheet_name="Proyectos", index=False)
        df_colchon.to_excel(writer, sheet_name="Colchón de la Empresa", index=False)
    
    nuevo_reporte = models.ReporteMensual(
        mes_anio=mes_actual,
        archivo_ruta_excel=f"/rutas_reportes/{file_name}"
    )
    db.add(nuevo_reporte)
    
    for c in clientes:
        tarifa_cierre = 0.00
        plan_info = db.query(models.PlanInternet).filter(models.PlanInternet.nombre == c.plan).first()
        if plan_info:
            tarifa_cierre = float(plan_info.precio or 0)

        c.saldo = float(c.saldo or 0) + tarifa_cierre + try_float(c.plus) + try_float(c.adicional)
        
        c.facturas = ""
        c.internet_payment = ""
        c.app = ""
        c.payment_date = ""
        c.client_payment_date = ""
        c.bank = ""
        c.cod = ""
        c.plus = ""
        c.bank_plus = ""
        c.adicional = ""
        c.plus_pagado = 0.00
        c.adicional_pagado = 0.00
        c.pago_mensual = 0.00
        c.comentarios = ""
        c.notas_pago = ""
        
        sync_cliente_balances(c, db)
        
    save_config({"ultimo_cierre": datetime.now().strftime("%Y-%m")})
    db.commit()
    
    return {
        "message": "Reporte generado. Campos de pago vaciados (saldos intactos).", 
        "reporte_id": nuevo_reporte.id, 
        "archivo": nuevo_reporte.archivo_ruta_excel
    }
