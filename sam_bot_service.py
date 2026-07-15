import os
import re
import json
import anthropic
from sqlalchemy.orm import Session
import models
from rapidfuzz import fuzz, process
import whatsapp_service

CLAUDE_MODEL = "claude-3-5-haiku-20241022"

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
- recomendacion_peliculas_opsatv: Si el usuario menciona alguna de estas palabras clave o conceptos: recomendar, recomendación, sugerir, sugerencia, qué ver, qué me recomiendas, ver, película, serie, buscar películas, encontrar series, estrenos, tendencia, top, popular, famoso, cartelera, OPSATV, acción (en contexto de cine), comedia, drama, terror, ciencia ficción, suspenso, thriller, aventura, animación, romance, documental, misterio, o cualquier solicitud relacionada con entretenimiento audiovisual.
- general: Si es un saludo, despedida, pregunta genérica, agradecimiento o no encaja en las anteriores.

Conversación actual:
"{contexto}"

Tu tarea: Responde únicamente con el nombre de la intención ("registrar_cliente_potencial", "consultar_pagos_y_saldos", "recomendacion_peliculas_opsatv" o "general"). No agregues explicaciones, puntuación ni texto adicional."""

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
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
        # Obtener el último mensaje del usuario
        lineas = contexto.strip().split("\n")
        ultimo_mensaje = lineas[-1].replace("user:", "").strip().lower() if lineas else ""
        if any(w in ultimo_mensaje for w in ["saldo", "debo", "pagar", "pago", "factura", "cuanto", "cuánto", "deuda"]):
            return "consultar_pagos_y_saldos"
        elif any(w in ultimo_mensaje for w in ["registrar", "nuevo cliente", "prospecto", "ingresar cliente"]):
            return "registrar_cliente_potencial"
        elif any(w in ultimo_mensaje for w in [
            "pelicula", "película", "serie", "recomendar", "recomendacion", "recomendación",
            "sugerir", "sugerencia", "qué ver", "que ver", "opsatv", "ver", "estrenos",
            "tendencia", "top", "popular", "famoso", "cartelera", "accion", "comedia",
            "drama", "terror", "ciencia ficcion", "suspenso", "thriller", "aventura",
            "animacion", "romance", "documental", "misterio", "buscar", "encontrar"
        ]):
            return "recomendacion_peliculas_opsatv"
        return "general"

# -------------------------------------------------------------
# SKILL: REGISTRAR CLIENTE POTENCIAL
# -------------------------------------------------------------
PROMPT_REGISTRO_CLIENTE = """# Skill: Registrar Cliente
Eres SAM, la IA encargada de recopilar los datos para registrar un nuevo cliente en el sistema de OPSATEL.
"""

def procesar_registro_cliente(numero: str, mensaje: str, contexto: str, db: Session) -> str:
    client = get_anthropic_client()
    
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

    messages = [
        {"role": "user", "content": f"{prompt_dinamico}\n\nConversación hasta ahora:\n{contexto}"}
    ]
    
    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=600,
            temperature=0.2,
            messages=messages
        )
        res_text = response.content[0].text.strip()
        
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
    client = get_anthropic_client()
    
    # 1. Comprobar si el usuario desea cancelar el flujo activo
    if mensaje.strip().lower() in ["cancelar", "salir", "cancel", "no"]:
        estados_skills[numero] = None
        if numero in historial_conversaciones:
            historial_conversaciones[numero] = []
        return "Entendido, he cancelado la consulta de saldo. ¿En qué más te puedo ayudar hoy?"

    # 2. Comprobar si el mensaje actual ya contiene una cédula
    cedula_extraida = extraer_cedula(mensaje)
    
    if cedula_extraida:
        cliente = db.query(models.Cliente).filter(models.Cliente.cedula == cedula_extraida).first()
        if cliente:
            # Encontrado, limpiamos el estado del skill y devolvemos la información
            estados_skills[numero] = None
            
            # Obtener pagos e historial
            pagos = db.query(models.Pago).filter(models.Pago.cliente_id == cliente.id).order_by(models.Pago.fecha_pago.desc()).limit(3).all()
            historial_pagos_text = ""
            if pagos:
                for p in pagos:
                    fecha_str = p.fecha_pago.strftime("%d/%m/%Y") if p.fecha_pago else "N/A"
                    historial_pagos_text += f"- {fecha_str}: ${p.monto} ({p.metodo_pago or 'No especificado'})\n"
            else:
                historial_pagos_text = "No registra pagos previos en el sistema.\n"
                
            prompt_pago = f"""Eres SAM, el Sistema Autónomo Multitarea de OPSATEL.
Un cliente ha solicitado información sobre su saldo y estado de cuenta.
Genera una respuesta amigable, educada y concisa informando sobre estos datos.

Datos reales del cliente:
- Nombre: {cliente.nombre}
- Cédula: {cliente.cedula}
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
                    model=CLAUDE_MODEL,
                    max_tokens=250,
                    temperature=0.3,
                    messages=[{"role": "user", "content": prompt_pago}]
                )
                return response_sam.content[0].text.strip()
            except Exception as e:
                print(f"[SAM Chatbot] Error generando respuesta de pago: {e}")
                return f"Hola {cliente.nombre}, tu saldo pendiente es de ${cliente.saldo or 0.00} y tu servicio se encuentra en estado: {cliente.estado}."
        else:
            # Cédula ingresada pero no encontrada en BD. No limpiamos el estado del skill
            return f"Lo siento, no encontré ningún cliente con el número de cédula **{cedula_extraida}** en nuestra base de datos. Por favor, verifica el número e ingrésalo nuevamente, o escribe **cancelar** para volver al inicio."

    # 3. Si no hay cédula en el mensaje actual:
    if ya_solicitado:
        # Ya estábamos en el flujo y no ingresó una cédula válida
        return "No logré identificar un número de cédula de 10 dígitos. Por favor, indícame tu número de cédula para consultar tu saldo, o escribe **cancelar** para volver al inicio."
        
    # Si es el primer mensaje del flujo, verificamos si menciona a un tercero por nombre
    prompt_extract = f"""Del siguiente mensaje de WhatsApp del usuario, determina si está pidiendo consultar el saldo/pago de otra persona mencionando su nombre de forma explícita.
Si menciona un nombre, responde únicamente con el nombre extraído.
Si el usuario pregunta por su propio saldo (ej. "cuanto debo", "mi saldo", "mi pago") o no menciona ningún nombre específico, responde únicamente con la palabra "auto".

Mensaje: "{mensaje}"
Respuesta:"""
    
    nombre_buscado = "auto"
    try:
        response_ext = client.messages.create(
            model=CLAUDE_MODEL,
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
        # No se especificó nombre de otra persona y tampoco detectamos cédula en este primer mensaje.
        # Por lo tanto, solicitamos la cédula para iniciar el flujo interactivo.
        estados_skills[numero] = "consultar_pagos_y_saldos"
        return "Por favor, ayúdame con tu número de cédula para consultar tu saldo."
    else:
        # Búsqueda por el nombre extraído (para compatibilidad de consultas de terceros)
        cliente, sugerencias = buscar_cliente_por_nombre(nombre_buscado, db)
        # Como es consulta directa por nombre, no mantenemos estado activo del skill
        estados_skills[numero] = None
        
    if not cliente:
        if sugerencias:
            sug_text = "\n".join([f"- {s['nombre']}" for s in sugerencias])
            return f"No encontré un cliente exacto para '{nombre_buscado}'. ¿Te refieres a alguno de estos?\n{sug_text}\n\nPor favor indícame el nombre tal como aparece arriba."
        else:
            return f"Lo lamento, no encontré ningún cliente con el nombre '{nombre_buscado}' en nuestra base de datos."
            
    # Si encontramos al cliente por nombre, obtenemos sus últimos pagos y saldo
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
            model=CLAUDE_MODEL,
            max_tokens=250,
            temperature=0.3,
            messages=[{"role": "user", "content": prompt_pago}]
        )
        return response_sam.content[0].text.strip()
    except Exception as e:
        print(f"[SAM Chatbot] Error generando respuesta de pago: {e}")
        return f"Hola {cliente.nombre}, tu saldo pendiente es de ${cliente.saldo or 0.00} y tu servicio se encuentra en estado: {cliente.estado}."

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
    client = get_anthropic_client()
    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=500,
            temperature=0.9,
            messages=[{"role": "user", "content": f"{PROMPT_PELICULAS}\n\nConversación con el usuario:\n{contexto}\n\nMensaje actual del usuario: {mensaje}\n\nResponde directamente con las recomendaciones, sin preámbulos ni encabezados adicionales."}]
        )
        return response.content[0].text.strip()
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
# CHAT GENERAL (PERSONALIDAD BÁSICA DE SAM)
# -------------------------------------------------------------
PROMPT_GENERAL = """Eres SAM (Sistema Autónomo Multitarea de OPSATEL), un asistente virtual inteligente para la empresa proveedora de Internet y Telecomunicaciones OPSATEL.
Tu personalidad es amable, atenta, rápida y muy profesional.
Tus respuestas deben ser cortas, directas y optimizadas para leerse en WhatsApp.

Si el usuario te hace preguntas generales o te saluda, dale la bienvenida usando siempre el saludo: "Hola soy Sam de opsatel, espero estes teniendo un buen dia en que puedo ayudarte el dia de hoy?" y ofréceles tu ayuda en lo que necesiten.

REGLA IMPORTANTE: Si el usuario te hace una pregunta sobre la que no tienes información suficiente, no la puedes responder con certeza, o está fuera de tus funciones, responde SIEMPRE con el siguiente mensaje exacto:
"Lamento informarle que no cuento con la información necesaria para responder a su consulta con precisión. Le sugiero verificar esta cuestión con el personal corporativo"
No inventes datos, no especules. Solo usa la respuesta anterior cuando no puedas responder con certeza."""

def procesar_chat_general(numero: str, mensaje: str, contexto: str) -> str:
    client = get_anthropic_client()
    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=350,
            temperature=0.5,
            messages=[{"role": "user", "content": f"{PROMPT_GENERAL}\n\nConversación:\n{contexto}"}]
        )
        return response.content[0].text.strip()
    except Exception as e:
        print(f"[SAM Chatbot] Error en chat general: {e}")
        return "Hola soy Sam de opsatel, espero estes teniendo un buen dia en que puedo ayudarte el dia de hoy?"

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
    ya_solicitado = (skill_activo == "consultar_pagos_y_saldos")
    
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
        # Marcar que este número está en el flujo de consulta de pagos/saldos
        estados_skills[numero] = "consultar_pagos_y_saldos"
        response_text = procesar_consulta_pago(numero, mensaje, contexto, db, ya_solicitado)
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
