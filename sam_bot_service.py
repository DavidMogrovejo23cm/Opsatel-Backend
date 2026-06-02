import os
import re
import json
import anthropic
from sqlalchemy.orm import Session
import models
from rapidfuzz import fuzz, process
import whatsapp_service

# Inicializar cliente de Anthropic si la clave está configurada
client_ai = None
def get_anthropic_client():
    global client_ai
    if client_ai is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if api_key:
            client_ai = anthropic.Anthropic(api_key=api_key)
        else:
            # Fallback a la clave de pruebas si no está en el .env
            client_ai = anthropic.Anthropic(api_key="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")
    return client_ai

# Estructura para almacenar el historial de conversaciones por número en memoria
# Formato: {numero: [{"role": "user"|"assistant", "content": str}]}
historial_conversaciones = {}
# Estado del skill activo por número: {numero: "skill_name"}
estados_skills = {}

# Límite máximo de mensajes en el historial para evitar fugas de memoria
MAX_HISTORY_LEN = 12

def limpiar_numero_whatsapp(numero: str) -> str:
    """Limpia el formato del número eliminando @c.us y no-dígitos"""
    if "@" in numero:
        numero = numero.split("@")[0]
    return re.sub(r'\D', '', str(numero))

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

def clasificar_intencion(contexto: str) -> str:
    """Clasifica el mensaje actual del usuario en una de las intenciones disponibles"""
    client = get_anthropic_client()
    
    prompt = f"""Eres un enrutador inteligente de intenciones del chatbot SAM.
Debes clasificar la intención del usuario basándote en la conversación actual.

Intenciones disponibles:
- registrar_cliente_potencial: Si el usuario desea registrar, ingresar o guardar un prospecto, nuevo cliente, o prospecto de ventas.
- consultar_pagos_y_saldos: Si el usuario pregunta por su deuda, saldo pendiente, facturas, último pago, comprobante de pago o estado de cuenta.
- recomendacion_peliculas_opsatv: Si el usuario pide recomendaciones de películas, qué ver, series o catálogos en OPSATV.
- general: Si es un saludo, despedida, pregunta genérica, agradecimiento o no encaja en las anteriores.

Conversación actual:
"{contexto}"

Tu tarea: Responde únicamente con el nombre de la intención ("registrar_cliente_potencial", "consultar_pagos_y_saldos", "recomendacion_peliculas_opsatv" o "general"). No agregues explicaciones, puntuación ni texto adicional."""

    try:
        response = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=30,
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}]
        )
        intencion = response.content[0].text.strip().lower()
        
        valid_intents = ["registrar_cliente_potencial", "consultar_pagos_y_saldos", "recomendacion_peliculas_opsatv", "general"]
        for intent in valid_intents:
            if intent in intencion:
                return intent
        return "general"
    except Exception as e:
        print(f"[SAM Chatbot] Error clasificando intención: {e}")
        return "general"

# -------------------------------------------------------------
# SKILL: REGISTRAR CLIENTE POTENCIAL
# -------------------------------------------------------------
PROMPT_REGISTRO_CLIENTE = """# Skill: Registrar Cliente Potencial
Eres SAM, la IA encargada de recopilar los datos para registrar un cliente potencial de forma organizada.
Debes mantener un tono amigable, claro, profesional y dar respuestas cortas.
Siempre menciona que eres SAM, el Sistema Autónomo Multitarea de OPSATEL y que vas a recopilar datos para registrar un cliente potencial si es el inicio.

Los datos obligatorios que debes conseguir son:
* nombre
* telefono
* empresa
* plan_actual (decimal en dólares que paga actualmente)
* antiguedad_anios (entero en años)
* latitud
* longitud
* notas (comentarios adicionales)

Reglas:
- No inventes datos.
- Si falta algún dato, pídelo amigablemente de uno en uno o en grupo de forma muy clara.
- Muestra los datos recopilados estructurados así para que el usuario vea el avance:
Nombre: <valor o (pendiente)>
Teléfono: <valor o (pendiente)>
Empresa: <valor o (pendiente)>
Plan actual: <valor o (pendiente)>
Antigüedad: <valor o (pendiente)>
Latitud: <valor o (pendiente)>
Longitud: <valor o (pendiente)>
Notas: <valor o (pendiente)>

- Cuando TODOS los datos estén completos, pídele confirmación explícita al usuario mostrando la ficha completa.
- Únicamente cuando el usuario confirme (diciendo "sí", "correcto", "confirmado", "ok"), genera un JSON final de una sola línea, sin explicaciones ni texto antes o después.

Formato exacto del JSON final:
{"nombre": "", "telefono": "", "empresa": "", "plan_actual": 0.0, "antiguedad_anios": 0, "latitud": 0.0, "longitud": 0.0, "notas": ""}
"""

def procesar_registro_cliente(numero: str, mensaje: str, contexto: str, db: Session) -> str:
    client = get_anthropic_client()
    
    messages = [
        {"role": "user", "content": f"{PROMPT_REGISTRO_CLIENTE}\n\nConversación hasta ahora:\n{contexto}"}
    ]
    
    try:
        response = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=600,
            temperature=0.2,
            messages=messages
        )
        res_text = response.content[0].text.strip()
        
        # Verificar si la IA generó el JSON final
        # Buscamos patrones {...} que parezcan JSON
        json_match = re.search(r'\{.*"nombre".*\}', res_text)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                
                # Crear cliente en la tabla real hoja_de_c__lculo_sin_t__tulo (Cliente)
                # Mapeamos los campos a la base de datos de Opsatel
                ubicacion_gps = f"{data.get('latitud', 0.0)}, {data.get('longitud', 0.0)}"
                comentarios_detallados = f"Empresa: {data.get('empresa')}. Antigüedad: {data.get('antiguedad_anios')} años. Notas: {data.get('notas')}"
                
                nuevo_cliente = models.Cliente(
                    nombre=data.get("nombre"),
                    celular=data.get("telefono"),
                    plan=f"Plan actual: ${data.get('plan_actual')}",
                    pago_mensual=data.get("plan_actual", 0.0),
                    saldo=0.00,
                    estado="Pendiente", # Se registra como prospecto/pendiente
                    ubicacion=ubicacion_gps,
                    comentarios=comentarios_detallados
                )
                
                db.add(nuevo_cliente)
                db.commit()
                db.refresh(nuevo_cliente)
                
                # Limpiar estado de skill
                estados_skills[numero] = None
                if numero in historial_conversaciones:
                    historial_conversaciones[numero] = []
                    
                return f"✅ ¡Perfecto! He registrado los datos de *{data.get('nombre')}* como cliente potencial en el sistema de OPSATEL exitosamente."
            except Exception as db_err:
                print(f"[SAM Chatbot] Error guardando cliente potencial: {db_err}")
                db.rollback()
                return "Hubo un inconveniente al guardar los datos del cliente potencial en la base de datos. Por favor, reintente en unos momentos."
        else:
            return res_text
    except Exception as e:
        print(f"[SAM Chatbot] Error en skill registrar cliente: {e}")
        return "Disculpa, tuve un problema al procesar el registro de cliente potencial. ¿Podrías indicarme los datos nuevamente?"

# -------------------------------------------------------------
# SKILL: CONSULTAR PAGOS Y SALDOS
# -------------------------------------------------------------
def buscar_cliente_por_celular(numero_limpio: str, db: Session):
    """Busca un cliente cuyo celular contenga el número limpio del remitente"""
    # Intentar buscar reemplazando 593 por 0 y también con el número completo
    num_ecuador = "0" + numero_limpio[3:] if numero_limpio.startswith("593") and len(numero_limpio) > 3 else numero_limpio
    
    cliente = db.query(models.Cliente).filter(
        (models.Cliente.celular.like(f"%{numero_limpio}%")) |
        (models.Cliente.celular.like(f"%{num_ecuador}%"))
    ).first()
    return cliente

def buscar_cliente_por_nombre(nombre_buscar: str, db: Session):
    """Realiza una búsqueda difusa en la base de datos de clientes por nombre"""
    clientes = db.query(models.Cliente.id, models.Cliente.nombre).all()
    if not clientes:
        return None, []
        
    nombres_dict = {c.id: c.nombre for c in clientes if c.nombre}
    nombres_lista = list(nombres_dict.values())
    
    # Extraer coincidencias usando rapidfuzz
    matches = process.extract(nombre_buscar, nombres_lista, scorer=fuzz.token_set_ratio, limit=5)
    
    coincidencias_validas = []
    for match in matches:
        nombre_coincidente, score, index = match
        if score >= 50:
            # Buscar el ID del cliente
            cliente_id = [cid for cid, cnom in nombres_dict.items() if cnom == nombre_coincidente][0]
            coincidencias_validas.append({"id": cliente_id, "nombre": nombre_coincidente, "score": score})
            
    # Si hay una coincidencia muy fuerte (>85), la tomamos directamente
    coincidencias_validas.sort(key=lambda x: x["score"], reverse=True)
    if coincidencias_validas and coincidencias_validas[0]["score"] >= 85:
        cliente_real = db.query(models.Cliente).filter(models.Cliente.id == coincidencias_validas[0]["id"]).first()
        return cliente_real, []
        
    return None, coincidencias_validas[:3]

def procesar_consulta_pago(numero: str, mensaje: str, contexto: str, db: Session) -> str:
    client = get_anthropic_client()
    
    # Preguntar a Claude si el mensaje menciona un nombre de persona a buscar
    prompt_extract = f"""Del siguiente mensaje de WhatsApp del usuario, determina si está pidiendo consultar el saldo/pago de otra persona mencionando su nombre de forma explícita.
Si menciona un nombre, responde únicamente con el nombre extraído.
Si el usuario pregunta por su propio saldo (ej. "cuanto debo", "mi saldo", "mi pago") o no menciona ningún nombre específico, responde únicamente con la palabra "auto".

Mensaje: "{mensaje}"
Respuesta:"""
    
    nombre_buscado = "auto"
    try:
        response_ext = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=30,
            temperature=0.0,
            messages=[{"role": "user", "content": prompt_extract}]
        )
        nombre_buscado = response_ext.content[0].text.strip().lower()
    except Exception as e:
        print(f"[SAM Chatbot] Error al extraer nombre: {e}")
        
    cliente = None
    sugerencias = []
    
    if "auto" in nombre_buscado:
        # Buscar por el número de celular del remitente
        numero_limpio = limpiar_numero_whatsapp(numero)
        cliente = buscar_cliente_por_celular(numero_limpio, db)
        if not cliente:
            # Si no se encuentra por celular, pedir el nombre
            return "No encontré tu número celular registrado en nuestra base de datos. Por favor, indícame tu nombre completo para buscarte en el sistema."
    else:
        # Buscar por el nombre extraído
        cliente, sugerencias = buscar_cliente_por_nombre(nombre_buscado, db)
        
    if not cliente:
        if sugerencias:
            sug_text = "\n".join([f"- {s['nombre']}" for s in sugerencias])
            return f"No encontré un cliente exacto para '{nombre_buscado}'. ¿Te refieres a alguno de estos?\n{sug_text}\n\nPor favor indícame el nombre tal como aparece arriba."
        else:
            return f"Lo lamento, no encontré ningún cliente con el nombre '{nombre_buscado}' en nuestra base de datos."
            
    # Si encontramos al cliente, obtenemos sus últimos pagos y saldo
    pagos = db.query(models.Pago).filter(models.Pago.cliente_id == cliente.id).order_by(models.Pago.fecha_pago.desc()).limit(3).all()
    
    # Formatear el historial de pagos
    historial_pagos_text = ""
    if pagos:
        for p in pagos:
            fecha_str = p.fecha_pago.strftime("%d/%m/%Y") if p.fecha_pago else "N/A"
            historial_pagos_text += f"- {fecha_str}: ${p.monto} ({p.metodo_pago or 'No especificado'})\n"
    else:
        historial_pagos_text = "No registra pagos previos en el sistema.\n"
        
    # Prompt para que Claude genere la respuesta de SAM con datos reales
    prompt_pago = f"""Eres SAM, el Sistema Autónomo Multitarea de OPSATEL.
Un cliente ha solicitado información sobre su saldo y estado de cuenta.
Genera una respuesta amigable, educada y concisa informando sobre estos datos.

Datos reales del cliente:
- Nombre: {cliente.nombre}
- Celular registrado: {cliente.celular}
- Plan contratado: {cliente.plan or 'No definido'}
- Mensualidad contratada: ${cliente.pago_mensual or 0.00}
- Saldo pendiente (Deuda): ${cliente.saldo or 0.00}
- Estado del servicio: {cliente.estado}
- Últimos 3 pagos registrados:
{historial_pagos_text}

Reglas:
- Si el saldo (deuda) es 0 o menor, felicítalo por estar al día.
- Si tiene saldo pendiente, infórmale el monto exacto de forma clara y respetuosa.
- Mantén la respuesta breve y al grano, ideal para WhatsApp.
- No inventes ningún dato que no esté listado arriba.
"""
    try:
        response_sam = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=250,
            temperature=0.3,
            messages=[{"role": "user", "content": prompt_pago}]
        )
        return response_sam.content[0].text.strip()
    except Exception as e:
        print(f"[SAM Chatbot] Error generando respuesta de pago: {e}")
        return f"Hola {cliente.nombre}, tu saldo pendiente es de ${cliente.saldo or 0.00} y tu servicio se encuentra en estado: {cliente.estado}."

# -------------------------------------------------------------
# SKILL: RECOMENDACIÓN DE PELÍCULAS OPSATV
# -------------------------------------------------------------
PROMPT_PELICULAS = """# Skill: Recomendación de Películas OPSATV
Eres SAM, especialista en recomendar películas exclusivas de la plataforma OPSATV.
Reglas:
- Simula siempre que estás buscando en el catálogo interno de OPSATV.
- Si te piden recomendaciones, sugiere una película que se encuentre disponible e incluye:
  1. Título de la película.
  2. Año de estreno (aproximado).
  3. Breve sinopsis o descripción (2-3 frases).
  4. Valoración personal ("Es una excelente producción", etc.).
- Nunca sugieras películas que no estén disponibles en la plataforma o que no tengan relación con el cine popular.
- Mantén el tono amigable y divertido.
"""

def procesar_recomendacion_peliculas(numero: str, mensaje: str, contexto: str) -> str:
    client = get_anthropic_client()
    try:
        response = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=400,
            temperature=0.7,
            messages=[{"role": "user", "content": f"{PROMPT_PELICULAS}\n\nMensaje del usuario:\n{contexto}"}]
        )
        return response.content[0].text.strip()
    except Exception as e:
        print(f"[SAM Chatbot] Error recomendando películas: {e}")
        return "Te recomiendo revisar la categoría de Acción de OPSATV, ¡está llena de grandes estrenos!"

# -------------------------------------------------------------
# CHAT GENERAL (PERSONALIDAD BÁSICA DE SAM)
# -------------------------------------------------------------
PROMPT_GENERAL = """Eres SAM (Sistema Autónomo Multitarea de OPSATEL), un asistente virtual inteligente para la empresa proveedora de Internet y Telecomunicaciones OPSATEL.
Tu personalidad es amable, atenta, rápida y muy profesional.
Tus respuestas deben ser cortas, directas y optimizadas para leerse en WhatsApp.

Tus funciones principales en este chatbot son:
1. Ayudar a los usuarios a consultar sus pagos y saldos.
2. Ayudar a registrar nuevos clientes potenciales (prospectos).
3. Recomendar películas en OPSATV.

Si el usuario te hace preguntas generales o te saluda, conversa amigablemente, infórmale sobre tus funciones de manera breve y ofréceles tu ayuda."""

def procesar_chat_general(numero: str, mensaje: str, contexto: str) -> str:
    client = get_anthropic_client()
    try:
        response = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=350,
            temperature=0.5,
            messages=[{"role": "user", "content": f"{PROMPT_GENERAL}\n\nConversación:\n{contexto}"}]
        )
        return response.content[0].text.strip()
    except Exception as e:
        print(f"[SAM Chatbot] Error en chat general: {e}")
        return "Hola, soy SAM de OPSATEL. ¿En qué te puedo ayudar hoy? (Puedo asistirte con tu saldo de cuenta o registrarte como cliente potencial)."

# -------------------------------------------------------------
# FUNCIÓN PRINCIPAL DE ENTRADA AL SERVICIO
# -------------------------------------------------------------
def procesar_mensaje_entrante(numero: str, mensaje: str, db: Session) -> str:
    """
    Punto de entrada principal para el chatbot SAM.
    Recibe el número telefónico del remitente y el contenido del mensaje.
    Procesa según la intención detectada y devuelve la respuesta generada.
    """
    # 1. Guardar mensaje del usuario en el historial
    guardar_mensaje_historial(numero, "user", mensaje)
    
    # 2. Obtener el contexto actual de la conversación
    contexto = obtener_contexto_conversacion(numero, mensaje)
    
    # 3. Determinar el skill activo o clasificar la intención actual
    skill_activo = estados_skills.get(numero)
    
    if not skill_activo:
        # Si no hay un skill en curso, clasificar la intención del mensaje
        skill_activo = clasificar_intencion(contexto)
        
    print(f"[SAM Chatbot] Procesando mensaje de {numero} - Skill: {skill_activo}")
    
    # 4. Ejecutar la lógica según el skill
    response_text = ""
    if skill_activo == "registrar_cliente_potencial":
        # Marcar que este número está en el flujo de registro
        estados_skills[numero] = "registrar_cliente_potencial"
        response_text = procesar_registro_cliente(numero, mensaje, contexto, db)
    elif skill_activo == "consultar_pagos_y_saldos":
        # Las consultas de pago son de una sola interacción, no guardan estado persistente de skill
        estados_skills[numero] = None
        response_text = procesar_consulta_pago(numero, mensaje, contexto, db)
    elif skill_activo == "recomendacion_peliculas_opsatv":
        estados_skills[numero] = None
        response_text = procesar_recomendacion_peliculas(numero, mensaje, contexto)
    else:
        estados_skills[numero] = None
        response_text = procesar_chat_general(numero, mensaje, contexto)
        
    # 5. Guardar la respuesta generada en el historial
    guardar_mensaje_historial(numero, "assistant", response_text)
    
    # 6. Despachar el mensaje por WhatsApp usando el bridge local
    whatsapp_service.send_whatsapp_message(numero, response_text)
    
    return response_text
