import os
import requests
import re
from dotenv import load_dotenv

load_dotenv()

# WhatsApp Configuration
WHATSAPP_PROVIDER = os.getenv("WHATSAPP_PROVIDER", "local-bridge").lower()
WHATSAPP_BRIDGE_URL = os.getenv("WHATSAPP_BRIDGE_URL", "http://localhost:3001")
WHATSAPP_API_URL = os.getenv("WHATSAPP_API_URL", "https://api.green-api.com")
WHATSAPP_INSTANCE_ID = os.getenv("WHATSAPP_INSTANCE_ID", "")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")

def format_whatsapp_number(number: str) -> str:
    """
    Cleans a phone number and formats it for WhatsApp.
    - Standardizes Ecuador mobile numbers to start with 593.
    - Extracts the first mobile number if multiple are separated by / , ; or spaces.
    - Rejects Ecuadorian landlines (02, 03, 04, 05, 06, 07) to avoid sending to numbers without WhatsApp.
    - Preserves domain suffixes like @lid or @c.us if present.
    """
    if not number:
        return ""
        
    number_str = str(number).strip()
    server = ""
    if "@" in number_str:
        parts = number_str.split("@", 1)
        number_part = parts[0]
        server = "@" + parts[1]
    else:
        number_part = number_str

    # Si vienen múltiples números (ej: "0991234567 / 0987654321"), tomar el primero
    for sep in ['/', ',', ';', '|', '\n']:
        if sep in number_part:
            number_part = number_part.split(sep)[0].strip()

    cleaned = re.sub(r'\D', '', number_part)
    if not cleaned:
        return ""

    # Detección y filtrado de teléfonos fijos de Ecuador (02, 03, 04, 05, 06, 07)
    # Tienen 9 dígitos y no inician con 9 (los celulares inician con 09 o 9)
    if len(cleaned) == 9 and cleaned.startswith(('02', '03', '04', '05', '06', '07')):
        print(f"[WhatsApp Service] Teléfono fijo detectado ({number_part}). Omitiendo para WhatsApp.")
        return ""

    # Celulares Ecuador:
    # 09xxxxxxxx (10 dígitos) -> 5939xxxxxxxx
    if cleaned.startswith('09') and len(cleaned) == 10:
        cleaned = '593' + cleaned[1:]
    # 9xxxxxxxx (9 dígitos) -> 5939xxxxxxxx
    elif cleaned.startswith('9') and len(cleaned) == 9:
        cleaned = '593' + cleaned
    # 5939xxxxxxxx (12 dígitos) -> ya formateado
    elif cleaned.startswith('5939') and len(cleaned) == 12:
        pass
    # 0xxxxxxxx (10 dígitos genérico) -> 593xxxxxxxx
    elif cleaned.startswith('0') and len(cleaned) == 10:
        cleaned = '593' + cleaned[1:]
    # Internacional general (entre 10 y 15 dígitos)
    elif len(cleaned) >= 10 and len(cleaned) <= 15:
        pass
    else:
        return ""
        
    return f"{cleaned}{server}"

def send_whatsapp_message(numero: str, mensaje: str) -> bool:
    """
    Sends a WhatsApp message using the configured provider.
    Returns True if successful, False otherwise.
    """
    clean_num = format_whatsapp_number(numero)
    if not clean_num:
        print(f"[WhatsApp Service] Error: Número de teléfono inválido o vacío: '{numero}'")
        return False

    # 1. Local Bridge (whatsapp-web.js microservice)
    if WHATSAPP_PROVIDER == "local-bridge":
        url = f"{WHATSAPP_BRIDGE_URL.rstrip('/')}/send"
        payload = {
            "number": clean_num,
            "message": mensaje
        }
        try:
            print(f"[WhatsApp Service] Enviando vía Local Bridge a {clean_num}")
            response = requests.post(url, json=payload, timeout=15)
            if response.status_code == 200:
                res_data = response.json()
                if res_data.get("success"):
                    print(f"[WhatsApp Service] Mensaje enviado exitosamente a {clean_num}")
                    return True
                else:
                    print(f"[WhatsApp Service] Local Bridge reportó error: {res_data.get('error')}")
                    return False
            else:
                print(f"[WhatsApp Service] HTTP Error {response.status_code} desde Local Bridge: {response.text}")
                return False
        except Exception as e:
            print(f"[WhatsApp Service] Error de conexión con Local Bridge: {str(e)}")
            return False

    # 2. Green API
    elif WHATSAPP_PROVIDER == "green-api":
        if not WHATSAPP_INSTANCE_ID or not WHATSAPP_TOKEN:
            print("[WhatsApp Service] Error: Faltan credenciales WHATSAPP_INSTANCE_ID o WHATSAPP_TOKEN para Green API.")
            return False
            
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
        print(f"[WhatsApp Mock Service] Enviando mensaje a {clean_num}: {mensaje}")
        return True

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
