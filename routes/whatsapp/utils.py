import re
import random
import unicodedata
import urllib.parse
from datetime import datetime
from typing import Optional, List, Dict, Union, Any, Tuple
import pytz
import requests
from sqlalchemy.orm import Session
from sqlalchemy import or_, func

import models
import whatsapp_service

# Zona horaria Ecuador
ECUADOR_TZ = pytz.timezone('America/Guayaquil')

# Caché anti-duplicados para respuestas de comprobantes por WhatsApp (número -> timestamp)
_ultimos_comprobantes_respondidos = {}

# Control en memoria de cancelaciones en tiempo real para difusiones globales y tareas programadas
CANCELLED_DIFUSIONES = set()
GLOBAL_CANCEL_REQUESTED = False


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


def personalizar_mensaje_cliente(mensaje_base: str, cliente) -> str:
    """
    Personaliza un mensaje con los datos del cliente desde la BD.
    Soporta etiquetas: {nombre}, {nombre_completo}, {cliente}, {saldo}, {plan}, {cedula}, {nodo}, {parroquia}.
    Si el mensaje no contiene ninguna etiqueta de nombre, se agrega automáticamente un saludo cordial personalizado con su nombre.
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

    try:
        import sam_bot_service
        cli = sam_bot_service.buscar_cliente_por_celular(num_clean, db)
        if cli:
            return cli, num_clean
    except Exception:
        pass

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
