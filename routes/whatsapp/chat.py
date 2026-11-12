import re
import urllib.parse
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_, func

import models
import whatsapp_service
from database import get_db
from ..auth import require_role
from .schemas import EnviarMensajeChatPayload, VincularClienteChatPayload
from .utils import (
    ECUADOR_TZ,
    obtener_info_contacto_bridge,
    registrar_mensaje_chat
)

router = APIRouter()


# ========================================================================
# CHATS Y CONVERSACIONES POR CLIENTE (MÁXIMO 100 MENSAJES POR NÚMERO)
# ========================================================================

@router.get("/conversaciones", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def listar_conversaciones_chat(db: Session = Depends(get_db)):
    """
    Obtiene la lista de clientes con los que se tiene conversación activa,
    ordenados por la fecha del último mensaje recibido o enviado.
    Resuelve automáticamente nombres de contactos @lid a través del puente de WhatsApp.
    """
    try:
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
                "celular": getattr(cliente, "celular", "") if (cliente and cliente.celular) else (msg.numero if not is_lid else "No registrado"),
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


@router.delete("/conversaciones/all", dependencies=[Depends(require_role(["administrador"]))])
def eliminar_todas_las_conversaciones(db: Session = Depends(get_db)):
    """
    Elimina TODOS los mensajes de chat y conversaciones en vivo de WhatsApp.
    También limpia el historial y estados en memoria de SAM Bot.
    Acción exclusiva para administradores.
    """
    try:
        total_eliminados = db.query(models.WhatsAppMensajeChat).delete(synchronize_session=False)
        db.commit()

        try:
            import sam_bot_service
            if hasattr(sam_bot_service, "limpiar_todo_historial_conversaciones"):
                sam_bot_service.limpiar_todo_historial_conversaciones()
            else:
                sam_bot_service.historial_conversaciones.clear()
                sam_bot_service.estados_skills.clear()
                sam_bot_service.ultimas_interacciones.clear()
                sam_bot_service.pausas_operador.clear()
        except Exception as e_mem:
            print(f"[Aviso SAM] No se pudo limpiar la memoria: {e_mem}")

        return {
            "success": True,
            "message": f"Se han eliminado exitosamente {total_eliminados} mensajes. Todas las conversaciones en vivo han sido borradas.",
            "total_eliminados": total_eliminados
        }
    except Exception as e:
        db.rollback()
        print(f"[Error Eliminar Conversaciones] {e}")
        raise HTTPException(status_code=500, detail=f"Error al eliminar conversaciones: {str(e)}")


@router.get("/conversaciones/{numero:path}", dependencies=[Depends(require_role(["administrador", "secretario", "tecnico"]))])
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

        mensajes = db.query(models.WhatsAppMensajeChat).filter(
            (models.WhatsAppMensajeChat.numero == num_limpio) |
            (models.WhatsAppMensajeChat.numero == numero_decodificado) |
            (models.WhatsAppMensajeChat.numero == numero) |
            (models.WhatsAppMensajeChat.numero.like(f"%{num_solo_digitos}%"))
        ).order_by(models.WhatsAppMensajeChat.id.asc()).limit(100).all()

        cliente = None
        pushname_fallback = None

        for m in reversed(mensajes):
            if m.cliente_id:
                cliente = db.query(models.Cliente).filter(models.Cliente.id == m.cliente_id).first()
                if cliente:
                    break

        if not cliente and not is_lid:
            try:
                import sam_bot_service
                cliente = sam_bot_service.buscar_cliente_por_celular(num_limpio, db)
            except Exception:
                pass

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
                "celular": numero_decodificado if not is_lid else "No registrado",
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


@router.post("/conversaciones/{numero:path}/enviar", dependencies=[Depends(require_role(["administrador", "secretario", "tecnico"]))])
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

        success = whatsapp_service.send_whatsapp_message(numero_decodificado, texto)

        nuevo_msg = registrar_mensaje_chat(db, numero_decodificado, "operador", texto)

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


@router.delete("/conversaciones/{numero:path}", dependencies=[Depends(require_role(["administrador"]))])
def eliminar_conversacion_individual(numero: str, db: Session = Depends(get_db)):
    """
    Elimina los mensajes de chat de una conversación individual con un número o @lid.
    """
    try:
        numero_decodificado = urllib.parse.unquote(numero).strip()
        num_limpio = whatsapp_service.format_whatsapp_number(numero_decodificado)
        if not num_limpio:
            num_limpio = numero_decodificado

        num_solo_digitos = re.sub(r'\D', '', num_limpio)

        filtros = [
            models.WhatsAppMensajeChat.numero == num_limpio,
            models.WhatsAppMensajeChat.numero == numero_decodificado,
            models.WhatsAppMensajeChat.numero == numero
        ]
        if num_solo_digitos and "@lid" not in num_limpio:
            filtros.append(models.WhatsAppMensajeChat.numero.like(f"%{num_solo_digitos}%"))

        eliminados = db.query(models.WhatsAppMensajeChat).filter(or_(*filtros)).delete(synchronize_session=False)
        db.commit()

        try:
            import sam_bot_service
            if num_limpio in sam_bot_service.historial_conversaciones:
                sam_bot_service.historial_conversaciones.pop(num_limpio, None)
            if num_limpio in sam_bot_service.estados_skills:
                sam_bot_service.estados_skills.pop(num_limpio, None)
        except Exception:
            pass

        return {
            "success": True,
            "message": f"Conversación eliminada ({eliminados} mensajes eliminados).",
            "total_eliminados": eliminados
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al eliminar conversación: {str(e)}")


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
