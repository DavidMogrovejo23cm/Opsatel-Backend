"""
@file whatsapp.py
@author David Mogrovejo dmogrovejo87@gmail.com
@copyright (c) 2026 David Mogrovejo. All Rights Reserved.
@notice Developed with AI assistance.‍​‌​​​‌​​​‌‌​​​​‌​‌‌‌​‌‌​​‌‌​‌​​‌​‌‌​​‌​​​​‌​​​​​​‌​​‌‌​‌​‌‌​‌‌‌‌​‌‌​​‌‌‌​‌‌‌​​‌​​‌‌​‌‌‌‌​‌‌‌​‌‌​​‌‌​​‌​‌​‌‌​‌​‌​​‌‌​‌‌‌‌​​‌​​​​​​​‌​‌​​​​‌‌​​​‌‌​​‌​‌​​‌​​‌​​​​​​​‌‌​​‌​​​‌‌​​​​​​‌‌​​‌​​​‌‌​‌‌​​​‌​‌‌‌​​​‌​​​​​​‌​​​​​‌​‌‌​‌‌​​​‌‌​‌‌​​​​‌​​​​​​‌​‌​​‌​​‌‌​‌​​‌​‌‌​​‌‌‌​‌‌​‌​​​​‌‌‌​‌​​​‌‌‌​​‌‌​​‌​​​​​​‌​‌​​‌​​‌‌​​‌​‌​‌‌‌​​‌‌​‌‌​​‌​‌​‌‌‌​​‌​​‌‌‌​‌‌​​‌‌​​‌​‌​‌‌​​‌​​​​‌​‌‌‌​​​‌​​​​​​‌​​​‌​​​‌‌​​‌​‌​‌‌‌​‌‌​​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​‌‌‌‌​‌‌‌​​​​​‌‌​​‌​‌​‌‌​​‌​​​​‌​​​​​​‌‌‌​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​​‌​​​​​​‌​​​​​‌​‌​​‌​​‌​​‌​​​​​​‌‌​​​​‌​‌‌‌​​‌‌​‌‌‌​​‌‌​‌‌​‌​​‌​‌‌‌​​‌‌​‌‌‌​‌​​​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌‌​‌‌​​‌​‌​​‌​‌‌‌​​​‌​​​​​​‌​​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌‌​​‌‌‌​‌​​​‌‌​​​​‌​‌‌​​​‌‌​‌‌‌​‌​​​​‌‌‌​‌​​​‌​​​​​​‌‌​​‌​​​‌‌​‌‌​‌​‌‌​‌‌‌‌​‌‌​​‌‌‌​‌‌‌​​‌​​‌‌​‌‌‌‌​‌‌‌​‌‌​​‌‌​​‌​‌​‌‌​‌​‌​​‌‌​‌‌‌‌​​‌‌‌​​​​​‌‌​‌‌‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌​​​‌​​​​​​‌​​​‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌‌​​‌‌​‌‌​‌​​‌​‌‌​​​‌‌​​‌​​​​​​‌​‌​​‌‌​‌‌​‌​​‌​‌‌​​‌‌‌​​‌‌‌​‌​​​‌​​​​​​‌‌​​​‌​​‌‌​​‌‌​​​‌‌​​‌​​​‌‌​‌‌​​‌‌​​‌​‌​‌‌​​‌​‌​​‌‌​​​​​​‌‌​​‌‌​​‌‌​​‌‌​​‌‌​‌​​​​‌‌​​​‌​​‌‌‌​​​​‌‌​​‌​​​​‌‌​‌​‌​‌‌​​‌​​​‌‌​​​‌‌‍
@hash bf26ee033418d5dcd984ad8115334e7ce788cfb5d2bd456cf6e6ee21b877a762
"""
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import pytz
import models, schemas
from database import get_db, SessionLocal
from .auth import require_role
import traceback
import whatsapp_service

import requests
import os
import time
import random
from typing import Optional, List, Dict, Union, Any, Tuple
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
import time

# Caché anti-duplicados para respuestas de comprobantes por WhatsApp (número -> timestamp)
_ultimos_comprobantes_respondidos = {}

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
            # Variar el saludo entre destinatarios evita mensajes idénticos (señal de spam)
            saludo = random.choice([
                f"Hola *{primer_nombre}*,\n",
                f"¡Hola *{primer_nombre}*!\n",
                f"Saludos *{primer_nombre}*,\n",
                f"Estimado/a *{primer_nombre}*,\n",
            ])
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


# Control en memoria de cancelaciones en tiempo real
CANCELLED_DIFUSIONES = set()
GLOBAL_CANCEL_REQUESTED = False

def extract_port_number(val: Optional[str]) -> Optional[str]:
    if not val:
        return None
    s = str(val).strip()
    if '/' in s:
        parts = [p.strip() for p in s.split('/') if p.strip()]
        if parts:
            m = re.search(r'\d+', parts[-1])
            return m.group() if m else None
    m = re.search(r'\d+', s)
    return m.group() if m else None

def matches_puerto(cliente_puerto: Optional[str], selected_puertos: List[str]) -> bool:
    if not selected_puertos:
        return True
    if not cliente_puerto:
        return False
    c_str = str(cliente_puerto).strip().lower()
    c_num = extract_port_number(c_str)
    
    for sp in selected_puertos:
        s_str = str(sp).strip().lower()
        if c_str == s_str:
            return True
        s_num = extract_port_number(s_str)
        if s_num is not None and c_num is not None:
            if s_num == c_num:
                return True
        elif s_str in c_str or c_str in s_str:
            return True
    return False

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
    global GLOBAL_CANCEL_REQUESTED
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
            if GLOBAL_CANCEL_REQUESTED:
                return True
            if cur_dif_id and cur_dif_id in CANCELLED_DIFUSIONES:
                return True
            if cur_dif_id:
                try:
                    # Comprobar directamente en la base de datos si el estado cambió a 'cancelado'
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
            # Si el mensaje contiene variables o el cliente fue hallado, personalizar
            tiene_variables = bool(re.search(r'\{nombre\}|\{saldo\}|\{plan\}|\{cedula\}|\{nodo\}|\{parroquia\}|\{cliente\}', mensaje, re.IGNORECASE))
            if tiene_variables:
                mensaje_final = personalizar_mensaje_cliente(mensaje, cliente)

        # Enviar mensaje usando el servicio unificado únicamente al primer número del cliente
        success = whatsapp_service.send_whatsapp_message(primary_target, mensaje_final, priority="manual")
        
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
                numero_destino=primary_target,
                mensaje=mensaje_final,
                tipo_envio="manual",
                estado="enviado",
                fecha_envio=datetime.now(ECUADOR_TZ).strftime("%Y-%m-%d %H:%M:%S"),
                fecha_creacion=datetime.now(ECUADOR_TZ)
            )
            db.add(historial)
            db.commit()

        # Guardar en el chat bidireccional del cliente para el número al que realmente se envió
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
                "nodo": getattr(c, 'nodo', None),
                "recurrencia": getattr(c, 'recurrencia', 'diario') or 'diario',
                "dia_mes": dia_m,
                "fecha": fecha_str,
                "desde_cliente_id": getattr(c, 'desde_cliente_id', None),
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
            "nodo": getattr(config, 'nodo', None),
            "fecha": fecha_str,
            "dia_mes": dia_m,
            "recurrencia": getattr(config, 'recurrencia', 'diario') or 'diario',
            "desde_cliente_id": getattr(config, 'desde_cliente_id', None),
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

        if payload.desde_cliente_id is not None:
            if payload.desde_cliente_id and int(payload.desde_cliente_id) > 0:
                config.desde_cliente_id = int(payload.desde_cliente_id)
            else:
                config.desde_cliente_id = None

        if payload.nodo is not None:
            if payload.nodo == "vaciar" or str(payload.nodo).lower() in ["todos", "all", "todos los nodos", ""]:
                config.nodo = None
            else:
                config.nodo = payload.nodo.strip()
            
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

def _reintentar_fallidos_task(ids_fallidos: list):
    """
    Tarea en segundo plano: reintenta los mensajes fallidos uno a uno.
    Cada envío es 'bulk', por lo que el puente aplica horario, topes y espaciado anti-bloqueo.
    """
    global GLOBAL_CANCEL_REQUESTED
    db = SessionLocal()
    reintentados = 0
    errores = 0
    seen_destinos = set()
    try:
        for hist_id in ids_fallidos:
            if GLOBAL_CANCEL_REQUESTED:
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

                # Evitar reintentar dos veces al mismo destinatario con el mismo contenido
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
                    # Registrar en el chat para el número destino
                    try:
                        registrar_mensaje_chat(db, target_num, "operador", msg)
                    except Exception:
                        pass
                else:
                    errores += 1

                # Pausa interruptible
                deadline = time.time() + random.uniform(15, 30)
                while time.time() < deadline:
                    if GLOBAL_CANCEL_REQUESTED:
                        break
                    time.sleep(min(0.5, deadline - time.time()))
            except Exception as e_retry:
                db.rollback()
                print(f"[Retry Error] Error reintentando mensaje {hist_id}: {e_retry}")
                errores += 1
        print(f"[Retry Task] Reintento finalizado. Exitosos: {reintentados}, Errores: {errores}")
    finally:
        db.close()


@router.post("/historial/reintentar-fallidos", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def reintentar_mensajes_fallidos(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Reintenta en segundo plano el envío de todos los mensajes con estado 'fallido' en el historial.
    Se envían de forma escalonada (protección anti-bloqueo): puede tardar horas y respeta el horario permitido.
    """
    global GLOBAL_CANCEL_REQUESTED
    GLOBAL_CANCEL_REQUESTED = False
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
        
        # Notificar al puente local para resetear pausas si correspondía
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
    global GLOBAL_CANCEL_REQUESTED
    try:
        GLOBAL_CANCEL_REQUESTED = True
        
        # Marcar todas las difusiones 'en_proceso' como 'cancelado'
        actualizados = db.query(models.WhatsAppDifusionHistorial).filter(
            models.WhatsAppDifusionHistorial.estado == "en_proceso"
        ).update({"estado": "cancelado"}, synchronize_session=False)
        db.commit()
        
        # Notificar al bridge
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

# --- Estado y control del sistema anti-bloqueo del puente ---
@router.get("/antiban", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def antiban_estado():
    """Estado del gobernador anti-bloqueo (horario, topes, pausas, opt-outs)."""
    try:
        r = requests.get(f"{whatsapp_service.WHATSAPP_BRIDGE_URL.rstrip('/')}/antiban", timeout=5)
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Puente de WhatsApp no disponible: {e}")

@router.post("/antiban/restriccion", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def antiban_declarar_restriccion(horas: float = 24):
    """Declara una restricción de WhatsApp (ej. aviso 'Tu cuenta está restringida'): pausa los envíos masivos X horas
    y reinicia el calentamiento al terminar."""
    try:
        r = requests.post(f"{whatsapp_service.WHATSAPP_BRIDGE_URL.rstrip('/')}/antiban/restricted", json={"hours": horas}, timeout=5)
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Puente de WhatsApp no disponible: {e}")

@router.post("/antiban/reanudar", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def antiban_reanudar():
    """Levanta manualmente la pausa del envío masivo."""
    try:
        r = requests.post(f"{whatsapp_service.WHATSAPP_BRIDGE_URL.rstrip('/')}/antiban/clear", json={}, timeout=5)
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Puente de WhatsApp no disponible: {e}")

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
    global GLOBAL_CANCEL_REQUESTED
    GLOBAL_CANCEL_REQUESTED = False

    if not payload.mensaje:
        raise HTTPException(status_code=400, detail="El mensaje no puede estar vacío.")

    # 1. Crear el registro en la base de datos primero para tener el ID listo de inmediato
    db = SessionLocal()
    difusion_id = None
    try:
        from database import engine
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
    
    # Encolar la tarea en background pasando el difusion_id
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

from pydantic import BaseModel
from typing import Optional, List, Dict, Union, Any, Tuple
import urllib.parse

class WhatsAppWebhookPayload(BaseModel):
    numero: str
    mensaje: str
    nombre: Optional[str] = None
    jid_original: Optional[str] = None
    url_archivo: Optional[str] = None
    nombre_archivo: Optional[str] = None
    ruta_archivo: Optional[str] = None
    mimetype: Optional[str] = None
    tamano_bytes: Optional[int] = None
    es_documento_valido: Optional[bool] = None
    es_invalido: Optional[bool] = None
    ya_notificado_cliente: Optional[bool] = None

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

        # =========================================================================
        # 4.0 DESCARTE INMEDIATO DE IMÁGENES NO VÁLIDAS (NO COMPROBANTES)
        # Si la imagen no es un documento/comprobante válido, NUNCA enviar agradecimiento
        # =========================================================================
        es_imagen_invalida = bool(
            payload.es_documento_valido is False or
            payload.es_invalido is True or
            "[Imagen descartada" in mensaje or
            "[Imagen no válida]" in mensaje or
            "[Imagen recibida - Documento no válido]" in mensaje or
            "no es un comprobante válido" in mensaje.lower() or
            "la imagen mandada no es un documento valido" in mensaje.lower()
        )
        if es_imagen_invalida:
            resp_invalido = "La imagen enviada no es un documento válido. Por favor, envía un comprobante de pago o transferencia bancaria válido."
            url_img = payload.url_archivo or ""
            if not url_img:
                m_url = re.search(r'(?:https?://[^\s]+)?(/uploadscr/[a-zA-Z0-9_\-\.\/]+)', mensaje)
                if m_url:
                    url_img = m_url.group(1)

            msg_chat_user = f"📷 [Imagen recibida - No es un comprobante válido] {url_img}".strip()
            registrar_mensaje_chat(
                db, jid_destino, "cliente", msg_chat_user,
                cliente_id=c_por_msg.id if c_por_msg else None,
                tipo="multimedia",
                nombre_remitente=payload.nombre or ""
            )
            registrar_mensaje_chat(
                db, jid_destino, "asistente", resp_invalido,
                cliente_id=c_por_msg.id if c_por_msg else None
            )
            sam_bot_service.guardar_mensaje_historial(jid_destino, "user", msg_chat_user)
            sam_bot_service.guardar_mensaje_historial(jid_destino, "assistant", resp_invalido)

            if not payload.ya_notificado_cliente:
                try:
                    whatsapp_service.send_whatsapp_message(jid_destino, resp_invalido)
                except Exception as e_send_inv:
                    print(f"[WhatsApp] Aviso al enviar rechazo de documento inválido: {e_send_inv}")

            return {"success": False, "response": resp_invalido, "comprobante": False}

        # =========================================================================
        # 4.1 DETECCIÓN Y PROCESAMIENTO GARANTIZADO DE COMPROBANTES / IMÁGENES
        # Almacena en la tabla MySQL 'comprobantes', vincula al cliente y muestra en chat
        # =========================================================================
        es_comprobante = bool(
            payload.url_archivo or
            "uploadscr" in mensaje or
            mensaje.startswith("🧾 [Comprobante") or
            mensaje.startswith("[NON_TEXT_MSG] image") or
            mensaje.strip() == "[NON_TEXT_MSG] image" or
            (payload.mimetype and str(payload.mimetype).startswith("image/"))
        )

        if es_comprobante:
            asegurar_tabla_comprobantes(db)

            # A. Extraer o resolver URL y nombre del comprobante
            url_final = payload.url_archivo
            if not url_final:
                m_url = re.search(r'(?:https?://[^\s]+)?(/uploadscr/[a-zA-Z0-9_\-\.\/]+)', mensaje)
                if m_url:
                    url_final = m_url.group(1)

            nombre_archivo = payload.nombre_archivo or (os.path.basename(url_final) if url_final else None)

            # Si vino como [NON_TEXT_MSG] image sin URL, buscar en carpetas uploadscr el archivo guardado más reciente
            backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            candidatos_dir = [
                os.path.join(backend_dir, "uploadscr"),
                os.path.join(backend_dir, "uploads", "uploadscr"),
                os.path.join(backend_dir, "..", "Opsatel-Frontend", "uploadscr"),
                os.path.join(backend_dir, "..", "Opsatel-Frontend", "public", "uploadscr"),
                os.path.join(backend_dir, "..", "Opsatel-Frontend", "dist", "uploadscr"),
            ]
            if not url_final or not nombre_archivo:
                arch_reciente = None
                for c_dir in candidatos_dir:
                    if os.path.exists(c_dir):
                        try:
                            archivos = [os.path.join(c_dir, f) for f in os.listdir(c_dir) if os.path.isfile(os.path.join(c_dir, f))]
                            if archivos:
                                mas_nuevo = max(archivos, key=os.path.getmtime)
                                if (datetime.now().timestamp() - os.path.getmtime(mas_nuevo)) < 300:
                                    arch_reciente = os.path.basename(mas_nuevo)
                                    break
                        except Exception:
                            pass

                if arch_reciente:
                    nombre_archivo = arch_reciente
                    url_final = f"/uploadscr/{arch_reciente}"
                else:
                    ts_now = int(datetime.utcnow().timestamp())
                    t_dig = (tel_real or jid_destino).replace("@c.us", "").replace("@lid", "")
                    nombre_archivo = f"comp_{ts_now}_{t_dig}.jpg"
                    url_final = f"/uploadscr/{nombre_archivo}"

            ruta_archivo = payload.ruta_archivo or f"uploadscr/{nombre_archivo}"
            mimetype = payload.mimetype or "image/jpeg"
            tamano_bytes = payload.tamano_bytes or 0

            # Validación de documento financiero / comprobante:
            # Si el webhook ya trae información del OCR o si podemos verificar el archivo físico
            from services.ocr_comprobantes import analizar_comprobante_ocr
            ocr_verif = {}
            try:
                ocr_verif = analizar_comprobante_ocr(ruta_archivo or nombre_archivo)
            except Exception as e_ocr_err:
                print(f"[WhatsApp] Error analizando comprobante OCR en webhook: {e_ocr_err}")

            es_doc_valido = bool(ocr_verif and ocr_verif.get("es_documento_valido", False))
            if not es_doc_valido:
                # La imagen no contiene elementos de un comprobante válido: NUNCA enviar 'Muchas gracias'
                resp_invalido = "La imagen enviada no es un documento válido. Por favor, envía un comprobante de pago o transferencia bancaria válido."
                msg_formateado_chat = f"📷 [Imagen recibida - No es un comprobante válido] {url_final}"

                registrar_mensaje_chat(
                    db, jid_destino, "cliente", msg_formateado_chat,
                    cliente_id=c_por_msg.id if c_por_msg else None,
                    tipo="multimedia",
                    nombre_remitente=payload.nombre or ""
                )
                registrar_mensaje_chat(
                    db, jid_destino, "asistente", resp_invalido,
                    cliente_id=c_por_msg.id if c_por_msg else None
                )
                sam_bot_service.guardar_mensaje_historial(jid_destino, "user", msg_formateado_chat)
                sam_bot_service.guardar_mensaje_historial(jid_destino, "assistant", resp_invalido)

                if not payload.ya_notificado_cliente:
                    try:
                        whatsapp_service.send_whatsapp_message(jid_destino, resp_invalido)
                    except Exception as e_send_inv:
                        print(f"[WhatsApp] Aviso al enviar rechazo de documento inválido: {e_send_inv}")

                return {"success": False, "response": resp_invalido, "comprobante": False}

            # Extraer nota o mensaje adicional que el cliente haya escrito junto al comprobante
            texto_adjunto = ""
            if " - " in mensaje and not mensaje.startswith("[NON_TEXT_MSG]"):
                texto_adjunto = mensaje.split(" - ", 1)[1].strip()
            elif not mensaje.startswith("🧾") and not mensaje.startswith("[NON_TEXT_MSG]"):
                texto_adjunto = mensaje.strip()

            num_db = tel_real or jid_destino.replace("@c.us", "").replace("@lid", "")
            nombre_db = payload.nombre or (c_por_msg.nombre if c_por_msg else "Cliente WhatsApp")
            ahora_ec = datetime.now(ECUADOR_TZ).replace(tzinfo=None)

            # B. Insertar en la tabla 'comprobantes' de MySQL (evitando duplicar si ya se registró por endpoint)
            comp_existente = db.query(models.Comprobante).filter(
                (models.Comprobante.nombre_archivo == nombre_archivo) |
                (
                    (models.Comprobante.numero_telefono == num_db) &
                    (models.Comprobante.created_at >= datetime.utcnow() - timedelta(minutes=2))
                )
            ).first()

            if not comp_existente:
                eval_webhook = evaluar_validacion_comprobante(
                    db=db,
                    numero_raw=num_db,
                    nombre_remitente=nombre_db,
                    ocr_data=ocr_verif,
                    monto_final=ocr_verif.get("monto"),
                    referencia_final=ocr_verif.get("numero_referencia"),
                    nombre_archivo=nombre_archivo or "",
                    hash_imagen=ocr_verif.get("hash_imagen")
                )
                cli_wh = eval_webhook.get("cliente")
                cat_val = eval_webhook.get("categoria_validacion") or "CONFIRMACION_RECIBO"
                mot_val = eval_webhook.get("motivo_validacion") or ""
                ced_val = getattr(cli_wh, "cedula", None) if cli_wh else None
                es_dup_wh = bool(eval_webhook.get("es_duplicado", False))
                dup_det_wh = eval_webhook.get("duplicado_detalle")
                score_aut_wh = int(ocr_verif.get("score_autenticidad") or 0)

                nuevo_comp = models.Comprobante(
                    cliente_id=cli_wh.id if cli_wh else (c_por_msg.id if c_por_msg else None),
                    numero_telefono=eval_webhook.get("numero_limpio") or num_db,
                    nombre_remitente=nombre_db,
                    nombre_archivo=nombre_archivo,
                    ruta_archivo=ruta_archivo,
                    url_archivo=url_final,
                    mimetype=mimetype,
                    tamano_bytes=tamano_bytes,
                    mensaje_texto=texto_adjunto or "Comprobante de pago recibido por WhatsApp",
                    estado="PENDIENTE",
                    banco_origen=ocr_verif.get("banco_origen"),
                    banco_destino=ocr_verif.get("banco_destino"),
                    monto=eval_webhook.get("monto_evaluado"),
                    numero_referencia=ocr_verif.get("numero_referencia"),
                    cuenta_origen=ocr_verif.get("cuenta_origen"),
                    cuenta_destino=ocr_verif.get("cuenta_destino"),
                    beneficiario=ocr_verif.get("beneficiario"),
                    ordenante=ocr_verif.get("ordenante"),
                    fecha_comprobante=ocr_verif.get("fecha"),
                    texto_ocr=ocr_verif.get("texto_extraido"),
                    cedula_cliente=ced_val,
                    saldo_pendiente_bd=eval_webhook.get("saldo_pendiente_bd"),
                    categoria_validacion=cat_val,
                    motivo_validacion=mot_val,
                    hash_imagen=ocr_verif.get("hash_imagen"),
                    score_autenticidad=score_aut_wh,
                    es_duplicado=es_dup_wh,
                    duplicado_detalle=dup_det_wh,
                    observaciones=ocr_verif.get("resumen_ocr"),
                    fecha_hora=ahora_ec,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                db.add(nuevo_comp)
                db.commit()
                db.refresh(nuevo_comp)

                # Replicar en SQLite opsatel.db si existe
                try:
                    for db_sqlite in [os.path.join(backend_dir, "opsatel.db"), os.path.join(backend_dir, "..", "opsatel.db")]:
                        if os.path.exists(db_sqlite) and "sqlite" not in str(db.get_bind().url).lower():
                            import sqlite3
                            sc = sqlite3.connect(db_sqlite)
                            sc.execute("""
                                INSERT INTO comprobantes (
                                    cliente_id, numero_telefono, nombre_remitente, nombre_archivo,
                                    ruta_archivo, url_archivo, mimetype, tamano_bytes, mensaje_texto,
                                    estado, fecha_hora, created_at, updated_at
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDIENTE', ?, ?, ?)
                            """, (
                                c_por_msg.id if c_por_msg else None,
                                num_db,
                                nombre_db,
                                nombre_archivo,
                                ruta_archivo,
                                url_final,
                                mimetype,
                                tamano_bytes,
                                texto_adjunto or "Comprobante de pago recibido por WhatsApp",
                                ahora_ec.strftime("%Y-%m-%d %H:%M:%S"),
                                datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                                datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                            ))
                            sc.commit()
                            sc.close()
                except Exception as e_sq_sync:
                    print(f"[Comprobante] Aviso replicando a sqlite: {e_sq_sync}")

            # C. Registrar mensaje entrante en el chat persistente con URL de imagen y tipo multimedia
            msg_formateado_chat = f"🧾 [Comprobante guardado en uploadscr] {url_final}"
            if texto_adjunto:
                msg_formateado_chat += f" - {texto_adjunto}"

            registrar_mensaje_chat(
                db, jid_destino, "cliente", msg_formateado_chat,
                cliente_id=c_por_msg.id if c_por_msg else None,
                tipo="multimedia",
                nombre_remitente=payload.nombre or ""
            )
            sam_bot_service.guardar_mensaje_historial(jid_destino, "user", msg_formateado_chat)

            # Evitar responder dos veces: verificar si el cliente ya fue notificado o si ya se le envió confirmación recientemente
            ahora_ts = time.time()
            num_clean_track = re.sub(r'\D', '', str(num_db or jid_destino or ""))

            # Limpiar entradas antiguas (> 180s)
            for k, ts in list(_ultimos_comprobantes_respondidos.items()):
                if ahora_ts - ts > 180:
                    _ultimos_comprobantes_respondidos.pop(k, None)

            ya_respondido = False
            if num_clean_track and (ahora_ts - _ultimos_comprobantes_respondidos.get(num_clean_track, 0)) < 25:
                ya_respondido = True
            if jid_destino and (ahora_ts - _ultimos_comprobantes_respondidos.get(jid_destino, 0)) < 25:
                ya_respondido = True

            if ya_respondido:
                print(f"[WhatsApp Webhook] ⏭️ Confirmación de comprobante ya enviada recientemente a {num_clean_track or jid_destino}. Omitiendo envío duplicado.")
                return {"success": True, "response": "", "comprobante": True, "duplicado_omitido": True}

            if getattr(payload, "ya_notificado_cliente", False) or getattr(payload, "es_duplicado", False) or es_dup_wh:
                print(f"[WhatsApp Webhook] Cliente {num_clean_track or jid_destino} ya notificado o comprobante duplicado. Omitiendo mensaje de agradecimiento normal.")
                return {"success": True, "response": "", "comprobante": True, "ya_notificado": True}

            # D. Respuesta cordial de confirmación del comprobante (SIN saludo genérico de bienvenida)
            # Marcar de inmediato en el caché para asegurar que no se duplique
            if num_clean_track:
                _ultimos_comprobantes_respondidos[num_clean_track] = ahora_ts
            if jid_destino:
                _ultimos_comprobantes_respondidos[jid_destino] = ahora_ts

            resp_comprobante = (
                "¡Muchas gracias! 🧾 Hemos recibido tu comprobante de pago.\n"
                "Ha sido guardado en el sistema y remitido al área administrativa (+593 98 714 9097) para su verificación. ¡Que tengas un excelente día! 😊"
            )
            registrar_mensaje_chat(
                db, jid_destino, "asistente", resp_comprobante,
                cliente_id=c_por_msg.id if c_por_msg else None
            )
            sam_bot_service.guardar_mensaje_historial(jid_destino, "assistant", resp_comprobante)
            try:
                whatsapp_service.send_whatsapp_message(jid_destino, resp_comprobante)
            except Exception as e_send_w:
                print(f"[WhatsApp] Aviso al enviar confirmación de comprobante: {e_send_w}")

            return {"success": True, "response": resp_comprobante, "comprobante": True}

        # Registrar mensaje normal entrante del cliente en el historial persistente de chat
        cid_vinculado = c_por_msg.id if c_por_msg else None
        nuevo_msg_guardado = registrar_mensaje_chat(
            db, jid_destino, "cliente", mensaje,
            cliente_id=cid_vinculado,
            tipo="texto",
            nombre_remitente=payload.nombre or ""
        )
        if nuevo_msg_guardado and nuevo_msg_guardado.cliente_id and not c_por_msg:
            c_por_msg = db.query(models.Cliente).filter(models.Cliente.id == nuevo_msg_guardado.cliente_id).first()
            if c_por_msg:
                sam_bot_service.clientes_identificados_sesion[jid_destino] = c_por_msg.id
                if tel_real:
                    sam_bot_service.clientes_identificados_sesion[tel_real] = c_por_msg.id

        sam_bot_service.guardar_mensaje_historial(jid_destino, "user", mensaje)

        # Si es otro tipo de archivo no soportado directamente (video, audio, etc.)
        if mensaje.startswith("[NON_TEXT_MSG]"):
            tipo_media = mensaje.replace("[NON_TEXT_MSG]", "").strip().lower()
            resp_media = f"Hemos recibido tu archivo adjunto ({tipo_media}). Un asesor humano lo revisará en breve. ¡Muchas gracias!"
            registrar_mensaje_chat(db, jid_destino, "asistente", resp_media, cliente_id=c_por_msg.id if c_por_msg else None)
            sam_bot_service.guardar_mensaje_historial(jid_destino, "assistant", resp_media)
            try:
                whatsapp_service.send_whatsapp_message(jid_destino, resp_media)
            except Exception:
                pass
            return {"success": True, "response": resp_media}

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

        # 6.5 CONSULTA Y RECOMENDACIÓN DE PELÍCULAS (Base de Datos OPSATV + The Movie Database)
        # Se ejecuta ANTES de que interactúe la IA Groq general.
        # Consulta en la tabla 'peliculas' (nombre, descripcion, generos, actores, audio)
        # y si no existe busca en TMDb como sugerencia para solicitar.
        try:
            from services.movie_service import gestionar_consulta_peliculas
            resp_pelicula = gestionar_consulta_peliculas(mensaje=mensaje, db=db)
            if resp_pelicula:
                registrar_mensaje_chat(db, jid_destino, "asistente", resp_pelicula, cliente_id=c_por_msg.id if c_por_msg else None)
                sam_bot_service.guardar_mensaje_historial(jid_destino, "assistant", resp_pelicula)
                whatsapp_service.send_whatsapp_message(jid_destino, resp_pelicula)
                return {
                    "success": True,
                    "response": resp_pelicula,
                    "modulo": "peliculas"
                }
        except Exception as e_pel:
            print(f"[WhatsApp Webhook] Aviso al consultar módulo de películas: {e_pel}")

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


# ============================================================================
# DESTINOS DE REENVÍO AUTOMÁTICO DE COMPROBANTES OCR
# ============================================================================

def asegurar_tabla_destinos_ocr(db: Session):
    try:
        models.WhatsAppDestinoOCR.__table__.create(bind=db.get_bind(), checkfirst=True)
        total = db.query(models.WhatsAppDestinoOCR).count()
        if total == 0:
            def_admin = models.WhatsAppDestinoOCR(
                numero="593987149097",
                nombre="Administración Principal",
                activo=True
            )
            db.add(def_admin)
            db.commit()
    except Exception as e_seed:
        db.rollback()
        print(f"[Destinos OCR] Verificación de tabla: {e_seed}")


@router.get("/destinos-ocr")
def listar_destinos_ocr(db: Session = Depends(get_db)):
    """Lista todos los números configurados para recibir comprobantes OCR."""
    asegurar_tabla_destinos_ocr(db)
    destinos = db.query(models.WhatsAppDestinoOCR).order_by(models.WhatsAppDestinoOCR.id.asc()).all()
    return destinos


@router.get("/destinos-ocr-public")
def listar_destinos_ocr_publico(db: Session = Depends(get_db)):
    """Endpoint público rápido para el puente de WhatsApp (whatsapp_bridge.js)."""
    asegurar_tabla_destinos_ocr(db)
    destinos = db.query(models.WhatsAppDestinoOCR).filter(models.WhatsAppDestinoOCR.activo == True).all()
    return [
        {"id": d.id, "numero": d.numero, "nombre": d.nombre, "activo": d.activo}
        for d in destinos
    ]


@router.post("/destinos-ocr")
def crear_destino_ocr(payload: schemas.WhatsAppDestinoOCRCreate, db: Session = Depends(get_db)):
    """Registra un nuevo número para reenvío automático de comprobantes OCR."""
    asegurar_tabla_destinos_ocr(db)
    num_clean = re.sub(r"\D", "", payload.numero)
    if not num_clean:
        raise HTTPException(status_code=400, detail="Número de teléfono inválido")

    if num_clean.startswith("0") and len(num_clean) == 10:
        num_clean = "593" + num_clean[1:]
    elif len(num_clean) == 9 and num_clean.startswith("9"):
        num_clean = "593" + num_clean

    existente = db.query(models.WhatsAppDestinoOCR).filter(models.WhatsAppDestinoOCR.numero == num_clean).first()
    if existente:
        existente.nombre = payload.nombre.strip()
        existente.activo = payload.activo if payload.activo is not None else True
        db.commit()
        db.refresh(existente)
        return existente

    nuevo = models.WhatsAppDestinoOCR(
        numero=num_clean,
        nombre=payload.nombre.strip(),
        activo=payload.activo if payload.activo is not None else True
    )
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return nuevo


@router.patch("/destinos-ocr/{destino_id}/toggle-activo")
def toggle_activo_destino_ocr(destino_id: int, db: Session = Depends(get_db)):
    """Activa o pausa un número destinatario de OCR."""
    destino = db.query(models.WhatsAppDestinoOCR).filter(models.WhatsAppDestinoOCR.id == destino_id).first()
    if not destino:
        raise HTTPException(status_code=404, detail="Destinatario no encontrado")
    destino.activo = not destino.activo
    db.commit()
    return {"success": True, "activo": destino.activo, "id": destino.id}


@router.delete("/destinos-ocr/{destino_id}")
def eliminar_destino_ocr(destino_id: int, db: Session = Depends(get_db)):
    """Elimina un número de la lista de reenvío OCR."""
    destino = db.query(models.WhatsAppDestinoOCR).filter(models.WhatsAppDestinoOCR.id == destino_id).first()
    if not destino:
        raise HTTPException(status_code=404, detail="Destinatario no encontrado")
    db.delete(destino)
    db.commit()
    return {"success": True, "message": "Destinatario eliminado correctamente"}


# ============================================================================
# COMPROBANTES DE PAGO, VALIDACIÓN CONTRA BD Y APROBACIÓN DE RECIBOS (uploadscr)
# ============================================================================

def _try_float_val(val) -> float:
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(",", ".")
    if not s or s.upper() in {"NONE", "N/A", "NULL", "-"}:
        return 0.0
    m = re.search(r"[-+]?\d+(?:\.\d+)?", s)
    if m:
        try:
            return float(m.group(0))
        except ValueError:
            return 0.0
    return 0.0


def obtener_tarifa_plan_cliente(cliente: models.Cliente, db: Session = None) -> float:
    """Obtiene la tarifa mensual del plan del cliente como referencia cuando su saldo en BD está en 0."""
    if not cliente:
        return 0.0
    if getattr(cliente, "cortesia_total", False):
        return 0.0
    if getattr(cliente, "mantenimiento", False):
        return 10.0
    esp = _try_float_val(getattr(cliente, "precio_plan_especial", 0.0))
    if esp > 0:
        return round(esp, 2)
    plan_str = str(getattr(cliente, "plan", "") or "").strip()
    if plan_str and db is not None:
        try:
            plan_obj = db.query(models.PlanInternet).filter(models.PlanInternet.nombre.ilike(plan_str)).first()
            if plan_obj and plan_obj.precio is not None and float(plan_obj.precio) > 0:
                return round(float(plan_obj.precio), 2)
        except Exception:
            pass
    precios_base = {
        "100mb": 17.25,
        "100m/100m": 17.25,
        "600mb": 17.87,
        "600m/600m": 17.87,
        "650m/650m": 20.00,
        "700mb": 21.73,
        "800mb": 32.20,
        "800m/800m": 32.20,
    }
    if plan_str.lower() in precios_base:
        return precios_base[plan_str.lower()]
    inet_pay = _try_float_val(getattr(cliente, "internet_payment", 0.0))
    if inet_pay > 0:
        return round(inet_pay, 2)
    return 0.0


def calcular_deuda_pendiente_cliente(cliente: models.Cliente, db: Session = None) -> float:
    """Calcula el saldo total pendiente del cliente en la BD (Internet + Plus + Adicional, o cuota de plan)."""
    if not cliente:
        return 0.0
    if getattr(cliente, "cortesia_total", False):
        return 0.0
    saldo_net = max(0.0, _try_float_val(getattr(cliente, "saldo", 0.0)))
    saldo_plus = max(0.0, _try_float_val(getattr(cliente, "plus", 0.0)))
    saldo_adic = max(0.0, _try_float_val(getattr(cliente, "adicional", 0.0)))
    deuda = round(saldo_net + saldo_plus + saldo_adic, 2)
    if deuda <= 0.0:
        total_p = _try_float_val(getattr(cliente, "total_pago", 0.0))
        if total_p > 0:
            deuda = round(total_p, 2)
    if deuda <= 0.0:
        tarifa = obtener_tarifa_plan_cliente(cliente, db)
        if tarifa > 0:
            deuda = round(tarifa + saldo_plus + saldo_adic, 2)
    return deuda


def buscar_cliente_por_telefono_comprobante(db: Session, numero_raw: str, nombre_archivo: str = "") -> Tuple[Optional[models.Cliente], str]:
    """
    Busca exhaustivamente si el número de teléfono del remitente (o el incrustado en el nombre de archivo
    comp_<ts>_<telefono>_wa.jpg / comp_ID_<id>_...) pertenece a un cliente registrado en la base de datos.
    Retorna (cliente, telefono_limpio).
    """
    # 0. Si el nombre de archivo contiene explícitamente el ID del cliente (ej. comp_ID_45_...)
    if nombre_archivo:
        m_id = re.search(r"comp_ID_(\d+)_", str(nombre_archivo))
        if m_id:
            try:
                c_id_match = db.query(models.Cliente).filter(models.Cliente.id == int(m_id.group(1))).first()
                if c_id_match:
                    c_clean = "".join([c for c in str(c_id_match.celular or "") if c.isdigit()])
                    return c_id_match, c_clean
            except Exception:
                pass

    num_str = str(numero_raw or "").strip()
    es_lid = num_str.lower().endswith("@lid")
    num_clean = "" if es_lid else "".join([c for c in num_str if c.isdigit()])

    # Si numero_raw venía vacío o como @lid, extraer el teléfono real desde el nombre del archivo si existe
    if (not num_clean or len(num_clean) < 8 or len(num_clean) > 13) and nombre_archivo:
        m_arch = re.search(r"comp_\d+_(\d{9,13})_wa", str(nombre_archivo))
        if m_arch:
            cand_arch = m_arch.group(1)
            if cand_arch.startswith("5939") or cand_arch.startswith("09") or (len(cand_arch) == 9 and cand_arch.startswith("9")):
                num_clean = cand_arch
        else:
            m_sin = re.search(r"comp_ID_sin_registrar_.*?_(\d{8,13})_", str(nombre_archivo))
            if m_sin:
                num_clean = m_sin.group(1)

    if not num_clean or len(num_clean) < 8:
        return None, num_clean

    # 1. Intentar con el buscador estándar de SAM Bot
    try:
        import sam_bot_service
        cli = sam_bot_service.buscar_cliente_por_celular(num_clean, db)
        if cli:
            return cli, num_clean
    except Exception:
        pass

    # 2. Búsqueda directa optimizada por los últimos 8 o 9 dígitos en la tabla de clientes
    ultimos_9 = num_clean[-9:] if len(num_clean) >= 9 else num_clean
    ultimos_8 = num_clean[-8:]
    try:
        cand_sql = db.query(models.Cliente).filter(
            models.Cliente.celular != None,
            models.Cliente.celular.like(f"%{ultimos_8}%")
        ).first()
        if cand_sql:
            return cand_sql, num_clean

        if len(ultimos_9) == 9:
            cand_sql9 = db.query(models.Cliente).filter(
                models.Cliente.celular != None,
                models.Cliente.celular.like(f"%{ultimos_9}%")
            ).first()
            if cand_sql9:
                return cand_sql9, num_clean
    except Exception:
        pass

    return None, num_clean


def _nombres_compatibles(nombre_bd: str, nombre_comparar: str) -> bool:
    """Verifica si dos nombres comparten al menos un apellido/nombre significativo o similitud."""
    if not nombre_bd or not nombre_comparar:
        return True
    stop_words = {"de", "del", "la", "las", "el", "los", "san", "santa", "cliente", "whatsapp", "transferencia", "banco"}
    n1 = re.sub(r"[^a-zA-ZáéíóúñÁÉÍÓÚÑ\s]", " ", nombre_bd.lower())
    n2 = re.sub(r"[^a-zA-ZáéíóúñÁÉÍÓÚÑ\s]", " ", nombre_comparar.lower())
    t1 = {w for w in n1.split() if len(w) >= 3 and w not in stop_words}
    t2 = {w for w in n2.split() if len(w) >= 3 and w not in stop_words}
    if not t1 or not t2:
        return True
    if t1.intersection(t2):
        return True
    try:
        from rapidfuzz import fuzz
        if fuzz.token_set_ratio(n1, n2) >= 52:
            return True
    except Exception:
        pass
    return False


def asegurar_tabla_comprobantes(db: Session = None):
    """
    Garantiza que la tabla 'comprobantes' y todas sus columnas de validación OCR
    existan tanto en el motor activo (MySQL/PostgreSQL) como en SQLite opsatel.db.
    """
    columnas_nuevas = [
        ("cedula_cliente", "VARCHAR(100)"),
        ("cuenta_origen", "VARCHAR(100)"),
        ("cuenta_destino", "VARCHAR(100)"),
        ("beneficiario", "VARCHAR(255)"),
        ("ordenante", "VARCHAR(255)"),
        ("fecha_comprobante", "VARCHAR(100)"),
        ("texto_ocr", "TEXT"),
        ("saldo_pendiente_bd", "FLOAT"),
        ("categoria_validacion", "VARCHAR(60) DEFAULT 'PENDIENTES_COMPROBANTE'"),
        ("motivo_validacion", "TEXT"),
        ("hash_imagen", "VARCHAR(64)"),
        ("score_autenticidad", "INTEGER DEFAULT 0"),
        ("es_duplicado", "BOOLEAN DEFAULT 0"),
        ("duplicado_detalle", "TEXT"),
        ("pago_id", "INTEGER"),
    ]

    if db is not None:
        try:
            from sqlalchemy import inspect as sa_inspect, text as sa_text
            engine = db.get_bind()
            models.Comprobante.__table__.create(bind=engine, checkfirst=True)

            inspector = sa_inspect(engine)
            existentes = {col["name"].lower() for col in inspector.get_columns("comprobantes")}
            for col_name, col_type in columnas_nuevas:
                if col_name.lower() not in existentes:
                    try:
                        db.execute(sa_text(f"ALTER TABLE comprobantes ADD COLUMN {col_name} {col_type}"))
                        db.commit()
                    except Exception:
                        db.rollback()

            # Sanitizar mensajes antiguos que hayan quedado como texto plano '[NON_TEXT_MSG] image'
            db.query(models.WhatsAppMensajeChat).filter(
                models.WhatsAppMensajeChat.mensaje == "[NON_TEXT_MSG] image"
            ).update({"mensaje": "📷 [Comprobante / Foto enviada]", "tipo": "multimedia"}, synchronize_session=False)
            db.commit()
        except Exception as e_bind:
            db.rollback()
            print(f"[Comprobantes] Verificación de tabla en motor activo: {e_bind}")

    # Asegurar también en SQLite opsatel.db si existe
    try:
        backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        for candidate in [os.path.join(backend_dir, "opsatel.db"), os.path.join(backend_dir, "..", "opsatel.db")]:
            if os.path.exists(candidate):
                import sqlite3
                s_conn = sqlite3.connect(candidate)
                s_cur = s_conn.cursor()
                s_cur.execute("""
                    CREATE TABLE IF NOT EXISTS comprobantes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        cliente_id INTEGER,
                        numero_telefono VARCHAR(50),
                        nombre_remitente VARCHAR(255),
                        nombre_archivo VARCHAR(255),
                        ruta_archivo VARCHAR(500),
                        url_archivo VARCHAR(500),
                        mimetype VARCHAR(100),
                        tamano_bytes INTEGER,
                        mensaje_texto TEXT,
                        estado VARCHAR(50) DEFAULT 'PENDIENTE',
                        monto FLOAT,
                        banco_origen VARCHAR(100),
                        banco_destino VARCHAR(100),
                        numero_referencia VARCHAR(100),
                        cedula_cliente VARCHAR(100),
                        cuenta_origen VARCHAR(100),
                        cuenta_destino VARCHAR(100),
                        beneficiario VARCHAR(255),
                        ordenante VARCHAR(255),
                        fecha_comprobante VARCHAR(100),
                        texto_ocr TEXT,
                        saldo_pendiente_bd FLOAT,
                        categoria_validacion VARCHAR(60) DEFAULT 'PENDIENTES_COMPROBANTE',
                        motivo_validacion TEXT,
                        pago_id INTEGER,
                        observaciones TEXT,
                        fecha_hora DATETIME,
                        created_at DATETIME,
                        updated_at DATETIME
                    )
                """)
                s_cur.execute("PRAGMA table_info(comprobantes)")
                cols_sq = {row[1].lower() for row in s_cur.fetchall()}
                for col_name, col_type in columnas_nuevas:
                    if col_name.lower() not in cols_sq:
                        try:
                            s_cur.execute(f"ALTER TABLE comprobantes ADD COLUMN {col_name} {col_type}")
                        except Exception:
                            pass
                s_conn.commit()
                s_conn.close()
    except Exception as e_sq:
        print(f"[Comprobantes] Verificación de tabla en SQLite: {e_sq}")


def evaluar_validacion_comprobante(
    db: Session,
    numero_raw: str,
    nombre_remitente: Optional[str],
    ocr_data: Dict[str, Any],
    monto_final: Optional[float],
    referencia_final: Optional[str],
    nombre_archivo: str = "",
    comprobante_id_actual: Optional[int] = None,
    es_registro_historico_sin_ocr: bool = False,
    hash_imagen: Optional[str] = None
) -> Dict[str, Any]:
    """
    Compara el comprobante recibido con la Base de Datos, verifica autenticidad, detecta duplicados
    y lo clasifica en:
    - 'CONFIRMACION_RECIBO': Comprobante real, verificado, enviado desde un número registrado en la BD,
                             sin duplicados de referencia ni de imagen, y con monto coherente con la deuda.
    - 'PENDIENTES_COMPROBANTE': Enviado desde otro número, no registrado, duplicado (referencia o imagen),
                                paga de más, comprobante extemporáneo o novedad en el OCR.
    """
    cliente_por_telefono, num_clean = buscar_cliente_por_telefono_comprobante(db, numero_raw, nombre_archivo)
    telefono_registrado = cliente_por_telefono is not None

    # Buscar por nombre solo si el teléfono no arrojó coincidencia y el texto es suficientemente largo
    ordenante_ocr = (ocr_data.get("ordenante") or "").strip()
    cliente_por_ordenante = None
    if not cliente_por_telefono and ordenante_ocr and len(ordenante_ocr) >= 6:
        try:
            partes = [p for p in ordenante_ocr.split() if len(p) >= 4]
            if partes:
                q_nom = db.query(models.Cliente)
                for p in partes[:2]:
                    q_nom = q_nom.filter(models.Cliente.nombre.ilike(f"%{p}%"))
                cliente_por_ordenante = q_nom.first()
        except Exception:
            pass

    cliente_por_pushname = None
    if not cliente_por_telefono and not cliente_por_ordenante and nombre_remitente and len(nombre_remitente.strip().split()) >= 2:
        try:
            partes_p = [p for p in nombre_remitente.strip().split() if len(p) >= 4]
            if partes_p:
                q_p = db.query(models.Cliente)
                for p in partes_p[:2]:
                    q_p = q_p.filter(models.Cliente.nombre.ilike(f"%{p}%"))
                cliente_por_pushname = q_p.first()
        except Exception:
            pass

    # Si el teléfono sí está registrado en la BD, siempre vinculamos al dueño de esa línea registrada
    cliente = cliente_por_telefono or cliente_por_ordenante or cliente_por_pushname
    deuda_bd = calcular_deuda_pendiente_cliente(cliente, db) if cliente else 0.0

    monto_evaluado = monto_final
    if (monto_evaluado is None or monto_evaluado <= 0) and telefono_registrado and es_registro_historico_sin_ocr and deuda_bd > 0:
        monto_evaluado = deuda_bd

    razones_pendiente = []
    es_duplicado = False
    duplicado_detalle = None

    # =========================================================================
    # 1. VERIFICACIÓN ESTRICTA DE DUPLICADOS (IMAGEN, REFERENCIA, PAGOS EN BD)
    # =========================================================================
    hash_evaluar = hash_imagen or ocr_data.get("hash_imagen")
    if hash_evaluar and len(str(hash_evaluar).strip()) >= 16:
        q_dup_hash = db.query(models.Comprobante).filter(
            models.Comprobante.hash_imagen == str(hash_evaluar).strip(),
            models.Comprobante.estado.notin_(["DESCARTADO", "RECHAZADO"])
        )
        if comprobante_id_actual:
            q_dup_hash = q_dup_hash.filter(models.Comprobante.id != comprobante_id_actual)
        dup_hash = q_dup_hash.first()
        if dup_hash:
            es_duplicado = True
            duplicado_detalle = f"Imagen idéntica (hash SHA-256) ya fue enviada en comprobante #{dup_hash.id} ({dup_hash.estado})"
            razones_pendiente.append(
                f"🚨 IMAGEN DUPLICADA: Esta misma foto/archivo ya fue registrada en el comprobante #{dup_hash.id} ({dup_hash.estado})."
            )

    ref_clean = str(referencia_final or "").strip()
    if ref_clean and len(ref_clean) >= 5 and ref_clean.lower() not in ["null", "none", "00000", "000000"]:
        # A) Buscar en Comprobantes APROBADOS (ya cobrados)
        q_dup_aprob = db.query(models.Comprobante).filter(
            models.Comprobante.numero_referencia == ref_clean,
            models.Comprobante.estado == "APROBADO"
        )
        if comprobante_id_actual:
            q_dup_aprob = q_dup_aprob.filter(models.Comprobante.id != comprobante_id_actual)
        dup_aprob = q_dup_aprob.first()
        if dup_aprob:
            es_duplicado = True
            duplicado_detalle = f"Referencia N° {ref_clean} ya fue cobrada en comprobante #{dup_aprob.id}"
            razones_pendiente.append(
                f"🚨 COMPROBANTE YA COBRADO: La referencia N° {ref_clean} ya fue cobrada en el comprobante #{dup_aprob.id}."
            )

        # B) Buscar en Comprobantes PENDIENTES (cola de revisión)
        if not dup_aprob:
            q_dup_pend = db.query(models.Comprobante).filter(
                models.Comprobante.numero_referencia == ref_clean,
                models.Comprobante.estado == "PENDIENTE"
            )
            if comprobante_id_actual:
                q_dup_pend = q_dup_pend.filter(models.Comprobante.id != comprobante_id_actual)
            dup_pend = q_dup_pend.first()
            if dup_pend:
                es_duplicado = True
                duplicado_detalle = f"Referencia N° {ref_clean} ya registrada en comprobante #{dup_pend.id} (pendiente de aprobación)"
                razones_pendiente.append(
                    f"⚠️ COMPROBANTE REPETIDO: La referencia N° {ref_clean} ya fue enviada previamente y consta en el comprobante #{dup_pend.id} en revisión."
                )

        # C) Buscar en historial_pagos (tabla Pago)
        if not dup_aprob:
            try:
                pago_dup = db.query(models.Pago).filter(
                    models.Pago.referencia == ref_clean,
                    models.Pago.anulado == False
                ).first()
                if pago_dup:
                    es_duplicado = True
                    fecha_p_str = pago_dup.fecha_pago.strftime("%Y-%m-%d") if pago_dup.fecha_pago else ""
                    duplicado_detalle = f"Referencia N° {ref_clean} ya consta en el Pago #{pago_dup.id} (${pago_dup.monto}) del {fecha_p_str}"
                    razones_pendiente.append(
                        f"🚨 REFERENCIA COBRADA EN BD: El código N° {ref_clean} ya consta en el Pago #{pago_dup.id} (${pago_dup.monto}) de la fecha {fecha_p_str}."
                    )
            except Exception as e_pago:
                print(f"[Comprobantes] Error buscando referencia en historial_pagos: {e_pago}")

        # D) Buscar en historial_pagos_extras (tabla PagoExtra)
        if not dup_aprob and not es_duplicado:
            try:
                pe_dup = db.query(models.PagoExtra).filter(
                    models.PagoExtra.referencia == ref_clean,
                    models.PagoExtra.anulado == False
                ).first()
                if pe_dup:
                    es_duplicado = True
                    duplicado_detalle = f"Referencia N° {ref_clean} ya consta en Pagos Extras #{pe_dup.id} (${pe_dup.monto})"
                    razones_pendiente.append(
                        f"🚨 REFERENCIA COBRADA EN EXTRAS: El código N° {ref_clean} ya fue cobrado en Pago Extra #{pe_dup.id}."
                    )
            except Exception:
                pass

    # =========================================================================
    # 2. EVALUACIÓN DE AUTENTICIDAD, DESTINATARIO Y VIGENCIA
    # =========================================================================
    score_autenticidad = int(ocr_data.get("score_autenticidad") or 0)
    alertas_ocr = ocr_data.get("alertas_autenticidad") or []
    for al in alertas_ocr:
        if "antiguo" in al.lower():
            razones_pendiente.append(f"⚠️ {al}")

    if not cliente:
        razones_pendiente.append(
            f"Número remitente (+{num_clean or numero_raw}) no está registrado y no tiene coincidencia con ningún cliente en la base de datos."
        )
    elif not telefono_registrado:
        tel_titular = getattr(cliente, "celular", None) or "Sin celular en BD"
        razones_pendiente.append(
            f"Enviado desde otro número (+{num_clean or numero_raw}) distinto al registrado en BD para {cliente.nombre} (ID #{cliente.id}, Cel. titular: {tel_titular})."
        )

    # Validar el monto pagado contra la deuda/cuota pendiente en la base de datos
    if monto_evaluado is None or monto_evaluado <= 0:
        razones_pendiente.append(
            "No se logró reconocer el monto en el comprobante. Requiere revisión manual."
        )
    elif cliente and deuda_bd > 0.01 and monto_evaluado > deuda_bd + 0.05:
        exceso = round(monto_evaluado - deuda_bd, 2)
        razones_pendiente.append(
            f"Paga de más: El comprobante es por ${monto_evaluado:.2f}, pero el valor pendiente en BD es de ${deuda_bd:.2f} (excede por ${exceso:.2f})."
        )

    # Si es duplicado, forzamos clasificación a PENDIENTES_COMPROBANTE con aviso crítico
    if es_duplicado:
        categoria = "PENDIENTES_COMPROBANTE"
        motivo = " | ".join(razones_pendiente)
    elif len(razones_pendiente) == 0 and cliente and telefono_registrado and monto_evaluado and monto_evaluado > 0:
        categoria = "CONFIRMACION_RECIBO"
        sello_ops = " 🏛️ [Cuenta Opsatel Verificada]" if ocr_data.get("es_opsatel_destinatario") else ""
        if deuda_bd > 0 and abs(monto_evaluado - deuda_bd) <= 0.05:
            motivo = (
                f"✅ Listo para confirmar cobro: Número registrado de {cliente.nombre} (ID #{cliente.id}, Cédula: {getattr(cliente, 'cedula', 'S/N')}). "
                f"Paga ${monto_evaluado:.2f} coincidiendo con su valor pendiente en BD (${deuda_bd:.2f}).{sello_ops}"
            )
        elif deuda_bd > monto_evaluado:
            restante = round(deuda_bd - monto_evaluado, 2)
            motivo = (
                f"✅ Listo para confirmar cobro (Abono parcial): Número registrado de {cliente.nombre} (ID #{cliente.id}). "
                f"Paga ${monto_evaluado:.2f} de ${deuda_bd:.2f} pendiente en BD (restará ${restante:.2f}).{sello_ops}"
            )
        else:
            motivo = (
                f"✅ Listo para confirmar cobro: Número registrado de {cliente.nombre} (ID #{cliente.id}). "
                f"Monto a cobrar: ${monto_evaluado:.2f}.{sello_ops}"
            )
    else:
        categoria = "PENDIENTES_COMPROBANTE"
        motivo = "⚠️ " + " | ".join(razones_pendiente) if razones_pendiente else "⚠️ Requiere revisión manual antes de cobrar."

    return {
        "cliente": cliente,
        "numero_limpio": num_clean,
        "telefono_registrado": telefono_registrado,
        "saldo_pendiente_bd": deuda_bd,
        "monto_evaluado": monto_evaluado,
        "categoria_validacion": categoria,
        "motivo_validacion": motivo,
        "es_duplicado": es_duplicado,
        "duplicado_detalle": duplicado_detalle,
        "score_autenticidad": score_autenticidad
    }


_ULTIMA_REVALIDACION_COMPROBANTES: float = 0.0

def revalidar_comprobantes_existentes_pendientes(db: Session, force: bool = False):
    """
    Re-evalúa de forma ágil comprobantes pendientes para vincular números registrados en la BD.
    Utiliza una ventana de enfriamiento (cooldown) para no re-ejecutar en cada petición HTTP
    y nunca bloquea la respuesta con análisis OCR pesado sincrónico.
    """
    global _ULTIMA_REVALIDACION_COMPROBANTES
    ahora = time.time()
    if not force and (ahora - _ULTIMA_REVALIDACION_COMPROBANTES) < 60.0:
        return
    _ULTIMA_REVALIDACION_COMPROBANTES = ahora

    try:
        from services.ocr_comprobantes import buscar_ruta_archivo, es_documento_comprobante_valido
        pendientes = db.query(models.Comprobante).filter(
            models.Comprobante.estado == "PENDIENTE"
        ).order_by(models.Comprobante.id.desc()).limit(50).all()

        hubo_cambios = False
        for r in pendientes:
            msg_t = (r.mensaje_texto or "").lower()
            if "no es un comprobante válido" in msg_t or "no es un documento valido" in msg_t or "imagen descartada" in msg_t or "documento no válido" in msg_t:
                r.estado = "DESCARTADO"
                r.categoria_validacion = "NO_COMPROBANTE"
                r.motivo_validacion = "Imagen descartada: no es un comprobante de pago válido"
                hubo_cambios = True
                continue

            if r.texto_ocr:
                es_val, mot_val = es_documento_comprobante_valido(r.texto_ocr, {
                    "banco_origen": r.banco_origen,
                    "monto": r.monto,
                    "numero_comprobante": r.numero_referencia,
                    "cuenta_destino": r.cuenta_destino
                })
                if not es_val and not r.monto and not r.banco_origen and not r.numero_referencia:
                    r.estado = "DESCARTADO"
                    r.categoria_validacion = "NO_COMPROBANTE"
                    r.motivo_validacion = "Imagen no admitida: no contiene datos de comprobante bancario"
                    hubo_cambios = True
                    continue

            ruta_real = buscar_ruta_archivo(r.ruta_archivo or r.nombre_archivo or "")
            archivo_existe = bool(ruta_real and os.path.isfile(ruta_real))
            es_historico_sin_ocr = (not archivo_existe) and (not r.texto_ocr)

            eval_res = evaluar_validacion_comprobante(
                db=db,
                numero_raw=r.numero_telefono,
                nombre_remitente=r.nombre_remitente,
                ocr_data={"ordenante": r.ordenante, "score_autenticidad": getattr(r, "score_autenticidad", 0)},
                monto_final=r.monto,
                referencia_final=r.numero_referencia,
                nombre_archivo=r.nombre_archivo or "",
                comprobante_id_actual=r.id,
                es_registro_historico_sin_ocr=es_historico_sin_ocr,
                hash_imagen=getattr(r, "hash_imagen", None)
            )

            cli = eval_res.get("cliente")
            nuevo_cid = cli.id if cli else r.cliente_id
            nueva_ced = (getattr(cli, "cedula", None) if cli else None) or r.cedula_cliente
            nuevo_saldo_bd = eval_res.get("saldo_pendiente_bd")
            nueva_cat = eval_res.get("categoria_validacion")
            nuevo_motivo = eval_res.get("motivo_validacion")
            nuevo_monto = eval_res.get("monto_evaluado")
            nuevo_dup = bool(eval_res.get("es_duplicado", False))
            nuevo_dup_det = eval_res.get("duplicado_detalle")

            if (
                r.cliente_id != nuevo_cid
                or r.categoria_validacion != nueva_cat
                or r.motivo_validacion != nuevo_motivo
                or r.cedula_cliente != nueva_ced
                or r.saldo_pendiente_bd != nuevo_saldo_bd
                or getattr(r, "es_duplicado", False) != nuevo_dup
                or getattr(r, "duplicado_detalle", None) != nuevo_dup_det
                or (r.monto is None and nuevo_monto is not None)
            ):
                r.cliente_id = nuevo_cid
                r.cedula_cliente = nueva_ced
                r.saldo_pendiente_bd = nuevo_saldo_bd
                r.categoria_validacion = nueva_cat
                r.motivo_validacion = nuevo_motivo
                r.es_duplicado = nuevo_dup
                r.duplicado_detalle = nuevo_dup_det
                if r.monto is None and nuevo_monto is not None:
                    r.monto = nuevo_monto
                if eval_res.get("numero_limpio") and (not r.numero_telefono or "@lid" in str(r.numero_telefono)):
                    r.numero_telefono = eval_res.get("numero_limpio")
                hubo_cambios = True

        if hubo_cambios:
            db.commit()
    except Exception as e_rev:
        db.rollback()
        print(f"[Comprobantes] Aviso en revalidación automática de pendientes: {e_rev}")


@router.get("/identificar-cliente-rapido")
def identificar_cliente_rapido(
    numero: str,
    db: Session = Depends(get_db)
):
    """
    Consulta rápida de cliente por teléfono para que el bridge de WhatsApp
    nombre el archivo de imagen con ID, Nombre y Fecha al momento de descargarlo en uploads.
    """
    try:
        cli, num_clean = buscar_cliente_por_telefono_comprobante(db, numero)
        if cli:
            return {
                "encontrado": True,
                "cliente_id": cli.id,
                "nombre": cli.nombre,
                "cedula": getattr(cli, "cedula", None),
                "numero_limpio": num_clean
            }
    except Exception as e:
        print(f"[Identificar Cliente] Error en consulta rápida: {e}")
    return {"encontrado": False, "cliente_id": None, "nombre": None, "numero_limpio": numero}


@router.post("/registrar-comprobante")
def registrar_comprobante_endpoint(
    payload: schemas.ComprobanteCreate,
    db: Session = Depends(get_db)
):
    """
    Endpoint invocado automáticamente por el puente de WhatsApp (whatsapp_bridge.js)
    cuando se detecta y descarga una imagen en la carpeta 'uploadscr'.
    1. Sube la calidad de la imagen y extrae todos los campos por OCR.
    2. Compara teléfono, cédula, titular y monto pagado contra la deuda pendiente en BD.
    3. Clasifica automáticamente en 'CONFIRMACION_RECIBO' o 'PENDIENTES_COMPROBANTE'.
    """
    try:
        asegurar_tabla_comprobantes(db)

        # 1. Análisis OCR automático de alta precisión (con mejora de calidad de imagen)
        ocr_data = {}
        try:
            from services.ocr_comprobantes import analizar_comprobante_ocr
            ocr_data = analizar_comprobante_ocr(payload.ruta_archivo or payload.nombre_archivo)
        except Exception as e_ocr:
            print(f"[Comprobantes OCR] Error en extracción OCR: {e_ocr}")

        # Comprobar si la imagen es realmente un comprobante bancario o documento financiero admitido
        es_documento_valido = bool(ocr_data.get("es_documento_valido", False))
        if not es_documento_valido:
            # Si no tiene banco ni monto ni referencia bancaria válida
            print(f"[Comprobantes] ⚠️ La imagen recibida '{payload.nombre_archivo}' NO es un comprobante válido ({ocr_data.get('motivo_validacion_documento')})")
            return {
                "success": False,
                "es_documento_valido": False,
                "error": "la imagen mandada no es un documento valido",
                "message": "La imagen enviada no es un documento válido. Por favor, envía un comprobante de pago o transferencia bancaria válido.",
                "resumen_ocr": ocr_data.get("resumen_ocr"),
                "texto_extraido": ocr_data.get("texto_extraido", "")
            }

        monto_final = payload.monto if payload.monto is not None else ocr_data.get("monto")
        banco_final = payload.banco_origen or ocr_data.get("banco_origen")
        banco_destino_final = payload.banco_destino or ocr_data.get("banco_destino")
        referencia_final = payload.numero_referencia or ocr_data.get("numero_referencia")
        cuenta_origen_final = ocr_data.get("cuenta_origen")
        cuenta_destino_final = ocr_data.get("cuenta_destino")
        beneficiario_final = ocr_data.get("beneficiario")
        ordenante_final = ocr_data.get("ordenante")
        fecha_comp_final = ocr_data.get("fecha")
        texto_ocr_final = ocr_data.get("texto_extraido") or ""

        hash_final = payload.hash_imagen or ocr_data.get("hash_imagen")
        score_autenticidad = int(ocr_data.get("score_autenticidad") or 0)

        # 2. Evaluar validación contra la Base de Datos
        eval_res = evaluar_validacion_comprobante(
            db=db,
            numero_raw=payload.numero_telefono,
            nombre_remitente=payload.nombre_remitente,
            ocr_data=ocr_data,
            monto_final=monto_final,
            referencia_final=referencia_final,
            nombre_archivo=payload.nombre_archivo or "",
            hash_imagen=hash_final
        )
        cliente = eval_res["cliente"]
        saldo_pendiente_bd = eval_res["saldo_pendiente_bd"]
        categoria_validacion = eval_res["categoria_validacion"]
        motivo_validacion = eval_res["motivo_validacion"]
        monto_final = eval_res["monto_evaluado"]
        cedula_cliente = getattr(cliente, "cedula", None) if cliente else None
        es_duplicado = bool(eval_res.get("es_duplicado", False))
        duplicado_detalle = eval_res.get("duplicado_detalle")

        num_raw = payload.numero_telefono or ""
        num_clean = eval_res.get("numero_limpio") or "".join([c for c in num_raw if c.isdigit()])

        observaciones_lista = []
        if payload.observaciones:
            observaciones_lista.append(payload.observaciones)
        if motivo_validacion:
            observaciones_lista.append(motivo_validacion)
        if ocr_data.get("resumen_ocr"):
            observaciones_lista.append(ocr_data.get("resumen_ocr"))
        observaciones_final = "\n".join(observaciones_lista) if observaciones_lista else None

        ahora_ec = datetime.now(ECUADOR_TZ).replace(tzinfo=None)

        # Si el comprobante se guardó inicialmente como sin_registrar pero OCR/BD identificó al cliente:
        nombre_arch_final = payload.nombre_archivo or ""
        ruta_arch_final = payload.ruta_archivo or ""
        url_arch_final = payload.url_archivo or ""
        if cliente and cliente.id and "ID_sin_registrar" in nombre_arch_final:
            try:
                nom_limpio = re.sub(r'[^a-zA-Z0-9_\-]', '_', getattr(cliente, 'nombre', '') or 'Cliente')
                nom_limpio = re.sub(r'_+', '_', nom_limpio).strip('_')[:40]
                nuevo_nombre_arch = re.sub(
                    r"comp_ID_sin_registrar_[^_]+_(?:\d{8,13}_)?",
                    f"comp_ID_{cliente.id}_{nom_limpio}_",
                    nombre_arch_final
                )
                backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
                candidatos_dir = [
                    os.path.join(backend_dir, "uploadscr"),
                    os.path.join(backend_dir, "uploads", "uploadscr"),
                    os.path.join(backend_dir, "uploads", "comprobantes"),
                    os.path.join(backend_dir, "..", "Opsatel-Frontend", "uploadscr"),
                    os.path.join(backend_dir, "..", "Opsatel-Frontend", "public", "uploadscr"),
                ]
                renombrado = False
                for c_dir in candidatos_dir:
                    old_f = os.path.join(c_dir, nombre_arch_final)
                    new_f = os.path.join(c_dir, nuevo_nombre_arch)
                    if os.path.exists(old_f):
                        try:
                            os.rename(old_f, new_f)
                            renombrado = True
                        except Exception:
                            pass
                if renombrado:
                    nombre_arch_final = nuevo_nombre_arch
                    url_arch_final = f"/uploadscr/{nuevo_nombre_arch}"
                    ruta_arch_final = f"uploadscr/{nuevo_nombre_arch}"
            except Exception as e_ren:
                print(f"[Comprobante] Aviso renombrando archivo con cliente_id: {e_ren}")

        # 3. Crear registro en la tabla comprobantes
        nuevo_comp = models.Comprobante(
            cliente_id=cliente.id if cliente else None,
            numero_telefono=num_clean or payload.numero_telefono,
            nombre_remitente=payload.nombre_remitente or (cliente.nombre if cliente else (ordenante_final or "Cliente WhatsApp")),
            nombre_archivo=nombre_arch_final,
            ruta_archivo=ruta_arch_final,
            url_archivo=url_arch_final,
            mimetype=payload.mimetype or "image/jpeg",
            tamano_bytes=payload.tamano_bytes,
            mensaje_texto=payload.mensaje_texto or "",
            estado="PENDIENTE",
            monto=monto_final,
            banco_origen=banco_final,
            banco_destino=banco_destino_final,
            numero_referencia=referencia_final,
            cedula_cliente=cedula_cliente,
            cuenta_origen=cuenta_origen_final,
            cuenta_destino=cuenta_destino_final,
            beneficiario=beneficiario_final,
            ordenante=ordenante_final,
            fecha_comprobante=fecha_comp_final,
            texto_ocr=texto_ocr_final,
            saldo_pendiente_bd=saldo_pendiente_bd,
            categoria_validacion=categoria_validacion,
            motivo_validacion=motivo_validacion,
            hash_imagen=hash_final,
            score_autenticidad=score_autenticidad,
            es_duplicado=es_duplicado,
            duplicado_detalle=duplicado_detalle,
            observaciones=observaciones_final,
            fecha_hora=ahora_ec,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )

        db.add(nuevo_comp)
        db.commit()
        db.refresh(nuevo_comp)

        print(
            f"[Comprobantes] ✅ Comprobante #{nuevo_comp.id} registrado [{categoria_validacion}] - "
            f"Cliente: {cliente.nombre if cliente else 'No vinculado'} | Monto: ${monto_final or 0:.2f} | Deuda BD: ${saldo_pendiente_bd:.2f}"
            + (f" | 🚨 DUPLICADO: {duplicado_detalle}" if es_duplicado else "")
        )

        return {
            "success": True,
            "es_documento_valido": True,
            "es_duplicado": es_duplicado,
            "duplicado_detalle": duplicado_detalle,
            "score_autenticidad": score_autenticidad,
            "hash_imagen": hash_final,
            "message": "Comprobante registrado y validado exitosamente",
            "comprobante_id": nuevo_comp.id,
            "url_archivo": nuevo_comp.url_archivo,
            "cliente_id": cliente.id if cliente else None,
            "cliente_nombre": cliente.nombre if cliente else None,
            "cliente_cedula": cedula_cliente,
            "cliente_telefono": getattr(cliente, "celular", None) or nuevo_comp.numero_telefono,
            "cliente_plan": getattr(cliente, "plan", None) if cliente else None,
            "telefono_registrado": eval_res["telefono_registrado"],
            "saldo_pendiente_bd": saldo_pendiente_bd,
            "categoria_validacion": categoria_validacion,
            "motivo_validacion": motivo_validacion,
            "monto": nuevo_comp.monto,
            "banco_origen": nuevo_comp.banco_origen,
            "banco_destino": banco_destino_final,
            "beneficiario": beneficiario_final,
            "ordenante": ordenante_final,
            "cuenta_destino": cuenta_destino_final,
            "cuenta_origen": cuenta_origen_final,
            "numero_referencia": nuevo_comp.numero_referencia,
            "fecha": fecha_comp_final,
            "estado_transaccion": ocr_data.get("estado_transaccion"),
            "ocr_detectado": bool(ocr_data.get("success")),
            "resumen_ocr": ocr_data.get("resumen_ocr"),
            "texto_extraido": texto_ocr_final,
            "ocr_completo": ocr_data
        }

    except Exception as e:
        db.rollback()
        print(f"[Comprobantes] ❌ Error registrando comprobante: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error al registrar comprobante: {str(e)}")


@router.get("/comprobantes")
def listar_comprobantes(
    estado: Optional[str] = None,
    categoria: Optional[str] = None,
    q: Optional[str] = None,
    cliente_id: Optional[int] = None,
    limit: int = 150,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """
    Lista todos los comprobantes guardados con detalles del cliente, comparación de saldos y sección:
    - CONFIRMACION_RECIBO (por confirmar para que se cobre en la BD)
    - PENDIENTES_COMPROBANTE (tuvieron algún problema: número no registrado, otro número, paga de más, dato no reconocido)
    - COBRADOS / HISTORIAL (registro de comprobantes ya cobrados en la BD)
    """
    try:
        asegurar_tabla_comprobantes(db)
        # Re-evaluar automáticamente los comprobantes pendientes para vincular números registrados en BD
        revalidar_comprobantes_existentes_pendientes(db)

        # Contadores en tiempo real para las 3 secciones
        count_confirmacion = db.query(models.Comprobante).filter(
            models.Comprobante.estado == "PENDIENTE",
            models.Comprobante.categoria_validacion == "CONFIRMACION_RECIBO"
        ).count()
        count_pendientes_anomalia = db.query(models.Comprobante).filter(
            models.Comprobante.estado == "PENDIENTE",
            models.Comprobante.categoria_validacion == "PENDIENTES_COMPROBANTE"
        ).count()
        count_aprobados = db.query(models.Comprobante).filter(
            models.Comprobante.estado == "APROBADO"
        ).count()
        count_rechazados = db.query(models.Comprobante).filter(
            models.Comprobante.estado.in_(["RECHAZADO", "DESCARTADO"])
        ).count()

        query = db.query(models.Comprobante)

        if estado and estado.strip() and estado.upper() != "TODOS":
            query = query.filter(models.Comprobante.estado == estado.strip().upper())
        else:
            query = query.filter(models.Comprobante.estado != "DESCARTADO")

        if categoria and categoria.strip() and categoria.upper() != "TODOS":
            cat_up = categoria.strip().upper()
            if cat_up == "CONFIRMACION_RECIBO":
                query = query.filter(
                    models.Comprobante.categoria_validacion == "CONFIRMACION_RECIBO",
                    models.Comprobante.estado == "PENDIENTE"
                )
            elif cat_up == "PENDIENTES_COMPROBANTE":
                query = query.filter(
                    models.Comprobante.categoria_validacion == "PENDIENTES_COMPROBANTE",
                    models.Comprobante.estado == "PENDIENTE"
                )
            elif cat_up in ("COBRADOS", "YA_COBRADOS"):
                query = query.filter(models.Comprobante.estado == "APROBADO")
            elif cat_up == "HISTORIAL":
                query = query.filter(models.Comprobante.estado.in_(["APROBADO", "RECHAZADO", "REVISADO"]))

        if cliente_id:
            query = query.filter(models.Comprobante.cliente_id == cliente_id)

        if q and q.strip():
            filtro = f"%{q.strip()}%"
            query = query.filter(
                or_(
                    models.Comprobante.numero_telefono.ilike(filtro),
                    models.Comprobante.nombre_remitente.ilike(filtro),
                    models.Comprobante.cedula_cliente.ilike(filtro),
                    models.Comprobante.ordenante.ilike(filtro),
                    models.Comprobante.beneficiario.ilike(filtro),
                    models.Comprobante.banco_origen.ilike(filtro),
                    models.Comprobante.nombre_archivo.ilike(filtro),
                    models.Comprobante.mensaje_texto.ilike(filtro),
                    models.Comprobante.numero_referencia.ilike(filtro)
                )
            )

        total = query.count()
        registros = query.order_by(models.Comprobante.id.desc()).offset(offset).limit(limit).all()

        resultado = []
        for r in registros:
            c_info = None
            deuda_actual_bd = r.saldo_pendiente_bd
            if r.cliente:
                deuda_actual_bd = calcular_deuda_pendiente_cliente(r.cliente, db)
                c_info = {
                    "id": r.cliente.id,
                    "nombre": r.cliente.nombre,
                    "cedula": getattr(r.cliente, "cedula", None) or r.cedula_cliente or "N/A",
                    "celular": getattr(r.cliente, "celular", None) or "N/A",
                    "plan": getattr(r.cliente, "plan", "N/A"),
                    "nodo": getattr(r.cliente, "nodo", "N/A"),
                    "estado_servicio": getattr(r.cliente, "estado", "Activo"),
                    "saldo": float(getattr(r.cliente, "saldo", 0.0) or 0.0),
                    "deuda_total": deuda_actual_bd,
                    "deuda_total_bd": deuda_actual_bd
                }
            resultado.append({
                "id": r.id,
                "cliente_id": r.cliente_id,
                "cliente": c_info,
                "cedula_cliente": (c_info["cedula"] if c_info else r.cedula_cliente) or "No registrada",
                "numero_telefono": r.numero_telefono,
                "nombre_remitente": r.nombre_remitente,
                "nombre_archivo": r.nombre_archivo,
                "ruta_archivo": r.ruta_archivo,
                "url_archivo": r.url_archivo,
                "mimetype": r.mimetype,
                "tamano_bytes": r.tamano_bytes,
                "mensaje_texto": r.mensaje_texto,
                "estado": r.estado or "PENDIENTE",
                "monto": r.monto,
                "banco_origen": r.banco_origen,
                "banco_destino": r.banco_destino,
                "numero_referencia": r.numero_referencia,
                "cuenta_origen": r.cuenta_origen,
                "cuenta_destino": r.cuenta_destino,
                "beneficiario": r.beneficiario,
                "ordenante": r.ordenante,
                "fecha_comprobante": r.fecha_comprobante,
                "texto_ocr": r.texto_ocr,
                "saldo_pendiente_bd": r.saldo_pendiente_bd if r.saldo_pendiente_bd is not None else deuda_actual_bd,
                "deuda_actual_bd": deuda_actual_bd,
                "categoria_validacion": r.categoria_validacion or "PENDIENTES_COMPROBANTE",
                "motivo_validacion": r.motivo_validacion,
                "hash_imagen": getattr(r, "hash_imagen", None),
                "score_autenticidad": getattr(r, "score_autenticidad", 0) or 0,
                "es_duplicado": bool(getattr(r, "es_duplicado", False)),
                "duplicado_detalle": getattr(r, "duplicado_detalle", None),
                "pago_id": r.pago_id,
                "observaciones": r.observaciones,
                "fecha_hora": r.fecha_hora.isoformat() if r.fecha_hora else None,
                "created_at": r.created_at.isoformat() if r.created_at else None
            })

        return {
            "success": True,
            "total": total,
            "resumen_categorias": {
                "confirmacion_recibo": count_confirmacion,
                "pendientes_comprobante": count_pendientes_anomalia,
                "total_por_atender": count_confirmacion + count_pendientes_anomalia,
                "cobrados": count_aprobados,
                "aprobados": count_aprobados,
                "rechazados": count_rechazados
            },
            "comprobantes": resultado
        }
    except Exception as e:
        print(f"[Comprobantes] Error listando comprobantes: {e}")
        return {
            "success": False,
            "total": 0,
            "resumen_categorias": {
                "confirmacion_recibo": 0,
                "pendientes_comprobante": 0,
                "total_por_atender": 0,
                "cobrados": 0,
                "aprobados": 0,
                "rechazados": 0
            },
            "comprobantes": [],
            "error": str(e)
        }


@router.post("/comprobantes/{comprobante_id}/aprobar-pago")
def aprobar_pago_comprobante(
    comprobante_id: int,
    payload: Optional[schemas.ComprobanteAprobarRequest] = None,
    db: Session = Depends(get_db)
):
    """
    Confirma y cobra un comprobante de pago (desde Confirmación de Recibo o Pendientes Comprobante):
    1. Vincula al cliente (el detectado automáticamente o el indicado por el operador).
    2. Registra el pago en 'historial_pagos' con el banco y número de referencia del OCR.
    3. Descuenta el monto pagado de la deuda pendiente del cliente (Adicional -> Plus -> Internet).
    4. Si la deuda queda en $0.00, reactiva automáticamente el servicio del cliente.
    5. Pasa el comprobante a 'APROBADO' (Registro de Comprobantes ya Cobrados) y envía confirmación por WhatsApp.
    """
    try:
        asegurar_tabla_comprobantes(db)
        comp = db.query(models.Comprobante).filter(models.Comprobante.id == comprobante_id).first()
        if not comp:
            raise HTTPException(status_code=404, detail="Comprobante no encontrado")

        if comp.estado == "APROBADO" and comp.pago_id:
            raise HTTPException(status_code=400, detail="Este comprobante ya fue cobrado y aplicado anteriormente.")

        target_cliente_id = (payload.cliente_id if payload and payload.cliente_id else None) or comp.cliente_id
        if not target_cliente_id:
            raise HTTPException(
                status_code=400,
                detail="Este comprobante no tiene un cliente vinculado. Selecciona o vincula primero el cliente para cobrar el pago."
            )

        cliente = db.query(models.Cliente).filter(models.Cliente.id == target_cliente_id).first()
        if not cliente:
            raise HTTPException(status_code=404, detail=f"Cliente ID #{target_cliente_id} no encontrado en la base de datos.")

        monto_payload = None
        if payload:
            if payload.monto_aplicar is not None:
                monto_payload = payload.monto_aplicar
            elif payload.monto is not None:
                monto_payload = payload.monto

        monto_pagar = monto_payload if monto_payload is not None else comp.monto
        if monto_pagar is None or float(monto_pagar) <= 0:
            deuda_fallback = calcular_deuda_pendiente_cliente(cliente, db)
            if deuda_fallback > 0:
                monto_pagar = deuda_fallback
            else:
                raise HTTPException(status_code=400, detail="El monto del comprobante debe ser mayor a $0.00 para cobrar el pago.")
        monto_pagar = round(float(monto_pagar), 2)

        metodo_pago = (
            (payload.metodo_pago if payload and payload.metodo_pago else None)
            or comp.banco_origen
            or comp.banco_destino
            or "Transferencia"
        )
        referencia_pago = (
            (payload.numero_referencia if payload and payload.numero_referencia else None)
            or comp.numero_referencia
            or f"COMP-{comp.id}"
        )

        ahora_ec = datetime.now(ECUADOR_TZ).replace(tzinfo=None)
        mes_actual = ahora_ec.strftime("%Y-%m")

        # Distribuir el monto pagado entre Adicional, Plus e Internet
        curr_adic = max(0.0, _try_float_val(cliente.adicional))
        curr_plus = max(0.0, _try_float_val(cliente.plus))
        restante_aplicar = monto_pagar

        m_adic = round(min(curr_adic, restante_aplicar), 2)
        restante_aplicar = round(restante_aplicar - m_adic, 2)

        m_plus = round(min(curr_plus, restante_aplicar), 2)
        restante_aplicar = round(restante_aplicar - m_plus, 2)

        m_internet = round(restante_aplicar, 2)

        # Buscar turno de caja abierto si existe
        turno = db.query(models.TurnoCaja).filter(models.TurnoCaja.estado == "Abierto").order_by(models.TurnoCaja.id.desc()).first()
        turno_id = turno.id if turno else None

        nuevo_pago = models.Pago(
            cliente_id=cliente.id,
            monto=monto_pagar,
            metodo_pago=metodo_pago,
            mes_correspondiente=mes_actual,
            referencia=referencia_pago,
            monto_internet=m_internet,
            monto_plus=m_plus,
            monto_adicional=m_adic,
            fecha_pago=ahora_ec,
            estado="Completado",
            anulado=False,
            turnocaja_id=turno_id
        )
        db.add(nuevo_pago)

        # Actualizar saldos del cliente
        if m_adic > 0:
            nuevo_adic = max(0.0, round(curr_adic - m_adic, 2))
            cliente.adicional = str(nuevo_adic) if nuevo_adic > 0 else ""
            cliente.adicional_pagado = round(float(cliente.adicional_pagado or 0.0) + m_adic, 2)

        if m_plus > 0:
            nuevo_plus = max(0.0, round(curr_plus - m_plus, 2))
            cliente.plus = str(nuevo_plus) if nuevo_plus > 0 else ""
            cliente.plus_pagado = round(float(cliente.plus_pagado or 0.0) + m_plus, 2)

        cliente.saldo = round(float(cliente.saldo or 0.0) - m_internet, 2)
        cliente.pago_mensual = round(float(cliente.pago_mensual or 0.0) + monto_pagar, 2)
        cliente.bank = metodo_pago[:50]
        cliente.cod = str(referencia_pago)[:50]
        cliente.payment_date = ahora_ec.strftime("%Y-%m-%d")

        if m_internet > 0:
            prev_net = _try_float_val(cliente.internet_payment)
            cliente.internet_payment = str(round(prev_net + m_internet, 2))

        # Sincronizar total_pago y verificar reactivación en firewall/MikroTik
        reactivado_fw = False
        try:
            from routes.clientes import sync_cliente_balances, verificar_y_reactivar_cliente_por_pago_completo
            sync_cliente_balances(cliente, db)
            info_react = verificar_y_reactivar_cliente_por_pago_completo(cliente, db, motivo="APROBAR_COMPROBANTE_OCR")
            reactivado_fw = bool(info_react.get("reactivado"))
        except Exception as e_sync:
            print(f"[Comprobantes] Aviso sincronizando balances/firewall: {e_sync}")
            cliente.total_pago = round(
                float(cliente.saldo or 0.0) + _try_float_val(cliente.plus) + _try_float_val(cliente.adicional), 2
            )

        db.flush()

        # Actualizar estado del comprobante y moverlo a Registro de Comprobantes ya Cobrados
        comp.cliente_id = cliente.id
        comp.cedula_cliente = getattr(cliente, "cedula", None)
        comp.monto = monto_pagar
        comp.banco_origen = metodo_pago
        comp.numero_referencia = referencia_pago
        comp.estado = "APROBADO"
        comp.pago_id = nuevo_pago.id
        if payload and payload.observaciones:
            comp.observaciones = payload.observaciones
        comp.updated_at = datetime.utcnow()

        db.commit()

        deuda_restante = max(0.0, round(
            max(0.0, _try_float_val(cliente.saldo)) +
            max(0.0, _try_float_val(cliente.plus)) +
            max(0.0, _try_float_val(cliente.adicional)),
            2
        ))

        # Enviar notificación de recibo aprobado por WhatsApp al cliente si está activo
        notificar = True
        if payload is not None:
            if payload.notificar_cliente is not None:
                notificar = bool(payload.notificar_cliente)
            elif payload.notificar_whatsapp is not None:
                notificar = bool(payload.notificar_whatsapp)

        if notificar and comp.numero_telefono:
            try:
                estado_cuenta_txt = (
                    "✅ *Tu cuenta se encuentra al día ($0.00 pendiente).*"
                    if deuda_restante <= 0.01
                    else f"📌 *Saldo restante pendiente:* ${deuda_restante:.2f}"
                )
                msg_confirmacion = (
                    f"🧾 *RECIBO DE PAGO CONFIRMADO - OPSATEL*\n\n"
                    f"Hola *{cliente.nombre}* (ID #{cliente.id}), tu comprobante ha sido verificado y cobrado exitosamente:\n\n"
                    f"💰 *Valor abonado:* ${monto_pagar:.2f}\n"
                    f"🏦 *Entidad:* {metodo_pago}\n"
                    f"🔢 *N° Referencia:* {referencia_pago}\n"
                    f"📅 *Fecha:* {ahora_ec.strftime('%d/%m/%Y %H:%M')}\n"
                    f"{estado_cuenta_txt}\n\n"
                    f"¡Muchas gracias por tu pago puntual! 😊"
                )
                whatsapp_service.send_whatsapp_message(comp.numero_telefono, msg_confirmacion)
            except Exception as e_wa:
                print(f"[Comprobantes] Aviso enviando confirmación WhatsApp: {e_wa}")

        return {
            "success": True,
            "message": f"Pago de ${monto_pagar:.2f} cobrado en BD para {cliente.nombre} (ID #{cliente.id}). Movido a Registro de Comprobantes ya Cobrados.",
            "comprobante_id": comp.id,
            "pago_id": nuevo_pago.id,
            "cliente_id": cliente.id,
            "cliente_nombre": cliente.nombre,
            "monto_aplicado": monto_pagar,
            "saldo_restante": deuda_restante,
            "reactivado_firewall": reactivado_fw
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"[Comprobantes] ❌ Error aprobando comprobante: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error al aprobar el pago del comprobante: {str(e)}")


@router.patch("/comprobantes/{comprobante_id}")
def actualizar_comprobante(
    comprobante_id: int,
    payload: schemas.ComprobanteUpdate,
    db: Session = Depends(get_db)
):
    """Actualiza el estado, cliente vinculado, categoría o notas de verificación de un comprobante"""
    try:
        asegurar_tabla_comprobantes(db)
        comp = db.query(models.Comprobante).filter(models.Comprobante.id == comprobante_id).first()
        if not comp:
            raise HTTPException(status_code=404, detail="Comprobante no encontrado")

        if payload.estado is not None:
            comp.estado = payload.estado.strip().upper()
        if payload.monto is not None:
            comp.monto = payload.monto
        if payload.banco_origen is not None:
            comp.banco_origen = payload.banco_origen.strip()
        if payload.banco_destino is not None:
            comp.banco_destino = payload.banco_destino.strip()
        if payload.numero_referencia is not None:
            comp.numero_referencia = payload.numero_referencia.strip()
        if payload.observaciones is not None:
            comp.observaciones = payload.observaciones.strip()
        if payload.categoria_validacion is not None:
            comp.categoria_validacion = payload.categoria_validacion.strip().upper()
        if payload.motivo_validacion is not None:
            comp.motivo_validacion = payload.motivo_validacion.strip()
        if payload.cliente_id is not None:
            comp.cliente_id = payload.cliente_id
            c_vinc = db.query(models.Cliente).filter(models.Cliente.id == payload.cliente_id).first()
            if c_vinc:
                comp.cedula_cliente = getattr(c_vinc, "cedula", None)
                comp.saldo_pendiente_bd = calcular_deuda_pendiente_cliente(c_vinc)

        comp.updated_at = datetime.utcnow()
        db.commit()

        return {"success": True, "message": "Comprobante actualizado correctamente", "id": comp.id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al actualizar comprobante: {str(e)}")


@router.delete("/comprobantes/{comprobante_id}")
def eliminar_comprobante(
    comprobante_id: int,
    eliminar_archivo: bool = False,
    db: Session = Depends(get_db)
):
    """Elimina el registro de un comprobante y opcionalmente su archivo del disco"""
    try:
        asegurar_tabla_comprobantes(db)
        comp = db.query(models.Comprobante).filter(models.Comprobante.id == comprobante_id).first()
        if not comp:
            raise HTTPException(status_code=404, detail="Comprobante no encontrado")

        if eliminar_archivo and comp.nombre_archivo:
            # Buscar en las rutas de uploadscr para eliminar archivo físico
            for base in [
                os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Opsatel-Frontend", "uploadscr")),
                os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Opsatel-Frontend", "public", "uploadscr")),
                os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "uploadscr"))
            ]:
                f_path = os.path.join(base, comp.nombre_archivo)
                if os.path.exists(f_path):
                    try:
                        os.remove(f_path)
                    except Exception:
                        pass

        db.delete(comp)
        db.commit()
        return {"success": True, "message": "Comprobante eliminado correctamente"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al eliminar comprobante: {str(e)}")



