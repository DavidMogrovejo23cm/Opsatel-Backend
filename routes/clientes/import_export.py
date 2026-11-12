"""
@file import_export.py
@description Importación masiva desde Excel, verificación de tablas y exportación completa de la base de datos.
"""
import io
import re
import json
import logging
import traceback
import unicodedata
from decimal import Decimal
from datetime import datetime, date
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

import models
from database import get_db
from routes.auth import require_role
from text_utils import normalize_opsatel_text
from .utils import (
    clean_int_string_value,
    try_float,
    sync_cliente_balances,
    invalidate_stats_cache
)

logger = logging.getLogger("opsatel.routes.clientes.import_export")

router = APIRouter()

@router.get("/test-db")
def test_database_tables(db: Session = Depends(get_db)):
    models_to_test = [
        ("Cliente", models.Cliente),
        ("Pago", models.Pago),
        ("Nodo", models.Nodo),
        ("PlanInternet", models.PlanInternet),
        ("Banco", models.Banco),
        ("Puerto", models.Puerto),
        ("FinanzasBase", models.FinanzasBase),
        ("Parroquia", models.Parroquia),
        ("ClienteExtra", models.ClienteExtra),
        ("PagoExtra", models.PagoExtra),
        ("HojaRuta", models.HojaRuta),
        ("Ticket", models.Ticket),
        ("CallCenterTicket", models.CallCenterTicket),
        ("Egreso", models.Egreso),
        ("Proyecto", models.Proyecto),
        ("ProyectoPago", models.ProyectoPago),
        ("GastoProyecto", models.GastoProyecto),
        ("Colchon", models.Colchon),
        ("GastoFijo", models.GastoFijo),
        ("Asistencia", models.Asistencia),
        ("WhatsAppHistorial", models.WhatsAppHistorial),
        ("WhatsAppConfiguracion", models.WhatsAppConfiguracion),
        ("ReporteMensual", models.ReporteMensual),
        ("Usuario", models.Usuario)
    ]
    results = {}
    for name, model in models_to_test:
        try:
            count = db.query(model).count()
            results[name] = {"status": "ok", "count": count}
        except Exception as e:
            results[name] = {"status": "error", "message": str(e)}
    return results


@router.get("/descargar-completo")
def descargar_completa_base_datos(db: Session = Depends(get_db)):
    """
    Exporta TODAS las tablas de la base de datos a un único archivo Excel (.xlsx) con múltiples pestañas.
    """
    try:
        TABLE_SHEET_NAMES = {
            "hoja_de_c__lculo_sin_t__tulo": "Clientes",
            "historial_pagos": "Historial de Pagos",
            "clientes_extras": "Clientes Extras",
            "historial_pagos_extras": "Pagos Extras",
            "call_center_tickets": "Tickets Call Center",
            "tickets_desarrollo": "Tickets de Desarrollo",
            "hoja_ruta": "Hojas de Ruta",
            "egresos_balance": "Egresos Balance",
            "gastos_fijos_balance": "Gastos Fijos",
            "proyectos_balance": "Proyectos",
            "proyecto_pagos": "Proyecto Pagos",
            "gastos_proyecto": "Gastos Proyectos",
            "colchon_balance": "Colchón de Reserva",
            "asistencias": "Asistencia Personal",
            "horarios_empleados": "Horarios de Empleados",
            "turnos_cajas": "Turnos de Caja",
            "finanzas_base": "Finanzas Base",
            "nodos": "Nodos",
            "planes_internet": "Planes de Internet",
            "bancos": "Bancos",
            "puertos": "Puertos",
            "parroquias": "Parroquias",
            "cajas_nap": "Cajas NAP",
            "clientes_eliminados": "Clientes Eliminados",
            "reportes_mensuales": "Reportes Mensuales",
            "usuarios": "Usuarios del Sistema",
            "whatsapp_historial": "Historial WhatsApp",
            "whatsapp_configuracion": "Configuración WhatsApp",
            "whatsapp_administradores": "Administradores WhatsApp",
            "log_facturacion": "Logs de Facturación",
            "olt_config": "Configuración OLT",
            "olt_tasks": "Tareas OLT",
            "olt_task_logs": "Logs Tareas OLT",
            "olt_power_checks": "Potencia OLT",
            "audit_events": "Eventos Auditoría",
            "network_commands": "Comandos Red",
            "worker_heartbeats": "Workers Heartbeat",
            "inventory_service_ports": "Puertos Inventario",
            "inventory_ont_ids": "IDs ONT Inventario",
            "inventory_ip_pools": "Pools IP Inventario",
            "discovered_onts": "ONTs Descubiertas",
            "discovered_service_ports": "Puertos Descubiertos",
            "discovered_boards": "Tarjetas Descubiertas",
            "libreqos_servers": "Servidores LibreQoS",
            "client_qos_state": "Estados QoS Clientes",
            "libreqos_audit": "Auditoría LibreQoS",
            "libreqos_jobs": "Trabajos LibreQoS"
        }

        inspector = inspect(db.bind)
        db_tables = inspector.get_table_names()
        
        all_tables = list(db_tables)
        if hasattr(models.Base, 'metadata') and hasattr(models.Base.metadata, 'tables'):
            for table_name in models.Base.metadata.tables.keys():
                if table_name not in all_tables:
                    all_tables.append(table_name)
                    
        if "hoja_de_c__lculo_sin_t__tulo" in all_tables:
            all_tables.remove("hoja_de_c__lculo_sin_t__tulo")
            all_tables.insert(0, "hoja_de_c__lculo_sin_t__tulo")
            
        output = io.BytesIO()
        used_sheet_names = set()

        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            sheets_written = 0
            quote_fn = db.bind.dialect.identifier_preparer.quote
            
            for table_name in all_tables:
                try:
                    quoted_name = quote_fn(table_name)
                    query_str = f"SELECT * FROM {quoted_name}"
                    result = db.execute(text(query_str))
                    columns = list(result.keys())
                    raw_rows = result.mappings().all()

                    processed_rows = []
                    for row in raw_rows:
                        d = {}
                        for col, val in row.items():
                            if isinstance(val, (datetime, date)):
                                val = val.strftime("%Y-%m-%d %H:%M:%S") if hasattr(val, "strftime") else str(val)
                            elif isinstance(val, Decimal):
                                val = float(val)
                            elif isinstance(val, (dict, list)):
                                val = json.dumps(val, default=str, ensure_ascii=False)
                            elif isinstance(val, bytes):
                                val = val.decode("utf-8", errors="ignore")
                            d[col] = val
                        processed_rows.append(d)

                    if processed_rows:
                        df = pd.DataFrame(processed_rows)
                    else:
                        df = pd.DataFrame(columns=columns)

                    display_name = TABLE_SHEET_NAMES.get(table_name, table_name.replace("_", " ").title())
                    sanitized_name = re.sub(r'[\\/*?:\[\]]', '_', display_name)
                    base_sheet_name = sanitized_name[:31]

                    final_sheet_name = base_sheet_name
                    counter = 1
                    while final_sheet_name in used_sheet_names:
                        suffix = f"_{counter}"
                        final_sheet_name = f"{base_sheet_name[:31 - len(suffix)]}{suffix}"
                        counter += 1

                    used_sheet_names.add(final_sheet_name)
                    df.to_excel(writer, sheet_name=final_sheet_name, index=False)
                    sheets_written += 1
                except Exception as sheet_err:
                    logger.warning(f"Aviso: No se pudo exportar la tabla '{table_name}': {sheet_err}")
                    continue

            if sheets_written == 0:
                pd.DataFrame({"Info": ["No se encontraron tablas exportables"]}).to_excel(writer, sheet_name="Info", index=False)

        output.seek(0)
        
        headers = {
            'Content-Disposition': 'attachment; filename="Base_Datos_Completa_Opsatel.xlsx"'
        }
        return StreamingResponse(
            output,
            media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers=headers
        )
    except Exception as e:
        logger.error(f"Error al generar la descarga de la base de datos: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error al generar la descarga de la base de datos: {str(e)}")


@router.post("/upload-db", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def upload_database(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="El archivo debe ser un Excel (.xlsx, .xls)")
    
    try:
        df = pd.read_excel(file.file)
        df = df.replace([pd.NA, float('nan')], None)
        
        count_nuevos = 0
        count_actualizados = 0
        errores = 0
        detalles_errores = []
        
        def norm_col(col_name):
            if not isinstance(col_name, str):
                return ""
            s = unicodedata.normalize('NFKD', col_name).encode('ASCII', 'ignore').decode('utf-8')
            return re.sub(r'[^A-Z0-9]', '', s.upper())

        columnas_df = {col.upper().strip(): col for col in df.columns if isinstance(col, str)}
        norm_columnas_df = {norm_col(col): col for col in df.columns if isinstance(col, str)}
        
        FIELD_MAPPING = {
            "nombre": ["NOMBRE", "NOMBRES", "CLIENTE", "NOMBRE COMPLETO"],
            "cedula": ["CEDULA", "CI", "RUC", "IDENTIFICACION", "DNI"],
            "cedula_tipo": ["CEDULA_TIPO", "TIPO_CEDULA", "TIPO_IDENTIFICACION", "CEDULA TIPO"],
            "foto_fachada": ["FOTO_FACHADA", "FOTO FACHADA", "FACHADA", "FOT.FACHADA", "FOT_FACHADA"],
            "celular": ["CELULAR", "TELEFONO", "MOVIL", "CONTACTO", "CEL"],
            "correo": ["CORREO", "EMAIL", "MAIL"],
            "direccion": ["DIRECCION", "DIR", "DOMICILIO"],
            "nodo": ["NODO", "SECTOR", "NODO_ACCESO"],
            "parroquia": ["PARROQUIA", "CIUDAD", "CANTON", "PARROQUIA/CANTON"],
            "plan": ["PLAN", "VELOCIDAD", "PAQUETE", "PLAN INTERNET"],
            "fecha_firma": ["FECHA_FIRMA", "FECHA_CONTRATO", "FIRMA", "CONTRATO", "FECHA FIRMA"],
            "estado": ["ESTADO", "STATUS", "ESTADO_CLIENTE"],
            "puerto": ["PUERTO", "PORT", "NAP_PORT", "PUERTO_PON"],
            "ont": ["ONT", "SCRIPT_ONT", "COMANDO_ONT"],
            "servicio": ["SERVICIO", "SCRIPT_SERVICIO", "COMANDO_SERVICIO"],
            "breach": ["BREACH", "SCRIPT_BREACH"],
            "id_port": ["ID_PORT", "ONT_ID", "ID PORT"],
            "service_port": ["SERVICE_PORT", "SERVICE PORT", "SP"],
            "ip": ["IP", "DIRECCION_IP", "IP_ADDRESS"],
            "dispositivo": ["DISPOSITIVO", "EQUIPO", "ROUTER", "ONU"],
            "potencia": ["POTENCIA", "DBM", "SENAL", "POTENCIA_RX"],
            "nap": ["NAP", "CAJA_NAP", "CAJA", "NUMERO_CAJA"],
            "ubicacion": ["UBICACION", "COORDENADAS", "LAT_LONG", "GPS"],
            "tecnico": ["TECNICO", "INSTALADOR_TECNICO", "TECNICO_RESPONSABLE"],
            "activador": ["ACTIVADOR", "QUIEN_ACTIVA"],
            "red": ["RED", "VLAN", "SEGMENTO"],
            "clave": ["CLAVE", "PASSWORD_WIFI", "CLAVE_ONT"],
            "mac": ["MAC", "MAC_ADDRESS", "PON_SN", "SERIAL"],
            "instalation_date": ["INSTALATION_DATE", "FECHA_INSTALACION", "FECHA_ACTIVA", "INSTALATION DATE"],
            "tiempo": ["TIEMPO", "DURACION_CONTRATO", "MESES", "CONTRATO_MESES"],
            "arrienda": ["ARRIENDA", "ARRIENDO"],
            "cuenta": ["CUENTA", "NUM_CUENTA"],
            "facturas": ["FACTURAS", "FACTURA", "NUM_FACTURA"],
            "internet_payment": ["INTERNET_PAYMENT", "INTERNET PAYMENT", "PAGO_INTERNET", "INTERNET PAY"],
            "app": ["APP", "USA_APP"],
            "payment_date": ["PAYMENT_DATE", "PAYMENT DATE", "FECHA_PAGO"],
            "client_payment_date": ["CLIENT_PAYMENT_DATE", "CLIENT PAYMENT DATE", "CLIENT PAYMENT_DATE"],
            "bank": ["BANK", "BANCO", "ENTIDAD_FINANCIERA"],
            "cod": ["COD", "CODIGO_PAGO", "CODIGO_CLIENTE"],
            "plus": ["PLUS", "ADICIONAL_MENSUAL", "TV_PLUS", "VALOR_PLUS", "IPTV"],
            "bank_plus": ["BANK_PLUS", "BANCO_TV", "BANK PLUS"],
            "adicional": ["ADICIONAL", "MONTO_ADICIONAL", "CARGO_EXTRA"],
            "comentarios": ["COMENTARIOS", "NOTAS", "OBS", "DESCRIPCION", "COMENTARIO CONTRATO", "COMENTARIOS CONTRATO"],
            "observaciones": ["OBSERVACIONES"],
            "notas_pago": ["NOTAS_PAGO", "OBSERVACION_PAGO", "NOTA DE PAGO / REPARACIÓN", "NOTA DE PAGO / REPARACION", "NOTA DE PAGO / REPARACIN", "NOTA DE PAGO", "REPARACION", "REPARACIN"],
            "tercera_edad": ["TERCERA_EDAD", "DISCAPACIDAD", "MAYOR_EDAD"],
            "precio_plan_especial": ["PRECIO_PLAN_ESPECIAL", "VALOR_ESPECIAL", "TARIFA_REDUCIDA"],
            "mantenimiento": ["MANTENIMIENTO", "PLAN_MANTENIMIENTO"],
            "saldo": ["SALDO", "DEUDA", "PENDIENTE", "SALDO_ANTERIOR"],
            "pago_mensual": ["PAGO_MENSUAL", "COBRO_MES", "RECAUDACION", "TOTAL"],
            "iptv_activar": ["IPTV_ACTIVAR", "ACTIVAR_IPTV"],
            "iptv_user": ["IPTV_USER", "USUARIO_IPTV", "CUENTA IPTV", "CUENTA_IPTV"],
            "iptv_pass": ["IPTV_PASS", "CLAVE_IPTV"],
            "iptv_bouquets": ["IPTV_BOUQUETS", "PAQUETES_IPTV"],
            "iptv_exp_date": ["IPTV_EXP_DATE", "EXPIRACION_IPTV"],
            "iptv_max_conn": ["IPTV_MAX_CONN", "PANTALLAS_IPTV", "CONEXIONES"],
            "iptv_outputs": ["IPTV_OUTPUTS", "SALIDAS_IPTV"],
            "iptv_notes": ["IPTV_NOTES", "NOTAS_IPTV"],
            "iptv_member_id": ["IPTV_MEMBER_ID", "ID_SOCIO_IPTV"]
        }

        NUMERIC_FIELDS = {"saldo", "precio_plan_especial", "pago_mensual", "total_pago", "plus_pagado", "adicional_pagado"}
        INT_FIELDS = {"id", "iptv_max_conn", "iptv_member_id"}
        BOOL_FIELDS = {"tercera_edad", "iptv_activar", "mantenimiento"}

        def get_raw_val(row, aliases):
            for alias in aliases:
                a_up = alias.upper().strip()
                if a_up in columnas_df:
                    val = row[columnas_df[a_up]]
                    if pd.notnull(val):
                        return val
                a_norm = norm_col(alias)
                if a_norm in norm_columnas_df:
                    val = row[norm_columnas_df[a_norm]]
                    if pd.notnull(val):
                        return val
            return None

        try:
            is_postgres = "postgresql" in str(db.bind.url).lower() if db.bind else False
            if is_postgres:
                db.execute(text('ALTER TABLE "hoja_de_c__lculo_sin_t__tulo" ALTER COLUMN "CLAVE" TYPE TEXT'))
            else:
                db.execute(text("ALTER TABLE `hoja_de_c__lculo_sin_t__tulo` MODIFY COLUMN `CLAVE` TEXT"))
                db.execute(text("ALTER TABLE `hoja_de_c__lculo_sin_t__tulo` MODIFY COLUMN `RED` VARCHAR(255)"))
                db.execute(text("ALTER TABLE `hoja_de_c__lculo_sin_t__tulo` MODIFY COLUMN `UBICACION` TEXT"))
                db.execute(text("ALTER TABLE `hoja_de_c__lculo_sin_t__tulo` MODIFY COLUMN `DISPOSITIVO` TEXT"))
                db.execute(text("ALTER TABLE `hoja_de_c__lculo_sin_t__tulo` MODIFY COLUMN `TECNICO` VARCHAR(255)"))
                db.execute(text("ALTER TABLE `hoja_de_c__lculo_sin_t__tulo` MODIFY COLUMN `ACTIVADOR` VARCHAR(255)"))
            db.commit()
        except Exception as alter_err:
            db.rollback()
            logger.warning(f"Aviso asegurando tipos de columnas en BD: {alter_err}")

        ids_query = db.query(models.Cliente.id).order_by(models.Cliente.id).all()
        ids_existentes = set(i[0] for i in ids_query)
        proximo_id_hueco = 1

        for index, row in df.iterrows():
            try:
                nombre_raw = get_raw_val(row, FIELD_MAPPING["nombre"])
                if not nombre_raw or str(nombre_raw).strip() == "" or str(nombre_raw).strip().lower() in ["none", "nan", "null"]:
                    continue
                nombre = str(nombre_raw).strip()
                    
                id_raw = get_raw_val(row, ["ID", "NUMERO", "COD_CLIENTE", "ID_CLIENTE"])
                id_excel = None
                if id_raw is not None:
                    try:
                        id_excel = int(float(str(id_raw).strip()))
                    except Exception:
                        id_excel = None

                if id_excel and id_excel not in ids_existentes and id_excel > 0:
                    nuevo_id = id_excel
                else:
                    while proximo_id_hueco in ids_existentes:
                        proximo_id_hueco += 1
                    nuevo_id = proximo_id_hueco
                
                cliente = models.Cliente(id=nuevo_id, nombre=normalize_opsatel_text(nombre), estado="Activo")
                ids_existentes.add(nuevo_id)
                db.add(cliente)
                count_nuevos += 1

                for field, aliases in FIELD_MAPPING.items():
                    val = get_raw_val(row, aliases)
                    if val is None:
                        continue
                    
                    if field in NUMERIC_FIELDS:
                        setattr(cliente, field, try_float(val))
                    elif field in INT_FIELDS:
                        try:
                            setattr(cliente, field, int(float(val)))
                        except Exception:
                            pass
                    elif field in BOOL_FIELDS:
                        if isinstance(val, bool):
                            setattr(cliente, field, val)
                        else:
                            s_val = str(val).upper().strip()
                            setattr(cliente, field, s_val in ["SI", "S", "TRUE", "1", "ACTIVO", "YES"])
                    elif field == "mac":
                        mac_clean = ''.join(ch for ch in str(val) if ch.isalnum()).upper()
                        cliente.mac = mac_clean
                    else:
                        clean_val = clean_int_string_value(val)
                        if field == "cedula":
                            if clean_val and clean_val.isdigit() and len(clean_val) == 9:
                                clean_val = "0" + clean_val
                            if clean_val and clean_val.upper() in ["DIGITAL", "FISICO", "FISICA"]:
                                cliente.cedula_tipo = clean_val.upper()
                        elif field == "celular":
                            if clean_val and clean_val.isdigit() and len(clean_val) == 9 and clean_val.startswith("9"):
                                clean_val = "0" + clean_val
                        elif field in ["nombre", "direccion", "parroquia", "nodo", "comentarios", "observaciones", "notas_pago", "tecnico", "activador", "nap", "referencia", "bank", "bank_plus", "app", "cuenta", "arrienda"]:
                            clean_val = normalize_opsatel_text(clean_val)
                        setattr(cliente, field, clean_val)
                
                val_estado = get_raw_val(row, FIELD_MAPPING["estado"])
                if val_estado is not None and str(val_estado).strip() and str(val_estado).strip().lower() not in ["none", "nan", "null"]:
                    estado_str = str(val_estado).strip()
                    est_upper = estado_str.upper()
                    if est_upper == "ACTIVO":
                        cliente.estado = "Activo"
                    elif est_upper == "INACTIVO":
                        cliente.estado = "Inactivo"
                    elif est_upper in ["EN PROCESO", "PROCESO"]:
                        cliente.estado = "En Proceso"
                    elif est_upper in ["JURIDICO", "JURÍDICO"]:
                        cliente.estado = "Jurídico"
                    elif est_upper == "FINIQUITO":
                        cliente.estado = "Finiquito"
                    elif est_upper in ["CORTESIA", "CORTESÍA"]:
                        cliente.estado = "Cortesía"
                    elif est_upper == "TRASLADO":
                        cliente.estado = "Traslado"
                    elif est_upper in ["PENDIENTE", "EN ACTIVACION", "EN ACTIVACIÓN"]:
                        cliente.estado = "Pendiente"
                    else:
                        cliente.estado = estado_str
                else:
                    if not cliente.estado or str(cliente.estado).strip().lower() in ["", "none", "nan", "null"]:
                        cliente.estado = "Activo"

                if cliente.iptv_user and str(cliente.iptv_user).strip():
                    cliente.iptv_activar = True
                    if not cliente.tv_tipo or cliente.tv_tipo in ["Ninguno", ""]:
                        cliente.tv_tipo = "IPTV"

                val_plan = get_raw_val(row, FIELD_MAPPING["plan"])
                if val_plan is not None:
                    plan_str = str(val_plan).strip()
                    es_precio = False
                    precio_num = 0.0
                    try:
                        precio_num = float(plan_str.replace('$', '').strip())
                        es_precio = True
                    except ValueError:
                        pass
                    
                    if es_precio and precio_num > 0:
                        cliente.precio_plan_especial = precio_num
                        if abs(precio_num - 17.25) < 0.01:
                            cliente.plan = "100mb"
                        elif abs(precio_num - 17.87) < 0.01:
                            cliente.plan = "600mb"
                        elif abs(precio_num - 21.73) < 0.01:
                            cliente.plan = "700mb"
                        elif abs(precio_num - 32.20) < 0.01:
                            cliente.plan = "800mb"
                        else:
                            cliente.plan = "Plan Especial"
                    elif plan_str and plan_str.lower() not in ["none", "nan", "null"]:
                        cliente.plan = plan_str

                if not cliente.plan or str(cliente.plan).strip().lower() in ["", "none", "nan", "null"]:
                    cliente.plan = "Plan Estándar"

                sync_cliente_balances(cliente, db)
                db.commit()

            except Exception as e:
                db.rollback()
                errores += 1
                error_detail = str(e)
                if len(error_detail) > 200:
                    error_detail = error_detail[:200] + "..."
                error_msg = f"Fila {index + 2} ({nombre if 'nombre' in locals() else 'S/N'}): {error_detail}"
                logger.error(f"Error procesando: {error_msg}")
                detalles_errores.append(error_msg)
                
        try:
            max_id_res = db.execute(text("SELECT MAX(NUMERO) FROM hoja_de_c__lculo_sin_t__tulo")).fetchone()
            if max_id_res and max_id_res[0]:
                max_id = int(max_id_res[0])
                is_pg = "postgresql" in str(db.bind.url).lower() if db.bind else False
                if is_pg:
                    db.execute(text(f"ALTER SEQUENCE hoja_de_c__lculo_sin_t__tulo_numero_seq RESTART WITH {max_id + 1}"))
                else:
                    db.execute(text(f"ALTER TABLE hoja_de_c__lculo_sin_t__tulo AUTO_INCREMENT = {max_id + 1}"))
                db.commit()
        except Exception as autoinc_err:
            logger.warning(f"Aviso actualizando AUTO_INCREMENT tras importación: {autoinc_err}")

        invalidate_stats_cache()

        return {
            "message": f"Importación completada. Se agregaron {count_nuevos} clientes/servicios a la base de datos." + (f" ({errores} errores)" if errores > 0 else ""),
            "nuevos": count_nuevos,
            "actualizados": 0,
            "errores": errores,
            "total_procesados": len(df),
            "detalles": detalles_errores[:50]
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error crítico procesando Excel: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error crítico procesando Excel: {str(e)}")
