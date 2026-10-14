import os
import requests
import re
import random
import time

# ---------------------------------------------------------------------------
# Anti‑ban rate limiting for WhatsApp mass sending
# ---------------------------------------------------------------------------
# Estado global del limitador: tiempo de inicio del lote actual y contador de mensajes
_batch_start_time: float | None = None
_messages_in_batch: int = 0

def apply_rate_limit() -> None:
    """Aplica pausas aleatorias para evitar bloqueos de WhatsApp.
    - Dentro de un lote de hasta 10 mensajes se espera entre 20‑150 s.
    - Tras completar un lote se espera entre 5‑10 min antes de iniciar el siguiente.
    """
    global _batch_start_time, _messages_in_batch
    now = time.time()
    if _batch_start_time is None:
        _batch_start_time = now
    if _messages_in_batch >= 10:
        # Fin de lote: pausa larga
        wait_seconds = random.uniform(300, 600)  # 5‑10 min
        target_time = _batch_start_time + wait_seconds
        sleep_seconds = max(0.0, target_time - now)
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)
        # Reiniciar lote
        _batch_start_time = time.time()
        _messages_in_batch = 0
    else:
        # Pausa normal entre mensajes del mismo lote
        wait_seconds = random.uniform(20, 150)
        time.sleep(wait_seconds)
        _messages_in_batch += 1

from dotenv import load_dotenv

load_dotenv()

# WhatsApp Configuration
WHATSAPP_PROVIDER = os.getenv("WHATSAPP_PROVIDER", "local-bridge").lower()
WHATSAPP_BRIDGE_URL = os.getenv("WHATSAPP_BRIDGE_URL", "http://localhost:3001")
WHATSAPP_API_URL = os.getenv("WHATSAPP_API_URL", "https://api.green-api.com")
WHATSAPP_INSTANCE_ID = os.getenv("WHATSAPP_INSTANCE_ID", "")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")

# ---------------------------------------------------------------------------
# Configuración anti-bloqueo para envíos masivos (prioridad "bulk")
# El control fino (horario, topes por hora/día, cooldown por número, opt-out)
# vive en el puente Node (whatsapp_bridge.js); aquí solo se respetan sus esperas.
# ---------------------------------------------------------------------------
# Tiempo máximo que un envío masivo puede esperar a que el puente lo autorice (horario/topes/pausas)
BULK_MAX_WAIT_HOURS = float(os.getenv("WA_BULK_MAX_WAIT_H", "20"))
# Tiempo máximo que se espera a que el puente vuelva si está caído/reiniciándose
BRIDGE_DOWN_MAX_WAIT_MIN = float(os.getenv("WA_BRIDGE_DOWN_MAX_WAIT_MIN", "30"))
# Pie de mensaje con opción de baja (reduce reportes de spam). Vacío para desactivar.
BULK_FOOTER = os.getenv("WA_BULK_FOOTER", "_Si no deseas recibir estos avisos, responde *BAJA*._")
# Por defecto un envío masivo va solo al PRIMER número válido del cliente (no a todos sus números)
BULK_ALL_NUMBERS = os.getenv("WA_BULK_ALL_NUMBERS", "false").lower() in ("1", "true", "yes", "si")

_SPINTAX_RE = re.compile(r'\{([^{}|]*\|[^{}]*)\}')

def aplicar_spintax(texto: str) -> str:
    """Resuelve variantes {hola|buen día|saludos} eligiendo una al azar.
    Las etiquetas sin '|' (ej. {nombre}) no se tocan. Varía el texto entre destinatarios."""
    if not texto:
        return texto
    prev = None
    while prev != texto:
        prev = texto
        texto = _SPINTAX_RE.sub(lambda m: random.choice(m.group(1).split('|')), texto)
    return texto

def format_single_number(cleaned: str) -> str:
    """
    Limpia y valida un único número de teléfono (Ecuador o internacional).
    Descarta teléfonos fijos ecuatorianos.
    """
    if not cleaned:
        return ""
    
    server = ""
    if "@" in cleaned:
        parts = cleaned.split("@", 1)
        cleaned = parts[0]
        server = "@" + parts[1]

    digits = re.sub(r'\D', '', cleaned)
    if not digits:
        return ""

    if server.lower() == "@lid":
        return f"{digits}@lid"

    # Teléfonos fijos de Ecuador (9 dígitos iniciando con 02-07): descartar
    if len(digits) == 9 and digits.startswith(('02', '03', '04', '05', '06', '07')):
        return ""

    # Celulares Ecuador:
    # 09xxxxxxxx (10 dígitos) -> 5939xxxxxxxx
    if digits.startswith('09') and len(digits) == 10:
        return f"593{digits[1:]}{server}"
    # 9xxxxxxxx (9 dígitos) -> 5939xxxxxxxx
    elif digits.startswith('9') and len(digits) == 9:
        return f"593{digits}{server}"
    # 5939xxxxxxxx (12 dígitos)
    elif digits.startswith('5939') and len(digits) == 12:
        return f"{digits}{server}"
    # 0xxxxxxxx (10 dígitos genérico) -> 593xxxxxxxx
    elif digits.startswith('0') and len(digits) == 10:
        return f"593{digits[1:]}{server}"
    # Internacional (USA / Canadá: 10 dígitos sin 0 inicial -> 1 + dígitos)
    elif len(digits) == 10 and not digits.startswith('0'):
        return f"1{digits}{server}"
    # Internacional general (entre 10 y 15 dígitos)
    elif 10 <= len(digits) <= 15:
        return f"{digits}{server}"

    return ""

def extract_all_whatsapp_numbers(raw_string: str) -> list:
    """
    Extrae y formatea TODOS los números de teléfono válidos para WhatsApp encontrados
    en una cadena (separados por espacios, comas, barras, guiones, saltos de línea o texto).
    Descarta teléfonos fijos ecuatorianos y números no válidos.
    Garantiza que no haya duplicados manteniendo el orden original.
    """
    if not raw_string:
        return []
    
    raw = str(raw_string).strip()
    if "@" in raw and ("@lid" in raw or "@s.whatsapp.net" in raw):
        single = format_single_number(raw)
        return [single] if single else []

    # Delimitadores explícitos estándar
    delimiters = re.compile(r'[/,;|\\\n\r]|\s+y\s+|\s+o\s+|\s+e\s+|\s+and\s+|\s+or\s+|\s*-\s*', re.IGNORECASE)
    parts = [p.strip() for p in delimiters.split(raw) if p.strip()]

    extracted = []

    for part in parts:
        only_digits = re.sub(r'\D', '', part)
        
        # Si tiene 12 dígitos o menos, evaluarlo como número único
        if len(only_digits) <= 12:
            single = format_single_number(part)
            if single:
                extracted.append(single)
                continue

        # Si tiene más de 12 dígitos, contiene múltiples números separados por espacio o juntos
        tokens = part.split()
        idx = 0
        while idx < len(tokens):
            token = tokens[idx]
            
            # 1. Probar el token individual
            single = format_single_number(token)
            if single:
                extracted.append(single)
                idx += 1
                continue
            
            # 2. Probar combinando con el siguiente token (ej: "646" + "2077179")
            if idx + 1 < len(tokens):
                combined = token + tokens[idx + 1]
                single_comb = format_single_number(combined)
                if single_comb:
                    extracted.append(single_comb)
                    idx += 2
                    continue
            
            # 3. Probar extrayendo patrones celulares ecuatorianos pegados
            sub_matches = re.findall(r'(?:09\d{8}|5939\d{8}|(?<!\d)9\d{8}(?!\d))', token)
            if sub_matches:
                for sm in sub_matches:
                    s_fmt = format_single_number(sm)
                    if s_fmt:
                        extracted.append(s_fmt)

            idx += 1

    # Descartar duplicados manteniendo orden
    seen = set()
    result = []
    for num in extracted:
        if num and num not in seen:
            seen.add(num)
            result.append(num)

    return result

def format_whatsapp_number(number: str) -> str:
    """
    Limpia y formatea un número de teléfono para WhatsApp.
    Si vienen múltiples números en la cadena, extrae todos y devuelve el primero válido.
    """
    if not number:
        return ""
    nums = extract_all_whatsapp_numbers(number)
    return nums[0] if nums else ""

def _post_to_bridge(url: str, payload: dict, priority: str, clean_num: str) -> bool:
    """
    Envía al puente local respetando su gobernador anti-bloqueo.
    - bulk: si el puente responde 429 (fuera de horario, tope, pausa, espaciado) espera `retryAfter` y reintenta;
            si el puente está caído/503 espera y reintenta hasta BRIDGE_DOWN_MAX_WAIT_MIN.
    - manual/reply: sin reintentos largos (el puente solo aplica un espaciado mínimo humano).
    """
    is_bulk = priority == "bulk"
    now = time.time()
    deadline = now + BULK_MAX_WAIT_HOURS * 3600 if is_bulk else now
    down_deadline = now + BRIDGE_DOWN_MAX_WAIT_MIN * 60 if is_bulk else now

    while True:
        try:
            response = requests.post(url, json=payload, timeout=120)
        except Exception as e:
            print(f"[WhatsApp Service] Error de conexión con Local Bridge: {str(e)}")
            if is_bulk and time.time() < down_deadline:
                print("[WhatsApp Service] Puente no disponible. Reintentando en 60s sin marcar fallo...")
                time.sleep(60)
                continue
            return False

        if response.status_code == 200:
            try:
                res_data = response.json()
            except Exception:
                res_data = {}
            if res_data.get("success"):
                print(f"[WhatsApp Service] Mensaje enviado exitosamente a {clean_num}")
                return True
            print(f"[WhatsApp Service] Local Bridge reportó error: {res_data.get('error')}")
            return False

        try:
            data = response.json()
        except Exception:
            data = {}

        if response.status_code == 429 and is_bulk:
            retry_after = float(data.get("retryAfter") or 60)
            if time.time() + retry_after > deadline:
                print(f"[WhatsApp Service] Envío masivo a {clean_num} cancelado: la espera ({retry_after/60:.0f} min) excede el máximo permitido. Motivo: {data.get('error')}")
                return False
            wait = retry_after + random.uniform(2, 25)
            print(f"[WhatsApp Service] ⏳ Envío masivo en espera ({data.get('code')}: {data.get('error')}). Reintento en {wait/60:.1f} min.")
            time.sleep(wait)
            continue

        if response.status_code == 503 and is_bulk and time.time() < down_deadline:
            print("[WhatsApp Service] Puente WhatsApp no conectado (503). Reintentando en 60s sin marcar fallo...")
            time.sleep(60)
            continue

        print(f"[WhatsApp Service] HTTP Error {response.status_code} desde Local Bridge: {response.text}")
        return False


def _send_single_whatsapp_message(clean_num: str, mensaje: str, media_path: str = None, mime_type: str = "image/png", priority: str = "reply") -> bool:
    """
    Envía un mensaje o multimedia a un ÚNICO destinatario limpio.
    priority: 'bulk' (difusión/programado/reintento), 'manual' (operador) o 'reply' (respuesta a mensaje entrante).
    """
    # 1. Local Bridge (whatsapp-web.js microservice)
    if WHATSAPP_PROVIDER == "local-bridge":
        url = f"{WHATSAPP_BRIDGE_URL.rstrip('/')}/send"
        payload = {
            "number": clean_num,
            "message": mensaje,
            "caption": mensaje,
            "priority": priority
        }
        if media_path and os.path.exists(media_path):
            payload["mediaPath"] = os.path.abspath(media_path)
            try:
                import base64
                with open(media_path, "rb") as f_media:
                    payload["mediaBase64"] = base64.b64encode(f_media.read()).decode("utf-8")
                payload["filename"] = os.path.basename(media_path)
                if not mime_type:
                    if media_path.lower().endswith(".png"):
                        mime_type = "image/png"
                    elif media_path.lower().endswith((".jpg", ".jpeg")):
                        mime_type = "image/jpeg"
                payload["mimetype"] = mime_type
                print(f"[WhatsApp Service] Adjuntando media {os.path.basename(media_path)} ({mime_type}) para {clean_num}")
            except Exception as e_b64:
                print(f"[WhatsApp Service] Error codificando base64 de media: {e_b64}")

        print(f"[WhatsApp Service] Enviando vía Local Bridge a {clean_num} (Media: {'Sí' if media_path else 'No'}, prioridad: {priority})")
        return _post_to_bridge(url, payload, priority, clean_num)

    # 2. Green API
    elif WHATSAPP_PROVIDER == "green-api":
        if not WHATSAPP_INSTANCE_ID or not WHATSAPP_TOKEN:
            print("[WhatsApp Service] Error: Faltan credenciales WHATSAPP_INSTANCE_ID o WHATSAPP_TOKEN para Green API.")
            return False

        if media_path and os.path.exists(media_path):
            try:
                url_media = f"{WHATSAPP_API_URL.rstrip('/')}/waInstance{WHATSAPP_INSTANCE_ID}/sendFileByUpload/{WHATSAPP_TOKEN}"
                with open(media_path, "rb") as f_upload:
                    files = {"file": (os.path.basename(media_path), f_upload, mime_type)}
                    data = {"chatId": f"{clean_num}@c.us", "caption": mensaje}
                    res_m = requests.post(url_media, files=files, data=data, timeout=25)
                    if res_m.status_code == 200:
                        print(f"[WhatsApp Service] Green API envió media exitosamente a {clean_num}")
                        return True
            except Exception as e_gmedia:
                print(f"[WhatsApp Service] Error enviando archivo por Green API: {e_gmedia}")
            
        url = f"{WHATSAPP_API_URL.rstrip('/')}/waInstance{WHATSAPP_INSTANCE_ID}/sendMessage/{WHATSAPP_TOKEN}"
        payload = {
            "chatId": f"{clean_num}@c.us",
            "message": mensaje
        }
        headers = {
            "Content-Type": "application/json"
        }
        try:
            print(f"[WhatsApp Service] Enviando vía Green API a {clean_num}")
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            if response.status_code == 200:
                res_data = response.json()
                if "idMessage" in res_data:
                    print(f"[WhatsApp Service] Green API envió mensaje: {res_data['idMessage']}")
                    return True
                else:
                    print(f"[WhatsApp Service] Respuesta Green API sin idMessage: {res_data}")
                    return False
            else:
                print(f"[WhatsApp Service] HTTP Error {response.status_code} desde Green API: {response.text}")
                return False
        except Exception as e:
            print(f"[WhatsApp Service] Error con Green API: {str(e)}")
            return False

    # 3. Evolution API
    elif WHATSAPP_PROVIDER == "evolution-api":
        if not WHATSAPP_INSTANCE_ID or not WHATSAPP_TOKEN:
            print("[WhatsApp Service] Error: Faltan credenciales WHATSAPP_INSTANCE_ID o WHATSAPP_TOKEN para Evolution API.")
            return False

        if media_path and os.path.exists(media_path):
            try:
                import base64
                with open(media_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                url_media = f"{WHATSAPP_API_URL.rstrip('/')}/message/sendMedia/{WHATSAPP_INSTANCE_ID}"
                payload_media = {
                    "number": clean_num,
                    "mediaMessage": {
                        "mediatype": "image" if "image" in mime_type else "document",
                        "caption": mensaje,
                        "media": b64,
                        "fileName": os.path.basename(media_path)
                    }
                }
                headers_media = {"Content-Type": "application/json", "apikey": WHATSAPP_TOKEN}
                res_evo = requests.post(url_media, json=payload_media, headers=headers_media, timeout=25)
                if res_evo.status_code in [200, 201]:
                    print(f"[WhatsApp Service] Evolution API envió media exitosamente a {clean_num}")
                    return True
            except Exception as e_evo:
                print(f"[WhatsApp Service] Error enviando media por Evolution API: {e_evo}")
            
        url = f"{WHATSAPP_API_URL.rstrip('/')}/message/sendText/{WHATSAPP_INSTANCE_ID}"
        payload = {
            "number": clean_num,
            "options": {
                "delay": 1200,
                "presence": "composing"
            },
            "textMessage": {
                "text": mensaje
            }
        }
        headers = {
            "Content-Type": "application/json",
            "apikey": WHATSAPP_TOKEN
        }
        try:
            print(f"[WhatsApp Service] Enviando vía Evolution API a {clean_num}")
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            if response.status_code in [200, 201]:
                print(f"[WhatsApp Service] Evolution API envió mensaje exitosamente a {clean_num}")
                return True
            else:
                print(f"[WhatsApp Service] HTTP Error {response.status_code} desde Evolution API: {response.text}")
                return False
        except Exception as e:
            print(f"[WhatsApp Service] Error con Evolution API: {str(e)}")
            return False

    # 4. Mock / Simulador (Modo desarrollo)
    else:
        if media_path:
            print(f"[WhatsApp Mock Service] Enviando MEDIA ({media_path}) a {clean_num} con caption: {mensaje}")
        else:
            print(f"[WhatsApp Mock Service] Enviando mensaje a {clean_num}: {mensaje}")
        return True

def send_whatsapp_message(numero: str, mensaje: str, media_path: str = None, mime_type: str = "image/png", priority: str = "reply") -> bool:
    """
    Envía un mensaje o multimedia al PRIMER número válido de WhatsApp contenido en 'numero'.
    Si 'numero' contiene múltiples teléfonos (separados por espacio, coma, barra, guion, etc.),
    extrae los números válidos y despacha ÚNICAMENTE al que esté primero, garantizando
    que nunca se envíen mensajes a números secundarios del cliente.
    """
    if not numero:
        print("[WhatsApp Service] Error: Número de teléfono vacío.")
        return False

    targets = extract_all_whatsapp_numbers(numero)
    if not targets:
        single = format_single_number(numero)
        if single:
            targets = [single]
        else:
            print(f"[WhatsApp Service] Error: No se pudo formatear/extraer ningún número válido de '{numero}'.")
            return False

    # REGLA OBLIGATORIA: Enviar únicamente al primer número válido del cliente
    target_num = targets[0]

    is_bulk = priority == "bulk"
    mensaje_envio = mensaje
    if is_bulk:
        mensaje_envio = aplicar_spintax(mensaje)
        if BULK_FOOTER and "BAJA" not in (mensaje_envio or "").upper():
            mensaje_envio = f"{mensaje_envio.rstrip()}\n\n{BULK_FOOTER}"

    return _send_single_whatsapp_message(target_num, mensaje_envio, media_path=media_path, mime_type=mime_type, priority=priority)

def send_whatsapp_media(numero: str, media_path: str, caption: str = "", mime_type: str = "image/png") -> bool:
    """
    Envía un archivo multimedia (imagen, documento, pdf) por WhatsApp con caption opcional.
    """
    return send_whatsapp_message(numero=numero, mensaje=caption, media_path=media_path, mime_type=mime_type)

def get_whatsapp_bridge_status() -> dict:
    """
    Checks the status of the local Node.js bridge.
    """
    if WHATSAPP_PROVIDER != "local-bridge":
        return {"status": "NOT_USING_BRIDGE", "connected": True, "message": f"Usando proveedor: {WHATSAPP_PROVIDER}"}
        
    url = f"{WHATSAPP_BRIDGE_URL.rstrip('/')}/status"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.json()
        return {"status": f"HTTP_{response.status_code}", "connected": False}
    except Exception:
        return {"status": "OFFLINE", "connected": False, "message": "El microservicio Node.js no está corriendo"}

def get_whatsapp_bridge_qr() -> dict:
    """
    Retrieves the QR code base64 from the local Node.js bridge.
    """
    if WHATSAPP_PROVIDER != "local-bridge":
        return {"status": "NOT_USING_BRIDGE", "qr": None, "message": "No estás configurado para usar el puente local."}
        
    url = f"{WHATSAPP_BRIDGE_URL.rstrip('/')}/qr"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.json()
        return {"status": f"HTTP_{response.status_code}", "qr": None, "message": "Error al conectar con el puente"}
    except Exception:
        return {"status": "OFFLINE", "qr": None, "message": "El microservicio Node.js no está corriendo"}
