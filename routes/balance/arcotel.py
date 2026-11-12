"""
@file arcotel.py
@description Cálculos regulatorios, preview y almacenamiento congelado de reportes ARCOTEL.
"""
import os
import json
import logging
import datetime
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
from database import engine, get_db
from routes.auth import get_current_user
from .utils import normalizar_parroquia, try_float_val, try_int_val

logger = logging.getLogger("opsatel.routes.balance.arcotel")

router = APIRouter()

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
        try:
            models.ReporteArcotelGuardado.__table__.create(bind=engine, checkfirst=True)
        except Exception:
            pass

        guardado = db.query(models.ReporteArcotelGuardado).filter(models.ReporteArcotelGuardado.mes == mes).first()
        if guardado and guardado.datos_json:
            data = json.loads(guardado.datos_json)
            data["esta_guardado"] = True
            data["fecha_guardado"] = guardado.fecha_guardado.strftime("%d/%m/%Y %H:%M") if guardado.fecha_guardado else None
            return data

        backup_file = os.path.join("rutas_reportes", f"arcotel_frozen_{mes}.json")
        if os.path.exists(backup_file):
            with open(backup_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                data["esta_guardado"] = True
                return data

        data = construir_datos_arcotel(mes, db)
        data["esta_guardado"] = False
        return data
    except Exception as e:
        logger.error(f"Error al generar preview ARCOTEL: {e}")
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

    try:
        os.makedirs("rutas_reportes", exist_ok=True)
        backup_file = os.path.join("rutas_reportes", f"arcotel_frozen_{mes}.json")
        with open(backup_file, "w", encoding="utf-8") as f:
            f.write(datos_str)
    except Exception as io_err:
        logger.warning(f"Aviso guardando JSON físico ARCOTEL: {io_err}")

    try:
        excel_path = os.path.join("rutas_reportes", f"arcotel_guardado_{mes}.xlsx")
        guardar_excel_arcotel_congelado(datos, mes, excel_path)
    except Exception as exc_err:
        logger.warning(f"Aviso generando Excel congelado ARCOTEL: {exc_err}")

    return {
        "message": f"Reporte de {mes} guardado y congelado exitosamente. Sus valores no cambiarán.",
        "esta_guardado": True,
        "fecha_guardado": now.strftime("%d/%m/%Y %H:%M")
    }
