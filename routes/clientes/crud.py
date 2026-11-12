"""
@file crud.py
@description Operaciones principales de clientes: listado, dashboard stats, parseo inteligente, creación, actualización y eliminación.
"""
import os
import calendar
import logging
import traceback
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

import models
import schemas
from database import engine, get_db
from routes.auth import get_current_user, require_role
from services.smart_parser import parse_unstructured_client_data
from .utils import (
    PLAN_PRICES,
    auto_fix_initial_balances,
    sync_cliente_balances,
    verificar_y_reactivar_cliente_por_pago_completo,
    try_float,
    is_nodo_sayausi,
    get_stats_cache,
    set_stats_cache,
    invalidate_stats_cache
)

logger = logging.getLogger("opsatel.routes.clientes.crud")

router = APIRouter()

@router.get("/pendientes-count")
def get_pendientes_count(db: Session = Depends(get_db)):
    count = db.query(models.Cliente).filter(models.Cliente.estado.in_(["Pendiente", "En Activación"])).count()
    return {"count": count}


@router.get("/contador")
@router.get("/count")
def get_clientes_contador(estado: str = "TODOS", db: Session = Depends(get_db)):
    """
    Retorna el contador general de clientes según el estado seleccionado.
    Si se indica 'TODOS' o no se especifica, retorna el total general y el desglose por estado.
    """
    try:
        estado_clean = (estado or "TODOS").strip().upper()

        if estado_clean in ["TODOS", "", "ALL"]:
            total = db.query(models.Cliente).count()
            raw_group = db.query(func.upper(models.Cliente.estado), func.count(models.Cliente.id)).group_by(func.upper(models.Cliente.estado)).all()
            por_estado = {str(k or "DESCONOCIDO").strip(): v for k, v in raw_group}
            return {
                "estado": "TODOS",
                "count": total,
                "total": total,
                "por_estado": por_estado
            }

        query = db.query(models.Cliente)
        if estado_clean == "PENDIENTE":
            query = query.filter(models.Cliente.estado.in_(["Pendiente", "En Activación", "EN ACTIVACIÓN", "EN ACTIVACION"]))
        elif estado_clean in ["PROCESO", "EN PROCESO"]:
            query = query.filter(models.Cliente.estado.in_(["Proceso", "PROCESO", "En Proceso", "EN PROCESO"]))
        elif estado_clean in ["JURIDICO", "JURÍDICO"]:
            query = query.filter(models.Cliente.estado.in_(["Juridico", "JURIDICO", "Jurídico", "JURÍDICO"]))
        else:
            query = query.filter(func.upper(models.Cliente.estado) == estado_clean)

        count = query.count()
        return {
            "estado": estado,
            "count": count
        }
    except Exception as e:
        logger.error(f"Error en contador de clientes (estado='{estado}'): {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dashboard-stats")
def get_dashboard_stats(db: Session = Depends(get_db)):
    cached = get_stats_cache()
    if cached is not None:
        return cached

    results = db.query(
        models.Pago.metodo_pago,
        func.sum(models.Pago.monto).label("total"),
        func.sum(models.Pago.monto_internet).label("internet"),
        func.sum(models.Pago.monto_plus).label("plus")
    ).filter(
        models.Pago.anulado == False,
        models.Pago.estado == "Completado"
    ).group_by(models.Pago.metodo_pago).all()
    
    internet = {"Efectivo": 0.0, "Pichincha": 0.0, "JEP": 0.0}
    plus = {"Efectivo": 0.0, "Pichincha": 0.0}
    
    for r in results:
        metodo = (r.metodo_pago or "").upper()
        m_total = float(r.total or 0)
        m_internet = float(r.internet or 0)
        m_plus = float(r.plus or 0)
            
        if "JEP" in metodo:
            internet["JEP"] += m_total
        elif "PICHINCHA" in metodo:
            internet["Pichincha"] += m_internet
            plus["Pichincha"] += m_plus
        else:
            internet["Efectivo"] += m_internet
            plus["Efectivo"] += m_plus
            
    fb = db.query(models.FinanzasBase).first()
    b_caja = float(fb.caja_chica) if fb else 0.0
    b_pich = float(fb.pichincha) if fb else 0.0
    b_jep = float(fb.jep) if fb else 0.0
    
    finanzas_globales = {
        "Caja Chica": b_caja + internet["Efectivo"] + plus["Efectivo"],
        "Pichincha": b_pich + internet["Pichincha"] + plus["Pichincha"],
        "JEP": b_jep + internet["JEP"]
    }
            
    stats = {"internet": internet, "plus": plus, "finanzas_globales": finanzas_globales}
    set_stats_cache(stats)
    return stats


@router.post("/parse-smart", dependencies=[Depends(require_role(["administrador", "secretario", "tecnico"]))])
def parse_smart_client_data(request: schemas.SmartParseRequest, db: Session = Depends(get_db)):
    try:
        valid_nodos = [n[0] for n in db.query(models.Nodo.nombre).filter(models.Nodo.nombre != None).all()]
        valid_parroquias = [p[0] for p in db.query(models.Parroquia.nombre).filter(models.Parroquia.nombre != None).all()]
        valid_planes = [pl[0] for pl in db.query(models.PlanInternet.nombre).filter(models.PlanInternet.nombre != None).all()]
        
        parsed_data = parse_unstructured_client_data(
            text=request.text,
            valid_nodos=valid_nodos,
            valid_parroquias=valid_parroquias,
            valid_planes=valid_planes
        )
        return parsed_data
    except Exception as e:
        logger.error(f"Error parse-smart: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Error al interpretar los datos con Inteligencia Artificial: {str(e)}"
        )


@router.get("/eliminados", dependencies=[Depends(require_role(["administrador"]))])
def listar_clientes_eliminados(db: Session = Depends(get_db)):
    try:
        data = db.query(models.ClienteEliminado).order_by(models.ClienteEliminado.deleted_at.desc()).all()
        return data
    except Exception as e:
        logger.error(f"Error al listar eliminados: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error al listar historial de eliminados: {str(e)}")


@router.delete("/all", dependencies=[Depends(require_role(["administrador"]))])
def eliminar_todos_clientes(db: Session = Depends(get_db)):
    """
    Elimina TODOS los clientes de la base de datos.
    Solo accesible para administradores.
    """
    try:
        clientes = db.query(models.Cliente).all()
        
        for cliente in clientes:
            if cliente.cedula_frontal:
                path = cliente.cedula_frontal.lstrip("/")
                if os.path.exists(path):
                    try: os.remove(path)
                    except Exception: pass
            if cliente.cedula_posterior:
                path = cliente.cedula_posterior.lstrip("/")
                if os.path.exists(path):
                    try: os.remove(path)
                    except Exception: pass
            if cliente.foto_fachada:
                path = cliente.foto_fachada.lstrip("/")
                if os.path.exists(path):
                    try: os.remove(path)
                    except Exception: pass
        
        count = len(clientes)
        
        db.query(models.HojaRuta).delete()
        db.query(models.Pago).delete()

        try:
            db.query(models.OLTTaskLog).delete()
            db.query(models.OLTTask).delete()
        except Exception as e:
            logger.warning(f"Aviso: No se pudieron eliminar las tareas OLT: {e}")

        try:
            db.query(models.OLTPowerCheck).delete()
        except Exception as e:
            logger.warning(f"Aviso: No se pudieron eliminar las verificaciones de potencia OLT: {e}")

        try:
            import inventory_models
            db.query(inventory_models.InventoryIpPool).update({
                inventory_models.InventoryIpPool.estado: "LIBRE",
                inventory_models.InventoryIpPool.cliente_id: None,
                inventory_models.InventoryIpPool.updated_at: datetime.now()
            })
            db.query(inventory_models.InventoryServicePort).update({
                inventory_models.InventoryServicePort.estado: "LIBRE",
                inventory_models.InventoryServicePort.cliente_id: None,
                inventory_models.InventoryServicePort.updated_at: datetime.now()
            })
            db.query(inventory_models.InventoryOntId).update({
                inventory_models.InventoryOntId.estado: "LIBRE",
                inventory_models.InventoryOntId.cliente_id: None,
                inventory_models.InventoryOntId.updated_at: datetime.now()
            })
        except Exception as e:
            logger.warning(f"Aviso: No se pudo resetear el inventario: {e}")

        try:
            from libreqos_models import ClientQoSState, LibreQoSJob, LibreQoSAuditLog
            db.query(ClientQoSState).delete()
            db.query(LibreQoSJob).delete()
            db.query(LibreQoSAuditLog).update({LibreQoSAuditLog.cliente_id: None})
        except Exception as e:
            logger.warning(f"Aviso: No se pudieron limpiar las tablas de LibreQoS: {e}")

        try:
            from discovery_models import DiscoveredONT, DiscoveredServicePort
            db.query(DiscoveredONT).update({DiscoveredONT.cliente_id: None})
            db.query(DiscoveredServicePort).update({DiscoveredServicePort.cliente_id: None})
        except Exception as e:
            logger.warning(f"Aviso: No se pudieron desvincular los dispositivos descubiertos: {e}")
        
        db.query(models.Cliente).delete()
        db.commit()
        
        try:
            from sqlalchemy import text
            is_postgresql = "postgresql" in str(engine.url).lower() or "psycopg" in str(engine.url).lower()
            is_mysql = "mysql" in str(engine.url).lower()
            
            if is_postgresql:
                db.execute(text("ALTER SEQUENCE hoja_de_c__lculo_sin_t__tulo_numero_seq RESTART WITH 1"))
                db.execute(text("ALTER SEQUENCE hoja_ruta_id_seq RESTART WITH 1"))
                db.execute(text("ALTER SEQUENCE pago_id_seq RESTART WITH 1"))
            elif is_mysql:
                db.execute(text("ALTER TABLE hoja_de_c__lculo_sin_t__tulo AUTO_INCREMENT = 1"))
                db.execute(text("ALTER TABLE hoja_ruta AUTO_INCREMENT = 1"))
                db.execute(text("ALTER TABLE historial_pagos AUTO_INCREMENT = 1"))
            
            db.commit()
        except Exception as e:
            logger.warning(f"Aviso: No se pudo resetear AUTO_INCREMENT: {e}")
        
        invalidate_stats_cache()
        return {"message": f"{count} clientes eliminados correctamente. Hojas de ruta y pagos asociados también fueron eliminados. La base de datos ha sido limpiada."}
    
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al eliminar clientes: {str(e)}")


@router.get("/")
def listar_clientes(db: Session = Depends(get_db)):
    try:
        auto_fix_initial_balances(db)
        from libreqos_models import ClientQoSState
        data = db.query(models.Cliente).all()
        
        qos_map = {state.cliente_id: state.status for state in db.query(ClientQoSState).all()}

        hojas_con_tecnico = {}
        hojas_por_nombre = {}
        try:
            for h in db.query(models.HojaRuta.cliente_id, models.HojaRuta.nombre_cliente, models.HojaRuta.tecnico).filter(
                models.HojaRuta.tecnico != None, models.HojaRuta.tecnico != ''
            ).all():
                if h.cliente_id and h.cliente_id not in hojas_con_tecnico:
                    hojas_con_tecnico[h.cliente_id] = h.tecnico
                if h.nombre_cliente and h.nombre_cliente.strip().lower() not in hojas_por_nombre:
                    hojas_por_nombre[h.nombre_cliente.strip().lower()] = h.tecnico
        except Exception as hr_map_err:
            logger.warning(f"Aviso al precargar mapa de técnicos de HojaRuta: {hr_map_err}")
        
        has_updates = False
        for c in data:
            c.bridge = c.breach
            c.qos_status = qos_map.get(c.id, "NOT_CONFIGURED")
            if c.cod and str(c.cod).strip() != "" and str(c.cod).strip().upper() != "NONE":
                if str(c.facturas or "").strip().upper() != "SI":
                    c.facturas = "SI"
                    has_updates = True

            if c.estado and str(c.estado).strip().upper() == "ACTIVO":
                if not c.activador or str(c.activador).strip() == "":
                    c.activador = "sistema"
                    has_updates = True
                if not c.tecnico or str(c.tecnico).strip() == "":
                    tec_encontrado = hojas_con_tecnico.get(c.id) or (hojas_por_nombre.get(c.nombre.strip().lower()) if c.nombre else None)
                    if tec_encontrado:
                        c.tecnico = tec_encontrado
                        has_updates = True

        if has_updates:
            try:
                db.commit()
            except Exception:
                db.rollback()
            
        return data
    except Exception as e:
        logger.error(f"Error listando clientes: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/", response_model=schemas.ClienteResponse, dependencies=[Depends(require_role(["administrador", "secretario", "tecnico"]))])
def crear_cliente(cliente: schemas.ClienteCreate, db: Session = Depends(get_db)):
    ids_query = db.query(models.Cliente.id).order_by(models.Cliente.id).all()
    ids = [i[0] for i in ids_query]
    
    nuevo_id = 1
    for current_id in ids:
        if current_id == nuevo_id:
            nuevo_id += 1
        elif current_id > nuevo_id:
            break

    iptv_act = False
    iptv_u = None
    iptv_p = None
    iptv_max = 0
    iptv_b = "[]"
    iptv_out = "[]"

    if cliente.tv_tipo == "IPTV" or cliente.iptv_activar:
        iptv_act = True
        if cliente.iptv_user and str(cliente.iptv_user).strip():
            iptv_u = str(cliente.iptv_user).strip()
        else:
            name_parts = (cliente.nombre or "").strip().split(" ")
            name_parts = [p for p in name_parts if len(p) > 0]
            generated_user = str(nuevo_id)
            if len(name_parts) >= 2:
                generated_user += name_parts[0].lower() + name_parts[1][0].lower()
            elif len(name_parts) == 1:
                generated_user += name_parts[0].lower()
            iptv_u = generated_user
        
        iptv_p = cliente.iptv_pass if (cliente.iptv_pass and str(cliente.iptv_pass).strip()) else ("TV" + str(datetime.now().year) + ".@")
        iptv_max = cliente.iptv_max_conn or 1
        iptv_b = "[1,2,5]"
        iptv_out = "[1,2]"
            
    tarifa_base = 0.0
    if cliente.mantenimiento:
        tarifa_base = 10.00
    elif (cliente.tercera_edad or cliente.plan_corporativo) and cliente.precio_plan_especial and float(cliente.precio_plan_especial) > 0:
        tarifa_base = float(cliente.precio_plan_especial)
    elif cliente.precio_plan_especial and float(cliente.precio_plan_especial) > 0:
        tarifa_base = float(cliente.precio_plan_especial)
    else:
        plan_info = db.query(models.PlanInternet).filter(models.PlanInternet.nombre == cliente.plan).first()
        if not plan_info:
            plan_info = db.query(models.PlanInternet).filter(models.PlanInternet.nombre.ilike(cliente.plan)).first()
        if plan_info and plan_info.precio is not None:
            tarifa_base = float(plan_info.precio)
        else:
            tarifa_base = float(PLAN_PRICES.get(cliente.plan, 0.00))
            if tarifa_base == 0.0 and cliente.plan:
                import re as _re
                match_precio = _re.search(r'\$?(\d+(?:[\.,]\d{1,2})?)', str(cliente.plan))
                if match_precio:
                    try:
                        tarifa_base = float(match_precio.group(1).replace(',', '.'))
                    except ValueError:
                        pass

    if cliente.saldo is not None and float(cliente.saldo) > 0:
        saldo_inicial = round(float(cliente.saldo), 2)
    else:
        saldo_inicial = tarifa_base
        try:
            f_str = (cliente.fecha_firma or "").strip().split(" ")[0].split("T")[0]
            if f_str and "-" in f_str:
                parts = f_str.split("-")
                f_year, f_month, f_day = int(parts[0]), int(parts[1]), int(parts[2])
            else:
                now = datetime.now()
                f_year, f_month, f_day = now.year, now.month, now.day

            _, total_days = calendar.monthrange(f_year, f_month)
            active_days = (total_days - f_day) + 1
            if total_days > 0 and active_days > 0:
                saldo_inicial = round((tarifa_base / total_days) * active_days, 2)
        except Exception:
            saldo_inicial = round(tarifa_base, 2)

    db_cliente = models.Cliente(
        id=nuevo_id,
        nombre=cliente.nombre,
        cedula=cliente.cedula,
        celular=cliente.celular,
        correo=cliente.correo,
        direccion=cliente.direccion,
        nodo=cliente.nodo,
        parroquia=cliente.parroquia,
        plan=cliente.plan,
        plus=cliente.plus,
        iptv_max_conn=iptv_max,
        cedula_tipo=cliente.cedula_tipo,
        foto_fachada=cliente.foto_fachada,
        ubicacion=cliente.ubicacion,
        fecha_firma=cliente.fecha_firma,
        tiempo=cliente.tiempo,
        tercera_edad=bool(cliente.tercera_edad or cliente.plan_corporativo),
        precio_plan_especial=cliente.precio_plan_especial,
        mantenimiento=bool(cliente.mantenimiento),
        comentarios=cliente.comentarios,
        estado=cliente.estado if (getattr(cliente, 'estado', None) and cliente.estado.strip()) else "En Activación",
        saldo=saldo_inicial,
        iptv_activar=iptv_act,
        iptv_user=iptv_u,
        iptv_pass=iptv_p,
        iptv_bouquets=iptv_b,
        iptv_outputs=iptv_out,
        iptv_exp_date="Nunca",
        tv_tipo=cliente.tv_tipo or "Ninguno"
    )
    try:
        db.add(db_cliente)
        sync_cliente_balances(db_cliente, db)
        db.commit()
        db.refresh(db_cliente)

        if iptv_act:
            import asyncio
            from services.xui_service import create_xui_user
            async def run_xui_creation():
                try:
                    res = await create_xui_user(
                        username=iptv_u,
                        password=iptv_p,
                        max_connections=iptv_max,
                        bouquets=["1", "2", "5"],
                        allowed_outputs=["1", "2"]
                    )
                    logger.info(f"IPTV: Cuenta de XUI creada exitosamente para {iptv_u}. Detalle: {res}")
                except Exception as xui_err:
                    logger.error(f"ERROR IPTV: Falló la creación en panel XUI para {iptv_u}: {xui_err}")

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(run_xui_creation())
            except RuntimeError:
                import threading
                threading.Thread(target=lambda: asyncio.run(run_xui_creation()), daemon=True).start()

        invalidate_stats_cache()
        return db_cliente
    except Exception as e:
        db.rollback()
        logger.error(f"Error creando cliente: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Error en la base de datos al registrar el cliente: {str(e)}"
        )


@router.get("/{id}", response_model=schemas.ClienteResponse)
def obtener_cliente(id: int, db: Session = Depends(get_db)):
    cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    if cliente.cod and str(cliente.cod).strip() != "" and str(cliente.cod).strip().upper() != "NONE":
        if str(cliente.facturas or "").strip().upper() != "SI":
            cliente.facturas = "SI"
            try:
                db.commit()
            except Exception:
                db.rollback()
    return cliente


@router.patch("/{id}", dependencies=[Depends(require_role(["administrador", "secretario", "tecnico"]))])
def actualizar_cliente_general(
    id: int, 
    data: schemas.ClienteUpdateGeneral, 
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    p_id_port = data.id_port if data.id_port is not None else cliente.id_port
    if p_id_port:
        p_nodo = data.nodo if data.nodo is not None else cliente.nodo
        p_puerto = data.puerto if data.puerto is not None else cliente.puerto
        
        if data.id_port is not None or data.nodo is not None or data.puerto is not None:
            existente_id = db.query(models.Cliente).filter(
                models.Cliente.id_port == p_id_port,
                models.Cliente.nodo == p_nodo,
                models.Cliente.puerto == p_puerto,
                models.Cliente.id != id
            ).first()
            if existente_id:
                raise HTTPException(status_code=400, detail=f"El ID Port '{p_id_port}' ya existe en el puerto '{p_puerto}' ({p_nodo}).")

    campos_globales = ["service_port", "ip", "mac"]
    for campo in campos_globales:
        nuevo_valor = getattr(data, campo)
        if nuevo_valor:
            columna = getattr(models.Cliente, campo)
            existente = db.query(models.Cliente).filter(columna == nuevo_valor, models.Cliente.id != id).first()
            if existente:
                raise HTTPException(status_code=400, detail=f"El campo '{campo}' con valor '{nuevo_valor}' ya está en uso globalmente.")

    estado_prev = cliente.estado
    ip_prev = cliente.ip
    plan_prev = cliente.plan

    es_finiquito = data.estado and str(data.estado).strip().lower() == "finiquito"
    if es_finiquito and str(estado_prev or "").strip().lower() != "finiquito":
        from decimal import Decimal
        from datetime import datetime as dt_class, date as d_class
        snapshot = {}
        for col in models.Cliente.__table__.columns:
            val = None
            if hasattr(cliente, col.key):
                val = getattr(cliente, col.key)
            elif col.key == "NUMERO" and hasattr(cliente, "id"):
                val = getattr(cliente, "id")
            else:
                val = getattr(cliente, col.name, None)

            if isinstance(val, (dt_class, d_class)):
                val = val.strftime("%Y-%m-%d %H:%M:%S") if hasattr(val, "strftime") else str(val)
            elif isinstance(val, Decimal):
                val = float(val)
            snapshot[col.name] = val

        snapshot["ESTADO"] = "Finiquito"

        username_act = getattr(current_user, "username", "admin") if current_user else "admin"
        backup_rec = models.ClienteEliminado(
            cliente_id=id,
            nombre=cliente.nombre,
            cedula=cliente.cedula,
            plan=cliente.plan,
            ip=cliente.ip,
            mac=cliente.mac,
            deleted_by=username_act,
            estado_olt="OMITIDO",
            estado_mikrotik="OMITIDO",
            estado_xui="OMITIDO",
            estado_libreqos="OMITIDO",
            estado_db="FINIQUITO",
            datos_cliente=snapshot,
            detalles_error="Cliente pasado a estado FINIQUITO (fantasma histórico) desde la vista General."
        )
        db.add(backup_rec)

        try:
            from services.libreqos_manager import LibreQoSManager
            correlation_id = f"finiquito_{id}_{int(datetime.now().timestamp())}"
            LibreQoSManager.enqueue_job("REMOVE", id, db, correlation_id, "CLIENT_FINIQUITO_API")
        except Exception as lq_err:
            logger.warning(f"Aviso LibreQoS en finiquito: {lq_err}")

    is_total_pago_edited = False
    if data.total_pago is not None:
        nuevo_tot_pago = round(float(data.total_pago), 2)
        cliente.total_pago = nuevo_tot_pago
        is_total_pago_edited = True
        if nuevo_tot_pago == 0:
            cliente.saldo = 0.0
            cliente.plus = ""
            cliente.adicional = ""
        else:
            plus_val = try_float(cliente.plus)
            adic_val = try_float(cliente.adicional)
            cliente.saldo = round(nuevo_tot_pago - plus_val - adic_val, 2)

    nuevo_pago_mensual = None
    if data.pago_mensual is not None:
        nuevo_pago_mensual = round(float(data.pago_mensual), 2)
    elif data.total is not None:
        nuevo_pago_mensual = round(float(data.total), 2)

    if nuevo_pago_mensual is not None:
        cliente.pago_mensual = nuevo_pago_mensual
        try:
            now_dt = datetime.now()
            current_month_str = now_dt.strftime("%Y-%m")
            pago_existente = db.query(models.Pago).filter(
                models.Pago.cliente_id == id,
                models.Pago.anulado == False,
                models.Pago.estado == "Completado"
            ).order_by(models.Pago.fecha_pago.desc()).first()

            is_same_month = False
            if pago_existente and pago_existente.fecha_pago:
                p_mes = pago_existente.fecha_pago.strftime("%Y-%m") if hasattr(pago_existente.fecha_pago, 'strftime') else str(pago_existente.fecha_pago)[:7]
                if p_mes == current_month_str or (pago_existente.mes_correspondiente and pago_existente.mes_correspondiente[:7] == current_month_str):
                    is_same_month = True

            p_plus = min(try_float(cliente.plus_pagado) or try_float(cliente.plus), nuevo_pago_mensual)
            p_adic = min(try_float(cliente.adicional_pagado) or try_float(cliente.adicional), max(0.0, nuevo_pago_mensual - p_plus))
            p_net = max(0.0, round(nuevo_pago_mensual - p_plus - p_adic, 2))

            if is_same_month and pago_existente:
                pago_existente.monto = nuevo_pago_mensual
                pago_existente.monto_internet = p_net
                pago_existente.monto_plus = p_plus
                pago_existente.monto_adicional = p_adic
            elif nuevo_pago_mensual > 0:
                metodo_act = cliente.bank if (cliente.bank and str(cliente.bank).strip()) else "Efectivo"
                nuevo_pago_rec = models.Pago(
                    cliente_id=id,
                    monto=nuevo_pago_mensual,
                    monto_internet=p_net,
                    monto_plus=p_plus,
                    monto_adicional=p_adic,
                    metodo_pago=metodo_act,
                    mes_correspondiente=current_month_str,
                    fecha_pago=now_dt,
                    estado="Completado",
                    anulado=False
                )
                db.add(nuevo_pago_rec)
        except Exception as p_err:
            logger.warning(f"Aviso sincronización pago en balance: {p_err}")

    if data.saldo is not None and not is_total_pago_edited:
        cliente.saldo = round(float(data.saldo), 2)

    for var, value in vars(data).items():
        if value is not None and var not in ['total', 'pago_mensual', 'total_pago', 'saldo']:
            setattr(cliente, var, value)

    if data.cod is not None and str(data.cod).strip() != "" and data.facturas is None:
        cliente.facturas = "SI"

    sync_cliente_balances(cliente, db, keep_total_pago=is_total_pago_edited)
    verificar_y_reactivar_cliente_por_pago_completo(cliente, db, motivo="ACTUALIZAR_CLIENTE")

    if (data.estado and str(data.estado).strip().upper() == "ACTIVO") or (cliente.estado and str(cliente.estado).strip().upper() == "ACTIVO"):
        if not cliente.activador or str(cliente.activador).strip() == "":
            cliente.activador = "sistema"
        if not cliente.tecnico or str(cliente.tecnico).strip() == "":
            hr = db.query(models.HojaRuta).filter(
                or_(models.HojaRuta.cliente_id == id, models.HojaRuta.nombre_cliente == cliente.nombre)
            ).order_by(models.HojaRuta.id.desc()).first()
            tecnico_hr = (hr.tecnico if hr and hr.tecnico else None)
            cliente.tecnico = tecnico_hr or (current_user.username if current_user else None) or "sistema"

    if data.ubicacion is not None:
        try:
            db.query(models.HojaRuta).filter(
                or_(models.HojaRuta.cliente_id == id, models.HojaRuta.nombre_cliente == cliente.nombre)
            ).update({"ubicacion_cliente": data.ubicacion}, synchronize_session=False)
        except Exception as hr_ubi_err:
            logger.warning(f"Aviso al sincronizar ubicacion_cliente en HojaRuta: {hr_ubi_err}")

    invalidate_stats_cache()
    db.commit()

    try:
        from services.libreqos_manager import LibreQoSManager
        correlation_id = f"up_client_{id}_{int(datetime.now().timestamp())}"
        qos_state = LibreQoSManager.get_or_create_qos_state(id, db)

        if cliente.estado == "Suspendido" and estado_prev != "Suspendido":
            LibreQoSManager.enqueue_job("SUSPEND", id, db, correlation_id, "CLIENT_UPDATE_API")
        elif cliente.estado == "Activo" and estado_prev == "Suspendido":
            LibreQoSManager.enqueue_job("RESUME", id, db, correlation_id, "CLIENT_UPDATE_API")
        elif cliente.estado == "Activo" and (estado_prev != "Activo" or qos_state.status != "APPLIED") and cliente.ip:
            LibreQoSManager.enqueue_job("PROVISION", id, db, correlation_id, "CLIENT_UPDATE_API")
        elif cliente.estado == "Activo" and estado_prev == "Activo" and qos_state.status == "APPLIED" and (cliente.ip != ip_prev or cliente.plan != plan_prev):
            LibreQoSManager.enqueue_job("UPDATE", id, db, correlation_id, "CLIENT_UPDATE_API")
    except Exception as lq_err:
        logger.warning(f"Aviso: No se pudo encolar la tarea en LibreQoS tras actualización: {lq_err}")

    return {"message": "Cliente actualizado correctamente"}


@router.patch("/{id}/configuracion-tecnica", dependencies=[Depends(require_role(["administrador", "tecnico", "instalador"]))])
def actualizar_datos_tecnicos(
    id: int, 
    data: schemas.ClienteUpdateTecnico, 
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    try:
        cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
        if not cliente:
            raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
        if data.id_port:
            existente_id = db.query(models.Cliente).filter(
                models.Cliente.id_port == data.id_port,
                models.Cliente.nodo == cliente.nodo, 
                models.Cliente.puerto == data.puerto,
                models.Cliente.id != id
            ).first()
            if existente_id:
                raise HTTPException(status_code=400, detail=f"El ID Port '{data.id_port}' ya existe en el puerto '{data.puerto}' ({cliente.nodo}).")

        campos_globales = ["service_port", "ip", "mac"]
        for campo in campos_globales:
            nuevo_valor = getattr(data, campo)
            if nuevo_valor:
                columna = getattr(models.Cliente, campo)
                existente = db.query(models.Cliente).filter(columna == nuevo_valor, models.Cliente.id != id).first()
                if existente:
                    raise HTTPException(status_code=400, detail=f"El campo '{campo}' con valor '{nuevo_valor}' ya está en uso globalmente.")

        for var, value in vars(data).items():
            setattr(cliente, var, value)
            if var == 'iptv_max_conn' and value is not None:
                plan_info = db.query(models.PlanInternet).filter(models.PlanInternet.nombre == cliente.plan).first()
                base_screens = (plan_info.pantallas if plan_info.pantallas is not None else 0) if plan_info else 0
                cliente.plus = str(max(0, (value - base_screens) * 2))
        
        sync_cliente_balances(cliente, db)
        if cliente.potencia:
            try:
                p_val = float(str(cliente.potencia).replace(',', '.').strip())
                if p_val < -27.0:
                    raise HTTPException(status_code=400, detail=f"La potencia de {p_val} dBm es demasiado baja. El límite es -27.0 dBm.")
            except ValueError:
                pass

        cliente.estado = "Activo"
        cliente.instalation_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cliente.activador = "sistema"

        hr = db.query(models.HojaRuta).filter(
            or_(models.HojaRuta.cliente_id == id, models.HojaRuta.nombre_cliente == cliente.nombre)
        ).order_by(models.HojaRuta.id.desc()).first()
        tecnico_hr = (hr.tecnico if hr and hr.tecnico else None)

        if not cliente.tecnico or str(cliente.tecnico).strip() == "":
            cliente.tecnico = tecnico_hr or (current_user.username if current_user else None) or "sistema"
        elif tecnico_hr and (not data.tecnico or str(data.tecnico).strip() == ""):
            cliente.tecnico = tecnico_hr

        db.query(models.HojaRuta).filter(
            or_(models.HojaRuta.cliente_id == id, models.HojaRuta.nombre_cliente == cliente.nombre),
            models.HojaRuta.estado.in_(["Pendiente", "En proceso"])
        ).update({"estado": "Realizado"}, synchronize_session=False)
        db.commit()

        try:
            now = datetime.now()
            _, total_days_in_month = calendar.monthrange(now.year, now.month)
            current_day = now.day
            active_days = (total_days_in_month - current_day) + 1
            
            if getattr(cliente, 'mantenimiento', False):
                tarifa_base = 10.00
            elif cliente.tercera_edad and cliente.precio_plan_especial:
                tarifa_base = float(cliente.precio_plan_especial)
            else:
                plan_info = db.query(models.PlanInternet).filter(models.PlanInternet.nombre == cliente.plan).first()
                tarifa_base = float(plan_info.precio or 0) if plan_info else 0.00
            
            plus_base = try_float(cliente.plus)
            
            if total_days_in_month > 0:
                prorated_internet = (tarifa_base / total_days_in_month) * active_days
                prorated_plus = (plus_base / total_days_in_month) * active_days
                cliente.saldo = round(prorated_internet, 2)
                cliente.plus = str(round(prorated_plus, 2))
                sync_cliente_balances(cliente, db)
        except Exception as e:
            logger.warning(f"Error calculando prorrateo: {e}")

        db.commit()
        invalidate_stats_cache()

        try:
            from services.libreqos_manager import LibreQoSManager
            lq_cid = f"ct_{id}_{int(datetime.now().timestamp())}"
            LibreQoSManager.enqueue_job("PROVISION", id, db, lq_cid, "TECHNICAL_CONFIG_AUTO")
        except Exception as lq_err:
            logger.warning(f"Error al encolar LibreQoS en actualizacion tecnica: {lq_err}")

        return {"message": "Configuración técnica guardada, cliente ahora Activo (con pago prorrateado) y con fecha de instalación registrada y encolado en LibreQoS."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error técnico: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")


@router.patch("/{id}/administracion", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def actualizar_administracion(id: int, data: schemas.ClienteUpdateAdmin, db: Session = Depends(get_db)):
    cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    was_mantenimiento = getattr(cliente, 'mantenimiento', False)
    was_custom_price = getattr(cliente, 'precio_plan_especial', None) is not None and float(cliente.precio_plan_especial or 0) > 0

    for var, value in vars(data).items():
        if value is not None:
            setattr(cliente, var, value)
            if var == 'iptv_max_conn' and data.plus is None:
                plan_info = db.query(models.PlanInternet).filter(
                    func.lower(func.trim(models.PlanInternet.nombre)) == func.lower(func.trim(cliente.plan))
                ).first() if cliente.plan else None
                base_screens = (plan_info.pantallas if (plan_info and plan_info.pantallas is not None) else 0)
                cliente.plus = str(max(0, (value - base_screens) * 2))

    if data.cod is not None and str(data.cod).strip() != "" and data.facturas is None:
        cliente.facturas = "SI"

    if data.saldo is not None:
        cliente.saldo = float(data.saldo)
    elif cliente.mantenimiento and not was_mantenimiento:
        cliente.saldo = 10.00
    elif float(cliente.precio_plan_especial or 0) > 0 and not was_custom_price:
        cliente.saldo = float(cliente.precio_plan_especial)
    elif (was_mantenimiento and not cliente.mantenimiento) or (was_custom_price and float(cliente.precio_plan_especial or 0) == 0):
        plan_info = db.query(models.PlanInternet).filter(models.PlanInternet.nombre == cliente.plan).first()
        if plan_info:
            cliente.saldo = float(plan_info.precio or 0)

    sync_cliente_balances(cliente, db)
    verificar_y_reactivar_cliente_por_pago_completo(cliente, db, motivo="ACTUALIZAR_ADMINISTRACION")
    db.commit()
    invalidate_stats_cache()
    return {"message": "Datos de administración actualizados"}


@router.delete("/{id}", dependencies=[Depends(require_role(["administrador"]))])
def eliminar_cliente(id: int, db: Session = Depends(get_db)):
    cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    if cliente.cedula_frontal:
        path = cliente.cedula_frontal.lstrip("/")
        if os.path.exists(path):
            try: os.remove(path)
            except Exception: pass
    if cliente.cedula_posterior:
        path = cliente.cedula_posterior.lstrip("/")
        if os.path.exists(path):
            try: os.remove(path)
            except Exception: pass
    if cliente.foto_fachada:
        path = cliente.foto_fachada.lstrip("/")
        if os.path.exists(path):
            try: os.remove(path)
            except Exception: pass

    try:
        task_ids = [t.id for t in db.query(models.OLTTask).filter(models.OLTTask.cliente_id == id).all()]
        if task_ids:
            db.query(models.OLTTaskLog).filter(models.OLTTaskLog.task_id.in_(task_ids)).delete(synchronize_session=False)
            db.query(models.OLTTask).filter(models.OLTTask.id.in_(task_ids)).delete(synchronize_session=False)
    except Exception as e:
        logger.warning(f"Aviso: No se pudieron eliminar las tareas OLT del cliente: {e}")

    try:
        db.query(models.OLTPowerCheck).filter(models.OLTPowerCheck.cliente_id == id).delete()
    except Exception as e:
        logger.warning(f"Aviso: No se pudieron eliminar las verificaciones de potencia OLT: {e}")

    db.query(models.Pago).filter(models.Pago.cliente_id == id).delete()
    db.query(models.HojaRuta).filter(models.HojaRuta.cliente_id == id).delete()
    
    try:
        import inventory_models
        db.query(inventory_models.InventoryIpPool).filter(
            inventory_models.InventoryIpPool.cliente_id == id
        ).update({
            inventory_models.InventoryIpPool.estado: "LIBRE",
            inventory_models.InventoryIpPool.cliente_id: None,
            inventory_models.InventoryIpPool.updated_at: datetime.now()
        })
        db.query(inventory_models.InventoryServicePort).filter(
            inventory_models.InventoryServicePort.cliente_id == id
        ).update({
            inventory_models.InventoryServicePort.estado: "LIBRE",
            inventory_models.InventoryServicePort.cliente_id: None,
            inventory_models.InventoryServicePort.updated_at: datetime.now()
        })
        db.query(inventory_models.InventoryOntId).filter(
            inventory_models.InventoryOntId.cliente_id == id
        ).update({
            inventory_models.InventoryOntId.estado: "LIBRE",
            inventory_models.InventoryOntId.cliente_id: None,
            inventory_models.InventoryOntId.updated_at: datetime.now()
        })
    except Exception as e:
        logger.warning(f"Aviso: No se pudieron liberar los recursos del inventario: {e}")
        
    try:
        from services.libreqos_manager import LibreQoSManager
        LibreQoSManager.enqueue_job(
            operation="REMOVE",
            cliente_id=id,
            db=db,
            correlation_id=f"del_client_{id}_{int(datetime.now().timestamp())}",
            created_by="CLIENT_DELETE_API"
        )
    except Exception as lq_err:
        logger.warning(f"Aviso: No se pudo encolar la eliminación en LibreQoS: {lq_err}")

    try:
        from libreqos_models import ClientQoSState
        db.query(ClientQoSState).filter(ClientQoSState.cliente_id == id).delete()
    except Exception:
        pass

    try:
        from libreqos_models import LibreQoSJob
        db.query(LibreQoSJob).filter(LibreQoSJob.cliente_id == id).delete()
    except Exception:
        pass

    try:
        from libreqos_models import LibreQoSAuditLog
        db.query(LibreQoSAuditLog).filter(LibreQoSAuditLog.cliente_id == id).update({LibreQoSAuditLog.cliente_id: None})
    except Exception:
        pass

    try:
        from discovery_models import DiscoveredONT, DiscoveredServicePort
        db.query(DiscoveredONT).filter(DiscoveredONT.cliente_id == id).update({DiscoveredONT.cliente_id: None})
        db.query(DiscoveredServicePort).filter(DiscoveredServicePort.cliente_id == id).update({DiscoveredServicePort.cliente_id: None})
    except Exception:
        pass

    db.delete(cliente)
    db.commit()

    try:
        from sqlalchemy import text
        is_mysql = "mysql" in str(engine.url).lower() if 'engine' in dir() else False
        if is_mysql:
            max_id_res = db.execute(text("SELECT MAX(NUMERO) FROM hoja_de_c__lculo_sin_t__tulo")).fetchone()
            max_id = max_id_res[0] if max_id_res and max_id_res[0] is not None else 0
            db.execute(text(f"ALTER TABLE hoja_de_c__lculo_sin_t__tulo AUTO_INCREMENT = {max_id + 1}"))
            db.commit()
    except Exception as e:
        logger.warning(f"Aviso: No se pudo resetear AUTO_INCREMENT: {e}")

    invalidate_stats_cache()
    return {"message": "Cliente eliminado correctamente y ID liberado para el siguiente registro."}


@router.post("/{id}/eliminar-completamente", dependencies=[Depends(require_role(["administrador"]))])
async def eliminar_cliente_completamente(
    id: int,
    payload_confirm: schemas.ClienteEliminarCompleto,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Elimina a un cliente de forma secuencial y controlada de todos los sistemas:
    OLT, XUI (IPTV), LibreQoS y base de datos local.
    """
    expected_pin = os.getenv("DELETE_CLIENT_PIN", "1234566")
    if payload_confirm.pin != expected_pin:
        raise HTTPException(status_code=400, detail="El PIN de seguridad es incorrecto.")
        
    cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")

    from decimal import Decimal
    from datetime import datetime as dt_class, date as d_class
    
    snapshot = {}
    for col in models.Cliente.__table__.columns:
        val = None
        if hasattr(cliente, col.key):
            val = getattr(cliente, col.key)
        elif col.key == "NUMERO" and hasattr(cliente, "id"):
            val = getattr(cliente, "id")
        else:
            val = getattr(cliente, col.name, None)

        if isinstance(val, (dt_class, d_class)):
            val = val.strftime("%Y-%m-%d %H:%M:%S") if hasattr(val, "strftime") else str(val)
        elif isinstance(val, Decimal):
            val = float(val)
        snapshot[col.name] = val

    backup_rec = models.ClienteEliminado(
        cliente_id=id,
        nombre=cliente.nombre,
        cedula=cliente.cedula,
        plan=cliente.plan,
        ip=cliente.ip,
        mac=cliente.mac,
        deleted_by=current_user.username,
        estado_olt="PENDIENTE",
        estado_mikrotik="PENDIENTE",
        estado_xui="PENDIENTE",
        estado_libreqos="PENDIENTE",
        estado_db="PENDIENTE",
        datos_cliente=snapshot
    )
    db.add(backup_rec)
    db.commit()
    db.refresh(backup_rec)

    estado_olt = "OMITIDO"
    estado_mikrotik = "OMITIDO"
    estado_xui = "OMITIDO"
    estado_libreqos = "OMITIDO"
    
    # ETAPA 1: OLT
    if cliente.id_port and cliente.service_port:
        try:
            from services.olt_interface import OLTInterface
            puerto_raw = str(cliente.puerto or "0")
            import re as _re
            m = _re.search(r'\d+', puerto_raw)
            puerto_num = m.group() if m else "0"
            
            is_sayausi_val = is_nodo_sayausi(cliente.nodo)
            gpon_port = f"0/1/{puerto_num}" if is_sayausi_val else f"0/0/{puerto_num}"
            
            olt_config = db.query(models.OLTConfig).filter(
                or_(
                    models.OLTConfig.nodo_asociado == cliente.nodo,
                    models.OLTConfig.nodo_asociado.ilike("%SAYAUS%") if is_sayausi_val else models.OLTConfig.nodo_asociado.ilike("%BAN%"),
                    models.OLTConfig.nodo_asociado == None
                ),
                models.OLTConfig.active == True
            ).first()
            
            if not olt_config:
                raise Exception(f"No hay OLT activa configurada para el nodo '{cliente.nodo}'.")
                
            olt = OLTInterface(
                host=olt_config.host,
                port=olt_config.port or 23,
                username=olt_config.username,
                password=olt_config.password
            )
            olt.connect()
            olt_payload = {
                "gpon_port": gpon_port,
                "ont_id": str(cliente.id_port).strip(),
                "service_port": str(cliente.service_port).strip(),
                "mac": str(cliente.mac or "000000000000").replace(":", "").replace("-", "")
            }
            res_olt = olt.execute_removal_sequence(olt_payload)
            olt.disconnect()
            
            if not res_olt.get("success", False):
                raise Exception(f"Fallo en la OLT: {res_olt.get('error', 'Error desconocido')}")
                
            estado_olt = "ELIMINADO"
            backup_rec.estado_olt = estado_olt
            db.commit()
            
        except Exception as olt_err:
            estado_olt = "ERROR"
            backup_rec.estado_olt = estado_olt
            backup_rec.detalles_error = f"Error en Etapa OLT: {str(olt_err)}"
            db.commit()
            raise HTTPException(
                status_code=500,
                detail={"stage": "olt", "message": f"Error al eliminar en la OLT: {str(olt_err)}"}
            )
            
    # ETAPA 2: MIKROTIK
    if cliente.mac:
        try:
            from network.adapters.mikrotik import MikroTikAdapter
            
            olt_config_mt = db.query(models.OLTConfig).filter(
                or_(
                    models.OLTConfig.nodo_asociado == cliente.nodo,
                    models.OLTConfig.nodo_asociado == None
                ),
                models.OLTConfig.active == True
            ).first()
            
            if olt_config_mt and olt_config_mt.mikrotik_host:
                mt = MikroTikAdapter(
                    host=olt_config_mt.mikrotik_host,
                    port=olt_config_mt.mikrotik_port or 8728,
                    username=olt_config_mt.mikrotik_username or "admin",
                    password=olt_config_mt.mikrotik_password or ""
                )
                mt.connect()
                
                clean_mac = str(cliente.mac).replace(":", "").replace("-", "").upper()
                resource = mt.api.get_resource('/ip/dhcp-server/lease')
                all_leases = resource.get()
                
                removed_count = 0
                for lease in all_leases:
                    lease_mac = lease.get('mac-address', '').replace(":", "").replace("-", "").upper()
                    if lease_mac == clean_mac:
                        lease_id = lease.get('.id') or lease.get('id')
                        if lease_id:
                            resource.remove(**{'.id': lease_id})
                            removed_count += 1
                
                if removed_count == 0 and cliente.ip:
                    for lease in all_leases:
                        if lease.get('address') == cliente.ip:
                            lease_id = lease.get('.id') or lease.get('id')
                            if lease_id:
                                resource.remove(**{'.id': lease_id})
                                removed_count += 1
                
                mt.disconnect()
                estado_mikrotik = "ELIMINADO" if removed_count > 0 else "OMITIDO"
            else:
                estado_mikrotik = "OMITIDO"
                
            backup_rec.estado_mikrotik = estado_mikrotik
            db.commit()
                
        except Exception as mt_err:
            estado_mikrotik = "ERROR"
            backup_rec.estado_mikrotik = estado_mikrotik
            backup_rec.detalles_error = (backup_rec.detalles_error or "") + f" | Error en Etapa MikroTik: {str(mt_err)}"
            db.commit()
            logger.warning(f"Error eliminando de MikroTik (cliente {id}): {mt_err}")

    # ETAPA 3: XUI / IPTV
    if cliente.iptv_user and str(cliente.iptv_user).strip():
        try:
            from services.xui_service import delete_xui_user
            res_xui = await delete_xui_user(cliente.iptv_user)
            
            if not res_xui.get("success", False):
                if "not found" in str(res_xui.get("detail", "")).lower():
                    estado_xui = "OMITIDO"
                else:
                    raise Exception(f"Fallo en panel XUI: {res_xui.get('detail', 'Error desconocido')}")
            else:
                estado_xui = "ELIMINADO"
                
            backup_rec.estado_xui = estado_xui
            db.commit()
            
        except Exception as xui_err:
            estado_xui = "ERROR"
            backup_rec.estado_xui = estado_xui
            backup_rec.detalles_error = (backup_rec.detalles_error or "") + f" | Error en Etapa XUI: {str(xui_err)}"
            db.commit()
            logger.warning(f"Error eliminando de XUI IPTV (cliente {id}): {xui_err}")

    # ETAPA 4: LIBREQOS
    try:
        from services.libreqos_manager import LibreQoSManager
        LibreQoSManager.enqueue_job(
            operation="REMOVE",
            cliente_id=id,
            db=db,
            correlation_id=f"del_client_{id}_{int(datetime.now().timestamp())}",
            created_by="CLIENT_DELETE_API"
        )
        estado_libreqos = "ELIMINADO"
        backup_rec.estado_libreqos = estado_libreqos
        db.commit()
    except Exception as lq_err:
        estado_libreqos = "ERROR"
        backup_rec.estado_libreqos = estado_libreqos
        backup_rec.detalles_error = f"Error en Etapa LibreQoS: {str(lq_err)}"
        db.commit()
        raise HTTPException(
            status_code=500,
            detail={"stage": "libreqos", "message": f"Error al encolar eliminación en LibreQoS: {str(lq_err)}"}
        )

    # ETAPA 5: BASE DE DATOS LOCAL
    try:
        for file_path in [cliente.cedula_frontal, cliente.cedula_posterior, cliente.foto_fachada]:
            if file_path:
                path_clean = file_path.lstrip("/")
                if os.path.exists(path_clean):
                    try: os.remove(path_clean)
                    except Exception: pass

        task_ids = [t.id for t in db.query(models.OLTTask).filter(models.OLTTask.cliente_id == id).all()]
        if task_ids:
            db.query(models.OLTTaskLog).filter(models.OLTTaskLog.task_id.in_(task_ids)).delete(synchronize_session=False)
            db.query(models.OLTTask).filter(models.OLTTask.id.in_(task_ids)).delete(synchronize_session=False)

        db.query(models.OLTPowerCheck).filter(models.OLTPowerCheck.cliente_id == id).delete()
        db.query(models.Pago).filter(models.Pago.cliente_id == id).delete()
        db.query(models.HojaRuta).filter(models.HojaRuta.cliente_id == id).delete()
        
        try:
            import inventory_models
            db.query(inventory_models.InventoryIpPool).filter(
                inventory_models.InventoryIpPool.cliente_id == id
            ).update({
                inventory_models.InventoryIpPool.estado: "LIBRE",
                inventory_models.InventoryIpPool.cliente_id: None,
                inventory_models.InventoryIpPool.updated_at: datetime.now()
            })
            db.query(inventory_models.InventoryServicePort).filter(
                inventory_models.InventoryServicePort.cliente_id == id
            ).update({
                inventory_models.InventoryServicePort.estado: "LIBRE",
                inventory_models.InventoryServicePort.cliente_id: None,
                inventory_models.InventoryServicePort.updated_at: datetime.now()
            })
            db.query(inventory_models.InventoryOntId).filter(
                inventory_models.InventoryOntId.cliente_id == id
            ).update({
                inventory_models.InventoryOntId.estado: "LIBRE",
                inventory_models.InventoryOntId.cliente_id: None,
                inventory_models.InventoryOntId.updated_at: datetime.now()
            })
        except Exception as inv_err:
            logger.warning(f"Aviso Inventario al eliminar: {inv_err}")

        try:
            from libreqos_models import ClientQoSState
            db.query(ClientQoSState).filter(ClientQoSState.cliente_id == id).delete()
        except Exception:
            pass

        try:
            from libreqos_models import LibreQoSJob
            db.query(LibreQoSJob).filter(LibreQoSJob.cliente_id == id).delete()
        except Exception:
            pass

        try:
            from libreqos_models import LibreQoSAuditLog
            db.query(LibreQoSAuditLog).filter(LibreQoSAuditLog.cliente_id == id).update({LibreQoSAuditLog.cliente_id: None})
        except Exception:
            pass

        try:
            from discovery_models import DiscoveredONT, DiscoveredServicePort
            db.query(DiscoveredONT).filter(DiscoveredONT.cliente_id == id).update({DiscoveredONT.cliente_id: None})
            db.query(DiscoveredServicePort).filter(DiscoveredServicePort.cliente_id == id).update({DiscoveredServicePort.cliente_id: None})
        except Exception:
            pass

        db.delete(cliente)
        backup_rec.estado_db = "ELIMINADO"
        db.commit()
        invalidate_stats_cache()
        
    except Exception as db_err:
        backup_rec.estado_db = "ERROR"
        backup_rec.detalles_error = f"Error en Etapa Base de Datos: {str(db_err)}"
        db.commit()
        raise HTTPException(
            status_code=500,
            detail={"stage": "database", "message": f"Error al eliminar registros locales: {str(db_err)}"}
        )

    return {
        "success": True,
        "olt": estado_olt,
        "mikrotik": estado_mikrotik,
        "xui": estado_xui,
        "libreqos": estado_libreqos,
        "database": "ELIMINADO"
    }
