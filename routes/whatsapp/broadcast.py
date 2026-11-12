import time
import random
import re
import traceback
import requests
from datetime import datetime
from typing import Optional, List, Dict, Union, Any
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import or_, func

import models
import schemas
import whatsapp_service
from database import get_db, SessionLocal, engine
from ..auth import require_role
from .utils import (
    ECUADOR_TZ,
    personalizar_mensaje_cliente,
    remove_accents,
    registrar_mensaje_chat,
    matches_puerto,
    extract_port_number,
    CANCELLED_DIFUSIONES
)
from . import utils

router = APIRouter()


def send_global_broadcast_task(
    mensaje: str,
    nodo: Optional[str],
    db_session_factory,
    estado: Optional[str] = "ACTIVO",
    delay_min: float = 25.0,
    delay_max: float = 45.0,
    batch_size: int = 10,
    batch_pause_min: float = 180.0,
    batch_pause_max: float = 300.0,
    desde_id: Optional[int] = None,
    hasta_id: Optional[int] = None,
    limite_mensajes: Optional[int] = None,
    difusion_id: Optional[int] = None,
    puertos: Optional[List[str]] = None
):
    db = db_session_factory()
    try:
        models.Base.metadata.create_all(bind=engine, tables=[models.WhatsAppDifusionHistorial.__table__], checkfirst=True)
    except Exception:
        pass

    difusion_registro = None
    try:
        # Base query: clientes con celular registrado
        query = db.query(models.Cliente).filter(
            models.Cliente.celular != None,
            models.Cliente.celular != ""
        )

        # Filtro de Estado del cliente
        estado_clean = (estado or "ACTIVO").strip().upper()
        if estado_clean not in ["TODOS", "ALL", "TODOS LOS ESTADOS", "*"]:
            if estado_clean in ["ACTIVO", "ACTIVA"]:
                query = query.filter(func.upper(models.Cliente.estado).in_(["ACTIVO", "ACTIVA"]))
                estado_label = "Clientes Activos"
            elif estado_clean in ["INACTIVO", "INACTIVA"]:
                query = query.filter(func.upper(models.Cliente.estado).in_(["INACTIVO", "INACTIVA"]))
                estado_label = "Clientes Inactivos"
            elif estado_clean in ["SUSPENDIDO", "SUSPENDIDA"]:
                query = query.filter(func.upper(models.Cliente.estado).in_(["SUSPENDIDO", "SUSPENDIDA"]))
                estado_label = "Clientes Suspendidos"
            elif estado_clean in ["PROCESO", "EN PROCESO"]:
                query = query.filter(func.upper(models.Cliente.estado).in_(["PROCESO", "EN PROCESO"]))
                estado_label = "Clientes En Proceso"
            elif estado_clean in ["JURIDICO", "JURÍDICO"]:
                query = query.filter(func.upper(models.Cliente.estado).in_(["JURIDICO", "JURÍDICO"]))
                estado_label = "Clientes en Jurídico"
            elif estado_clean in ["PENDIENTE", "EN ACTIVACION", "EN ACTIVACIÓN"]:
                query = query.filter(func.upper(models.Cliente.estado).in_(["PENDIENTE", "EN ACTIVACIÓN", "EN ACTIVACION"]))
                estado_label = "Clientes Pendientes / En Activación"
            elif estado_clean == "FINIQUITO":
                query = query.filter(func.upper(models.Cliente.estado).in_(["FINIQUITO"]))
                estado_label = "Clientes Finiquito"
            elif estado_clean in ["CORTESIA", "CORTESÍA"]:
                query = query.filter(func.upper(models.Cliente.estado).in_(["CORTESIA", "CORTESÍA"]))
                estado_label = "Clientes Cortesía"
            elif estado_clean == "TRASLADO":
                query = query.filter(func.upper(models.Cliente.estado).in_(["TRASLADO"]))
                estado_label = "Clientes Traslado"
            else:
                query = query.filter(func.upper(models.Cliente.estado) == estado_clean)
                estado_label = f"Estado: {estado_clean}"
        else:
            estado_label = "Todos los estados"

        # Filtro de Nodo / Parroquia
        nodo_clean = nodo.strip() if nodo and str(nodo).strip() and str(nodo).lower() not in ["todos", "all", "todos los nodos"] else None
        if nodo_clean:
            clean_nodo_norm = remove_accents(nodo_clean)
            query = query.filter(
                or_(
                    models.Cliente.nodo.ilike(f"%{clean_nodo_norm}%"),
                    models.Cliente.parroquia.ilike(f"%{clean_nodo_norm}%")
                )
            )
            nodo_label = f"Nodo: {nodo_clean}"
        else:
            nodo_label = "Todos los nodos"

        # Filtro de Puertos
        puertos_clean = [str(p).strip() for p in puertos if str(p).strip()] if puertos else []
        if puertos_clean:
            puerto_conds = []
            for p in puertos_clean:
                p_str = str(p).strip()
                puerto_conds.append(models.Cliente.puerto.ilike(f"%{p_str}%"))
                p_num = extract_port_number(p_str)
                if p_num:
                    puerto_conds.append(models.Cliente.puerto == p_num)
                    puerto_conds.append(models.Cliente.puerto.ilike(f"%puerto {p_num}%"))
                    puerto_conds.append(models.Cliente.puerto.ilike(f"%/{p_num}"))
                    puerto_conds.append(models.Cliente.puerto.ilike(f"%/{p_num}/%"))
            if puerto_conds:
                query = query.filter(or_(*puerto_conds))

        # Filtro por ID inicial (Continuar desde ID X)
        if desde_id is not None and int(desde_id) > 0:
            query = query.filter(models.Cliente.id >= int(desde_id))
        if hasta_id is not None and int(hasta_id) > 0:
            query = query.filter(models.Cliente.id <= int(hasta_id))

        query = query.order_by(models.Cliente.id.asc())

        if limite_mensajes is not None and int(limite_mensajes) > 0:
            query = query.limit(int(limite_mensajes))
        
        clientes = query.all()

        rango_info = ""
        if desde_id and int(desde_id) > 0:
            rango_info += f" desde ID {desde_id}"
        if hasta_id and int(hasta_id) > 0:
            rango_info += f" hasta ID {hasta_id}"
        if limite_mensajes and int(limite_mensajes) > 0:
            rango_info += f" [Límite: {limite_mensajes}]"

        puertos_info = f" | Puertos: {', '.join([p if 'puerto' in str(p).lower() else f'Puerto {p}' for p in puertos_clean])}" if puertos_clean else ""
        alcance_label = f"{estado_label} ({nodo_label}{puertos_info}){rango_info}".strip()
        # Parámetros de pausas y lotes
        delay_a = float(delay_min) if delay_min and float(delay_min) >= 1.0 else 25.0
        delay_b = float(delay_max) if delay_max and float(delay_max) >= delay_a else max(delay_a, 45.0)
        tamano_lote = int(batch_size) if batch_size and int(batch_size) > 0 else 10
        pausa_lote_a = float(batch_pause_min) if batch_pause_min and float(batch_pause_min) >= 1.0 else 180.0
        pausa_lote_b = float(batch_pause_max) if batch_pause_max and float(batch_pause_max) >= pausa_lote_a else max(pausa_lote_a, 300.0)

        # Deduplicar clientes para garantizar que nunca se envíe doble vez al mismo cliente:
        clientes_unicos = []
        seen_ids = set()
        seen_cedulas = set()
        seen_numeros = set()

        for c in clientes:
            if not c or not c.celular:
                continue
            if c.id in seen_ids:
                continue
            if puertos_clean and not matches_puerto(c.puerto, puertos_clean):
                continue

            num_principal = whatsapp_service.format_whatsapp_number(c.celular)
            if not num_principal:
                continue

            ced_clean = str(c.cedula or "").strip().lower()
            if ced_clean and ced_clean in seen_cedulas:
                print(f"[Broadcast Task] Omitiendo cliente duplicado por cédula {c.cedula} ({c.nombre})")
                continue

            if num_principal in seen_numeros:
                print(f"[Broadcast Task] Omitiendo cliente duplicado por número de WhatsApp {num_principal} ({c.nombre})")
                continue

            seen_ids.add(c.id)
            if ced_clean:
                seen_cedulas.add(ced_clean)
            seen_numeros.add(num_principal)
            clientes_unicos.append(c)

        total_clientes = len(clientes_unicos)
        print(f"[Broadcast Task] Iniciando difusión masiva con protección anti-baneo a {total_clientes} clientes únicos ({alcance_label}). Lotes: {tamano_lote}. Intervalo por mensaje: {delay_a:.1f}-{delay_b:.1f}s. Pausa entre lotes: {pausa_lote_a/60:.1f}-{pausa_lote_b/60:.1f} min.")
        
        # Obtener o registrar campaña de difusión en historial
        if difusion_id:
            difusion_registro = db.query(models.WhatsAppDifusionHistorial).filter(
                models.WhatsAppDifusionHistorial.id == difusion_id
            ).first()
            if difusion_registro:
                difusion_registro.alcance = alcance_label
                difusion_registro.total_destinatarios = total_clientes
                difusion_registro.estado = "en_proceso" if total_clientes > 0 else "completado"
                db.commit()

        if not difusion_registro:
            difusion_registro = models.WhatsAppDifusionHistorial(
                tipo="difusion_masiva",
                alcance=alcance_label,
                mensaje=mensaje,
                total_destinatarios=total_clientes,
                total_exitosos=0,
                total_fallidos=0,
                estado="en_proceso" if total_clientes > 0 else "completado",
                fecha_envio=datetime.now(ECUADOR_TZ).strftime("%Y-%m-%d %H:%M:%S"),
                fecha_creacion=datetime.now(ECUADOR_TZ)
            )
            db.add(difusion_registro)
            db.commit()

        cur_dif_id = difusion_registro.id if difusion_registro else None

        # Funciones auxiliares para cancelación inmediata e interruptible sleep
        def should_cancel() -> bool:
            nonlocal cur_dif_id
            if utils.GLOBAL_CANCEL_REQUESTED:
                return True
            if cur_dif_id and cur_dif_id in CANCELLED_DIFUSIONES:
                return True
            if cur_dif_id:
                try:
                    db.expire_all()
                    item = db.query(models.WhatsAppDifusionHistorial).filter(models.WhatsAppDifusionHistorial.id == cur_dif_id).first()
                    if item and item.estado == "cancelado":
                        CANCELLED_DIFUSIONES.add(cur_dif_id)
                        return True
                except Exception:
                    pass
            return False

        def interruptible_sleep(duration_sec: float) -> bool:
            """Duerme en intervalos de 0.5s para responder de forma instantánea al botón Cancelar."""
            deadline = time.time() + duration_sec
            while time.time() < deadline:
                if should_cancel():
                    return True
                time.sleep(min(0.5, max(0.05, deadline - time.time())))
            return should_cancel()

        exitosos = 0
        fallidos = 0
        cancelado_por_usuario = False

        for idx, cliente in enumerate(clientes_unicos):
            if should_cancel():
                print(f"[Broadcast Task] 🛑 Envío masivo #{cur_dif_id} cancelado por el usuario. Deteniendo de inmediato...")
                cancelado_por_usuario = True
                break

            numero = (cliente.celular or "").strip()
            num_principal = whatsapp_service.format_whatsapp_number(numero)
            if not num_principal:
                fallidos += 1
                continue

            mensaje_personalizado = personalizar_mensaje_cliente(mensaje, cliente)
            success = whatsapp_service.send_whatsapp_message(num_principal, mensaje_personalizado, priority="bulk")
            
            if success:
                exitosos += 1
                try:
                    registrar_mensaje_chat(db, num_principal, "operador", mensaje_personalizado, cliente.id if cliente else None)
                except Exception:
                    pass
            else:
                fallidos += 1

            # Guardar en historial individual
            historial = models.WhatsAppHistorial(
                numero_destino=num_principal,
                mensaje=mensaje_personalizado,
                tipo_envio=f"difusion_{nodo_clean if nodo_clean else 'global'}",
                estado="enviado" if success else "fallido",
                fecha_envio=datetime.now(ECUADOR_TZ).strftime("%Y-%m-%d %H:%M:%S") if success else None,
                fecha_creacion=datetime.now(ECUADOR_TZ)
            )
            db.add(historial)

            if difusion_registro:
                difusion_registro.total_exitosos = exitosos
                difusion_registro.total_fallidos = fallidos
            db.commit()

            # Lógica de pausas entre clientes y descanso entre lotes con verificación de cancelación en tiempo real
            if idx < total_clientes - 1:
                if (idx + 1) % tamano_lote == 0:
                    descanso_sec = random.uniform(pausa_lote_a, pausa_lote_b)
                    descanso_min = descanso_sec / 60.0
                    print(f"[Broadcast Task] 🛑 Lote de {tamano_lote} clientes completado ({idx + 1}/{total_clientes}). Pausa de descanso anti-bloqueo: {descanso_min:.2f} minutos ({int(descanso_sec)}s) antes del siguiente grupo...")
                    if interruptible_sleep(descanso_sec):
                        print(f"[Broadcast Task] 🛑 Envío masivo #{cur_dif_id} cancelado durante la pausa entre lotes.")
                        cancelado_por_usuario = True
                        break
                else:
                    delay_sec = random.uniform(delay_a, delay_b)
                    print(f"[Broadcast Task] Mensaje {idx + 1}/{total_clientes} enviado ({'Éxito' if success else 'Fallo'}). Pausa de {delay_sec:.1f}s...")
                    if interruptible_sleep(delay_sec):
                        print(f"[Broadcast Task] 🛑 Envío masivo #{cur_dif_id} cancelado durante la pausa entre mensajes.")
                        cancelado_por_usuario = True
                        break

        if difusion_registro:
            if cancelado_por_usuario or should_cancel():
                difusion_registro.estado = "cancelado"
                print(f"[Broadcast Task] Campaña #{cur_dif_id} marcada como CANCELADA. Entregados antes de cancelar: {exitosos}/{total_clientes}")
            else:
                difusion_registro.estado = "completado"
                print(f"[Broadcast Task] Envío masivo #{cur_dif_id} finalizado exitosamente. Exitosos: {exitosos}, Fallidos: {fallidos}")
            difusion_registro.total_exitosos = exitosos
            difusion_registro.total_fallidos = fallidos
            db.commit()

    except Exception as e:
        db.rollback()
        print(f"[Broadcast Task] Error durante el envío masivo: {str(e)}")
        if difusion_registro:
            try:
                difusion_registro.estado = "fallido"
                db.commit()
            except Exception:
                pass
    finally:
        db.close()


def _reintentar_fallidos_task(ids_fallidos: list):
    """
    Tarea en segundo plano: reintenta los mensajes fallidos uno a uno.
    Cada envío es 'bulk', por lo que el puente aplica horario, topes y espaciado anti-bloqueo.
    """
    db = SessionLocal()
    reintentados = 0
    errores = 0
    seen_destinos = set()
    try:
        for hist_id in ids_fallidos:
            if utils.GLOBAL_CANCEL_REQUESTED:
                print("[Retry Task] Reintento de fallidos detenido por cancelación.")
                break
            try:
                item = db.query(models.WhatsAppHistorial).filter(models.WhatsAppHistorial.id == hist_id).first()
                if not item or item.estado != "fallido":
                    continue
                numero = item.numero_destino
                target_num = whatsapp_service.format_whatsapp_number(numero) or numero
                if not target_num:
                    continue

                dup_key = f"{target_num}_{item.mensaje}"
                if dup_key in seen_destinos:
                    item.estado = "cancelado_duplicado"
                    db.commit()
                    continue
                seen_destinos.add(dup_key)

                msg = item.mensaje
                ok = whatsapp_service.send_whatsapp_message(target_num, msg, priority="bulk")
                if ok:
                    item.estado = "enviado"
                    item.fecha_envio = datetime.now(ECUADOR_TZ).strftime("%Y-%m-%d %H:%M:%S")
                    reintentados += 1
                    db.commit()
                    try:
                        registrar_mensaje_chat(db, target_num, "operador", msg)
                    except Exception:
                        pass
                else:
                    errores += 1

                # Pausa interruptible
                deadline = time.time() + random.uniform(15, 30)
                while time.time() < deadline:
                    if utils.GLOBAL_CANCEL_REQUESTED:
                        break
                    time.sleep(min(0.5, deadline - time.time()))
            except Exception as e_retry:
                db.rollback()
                print(f"[Retry Error] Error reintentando mensaje {hist_id}: {e_retry}")
                errores += 1
        print(f"[Retry Task] Reintento finalizado. Exitosos: {reintentados}, Errores: {errores}")
    finally:
        db.close()


@router.post("/enviar-manual", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def enviar_whatsapp_manual(
    payload: schemas.WhatsAppManualSend,
    db: Session = Depends(get_db)
):
    """
    Envía un mensaje de WhatsApp de forma manual a un número específico.
    Si el número pertenece a un cliente en la BD o incluye variables {nombre}, {saldo}, etc., se personaliza.
    """
    try:
        numero = str(payload.numero).strip() if payload.numero else ""
        mensaje = str(payload.mensaje).strip() if payload.mensaje else ""
        
        if not numero or not mensaje:
            raise HTTPException(status_code=400, detail="Número y mensaje son obligatorios")
        
        # Extraer el primer número válido para WhatsApp
        targets = whatsapp_service.extract_all_whatsapp_numbers(numero)
        primary_target = targets[0] if targets else whatsapp_service.format_single_number(numero)
        if not primary_target:
            raise HTTPException(status_code=400, detail="El número proporcionado no es válido para WhatsApp.")

        # Buscar si el número corresponde a un cliente en la BD para personalizar
        cliente = None
        for t in [primary_target]:
            t_digits = re.sub(r'\D', '', t)
            t_ecuador = "0" + t_digits[3:] if t_digits.startswith("593") and len(t_digits) > 3 else t_digits
            cliente = db.query(models.Cliente).filter(
                (models.Cliente.celular.like(f"%{t_digits}%")) |
                (models.Cliente.celular.like(f"%{t_ecuador}%"))
            ).first()
            if cliente:
                break

        mensaje_final = mensaje
        if cliente:
            tiene_variables = bool(re.search(r'\{nombre\}|\{saldo\}|\{plan\}|\{cedula\}|\{nodo\}|\{parroquia\}|\{cliente\}', mensaje, re.IGNORECASE))
            if tiene_variables:
                mensaje_final = personalizar_mensaje_cliente(mensaje, cliente)

        success = whatsapp_service.send_whatsapp_message(primary_target, mensaje_final, priority="manual")
        
        if not success:
            raise HTTPException(
                status_code=500,
                detail="No se pudo enviar el mensaje a WhatsApp. Verifica que el servicio esté conectado y el número sea válido."
            )
        
        if payload.historial_id:
            historial = db.query(models.WhatsAppHistorial).filter(
                models.WhatsAppHistorial.id == payload.historial_id
            ).first()
            if historial:
                historial.estado = "enviado"
                historial.fecha_envio = datetime.now(ECUADOR_TZ).strftime("%Y-%m-%d %H:%M:%S")
                db.commit()
        else:
            historial = models.WhatsAppHistorial(
                numero_destino=primary_target,
                mensaje=mensaje_final,
                tipo_envio="manual",
                estado="enviado",
                fecha_envio=datetime.now(ECUADOR_TZ).strftime("%Y-%m-%d %H:%M:%S"),
                fecha_creacion=datetime.now(ECUADOR_TZ)
            )
            db.add(historial)
            db.commit()

        try:
            registrar_mensaje_chat(db, primary_target, "operador", mensaje_final, cliente.id if cliente else None)
        except Exception as chat_err:
            print(f"[Chat Warning] Error al registrar en chat: {chat_err}")
        
        return {
            "success": True,
            "message": f"Mensaje enviado a {primary_target}",
            "numero": primary_target,
            "destinatarios": [primary_target]
        }
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Error al enviar mensaje: {str(e)}"
        )


@router.post("/programar", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def programar_whatsapp(
    payload: schemas.WhatsAppConfiguracionCreate,
    db: Session = Depends(get_db)
):
    """
    Programa un envío de WhatsApp para una hora específica y opcionalmente una fecha o día específico.
    """
    try:
        hora = payload.hora
        mensaje = payload.mensaje
        enviar_a_todos = payload.enviar_a_todos
        fecha = payload.fecha
        recurrencia = payload.recurrencia or "diario"
        dia_mes = payload.dia_mes
        
        if not hora or not mensaje:
            raise HTTPException(status_code=400, detail="Hora y mensaje son obligatorios")
        
        try:
            datetime.strptime(hora, "%H:%M").time()
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato de hora inválido. Use HH:MM")
        
        fecha_obj = None
        if fecha:
            try:
                fecha_obj = datetime.strptime(fecha, "%Y-%m-%d")
            except ValueError:
                raise HTTPException(status_code=400, detail="Formato de fecha inválido. Use YYYY-MM-DD")
        elif recurrencia == "mensual":
            ahora_ec = datetime.now(ECUADOR_TZ)
            dia_target = dia_mes if (dia_mes and 1 <= dia_mes <= 31) else 1
            try:
                fecha_obj = ahora_ec.replace(day=dia_target, hour=0, minute=0, second=0, microsecond=0)
            except ValueError:
                fecha_obj = ahora_ec.replace(day=28, hour=0, minute=0, second=0, microsecond=0)
        
        filtro_clientes = payload.filtro_clientes or "todos"
        desde_cid = payload.desde_cliente_id if (payload.desde_cliente_id and int(payload.desde_cliente_id) > 0) else None
        nodo_val = payload.nodo.strip() if payload.nodo and str(payload.nodo).strip() and str(payload.nodo).lower() not in ["todos", "all", "todos los nodos"] else None

        config = models.WhatsAppConfiguracion(
            hora_programada=hora,
            mensaje_programado=mensaje,
            activo=True,
            enviar_a_todos=(filtro_clientes == "todos"),
            filtro_clientes=filtro_clientes,
            nodo=nodo_val,
            fecha_programada=fecha_obj,
            recurrencia=recurrencia,
            desde_cliente_id=desde_cid,
            fecha_creacion=datetime.now(ECUADOR_TZ)
        )
        db.add(config)
        db.commit()
        
        msg_resp = f"Envío programado para las {hora}"
        if recurrencia == "mensual":
            dia_num = fecha_obj.day if fecha_obj else (dia_mes or 1)
            msg_resp = f"Envío mensual recurrente configurado para el día {dia_num} de cada mes a las {hora}"
        elif fecha:
            msg_resp += f" el día {fecha}"
            
        if nodo_val:
            msg_resp += f" (Nodo: {nodo_val})"
        if desde_cid:
            msg_resp += f" (Iniciando desde Cliente ID #{desde_cid})"
            
        return {
            "success": True,
            "message": msg_resp,
            "id_config": config.id
        }
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al programar: {str(e)}")


@router.get("/historial", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def obtener_historial(
    limite: int = 100,
    db: Session = Depends(get_db)
):
    """Obtiene el historial de mensajes individuales y el historial de difusiones masivas / envíos programados"""
    try:
        try:
            models.Base.metadata.create_all(bind=engine, tables=[models.WhatsAppDifusionHistorial.__table__], checkfirst=True)
        except Exception:
            pass

        historial = db.query(models.WhatsAppHistorial).order_by(
            models.WhatsAppHistorial.fecha_creacion.desc()
        ).limit(limite).all()

        difusiones = db.query(models.WhatsAppDifusionHistorial).order_by(
            models.WhatsAppDifusionHistorial.fecha_creacion.desc()
        ).limit(limite).all()

        difusiones_list = [
            {
                "id": d.id,
                "tipo": d.tipo,
                "alcance": d.alcance,
                "mensaje": d.mensaje,
                "total_destinatarios": d.total_destinatarios,
                "total_exitosos": d.total_exitosos,
                "total_fallidos": d.total_fallidos,
                "estado": d.estado,
                "fecha": d.fecha_envio or (d.fecha_creacion.strftime("%Y-%m-%d %H:%M:%S") if d.fecha_creacion else "")
            }
            for d in difusiones
        ]

        if not difusiones_list:
            difusiones_antiguas = {}
            for h in historial:
                if h.tipo_envio and h.tipo_envio.startswith("difusion_"):
                    clave = (h.tipo_envio, str(h.fecha_envio)[:16] if h.fecha_envio else "")
                    if clave not in difusiones_antiguas:
                        nodo_str = h.tipo_envio.replace("difusion_", "")
                        alcance_str = "TODOS los clientes activos" if nodo_str in ["global", "todos"] else f"Nodo/Parroquia: {nodo_str}"
                        difusiones_antiguas[clave] = {
                            "id": f"ant-{h.id}",
                            "tipo": "difusion_masiva",
                            "alcance": alcance_str,
                            "mensaje": h.mensaje,
                            "total_destinatarios": 0,
                            "total_exitosos": 0,
                            "total_fallidos": 0,
                            "estado": "completado",
                            "fecha": h.fecha_envio or ""
                        }
                    difusiones_antiguas[clave]["total_destinatarios"] += 1
                    if h.estado == "enviado":
                        difusiones_antiguas[clave]["total_exitosos"] += 1
                    else:
                        difusiones_antiguas[clave]["total_fallidos"] += 1
            difusiones_list = list(difusiones_antiguas.values())

        return {
            "total": len(historial),
            "total_difusiones": len(difusiones_list),
            "historial": [
                {
                    "id": h.id,
                    "numero": h.numero_destino,
                    "mensaje": h.mensaje,
                    "tipo": h.tipo_envio,
                    "estado": h.estado,
                    "fecha": h.fecha_envio
                }
                for h in historial
            ],
            "difusiones": difusiones_list
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/historial/{historial_id}/marcar-enviado", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def marcar_historial_enviado(
    historial_id: int,
    db: Session = Depends(get_db)
):
    """
    Marca un mensaje del historial como enviado.
    """
    try:
        historial = db.query(models.WhatsAppHistorial).filter(
            models.WhatsAppHistorial.id == historial_id
        ).first()
        
        if not historial:
            raise HTTPException(status_code=404, detail="Registro de historial no encontrado")
            
        historial.estado = "enviado"
        historial.fecha_envio = datetime.now(ECUADOR_TZ).strftime("%Y-%m-%d %H:%M:%S")
        db.commit()
        
        return {"success": True, "message": "Mensaje marcado como enviado"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/historial/reintentar-fallidos", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def reintentar_mensajes_fallidos(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Reintenta en segundo plano el envío de todos los mensajes con estado 'fallido' en el historial.
    Se envían de forma escalonada (protección anti-bloqueo): puede tardar horas y respeta el horario permitido.
    """
    utils.GLOBAL_CANCEL_REQUESTED = False
    try:
        ids = [row[0] for row in db.query(models.WhatsAppHistorial.id).filter(
            models.WhatsAppHistorial.estado == "fallido"
        ).order_by(models.WhatsAppHistorial.id.asc()).all()]

        if not ids:
            return {
                "success": True, 
                "message": "No hay mensajes fallidos pendientes de reintento.", 
                "total": 0, 
                "reintentados": 0
            }

        background_tasks.add_task(_reintentar_fallidos_task, ids)

        return {
            "success": True, 
            "message": f"Reintento de {len(ids)} mensajes iniciado en segundo plano de forma escalonada (anti-bloqueo). Revisa el historial para ver el avance.",
            "total": len(ids),
            "reintentados": 0,
            "errores": 0,
            "en_segundo_plano": True
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/difusion/{difusion_id}/cancelar", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def cancelar_difusion(difusion_id: int, db: Session = Depends(get_db)):
    """
    Cancela inmediatamente una difusión masiva en curso.
    Detiene el bucle de envío y marca el estado como 'cancelado'.
    """
    try:
        CANCELLED_DIFUSIONES.add(int(difusion_id))
        dif = db.query(models.WhatsAppDifusionHistorial).filter(
            models.WhatsAppDifusionHistorial.id == difusion_id
        ).first()
        
        if not dif:
            raise HTTPException(status_code=404, detail="Campaña de difusión no encontrada")
            
        dif.estado = "cancelado"
        db.commit()
        
        try:
            bridge_url = getattr(whatsapp_service, "WHATSAPP_BRIDGE_URL", "http://localhost:3001")
            requests.post(f"{bridge_url.rstrip('/')}/cancel", timeout=2)
        except Exception:
            pass

        return {
            "success": True,
            "message": f"Difusión #{difusion_id} cancelada exitosamente. Se ha detenido el envío.",
            "id": difusion_id,
            "estado": "cancelado"
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al cancelar difusión: {str(e)}")


@router.post("/cancelar-todos-envios", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def cancelar_todos_los_envios(db: Session = Depends(get_db)):
    """
    Cancela de emergencia TODOS los envíos masivos y reintentos que se encuentren 'en_proceso'.
    """
    try:
        utils.GLOBAL_CANCEL_REQUESTED = True
        
        actualizados = db.query(models.WhatsAppDifusionHistorial).filter(
            models.WhatsAppDifusionHistorial.estado == "en_proceso"
        ).update({"estado": "cancelado"}, synchronize_session=False)
        db.commit()
        
        try:
            bridge_url = getattr(whatsapp_service, "WHATSAPP_BRIDGE_URL", "http://localhost:3001")
            requests.post(f"{bridge_url.rstrip('/')}/cancel", timeout=2)
        except Exception:
            pass

        return {
            "success": True,
            "message": f"Se cancelaron exitosamente {actualizados} campañas de envío en proceso.",
            "total_cancelados": actualizados
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error cancelando envíos: {str(e)}")


@router.post("/enviar-global", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def enviar_whatsapp_global(
    payload: schemas.WhatsAppGlobalSend,
    background_tasks: BackgroundTasks
):
    """
    Envía un mensaje de difusión de WhatsApp según el estado de cliente y nodo seleccionado.
    El envío se realiza en segundo plano (asíncronamente) con protección anti-baneo y pausas aleatorias.
    """
    utils.GLOBAL_CANCEL_REQUESTED = False

    if not payload.mensaje:
        raise HTTPException(status_code=400, detail="El mensaje no puede estar vacío.")

    db = SessionLocal()
    difusion_id = None
    try:
        models.Base.metadata.create_all(bind=engine, tables=[models.WhatsAppDifusionHistorial.__table__], checkfirst=True)
        
        estado_label = (payload.estado or "ACTIVO").strip().upper()
        nodo_label = payload.nodo.strip() if payload.nodo and str(payload.nodo).strip() and str(payload.nodo).lower() not in ["todos", "all"] else "Todos los nodos"
        
        puertos_list = None
        if payload.puertos:
            if isinstance(payload.puertos, list):
                puertos_list = [str(p).strip() for p in payload.puertos if str(p).strip()]
            elif isinstance(payload.puertos, str):
                puertos_list = [p.strip() for p in payload.puertos.split(',') if p.strip()]

        puertos_label = f" | Puertos: {', '.join([p if 'puerto' in str(p).lower() else f'Puerto {p}' for p in puertos_list])}" if puertos_list else ""
        alcance_est = f"Clientes {estado_label} ({nodo_label}{puertos_label})"
        
        dif_reg = models.WhatsAppDifusionHistorial(
            tipo="difusion_masiva",
            alcance=alcance_est,
            mensaje=payload.mensaje,
            total_destinatarios=0,
            total_exitosos=0,
            total_fallidos=0,
            estado="en_proceso",
            fecha_envio=datetime.now(ECUADOR_TZ).strftime("%Y-%m-%d %H:%M:%S"),
            fecha_creacion=datetime.now(ECUADOR_TZ)
        )
        db.add(dif_reg)
        db.commit()
        difusion_id = dif_reg.id
    except Exception as e_init:
        print(f"[enviar_whatsapp_global] Aviso creando registro inicial: {e_init}")
        db.rollback()
    finally:
        db.close()
    
    background_tasks.add_task(
        send_global_broadcast_task,
        payload.mensaje,
        payload.nodo,
        SessionLocal,
        payload.estado or "ACTIVO",
        payload.delay_min if payload.delay_min is not None else 25.0,
        payload.delay_max if payload.delay_max is not None else 45.0,
        payload.batch_size if payload.batch_size is not None else 10,
        payload.batch_pause_min if payload.batch_pause_min is not None else 180.0,
        payload.batch_pause_max if payload.batch_pause_max is not None else 300.0,
        payload.desde_id,
        payload.hasta_id,
        payload.limite_mensajes,
        difusion_id,
        puertos_list
    )
    
    msg_detalle = "Difusión masiva iniciada en segundo plano con protección anti-bloqueo."
    if payload.limite_mensajes:
        msg_detalle = f"Difusión iniciada en segundo plano para {payload.limite_mensajes} clientes (iniciando desde ID {payload.desde_id or 'primer registro'})."

    return {
        "success": True,
        "message": msg_detalle,
        "difusion_id": difusion_id
    }
