import os
import re
import tempfile
import datetime
import pandas as pd
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session

import models
from .utils import normalizar_parroquia, sincronizar_gastos_fijos_mes
from .arcotel import generar_data_tarifas


def generar_excel_balance_anual(anio: int, data: dict) -> str:
    """Genera el reporte financiero anual en formato Excel y retorna su ruta temporal."""
    totales = data["totales"]
    meses = data["meses"]
    proyectos = data["proyectos"]

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

    # ── SECCIÓN 3: PROYECTOS Y OBRAS DEL ANIO ──
    if proyectos:
        current_row += 3
        ws.cell(row=current_row, column=1, value="PROYECTOS Y OBRAS DEL ANIO").font = font_section
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
    return file_path


def generar_excel_balance_mensual(mes: str, db: Session) -> str:
    """Genera el reporte mensual completo de balances en formato Excel y retorna su ruta temporal."""
    parts = mes.split("-")
    clientes = db.query(models.Cliente).all()
    planes = db.query(models.PlanInternet).all()
    planes_precios = {p.nombre: float(p.precio) for p in planes if p.nombre}
    planes_megas = {}
    for p in planes:
        if p.nombre:
            planes_megas[p.nombre.strip().upper()] = int(p.megas or 0)

    # Nombres de mes en español e inglés
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

    # Filtrar solo clientes con factura y código válido (incluye cortesía total con factura)
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
                elif "JEP" in banco or "GUAYAQUIL" in banco: extras_jep += pago
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
    sincronizar_gastos_fijos_mes(mes, db)
    egresos_mes = db.query(models.Egreso).filter(models.Egreso.mes == mes).all()
    egresos_data = []
    total_egresos = 0.0
    egresos_por_cat = {}

    for eg in egresos_mes:
        monto_val = float(eg.monto or 0.0)
        est = (eg.estado or "Realizado").capitalize()
        if est == "Realizado":
            total_egresos += monto_val
            egresos_por_cat[eg.categoria] = egresos_por_cat.get(eg.categoria, 0.0) + monto_val
        egresos_data.append({
            "FECHA": eg.fecha or "",
            "ESTADO": est,
            "DESCRIPCION": eg.descripcion,
            "CATEGORIA": (eg.categoria or "").upper(),
            "SUBCATEGORIA": eg.subcategoria or "GENERAL",
            "METODO PAGO": eg.metodo_pago or "Efectivo",
            "MONTO": monto_val,
            "NOTAS": eg.notas or ""
        })

    df_egresos = pd.DataFrame(egresos_data)
    if not df_egresos.empty:
        df_egresos = df_egresos.sort_values(by=["CATEGORIA", "FECHA"])
        df_egresos.loc[len(df_egresos)] = {
            "FECHA": "TOTAL GENERAL", "ESTADO": "REALIZADOS", "DESCRIPCION": "", "CATEGORIA": "", "SUBCATEGORIA": "", "METODO PAGO": "",
            "MONTO": total_egresos, "NOTAS": ""
        }
    else:
        df_egresos = pd.DataFrame(columns=["FECHA", "ESTADO", "DESCRIPCION", "CATEGORIA", "SUBCATEGORIA", "METODO PAGO", "MONTO", "NOTAS"])

    # ── HOJA 5: PROYECTOS ──
    proyectos = db.query(models.Proyecto).all()
    proyectos_data = []

    proyectos_activos = [
        p for p in proyectos
        if (p.fecha_inicio or "")[:7] <= mes
        and (not p.fecha_fin or (p.fecha_fin or "")[:7] >= mes)
        and (p.estado or "").strip().lower() != "completado"
    ]
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
    return file_path
