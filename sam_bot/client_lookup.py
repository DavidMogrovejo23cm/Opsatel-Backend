"""
Módulo de búsqueda, identificación y consulta de información de clientes en SAM Chatbot.
"""
import re
import unicodedata
from typing import Dict, Any, Optional, Tuple, List
from sqlalchemy.orm import Session
from sqlalchemy import func, or_

import models
from database import SessionLocal
from .session_manager import clientes_identificados_sesion


def obtener_datos_cliente(cliente_id: int) -> dict:
    """Obtiene información esencial del cliente desde la base de datos.
    Devuelve dict con claves: nombre, saldo, plan, correo, celular.
    """
    db = SessionLocal()
    try:
        cli = db.query(models.Cliente).filter(models.Cliente.id == cliente_id).first()
        if not cli:
            return {}
        return {
            "nombre": cli.nombre,
            "saldo": float(cli.saldo or 0),
            "plan": cli.plan,
            "correo": cli.correo,
            "celular": cli.celular,
        }
    finally:
        db.close()


def normalizar_texto_busqueda(texto: str) -> str:
    """Normaliza texto para búsqueda insensible a acentos, mayúsculas y caracteres especiales."""
    if not texto:
        return ""
    s = unicodedata.normalize('NFD', str(texto))
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = re.sub(r'\(.*?\)', '', s)
    s = re.sub(r'\[.*?\]', '', s)
    s = re.sub(r'[^A-Z0-9\s]', ' ', s.upper())
    return re.sub(r'\s+', ' ', s).strip()


def buscar_cliente_por_celular(numero_limpio: str, db: Session):
    """Busca un cliente cuyo celular contenga el número limpio considerando espacios en la BD y múltiples variantes"""
    if not numero_limpio:
        return None
    num_str = str(numero_limpio).strip()
    digits = re.sub(r'\D', '', num_str)
    if not digits or len(digits) < 6:
        return None

    ultimos_8 = digits[-8:] if len(digits) >= 8 else digits
    ultimos_9 = digits[-9:] if len(digits) >= 9 else digits

    # 1. Búsqueda directa en SQL con func.replace para eliminar espacios y guiones
    try:
        col_clean = func.replace(func.replace(func.replace(models.Cliente.celular, ' ', ''), '-', ''), '.', '')
        cliente = db.query(models.Cliente).filter(
            or_(
                col_clean.like(f"%{ultimos_8}%"),
                col_clean.like(f"%{ultimos_9}%"),
                col_clean == digits
            )
        ).first()
        if cliente:
            return cliente
    except Exception:
        pass

    # 2. Búsqueda en memoria escaneando clientes de la base de datos
    clientes = db.query(models.Cliente).all()
    for c in clientes:
        if c.celular:
            c_digits = re.sub(r'\D', '', str(c.celular))
            if c_digits and (c_digits == digits or (len(c_digits) >= 8 and c_digits[-8:] == ultimos_8)):
                return c
    return None


def buscar_cliente_por_cedula(cedula_str: str, db: Session):
    """
    Busca un cliente por número de cédula o RUC en MySQL/PostgreSQL.
    Soporta cédulas de 10 dígitos, cédulas de 9 dígitos (sin cero inicial común en exportaciones de Excel)
    y RUCs de 13 dígitos. Limpia espacios, puntos y guiones.
    """
    if not cedula_str or not db:
        return None
    num_str = str(cedula_str).strip()
    digits = re.sub(r'\D', '', num_str)
    if not digits or len(digits) < 8:
        return None

    # Si es RUC (13 dígitos), la cédula base son los primeros 10 dígitos
    base_ced = digits[:10] if len(digits) == 13 else digits

    # Generar variantes con y sin cero a la izquierda para Ecuador
    variantes = [base_ced]
    if len(base_ced) == 9:
        variantes.append("0" + base_ced)
    elif len(base_ced) == 10 and base_ced.startswith("0"):
        variantes.append(base_ced[1:])
    if len(digits) == 13 and digits not in variantes:
        variantes.append(digits)

    # 1. Búsqueda directa SQL
    try:
        col_ced_clean = func.replace(func.replace(func.replace(models.Cliente.cedula, ' ', ''), '-', ''), '.', '')
        filtros = []
        for v in variantes:
            filtros.append(models.Cliente.cedula == v)
            filtros.append(col_ced_clean == v)
            filtros.append(models.Cliente.cedula.like(f"%{v}%"))

        cliente = db.query(models.Cliente).filter(or_(*filtros)).first()
        if cliente:
            return cliente
    except Exception as e:
        print(f"[SAM Chatbot] Aviso buscando cliente por cédula en SQL: {e}")

    # 2. Búsqueda en memoria escaneando clientes de la BD si SQL no coincidió por formatos extraños
    try:
        clientes = db.query(models.Cliente).all()
        for c in clientes:
            if c.cedula:
                c_clean = re.sub(r'\D', '', str(c.cedula))
                if c_clean in variantes:
                    return c
                if len(c_clean) >= 9 and any(v == c_clean or v.endswith(c_clean) or c_clean.endswith(v) for v in variantes):
                    return c
    except Exception:
        pass

    return None


def buscar_cliente_por_cedula_o_celular(identificador: str, db: Session):
    """
    Busca al cliente ya sea por su NÚMERO DE CÉDULA o por su NÚMERO DE CELULAR.
    Cualquiera de los dos sirve mientras esté registrado en la base de datos.
    Permite identificar a un cliente incluso si escribe desde un número de WhatsApp completamente externo.
    """
    if not identificador or not db:
        return None

    num_str = str(identificador).strip()
    digits = re.sub(r'\D', '', num_str)
    if not digits or len(digits) < 6:
        return None

    # En Ecuador los números celulares suelen empezar con 09 o 5939 o 9 (de 9 a 12 dígitos)
    es_probable_celular = (
        digits.startswith("09")
        or digits.startswith("5939")
        or (len(digits) == 9 and digits.startswith("9"))
    )

    if es_probable_celular:
        # Priorizar búsqueda por celular, luego intentar por cédula
        cli = buscar_cliente_por_celular(identificador, db)
        if cli:
            return cli
        cli = buscar_cliente_por_cedula(identificador, db)
        if cli:
            return cli
    else:
        # Priorizar búsqueda por cédula, luego intentar por celular
        cli = buscar_cliente_por_cedula(identificador, db)
        if cli:
            return cli
        cli = buscar_cliente_por_celular(identificador, db)
        if cli:
            return cli

    return None


def buscar_cliente_por_nombre(nombre_buscar: str, db: Session) -> Tuple[Optional[Any], List]:
    """
    Busca de forma exhaustiva en la tabla General de Clientes (models.Cliente):
    1. Normaliza acentos, mayúsculas y quita etiquetas como (WhatsApp).
    2. Comprueba si todas las palabras del nombre buscado están en el cliente de la BD (sin importar orden).
    3. Comprueba con rapidfuzz token_set_ratio.
    4. Comprueba palabras distintivas individuales (>= 5 letras).
    """
    if not nombre_buscar:
        return None, []

    nombre_norm = normalizar_texto_busqueda(nombre_buscar)
    if not nombre_norm or len(nombre_norm) < 2:
        return None, []

    clientes = db.query(models.Cliente).all()
    if not clientes:
        return None, []

    palabras = [w for w in nombre_norm.split() if len(w) >= 3]

    # 1. Búsqueda cruzada de palabras (ej: 'ANDRES' y 'SOLANO' en 'SOLANO CHALCO ANDRES')
    if palabras:
        for c in clientes:
            if c.nombre:
                c_norm = normalizar_texto_busqueda(c.nombre)
                if all(p in c_norm for p in palabras):
                    return c, []

    # 2. Búsqueda con rapidfuzz token_set_ratio (ignora orden de palabras y variaciones leves)
    try:
        from rapidfuzz import fuzz
        mejor_cliente = None
        mejor_score = 0
        for c in clientes:
            if c.nombre:
                c_norm = normalizar_texto_busqueda(c.nombre)
                score = fuzz.token_set_ratio(nombre_norm, c_norm)
                if score > mejor_score:
                    mejor_score = score
                    mejor_cliente = c

        if mejor_cliente and mejor_score >= 70:
            return mejor_cliente, []
    except Exception as e:
        print(f"[SAM Chatbot] Error en rapidfuzz: {e}")

    # 3. Palabra distintiva única (>= 5 letras, ej: 'SOLANO' o 'MOGROVEJO')
    for p in palabras:
        if len(p) >= 5:
            coincidencias = [c for c in clientes if c.nombre and p in normalizar_texto_busqueda(c.nombre)]
            if len(coincidencias) == 1:
                return coincidencias[0], []

    return None, []


def extraer_identificador_cliente(texto: str) -> str:
    """
    Extrae un número de cédula (9 a 13 dígitos) o celular (8 a 13 dígitos) del texto del mensaje.
    Soporta formatos con espacios, guiones o precedidos por palabras clave
    (ej: "mi cédula es 0105905251", "mi cel 0987149097", "0105905251", "098-714-9097").
    """
    if not texto:
        return ""

    # 1. Búsqueda explícita tras palabras clave de cédula, celular, teléfono o contrato
    patron_clave = re.search(
        r'(?:c[eé]dula|c\.?i\.?|ruc|celular|tel[eé]fono|cel|n[uú]mero|contrato)\D{0,10}(\d[\d\s\-\.]{7,15}\d)',
        texto,
        re.IGNORECASE
    )
    if patron_clave:
        extraido = re.sub(r'\D', '', patron_clave.group(1))
        if 8 <= len(extraido) <= 13:
            return extraido

    # 2. Búsqueda de cualquier secuencia de 9 a 13 dígitos contiguos
    match_secuencia = re.search(r'\b\d{9,13}\b', texto)
    if match_secuencia:
        return match_secuencia.group(0)

    # 3. Limpiar espacios, puntos y guiones si el mensaje contiene dígitos formateados
    limpio = re.sub(r'[\s\-.]', '', texto)
    match_limpio = re.search(r'\d{9,13}', limpio)
    if match_limpio:
        return match_limpio.group(0)

    return ""


def extraer_cedula(texto: str) -> str:
    """Extrae un identificador (cédula o celular) del texto. Mantiene compatibilidad con llamadas existentes."""
    return extraer_identificador_cliente(texto)


def obtener_cliente_sesion(numero: str, db: Session, mensaje: str = ""):
    """
    Obtiene el cliente asociado a la conversación actual:
    1. Si en el mensaje actual el usuario envió una cédula o celular registrado, lo busca y asocia.
    2. Si en la sesión ya se identificó previamente al cliente, lo recupera por ID.
    3. Si el número telefónico desde donde escribe pertenece a un cliente registrado, lo vincula.
    4. Si es un administrador con número telefónico registrado, busca por su teléfono.
    """
    if not db:
        return None

    # 1. Si el mensaje actual contiene una cédula o celular registrado
    if mensaje:
        cand = extraer_identificador_cliente(mensaje)
        if cand:
            c = buscar_cliente_por_cedula_o_celular(cand, db)
            if c:
                clientes_identificados_sesion[numero] = c.id
                return c

    # 2. Si ya está registrado en la memoria de la sesión
    c_id = clientes_identificados_sesion.get(numero)
    if c_id:
        c = db.query(models.Cliente).filter(models.Cliente.id == c_id).first()
        if c:
            return c

    # 3. Búsqueda por el número telefónico de WhatsApp
    c = buscar_cliente_por_celular(numero, db)
    if c:
        clientes_identificados_sesion[numero] = c.id
        return c

    # 4. Verificar si es número administrador con teléfono propio
    # Import diferido para evitar ciclos entre admin_commands y client_lookup
    from .admin_commands import es_numero_administrador
    adm = es_numero_administrador(numero, db)
    if adm and getattr(adm, "numero", None):
        c = buscar_cliente_por_celular(adm.numero, db)
        if c:
            return c

    return None


def obtener_deuda_total_cliente(cliente) -> dict:
    """
    Obtiene los valores oficiales y consolidados de deuda del cliente directamente del sistema:
    - total: suma total pendiente (Internet + IPTV Plus + Adicional) o total_pago consolidado
    - internet: saldo base del servicio de internet
    - iptv: valor extra por IPTV (plus)
    - adicional: valor de cargos adicionales
    - desglose: texto explicativo corto para el cliente (ej: " ($17.50 internet + $4.00 IPTV + $5.00 adicional)")
    """
    if not cliente:
        return {"total": 0.0, "internet": 0.0, "iptv": 0.0, "adicional": 0.0, "desglose": ""}

    def _to_float(val):
        if val is None or val == "":
            return 0.0
        try:
            s = str(val).replace("$", "").replace(",", ".").strip()
            return float(s) if s else 0.0
        except (ValueError, TypeError):
            return 0.0

    saldo_internet = _to_float(getattr(cliente, "saldo", 0.0))
    iptv_val = _to_float(getattr(cliente, "plus", 0.0))
    adicional_val = _to_float(getattr(cliente, "adicional", 0.0))

    # El sistema consolida en total_pago la deuda total real:
    total_guardado = _to_float(getattr(cliente, "total_pago", None))
    total_calculado = max(0.0, saldo_internet + iptv_val + adicional_val)

    if total_guardado > 0 and total_guardado >= total_calculado:
        total_real = total_guardado
    else:
        total_real = total_calculado

    desglose_items = []
    if saldo_internet > 0:
        desglose_items.append(f"${saldo_internet:.2f} internet")
    if iptv_val > 0:
        desglose_items.append(f"${iptv_val:.2f} IPTV")
    if adicional_val > 0:
        desglose_items.append(f"${adicional_val:.2f} adicional")

    desglose_str = ""
    if len(desglose_items) > 1:
        desglose_str = f" ({' + '.join(desglose_items)})"

    return {
        "total": total_real,
        "internet": saldo_internet,
        "iptv": iptv_val,
        "adicional": adicional_val,
        "desglose": desglose_str
    }
