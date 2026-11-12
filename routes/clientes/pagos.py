"""
@file pagos.py
@description Gestión de pagos, confirmaciones, anulaciones, facturación mensual global y cierre de mes.
"""
import math
import logging
import traceback
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

import models
import schemas
from database import get_db
from routes.auth import require_role
from config_manager import get_config, save_config
from .utils import (
    try_float,
    sync_cliente_balances,
    verificar_y_reactivar_cliente_por_pago_completo,
    invalidate_stats_cache
)

logger = logging.getLogger("opsatel.routes.clientes.pagos")

router = APIRouter()

def procesar_facturacion_global(db: Session):
    clientes = db.query(models.Cliente).all()
    # Congelar cuentas en PROCESO, JURIDICO, INACTIVO y FINIQUITO (omitir de la facturación mensual masiva)
    clientes_facturables = [
        c for c in clientes 
        if c.estado and c.estado.strip().upper() not in ["PROCESO", "EN PROCESO", "JURIDICO", "INACTIVO", "FINIQUITO"]
    ]
    
    count = 0
    for cliente in clientes_facturables:
        # 1. Recargo mensual de IPTV PLUS ($2 por pantalla adicional contratada)
        plan_info = db.query(models.PlanInternet).filter(models.PlanInternet.nombre == cliente.plan).first()
        base_screens = (plan_info.pantallas if plan_info.pantallas is not None else 0) if plan_info else 0
        
        cargo_plus = 0.0
        if (cliente.iptv_max_conn or 0) > base_screens:
            cargo_plus = float((cliente.iptv_max_conn - base_screens) * 2)
            
        if getattr(cliente, 'cortesia_total', False):
            cliente.plus = "0"
        else:
            cliente.plus = str(cargo_plus) if cargo_plus > 0 else ""
            
        # 2. La tarifa de internet se agrega al saldo directamente
        tarifa = 0.00
        if getattr(cliente, 'mantenimiento', False):
            tarifa = 10.00
        elif getattr(cliente, 'precio_plan_especial', None) is not None and float(cliente.precio_plan_especial or 0) > 0:
            tarifa = float(cliente.precio_plan_especial)
        elif plan_info:
            tarifa = float(plan_info.precio or 0)
        elif cliente.plan:
            import re as _re_tarifa
            m_tarifa = _re_tarifa.search(r'\$?(\d+(?:[\.,]\d{1,2})?)', str(cliente.plan))
            if m_tarifa:
                try:
                    tarifa = float(m_tarifa.group(1).replace(',', '.'))
                except ValueError:
                    pass
            
        cliente.saldo = float(cliente.saldo or 0) + tarifa
        
        # 3. Reiniciar campos mensuales para la vista General
        cliente.facturas = ""
        cliente.payment_date = ""
        cliente.bank = ""
        cliente.cod = ""
        cliente.bank_plus = ""
        cliente.internet_payment = ""
        cliente.pago_mensual = 0.00
        cliente.plus_pagado = 0.00
        cliente.adicional_pagado = 0.00
        
        # 4. Sincronizar balances
        sync_cliente_balances(cliente, db)
        count += 1
        
    db.commit()
    return count


@router.post("/facturacion-mensual-global")
def ejecutar_facturacion_mensual(
    db: Session = Depends(get_db), 
    current_user: models.Usuario = Depends(require_role(["administrador"]))
):
    now_utc = datetime.utcnow()
    current_month = now_utc.strftime("%Y-%m")
    
    last_log = db.query(models.LogFacturacion).order_by(models.LogFacturacion.fecha_ejecucion.desc()).first()
    if last_log and last_log.fecha_ejecucion:
        elapsed = (now_utc - last_log.fecha_ejecucion).total_seconds()
        if elapsed < 60:
            remaining = int(60 - elapsed)
            raise HTTPException(
                status_code=400, 
                detail=f"Modo de prueba: Debe esperar {remaining} segundos antes de ejecutar la facturación nuevamente (límite: 1 por minuto)."
            )

    periodo_key = now_utc.strftime("%Y-%m-%d %H:%M:%S")
    log_fact = models.LogFacturacion(
        periodo_mes=periodo_key,
        fecha_ejecucion=now_utc,
        estado="Procesando",
        usuario_id=current_user.id
    )
    db.add(log_fact)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400, 
            detail="Error al iniciar la facturación. Intente nuevamente en unos segundos."
        )
        
    try:
        count = procesar_facturacion_global(db)
        log_fact.estado = "Completado"
        save_config({"ultima_facturacion": current_month})
        db.commit()
        invalidate_stats_cache()
        return {"message": f"Facturación procesada para {count} clientes exitosamente."}
    except Exception as e:
        db.rollback()
        db.query(models.LogFacturacion).filter(models.LogFacturacion.periodo_mes == periodo_key).delete()
        db.commit()
        logger.error(f"Error en facturación: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error en facturación: {str(e)}")


@router.post("/cierre-mensual-global", dependencies=[Depends(require_role(["administrador"]))])
def ejecutar_cierre_mensual(db: Session = Depends(get_db)):
    config_sys = get_config()
    current_month = datetime.now().strftime("%Y-%m")
    
    if config_sys.get("ultimo_cierre") == current_month:
        raise HTTPException(status_code=400, detail="El cierre de este mes ya fue realizado.")
        
    clientes = db.query(models.Cliente).all()
    count = 0
    for cliente in clientes:
        if cliente.estado and cliente.estado.strip().upper() == "FINIQUITO":
            continue
        cliente.pago_mensual = 0.00
        cliente.plus_pagado = 0.00
        cliente.adicional_pagado = 0.00
        count += 1
        
    save_config({"ultimo_cierre": current_month})
    db.commit()
    invalidate_stats_cache()
    return {"message": f"Cierre de mes completado para {count} clientes. Ahora puede ejecutar la Facturación Mensual."}


@router.post("/pago-global-test")
def liquidar_todas_las_deudas(db: Session = Depends(get_db)):
    clientes = db.query(models.Cliente).filter(models.Cliente.saldo > 0).all()
    count = 0
    for cliente in clientes:
        cliente.saldo = 0.00
        count += 1
    db.commit()
    invalidate_stats_cache()
    return {"message": f"Deudas liquidadas para {count} clientes (TEST)."}


@router.get("/pagos/historial")
def listar_pagos(db: Session = Depends(get_db)):
    """Retorna un listado de pagos enriquecido con el excedente / saldo a favor del cliente."""
    pagos = db.query(models.Pago).order_by(models.Pago.fecha_pago.desc()).all()
    result = []
    for pago in pagos:
        cliente = db.query(models.Cliente).filter(models.Cliente.id == pago.cliente_id).first()
        excedente = 0.0
        if cliente and float(cliente.saldo or 0) < 0:
            excedente = abs(float(cliente.saldo))
        pago_dict = {
            "id": pago.id,
            "cliente_id": pago.cliente_id,
            "monto": float(pago.monto or 0),
            "metodo_pago": pago.metodo_pago,
            "fecha_pago": pago.fecha_pago,
            "excedente": round(excedente, 2),
        }
        result.append(pago_dict)
    return result


@router.get("/{id}/pagos")
def obtener_pagos_cliente(id: int, db: Session = Depends(get_db)):
    """Retorna el historial de pagos de un cliente específico enriquecido con su excedente."""
    pagos = db.query(models.Pago).filter(models.Pago.cliente_id == id).order_by(models.Pago.fecha_pago.desc()).all()
    result = []
    for pago in pagos:
        cliente = db.query(models.Cliente).filter(models.Cliente.id == pago.cliente_id).first()
        excedente = 0.0
        if cliente and float(cliente.saldo or 0) < 0:
            excedente = abs(float(cliente.saldo))
        result.append({
            "id": pago.id,
            "cliente_id": pago.cliente_id,
            "monto": float(pago.monto or 0),
            "metodo_pago": pago.metodo_pago,
            "fecha_pago": pago.fecha_pago,
            "excedente": round(excedente, 2),
        })
    return result


@router.post("/{id}/pagar")
def registrar_pago(
    id: int, 
    pago_data: schemas.PagoCreate, 
    db: Session = Depends(get_db), 
    current_user: models.Usuario = Depends(require_role(["administrador", "secretario"]))
):
    try:
        cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
        if not cliente:
            raise HTTPException(status_code=404, detail="Cliente no encontrado")

        turno = db.query(models.TurnoCaja).filter(
            models.TurnoCaja.usuario_id == current_user.id,
            models.TurnoCaja.estado == "Abierto"
        ).first()
        turno_id = turno.id if turno else None

        m_total_cash = float(pago_data.monto or 0)
        if m_total_cash < 0:
            raise HTTPException(status_code=400, detail="El monto total de pago no puede ser negativo")

        m_adic_cash = max(0.0, try_float(pago_data.adicional))
        m_plus_cash = max(0.0, try_float(pago_data.plus))

        componentes_cash = m_plus_cash + m_adic_cash
        if componentes_cash > m_total_cash + 0.01:
            raise HTTPException(
                status_code=400,
                detail="La suma de Plus y Adicional no puede superar el monto total recibido"
            )
        m_internet_cash = round(max(0.0, m_total_cash - componentes_cash), 2)

        if math.isnan(m_total_cash) or math.isnan(m_internet_cash) or math.isnan(m_plus_cash) or math.isnan(m_adic_cash):
            raise HTTPException(status_code=400, detail="Monto inválido (NaN)")

        deuda_internet = m_internet_cash + (pago_data.descuento_internet or 0.0)
        deuda_plus = m_plus_cash + (pago_data.descuento_plus or 0.0)
        deuda_adicional = m_adic_cash + (pago_data.descuento_adicional or 0.0)

        nuevo_pago = models.Pago(
            cliente_id=id,
            monto=m_total_cash,
            metodo_pago=pago_data.metodo_pago,
            mes_correspondiente=pago_data.mes_correspondiente,
            referencia=pago_data.referencia,
            monto_internet=m_internet_cash,
            monto_plus=m_plus_cash,
            monto_adicional=m_adic_cash,
            estado=pago_data.estado or "Completado",
            turnocaja_id=turno_id
        )
        db.add(nuevo_pago)

        if nuevo_pago.estado == "Pendiente_Verificacion":
            db.commit()
            invalidate_stats_cache()
            return {
                "message": "Pago registrado y pendiente de verificación bancaria. El saldo del cliente no se actualizará hasta que la transferencia sea confirmada.",
                "nuevo_saldo": float(cliente.saldo or 0),
                "saldo_internet": float(cliente.saldo or 0),
                "saldo_plus": round(try_float(cliente.plus), 2),
                "saldo_adicional": round(try_float(cliente.adicional), 2),
                "saldo_extras": round(try_float(cliente.plus) + try_float(cliente.adicional), 2)
            }

        # 1. ACTUALIZAR ADICIONAL
        if deuda_adicional > 0:
            curr_adic = try_float(cliente.adicional)
            cliente.adicional = str(max(0, curr_adic - deuda_adicional))
            if m_adic_cash > 0:
                cliente.adicional_pagado = float(cliente.adicional_pagado or 0) + m_adic_cash
            if cliente.adicional == "0.0": cliente.adicional = ""

        # 2. ACTUALIZAR PLUS (IPTV)
        if deuda_plus > 0:
            curr_plus = try_float(cliente.plus)
            cliente.plus = str(max(0, curr_plus - deuda_plus))
            if m_plus_cash > 0:
                cliente.plus_pagado = float(cliente.plus_pagado or 0) + m_plus_cash
            if cliente.plus == "0.0": cliente.plus = ""

        # 3. ACTUALIZAR SALDO PRINCIPAL
        cliente.saldo = float(cliente.saldo or 0) - deuda_internet
        cliente.pago_mensual = float(cliente.pago_mensual or 0) + m_total_cash

        if pago_data.facturas is not None: cliente.facturas = pago_data.facturas
        if pago_data.app is not None: cliente.app = pago_data.app
        if pago_data.payment_date is not None and not str(cliente.payment_date or "").strip():
            cliente.payment_date = pago_data.payment_date
        if pago_data.bank is not None: cliente.bank = pago_data.bank
        if pago_data.cod is not None:
            cliente.cod = pago_data.cod
            if str(pago_data.cod).strip() != "" and pago_data.facturas is None:
                cliente.facturas = "SI"
        if pago_data.bank_plus is not None: cliente.bank_plus = pago_data.bank_plus
        if pago_data.notas_pago is not None: cliente.notas_pago = pago_data.notas_pago

        # 4. GUARDAR INTERNET PAYMENT
        new_net_str = str(pago_data.internet_payment or "").strip()
        if new_net_str not in ["", "NONE", "0", "0.0", "0.00"]:
            val_net = try_float(new_net_str)
            if val_net > 0:
                prev_internet = try_float(cliente.internet_payment)
                if prev_internet > 0 and val_net != prev_internet:
                    cliente.internet_payment = str(round(prev_internet + val_net, 2))
                else:
                    cliente.internet_payment = str(round(val_net, 2))
        elif m_internet_cash > 0:
            prev_internet = try_float(cliente.internet_payment)
            cliente.internet_payment = str(round(prev_internet + m_internet_cash, 2))

        sync_cliente_balances(cliente, db)

        # 5. Reactivación automática si saldó en ceros
        reactivacion_info = verificar_y_reactivar_cliente_por_pago_completo(cliente, db, motivo="REGISTRO_PAGO")

        db.commit()
        invalidate_stats_cache()

        nuevo_saldo = float(cliente.saldo or 0)
        remaining_plus = round(try_float(cliente.plus), 2)
        remaining_adicional = round(try_float(cliente.adicional), 2)
        remaining_internet = round(max(0, nuevo_saldo), 2)
        response = {
            "message": f"Pago registrado. Saldo pendiente: ${nuevo_saldo:.2f}",
            "nuevo_saldo": nuevo_saldo,
            "saldo_internet": remaining_internet,
            "saldo_plus": remaining_plus,
            "saldo_adicional": remaining_adicional,
            "saldo_extras": round(remaining_plus + remaining_adicional, 2),
        }
        if reactivacion_info.get("reactivado"):
            response["reactivado_firewall"] = True
            response["message"] = f"Pago registrado. Deuda en ceros y servicio reactivado en firewall/MikroTik."
        elif nuevo_saldo < 0:
            response["message"] = f"Pago registrado. Excedente: ${abs(nuevo_saldo):.2f}"
        return response
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error al registrar pago: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error al registrar pago: {str(e)}")


@router.post("/{id}/pagos/{pago_id}/confirmar")
def confirmar_pago(
    id: int, 
    pago_id: int, 
    db: Session = Depends(get_db), 
    current_user: models.Usuario = Depends(require_role(["administrador", "secretario"]))
):
    pago = db.query(models.Pago).filter(models.Pago.id == pago_id, models.Pago.cliente_id == id).first()
    if not pago:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    if pago.estado != "Pendiente_Verificacion":
        raise HTTPException(status_code=400, detail="El pago ya está confirmado o anulado.")
    if pago.anulado:
        raise HTTPException(status_code=400, detail="No se puede confirmar un pago anulado.")
        
    cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
        
    deuda_internet = float(pago.monto_internet or 0)
    deuda_plus = float(pago.monto_plus or 0)
    deuda_adicional = float(pago.monto_adicional or 0)
    
    if deuda_adicional > 0:
        curr_adic = try_float(cliente.adicional)
        cliente.adicional = str(max(0, curr_adic - deuda_adicional))
        cliente.adicional_pagado = float(cliente.adicional_pagado or 0) + float(pago.monto_adicional)
        if cliente.adicional == "0.0": cliente.adicional = ""
        
    if deuda_plus > 0:
        curr_plus = try_float(cliente.plus)
        cliente.plus = str(max(0, curr_plus - deuda_plus))
        cliente.plus_pagado = float(cliente.plus_pagado or 0) + float(pago.monto_plus)
        if cliente.plus == "0.0": cliente.plus = ""
        
    cliente.saldo = float(cliente.saldo or 0) - deuda_internet
    cliente.pago_mensual = float(cliente.pago_mensual or 0) + float(pago.monto)
    
    pago.estado = "Completado"
    
    sync_cliente_balances(cliente, db)
    verificar_y_reactivar_cliente_por_pago_completo(cliente, db, motivo="CONFIRMAR_PAGO")
    db.commit()
    invalidate_stats_cache()
    
    return {"message": "Pago confirmado exitosamente. Balances de cliente actualizados."}


@router.post("/{id}/pagos/{pago_id}/anular")
def anular_pago(
    id: int, 
    pago_id: int, 
    request_data: schemas.PagoAnularRequest, 
    db: Session = Depends(get_db), 
    current_user: models.Usuario = Depends(require_role(["administrador", "secretario"]))
):
    try:
        pago = db.query(models.Pago).filter(models.Pago.id == pago_id, models.Pago.cliente_id == id).first()
        if not pago:
            raise HTTPException(status_code=404, detail="Pago no encontrado")
        if pago.anulado:
            raise HTTPException(status_code=400, detail="Este pago ya se encuentra anulado.")
            
        cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
        if not cliente:
            raise HTTPException(status_code=404, detail="Cliente no encontrado")
            
        if pago.estado == "Completado":
            deuda_internet = float(pago.monto_internet or 0)
            deuda_plus = float(pago.monto_plus or 0)
            deuda_adicional = float(pago.monto_adicional or 0)
            
            if deuda_adicional > 0:
                curr_adic = try_float(cliente.adicional)
                cliente.adicional = str(curr_adic + deuda_adicional)
                cliente.adicional_pagado = max(0.0, float(cliente.adicional_pagado or 0) - float(pago.monto_adicional))
                
            if deuda_plus > 0:
                curr_plus = try_float(cliente.plus)
                cliente.plus = str(curr_plus + deuda_plus)
                cliente.plus_pagado = max(0.0, float(cliente.plus_pagado or 0) - float(pago.monto_plus))
                
            cliente.saldo = float(cliente.saldo or 0) + deuda_internet
            cliente.pago_mensual = max(0.0, float(cliente.pago_mensual or 0) - float(pago.monto))
            
        pago.anulado = True
        pago.fecha_anulacion = datetime.utcnow()
        pago.anulado_por = current_user.username
        pago.motivo_anulacion = request_data.motivo_anulacion
        
        sync_cliente_balances(cliente, db)
        db.commit()
        invalidate_stats_cache()
        
        return {"message": "Pago anulado exitosamente. Balances revertidos contablemente."}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error al anular pago: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error al procesar pago: {str(e)}")
