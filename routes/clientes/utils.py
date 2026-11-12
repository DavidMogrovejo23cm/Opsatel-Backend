"""
@file utils.py
@description Utilidades, formateo y reglas de balance/reactivación para el módulo de clientes.
"""
import unicodedata
import calendar
import logging
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
import models

logger = logging.getLogger("opsatel.routes.clientes.utils")

# Precios de respaldo históricos en caso de no encontrarse en la tabla PlanInternet
PLAN_PRICES = {
    "100mb": 17.25,
    "100M/100M": 17.25,
    "600mb": 17.87,
    "600M/600M": 17.87,
    "700mb": 21.73,
    "800mb": 32.20,
    "800M/800M": 32.20,
    "650M/650M": 20.00
}

_stats_cache = None
_stats_cache_time = None

def get_stats_cache():
    global _stats_cache, _stats_cache_time
    now = datetime.now()
    if _stats_cache is not None and _stats_cache_time is not None and (now - _stats_cache_time).total_seconds() < 300:
        return _stats_cache
    return None

def set_stats_cache(stats: dict):
    global _stats_cache, _stats_cache_time
    _stats_cache = stats
    _stats_cache_time = datetime.now()

def invalidate_stats_cache():
    global _stats_cache, _stats_cache_time
    _stats_cache = None
    _stats_cache_time = None

def is_nodo_sayausi(nodo_val) -> bool:
    if not nodo_val:
        return False
    s = unicodedata.normalize('NFD', str(nodo_val)).encode('ascii', 'ignore').decode('utf-8').upper()
    return "SAYAUSI" in s

def try_float(val) -> float:
    try:
        clean_val = str(val or 0).replace('$', '').replace(',', '.').strip()
        return float(clean_val) if clean_val else 0.0
    except Exception:
        return 0.0

def clean_int_string_value(val):
    if val is None:
        return ""
    if isinstance(val, (int, float)):
        if isinstance(val, float) and val.is_integer():
            return str(int(val))
        elif isinstance(val, int):
            return str(val)
        else:
            return str(val)
    s_val = str(val).strip()
    if s_val.endswith('.0'):
        try:
            f_val = float(s_val)
            if f_val.is_integer():
                return str(int(f_val))
        except Exception:
            pass
    return s_val

def sync_cliente_balances(cliente: models.Cliente, db: Session = None, keep_total_pago: bool = False):
    if getattr(cliente, 'cortesia_total', False):
        cliente.total_pago = 0.00
        cliente.saldo = 0.00
        cliente.plus = "0"
        cliente.adicional = ""
        return

    if keep_total_pago and cliente.total_pago is not None:
        return

    plus = try_float(cliente.plus)
    saldo = float(cliente.saldo or 0)
    adicional = try_float(cliente.adicional)
    
    # PENDIENTE (total_pago) es la suma de TODAS las deudas pendientes (Internet + IPTV Plus + Adicional)
    # Permite valores negativos si el cliente cuenta con saldo a favor / excedente global
    cliente.total_pago = round(saldo + plus + adicional, 2)

def auto_fix_initial_balances(db: Session):
    """
    Verifica si existen clientes en estado 'En Activación' o 'Pendiente'
    recién ingresados sin saldo inicial asignado (saldo=0 y total_pago=0),
    y calcula automáticamente su monto a pagar del primer mes según su plan y fecha de firma.
    """
    try:
        sin_saldo = db.query(models.Cliente).filter(
            models.Cliente.estado.in_(["En Activación", "Pendiente"]),
            (models.Cliente.saldo == None) | (models.Cliente.saldo == 0),
            (models.Cliente.total_pago == None) | (models.Cliente.total_pago == 0)
        ).all()
        has_changes = False
        for c in sin_saldo:
            tarifa = 0.0
            if getattr(c, 'mantenimiento', False):
                tarifa = 10.0
            elif (getattr(c, 'tercera_edad', False) or getattr(c, 'plan_corporativo', False)) and c.precio_plan_especial:
                tarifa = float(c.precio_plan_especial)
            elif c.precio_plan_especial and float(c.precio_plan_especial) > 0:
                tarifa = float(c.precio_plan_especial)
            elif c.plan:
                plan_info = db.query(models.PlanInternet).filter(models.PlanInternet.nombre == c.plan).first()
                if not plan_info:
                    plan_info = db.query(models.PlanInternet).filter(models.PlanInternet.nombre.ilike(c.plan)).first()
                if plan_info and plan_info.precio is not None:
                    tarifa = float(plan_info.precio)
                else:
                    tarifa = float(PLAN_PRICES.get(c.plan, 0.0))
                    if tarifa == 0.0:
                        import re as _re
                        match_precio = _re.search(r'\$?(\d+(?:[\.,]\d{1,2})?)', str(c.plan))
                        if match_precio:
                            try:
                                tarifa = float(match_precio.group(1).replace(',', '.'))
                            except ValueError:
                                pass
            if tarifa > 0:
                saldo_calc = tarifa
                try:
                    f_str = (c.fecha_firma or "").strip().split(" ")[0].split("T")[0]
                    if f_str and "-" in f_str:
                        parts = f_str.split("-")
                        f_year, f_month, f_day = int(parts[0]), int(parts[1]), int(parts[2])
                    else:
                        now = datetime.now()
                        f_year, f_month, f_day = now.year, now.month, now.day
                    _, total_days = calendar.monthrange(f_year, f_month)
                    active_days = (total_days - f_day) + 1
                    if total_days > 0 and active_days > 0:
                        saldo_calc = round((tarifa / total_days) * active_days, 2)
                except Exception:
                    saldo_calc = round(tarifa, 2)
                c.saldo = saldo_calc
                sync_cliente_balances(c, db)
                has_changes = True
        if has_changes:
            db.commit()
    except Exception as e:
        logger.error(f"Error en auto_fix_initial_balances: {e}")

def clean_existing_database_formats(db: Session):
    try:
        clients = db.query(models.Cliente).all()
        fixed_count = 0
        for c in clients:
            changed = False
            
            # Campos a limpiar de terminaciones .0
            fields_to_clean = ["puerto", "id_port", "service_port", "tiempo", "cod", "nap"]
            for field in fields_to_clean:
                old_val = getattr(c, field)
                if old_val is not None:
                    new_val = clean_int_string_value(old_val)
                    if new_val != old_val:
                        setattr(c, field, new_val)
                        changed = True
            
            # Lógica especial para cédula (agregar cero a la izquierda si tiene 9 dígitos)
            if c.cedula is not None:
                old_ced = getattr(c, "cedula")
                clean_ced = clean_int_string_value(old_ced)
                if clean_ced and clean_ced.isdigit() and len(clean_ced) == 9:
                    clean_ced = "0" + clean_ced
                if clean_ced != old_ced:
                    c.cedula = clean_ced
                    changed = True
            
            # Lógica especial para celular (agregar cero a la izquierda si tiene 9 dígitos empezando por 9)
            if c.celular is not None:
                old_cel = getattr(c, "celular")
                clean_cel = clean_int_string_value(old_cel)
                if clean_cel and clean_cel.isdigit() and len(clean_cel) == 9 and clean_cel.startswith("9"):
                    clean_cel = "0" + clean_cel
                if clean_cel != old_cel:
                    c.celular = clean_cel
                    changed = True
                    
            if changed:
                fixed_count += 1
                
        if fixed_count > 0:
            db.commit()
            print(f"AUTOMIGRACIÓN: Se corrigieron {fixed_count} clientes con formatos inconsistentes de Excel (.0 o ceros a la izquierda).")
        auto_fix_initial_balances(db)
    except Exception as e:
        db.rollback()
        logger.error(f"Error en AUTOMIGRACIÓN de formatos de clientes: {e}")

def verificar_y_reactivar_cliente_por_pago_completo(cliente: models.Cliente, db: Session, motivo: str = "PAGO_COMPLETO") -> dict:
    """
    Regla de negocio crítica:
    Siempre que se pague el servicio de un cliente por completo (quede en ceros o con saldo a favor):
    - Revisa si está cortado por corte del firewall en MikroTik (o si su estado en BD no es 'Activo').
    - Si está cortado en firewall o no está activo, lo reactiva removiéndolo de la lista de corte y pasa a estado 'Activo'.
    - OJO: Solo y exclusivamente cuando se cancele TODO (saldo <= 0, plus <= 0, adicional <= 0, total_pago <= 0).
    """
    if not cliente:
        return {"reactivado": False, "motivo": "CLIENTE_INVALIDO"}

    saldo_val = float(cliente.saldo or 0)
    plus_val = try_float(cliente.plus)
    adic_val = try_float(cliente.adicional)
    total_pago_val = float(cliente.total_pago or 0) if cliente.total_pago is not None else (saldo_val + plus_val + adic_val)

    deuda_total = max(0.0, saldo_val) + max(0.0, plus_val) + max(0.0, adic_val)

    if deuda_total > 0.001 or total_pago_val > 0.001:
        logger.info(f"[AutoReactivar] Cliente {cliente.id} ({cliente.nombre}) mantiene deuda (${deuda_total:.2f}). No se reactiva firewall.")
        return {"reactivado": False, "motivo": "DEUDA_PENDIENTE", "deuda_total": deuda_total}

    from network.adapters.mikrotik import (
        reactivar_cliente_mikrotik_backend,
        esta_cliente_cortado_en_firewall
    )

    estado_actual = str(cliente.estado or "").strip()
    no_esta_activo = estado_actual.upper() != "ACTIVO"
    cortado_en_firewall = False

    try:
        cortado_en_firewall = esta_cliente_cortado_en_firewall(cliente, db)
    except Exception as e:
        logger.warning(f"[AutoReactivar] Aviso al consultar corte de firewall para cliente {cliente.id}: {e}")

    if cortado_en_firewall or no_esta_activo:
        logger.info(f"[AutoReactivar] Cliente {cliente.id} ({cliente.nombre}) canceló todo (en ceros). Procediendo a reactivar servicio...")

        # 1. Remover de listas de corte de firewall MikroTik
        res_mt = {"success": True}
        if cliente.ip:
            try:
                res_mt = reactivar_cliente_mikrotik_backend(cliente, db)
                logger.info(f"[AutoReactivar] Resultado MikroTik para {cliente.nombre} ({cliente.ip}): {res_mt}")
            except Exception as mt_err:
                logger.error(f"[AutoReactivar] Error MikroTik reactivando cliente {cliente.id}: {mt_err}")
                res_mt = {"success": False, "error": str(mt_err)}

        # 2. Activar si no está activo
        if no_esta_activo:
            cliente.estado = "Activo"
            if not cliente.activador or str(cliente.activador).strip() == "":
                cliente.activador = "sistema"

        # 3. Auditoría
        try:
            import observability as obs
            obs.log_audit_event_async(
                accion="REACTIVACION_FIREWALL_PAGO_COMPLETO",
                modulo="clientes",
                usuario="sistema",
                entidad_tipo="Cliente",
                entidad_id=str(cliente.id),
                detalles=f"Cliente {cliente.nombre} (IP: {cliente.ip}) canceló su servicio por completo (en ceros). Reactivado de firewall y pasado a Activo ({motivo})."
            )
        except Exception as obs_err:
            logger.warning(f"[AutoReactivar] Aviso registrando auditoría: {obs_err}")

        return {
            "reactivado": True,
            "cortado_previo_firewall": cortado_en_firewall,
            "estado_previo": estado_actual,
            "nuevo_estado": cliente.estado,
            "mikrotik": res_mt
        }
    else:
        if cliente.ip:
            try:
                reactivar_cliente_mikrotik_backend(cliente, db)
            except Exception:
                pass
        return {"reactivado": False, "motivo": "YA_ACTIVO_SIN_CORTE"}
