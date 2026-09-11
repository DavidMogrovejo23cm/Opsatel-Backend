import os
import re
import json
import time
from dotenv import load_dotenv

# Cargar automáticamente variables de entorno desde .env
load_dotenv()

from sqlalchemy.orm import Session
import models
# pyrefly: ignore [missing-import]
from rapidfuzz import fuzz, process
import whatsapp_service

# Configuración de Modelos de Inteligencia Artificial
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-3-5-haiku-20241022")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

client_gemini = None
client_anthropic = None

def get_gemini_client():
    """Inicializa y retorna el cliente de Google Gemini si GEMINI_API_KEY o GOOGLE_API_KEY está presente"""
    global client_gemini
    if client_gemini is None:
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if api_key and api_key.strip():
            try:
                # pyrefly: ignore [missing-import]
                from google import genai
                client_gemini = genai.Client(api_key=api_key.strip())
                print(f"[SAM Chatbot] [IA] Cliente Google Gemini conectado exitosamente ({GEMINI_MODEL}).")
            except Exception as e:
                print(f"[SAM Chatbot] Error inicializando Google Gemini: {e}")
                client_gemini = None
        else:
            return None
    return client_gemini

def get_anthropic_client():
    """Inicializa y retorna el cliente de Anthropic Claude como alternativa"""
    global client_anthropic
    if client_anthropic is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if api_key and api_key.strip():
            try:
                # pyrefly: ignore [missing-import]
                import anthropic
                client_anthropic = anthropic.Anthropic(api_key=api_key.strip())
                print(f"[SAM Chatbot] [IA] Cliente Anthropic Claude conectado exitosamente ({CLAUDE_MODEL}).")
            except Exception as e:
                print(f"[SAM Chatbot] Error inicializando Anthropic: {e}")
                client_anthropic = None
        else:
            return None
    return client_anthropic

active_groq_model = None

def llamar_groq_api(prompt: str, max_tokens: int = 500, temperature: float = 0.5) -> str:
    """Llama a la API de Groq consultando dinámicamente los modelos activos disponibles"""
    global active_groq_model
    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key or not groq_key.strip():
        return ""
    import requests
    headers = {
        "Authorization": f"Bearer {groq_key.strip()}",
        "Content-Type": "application/json"
    }

    # Si ya tenemos un modelo activo que funcionó antes, intentarlo primero
    candidate_models = []
    if active_groq_model:
        candidate_models.append(active_groq_model)
    if os.getenv("GROQ_MODEL"):
        candidate_models.append(os.getenv("GROQ_MODEL"))

    # Consultar dinámicamente la lista de modelos activos en Groq
    try:
        models_resp = requests.get("https://api.groq.com/openai/v1/models", headers=headers, timeout=10)
        if models_resp.status_code == 200:
            data = models_resp.json().get("data", [])
            live_ids = [m.get("id") for m in data if m.get("id")]
            print(f"[SAM Chatbot] [Groq] Modelos activos reportados por Groq: {live_ids}")
            # Filtrar solo modelos conversacionales de texto
            chat_models = [
                m for m in live_ids
                if not any(x in m.lower() for x in ["whisper", "guard", "safeguard", "embed", "tts", "audio", "vision-preview"])
            ]
            for m in chat_models:
                if m not in candidate_models:
                    candidate_models.append(m)
    except Exception as e_mod:
        print(f"[SAM Chatbot] [Groq] Advertencia consultando modelos activos: {e_mod}")

    # Fallback predeterminado por si falla la consulta
    for fb in ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "qwen-2.5-32b", "mixtral-8x7b-32768"]:
        if fb not in candidate_models:
            candidate_models.append(fb)

    chat_url = "https://api.groq.com/openai/v1/chat/completions"
    last_err = None
    for model in candidate_models:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature
        }
        try:
            resp = requests.post(chat_url, headers=headers, json=payload, timeout=25)
            if resp.status_code == 200:
                data = resp.json()
                active_groq_model = model
                print(f"[SAM Chatbot] [Groq] [OK] Respuesta generada exitosamente con modelo: {model}")
                return data["choices"][0]["message"]["content"].strip()
            else:
                last_err = f"HTTP {resp.status_code}: {resp.text}"
                print(f"[SAM Chatbot] [Groq] Error probando {model}: {last_err}")
                continue
        except Exception as e_req:
            last_err = str(e_req)
            continue

    if last_err:
        print(f"[SAM Chatbot] Error final en llamada a Groq: {last_err}")
    return ""

def llamar_openai_api(prompt: str, max_tokens: int = 500, temperature: float = 0.5) -> str:
    """Llama a la API de OpenAI (GPT-4o mini)"""
    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key or not openai_key.strip():
        return ""
    import requests
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {openai_key.strip()}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": OPENAI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=25)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()

def hay_proveedor_ia() -> bool:
    """Verifica si hay al menos un proveedor de IA disponible"""
    return bool(
        get_gemini_client() or
        os.getenv("GROQ_API_KEY") or
        os.getenv("OPENAI_API_KEY") or
        get_anthropic_client()
    )

def generar_respuesta_ia(prompt: str, max_tokens: int = 500, temperature: float = 0.5) -> str:
    """
    Genera texto usando los proveedores disponibles en orden de prioridad:
    1. Groq (Ultra-rápido, gratuito, ideal para VPS)
    2. Google Gemini
    3. OpenAI
    4. Anthropic Claude
    """
    global GEMINI_MODEL

    # Si hay GROQ configurado, es la opción más rápida y sin bloqueos de IP
    if os.getenv("GROQ_API_KEY"):
        try:
            res = llamar_groq_api(prompt, max_tokens, temperature)
            if res:
                return res
        except Exception as e_groq:
            print(f"[SAM Chatbot] Error en llamada a Groq: {e_groq}")

    # 2. Intentar con Google Gemini
    client_g = get_gemini_client()
    if client_g:
        # pyrefly: ignore [missing-import]
        from google.genai import types
        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        model_candidates = [
            GEMINI_MODEL,
            "gemini-2.5-flash",
            "gemini-1.5-flash",
            "gemini-3.6-flash",
            "gemini-2.0-flash-exp",
            "gemini-1.5-pro",
        ]
        seen = set()
        model_list = [m for m in model_candidates if not (m in seen or seen.add(m))]

        for model_name in model_list:
            try:
                response = client_g.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=config
                )
                if response and response.text:
                    if GEMINI_MODEL != model_name:
                        print(f"[SAM Chatbot] [IA] Modelo Gemini activo verificado: {model_name}")
                        GEMINI_MODEL = model_name
                    return response.text.strip()
            except Exception as e_gem:
                err_str = str(e_gem)
                if "404" in err_str or "NOT_FOUND" in err_str or "no longer available" in err_str:
                    print(f"[SAM Chatbot] [IA] Modelo '{model_name}' no disponible, probando siguiente variante...")
                    continue
                else:
                    print(f"[SAM Chatbot] Error en llamada a Gemini ({model_name}): {e_gem}")
                    break

    # 3. Intentar con OpenAI si está configurado
    if os.getenv("OPENAI_API_KEY"):
        try:
            res = llamar_openai_api(prompt, max_tokens, temperature)
            if res:
                return res
        except Exception as e_oai:
            print(f"[SAM Chatbot] Error en llamada a OpenAI: {e_oai}")

    # 4. Intentar con Anthropic Claude (Respaldo)
    client_a = get_anthropic_client()
    if client_a:
        try:
            response = client_a.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}]
            )
            if response and response.content:
                return response.content[0].text.strip()
        except Exception as e_ant:
            print(f"[SAM Chatbot] Error en llamada a Anthropic: {e_ant}")

    raise RuntimeError("No se pudo obtener respuesta de ningún proveedor de IA configurado.")

# Estructura para almacenar el historial de conversaciones por número en memoria
# Formato: {numero: [{"role": "user"|"assistant", "content": str}]}
historial_conversaciones = {}
# Estado del skill activo por número: {numero: "skill_name"}
estados_skills = {}
# Registro de última interacción por número para auto-expiración (TTL)
ultimas_interacciones = {}

# Límite de inactividad (TTL): 15 minutos en segundos
TTL_INACTIVIDAD_SEGUNDOS = 900
# Límite máximo de mensajes en el historial para evitar fugas de memoria
MAX_HISTORY_LEN = 12

# Pausa por intervención de Operador Humano: 5 minutos (300 segundos)
PAUSA_OPERADOR_SEGUNDOS = 300
pausas_operador = {}

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
        if numero in historial_conversaciones:
            historial_conversaciones[numero] = []
    ultimas_interacciones[numero] = ahora

def limpiar_todo_historial_conversaciones():
    """Limpia todo el historial de conversaciones y estados en memoria de SAM."""
    global historial_conversaciones, estados_skills, ultimas_interacciones, pausas_operador
    historial_conversaciones.clear()
    estados_skills.clear()
    ultimas_interacciones.clear()
    pausas_operador.clear()
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

def obtener_contexto_conversacion(numero: str, mensaje_actual: str) -> str:
    """Construye un string con el historial y el mensaje actual"""
    hist = historial_conversaciones.get(numero, [])
    contexto = ""
    for msg in hist:
        role_tag = "user" if msg["role"] == "user" else "assistant"
        contexto += f"{role_tag}: {msg['content']}\n"
    contexto += f"user: {mensaje_actual}"
    return contexto

def guardar_mensaje_historial(numero: str, role: str, content: str):
    """Guarda un mensaje en el historial y recorta si excede el límite"""
    if numero not in historial_conversaciones:
        historial_conversaciones[numero] = []
    historial_conversaciones[numero].append({"role": role, "content": content})
    if len(historial_conversaciones[numero]) > MAX_HISTORY_LEN:
        historial_conversaciones[numero] = historial_conversaciones[numero][-MAX_HISTORY_LEN:]

def clasificar_intencion(contexto: str, mensaje_actual: str = "") -> str:
    """
    Clasifica la intención del usuario basándose prioritariamente en su ÚLTIMO mensaje,
    permitiendo cambios de tema inmediatos para evitar atascos.
    """
    msg_limpio = mensaje_actual.strip().lower() if mensaje_actual else ""
    if not msg_limpio and contexto:
        lineas = contexto.strip().split("\n")
        msg_limpio = lineas[-1].replace("user:", "").strip().lower() if lineas else ""

    # 1. Preguntas sobre identidad, nombre del bot o charla social -> GENERAL
    if any(w in msg_limpio for w in [
        "como te llamas", "cómo te llamas", "quien eres", "quién eres", "tu nombre",
        "que haces", "qué haces", "hola", "buenos dias", "buenas tardes", "buenas noches",
        "saludos", "que tal", "sam", "ayuda"
    ]):
        # Si no menciona deuda ni falla, es charla general
        if not any(w in msg_limpio for w in ["debo", "saldo", "foco rojo", "sin internet"]):
            return "general"

    # 2. Consultas sobre Planes, Ofertas, Precios, Megas o Servicios -> GENERAL (para responder con los datos reales de BD)
    if any(w in msg_limpio for w in [
        "plan", "planes", "precio", "precios", "oferta", "ofertas", "megas", "costo",
        "tarifa", "cuanto cuesta", "cuánto cuesta", "cuanto vale", "cuánto vale",
        "que ofrecen", "qué ofrecen", "servicios", "promocion", "promociones", "contratar",
        "adquirir", "velocidad", "cobertura"
    ]):
        return "general"

    # 3. Consultas explícitas de Pago / Saldo / Deuda personal
    tiene_cedula = bool(re.search(r'\b\d{10}\b', msg_limpio))
    es_pregunta_deuda = any(w in msg_limpio for w in [
        "cuanto debo", "cuánto debo", "mi saldo", "saldo pendiente", "mi deuda",
        "mi factura", "factura pendiente", "estado de cuenta", "cuanto tengo que pagar",
        "cuánto tengo que pagar", "pago pendiente", "mi pago"
    ])
    if tiene_cedula or es_pregunta_deuda:
        return "consultar_pagos_y_saldos"

    # 4. Soporte técnico / fallas
    if any(w in msg_limpio for w in [
        "foco rojo", "luz roja", "sin internet", "sin servicio", "no tengo internet",
        "no hay internet", "se fue el internet", "sin señal", "sin senal", "luz los",
        "los rojo", "parpadea", "modem", "módem", "router", "falla", "fallando", "desconectado", "cable roto"
    ]):
        return "soporte_tecnico_foco_rojo"

    # 5. Entretenimiento / películas
    if any(w in msg_limpio for w in [
        "pelicula", "película", "serie", "recomendar", "recomendacion", "recomendación",
        "sugerir", "sugerencia", "qué ver", "que ver", "opsatv", "estrenos",
        "tendencia", "cartelera"
    ]):
        return "recomendacion_peliculas_opsatv"

    # 6. Registro formal de instalación / cliente potencial
    if any(w in msg_limpio for w in ["nuevo cliente", "prospecto", "ingresar cliente", "nueva instalacion"]):
        return "registrar_cliente_potencial"

    # 7. Agradecimientos / Cierre
    if any(w in msg_limpio for w in ["gracias", "muchas gracias", "ya funciona", "ya vale", "perfecto", "listo gracias", "chao", "adios"]):
        return "general"

    # 8. Clasificación con IA si no coincide con las reglas anteriores
    if not hay_proveedor_ia():
        return "general"

    prompt = f"""Eres un enrutador inteligente de intenciones del chatbot SAM de Opsatel.
Tu objetivo es clasificar la intención del usuario basándote prioritariamente en su ÚLTIMO mensaje.

Reglas:
- Si el usuario pregunta por planes de internet, precios, ofertas, megas, servicios o cómo te llamas / quién eres, responde siempre: "general".
- Si el usuario pregunta cuánto debe de su saldo personal o envía una cédula, responde: "consultar_pagos_y_saldos".
- Si el usuario reporta una avería o foco rojo en el módem, responde: "soporte_tecnico_foco_rojo".
- Si pide películas o series, responde: "recomendacion_peliculas_opsatv".
- De lo contrario, responde: "general".

Último mensaje del usuario: "{msg_limpio}"

Responde únicamente con una de estas opciones: "general", "consultar_pagos_y_saldos", "soporte_tecnico_foco_rojo", "recomendacion_peliculas_opsatv" o "registrar_cliente_potencial"."""

    try:
        intencion = generar_respuesta_ia(prompt, max_tokens=25, temperature=0.0).lower().strip()
        valid_intents = ["registrar_cliente_potencial", "consultar_pagos_y_saldos", "recomendacion_peliculas_opsatv", "soporte_tecnico_foco_rojo", "general"]
        for intent in valid_intents:
            if intent in intencion:
                return intent
        return "general"
    except Exception as e:
        print(f"[SAM Chatbot] Error clasificando intención con IA: {e}")
        return "general"


# -------------------------------------------------------------
# SKILL: REGISTRAR CLIENTE POTENCIAL
# -------------------------------------------------------------
PROMPT_REGISTRO_CLIENTE = """# Skill: Registrar Cliente
Eres SAM, la IA encargada de recopilar los datos para registrar un nuevo cliente en el sistema de OPSATEL.
"""

def procesar_registro_cliente(numero: str, mensaje: str, contexto: str, db: Session) -> str:
    # Obtener entidades de la base de datos para fuzzy mapping
    valid_nodos = [n[0] for n in db.query(models.Nodo.nombre).filter(models.Nodo.nombre != None).all()]
    valid_planes = [pl[0] for pl in db.query(models.PlanInternet.nombre).filter(models.PlanInternet.nombre != None).all()]

    prompt_dinamico = f"""# Skill: Registrar Cliente
Eres SAM, la IA encargada de recopilar los datos para registrar un nuevo cliente en el sistema de OPSATEL.
Debes mantener un tono amigable, claro, profesional y dar respuestas cortas.
Siempre menciona que eres SAM, el Sistema Autónomo Multitarea de OPSATEL y que vas a recopilar datos para registrar un cliente.

Los datos que debes conseguir son:
* nombre: Nombre completo del cliente.
* cedula: Cédula o RUC (10 o 13 dígitos).
* celular: Teléfono de contacto.
* direccion: Dirección domiciliaria.
* plan: Plan de internet elegido (debe mapearse a uno de los PLANES VÁLIDOS).
* nodo: Sector o Nodo de red (debe mapearse a uno de los NODOS VÁLIDOS).
* parroquia: Parroquia.
* latitud: Latitud GPS (opcional, si se conoce).
* longitud: Longitud GPS (opcional, si se conoce).
* comentarios: Notas adicionales (opcional).

PLANES VÁLIDOS en el sistema: {json.dumps(valid_planes, ensure_ascii=False)}
NODOS VÁLIDOS en el sistema: {json.dumps(valid_nodos, ensure_ascii=False)}

Reglas:
- No inventes datos.
- Si falta algún dato obligatorio (nombre, cedula, celular, direccion, plan, nodo), pídelo amigablemente. Puedes pedir varios datos juntos para agilizar.
- Muestra el avance estructurado para que el usuario lo vea de esta forma:
Nombre: <valor o (pendiente)>
Cédula: <valor o (pendiente)>
Celular: <valor o (pendiente)>
Dirección: <valor o (pendiente)>
Plan: <valor o (pendiente)>
Nodo: <valor o (pendiente)>
Parroquia: <valor o (pendiente)>
Coordenadas GPS: <latitud, longitud o (pendiente)>
Comentarios: <valor o (pendiente)>

- Cuando TODOS los datos obligatorios estén listos, muestra la ficha y pide confirmación explícita.
- Únicamente cuando el usuario confirme diciendo "sí", "correcto", "confirmado", "ok", etc., genera un JSON final de una sola línea, sin preámbulos ni explicaciones.

Formato exacto del JSON final:
{{"nombre": "", "cedula": "", "celular": "", "direccion": "", "plan": "", "nodo": "", "parroquia": "", "latitud": 0.0, "longitud": 0.0, "comentarios": ""}}
"""

    try:
        content = f"{prompt_dinamico}\n\nConversación hasta ahora:\n{contexto}"
        res_text = generar_respuesta_ia(content, max_tokens=600, temperature=0.2)
        
        # Verificar si la IA generó el JSON final
        json_match = re.search(r'\{.*"nombre".*\}', res_text)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                
                # Crear cliente en la tabla real (hoja_de_c__lculo_sin_t__tulo)
                ubicacion_gps = f"{data.get('latitud') or 0.0}, {data.get('longitud') or 0.0}"
                
                # Normalización de cédula y celular
                cedula = str(data.get("cedula") or "").strip()
                if cedula.isdigit() and len(cedula) == 9:
                    cedula = "0" + cedula
                    
                celular = str(data.get("celular") or "").strip()
                if celular.isdigit() and len(celular) == 9 and celular.startswith("9"):
                    celular = "0" + celular

                # Lógica para reutilizar IDs (Encontrar el primer hueco disponible)
                ids_query = db.query(models.Cliente.id).order_by(models.Cliente.id).all()
                ids = [i[0] for i in ids_query]
                
                nuevo_id = 1
                for current_id in ids:
                    if current_id == nuevo_id:
                        nuevo_id += 1
                    elif current_id > nuevo_id:
                        break # Encontramos un hueco

                nuevo_cliente = models.Cliente(
                    id=nuevo_id,
                    nombre=data.get("nombre"),
                    cedula=cedula,
                    celular=celular,
                    direccion=data.get("direccion"),
                    plan=data.get("plan"),
                    nodo=data.get("nodo"),
                    parroquia=data.get("parroquia"),
                    ubicacion=ubicacion_gps,
                    comentarios=data.get("comentarios"),
                    estado="Pendiente",
                    saldo=0.00
                )
                
                db.add(nuevo_cliente)
                db.commit()
                db.refresh(nuevo_cliente)
                
                # Limpiar estado de skill
                estados_skills[numero] = None
                if numero in historial_conversaciones:
                    historial_conversaciones[numero] = []
                    
                return f"✅ ¡Perfecto! He registrado a *{data.get('nombre')}* en el sistema de OPSATEL en estado Pendiente exitosamente."
            except Exception as db_err:
                print(f"[SAM Chatbot] Error guardando cliente: {db_err}")
                db.rollback()
                return "Hubo un inconveniente al guardar los datos del cliente en la base de datos. Por favor, reintente en unos momentos."
        else:
            return res_text
    except Exception as e:
        print(f"[SAM Chatbot] Error en skill registrar cliente: {e}")
        return "Disculpa, tuve un problema al procesar el registro de cliente. ¿Podrías indicarme los datos nuevamente?"

# -------------------------------------------------------------
# SKILL: CONSULTAR PAGOS Y SALDOS
# -------------------------------------------------------------
def normalizar_texto_busqueda(texto: str) -> str:
    if not texto:
        return ""
    import unicodedata
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
        from sqlalchemy import func, or_
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


def buscar_cliente_por_nombre(nombre_buscar: str, db: Session):
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
        # pyrefly: ignore [missing-import]
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

def extraer_cedula(texto: str) -> str:
    """
    Intenta extraer un número de cédula de 10 dígitos del texto.
    Limpia espacios, guiones y puntos antes de buscar la secuencia.
    """
    if not texto:
        return ""
    # Remover guiones, espacios y puntos
    limpio = re.sub(r'[\s\-.]', '', texto)
    # Buscar una secuencia de exactamente 10 dígitos en la cadena limpia
    match = re.search(r'\d{10}', limpio)
    if match:
        return match.group(0)
    return ""

def procesar_consulta_pago(numero: str, mensaje: str, contexto: str, db: Session, ya_solicitado: bool = False) -> str:
    """Procesa consultas de saldo y pagos usando datos 100% reales de MySQL de forma natural"""
    # 1. Cancelar flujo si el usuario lo pide
    if mensaje.strip().lower() in ["cancelar", "salir", "cancel", "no", "menu", "menú"]:
        estados_skills[numero] = None
        return "Entendido, con gusto te ayudo con cualquier otra consulta sobre Opsatel 😊"

    # 2. Comprobar si el mensaje actual contiene una cédula de 10 dígitos
    cedula_extraida = extraer_cedula(mensaje)
    cliente = None

    if cedula_extraida:
        cliente = db.query(models.Cliente).filter(models.Cliente.cedula == cedula_extraida).first()
        if not cliente:
            ced_alt = cedula_extraida[1:] if cedula_extraida.startswith("0") else ("0" + cedula_extraida)
            cliente = db.query(models.Cliente).filter(models.Cliente.cedula == ced_alt).first()

        if not cliente:
            estados_skills[numero] = None
            return f"No encontré ningún contrato registrado con la cédula **{cedula_extraida}** en nuestra base de datos. Por favor verifica el número o escríbeme para ayudarte 😊"

    # 3. Si no hay cédula, verificar si el número telefónico de quien escribe pertenece a un cliente registrado
    if not cliente:
        cliente = buscar_cliente_por_celular(numero, db)
        if not cliente:
            adm = es_numero_administrador(numero, db)
            if adm and adm.numero:
                cliente = buscar_cliente_por_celular(adm.numero, db)

    # 4. Si el cliente fue identificado (por cédula o por su número telefónico registrado)
    if cliente:
        estados_skills[numero] = None
        pagos = db.query(models.Pago).filter(models.Pago.cliente_id == cliente.id).order_by(models.Pago.fecha_pago.desc()).limit(3).all()
        historial_pagos_text = ""
        if pagos:
            for p in pagos:
                fecha_str = p.fecha_pago.strftime("%d/%m/%Y") if p.fecha_pago else "N/A"
                historial_pagos_text += f"- {fecha_str}: ${p.monto} ({p.metodo_pago or 'No especificado'})\n"
        else:
            historial_pagos_text = "No registra pagos previos en el sistema.\n"

        prompt_pago = f"""Eres SAM, el asesor virtual oficial de OPSATEL.
Un cliente ha consultado sobre su estado de cuenta / saldo.
Genera una respuesta muy amable, concisa y profesional con estos datos reales de la base de datos:

Datos del cliente:
- Nombre: {cliente.nombre}
- Cédula: {cliente.cedula or 'No registrada'}
- Plan contratado: {cliente.plan or 'No definido'}
- Mensualidad contratada: ${cliente.pago_mensual or 0.00}
- Saldo pendiente (Deuda actual): ${cliente.saldo or 0.00}
- Estado del servicio: {cliente.estado}
- Últimos pagos registrados:
{historial_pagos_text}

Instrucciones:
- Si el saldo es 0 o menor, felicítalo calurosamente por estar al día con sus pagos en Opsatel.
- Si tiene saldo pendiente, indícale el valor exacto de forma respetuosa y clara.
- Mantén un tono natural, empático y humano para WhatsApp (evita sonar a robot)."""

        try:
            return generar_respuesta_ia(prompt_pago, max_tokens=250, temperature=0.3)
        except Exception as e:
            print(f"[SAM Chatbot] Error generando respuesta de pago: {e}")
            return f"Hola {cliente.nombre}, tu saldo pendiente es de ${cliente.saldo or 0.00} y tu servicio se encuentra en estado: {cliente.estado}."

    # 5. Si no se identificó por teléfono ni por cédula, verificar si preguntó por el nombre de otra persona (ej: "saldo de Juan Pérez")
    match_nombre = re.search(r'(?:saldo|deuda|cuenta)\s+de\s+([a-záéíóúñA-ZÁÉÍÓÚÑ\s]{3,35})', mensaje, re.IGNORECASE)
    if match_nombre:
        posible_nombre = match_nombre.group(1).strip()
        palabras_nom = posible_nombre.split()
        if len(palabras_nom) <= 4:
            cliente_nom, _ = buscar_cliente_por_nombre(posible_nombre, db)
            if cliente_nom:
                estados_skills[numero] = None
                pagos = db.query(models.Pago).filter(models.Pago.cliente_id == cliente_nom.id).order_by(models.Pago.fecha_pago.desc()).limit(3).all()
                historial_pagos_text = "\n".join([f"- {p.fecha_pago.strftime('%d/%m/%Y') if p.fecha_pago else 'N/A'}: ${p.monto}" for p in pagos]) if pagos else "No registra pagos previos."
                prompt_pago = f"""Eres SAM de OPSATEL. Informa de manera cortés el estado de cuenta de {cliente_nom.nombre}:
- Plan: {cliente_nom.plan}
- Saldo pendiente: ${cliente_nom.saldo or 0.00}
- Estado: {cliente_nom.estado}
- Últimos pagos: {historial_pagos_text}"""
                return generar_respuesta_ia(prompt_pago, max_tokens=250, temperature=0.3)

    # 6. Si no hay datos suficientes, pedir la cédula amablemente
    estados_skills[numero] = "consultar_pagos_y_saldos"
    return "Con mucho gusto te ayudo a consultar tu saldo en OPSATEL 😊 Por favor indícame tu número de cédula (10 dígitos) para buscar tu contrato en el sistema."

# -------------------------------------------------------------
# SKILL: RECOMENDACIÓN DE PELÍCULAS Y SERIES OPSATV
# -------------------------------------------------------------
PROMPT_PELICULAS = """# Skill: Recomendador Inteligente de Películas y Series — OPSATV

Eres SAM, el Sistema Autónomo Multitarea de OPSATEL, experto en el catálogo de entretenimiento de OPSATV.
Tu misión es recomendar películas o series de forma personalizada, entusiasta y natural, como si fueras un gran cinéfilo.

## PASO 1 — Analiza el mensaje del usuario y detecta:

### 🎬 Género (si menciona alguno):
- acción, comedia, drama, terror/horror, ciencia ficción/sci-fi, suspenso, thriller, aventura, animación, romance, documental, misterio/crimen.
- Si NO menciona género, elige uno al azar que sea popular.

### 📅 Contexto temporal (si menciona alguno):
- "actual", "reciente", "nuevos", "últimos años" → películas de 2021 en adelante.
- "2024", "2025", "2026" → estrenos de ese año específico.
- "mejor valoradas", "clásica", "top" → producciones de alta crítica de cualquier época.
- Si NO menciona tiempo, mezcla recientes con clásicos bien valorados.

### 🔀 Aleatoriedad OBLIGATORIA:
- NUNCA repitas siempre las mismas películas.
- Varía entre diferentes décadas, directores, y países de producción.
- Selecciona de forma pseudoaleatoria dentro del género pedido.

## PASO 2 — Responde con 2 a 3 recomendaciones concretas y REALES.

Formato para cada recomendación:
🎬 *[TÍTULO]* ([AÑO]) — [Género]
📖 [Sinopsis atractiva de 2-3 frases que enganche al usuario]
⭐ [Tu valoración entusiasta en 1 frase, ej: "Una obra maestra que no puedes perderte" / "Perfecta para una noche de suspenso"]

## PASO 3 — Cierra con una frase invitando a ver más opciones en OPSATV.

## REGLAS IMPORTANTES:
- Recomienda SOLO películas y series reales que existen en el mundo real (son reconocidas, tienen buenas críticas).
- Indica siempre título real, año real y género correcto.
- Mantén el tono amigable, divertido y natural, como si hablaras por WhatsApp.
- Respuesta máxima de 5-6 líneas por recomendación. Sé conciso.
- No uses markdown complejo, solo *cursiva* y emojis, que WhatsApp renderiza.
- Nunca inventes películas. Si no conoces una del género pedido, elige otra real cercana.
"""

def procesar_recomendacion_peliculas(numero: str, mensaje: str, contexto: str) -> str:
    try:
        content = f"{PROMPT_PELICULAS}\n\nConversación con el usuario:\n{contexto}\n\nMensaje actual del usuario: {mensaje}\n\nResponde directamente con las recomendaciones, sin preámbulos ni encabezados adicionales."
        return generar_respuesta_ia(content, max_tokens=500, temperature=0.9)
    except Exception as e:
        print(f"[SAM Chatbot] Error recomendando películas: {e}")
        return (
            "🎬 Te recomiendo estas joyas del cine para hoy:\n\n"
            "🎬 *Oppenheimer* (2023) — Drama/Historia\n"
            "📖 La historia del padre de la bomba atómica. Impresionante y profunda.\n"
            "⭐ Una de las mejores del año, ¡imprescindible!\n\n"
            "🎬 *Top Gun: Maverick* (2022) — Acción/Aventura\n"
            "📖 El legendario Maverick vuelve a los cielos en una misión imposible.\n"
            "⭐ Pura adrenalina de principio a fin. ¡La vas a amar! 🔥\n\n"
            "Encuéntralas en tu plataforma OPSATV 📺"
        )

# -------------------------------------------------------------
# SKILL: SOPORTE TÉCNICO E INSPECCIÓN DE FOCO ROJO / SIN SERVICIO
# -------------------------------------------------------------
PROMPT_SOPORTE_TECNICO = """# Skill: Soporte Técnico Inteligente — Diagnóstico de Servicio y Foco Rojo

Eres SAM, el especialista de soporte técnico virtual de OPSATEL.
Tu personalidad es extremadamente amable, empática, paciente, clara y 100% humana.
Comprendes perfectamente lo molesto que es quedarse sin internet y tu objetivo es guiar al usuario paso a paso con calidez y tranquilidad para diagnosticar y solucionar el problema.

## GUÍA DE DIAGNÓSTICO ESTRUCTURADA:

1. **Empatía y Calidez Inicial**:
   - Muestra comprensión sincera por la molestia (ej: "Entiendo perfectamente lo frustrante que es quedarse sin internet, no te preocupes, vamos a revisarlo juntos paso a paso para ayudarte 😊").

2. **Diferenciación de Equipos (1 o 2 equipos)**:
   - Pregunta o identifica si en el domicilio tienen **1 solo equipo** (la caja/ONT donde entra el cable delgado de fibra óptica directamente) o **2 equipos** (la ONT principal conectada por cable de red a un Router Wi-Fi secundario como TP-Link, Mercusys o Tenda).

3. **Diagnóstico de Luces / Foco Rojo (`LOS` vs Router)**:
   - Explica de forma clara y humana qué significa la luz roja:
     * Si la luz roja dice **`LOS`** (o tiene el ícono de una antena/mundo) en la ONT principal de fibra: Significa que hay una interrupción o pérdida de señal en el cable de fibra óptica.
     * Si la luz roja o sin internet ocurre en el Router secundario: Puede ser un falso contacto en el cable ethernet (UTP) entre ambos equipos.

4. **Comprobación Física de Cables**:
   - Pide revisar suavemente que el cable delgado de fibra (generalmente con conector amarillo o verde) esté firme y sin doblarse o estar aplastado en la ONT.
   - Si tienen 2 equipos, pedir verificar que el cable de red (ethernet) que conecta la ONT con el Router secundario esté bien conectado en ambas entradas.

5. **Reinicio Eléctrico de 30 Segundos (Power Cycle)**:
   - Explica cómo desconectar la fuente de poder/tomacorriente de los equipos durante 30 segundos exactos y volver a conectar.
   - Pide esperar entre 2 y 3 minutos a que las luces se estabilicen (las luces `PON` o `Power` deben quedar en verde fijo).

6. **Cierre Empático y Derivación Humana (SIN creación automática de tickets)**:
   - Si el usuario indica que probó los pasos y el foco rojo o la falla persiste, dile de forma muy cálida y atenta que se comunique con nuestro equipo de soporte técnico o que un asesor técnico humano lo asistirá para coordinar la revisión del enlace.

## REGLAS DE ORO:
- Responde de forma muy fluida y natural adaptándote a lo que el usuario te vaya respondiendo en el chat.
- Usa lenguaje sencillo sin tecnicismos complejos.
- Usa emoticonos amigables apropiados para WhatsApp (🌐, 🔌, 💡, 🔴, 🟢, ✨, 😊).
- Evita párrafos gigantescos; da instrucciones claras, amables y por pasos.
"""

def procesar_soporte_tecnico(numero: str, mensaje: str, contexto: str, db: Session) -> str:
    # Detectar si el cliente indica que la falla persiste o requiere visita técnica
    msg_lower = mensaje.lower()
    palabras_persistencia = [
        "sigue", "persiste", "no vale", "no funciona", "no sirvió", "no sirvio",
        "continúa", "continua", "sigue el foco rojo", "sigue la luz roja", "sigue igual",
        "no tengo internet", "no hay internet", "ayuda", "técnico", "tecnico", "visita"
    ]
    falla_persistente = any(p in msg_lower for p in palabras_persistencia) and len(contexto.split("\n")) > 2

    # Intentar obtener datos del cliente si existe en BD
    cliente = buscar_cliente_por_celular(numero, db)
    
    if falla_persistente:
        # 1. Crear Orden de Trabajo en Hoja de Ruta automáticamente
        try:
            import pytz
            from datetime import datetime
            ECUADOR_TZ = pytz.timezone('America/Guayaquil')
            fecha_hoy = datetime.now(ECUADOR_TZ).strftime("%Y-%m-%d")
            hora_actual = datetime.now(ECUADOR_TZ).strftime("%H:%M")

            cliente_id = cliente.id if cliente else None
            nombre_c = cliente.nombre if cliente else f"Cliente WhatsApp ({numero})"
            ubicacion_c = f"{cliente.direccion or ''} (Sector: {cliente.nodo or 'N/A'})".strip() if cliente else "Por definir"
            parroquia_c = cliente.parroquia if cliente else "N/A"
            celular_c = cliente.celular if cliente else numero

            ticket = models.HojaRuta(
                fecha=fecha_hoy,
                tecnico="Por Asignar",
                hora=hora_actual,
                cliente_id=cliente_id,
                nombre_cliente=nombre_c,
                ubicacion_cliente=ubicacion_c,
                celular_cliente=celular_c,
                actividad="SOPORTE TÉCNICO - FOCO ROJO / SIN SERVICIO",
                observacion=f"Reporte de Falla de Red vía WhatsApp. Mensaje cliente: {mensaje}",
                parroquia=parroquia_c,
                estado="Pendiente"
            )
            db.add(ticket)
            db.commit()
            print(f"[SAM Chatbot] 🛠️ Creada orden de trabajo HojaRuta #{ticket.id} para {nombre_c}")

            # 2. Notificar ÚNICAMENTE a Administradores con rol 'admin_total' por WhatsApp
            admins = db.query(models.WhatsAppAdministrador).filter(
                models.WhatsAppAdministrador.activo == True,
                (models.WhatsAppAdministrador.permisos == "admin_total") | (models.WhatsAppAdministrador.permisos == None)
            ).all()
            alerta_msg = (
                f"🚨 *[ALERTA TÉCNICA — FOCO ROJO / SIN SERVICIO]*\n\n"
                f"👤 *Cliente*: {nombre_c}\n"
                f"📱 *Teléfono*: {celular_c}\n"
                f"📍 *Nodo/Parroquia*: {cliente.nodo if cliente else 'N/A'} / {parroquia_c}\n"
                f"🔴 *Falla Reportada*: El cliente indica que la luz roja/falla persiste tras reinicio.\n"
                f"🛠️ *Acción*: Se ha registrado automáticamente la orden en la *Hoja de Ruta*."
            )
            for admin in admins:
                if admin.numero:
                    try:
                        whatsapp_service.send_whatsapp_message(admin.numero, alerta_msg)
                    except Exception as err_send:
                        print(f"[SAM Chatbot] Error notificando admin {admin.numero}: {err_send}")

        except Exception as ticket_err:
            print(f"[SAM Chatbot] Error registrando ticket de soporte: {ticket_err}")
            db.rollback()

    prompt_con_datos = f"""{PROMPT_SOPORTE_TECNICO}

Información del Cliente en Sistema:
- Cliente identificado: {"Sí (" + cliente.nombre + ")" if cliente else "No"}
- Falla persistente detectada: {"Sí (Orden agendada en Hoja de Ruta y notificada a técnicos)" if falla_persistente else "En etapa de diagnóstico"}

Conversación actual:
{contexto}
"""

    try:
        return generar_respuesta_ia(prompt_con_datos, max_tokens=450, temperature=0.4)
    except Exception as e:
        print(f"[SAM Chatbot] Error en soporte técnico: {e}")
        return (
            "🌐 Entiendo perfectamente lo frustrante que es quedarse sin internet. Vamos a solucionarlo juntos paso a paso 😊\n\n"
            "1️⃣ Primero, cuéntame si en tu domicilio tienes **1 solo equipo** (la cajita principal donde entra la fibra) o **2 equipos** (la cajita principal + un router Wi-Fi secundario como TP-Link o Mercusys).\n\n"
            "2️⃣ Revisa si en la cajita principal ves una luz roja encendida que diga **LOS**.\n\n"
            "🔌 **Prueba rápida**: Desconecta los equipos del tomacorriente durante 30 segundos, vuelve a conectarlos y espera 3 minutos a que se estabilicen las luces."
        )

# -------------------------------------------------------------
# CHAT GENERAL (PERSONALIDAD HUMANA E INTELIGENTE DE SAM)
# -------------------------------------------------------------
PROMPT_GENERAL = """Eres SAM (Sistema Autónomo Multitarea de OPSATEL), el asesor virtual oficial y humano de atención al cliente de la empresa de telecomunicaciones e internet por fibra óptica OPSATEL en Ecuador.

DIRECTRICES DE ATENCIÓN (SÉ 100% NATURAL, CÁLIDO, EMPÁTICO Y HUMANO):
1. TONO: Hablas como un asesor de atención al cliente real de primer nivel: sumamente cordial, educado, claro y dispuesto a ayudar. NUNCA suenes como un robot ni uses plantillas acartonadas.
2. TRATO AL USUARIO:
   - NUNCA digas "cliente desconocido", "usuario no identificado", ni menciones errores de base de datos o fallos del sistema.
   - Si el usuario es un CLIENTE REGISTRADO (aparece en DATOS DEL CLIENTE REGISTRADO):
     Salúdalo cordialmente por su nombre (ej: "¡Hola [Nombre]! Qué gusto saludarte de nuevo en OPSATEL 😊"). Conoces su plan actual contratado y su estado.
   - Si el usuario es un PROSPECTO O CLIENTE NUEVO (no registrado):
     Dale una cálida bienvenida a OPSATEL (ej: "¡Hola! Bienvenido a OPSATEL 😊 Con mucho gusto te ayudo."). Si pregunta por servicios o planes, puedes preguntarle con amabilidad su nombre o de qué sector o parroquia nos escribe para verificar la cobertura de fibra óptica.
3. PREGUNTAS SOBRE TI ("¿cómo te llamas?", "¿quién eres?"):
   - Responde con simpatía y cercanía: "¡Hola! Me llamo SAM, soy el asesor virtual oficial de OPSATEL. Estoy aquí para ayudarte con toda la información sobre nuestros planes de internet, pagos, consultas de saldo o soporte técnico. ¿En qué te puedo colaborar hoy? 😊"
4. PREGUNTAS SOBRE PLANES, PRECIOS O SUBIR DE NIVEL / MEJORAR PLAN:
   - Presenta de forma clara, ordenada y atractiva los planes de internet REALES listados abajo (Megas, Precio mensual y Pantallas de televisión TV/IPTV).
   - Si el cliente pregunta cómo subir de nivel o cambiar de plan, explícale que puede elegir cualquiera de los planes superiores y con gusto se le gestiona la actualización.
5. FORMATO PARA WHATSAPP (OBLIGATORIO - NUNCA USES TABLAS):
   - NUNCA utilices tablas de barras (|---|). En WhatsApp se ven rotas y desalineadas.
   - Presenta siempre los planes usando viñetas limpias con negritas, por ejemplo:
     • *GAMER PRO*: 800 Megas por $32.20 al mes (2 pantallas TV/IPTV)
     • *LAG CERO*: 700 Megas por $25.00 al mes (2 pantallas TV/IPTV)
     • *FAMILIAR +*: 650 Megas por $23.00 al mes (1 pantalla TV/IPTV)
6. COMPLETITUD DEL MENSAJE (SIN CORTES):
   - NUNCA dejes oraciones, listas o ideas incompletas a medias.
   - Concluye siempre tu respuesta de forma amigable con una pregunta de cierre (ej: "¿Te gustaría que te ayudemos a cambiarte a alguno de estos planes?").
7. PREGUNTAS SOBRE MEDIOS DE PAGO O BANCOS:
   - Infórmale las entidades bancarias oficiales registradas para depósitos o transferencias.
8. ACTITUD SIEMPRE POSITIVA Y RESOLUTIVA:
   - NUNCA respondas negativamente. Sé siempre servicial, proactivo y cercano.
"""

def procesar_chat_general(numero: str, mensaje: str, contexto: str, db: Session = None) -> str:
    info_bd = []
    nombre_cliente = None
    if db:
        try:
            # 1. Verificar si el usuario que escribe ya es un cliente registrado
            cliente = buscar_cliente_por_celular(numero, db)
            if not cliente:
                adm = es_numero_administrador(numero, db)
                if adm and adm.numero:
                    cliente = buscar_cliente_por_celular(adm.numero, db)

            if cliente and cliente.nombre:
                nombre_cliente = cliente.nombre
                info_bd.append(
                    f"DATOS DEL CLIENTE REGISTRADO QUE TE ESCRIBE:\n"
                    f"- Nombre del cliente: {cliente.nombre}\n"
                    f"- Plan actual contratado: {cliente.plan or 'No definido'}\n"
                    f"- Saldo pendiente: ${cliente.saldo or 0.00}\n"
                    f"- Estado actual del servicio: {cliente.estado}"
                )
            else:
                info_bd.append("ESTADO DEL REMITENTE: Prospecto o nuevo cliente interesado (Aún no registrado en la BD). Trátalo con máxima cordialidad y dale la bienvenida a OPSATEL.")

            # 2. Obtener Planes de Internet reales de la base de datos
            planes = db.query(models.PlanInternet).all()
            if planes:
                lista_planes = []
                for p in planes:
                    linea = f"• *{p.nombre}*: {p.megas} Megas por ${float(p.precio):.2f} al mes"
                    if p.pantallas:
                        linea += f" ({p.pantallas} pantalla(s) de TV/IPTV)"
                    lista_planes.append(linea)
                info_bd.append("PLANES DE INTERNET VIGENTES EN OPSATEL (Datos oficiales de la base de datos):\n" + "\n".join(lista_planes))

            # 3. Obtener Bancos / Medios de pago registrados
            bancos = db.query(models.Banco).all()
            if bancos:
                nombres_bancos = [b.nombre for b in bancos if b.nombre]
                if nombres_bancos:
                    info_bd.append("BANCOS AUTORIZADOS PARA PAGOS Y TRANSFERENCIAS:\n" + ", ".join(nombres_bancos))

        except Exception as e_bd:
            print(f"[SAM Chatbot] Error cargando contexto de BD para chat general: {e_bd}")

    bloque_bd = ("\n\nINFORMACIÓN OFICIAL DE OPSATEL:\n" + "\n\n".join(info_bd)) if info_bd else ""

    prompt_completo = f"""{PROMPT_GENERAL}
{bloque_bd}

Conversación actual con el usuario:
{contexto}
"""
    try:
        return generar_respuesta_ia(prompt_completo, max_tokens=800, temperature=0.5)
    except Exception as e:
        print(f"[SAM Chatbot] Error en chat general: {e}")
        if nombre_cliente:
            return f"¡Hola {nombre_cliente}! Espero que estés teniendo un excelente día 😊 ¿En qué te puedo ayudar hoy con tus servicios de Opsatel?"
        return "¡Hola! Bienvenido a OPSATEL, espero estés teniendo un excelente día 😊 ¿En qué te puedo ayudar hoy?"


# -------------------------------------------------------------
# LÓGICA EXCLUSIVA PARA ADMINISTRADORES Y ALTA DIRECTA
# -------------------------------------------------------------
def es_numero_administrador(numero: str, db: Session, jid_original: str = "", nombre_remitente: str = "", telefono_real: str = ""):
    """
    Verifica si el remitente pertenece a un Administrador activo registrado en el
    apartado de administradores (models.WhatsAppAdministrador).
    
    Regla fundamental:
    Si el usuario también está registrado como Cliente en el sistema, pero su número,
    identificador o perfil coincide con el apartado de administradores, SIEMPRE se le
    otorgan los permisos y acceso prioritario a las skills exclusivas de Administrador
    (caja, morosos, alta directa de instalaciones, etc.).
    """
    if not numero and not jid_original and not telefono_real:
        return None

    try:
        admins = db.query(models.WhatsAppAdministrador).filter(
            models.WhatsAppAdministrador.activo == True
        ).all()
        if not admins:
            return None

        # 1. Recopilar candidatos de números/identificadores del remitente
        candidatos_num = set()
        candidatos_nombre = set()

        for raw_val in [numero, jid_original, telefono_real]:
            if not raw_val:
                continue
            raw_str = str(raw_val).strip()
            candidatos_num.add(raw_str)
            digits = re.sub(r'\D', '', raw_str)
            if digits:
                candidatos_num.add(digits)
                if digits.startswith("593") and len(digits) > 3:
                    candidatos_num.add("0" + digits[3:])
                if digits.startswith("09") and len(digits) == 10:
                    candidatos_num.add("593" + digits[1:])
                if len(digits) >= 8:
                    candidatos_num.add(digits[-8:])
                    candidatos_num.add(digits[-9:])

        if nombre_remitente:
            candidatos_nombre.add(nombre_remitente.strip())

        # 2. Si el remitente es un @lid, consultar puente de WhatsApp
        is_lid = any("@lid" in str(c).lower() for c in candidatos_num)
        if is_lid:
            try:
                from routes.whatsapp import obtener_info_contacto_bridge
                lid_target = next((c for c in candidatos_num if "@lid" in str(c).lower()), None)
                if lid_target:
                    info = obtener_info_contacto_bridge(lid_target)
                    if info:
                        if info.get("number"):
                            candidatos_num.add(str(info["number"]))
                            num_d = re.sub(r'\D', '', str(info["number"]))
                            if num_d:
                                candidatos_num.add(num_d)
                                if len(num_d) >= 8:
                                    candidatos_num.add(num_d[-8:])
                                    candidatos_num.add(num_d[-9:])
                        if info.get("pushname"):
                            candidatos_nombre.add(str(info["pushname"]))
                        elif info.get("name"):
                            candidatos_nombre.add(str(info["name"]))
            except Exception as e_bridge:
                print(f"[SAM Chatbot] Error obteniendo info bridge para LID: {e_bridge}")

        # 3. Comprobar si también es cliente en models.Cliente y agregar sus datos de contacto
        try:
            for cand in list(candidatos_num):
                c = buscar_cliente_por_celular(cand, db)
                if c:
                    if c.celular:
                        c_digs = re.sub(r'\D', '', str(c.celular))
                        if c_digs:
                            candidatos_num.add(c_digs)
                            if len(c_digs) >= 8:
                                candidatos_num.add(c_digs[-8:])
                                candidatos_num.add(c_digs[-9:])
                    if c.nombre:
                        candidatos_nombre.add(str(c.nombre))
                    break
        except Exception:
            pass

        # 4. Comparar contra cada administrador registrado en la base de datos
        for admin in admins:
            if not admin.numero:
                continue
            adm_raw = str(admin.numero).strip()
            adm_digits = re.sub(r'\D', '', adm_raw)
            adm_ultimos_8 = adm_digits[-8:] if len(adm_digits) >= 8 else adm_digits
            adm_ultimos_9 = adm_digits[-9:] if len(adm_digits) >= 9 else adm_digits

            # Comparación por teléfono
            for cand in candidatos_num:
                cand_str = str(cand).strip()
                cand_digits = re.sub(r'\D', '', cand_str)
                cand_ultimos_8 = cand_digits[-8:] if len(cand_digits) >= 8 else cand_digits
                cand_ultimos_9 = cand_digits[-9:] if len(cand_digits) >= 9 else cand_digits

                if cand_digits and adm_digits and cand_digits == adm_digits:
                    print(f"[SAM Chatbot] 👑 Remitente identificado como Administrador: {admin.nombre} (Coincidencia exacta {cand_digits})")
                    return admin
                if len(adm_ultimos_8) >= 8 and len(cand_ultimos_8) >= 8 and adm_ultimos_8 == cand_ultimos_8:
                    print(f"[SAM Chatbot] 👑 Remitente identificado como Administrador: {admin.nombre} (Coincidencia últimos 8 dígitos {adm_ultimos_8})")
                    return admin
                if len(adm_ultimos_9) >= 9 and len(cand_ultimos_9) >= 9 and adm_ultimos_9 == cand_ultimos_9:
                    print(f"[SAM Chatbot] 👑 Remitente identificado como Administrador: {admin.nombre} (Coincidencia últimos 9 dígitos {adm_ultimos_9})")
                    return admin
                if adm_digits and cand_digits and len(adm_digits) >= 8 and len(cand_digits) >= 8:
                    if adm_digits in cand_digits or cand_digits in adm_digits:
                        print(f"[SAM Chatbot] 👑 Remitente identificado como Administrador: {admin.nombre} (Coincidencia substring)")
                        return admin

            # Comparación por nombre (si coincide el nombre de admin con el remitente o el cliente)
            if admin.nombre:
                for cand_nom in candidatos_nombre:
                    score = fuzz.token_set_ratio(normalizar_texto_busqueda(admin.nombre), normalizar_texto_busqueda(cand_nom))
                    if score >= 85:
                        print(f"[SAM Chatbot] 👑 Remitente identificado como Administrador por nombre: {admin.nombre} (Score {score} con '{cand_nom}')")
                        return admin

        return None
    except Exception as e:
        print(f"[SAM Chatbot] Error verificando admin en DB: {e}")
        return None

def procesar_registro_cliente_admin_directo(numero: str, mensaje: str, contexto: str, db: Session, admin_obj) -> str:
    """
    Procesa un mensaje de instalación enviado por un Administrador:
    Extrae los datos en 1 solo paso, crea el Cliente y crea la orden de trabajo en HojaRuta en 1 segundo.
    """
    valid_nodos = [n[0] for n in db.query(models.Nodo.nombre).filter(models.Nodo.nombre != None).all()]
    valid_planes = [pl[0] for pl in db.query(models.PlanInternet.nombre).filter(models.PlanInternet.nombre != None).all()]

    prompt_admin = f"""# Skill: Alta Directa de Instalaciones (Modo Administrador)
Eres SAM, el asistente inteligente de OPSATEL ejecutando comandos del Administrador: {admin_obj.nombre}.
Un administrador ha enviado los datos de una nueva instalación por WhatsApp.
Tu objetivo es EXTRAER de inmediato todos los datos posibles del mensaje y formatearlos en un JSON de una sola línea, SIN hacer preguntas, SIN pedir confirmación y SIN rodeos.

Campos a extraer:
* nombre: Nombre completo del cliente.
* cedula: Cédula o RUC (10 o 13 dígitos).
* celular: Teléfono de contacto.
* direccion: Dirección domiciliaria.
* plan: Plan de internet (intenta mapear a uno de los PLANES VÁLIDOS).
* nodo: Sector o Nodo de red (intenta mapear a uno de los NODOS VÁLIDOS).
* parroquia: Parroquia.
* latitud: Latitud GPS (opcional, float 0.0 si no hay).
* longitud: Longitud GPS (opcional, float 0.0 si no hay).
* comentarios: Notas adicionales (promociones, si es arrendatario, correo, etc.).

PLANES VÁLIDOS: {json.dumps(valid_planes, ensure_ascii=False)}
NODOS VÁLIDOS: {json.dumps(valid_nodos, ensure_ascii=False)}

Responde ÚNICAMENTE con el JSON final en este formato exacto:
{{"nombre": "", "cedula": "", "celular": "", "direccion": "", "plan": "", "nodo": "", "parroquia": "", "latitud": 0.0, "longitud": 0.0, "comentarios": ""}}
"""

    try:
        content = f"{prompt_admin}\n\nMensaje enviado por el Administrador:\n{mensaje}"
        res_text = generar_respuesta_ia(content, max_tokens=600, temperature=0.1)
        
        json_match = re.search(r'\{.*"nombre".*\}', res_text)
        if json_match:
            data = json.loads(json_match.group(0))
            
            ubicacion_gps = f"{data.get('latitud') or 0.0}, {data.get('longitud') or 0.0}"
            
            cedula = str(data.get("cedula") or "").strip()
            if cedula.isdigit() and len(cedula) == 9:
                cedula = "0" + cedula
                
            celular = str(data.get("celular") or "").strip()
            if celular.isdigit() and len(celular) == 9 and celular.startswith("9"):
                celular = "0" + celular

            # Reutilizar primer ID disponible
            ids_query = db.query(models.Cliente.id).order_by(models.Cliente.id).all()
            ids = [i[0] for i in ids_query]
            nuevo_id = 1
            for current_id in ids:
                if current_id == nuevo_id:
                    nuevo_id += 1
                elif current_id > nuevo_id:
                    break

            # 1. Crear Cliente
            nuevo_cliente = models.Cliente(
                id=nuevo_id,
                nombre=data.get("nombre") or "Cliente Desconocido",
                cedula=cedula,
                celular=celular,
                direccion=data.get("direccion"),
                plan=data.get("plan"),
                nodo=data.get("nodo"),
                parroquia=data.get("parroquia"),
                ubicacion=ubicacion_gps,
                comentarios=data.get("comentarios"),
                estado="Pendiente",
                saldo=0.00
            )
            db.add(nuevo_cliente)
            db.flush()

            # 2. Crear Orden de Trabajo en Hoja de Ruta
            import pytz
            from datetime import datetime
            ECUADOR_TZ = pytz.timezone('America/Guayaquil')
            fecha_hoy = datetime.now(ECUADOR_TZ).strftime("%Y-%m-%d")

            obs_hoja = f"Plan: {data.get('plan') or 'No especificado'}"
            if data.get("comentarios"):
                obs_hoja += f" | {data.get('comentarios')}"

            nueva_hoja = models.HojaRuta(
                fecha=fecha_hoy,
                tecnico="Por Asignar",
                hora="09:00",
                cliente_id=nuevo_cliente.id,
                nombre_cliente=nuevo_cliente.nombre,
                ubicacion_cliente=f"{nuevo_cliente.direccion or ''} (Sector: {nuevo_cliente.nodo or 'N/A'})".strip(),
                celular_cliente=nuevo_cliente.celular,
                actividad="INSTALACIÓN DE SERVICIO DE INTERNET",
                observacion=obs_hoja,
                parroquia=nuevo_cliente.parroquia,
                estado="Pendiente"
            )
            db.add(nueva_hoja)
            db.commit()
            
            # Limpiar skill activo
            estados_skills[numero] = None
            if numero in historial_conversaciones:
                historial_conversaciones[numero] = []

            return (
                f"👑 *[Modo Administrador — {admin_obj.nombre}]*\n\n"
                f"✅ ¡Instalación registrada y agendada en la *Hoja de Ruta* exitosamente!\n\n"
                f"👤 *Cliente #{nuevo_cliente.id}*: {nuevo_cliente.nombre}\n"
                f"🆔 *Cédula*: {nuevo_cliente.cedula or 'N/A'}\n"
                f"📱 *Celular*: {nuevo_cliente.celular or 'N/A'}\n"
                f"📍 *Nodo*: {nuevo_cliente.nodo or 'N/A'}\n"
                f"📦 *Plan*: {nuevo_cliente.plan or 'N/A'}\n"
                f"🛠️ *Orden Hoja de Ruta*: Creada (Estado: Pendiente)\n\n"
                f"_La orden ya está disponible en el panel web para asignación técnica._"
            )
        else:
            return procesar_registro_cliente(numero, mensaje, contexto, db)
    except Exception as e:
        print(f"[SAM Chatbot Admin] Error procesando alta directa: {e}")
        db.rollback()
        return f"⚠️ Hola {admin_obj.nombre}, ocurrió un inconveniente registrando el cliente en la Hoja de Ruta: {str(e)}"

def procesar_comando_administrador(numero: str, mensaje: str, contexto: str, db: Session, admin_obj) -> str:
    """Procesa comandos administrativos (Caja del día, Morosos, Instalaciones a Hoja de Ruta, etc.)"""
    msg_lower = mensaje.lower()
    
    if any(w in msg_lower for w in [
        "caja", "cobro", "cobros", "recaudacion", "recaudación", "cuanto se cobro", "cuánto se cobró",
        "cuanto cobramos", "ingresos", "cierre"
    ]):
        import pytz
        from datetime import datetime
        ECUADOR_TZ = pytz.timezone('America/Guayaquil')
        hoy_str = datetime.now(ECUADOR_TZ).strftime("%Y-%m-%d")
        
        pagos_hoy = db.query(models.Pago).filter(
            models.Pago.fecha_pago >= f"{hoy_str} 00:00:00"
        ).all()
        
        total_monto = sum(float(p.monto or 0) for p in pagos_hoy)
        total_pagos = len(pagos_hoy)

        metodos = {}
        for p in pagos_hoy:
            met = (p.metodo_pago or "Otros").title()
            metodos[met] = metodos.get(met, 0.0) + float(p.monto or 0)
        
        desglose_txt = ""
        if metodos:
            desglose_txt = "\n*Desglose por método:*\n" + "\n".join([f"• {m}: ${val:.2f}" for m, val in metodos.items()])
        
        return (
            f"👑 *[Resumen de Caja del Día — {admin_obj.nombre}]*\n\n"
            f"📅 *Fecha*: {hoy_str}\n"
            f"💰 *Total Recaudado*: ${total_monto:.2f}\n"
            f"📊 *Número de Pagos*: {total_pagos}"
            f"{desglose_txt}\n\n"
            f"_Reporte generado en tiempo real desde el Centro de Operaciones Opsatel._"
        )
        
    elif any(w in msg_lower for w in [
        "moroso", "morosos", "corte", "cortes", "suspendido", "suspendidos", "deudores", "deuda general"
    ]):
        morosos = db.query(models.Cliente).filter(models.Cliente.estado == "Moroso").count()
        suspendidos = db.query(models.Cliente).filter(models.Cliente.estado == "Suspendido").count()
        return (
            f"👑 *[Reporte de Morosidad y Cortes — {admin_obj.nombre}]*\n\n"
            f"⚠️ *Clientes en estado Moroso*: {morosos}\n"
            f"🚫 *Clientes en estado Suspendido*: {suspendidos}\n\n"
            f"_Para revisar la lista detallada, ingresa al panel web de Opsatel._"
        )

    elif any(w in msg_lower for w in ["instalacion", "instalación", "nuevo cliente", "ingresar cliente", "registrar", "alta"]):
        return procesar_registro_cliente_admin_directo(numero, mensaje, contexto, db, admin_obj)
        
    return (
        f"👑 *¡Hola {admin_obj.nombre}!* Reconozco tu perfil de Administrador en Opsatel.\n\n"
        f"Como tu número está registrado en el *apartado de Administradores*, tienes acceso prioritario a tus funciones exclusivas de gestión:\n"
        f"• 💰 *'Resumen de caja'* (recaudación y pagos del día)\n"
        f"• ⚠️ *'Reporte de morosos'* (clientes suspendidos o en corte)\n"
        f"• 🛠️ *Datos de instalación* (ej: *INSTALACION BAÑOS ...* para registrarla y pasarla directo a la Hoja de Ruta)\n\n"
        f"💡 _Nota: Como también eres cliente de Opsatel, si deseas consultar tu propio saldo personal solo pregúntame '¿cuánto debo?' o solicita soporte técnico cuando lo requieras._ 😊\n\n"
        f"¿En qué te colaboro hoy?"
    )

# -------------------------------------------------------------
# FUNCIÓN PRINCIPAL DE ENTRADA AL SERVICIO
# -------------------------------------------------------------
def procesar_mensaje_entrante(numero: str, mensaje: str, db: Session, nombre_remitente: str = "", jid_original: str = "", telefono_real: str = "") -> str:
    """
    Punto de entrada principal para el chatbot SAM.
    Recibe el número telefónico o JID del remitente y el contenido del mensaje.
    Procesa según la intención detectada y devuelve la respuesta generada sin atascarse.
    """
    # Limpiar formato del número preservando @lid si corresponde
    numero = limpiar_numero_whatsapp(numero)

    # 0. Limpiar sesión si expiró el tiempo de inactividad (TTL)
    limpiar_sesion_si_expirada(numero)

    # 0.1 Registrar mensaje del cliente en historial de chat persistente (máximo 100 mensajes)
    try:
        from routes.whatsapp import registrar_mensaje_chat
        tipo_msg = "multimedia" if mensaje.startswith("[NON_TEXT_MSG]") else "texto"
        registrar_mensaje_chat(db, numero, "cliente", mensaje, tipo=tipo_msg, nombre_remitente=nombre_remitente)
    except Exception as e_chat:
        print(f"[SAM Chatbot] Error registrando mensaje cliente en chat: {e_chat}")

    # 0.2 Comprobar si el bot está en pausa por intervención de un operador humano (5 minutos)
    if esta_bot_pausado_por_operador(numero) or (jid_original and esta_bot_pausado_por_operador(jid_original)):
        print(f"[SAM Chatbot] 🤫 Intervención de operador activa para {numero}. Bot en silencio por 5 minutos. Mensaje cliente guardado en chat.")
        return ""

    # 1. Manejo de mensajes no soportados (audio, imágenes, stickers)
    if mensaje.startswith("[NON_TEXT_MSG]"):
        tipo_recibido = mensaje.replace("[NON_TEXT_MSG]", "").strip() or "multimedia"
        response_text = f"Hola, soy SAM de Opsatel 😊 Por el momento solo puedo leer mensajes de texto. Por favor, escríbeme tu consulta en texto y con gusto te ayudo."
        guardar_mensaje_historial(numero, "assistant", response_text)
        try:
            from routes.whatsapp import registrar_mensaje_chat
            registrar_mensaje_chat(db, numero, "asistente", response_text)
        except Exception as e_chat:
            print(f"[SAM Chatbot] Error registrando respuesta SAM: {e_chat}")
        whatsapp_service.send_whatsapp_message(numero, response_text)
        return response_text

    # 2. Comando explícito de cancelación / reinicio de conversación
    msg_limpio = mensaje.strip().lower()
    if msg_limpio in ["cancelar", "salir", "menu", "menú", "inicio", "empezar de nuevo", "reset", "reiniciar"]:
        estados_skills[numero] = None
        historial_conversaciones[numero] = []
        response_text = "¡Listo! He reiniciado la conversación. ¿En qué te puedo colaborar hoy con tus servicios de Opsatel? 😊"
        guardar_mensaje_historial(numero, "assistant", response_text)
        try:
            from routes.whatsapp import registrar_mensaje_chat
            registrar_mensaje_chat(db, numero, "asistente", response_text)
        except Exception as e_chat:
            print(f"[SAM Chatbot] Error registrando respuesta SAM: {e_chat}")
        whatsapp_service.send_whatsapp_message(numero, response_text)
        return response_text

    # 3. Guardar mensaje del usuario en el historial
    guardar_mensaje_historial(numero, "user", mensaje)
    
    # 4. Obtener el contexto actual de la conversación
    contexto = obtener_contexto_conversacion(numero, mensaje)
    
    # 5. Verificar si el remitente es un Administrador registrado (en el apartado de Administradores)
    admin_obj = es_numero_administrador(numero, db, jid_original=jid_original, nombre_remitente=nombre_remitente, telefono_real=telefono_real)

    # 6. Determinar skill activo y evaluar cambio de intención (DESENGANCHE DINÁMICO)
    skill_previo = estados_skills.get(numero)
    intencion_detectada = clasificar_intencion(contexto, mensaje)
    
    skill_activo = intencion_detectada
    ya_solicitado = False

    if skill_previo:
        # Si el usuario hace cualquier pregunta general o cambia de tema:
        if intencion_detectada == "general":
            skill_activo = "general"
            estados_skills[numero] = None
        elif intencion_detectada != skill_previo:
            print(f"[SAM Chatbot] 🔄 Desenganche de tema: Cambiando de '{skill_previo}' a '{intencion_detectada}'")
            skill_activo = intencion_detectada
            estados_skills[numero] = None
        # Si estaba consultando pagos: solo continuar en el skill si ingresó cédula de 10 dígitos
        elif skill_previo == "consultar_pagos_y_saldos":
            if extraer_cedula(mensaje):
                skill_activo = "consultar_pagos_y_saldos"
                ya_solicitado = True
            else:
                skill_activo = "general"
                estados_skills[numero] = None
        # Si estaba en registro interactivo de cliente potencial:
        elif skill_previo == "registrar_cliente_potencial":
            if any(w in msg_limpio for w in ["cancelar", "salir", "no", "planes", "precio", "como te llamas"]):
                skill_activo = "general"
                estados_skills[numero] = None
            else:
                skill_activo = "registrar_cliente_potencial"
        else:
            skill_activo = intencion_detectada
            estados_skills[numero] = None
    else:
        skill_activo = intencion_detectada

    print(f"[SAM Chatbot] Procesando mensaje de {numero} (Admin: {admin_obj.nombre if admin_obj else 'No'}) - Skill seleccionado: {skill_activo}")
    
    # 7. Ejecutar la lógica según el skill y rol del usuario
    response_text = ""

    # Detección de comandos y permisos exclusivos para Administradores
    es_comando_admin = admin_obj and (
        skill_activo == "registrar_cliente_potencial"
        or any(w in mensaje.lower() for w in [
            "instalacion", "instalación", "caja", "cobro", "cobros", "recaudacion", "recaudación",
            "cuanto se cobro", "cuánto se cobró", "cuanto cobramos", "ingresos", "cierre",
            "moroso", "morosos", "corte", "cortes", "suspendido", "suspendidos",
            "deudores", "alta"
        ])
    )

    if es_comando_admin:
        response_text = procesar_comando_administrador(numero, mensaje, contexto, db, admin_obj)
    elif skill_activo == "registrar_cliente_potencial":
        estados_skills[numero] = "registrar_cliente_potencial"
        response_text = procesar_registro_cliente(numero, mensaje, contexto, db)
    elif skill_activo == "consultar_pagos_y_saldos":
        response_text = procesar_consulta_pago(numero, mensaje, contexto, db, ya_solicitado)
    elif skill_activo == "recomendacion_peliculas_opsatv":
        estados_skills[numero] = None
        response_text = procesar_recomendacion_peliculas(numero, mensaje, contexto)
    elif skill_activo == "soporte_tecnico_foco_rojo":
        # Soporte técnico no deja el skill enganchado para la siguiente consulta
        estados_skills[numero] = None
        response_text = procesar_soporte_tecnico(numero, mensaje, contexto, db)
    elif admin_obj and msg_limpio in ["menu", "menú", "admin", "comandos", "panel"]:
        # Menú explícito de gestión administrativa
        estados_skills[numero] = None
        response_text = procesar_comando_administrador(numero, mensaje, contexto, db, admin_obj)
    else:
        estados_skills[numero] = None
        response_text = procesar_chat_general(numero, mensaje, contexto, db)

    # 8. Guardar la respuesta generada en el historial
    guardar_mensaje_historial(numero, "assistant", response_text)
    try:
        from routes.whatsapp import registrar_mensaje_chat
        registrar_mensaje_chat(db, numero, "asistente", response_text)
    except Exception as e_chat:
        print(f"[SAM Chatbot] Error registrando respuesta SAM: {e_chat}")
    
    # 9. Despachar el mensaje por WhatsApp usando el servicio unificado
    whatsapp_service.send_whatsapp_message(numero, response_text)
    
    return response_text

