from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
from datetime import datetime
import pytz
import models, schemas
from database import get_db, SessionLocal
from .auth import require_role
import traceback
import whatsapp_service

import requests
from typing import Optional
import urllib.parse

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])

# Zona horaria Ecuador
ECUADOR_TZ = pytz.timezone('America/Guayaquil')

def obtener_info_contacto_bridge(chat_id: str):
    """
    Consulta al puente local de WhatsApp (/contact/:chatId) para obtener
    el número telefónico real y el nombre de perfil del contacto.
    """
    if not chat_id:
        return None
    try:
        bridge_url = getattr(whatsapp_service, "WHATSAPP_BRIDGE_URL", "http://localhost:3001")
        url = f"{bridge_url.rstrip('/')}/contact/{urllib.parse.quote(chat_id)}"
        resp = requests.get(url, timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success"):
                return data
    except Exception as e:
        print(f"[WhatsApp Route] Error consultando contacto en bridge para {chat_id}: {e}")
    return None


from sqlalchemy import or_, func
import unicodedata
import re

def personalizar_mensaje_cliente(mensaje_base: str, cliente) -> str:
    """
    Personaliza un mensaje con los datos del cliente desde la BD.
    Soporta etiquetas: {nombre}, {nombre_completo}, {cliente}, {saldo}, {plan}, {cedula}, {nodo}, {parroquia}.
    Si el mensaje no contiene ninguna etiqueta de nombre, se añade automáticamente un saludo cordial personalizado con su nombre.
    """
    if not mensaje_base:
        return ""

    nombre_raw = getattr(cliente, "nombre", "") or ""
    nombre_limpio = " ".join(nombre_raw.strip().split())
    if nombre_limpio:
        partes = nombre_limpio.split()
        primer_nombre = partes[0].capitalize()
        nombre_corto = primer_nombre
    else:
        primer_nombre = "estimado/a cliente"
        nombre_limpio = "Estimado/a cliente"
        nombre_corto = "estimado/a cliente"

    saldo_val = getattr(cliente, "saldo", 0.0) or 0.0
    saldo_str = f"${float(saldo_val):.2f}"
    plan_str = str(getattr(cliente, "plan", "") or "No especificado").strip()
    cedula_str = str(getattr(cliente, "cedula", "") or "").strip()
    nodo_str = str(getattr(cliente, "nodo", "") or "").strip()
    parroquia_str = str(getattr(cliente, "parroquia", "") or "").strip()

    msg = mensaje_base
    tiene_etiqueta_nombre = False

    if re.search(r'\{nombre\}|\{cliente\}', msg, re.IGNORECASE):
        tiene_etiqueta_nombre = True
        msg = re.sub(r'\{nombre\}|\{cliente\}', nombre_corto, msg, flags=re.IGNORECASE)

    if re.search(r'\{nombre_completo\}', msg, re.IGNORECASE):
        tiene_etiqueta_nombre = True
        msg = re.sub(r'\{nombre_completo\}', nombre_limpio, msg, flags=re.IGNORECASE)

    msg = re.sub(r'\{saldo\}', saldo_str, msg, flags=re.IGNORECASE)
    msg = re.sub(r'\{plan\}', plan_str, msg, flags=re.IGNORECASE)
    msg = re.sub(r'\{cedula\}', cedula_str, msg, flags=re.IGNORECASE)
    msg = re.sub(r'\{nodo\}', nodo_str, msg, flags=re.IGNORECASE)
    msg = re.sub(r'\{parroquia\}', parroquia_str, msg, flags=re.IGNORECASE)

    if not tiene_etiqueta_nombre:
        if primer_nombre != "estimado/a cliente":
            saludo = f"Hola *{primer_nombre}*,\n"
        else:
            saludo = "Estimado/a cliente,\n"
        msg = f"{saludo}{msg.strip()}"

    return msg


def remove_accents(input_str):
    if not input_str:
        return ""
    return ''.join(c for c in unicodedata.normalize('NFD', str(input_str)) if unicodedata.category(c) != 'Mn')

def registrar_mensaje_chat(db: Session, numero: str, rol: str, mensaje: str, cliente_id: int = None, tipo: str = "texto"):
    """
    Registra un mensaje en el historial del chat y aplica la regla estricta:
    Guarda únicamente los últimos 30 mensajes por número telefónico, podando los más antiguos.
    Soporta identificadores @lid y números telefónicos estándar vinculando al cliente correspondiente.
    """
    if not numero or not mensaje:
        return None

    num_limpio = whatsapp_service.format_whatsapp_number(numero)
    if not num_limpio:
        num_limpio = str(numero).strip()

    is_lid = "@lid" in str(num_limpio).lower() or str(numero).lower().endswith("@lid")

    # Si no tiene cliente_id asignado, buscar coincidencia en la BD
    if not cliente_id:
        # 1. Comprobar si ya existe algún mensaje previo con este número exacto que tenga cliente_id
        prev_msg = db.query(models.WhatsAppMensajeChat.cliente_id).filter(
            models.WhatsAppMensajeChat.numero == num_limpio,
            models.WhatsAppMensajeChat.cliente_id.isnot(None)
        ).order_by(models.WhatsAppMensajeChat.id.desc()).first()
        if prev_msg:
            cliente_id = prev_msg[0]

        # 2. Si es LID y no tenemos cliente_id, intentar resolver datos reales mediante el bridge
        if not cliente_id and is_lid:
            info_contacto = obtener_info_contacto_bridge(num_limpio)
            if info_contacto:
                real_number = info_contacto.get("number")
                pushname = info_contacto.get("pushname") or info_contacto.get("name")

                # Intentar por número real si se obtuvo
                if real_number:
                    try:
                        import sam_bot_service
                        c = sam_bot_service.buscar_cliente_por_celular(real_number, db)
                        if c:
                            cliente_id = c.id
                    except Exception:
                        pass

                # Si aún no coincide por número, intentar por nombre pushname
                if not cliente_id and pushname:
                    try:
                        import sam_bot_service
                        c_match, _ = sam_bot_service.buscar_cliente_por_nombre(pushname, db)
                        if c_match:
                            cliente_id = c_match.id
                    except Exception:
                        pass

        # 3. Si es un número estándar (@c.us o dígitos)
        if not cliente_id and not is_lid:
            try:
                import sam_bot_service
                c = sam_bot_service.buscar_cliente_por_celular(num_limpio, db)
                if c:
                    cliente_id = c.id
            except Exception:
                pass

    # 1. Crear el nuevo mensaje
    nuevo_msg = models.WhatsAppMensajeChat(
        numero=num_limpio,
        rol=rol,
        mensaje=str(mensaje).strip(),
        tipo=tipo,
        cliente_id=cliente_id,
        fecha_hora=datetime.now(ECUADOR_TZ)
    )
    db.add(nuevo_msg)
    db.flush()

    # Si se determinó cliente_id, propagarlo a mensajes anteriores de este mismo identificador que no lo tenían
    if cliente_id:
        try:
            db.query(models.WhatsAppMensajeChat).filter(
                models.WhatsAppMensajeChat.numero == num_limpio,
                models.WhatsAppMensajeChat.cliente_id.is_(None)
            ).update({"cliente_id": cliente_id}, synchronize_session=False)
        except Exception:
            pass

    # Si quien envió el mensaje fue un Operador humano, pausar respuestas de SAM por 5 minutos
    if rol == "operador":
        try:
            import sam_bot_service
            sam_bot_service.pausar_bot_por_operador(num_limpio)
        except Exception as e_pause:
            print(f"[WhatsApp Chat] Error activando pausa de SAM para operador: {e_pause}")

    # 2. Poda automática: Mantener exactamente los 100 más recientes
    subq = db.query(models.WhatsAppMensajeChat.id).filter(
        models.WhatsAppMensajeChat.numero == num_limpio
    ).order_by(models.WhatsAppMensajeChat.id.desc()).offset(100).all()

    if subq:
        ids_a_eliminar = [row[0] for row in subq]
        db.query(models.WhatsAppMensajeChat).filter(
            models.WhatsAppMensajeChat.id.in_(ids_a_eliminar)
        ).delete(synchronize_session=False)

    db.commit()
    return nuevo_msg


def send_global_broadcast_task(mensaje: str, nodo: str, db_session_factory):
    db = db_session_factory()
    import time
    import random
    try:
        # Obtener clientes activos con celular registrado (soporta ACTIVO / ACTIVA / Activo)
        query = db.query(models.Cliente).filter(
            func.upper(models.Cliente.estado).in_(["ACTIVO", "ACTIVA"]),
            models.Cliente.celular != None,
            models.Cliente.celular != ""
        )

        if nodo and str(nodo).strip() and str(nodo).lower() not in ["todos", "all", "todos los nodos"]:
            clean_nodo = remove_accents(str(nodo).strip())
            query = query.filter(
                or_(
                    models.Cliente.nodo.ilike(f"%{clean_nodo}%"),
                    models.Cliente.parroquia.ilike(f"%{clean_nodo}%")
                )
            )
        
        clientes = query.all()
        
        nodo_label = f"nodo/parroquia '{nodo}'" if (nodo and str(nodo).lower() not in ["todos", "all", "todos los nodos"]) else "TODOS los nodos"
        print(f"[Broadcast Task] Iniciando difusión masiva con protección anti-baneo a {len(clientes)} clientes activos ({nodo_label}).")
        
        for idx, cliente in enumerate(clientes):
            numero = cliente.celular.strip()
            mensaje_personalizado = personalizar_mensaje_cliente(mensaje, cliente)
            success = whatsapp_service.send_whatsapp_message(numero, mensaje_personalizado)
            
            # Guardar en historial
            historial = models.WhatsAppHistorial(
                numero_destino=numero,
                mensaje=mensaje_personalizado,
                tipo_envio=f"difusion_{nodo if (nodo and str(nodo).lower() not in ['todos', 'all']) else 'global'}",
                estado="enviado" if success else "fallido",
                fecha_envio=datetime.now(ECUADOR_TZ).strftime("%Y-%m-%d %H:%M:%S") if success else None,
                fecha_creacion=datetime.now(ECUADOR_TZ)
            )
            db.add(historial)
            db.commit()

            # Pausa aleatoria anti-baneo (entre 4.0 y 7.5 segundos por mensaje)
            if idx < len(clientes) - 1:
                delay_sec = random.uniform(4.0, 7.5)
                time.sleep(delay_sec)

        print(f"[Broadcast Task] Envío masivo finalizado exitosamente.")
    except Exception as e:
        db.rollback()
        print(f"[Broadcast Task] Error durante el envío masivo: {str(e)}")
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
        numero = payload.numero
        mensaje = payload.mensaje
        
        if not numero or not mensaje:
            raise HTTPException(status_code=400, detail="Número y mensaje son obligatorios")
        
        # Buscar si el número corresponde a un cliente en la BD para personalizar
        num_limpio = whatsapp_service.format_whatsapp_number(numero)
        num_solo_digitos = re.sub(r'\D', '', num_limpio)
        num_ecuador = "0" + num_solo_digitos[3:] if num_solo_digitos.startswith("593") and len(num_solo_digitos) > 3 else num_solo_digitos

        cliente = db.query(models.Cliente).filter(
            (models.Cliente.celular.like(f"%{num_solo_digitos}%")) |
            (models.Cliente.celular.like(f"%{num_ecuador}%"))
        ).first()

        mensaje_final = mensaje
        if cliente:
            # Si el mensaje contiene variables o el cliente fue hallado, personalizar
            tiene_variables = bool(re.search(r'\{nombre\}|\{saldo\}|\{plan\}|\{cedula\}|\{nodo\}|\{parroquia\}|\{cliente\}', mensaje, re.IGNORECASE))
            if tiene_variables:
                mensaje_final = personalizar_mensaje_cliente(mensaje, cliente)

        # Enviar mensaje usando el servicio unificado
        success = whatsapp_service.send_whatsapp_message(numero, mensaje_final)
        
        if not success:
            raise HTTPException(
                status_code=500,
                detail="No se pudo enviar el mensaje. Asegúrate de que el puente local de WhatsApp esté conectado."
            )
        
        # Guardar en historial general
        historial = models.WhatsAppHistorial(
            numero_destino=numero,
            mensaje=mensaje_final,
            tipo_envio="manual",
            estado="enviado",
            fecha_envio=datetime.now(ECUADOR_TZ).strftime("%Y-%m-%d %H:%M:%S"),
            fecha_creacion=datetime.now(ECUADOR_TZ)
        )
        db.add(historial)
        db.commit()

        # Guardar en el chat bidireccional del cliente (con regla de máximo 30 mensajes)
        try:
            registrar_mensaje_chat(db, numero, "operador", mensaje_final, cliente.id if cliente else None)
        except Exception as chat_err:
            print(f"[Chat Warning] Error al registrar en chat: {chat_err}")
        
        return {
            "success": True,
            "message": f"Mensaje enviado a {numero}",
            "numero": numero
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
    Programa un envío de WhatsApp para una hora específica y opcionalmente una fecha específica.
    """
    try:
        hora = payload.hora
        mensaje = payload.mensaje
        enviar_a_todos = payload.enviar_a_todos
        fecha = payload.fecha
        
        if not hora or not mensaje:
            raise HTTPException(status_code=400, detail="Hora y mensaje son obligatorios")
        
        # Validar formato de hora
        try:
            datetime.strptime(hora, "%H:%M").time()
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato de hora inválido. Use HH:MM")
        
        # Validar formato de fecha (si existe)
        fecha_obj = None
        if fecha:
            try:
                fecha_obj = datetime.strptime(fecha, "%Y-%m-%d")
            except ValueError:
                raise HTTPException(status_code=400, detail="Formato de fecha inválido. Use YYYY-MM-DD")
        
        # Guardar configuración programada
        config = models.WhatsAppConfiguracion(
            hora_programada=hora,
            mensaje_programado=mensaje,
            activo=True,
            enviar_a_todos=enviar_a_todos,
            fecha_programada=fecha_obj,
            recurrencia=payload.recurrencia or "diario",
            fecha_creacion=datetime.now(ECUADOR_TZ)
        )
        db.add(config)
        db.commit()
        
        msg_resp = f"Envío programado para las {hora}"
        if fecha:
            msg_resp += f" el día {fecha}"
        if payload.recurrencia == "mensual":
            msg_resp += " (Recurrente mensual)"
            
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

@router.get("/configuracion", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def obtener_configuracion(db: Session = Depends(get_db)):
    """Obtiene la configuración actual de envío programado"""
    try:
        config = db.query(models.WhatsAppConfiguracion).filter(
            models.WhatsAppConfiguracion.activo == True
        ).first()
        
        if not config:
            return {"configurado": False, "mensaje": "No hay envío programado"}
        
        fecha_str = config.fecha_programada.strftime("%Y-%m-%d") if config.fecha_programada else None
        
        return {
            "configurado": True,
            "hora": config.hora_programada,
            "mensaje": config.mensaje_programado,
            "enviar_a_todos": config.enviar_a_todos,
            "fecha": fecha_str,
            "recurrencia": getattr(config, 'recurrencia', 'diario') or 'diario',
            "id": config.id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.patch("/configuracion/{config_id}", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def actualizar_configuracion(
    config_id: int,
    payload: schemas.WhatsAppConfiguracionUpdate,
    db: Session = Depends(get_db)
):
    """Actualiza la configuración de envío programado"""
    try:
        config = db.query(models.WhatsAppConfiguracion).filter(
            models.WhatsAppConfiguracion.id == config_id
        ).first()
        
        if not config:
            raise HTTPException(status_code=404, detail="Configuración no encontrada")
        
        if payload.hora is not None:
            # Validar formato
            try:
                datetime.strptime(payload.hora, "%H:%M").time()
                config.hora_programada = payload.hora
            except ValueError:
                raise HTTPException(status_code=400, detail="Formato de hora inválido")
        
        if payload.mensaje is not None:
            config.mensaje_programado = payload.mensaje
        
        if payload.activo is not None:
            config.activo = payload.activo
            
        if payload.enviar_a_todos is not None:
            config.enviar_a_todos = payload.enviar_a_todos
            
        if payload.fecha is not None:
            if payload.fecha == "vaciar":
                config.fecha_programada = None
            else:
                try:
                    fecha_obj = datetime.strptime(payload.fecha, "%Y-%m-%d")
                    config.fecha_programada = fecha_obj
                except ValueError:
                    raise HTTPException(status_code=400, detail="Formato de fecha inválido. Use YYYY-MM-DD")
        
        if payload.recurrencia is not None:
            config.recurrencia = payload.recurrencia
            
        db.commit()
        
        return {"success": True, "message": "Configuración actualizada"}
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/configuracion/{config_id}", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def eliminar_configuracion(
    config_id: int,
    db: Session = Depends(get_db)
):
    """Elimina una configuración de envío programado"""
    try:
        config = db.query(models.WhatsAppConfiguracion).filter(
            models.WhatsAppConfiguracion.id == config_id
        ).first()
        
        if not config:
            raise HTTPException(status_code=404, detail="Configuración no encontrada")
        
        db.delete(config)
        db.commit()
        
        return {"success": True, "message": "Configuración eliminada"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/historial", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def obtener_historial(
    limite: int = 50,
    db: Session = Depends(get_db)
):
    """Obtiene el historial de mensajes enviados"""
    try:
        historial = db.query(models.WhatsAppHistorial).order_by(
            models.WhatsAppHistorial.fecha_creacion.desc()
        ).limit(limite).all()
        
        return {
            "total": len(historial),
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
            ]
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

@router.post("/logout", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def cerrar_sesion_puente():
    """
    Cierra la sesión activa en el microservicio Node.js (whatsapp-web.js).
    Permite volver a escanear un nuevo código QR.
    """
    import requests
    provider = whatsapp_service.WHATSAPP_PROVIDER
    if provider != "local-bridge":
        return {"success": True, "message": f"Proveedor {provider} no requiere logout local"}
    
    url = f"{whatsapp_service.WHATSAPP_BRIDGE_URL.rstrip('/')}/logout"
    try:
        resp = requests.post(url, timeout=10)
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"No se pudo contactar con el puente local para cerrar sesión: {str(e)}")

@router.get("/status-bridge", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def obtener_status_puente():
    """
    Obtiene el estado de conexión del proveedor de WhatsApp activo.
    Para green-api: retorna datos de configuración.
    Para local-bridge: consulta el microservicio Node.js.
    """
    provider = whatsapp_service.WHATSAPP_PROVIDER
    if provider == "green-api":
        instance_id = whatsapp_service.WHATSAPP_INSTANCE_ID
        token = whatsapp_service.WHATSAPP_TOKEN
        if instance_id and token:
            return {
                "status": "GREEN_API",
                "connected": True,
                "provider": "green-api",
                "instance_id": instance_id,
                "message": "Proveedor Green API configurado. Gestiona la sesión en console.green-api.com"
            }
        else:
            return {
                "status": "GREEN_API_NO_CREDENTIALS",
                "connected": False,
                "provider": "green-api",
                "message": "Faltan las variables WHATSAPP_INSTANCE_ID y WHATSAPP_TOKEN en el entorno del servidor."
            }
    return whatsapp_service.get_whatsapp_bridge_status()

@router.get("/qr-bridge", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def obtener_qr_puente():
    """
    Obtiene la imagen Base64 del QR (solo para local-bridge).
    Para green-api, el QR se gestiona en el panel de Green API.
    """
    provider = whatsapp_service.WHATSAPP_PROVIDER
    if provider == "green-api":
        raise HTTPException(
            status_code=400,
            detail="El QR se gestiona en el panel de Green API (console.green-api.com). No aplica para este proveedor."
        )
    res = whatsapp_service.get_whatsapp_bridge_qr()
    if not res.get("qr"):
        raise HTTPException(
            status_code=400,
            detail=res.get("message") or "El código QR no está disponible."
        )
    return res

@router.post("/enviar-global", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def enviar_whatsapp_global(
    payload: schemas.WhatsAppGlobalSend,
    background_tasks: BackgroundTasks
):
    """
    Envía un mensaje de WhatsApp a todos los clientes que se encuentran en estado 'Activo'.
    El envío se realiza en segundo plano (asíncronamente) para no bloquear al servidor.
    """
    if not payload.mensaje:
        raise HTTPException(status_code=400, detail="El mensaje no puede estar vacío.")
    
    # Encolar la tarea en background
    background_tasks.add_task(send_global_broadcast_task, payload.mensaje, payload.nodo, SessionLocal)
    
    return {
        "success": True,
        "message": "Difusión masiva iniciada en segundo plano."
    }

from pydantic import BaseModel
from typing import Optional
import urllib.parse

class WhatsAppWebhookPayload(BaseModel):
    numero: str
    mensaje: str
    nombre: Optional[str] = None
    jid_original: Optional[str] = None

@router.post("/webhook-mensaje")
def webhook_mensaje_whatsapp(
    payload: WhatsAppWebhookPayload,
    db: Session = Depends(get_db)
):
    """
    Webhook público que recibe los mensajes entrantes de WhatsApp desde el puente local
    y los procesa a través del asistente virtual SAM.
    """
    try:
        import sam_bot_service
        
        # Si el mensaje provino de un LID (@lid), enviar la respuesta al LID original
        destino = payload.jid_original if (payload.jid_original and "@lid" in str(payload.jid_original).lower()) else payload.numero

        response_text = sam_bot_service.procesar_mensaje_entrante(
            numero=destino,
            mensaje=payload.mensaje,
            db=db,
            nombre_remitente=payload.nombre or "",
            jid_original=payload.jid_original or ""
        )
        return {
            "success": True,
            "response": response_text
        }
    except Exception as e:
        print(f"[Webhook Mensaje Error] {str(e)}")
        import traceback
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Error interno procesando mensaje en SAM: {str(e)}"
        )

# ========================================================================
# CHATS Y CONVERSACIONES POR CLIENTE (MÁXIMO 100 MENSAJES POR NÚMERO)
# ========================================================================

class EnviarMensajeChatPayload(BaseModel):
    mensaje: str

@router.get("/conversaciones", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def listar_conversaciones_chat(db: Session = Depends(get_db)):
    """
    Obtiene la lista de clientes con los que se tiene conversación activa,
    ordenados por la fecha del último mensaje recibido o enviado.
    Resuelve automáticamente nombres de contactos @lid a través del puente de WhatsApp.
    """
    try:
        # Obtener el último mensaje por número y el conteo de mensajes (máximo 100)
        subq = db.query(
            models.WhatsAppMensajeChat.numero,
            func.max(models.WhatsAppMensajeChat.id).label("max_id"),
            func.count(models.WhatsAppMensajeChat.id).label("total_msgs")
        ).group_by(models.WhatsAppMensajeChat.numero).subquery()

        filas = db.query(models.WhatsAppMensajeChat, subq.c.total_msgs).join(
            subq, models.WhatsAppMensajeChat.id == subq.c.max_id
        ).order_by(models.WhatsAppMensajeChat.id.desc()).all()

        resultado = []
        for msg, total_msgs in filas:
            num_limpio = msg.numero
            is_lid = "@lid" in str(num_limpio).lower()
            num_solo_digitos = re.sub(r'\D', '', num_limpio)
            num_ecuador = "0" + num_solo_digitos[3:] if num_solo_digitos.startswith("593") and len(num_solo_digitos) > 3 else num_solo_digitos

            # Buscar datos del cliente si existe en la BD
            cliente = None
            pushname_fallback = None

            if msg.cliente_id:
                cliente = db.query(models.Cliente).filter(models.Cliente.id == msg.cliente_id).first()

            if not cliente and not is_lid:
                try:
                    import sam_bot_service
                    cliente = sam_bot_service.buscar_cliente_por_celular(num_limpio, db)
                except Exception:
                    pass

            # Si es LID y no tenemos cliente vinculado, intentar resolver contacto por puente
            if not cliente and is_lid:
                info_contacto = obtener_info_contacto_bridge(num_limpio)
                if info_contacto:
                    real_number = info_contacto.get("number")
                    pushname = info_contacto.get("pushname") or info_contacto.get("name")
                    if real_number:
                        try:
                            import sam_bot_service
                            cliente = sam_bot_service.buscar_cliente_por_celular(real_number, db)
                        except Exception:
                            pass

                    if not cliente and pushname:
                        try:
                            import sam_bot_service
                            c_match, _ = sam_bot_service.buscar_cliente_por_nombre(pushname, db)
                            if c_match:
                                cliente = c_match
                            else:
                                pushname_fallback = pushname
                        except Exception:
                            pushname_fallback = pushname

                    if cliente:
                        try:
                            db.query(models.WhatsAppMensajeChat).filter(
                                models.WhatsAppMensajeChat.numero == num_limpio
                            ).update({"cliente_id": cliente.id}, synchronize_session=False)
                            db.commit()
                        except Exception:
                            db.rollback()

            nombre_mostrar = cliente.nombre if cliente else (f"{pushname_fallback} (WhatsApp)" if pushname_fallback else f"Cliente ({msg.numero})")

            resultado.append({
                "numero": msg.numero,
                "cliente_id": cliente.id if cliente else None,
                "nombre": nombre_mostrar,
                "plan": getattr(cliente, "plan", "No especificado") if cliente else "No especificado",
                "saldo": float(cliente.saldo or 0.0) if hasattr(cliente, 'saldo') and cliente and cliente.saldo else 0.0,
                "estado": getattr(cliente, "estado", "Desconocido") if cliente else "Desconocido",
                "nodo": getattr(cliente, "nodo", "N/A") if cliente else "N/A",
                "ip": getattr(cliente, "ip", "N/A") if cliente else "N/A",
                "celular": getattr(cliente, "celular", msg.numero) if cliente else msg.numero,
                "cedula": getattr(cliente, "cedula", "N/A") if cliente else "N/A",
                "parroquia": getattr(cliente, "parroquia", "N/A") if cliente else "N/A",
                "ultimo_mensaje": msg.mensaje,
                "ultimo_rol": msg.rol,
                "ultima_fecha": msg.fecha_hora.strftime("%Y-%m-%d %H:%M:%S") if msg.fecha_hora else "",
                "total_mensajes": total_msgs
            })

        return resultado
    except Exception as e:
        print(f"[Error Listar Conversaciones] {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/conversaciones/{numero:path}", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def obtener_chat_conversacion(numero: str, db: Session = Depends(get_db)):
    """
    Obtiene el historial de chat con un cliente específico (hasta 100 mensajes cronológicos).
    """
    try:
        numero_decodificado = urllib.parse.unquote(numero).strip()
        num_limpio = whatsapp_service.format_whatsapp_number(numero_decodificado)
        if not num_limpio:
            num_limpio = numero_decodificado

        is_lid = "@lid" in str(num_limpio).lower()
        num_solo_digitos = re.sub(r'\D', '', num_limpio)
        num_ecuador = "0" + num_solo_digitos[3:] if num_solo_digitos.startswith("593") and len(num_solo_digitos) > 3 else num_solo_digitos

        # Obtener hasta los últimos 100 mensajes ordenados por id ASC para visualización natural de chat
        mensajes = db.query(models.WhatsAppMensajeChat).filter(
            (models.WhatsAppMensajeChat.numero == num_limpio) |
            (models.WhatsAppMensajeChat.numero == numero_decodificado) |
            (models.WhatsAppMensajeChat.numero == numero) |
            (models.WhatsAppMensajeChat.numero.like(f"%{num_solo_digitos}%"))
        ).order_by(models.WhatsAppMensajeChat.id.asc()).limit(100).all()

        # Buscar datos del cliente asociado
        cliente = None
        pushname_fallback = None

        # 1. Comprobar si algún mensaje en el historial ya tiene cliente_id asignado
        for m in reversed(mensajes):
            if m.cliente_id:
                cliente = db.query(models.Cliente).filter(models.Cliente.id == m.cliente_id).first()
                if cliente:
                    break

        # 2. Si no es LID, buscar por teléfono estándar en la base de datos
        if not cliente and not is_lid:
            try:
                import sam_bot_service
                cliente = sam_bot_service.buscar_cliente_por_celular(num_limpio, db)
            except Exception:
                pass

        # 3. Si no se ha vinculado, resolver mediante el bridge de WhatsApp (teléfono o nombre en BD)
        if not cliente:
            info_contacto = obtener_info_contacto_bridge(num_limpio)
            if info_contacto:
                real_number = info_contacto.get("number")
                pushname = info_contacto.get("pushname") or info_contacto.get("name")
                if real_number:
                    try:
                        import sam_bot_service
                        cliente = sam_bot_service.buscar_cliente_por_celular(real_number, db)
                    except Exception:
                        pass

                if not cliente and pushname:
                    try:
                        import sam_bot_service
                        c_match, _ = sam_bot_service.buscar_cliente_por_nombre(pushname, db)
                        if c_match:
                            cliente = c_match
                        else:
                            pushname_fallback = pushname
                    except Exception:
                        pushname_fallback = pushname

                if cliente:
                    try:
                        db.query(models.WhatsAppMensajeChat).filter(
                            (models.WhatsAppMensajeChat.numero == num_limpio) |
                            (models.WhatsAppMensajeChat.numero == numero_decodificado)
                        ).update({"cliente_id": cliente.id}, synchronize_session=False)
                        db.commit()
                    except Exception:
                        db.rollback()

        cliente_data = None
        if cliente:
            cliente_data = {
                "id": cliente.id,
                "nombre": cliente.nombre,
                "cedula": getattr(cliente, "cedula", "N/A") or "N/A",
                "celular": getattr(cliente, "celular", "N/A") or "N/A",
                "plan": getattr(cliente, "plan", "No especificado") or "No especificado",
                "saldo": float(cliente.saldo or 0.0) if hasattr(cliente, 'saldo') and cliente.saldo else 0.0,
                "estado": getattr(cliente, "estado", "Activo") or "Activo",
                "nodo": getattr(cliente, "nodo", "N/A") or "N/A",
                "ip": getattr(cliente, "ip", "N/A") or "N/A",
                "parroquia": getattr(cliente, "parroquia", "N/A") or "N/A",
                "direccion": getattr(cliente, "direccion", "N/A") or "N/A"
            }
        elif pushname_fallback:
            cliente_data = {
                "id": None,
                "nombre": f"{pushname_fallback} (WhatsApp)",
                "cedula": "N/A",
                "celular": numero_decodificado,
                "plan": "No registrado",
                "saldo": 0.0,
                "estado": "WhatsApp",
                "nodo": "N/A",
                "ip": "N/A",
                "parroquia": "N/A",
                "direccion": "N/A"
            }

        return {
            "numero": num_limpio,
            "cliente": cliente_data,
            "mensajes": [
                {
                    "id": m.id,
                    "rol": m.rol,
                    "mensaje": m.mensaje,
                    "tipo": m.tipo,
                    "fecha_hora": m.fecha_hora.strftime("%Y-%m-%d %H:%M:%S") if m.fecha_hora else ""
                }
                for m in mensajes
            ]
        }
    except Exception as e:
        print(f"[Error Obtener Chat] {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/conversaciones/{numero:path}/enviar", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def enviar_mensaje_desde_chat(
    numero: str,
    payload: EnviarMensajeChatPayload,
    db: Session = Depends(get_db)
):
    """
    Permite al operador enviar un mensaje directo al cliente desde la interfaz de chat.
    Despacha a WhatsApp (incluyendo JIDs @lid) y lo registra con rol 'operador', conservando hasta 100 mensajes.
    Pausa automáticamente el bot SAM durante 5 minutos para que el operador atienda la conversación.
    """
    try:
        numero_decodificado = urllib.parse.unquote(numero).strip()
        texto = payload.mensaje.strip() if payload.mensaje else ""
        if not texto:
            raise HTTPException(status_code=400, detail="El mensaje no puede estar vacío")

        # 1. Enviar a través de WhatsApp (whatsapp_service y bridge ya preservan @lid)
        success = whatsapp_service.send_whatsapp_message(numero_decodificado, texto)

        # 2. Registrar en la base de datos aplicando la regla de 100 mensajes
        nuevo_msg = registrar_mensaje_chat(db, numero_decodificado, "operador", texto)

        # 3. Pausar las respuestas automáticas de SAM por 5 minutos para este contacto
        try:
            import sam_bot_service
            sam_bot_service.pausar_bot_por_operador(numero_decodificado)
        except Exception as e_pause:
            print(f"[WhatsApp Chat] Error pausando SAM: {e_pause}")

        if not success:
            raise HTTPException(
                status_code=500,
                detail="No se pudo enviar el mensaje a WhatsApp. Verifica que el servicio esté conectado."
            )

        return {
            "success": True,
            "mensaje": {
                "id": nuevo_msg.id if nuevo_msg else None,
                "rol": "operador",
                "mensaje": texto,
                "tipo": "texto",
                "fecha_hora": datetime.now(ECUADOR_TZ).strftime("%Y-%m-%d %H:%M:%S")
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"[Error Enviar Mensaje Chat] {e}")
        raise HTTPException(status_code=500, detail=str(e))

class VincularClienteChatPayload(BaseModel):
    cliente_id: int

@router.post("/conversaciones/{numero:path}/vincular-cliente", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def vincular_cliente_a_chat(
    numero: str,
    payload: VincularClienteChatPayload,
    db: Session = Depends(get_db)
):
    """
    Permite vincular manualmente una conversación telefónica o @lid a un cliente específico de la base de datos.
    """
    numero_decodificado = urllib.parse.unquote(numero).strip()
    cliente = db.query(models.Cliente).filter(models.Cliente.id == payload.cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado en la base de datos")

    db.query(models.WhatsAppMensajeChat).filter(
        (models.WhatsAppMensajeChat.numero == numero_decodificado) |
        (models.WhatsAppMensajeChat.numero == numero)
    ).update({"cliente_id": cliente.id}, synchronize_session=False)
    db.commit()

    return {
        "success": True,
        "message": f"Conversación vinculada al cliente {cliente.nombre} (ID #{cliente.id})",
        "cliente": {
            "id": cliente.id,
            "nombre": cliente.nombre,
            "cedula": getattr(cliente, "cedula", "N/A") or "N/A",
            "celular": getattr(cliente, "celular", "N/A") or "N/A",
            "plan": getattr(cliente, "plan", "No especificado") or "No especificado",
            "saldo": float(cliente.saldo or 0.0) if hasattr(cliente, 'saldo') and cliente.saldo else 0.0,
            "estado": getattr(cliente, "estado", "Activo") or "Activo",
            "nodo": getattr(cliente, "nodo", "N/A") or "N/A",
            "ip": getattr(cliente, "ip", "N/A") or "N/A",
            "parroquia": getattr(cliente, "parroquia", "N/A") or "N/A",
            "direccion": getattr(cliente, "direccion", "N/A") or "N/A"
        }
    }

@router.get("/buscar-clientes-chat", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def buscar_clientes_para_chat(q: str = "", db: Session = Depends(get_db)):
    """Busca clientes por ID, nombre, cédula, celular o IP para vincular a un chat"""
    if not q or len(q.strip()) < 1:
        return []
    texto = q.strip()
    filtros = [
        models.Cliente.nombre.ilike(f"%{texto}%"),
        models.Cliente.celular.ilike(f"%{texto}%"),
        models.Cliente.cedula.ilike(f"%{texto}%"),
        models.Cliente.ip.ilike(f"%{texto}%")
    ]
    if texto.isdigit():
        try:
            filtros.append(models.Cliente.id == int(texto))
        except Exception:
            pass

    clientes = db.query(models.Cliente).filter(or_(*filtros)).limit(15).all()
    return [
        {
            "id": c.id,
            "nombre": c.nombre,
            "celular": c.celular,
            "cedula": c.cedula,
            "plan": c.plan,
            "nodo": c.nodo,
            "ip": getattr(c, "ip", "N/A") or "N/A"
        }
        for c in clientes
    ]


# ========================================================================
# CRUD DE ADMINISTRADORES DE WHATSAPP
# ========================================================================

@router.get("/administradores", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def listar_administradores_whatsapp(db: Session = Depends(get_db)):
    """Obtiene la lista de números telefónicos autorizados como Administradores en WhatsApp"""
    try:
        admins = db.query(models.WhatsAppAdministrador).order_by(models.WhatsAppAdministrador.fecha_creacion.desc()).all()
        return [
            {
                "id": a.id,
                "numero": a.numero,
                "nombre": a.nombre,
                "permisos": a.permisos or "admin_total",
                "activo": a.activo,
                "fecha_creacion": a.fecha_creacion.strftime("%Y-%m-%d %H:%M:%S") if a.fecha_creacion else None
            }
            for a in admins
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al listar administradores: {str(e)}")

@router.post("/administradores", dependencies=[Depends(require_role(["administrador"]))])
def crear_administrador_whatsapp(
    payload: schemas.WhatsAppAdministradorCreate,
    db: Session = Depends(get_db)
):
    """Registra un nuevo número telefónico autorizado como Administrador"""
    try:
        if not payload.numero or not payload.nombre:
            raise HTTPException(status_code=400, detail="El número y el nombre son obligatorios")
            
        num_limpio = whatsapp_service.format_whatsapp_number(payload.numero)
        if not num_limpio:
            raise HTTPException(status_code=400, detail="Número de teléfono inválido")

        # Verificar si ya existe
        existente = db.query(models.WhatsAppAdministrador).filter(
            models.WhatsAppAdministrador.numero == num_limpio
        ).first()
        
        if existente:
            raise HTTPException(status_code=400, detail=f"El número {num_limpio} ya se encuentra registrado como Administrador.")

        nuevo_admin = models.WhatsAppAdministrador(
            numero=num_limpio,
            nombre=payload.nombre.strip(),
            permisos=payload.permisos or "admin_total",
            activo=payload.activo if payload.activo is not None else True,
            fecha_creacion=datetime.now(ECUADOR_TZ)
        )
        db.add(nuevo_admin)
        db.commit()
        db.refresh(nuevo_admin)

        return {
            "success": True,
            "message": f"Administrador {nuevo_admin.nombre} registrado exitosamente",
            "id": nuevo_admin.id
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al registrar administrador: {str(e)}")

@router.patch("/administradores/{admin_id}", dependencies=[Depends(require_role(["administrador"]))])
def actualizar_administrador_whatsapp(
    admin_id: int,
    payload: schemas.WhatsAppAdministradorUpdate,
    db: Session = Depends(get_db)
):
    """Actualiza la información de un número administrador"""
    try:
        admin = db.query(models.WhatsAppAdministrador).filter(
            models.WhatsAppAdministrador.id == admin_id
        ).first()

        if not admin:
            raise HTTPException(status_code=404, detail="Administrador no encontrado")

        if payload.nombre is not None:
            admin.nombre = payload.nombre.strip()

        if payload.numero is not None:
            num_limpio = whatsapp_service.format_whatsapp_number(payload.numero)
            if num_limpio:
                admin.numero = num_limpio

        if payload.permisos is not None:
            admin.permisos = payload.permisos

        if payload.activo is not None:
            admin.activo = payload.activo

        db.commit()
        return {"success": True, "message": "Administrador actualizado correctamente"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al actualizar administrador: {str(e)}")

@router.delete("/administradores/{admin_id}", dependencies=[Depends(require_role(["administrador"]))])
def eliminar_administrador_whatsapp(
    admin_id: int,
    db: Session = Depends(get_db)
):
    """Elimina un número administrador"""
    try:
        admin = db.query(models.WhatsAppAdministrador).filter(
            models.WhatsAppAdministrador.id == admin_id
        ).first()

        if not admin:
            raise HTTPException(status_code=404, detail="Administrador no encontrado")

        db.delete(admin)
        db.commit()
        return {"success": True, "message": "Administrador eliminado correctamente"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al eliminar administrador: {str(e)}")


