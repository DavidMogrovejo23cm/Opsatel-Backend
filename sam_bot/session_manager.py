"""
Módulo de gestión de sesiones, memoria y pausas de operador para SAM Chatbot.
"""
import time
import re
from datetime import datetime
import pytz
from typing import Dict, List, Any, Optional

from .llm_client import limpiar_respuesta_ia

# Estructura para almacenar el historial de conversaciones por número en memoria
# Formato: {numero: [{"role": "user"|"assistant", "content": str}]}
historial_conversaciones: Dict[str, List[Dict[str, str]]] = {}

# Estado del skill activo por número: {numero: "skill_name"}
estados_skills: Dict[str, Optional[str]] = {}

# Registro de última interacción por número para auto-expiración (TTL)
ultimas_interacciones: Dict[str, float] = {}

# Memoria de clientes identificados en la sesión actual por número o JID de WhatsApp
# Permite que si alguien escribe de un número externo y ya dio su cédula o celular,
# el bot siga recordando a quién corresponde durante toda la conversación.
clientes_identificados_sesion: Dict[str, Any] = {}

# Límite de inactividad (TTL): 15 minutos en segundos
TTL_INACTIVIDAD_SEGUNDOS: int = 900

# Límite máximo de mensajes en el historial para evitar fugas de memoria
MAX_HISTORY_LEN: int = 12

# Pausa por intervención de Operador Humano: 5 minutos (300 segundos)
PAUSA_OPERADOR_SEGUNDOS: int = 300
pausas_operador: Dict[str, float] = {}


def obtener_fecha_hora_ecuador() -> str:
    """Retorna la fecha y hora actual en la zona horaria de Ecuador (America/Guayaquil)"""
    try:
        ec_tz = pytz.timezone('America/Guayaquil')
        ahora_ec = datetime.now(ec_tz)
        dias_semana = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
        meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
        dia_nom = dias_semana[ahora_ec.weekday()]
        mes_nom = meses[ahora_ec.month - 1]
        hora_str = ahora_ec.strftime("%I:%M %p").lstrip("0")
        return f"{dia_nom.capitalize()} {ahora_ec.day} de {mes_nom} de {ahora_ec.year}, {hora_str} (Ecuador)"
    except Exception:
        return "Ecuador"


def pausar_bot_por_operador(numero: str):
    """
    Pausa las respuestas automáticas de SAM para este contacto durante 5 minutos
    porque un operador humano intervino en la conversación.
    """
    if not numero:
        return
    num_limpio = limpiar_numero_whatsapp(numero)
    expira_en = time.time() + PAUSA_OPERADOR_SEGUNDOS
    pausas_operador[num_limpio] = expira_en
    solo_digitos = re.sub(r'\D', '', num_limpio)
    if solo_digitos and "@lid" not in num_limpio:
        pausas_operador[solo_digitos] = expira_en
    print(f"[SAM Chatbot] ⏸️ Bot pausado para {numero} por 5 minutos (control tomado por Operador).")


def esta_bot_pausado_por_operador(numero: str) -> bool:
    """
    Verifica si el bot está silenciado para este número debido a intervención reciente de operador humano.
    """
    if not numero:
        return False
    ahora = time.time()
    num_limpio = limpiar_numero_whatsapp(numero)

    expira = pausas_operador.get(num_limpio)
    if expira and ahora < expira:
        minutos_restantes = int((expira - ahora) / 60) + 1
        print(f"[SAM Chatbot] 🤫 Bot en silencio para {numero}: Operador humano activo ({minutos_restantes} min restantes).")
        return True
    elif expira:
        pausas_operador.pop(num_limpio, None)

    solo_digitos = re.sub(r'\D', '', num_limpio)
    if solo_digitos and "@lid" not in num_limpio:
        expira_d = pausas_operador.get(solo_digitos)
        if expira_d and ahora < expira_d:
            return True
        elif expira_d:
            pausas_operador.pop(solo_digitos, None)

    return False


def limpiar_sesion_si_expirada(numero: str):
    """Limpia el estado y conversación si pasaron más de 15 minutos de inactividad"""
    ahora = time.time()
    ultimo = ultimas_interacciones.get(numero)
    if ultimo and (ahora - ultimo > TTL_INACTIVIDAD_SEGUNDOS):
        estados_skills[numero] = None
        clientes_identificados_sesion.pop(numero, None)
        if numero in historial_conversaciones:
            historial_conversaciones[numero] = []
    ultimas_interacciones[numero] = ahora


def limpiar_todo_historial_conversaciones():
    """Limpia todo el historial de conversaciones y estados en memoria de SAM."""
    global historial_conversaciones, estados_skills, ultimas_interacciones, pausas_operador, clientes_identificados_sesion
    historial_conversaciones.clear()
    estados_skills.clear()
    ultimas_interacciones.clear()
    pausas_operador.clear()
    clientes_identificados_sesion.clear()
    print("[SAM Chatbot] 🧹 Todo el historial y estados de conversación han sido limpiados en memoria.")


def limpiar_numero_whatsapp(numero: str) -> str:
    """Limpia el formato del número conservando identificadores @lid intactos si corresponden"""
    if not numero:
        return ""
    num_str = str(numero).strip()
    if "@lid" in num_str.lower():
        parts = num_str.split("@")
        clean_user = re.sub(r'[^\w.-]', '', parts[0])
        return f"{clean_user}@lid"
    if "@" in num_str:
        num_str = num_str.split("@")[0]
    return re.sub(r'\D', '', num_str)


def obtener_contexto_conversacion(numero: str, mensaje_actual: str = "") -> str:
    """Construye un string limpio y legible con el historial de la conversación"""
    hist = historial_conversaciones.get(numero, [])
    lineas = []
    for msg in hist:
        raw_text = (msg.get("content") or "").strip()
        clean_text = limpiar_respuesta_ia(raw_text) if msg.get("role") == "assistant" else raw_text
        if not clean_text:
            continue
        role_tag = "Cliente" if msg["role"] == "user" else "SAM"
        lineas.append(f"{role_tag}: {clean_text}")

    # Si se pasa mensaje_actual y aún no está registrado al final de hist, agregarlo
    if mensaje_actual and mensaje_actual.strip():
        msg_act = mensaje_actual.strip()
        if not hist or hist[-1].get("content") != msg_act:
            lineas.append(f"Cliente: {msg_act}")

    return "\n".join(lineas)


def guardar_mensaje_historial(numero: str, role: str, content: str):
    """Guarda un mensaje en el historial sanitizado y recorta si excede el límite"""
    if not content or not str(content).strip():
        return
    clean_content = limpiar_respuesta_ia(content) if role == "assistant" else str(content).strip()
    if not clean_content:
        return
    if numero not in historial_conversaciones:
        historial_conversaciones[numero] = []
    historial_conversaciones[numero].append({"role": role, "content": clean_content})
    if len(historial_conversaciones[numero]) > MAX_HISTORY_LEN:
        historial_conversaciones[numero] = historial_conversaciones[numero][-MAX_HISTORY_LEN:]
