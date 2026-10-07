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
import time
import random
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

    def _parse_val(v):
        if v is None or v == "": return 0.0
        try:
            return float(str(v).replace("$", "").replace(",", ".").strip())
        except (ValueError, TypeError):
            return 0.0

    total_guardado = _parse_val(getattr(cliente, "total_pago", None))
    s_val = _parse_val(getattr(cliente, "saldo", 0.0))
    p_val = _parse_val(getattr(cliente, "plus", 0.0))
    a_val = _parse_val(getattr(cliente, "adicional", 0.0))
    calc_total = max(0.0, s_val + p_val + a_val)

    if total_guardado > 0 and total_guardado >= calc_total:
        saldo_val = total_guardado
    else:
        saldo_val = calc_total

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

def registrar_mensaje_chat(db: Session, numero: str, rol: str, mensaje: str, cliente_id: int = None, tipo: str = "texto", nombre_remitente: str = ""):
    """
    Registra un mensaje en el historial del chat y vincula automáticamente al cliente en la base de datos:
    Guarda hasta 100 mensajes por número telefónico o identificador @lid.
    Resuelve automáticamente el cliente_id desde la BD por teléfono o nombre.
    """
    if not numero or not mensaje:
        return None

    num_limpio = whatsapp_service.format_whatsapp_number(numero)
    if not num_limpio:
        num_limpio = str(numero).strip()

    is_lid = "@lid" in str(num_limpio).lower() or str(numero).lower().endswith("@lid")

    # Si no tiene cliente_id asignado, buscar coincidencia automática en la BD
    if not cliente_id:
        # 1. Comprobar si ya existe algún mensaje previo con este número exacto que tenga cliente_id
        prev_msg = db.query(models.WhatsAppMensajeChat.cliente_id).filter(
            models.WhatsAppMensajeChat.numero == num_limpio,
            models.WhatsAppMensajeChat.cliente_id.isnot(None)
        ).order_by(models.WhatsAppMensajeChat.id.desc()).first()
        if prev_msg:
            cliente_id = prev_msg[0]

        # 2. Si se proporcionó nombre_remitente (desde webhook pushname), buscar directamente en la BD
        if not cliente_id and nombre_remitente:
            try:
                import sam_bot_service
                c_match, _ = sam_bot_service.buscar_cliente_por_nombre(nombre_remitente, db)
                if c_match:
                    cliente_id = c_match.id
            except Exception as e_nom:
                print(f"[registrar_mensaje_chat] Error vinculando por nombre_remitente '{nombre_remitente}': {e_nom}")

        # 3. Si es LID y aún no tenemos cliente_id, consultar contacto en el bridge
        if not cliente_id and is_lid:
            info_contacto = obtener_info_contacto_bridge(num_limpio)
            if info_contacto:
                real_number = info_contacto.get("number")
                pushname = info_contacto.get("pushname") or info_contacto.get("name")

                if real_number:
                    try:
                        import sam_bot_service
                        c = sam_bot_service.buscar_cliente_por_celular(real_number, db)
                        if c:
                            cliente_id = c.id
                    except Exception:
                        pass

                if not cliente_id and pushname:
                    try:
                        import sam_bot_service
                        c_match, _ = sam_bot_service.buscar_cliente_por_nombre(pushname, db)
                        if c_match:
                            cliente_id = c_match.id
                    except Exception:
                        pass

        # 4. Si es un número estándar (@c.us o dígitos), buscar por teléfono en la BD
        if not cliente_id and not is_lid:
            try:
                import sam_bot_service
                c = sam_bot_service.buscar_cliente_por_celular(num_limpio, db)
                if c:
                    cliente_id = c.id
            except Exception:
                pass

        # 5. Si aún no está vinculado, comprobar si el mensaje contiene una cédula o celular registrado
        if not cliente_id and mensaje:
            try:
                import sam_bot_service
                cand_id = sam_bot_service.extraer_identificador_cliente(str(mensaje))
                if cand_id:
                    c = sam_bot_service.buscar_cliente_por_cedula_o_celular(cand_id, db)
                    if c:
                        cliente_id = c.id
                        sam_bot_service.clientes_identificados_sesion[num_limpio] = c.id
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


def send_global_broadcast_task(
    mensaje: str,
    nodo: Optional[str],
    db_session_factory,
    estado: Optional[str] = "ACTIVO",
    delay_min: float = 30.0,
    delay_max: float = 120.0,
    batch_size: int = 10,
    batch_pause_min: float = 300.0,
    batch_pause_max: float = 600.0,
    desde_id: Optional[int] = None,
    hasta_id: Optional[int] = None,
    limite_mensajes: Optional[int] = None
):
    db = db_session_factory()
    import time
    import random
    from database import engine
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

        alcance_label = f"{estado_label} ({nodo_label}){rango_info}".strip()
        # Parámetros de pausas y lotes
        delay_a = float(delay_min) if delay_min and float(delay_min) >= 1.0 else 30.0
        delay_b = float(delay_max) if delay_max and float(delay_max) >= delay_a else max(delay_a, 120.0)
        tamano_lote = int(batch_size) if batch_size and int(batch_size) > 0 else 10
        pausa_lote_a = float(batch_pause_min) if batch_pause_min and float(batch_pause_min) >= 1.0 else 300.0
        pausa_lote_b = float(batch_pause_max) if batch_pause_max and float(batch_pause_max) >= pausa_lote_a else max(pausa_lote_a, 600.0)

        total_clientes = len(clientes)
        print(f"[Broadcast Task] Iniciando difusión masiva con protección anti-baneo a {total_clientes} clientes ({alcance_label}). Lotes: {tamano_lote}. Intervalo por mensaje: {delay_a:.1f}-{delay_b:.1f}s. Pausa entre lotes: {pausa_lote_a/60:.1f}-{pausa_lote_b/60:.1f} min.")
        
        # Registrar campaña de difusión en historial
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

        exitosos = 0
        fallidos = 0

        for idx, cliente in enumerate(clientes):
            numero = (cliente.celular or "").strip()
            if not numero:
                fallidos += 1
                continue

            mensaje_personalizado = personalizar_mensaje_cliente(mensaje, cliente)
            # send_whatsapp_message extrae y despacha a todos los números válidos del cliente si tiene más de uno
            success = whatsapp_service.send_whatsapp_message(numero, mensaje_personalizado)
            
            if success:
                exitosos += 1
                try:
                    targets = whatsapp_service.extract_all_whatsapp_numbers(numero)
                    for num_tgt in (targets if targets else [numero]):
                        registrar_mensaje_chat(db, num_tgt, "operador", mensaje_personalizado, cliente.id if cliente else None)
                except Exception:
                    pass
            else:
                fallidos += 1

            # Guardar en historial individual
            historial = models.WhatsAppHistorial(
                numero_destino=numero,
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

            # Lógica de pausas entre clientes y descanso entre lotes de 10
            if idx < total_clientes - 1:
                # Comprobar si completó un lote de 10 clientes (o tamano_lote)
                if (idx + 1) % tamano_lote == 0:
                    descanso_sec = random.uniform(pausa_lote_a, pausa_lote_b)
                    descanso_min = descanso_sec / 60.0
                    print(f"[Broadcast Task] 🛑 Lote de {tamano_lote} clientes completado ({idx + 1}/{total_clientes}). Pausa de descanso anti-bloqueo: {descanso_min:.2f} minutos ({int(descanso_sec)}s) antes del siguiente grupo...")
                    time.sleep(descanso_sec)
                else:
                    # Pausa aleatoria dentro del lote (entre 30 y 120 segundos)
                    delay_sec = random.uniform(delay_a, delay_b)
                    print(f"[Broadcast Task] Mensaje {idx + 1}/{total_clientes} enviado ({'Éxito' if success else 'Fallo'}). Pausa de {delay_sec:.1f}s...")
                    time.sleep(delay_sec)

        if difusion_registro:
            difusion_registro.estado = "completado"
            difusion_registro.total_exitosos = exitosos
            difusion_registro.total_fallidos = fallidos
            db.commit()

        print(f"[Broadcast Task] Envío masivo finalizado exitosamente. Exitosos: {exitosos}, Fallidos: {fallidos}")
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
        
        # Extraer todos los números posibles para buscar cliente y registrar
        targets = whatsapp_service.extract_all_whatsapp_numbers(numero)

        # Buscar si alguno de los números corresponde a un cliente en la BD para personalizar
        cliente = None
        for t in (targets if targets else [numero]):
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
            # Si el mensaje contiene variables o el cliente fue hallado, personalizar
            tiene_variables = bool(re.search(r'\{nombre\}|\{saldo\}|\{plan\}|\{cedula\}|\{nodo\}|\{parroquia\}|\{cliente\}', mensaje, re.IGNORECASE))
            if tiene_variables:
                mensaje_final = personalizar_mensaje_cliente(mensaje, cliente)

        # Enviar mensaje usando el servicio unificado a todos los números del destinatario
        success = whatsapp_service.send_whatsapp_message(numero, mensaje_final)
        
        if not success:
            raise HTTPException(
                status_code=500,
                detail="No se pudo enviar el mensaje a WhatsApp. Verifica que el servicio esté conectado y el número sea válido."
            )
        
        # Si se proporcionó historial_id (ej. reintento desde la interfaz), actualizar registro existente
        if payload.historial_id:
            historial = db.query(models.WhatsAppHistorial).filter(
                models.WhatsAppHistorial.id == payload.historial_id
            ).first()
            if historial:
                historial.estado = "enviado"
                historial.fecha_envio = datetime.now(ECUADOR_TZ).strftime("%Y-%m-%d %H:%M:%S")
                db.commit()
        else:
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

        # Guardar en el chat bidireccional del cliente para cada número
        try:
            for t in (targets if targets else [numero]):
                registrar_mensaje_chat(db, t, "operador", mensaje_final, cliente.id if cliente else None)
        except Exception as chat_err:
            print(f"[Chat Warning] Error al registrar en chat: {chat_err}")
        
        return {
            "success": True,
            "message": f"Mensaje enviado a {numero}",
            "numero": numero,
            "destinatarios": targets
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
        elif recurrencia == "mensual":
            ahora_ec = datetime.now(ECUADOR_TZ)
            dia_target = dia_mes if (dia_mes and 1 <= dia_mes <= 31) else 1
            try:
                fecha_obj = ahora_ec.replace(day=dia_target, hour=0, minute=0, second=0, microsecond=0)
            except ValueError:
                fecha_obj = ahora_ec.replace(day=28, hour=0, minute=0, second=0, microsecond=0)
        
        # Guardar configuración programada
        filtro_clientes = payload.filtro_clientes or "todos"
        config = models.WhatsAppConfiguracion(
            hora_programada=hora,
            mensaje_programado=mensaje,
            activo=True,
            enviar_a_todos=(filtro_clientes == "todos"),
            filtro_clientes=filtro_clientes,
            fecha_programada=fecha_obj,
            recurrencia=recurrencia,
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

def _calcular_proximo_envio(config: models.WhatsAppConfiguracion) -> str:
    try:
        ahora = datetime.now(ECUADOR_TZ)
        hora_partes = config.hora_programada.split(":")
        hora_int = int(hora_partes[0])
        min_int = int(hora_partes[1])
        rec = getattr(config, 'recurrencia', 'diario') or 'diario'
        
        if rec == "diario":
            hora_hoy = ahora.replace(hour=hora_int, minute=min_int, second=0, microsecond=0)
            if ahora < hora_hoy:
                return f"Hoy a las {config.hora_programada}"
            else:
                return f"Mañana a las {config.hora_programada}"
        elif rec == "mensual":
            dia = config.fecha_programada.day if config.fecha_programada else 1
            try:
                fecha_este_mes = ahora.replace(day=dia, hour=hora_int, minute=min_int, second=0, microsecond=0)
            except ValueError:
                fecha_este_mes = ahora.replace(day=28, hour=hora_int, minute=min_int, second=0, microsecond=0)
            
            meses_es = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
            if ahora < fecha_este_mes:
                mes_nombre = meses_es[fecha_este_mes.month - 1]
                return f"{dia} de {mes_nombre} a las {config.hora_programada}"
            else:
                mes_siguiente = ahora.month + 1 if ahora.month < 12 else 1
                mes_nombre = meses_es[mes_siguiente - 1]
                return f"{dia} de {mes_nombre} a las {config.hora_programada}"
        elif rec == "unico":
            if config.fecha_programada:
                return f"{config.fecha_programada.strftime('%Y-%m-%d')} a las {config.hora_programada}"
            return f"A las {config.hora_programada}"
        return f"A las {config.hora_programada}"
    except Exception:
        return f"A las {config.hora_programada}"

@router.get("/configuraciones", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def listar_configuraciones(db: Session = Depends(get_db)):
    """Obtiene la lista de todas las configuraciones de envíos programados (recurrentes mensuales, diarios y únicos)"""
    try:
        configs = db.query(models.WhatsAppConfiguracion).order_by(
            models.WhatsAppConfiguracion.id.desc()
        ).all()
        
        resultado = []
        for c in configs:
            dia_m = c.fecha_programada.day if c.fecha_programada else 1
            fecha_str = c.fecha_programada.strftime("%Y-%m-%d") if c.fecha_programada else None
            resultado.append({
                "id": c.id,
                "hora": c.hora_programada,
                "mensaje": c.mensaje_programado,
                "activo": c.activo,
                "enviar_a_todos": c.enviar_a_todos,
                "filtro_clientes": getattr(c, 'filtro_clientes', 'todos') or 'todos',
                "recurrencia": getattr(c, 'recurrencia', 'diario') or 'diario',
                "dia_mes": dia_m,
                "fecha": fecha_str,
                "proximo_envio": _calcular_proximo_envio(c)
            })
        return resultado
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
        dia_m = config.fecha_programada.day if config.fecha_programada else 1
        
        return {
            "configurado": True,
            "hora": config.hora_programada,
            "mensaje": config.mensaje_programado,
            "enviar_a_todos": config.enviar_a_todos,
            "filtro_clientes": getattr(config, 'filtro_clientes', 'todos') or 'todos',
            "fecha": fecha_str,
            "dia_mes": dia_m,
            "recurrencia": getattr(config, 'recurrencia', 'diario') or 'diario',
            "proximo_envio": _calcular_proximo_envio(config),
            "id": config.id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.patch("/configuracion/{config_id}/toggle-activo", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def toggle_activo_configuracion(config_id: int, db: Session = Depends(get_db)):
    """Alterna el estado activo/pausado de una configuración de envío programado"""
    try:
        config = db.query(models.WhatsAppConfiguracion).filter(
            models.WhatsAppConfiguracion.id == config_id
        ).first()
        if not config:
            raise HTTPException(status_code=404, detail="Configuración no encontrada")
        config.activo = not config.activo
        db.commit()
        return {
            "success": True,
            "activo": config.activo,
            "message": f"Envío {'activado' if config.activo else 'pausado'} exitosamente"
        }
    except Exception as e:
        db.rollback()
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
            
        if payload.filtro_clientes is not None:
            config.filtro_clientes = payload.filtro_clientes
            config.enviar_a_todos = (payload.filtro_clientes == "todos")
        elif payload.enviar_a_todos is not None:
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
        elif payload.dia_mes is not None and (payload.recurrencia == "mensual" or config.recurrencia == "mensual"):
            ahora_ec = datetime.now(ECUADOR_TZ)
            dia_target = min(max(payload.dia_mes, 1), 31)
            try:
                config.fecha_programada = ahora_ec.replace(day=dia_target, hour=0, minute=0, second=0, microsecond=0)
            except ValueError:
                config.fecha_programada = ahora_ec.replace(day=28, hour=0, minute=0, second=0, microsecond=0)
        
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
    limite: int = 100,
    db: Session = Depends(get_db)
):
    """Obtiene el historial de mensajes individuales y el historial de difusiones masivas / envíos programados"""
    try:
        # Asegurar existencia de la tabla
        try:
            from database import engine
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

        # Si aún no hay difusiones en la nueva tabla, sintetizar desde el historial previo
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
    db: Session = Depends(get_db)
):
    """
    Reintenta el envío de todos los mensajes con estado 'fallido' en el historial.
    Procesa clientes con números múltiples o separados correctamente enviando a todos sus números.
    """
    try:
        fallidos = db.query(models.WhatsAppHistorial).filter(
            models.WhatsAppHistorial.estado == "fallido"
        ).all()

        if not fallidos:
            return {
                "success": True, 
                "message": "No hay mensajes fallidos pendientes de reintento.", 
                "total": 0, 
                "reintentados": 0
            }

        total = len(fallidos)
        reintentados = 0
        errores = 0

        for item in fallidos:
            try:
                numero = item.numero_destino
                msg = item.mensaje
                # send_whatsapp_message enviará a todos los números del destinatario
                ok = whatsapp_service.send_whatsapp_message(numero, msg)
                if ok:
                    item.estado = "enviado"
                    item.fecha_envio = datetime.now(ECUADOR_TZ).strftime("%Y-%m-%d %H:%M:%S")
                    reintentados += 1
                    db.commit()
                    # Registrar en el chat para cada número extraído
                    try:
                        targets = whatsapp_service.extract_all_whatsapp_numbers(numero)
                        for t in (targets if targets else [numero]):
                            registrar_mensaje_chat(db, t, "operador", msg)
                    except Exception:
                        pass
                    time.sleep(1.5)
                else:
                    errores += 1
            except Exception as e_retry:
                print(f"[Retry Error] Error reintentando mensaje {item.id}: {e_retry}")
                errores += 1

        return {
            "success": True,
            "message": f"Reintento finalizado. Exitosos: {reintentados}, Errores: {errores}",
            "total": total,
            "reintentados": reintentados,
            "errores": errores
        }
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
    Envía un mensaje de difusión de WhatsApp según el estado de cliente y nodo seleccionado.
    El envío se realiza en segundo plano (asíncronamente) con protección anti-baneo y pausas aleatorias.
    """
    if not payload.mensaje:
        raise HTTPException(status_code=400, detail="El mensaje no puede estar vacío.")
    
    # Encolar la tarea en background con lotes de 10, pausas de 30-120s y descansos de 5-10min
    background_tasks.add_task(
        send_global_broadcast_task,
        payload.mensaje,
        payload.nodo,
        SessionLocal,
        payload.estado or "ACTIVO",
        payload.delay_min if payload.delay_min is not None else 30.0,
        payload.delay_max if payload.delay_max is not None else 120.0,
        payload.batch_size if payload.batch_size is not None else 10,
        payload.batch_pause_min if payload.batch_pause_min is not None else 300.0,
        payload.batch_pause_max if payload.batch_pause_max is not None else 600.0,
        payload.desde_id,
        payload.hasta_id,
        payload.limite_mensajes
    )
    
    msg_detalle = "Difusión masiva iniciada en segundo plano con protección anti-bloqueo."
    if payload.limite_mensajes:
        msg_detalle = f"Difusión iniciada en segundo plano para {payload.limite_mensajes} clientes (iniciando desde ID {payload.desde_id or 'primer registro'})."

    return {
        "success": True,
        "message": msg_detalle
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
    Webhook principal que recibe mensajes entrantes de WhatsApp desde el puente local (Node.js).
    Orquestado al 100% por IA (Groq Tool Calling), con resolución de identificadores LID y
    desactivación total del 'Skill Router' obsoleto para evitar tickets vacíos.
    """
    try:
        import whatsapp_service
        import sam_bot_service
        from chatbot_service import procesar_mensaje_con_herramientas, resolver_identidad_whatsapp

        mensaje = (payload.mensaje or "").strip()
        if not mensaje:
            return {"success": True, "response": ""}

        # 1. Descartar eventos o notificaciones internas del protocolo de WhatsApp
        if mensaje.startswith("[NON_TEXT_MSG]"):
            tipo_rec = mensaje.replace("[NON_TEXT_MSG]", "").strip().lower()
            if any(t in tipo_rec for t in ["notification", "protocol", "cipher", "call", "broadcast", "status"]):
                return {"success": True, "response": ""}

        # 2. Resolución de Identidad: detecta si es un @lid o número celular real
        identidad = resolver_identidad_whatsapp(
            numero_raw=payload.numero,
            jid_original=payload.jid_original or ""
        )
        jid_destino = identidad["jid_destino"]
        tel_real = identidad["telefono_limpio"]

        # Si aún no tenemos tel_real y el remitente es un LID, intentar resolverlo mediante el bridge o BD
        if not tel_real and (identidad["es_lid"] or "@lid" in str(jid_destino).lower()):
            # A. Consultar al bridge si ya resolvió el teléfono para este LID
            info_contacto = obtener_info_contacto_bridge(jid_destino)
            if info_contacto and info_contacto.get("number"):
                num_c = re.sub(r'\D', '', str(info_contacto["number"]))
                if 8 <= len(num_c) <= 13:
                    tel_real = num_c

            # B. Si no se resolvió por bridge, revisar en BD si este LID ya tuvo mensajes asociados a un cliente_id
            if not tel_real:
                prev_chat = db.query(models.WhatsAppMensajeChat).filter(
                    models.WhatsAppMensajeChat.numero == jid_destino,
                    models.WhatsAppMensajeChat.cliente_id.isnot(None)
                ).order_by(models.WhatsAppMensajeChat.id.desc()).first()
                if prev_chat and prev_chat.cliente_id:
                    c_asoc = db.query(models.Cliente).filter(models.Cliente.id == prev_chat.cliente_id).first()
                    if c_asoc and c_asoc.celular:
                        tel_real = re.sub(r'\D', '', str(c_asoc.celular))

            # Si se logró resolver tel_real, actualizar la metadata para Groq
            if tel_real:
                identidad["es_lid"] = False
                identidad["telefono_limpio"] = tel_real
                identidad["metadata_ia"] = (
                    f"El cliente escribe desde el número celular registrado '{tel_real}'. "
                    f"Tu PRIMERA ACCIÓN OBLIGATORIA ante cualquier consulta, saludo o reclamo es ejecutar "
                    f"'consultar_estado_cliente(identificador='{tel_real}')' para verificar su contrato, saldo y servicio. "
                    "Si la herramienta encuentra sus datos, trátalo con calidez por su primer nombre y "
                    "NO LE PIDAS CÉDULA NI TELÉFONO. "
                    "REGLA CRÍTICA: Si el usuario únicamente saluda ('hola', 'buenas'), responde exclusivamente con un saludo cálido y pregunta amablemente en qué le colaboras hoy. "
                    "PROHIBIDO cobrarle, mencionarle moras, saldos o enviarle cuentas bancarias en un simple saludo."
                )

        # C. Comprobar si el cliente ya fue identificado en la sesión o si proporcionó cédula/celular en el mensaje
        cand_id = sam_bot_service.extraer_identificador_cliente(mensaje)
        c_por_msg = None
        if cand_id:
            c_por_msg = sam_bot_service.buscar_cliente_por_cedula_o_celular(cand_id, db)
        elif sam_bot_service.clientes_identificados_sesion.get(jid_destino):
            c_id = sam_bot_service.clientes_identificados_sesion[jid_destino]
            c_por_msg = db.query(models.Cliente).filter(models.Cliente.id == c_id).first()
        elif payload.numero and sam_bot_service.clientes_identificados_sesion.get(payload.numero):
            c_id = sam_bot_service.clientes_identificados_sesion[payload.numero]
            c_por_msg = db.query(models.Cliente).filter(models.Cliente.id == c_id).first()
        elif tel_real and sam_bot_service.clientes_identificados_sesion.get(tel_real):
            c_id = sam_bot_service.clientes_identificados_sesion[tel_real]
            c_por_msg = db.query(models.Cliente).filter(models.Cliente.id == c_id).first()

        # D. Si aún no está en memoria de sesión, consultar en MySQL si este chat ya tiene un cliente_id vinculado históricamente
        if not c_por_msg:
            nums_hist_cliente = [jid_destino]
            if tel_real:
                nums_hist_cliente.extend([tel_real, f"{tel_real}@c.us"])
            if payload.numero and payload.numero not in nums_hist_cliente:
                nums_hist_cliente.append(payload.numero)

            prev_chat_con_cid = db.query(models.WhatsAppMensajeChat.cliente_id).filter(
                models.WhatsAppMensajeChat.numero.in_(nums_hist_cliente),
                models.WhatsAppMensajeChat.cliente_id.isnot(None)
            ).order_by(models.WhatsAppMensajeChat.id.desc()).first()

            if prev_chat_con_cid and prev_chat_con_cid[0]:
                c_por_msg = db.query(models.Cliente).filter(models.Cliente.id == prev_chat_con_cid[0]).first()

        # E. Si aún no se encontró y tenemos tel_real, buscar directamente en BD por celular
        if not c_por_msg and tel_real:
            c_por_msg = sam_bot_service.buscar_cliente_por_celular(tel_real, db)

        if c_por_msg:
            sam_bot_service.clientes_identificados_sesion[jid_destino] = c_por_msg.id
            if payload.numero:
                sam_bot_service.clientes_identificados_sesion[payload.numero] = c_por_msg.id
            if tel_real:
                sam_bot_service.clientes_identificados_sesion[tel_real] = c_por_msg.id
            deuda_c = sam_bot_service.obtener_deuda_total_cliente(c_por_msg)
            identidad["metadata_ia"] = (
                f"El cliente ha sido identificado exitosamente en la base de datos como '{c_por_msg.nombre}' "
                f"(Cédula: {c_por_msg.cedula}, Celular registrado: {c_por_msg.celular}, Plan: {c_por_msg.plan or 'Internet'}, "
                f"Total pendiente: ${deuda_c['total']:.2f}{deuda_c['desglose']}). "
                f"Dirígete a él cordialmente por su primer nombre y responde directamente a su solicitud sin volver a pedirle cédula ni celular."
            )

        # 3. Verificar si el bot está en pausa por intervención de un operador humano
        if sam_bot_service.esta_bot_pausado_por_operador(jid_destino) or (payload.numero and sam_bot_service.esta_bot_pausado_por_operador(payload.numero)):
            registrar_mensaje_chat(db, jid_destino, "cliente", mensaje, cliente_id=c_por_msg.id if c_por_msg else None, nombre_remitente=payload.nombre or "")
            return {"success": True, "response": "", "pausado": True}

        # 4. Obtener historial previo de conversación (recuperación híbrida persistente: Base de Datos MySQL + RAM)
        numeros_filtro = [jid_destino]
        if tel_real:
            numeros_filtro.extend([tel_real, f"{tel_real}@c.us"])
        if payload.numero and payload.numero not in numeros_filtro:
            numeros_filtro.append(payload.numero)

        msgs_previos_db = db.query(models.WhatsAppMensajeChat).filter(
            models.WhatsAppMensajeChat.numero.in_(numeros_filtro)
        ).order_by(models.WhatsAppMensajeChat.id.desc()).limit(12).all()

        if msgs_previos_db:
            historial_previo = []
            for m in reversed(msgs_previos_db):
                rol_formato = "user" if m.rol == "cliente" else "assistant"
                historial_previo.append({"role": rol_formato, "content": m.mensaje})
        else:
            historial_previo = list(sam_bot_service.historial_conversaciones.get(jid_destino, []))

        # Registrar mensaje entrante del cliente en el historial persistente de chat
        cid_vinculado = c_por_msg.id if c_por_msg else None
        nuevo_msg_guardado = registrar_mensaje_chat(
            db, jid_destino, "cliente", mensaje,
            cliente_id=cid_vinculado,
            nombre_remitente=payload.nombre or ""
        )
        if nuevo_msg_guardado and nuevo_msg_guardado.cliente_id and not c_por_msg:
            c_por_msg = db.query(models.Cliente).filter(models.Cliente.id == nuevo_msg_guardado.cliente_id).first()
            if c_por_msg:
                sam_bot_service.clientes_identificados_sesion[jid_destino] = c_por_msg.id
                if tel_real:
                    sam_bot_service.clientes_identificados_sesion[tel_real] = c_por_msg.id

        sam_bot_service.guardar_mensaje_historial(jid_destino, "user", mensaje)

        # 5. Comando explícito de reinicio / cancelación
        if mensaje.lower() in ["cancelar", "salir", "menu", "menú", "inicio", "empezar de nuevo", "reset", "reiniciar"]:
            sam_bot_service.estados_skills[jid_destino] = None
            sam_bot_service.historial_conversaciones[jid_destino] = []
            sam_bot_service.clientes_identificados_sesion.pop(jid_destino, None)
            if payload.numero:
                sam_bot_service.clientes_identificados_sesion.pop(payload.numero, None)
            if tel_real:
                sam_bot_service.clientes_identificados_sesion.pop(tel_real, None)
            response_text = "¡Listo! He reiniciado la conversación. ¿En qué te puedo colaborar hoy con tus servicios de Opsatel? 😊"
            registrar_mensaje_chat(db, jid_destino, "asistente", response_text, cliente_id=c_por_msg.id if c_por_msg else None)
            sam_bot_service.guardar_mensaje_historial(jid_destino, "assistant", response_text)
            whatsapp_service.send_whatsapp_message(jid_destino, response_text)
            return {"success": True, "response": response_text}

        # 6. Comandos administrativos exclusivos (si el remitente es administrador)
        admin_obj = sam_bot_service.es_numero_administrador(
            jid_destino, db, jid_original=payload.jid_original,
            nombre_remitente=payload.nombre or "", telefono_real=tel_real
        )
        es_cmd_admin = admin_obj and (
            sam_bot_service.estados_skills.get(jid_destino) == "alta_instalacion_admin"
            or any(w in mensaje.lower() for w in [
                "caja", "cobro", "cobros", "recaudacion", "recaudación", "ingresos", "cierre",
                "moroso", "morosos", "corte", "cortes", "suspendido", "suspendidos", "deudores",
                "instalacion", "instalación", "nuevo cliente", "ingresar cliente", "registrar cliente",
                "registrar", "alta"
            ])
        )
        if es_cmd_admin:
            contexto = sam_bot_service.obtener_contexto_conversacion(jid_destino, mensaje)
            response_text = sam_bot_service.procesar_comando_administrador(jid_destino, mensaje, contexto, db, admin_obj)
            registrar_mensaje_chat(db, jid_destino, "asistente", response_text, cliente_id=c_por_msg.id if c_por_msg else None)
            sam_bot_service.guardar_mensaje_historial(jid_destino, "assistant", response_text)
            whatsapp_service.send_whatsapp_message(jid_destino, response_text)
            return {"success": True, "response": response_text}

        # 7. ORQUESTACIÓN PRINCIPAL CON IA (GROQ TOOL CALLING)
        # Bypasea el viejo "Skill Router" para que Groq identifique al cliente en MySQL
        # antes de ejecutar cualquier reinicio o generación de ticket
        response_text = procesar_mensaje_con_herramientas(
            mensaje=mensaje,
            numero=tel_real or jid_destino,
            db=db,
            historial_mensajes=historial_previo,
            metadata_identidad=identidad["metadata_ia"],
            cliente_id=c_por_msg.id if c_por_msg else None
        )

        # 8. Registrar respuesta del asistente y despachar por WhatsApp
        registrar_mensaje_chat(db, jid_destino, "asistente", response_text, cliente_id=c_por_msg.id if c_por_msg else None)
        sam_bot_service.guardar_mensaje_historial(jid_destino, "assistant", response_text)
        whatsapp_service.send_whatsapp_message(jid_destino, response_text)

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

        # Limpiar memoria de conversaciones en SAM Bot
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


