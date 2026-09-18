"""
Servicio Central de Chatbot SAM con Groq API y Function Calling nativo.
Orquesta el ciclo multi-turno de mensajes, ejecución de herramientas y
respuestas contextuales sin alucinaciones para WhatsApp.
"""

import os
import json
import re
import time
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from groq import Groq

from ai_tools import TOOLS_SCHEMA, ejecutar_herramienta
from system_prompt import SYSTEM_PROMPT

logger = logging.getLogger("opsatel.chatbot_service")

# Modelos recomendados de Groq compatibles con Tool Calling nativo
DEFAULT_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
FALLBACK_MODELS = [
    DEFAULT_MODEL,
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "llama-3.3-70b-versatile",
    "llama-3.1-70b-versatile",
    "llama-3.1-8b-instant"
]

_active_groq_model = None


def resolver_modelo_groq(client: Groq) -> str:
    """
    Resuelve dinámicamente un modelo de Groq activo y compatible con Tool Calling.
    Filtra modelos incompatibles (whisper, compound, safeguards, etc.).
    """
    global _active_groq_model
    if _active_groq_model:
        return _active_groq_model

    # Si el usuario configuró GROQ_MODEL explícitamente en el entorno
    env_model = os.getenv("GROQ_MODEL")
    if env_model and env_model.strip():
        _active_groq_model = env_model.strip()
        return _active_groq_model

    try:
        models_resp = client.models.list()
        # Filtrar modelos que no soportan Tool Calling (compound, whisper, guard, vision, etc.)
        live_ids = [
            m.id for m in models_resp.data
            if m.id and not any(x in m.id.lower() for x in [
                "compound", "whisper", "guard", "safeguard", "embed", "tts", "audio", "vision", "orpheus", "allam"
            ])
        ]
        logger.info(f"[Chatbot SAM] Modelos compatibles reportados en cuenta Groq: {live_ids}")
        for pref in FALLBACK_MODELS:
            if pref in live_ids:
                _active_groq_model = pref
                logger.info(f"[Chatbot SAM] Modelo activo resuelto: {_active_groq_model}")
                return _active_groq_model
        if live_ids:
            _active_groq_model = live_ids[0]
            return _active_groq_model
    except Exception as e_list:
        logger.warning(f"[Chatbot SAM] No se pudo listar modelos ({e_list}). Usando {DEFAULT_MODEL}")

    _active_groq_model = DEFAULT_MODEL
    return _active_groq_model


def obtener_cliente_groq() -> Groq:
    """Instancia el cliente oficial de Groq con timeout ágil y max_retries=0 para rotar modelos al instante."""
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY no configurada en las variables de entorno (.env). "
            "Por favor, configure GROQ_API_KEY para habilitar el chatbot."
        )
    return Groq(api_key=api_key, max_retries=0, timeout=12.0)



def resolver_identidad_whatsapp(numero_raw: str, jid_original: str = "") -> Dict[str, Any]:
    """
    Analiza y normaliza el identificador o teléfono entrante de WhatsApp.
    Distingue entre identificadores opacos/privados (LID de WhatsApp) y números telefónicos reales.
    
    Retorna un diccionario con:
        - es_lid: bool indicando si es un LID anónimo no resuelto
        - telefono_limpio: str con el número telefónico real si se conoce
        - jid_destino: str con el JID de destino para enviar la respuesta a WhatsApp
        - metadata_ia: str con la directriz contextual estricta para Groq
    """
    import re
    num_str = str(numero_raw or "").strip()
    jid_str = str(jid_original or "").strip()

    # Determinar el JID exacto para despachar la respuesta por WhatsApp
    if jid_str and "@lid" in jid_str.lower():
        jid_destino = jid_str
    elif "@" in num_str:
        jid_destino = num_str
    else:
        jid_destino = num_str

    # Extraer únicamente los dígitos numéricos del número principal recibido
    parte_usuario = num_str.split("@")[0] if "@" in num_str else num_str
    solo_digitos = re.sub(r"\D", "", parte_usuario)

    # Es un número celular real si tiene entre 8 y 13 dígitos y no contiene la palabra 'lid'
    if "@lid" not in num_str.lower() and 8 <= len(solo_digitos) <= 13:
        telefono_limpio = solo_digitos
        es_lid = False
        metadata_ia = (
            f"El cliente escribe desde el número celular registrado '{telefono_limpio}'. "
            f"Tu PRIMERA ACCIÓN OBLIGATORIA ante cualquier consulta, saludo o reclamo es ejecutar "
            f"'consultar_estado_cliente(telefono='{telefono_limpio}')' para verificar su contrato, saldo y servicio. "
            "Si la herramienta encuentra sus datos, trátalo con calidez por su primer nombre y "
            "NO LE PIDAS CÉDULA NI TELÉFONO. "
            "REGLA CRÍTICA: Si el usuario únicamente saluda ('hola', 'buenas'), responde exclusivamente con un saludo cálido y pregunta amablemente en qué le colaboras hoy. "
            "PROHIBIDO cobrarle, mencionarle moras, saldos o enviarle cuentas bancarias en un simple saludo."
        )
    else:
        telefono_limpio = ""
        es_lid = True
        metadata_ia = (
            f"El usuario te escribe desde un identificador de WhatsApp (LID: '{jid_destino}') que oculta temporalmente su número. "
            "Si no posees su teléfono en el historial, solicítale amablemente su número de cédula o su celular registrado de contrato "
            "para ubicar su ficha en el sistema."
        )

    return {
        "es_lid": es_lid,
        "telefono_limpio": telefono_limpio,
        "jid_destino": jid_destino,
        "metadata_ia": metadata_ia
    }


def procesar_mensaje_con_herramientas(
    mensaje: str,
    numero: str,
    db: Session,
    historial_mensajes: Optional[List[Dict[str, Any]]] = None,
    metadata_identidad: Optional[str] = None,
    max_tool_iterations: int = 4
) -> str:
    """
    Función controladora del ciclo de vida del LLM con Function Calling.
    
    1. Prepara el historial con el system_prompt y contexto del cliente.
    2. Envía la solicitud a Groq incluyendo el esquema de tools.
    3. Si Groq responde con 'tool_calls', ejecuta el dispatcher contra el backend.
    4. Inyecta el resultado con rol 'tool' y realiza el segundo pase a Groq.
    5. Retorna la respuesta final en lenguaje natural para WhatsApp.
    
    Args:
        mensaje: Texto entrante enviado por el cliente en WhatsApp.
        numero: Teléfono del remitente (WhatsApp JID/número limpio).
        db: Sesión activa de base de datos SQLAlchemy.
        historial_mensajes: Conversación previa en formato [{"role": "user"|"assistant", "content": "..."}].
        metadata_identidad: Instrucción contextual sobre la resolución del LID o celular.
        max_tool_iterations: Límite de ejecuciones secuenciales de herramientas por turno.
    
    Returns:
        Texto final de respuesta redactado por SAM para enviar al cliente.
    """
    client = obtener_cliente_groq()

    # Directriz de identidad contextual para Groq
    contexto_remitente = metadata_identidad or (
        f"El cliente está enviando un mensaje desde el número '{numero}'. "
        "La identidad, titularidad y estado del cliente se determinan exclusivamente por su registro en la BASE DE DATOS "
        "usando la herramienta 'consultar_estado_cliente'. NO te fíes de nombres de perfiles o contactos de WhatsApp."
    )

    # Construcción de la lista inicial de mensajes
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "system",
            "content": f"[METADATA DEL REMITENTE]: {contexto_remitente}"
        }
    ]

    # Incorporar historial previo de la conversación si se proporciona (máx 3 turnos para ahorro de tokens)
    if historial_mensajes:
        for msg in historial_mensajes[-3:]:
            rol = msg.get("role", "user")
            contenido = msg.get("content", "")
            if rol in ["user", "assistant"] and contenido:
                messages.append({"role": rol, "content": str(contenido)[:350]})

    # Agregar el mensaje actual del cliente solo si no fue ya incluido
    if not messages or messages[-1].get("content") != mensaje:
        messages.append({"role": "user", "content": mensaje})

    # Resolver modelo dinámicamente según permisos de la cuenta
    model_to_use = resolver_modelo_groq(client)
    candidatos_modelos = [model_to_use] + [m for m in FALLBACK_MODELS if m != model_to_use]

    # Ciclo de ejecución de herramientas (Soporta múltiples pasos: ej. consultar cliente -> consultar saturación -> responder)
    for iteracion in range(max_tool_iterations):
        try:
            chat_completion = None
            for cand in candidatos_modelos:
                try:
                    logger.info(f"[Chatbot SAM] [Pase {iteracion + 1}] Enviando solicitud a Groq (Modelo: {cand})...")
                    chat_completion = client.chat.completions.create(
                        model=cand,
                        messages=messages,
                        tools=TOOLS_SCHEMA,
                        tool_choice="auto",
                        temperature=0.4,
                        max_tokens=400
                    )
                    model_to_use = cand
                    _active_groq_model = cand
                    break
                except Exception as e_cand:
                    err_msg = str(e_cand).lower()
                    # Manejo ágil de Rate Limit (429 TPM): rotación instantánea a modelo alternativo
                    if "429" in err_msg or "rate_limit" in err_msg or "tokens" in err_msg:
                        logger.warning(f"[Chatbot SAM] Modelo '{cand}' saturó tokens (429). Rotando inmediatamente a modelo alternativo...")
                    elif any(k in err_msg for k in ["404", "does not exist", "access", "tool calling", "not supported", "400"]):
                        logger.warning(f"[Chatbot SAM] Modelo '{cand}' incompatible ({e_cand}). Rotando a modelo alternativo...")
                    else:
                        logger.warning(f"[Chatbot SAM] Error con modelo '{cand}' ({e_cand}). Probando alternativo...")
                    continue

            if not chat_completion:
                logger.error("[Chatbot SAM] Ninguno de los modelos candidatos pudo completar el ciclo con tools.")
                break

            response_message = chat_completion.choices[0].message
            tool_calls = response_message.tool_calls

            # CASO A: Groq no solicitó herramientas o ya terminó de recopilar datos -> Retornar respuesta
            if not tool_calls:
                texto_respuesta = response_message.content or ""
                logger.info(f"[Chatbot SAM] Respuesta final generada exitosamente con modelo: {model_to_use}")
                return texto_respuesta.strip()

            # CASO B: Groq solicitó la ejecución de una o más herramientas
            logger.info(f"[Chatbot SAM] Groq solicitó {len(tool_calls)} llamada(s) a herramienta(s).")
            
            # Anexar el mensaje del asistente con las tool_calls al historial
            messages.append(response_message)

            # Ejecutar cada herramienta solicitada
            for tool_call in tool_calls:
                function_name = tool_call.function.name
                arguments_str = tool_call.function.arguments or "{}"
                
                try:
                    arguments = json.loads(arguments_str)
                except json.JSONDecodeError:
                    logger.error(f"[Chatbot SAM] Error decodificando argumentos JSON: {arguments_str}")
                    arguments = {}

                # Si la función es consultar_estado_cliente y no enviaron teléfono, autocompletar solo si es número real (no LID)
                if function_name == "consultar_estado_cliente" and not arguments.get("telefono"):
                    import re
                    solo_dig = re.sub(r'\D', '', str(numero or ""))
                    if solo_dig and 8 <= len(solo_dig) <= 13 and "@lid" not in str(numero).lower():
                        arguments["telefono"] = numero
                    else:
                        arguments["telefono"] = ""

                logger.info(f"[Chatbot SAM] Ejecutando tool '{function_name}' con args: {arguments}")
                
                # Ejecutar la lógica real del backend usando el Router/Dispatcher
                resultado = ejecutar_herramienta(
                    nombre_herramienta=function_name,
                    argumentos=arguments,
                    db=db
                )

                # Agregar la respuesta de la herramienta con rol 'tool' y el ID correspondiente
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": function_name,
                    "content": json.dumps(resultado, ensure_ascii=False)
                })

            # El ciclo continúa al siguiente pase para que Groq procese los datos de la herramienta

        except Exception as e:
            logger.error(f"[Chatbot SAM] Error durante ciclo de Groq con herramientas: {e}")
            break

    # Si por alguna razón el ciclo de tools no pudo cerrar, solicitar respuesta final de texto natural
    try:
        # Filtrar llamadas a herramientas huérfanas si quedaron en messages
        clean_messages = []
        for m in messages:
            if isinstance(m, dict) and m.get("role") == "tool" and not m.get("content"):
                continue
            clean_messages.append(m)

        for cand_fin in candidatos_modelos:
            try:
                final_completion = client.chat.completions.create(
                    model=cand_fin,
                    messages=clean_messages,
                    temperature=0.5,
                    max_tokens=450
                )
                txt_res = (final_completion.choices[0].message.content or "").strip()
                if txt_res:
                    return txt_res
            except Exception:
                continue

        return "¡Hola! Con gusto te ayudo. ¿En qué te puedo colaborar el día de hoy con tus servicios de Opsatel? 😊"
    except Exception as e:
        logger.error(f"[Chatbot SAM] Error generando respuesta de cierre: {e}")
        return "¡Hola! ¿En qué te puedo colaborar el día de hoy con tus servicios de Opsatel? 😊"
