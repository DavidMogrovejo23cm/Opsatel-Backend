"""
Módulo de skills especializadas de SAM Chatbot:
- Registro de clientes potenciales y agendamiento en Hoja de Ruta.
- Consulta de pagos, saldos y deudas.
- Envío de cuentas bancarias y medios de pago.
- Recomendación de películas y cartelera.
- Soporte técnico inteligente, diagnóstico de potencia óptica y alerta a técnico de guardia.
- Chat general y orientación comercial.
"""
import os
import re
import json
from typing import Optional, Tuple, Dict, Any, List
from datetime import datetime, timedelta
import pytz
from sqlalchemy.orm import Session

import models
from .llm_client import generar_respuesta_ia
from .session_manager import (
    estados_skills,
    clientes_identificados_sesion,
    historial_conversaciones,
    obtener_fecha_hora_ecuador,
)
from .client_lookup import (
    obtener_datos_cliente,
    obtener_cliente_sesion,
    obtener_deuda_total_cliente,
    buscar_cliente_por_cedula_o_celular,
    buscar_cliente_por_nombre,
    extraer_identificador_cliente,
)

SYSTEM_PROMPT_BASE = (
    "Eres SAM, el asistente virtual inteligente de la empresa de telecomunicaciones OPSATEL. "
    "Tu objetivo es brindar soporte técnico, consultas de saldo, planes y atención a clientes de forma clara, "
    "concisa y profesional en español. Mantén un tono cordial, empático y resolutivo."
)

PLANTILLAS = {
    "saldo": "Tu saldo es **{saldo} €**. 📈",
    "pago": "Puedes pagar aquí: {link} 💳",
    "factura": "Tu última factura: {numero_factura} - {monto} €. 📄",
}

NUMERO_TECNICO_GUARDIA = "593988804142"

PROMPT_REGISTRO_CLIENTE = """# Skill: Registrar Cliente
Eres SAM, la IA encargada de recopilar los datos para registrar un nuevo cliente en el sistema de OPSATEL.
"""

PROMPT_PELICULAS = """# Rol: Asesor de Cine y Entretenimiento OPSATEL / OPSATV
Eres SAM, el asistente inteligente de entretenimiento de OPSATEL.
Tu objetivo es responder consultas sobre películas, sinopsis o brindar recomendaciones de cine de primer nivel.

DIRECTRICES:
1. Recomienda entre 2 y 3 películas variadas (populares, aclamadas o taquilleras).
2. Para cada una incluye:
   - Título y año
   - Género
   - Una breve sinopsis de 1 o 2 líneas
   - Por qué vale la pena verla
3. Mantén un tono amigable, cinéfilo y entretenido.
4. Concluye recordando amablemente que pueden disfrutar el mejor entretenimiento a través de la plataforma OPSATV de OPSATEL.
"""

PROMPT_GENERAL = """# Rol: SAM - Asesor Virtual Oficial de OPSATEL Telecomunicaciones
Eres SAM, la inteligencia artificial y asesor virtual de OPSATEL (empresa líder en servicios de internet por fibra óptica de alta velocidad y televisión IPTV).

DIRECTRICES DE PERSONALIDAD Y ATENCIÓN:
1. Sé EXTREMADAMENTE CONCISO, ÁGIL, CÁLIDO Y HUMANO.
2. Respuestas cortas (máximo 1 a 3 líneas). Evita textos largos.
3. Si el usuario te saluda, salúdalo con calidez por su nombre si está disponible.
4. Responde con precisión usando la información oficial de OPSATEL.
"""

PROMPT_SOPORTE_TECNICO = """# Rol: SAM - Especialista de Soporte Técnico Oficial de OPSATEL
Eres SAM, el asesor técnico de primer nivel de OPSATEL Telecomunicaciones.
Tu misión es diagnosticar de forma inteligente la conexión de fibra óptica del cliente, resolver dudas técnicas y canalizar incidencias críticas con los técnicos de guardia.

REGLAS DE ATENCIÓN:
1. Prioriza empatía, calma y soluciones prácticas paso a paso.
2. Si el diagnóstico interno detecta un corte por falta de pago:
   Infórmale con respeto y cortesía que su servicio presenta una suspensión temporal por un valor pendiente, y pregúntale amablemente si desea las cuentas bancarias para su reactivación. NUNCA lo hagas reiniciar equipos si la causa es administrativa de pago.
3. Formato para WhatsApp: Mensajes breves (máximo 2 a 4 líneas), cálidos, agradables y sin muros de texto. Usa emojis amigables con moderación (😊, 🔌, 👍, ✨).
"""


def construir_prompt(mensaje_raw: str, cliente_id: int) -> str:
    """Construye el prompt para la IA insertando datos del cliente en formato JSON."""
    datos = obtener_datos_cliente(cliente_id)
    datos_json = json.dumps(datos, ensure_ascii=False)
    return f"Datos del cliente: {datos_json}\n{mensaje_raw}"


def es_solicitud_cuentas_pago(msg_limpio: str) -> bool:
    """
    Discierne de forma inteligente y contextual si el mensaje del cliente
    es una pregunta por cuentas bancarias, números de cuenta, transferencias,
    depósitos o medios de pago oficiales de Opsatel.
    """
    if not msg_limpio:
        return False
        
    frases_directas = [
        "a que cuenta", "a qué cuenta", "en que cuenta", "en qué cuenta",
        "cuentas para pagar", "cuenta para pagar", "cuentas de pago", "cuenta de pago",
        "cuentas bancarias", "cuenta bancaria", "datos bancarios", "datos de la cuenta",
        "datos de las cuentas", "datos para transferir", "datos para el deposito",
        "datos para depósito", "datos para pagar", "datos de pago",
        "numero de cuenta", "número de cuenta", "numeros de cuenta", "números de cuenta",
        "num de cuenta", "nro de cuenta", "n° de cuenta",
        "donde pago", "dónde pago", "donde puedo pagar", "dónde puedo pagar",
        "donde cancelo", "dónde cancelo", "donde puedo cancelar", "dónde puedo cancelar",
        "donde se paga", "dónde se paga", "donde cancelar", "dónde cancelar",
        "donde transferir", "dónde transferir", "donde puedo transferir", "dónde puedo transferir",
        "donde depositar", "dónde depositar", "donde puedo depositar", "dónde puedo depositar",
        "como transferir", "cómo transferir", "como depositar", "cómo depositar",
        "a donde transfiero", "a dónde transfiero", "a donde deposito", "a dónde deposito",
        "a donde pago", "a dónde pago", "a donde cancelo", "a dónde cancelo",
        "a nombre de quien", "a nombre de quién", "banco pichincha", "cooperativa jep",
        "cuenta pichincha", "cuenta jep", "pichincha o jep", "jep o pichincha",
        "pasame la cuenta", "pásame la cuenta", "pasame las cuentas", "pásame las cuentas",
        "pasar la cuenta", "pasar las cuentas", "pase la cuenta", "pase las cuentas",
        "me pasa la cuenta", "me pasa las cuentas", "me ayuda con la cuenta", "me ayuda con las cuentas",
        "mandame la cuenta", "mándame la cuenta", "mandame las cuentas", "mándame las cuentas",
        "envíame la cuenta", "enviame la cuenta", "envíame las cuentas", "enviame las cuentas",
        "enviar comprobante", "envio comprobante", "envío comprobante", "donde envio el comprobante",
        "a donde envio el comprobante", "a dónde envío el comprobante", "donde mando el comprobante",
        "formas de pago", "medios de pago", "metodos de pago", "métodos de pago",
        "pagar el servicio", "cancelar el servicio", "pagar el internet", "cancelar el internet"
    ]
    if any(f in msg_limpio for f in frases_directas):
        return True

    tiene_interrogativo = any(w in msg_limpio for w in ["donde", "dónde", "como", "cómo", "a donde", "a dónde", "por donde", "por dónde"])
    tiene_verbo_pago = any(w in msg_limpio for w in ["pago", "pagar", "cancelo", "cancelar", "transferir", "transfiero", "deposito", "depositar"])
    if tiene_interrogativo and tiene_verbo_pago:
        if not any(w in msg_limpio for w in ["foco rojo", "sin internet", "contratar", "nuevo contrato"]):
            return True

    tiene_cuenta = any(w in msg_limpio for w in ["cuenta", "cuentas", "cta", "ctas"])
    tiene_accion_pago = any(w in msg_limpio for w in [
        "pagar", "pago", "cancelar", "transferir", "transferencia", "deposito", "depósito", "depositar", "banco", "bancos"
    ])
    if tiene_cuenta and tiene_accion_pago and not any(w in msg_limpio for w in ["como te llamas", "crear cuenta"]):
        return True

    return False


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
        if not any(w in msg_limpio for w in ["debo", "saldo", "cuenta", "transferir", "foco rojo", "sin internet"]):
            return "general"

    # 2. Solicitud explícita de Cuentas Bancarias / Medios de Pago
    if es_solicitud_cuentas_pago(msg_limpio):
        return "solicitar_cuentas_pago"

    # 3. Intención explícita de CONTRATAR o AGENDAR INSTALACIÓN
    if any(w in msg_limpio for w in [
        "quiero contratar", "deseo contratar", "agendar instalacion", "agendar instalación",
        "solicitar instalacion", "solicitar instalación", "quiero instalar", "deseo instalar",
        "instalenme", "instálenme", "contratar internet", "contratar el plan", "nuevo cliente",
        "prospecto", "nueva instalacion", "nueva instalación", "agendar cita", "quiero el servicio",
        "contratar", "me interesa contratar"
    ]):
        return "registrar_cliente_potencial"

    # 4. Consultas informativas sobre Planes, Ofertas, Precios, Megas o Servicios -> GENERAL
    if any(w in msg_limpio for w in [
        "plan", "planes", "precio", "precios", "oferta", "ofertas", "megas", "costo",
        "tarifa", "cuanto cuesta", "cuánto cuesta", "cuanto vale", "cuánto vale",
        "que ofrecen", "qué ofrecen", "servicios", "promocion", "promociones",
        "velocidad", "cobertura", "subir de nivel", "cambiar de plan", "mejorar plan"
    ]):
        return "general"

    # 5. Consultas explícitas de Pago / Saldo / Deuda personal
    tiene_identificador = bool(re.search(r'\b\d{9,13}\b', msg_limpio)) or bool(re.search(r'(?:c[eé]dula|ruc|celular|tel[eé]fono|cel)\D{0,5}\d{7,13}', msg_limpio))
    es_pregunta_deuda = any(w in msg_limpio for w in [
        "cuanto debo", "cuánto debo", "mi saldo", "saldo pendiente", "mi deuda",
        "mi factura", "factura pendiente", "estado de cuenta", "cuanto tengo que pagar",
        "cuánto tengo que pagar", "pago pendiente", "mi pago", "consultar saldo",
        "saber mi saldo", "cuanto es mi saldo", "cuánto es mi saldo", "valor a pagar"
    ])
    if tiene_identificador or es_pregunta_deuda:
        return "consultar_pagos_y_saldos"

    # 6. Soporte técnico / fallas / lentitud
    if any(w in msg_limpio for w in [
        "foco rojo", "luz roja", "sin internet", "sin servicio", "no tengo internet",
        "no hay internet", "se fue el internet", "sin senal", "sin señal", "luz los",
        "los rojo", "parpadea", "modem", "módem", "router", "falla", "fallando", "desconectado", "cable roto",
        "lento", "lentitud", "internet lento", "muy lento", "mal internet", "pésimo internet", "pesimo internet",
        "se corta", "intermitente", "no carga", "baja velocidad", "cae el internet", "problema con el internet",
    ]):
        return "soporte_tecnico"

    # 7. Películas / Entretenimiento
    if any(w in msg_limpio for w in ["pelicula", "película", "peliculas", "películas", "cine", "recomienda", "recomendame", "iptv", "opsatv"]):
        return "recomendar_peliculas"

    # 8. Clasificación con IA si ninguna regla fija se activó
    prompt_clasificacion = f"""Clasifica la intención del usuario basándote en la conversación:
{contexto}

Opciones válidas:
- registrar_cliente_potencial: Quiere contratar o agendar una nueva instalación.
- consultar_pagos_y_saldos: Quiere saber su saldo, deuda o cuánto debe.
- solicitar_cuentas_pago: Pide cuentas bancarias, números de cuenta o dónde pagar.
- soporte_tecnico: Problemas de conexión, fallas, lentitud, luz roja.
- recomendar_peliculas: Pide recomendaciones de cine o TV.
- general: Saludos, charla general o preguntas comerciales.

Responde ÚNICAMENTE con una de las opciones anteriores."""

    try:
        intencion = generar_respuesta_ia(prompt_clasificacion, max_tokens=30, temperature=0.1).strip().lower()
        for intent in ["solicitar_cuentas_pago", "registrar_cliente_potencial", "consultar_pagos_y_saldos", "soporte_tecnico", "recomendar_peliculas"]:
            if intent in intencion:
                return intent
        return "general"
    except Exception as e:
        print(f"[SAM Chatbot] Error clasificando intención con IA: {e}")
        return "general"


def procesar_registro_cliente(numero: str, mensaje: str, contexto: str, db: Session) -> str:
    """
    Skill para recopilar datos de contratación de nuevos clientes y agendar automáticamente
    la orden de trabajo en la Hoja de Ruta técnica dentro de la jornada de 8:00 AM a 17:00 PM.
    """
    EC_TZ = pytz.timezone('America/Guayaquil')
    ahora_ec = datetime.now(EC_TZ)

    valid_nodos = [n[0] for n in db.query(models.Nodo.nombre).filter(models.Nodo.nombre != None).all()]
    valid_planes = [pl[0] for pl in db.query(models.PlanInternet.nombre).filter(models.PlanInternet.nombre != None).all()]

    dias_disponibles_txt = []
    for d_offset in range(5):
        dia_obj = ahora_ec + timedelta(days=d_offset)
        if dia_obj.weekday() == 6:
            continue
        f_str = dia_obj.strftime("%Y-%m-%d")
        nom_dia = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"][dia_obj.weekday()]
        conteo = db.query(models.HojaRuta).filter(models.HojaRuta.fecha == f_str, models.HojaRuta.estado != "Cancelado").count()
        dias_disponibles_txt.append(f"• {nom_dia} {f_str}: {conteo} citas técnicas agendadas")
    disponibilidad_str = "\n".join(dias_disponibles_txt)

    prompt_dinamico = f"""# Skill: Contratación y Agendamiento Técnico en Hoja de Ruta (OPSATEL)
Eres SAM, el asesor virtual de OPSATEL encargado de tomar los datos del contrato y agendar la orden de instalación en la Hoja de Ruta técnica.
Mantén un trato cálido, humano, ágil y profesional.

REGLAS DE LOS DATOS DEL CONTRATO:
1. DATOS OBLIGATORIOS:
   - nombre: Nombre y apellido completos del titular.
   - celular: Teléfono de contacto (por defecto el número de WhatsApp actual: {numero}).
   - ubicacion: COORDENADAS GPS O ENLACE DE GOOGLE MAPS (¡OBLIGATORIA! para que los técnicos puedan verificar la fibra óptica y llegar al domicilio exacto). Si el cliente no sabe cómo obtenerlas, explícale amablemente que puede compartir su ubicación actual por WhatsApp o enviar el link de Google Maps de su vivienda.
   - direccion: Dirección domiciliaria con calles y referencias claras (ej: color de casa, frente a qué lugar).
   - parroquia: Parroquia o sector donde se instalará.
   - plan: Plan de internet seleccionado (debe ser uno de los PLANES VÁLIDOS de OPSATEL).
   - fecha_instalacion: Fecha acordada para la instalación (coordinar según la disponibilidad mostrada abajo).
   - hora_instalacion: Hora acordada para la cita (¡ATENCIÓN! Los técnicos ÚNICAMENTE trabajan en la jornada de 8:00 AM a 17:00 PM / 8:00 a 17:00. NUNCA agendes fuera de ese horario).

2. DATO OPCIONAL:
   - cedula: Cédula de 10 dígitos o RUC. ¡LA CÉDULA ES TOTALMENTE OPCIONAL! Si el cliente te la brinda la anotas; si no la tiene o prefiere entregarla en persona a los técnicos durante la visita, NO insistas ni frenes el agendamiento; continúa con los demás datos.

PLANES VÁLIDOS: {json.dumps(valid_planes, ensure_ascii=False)}
NODOS / SECTORES VÁLIDOS: {json.dumps(valid_nodos, ensure_ascii=False)}

DISPONIBILIDAD TÉCNICA PRÓXIMA (Jornada técnica: 8:00 AM a 17:00 PM):
{disponibilidad_str}

DINÁMICA DE LA CONVERSACIÓN:
- Sé ágil y empático: puedes pedir varios datos juntos para no hacer el proceso largo.
- Explica al cliente que los técnicos laboran de 8:00 AM a 17:00 PM y oriéntale sobre las mejores opciones de fecha y hora disponibles.
- Cuando tengas los datos obligatorios (nombre, celular, ubicación/coordenadas, dirección, plan, fecha y hora), muestra un resumen ordenado y pide confirmación (ej: "¿Están correctos todos los datos para confirmar tu instalación?").
- ÚNICAMENTE cuando el usuario confirme diciendo "sí", "correcto", "confirmo", "de acuerdo", "ok", etc., responde GENERANDO SOLAMENTE UN JSON de una sola línea en este formato exacto:

{{"nombre": "", "cedula": "", "celular": "", "direccion": "", "ubicacion": "", "plan": "", "nodo": "", "parroquia": "", "fecha_instalacion": "YYYY-MM-DD", "hora_instalacion": "10:00 AM", "comentarios": ""}}
"""

    try:
        content = f"{prompt_dinamico}\n\nConversación hasta ahora:\n{contexto}"
        res_text = generar_respuesta_ia(content, max_tokens=700, temperature=0.2)
        
        json_match = re.search(r'\{.*"nombre".*\}', res_text)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                
                ubicacion_val = str(data.get("ubicacion") or "").strip()
                if not ubicacion_val:
                    lat = data.get("latitud")
                    lon = data.get("longitud")
                    if lat and lon and (lat != 0.0 or lon != 0.0):
                        ubicacion_val = f"{lat}, {lon}"
                    else:
                        ubicacion_val = str(data.get("direccion") or "")

                cedula = str(data.get("cedula") or "").strip()
                if cedula.lower() in ["sin cedula", "sin cédula", "no", "ninguna", "pendiente", "null", "none"]:
                    cedula = ""
                elif cedula.isdigit() and len(cedula) == 9:
                    cedula = "0" + cedula
                    
                celular = str(data.get("celular") or numero).strip()
                if celular.isdigit() and len(celular) == 9 and celular.startswith("9"):
                    celular = "0" + celular

                fecha_inst = str(data.get("fecha_instalacion") or "").strip()
                if not fecha_inst or len(fecha_inst) < 8:
                    fecha_inst = (ahora_ec + timedelta(days=1)).strftime("%Y-%m-%d")

                hora_inst = str(data.get("hora_instalacion") or "09:00 AM").strip()

                ids_query = db.query(models.Cliente.id).order_by(models.Cliente.id).all()
                ids = [i[0] for i in ids_query]
                nuevo_id = 1
                for current_id in ids:
                    if current_id == nuevo_id:
                        nuevo_id += 1
                    elif current_id > nuevo_id:
                        break

                nuevo_cliente = models.Cliente(
                    id=nuevo_id,
                    nombre=data.get("nombre"),
                    cedula=cedula,
                    celular=celular,
                    direccion=data.get("direccion"),
                    plan=data.get("plan"),
                    nodo=data.get("nodo"),
                    parroquia=data.get("parroquia"),
                    ubicacion=ubicacion_val,
                    comentarios=data.get("comentarios"),
                    estado="Pendiente",
                    saldo=0.00
                )
                db.add(nuevo_cliente)
                db.flush()

                obs_hoja = f"Plan: {data.get('plan') or 'No especificado'} | Dirección: {data.get('direccion') or 'No especificada'}"
                if cedula:
                    obs_hoja += f" | Cédula: {cedula}"
                if data.get("comentarios"):
                    obs_hoja += f" | Obs: {data.get('comentarios')}"

                nueva_hoja = models.HojaRuta(
                    fecha=fecha_inst,
                    hora=hora_inst,
                    cliente_id=nuevo_cliente.id,
                    nombre_cliente=nuevo_cliente.nombre,
                    ubicacion_cliente=ubicacion_val,
                    celular_cliente=celular,
                    parroquia=data.get("parroquia"),
                    actividad="Instalación Fibra Óptica",
                    observacion=obs_hoja,
                    estado="Pendiente"
                )
                db.add(nueva_hoja)
                db.commit()
                db.refresh(nuevo_cliente)
                db.refresh(nueva_hoja)
                
                estados_skills[numero] = None
                if numero in historial_conversaciones:
                    historial_conversaciones[numero] = []

                ced_txt = f"• *Cédula*: {cedula}\n" if cedula else "• *Cédula*: (Pendiente por validar en visita técnica)\n"
                    
                return (
                    f"🎉 *¡Solicitud de Instalación Agendada con Éxito en OPSATEL!*\n\n"
                    f"He registrado tus datos y creado tu orden de trabajo en nuestra Hoja de Ruta técnica:\n\n"
                    f"📋 *Orden de Trabajo*: #{nueva_hoja.id}\n"
                    f"👤 *Titular*: {nuevo_cliente.nombre}\n"
                    f"{ced_txt}"
                    f"📞 *Teléfono*: {celular}\n"
                    f"🚀 *Plan Elegido*: {nuevo_cliente.plan}\n"
                    f"🏠 *Dirección*: {nuevo_cliente.direccion}\n"
                    f"📍 *Ubicación*: {ubicacion_val}\n"
                    f"📅 *Fecha Agendada*: {fecha_inst}\n"
                    f"⏰ *Horario Técnico*: {hora_inst} *(Jornada técnica: 8:00 AM a 5:00 PM)*\n\n"
                    f"🔧 Nuestro equipo técnico se comunicará contigo antes de llegar a tu domicilio para coordinar la instalación de tu fibra óptica. ¡Bienvenido a la familia OPSATEL! 😊"
                )
            except Exception as db_err:
                print(f"[SAM Chatbot] Error guardando cliente y orden de trabajo: {db_err}")
                db.rollback()
                return "Hubo un inconveniente al guardar los datos en la base de datos. Por favor, reintenta en unos momentos."
        else:
            return res_text
    except Exception as e:
        print(f"[SAM Chatbot] Error en skill registrar cliente: {e}")
        return "Disculpa, tuve un problema al procesar los datos de instalación. ¿Podrías indicarme los datos nuevamente?"


def procesar_consulta_pago(numero: str, mensaje: str, contexto: str, db: Session, ya_solicitado: bool = False) -> str:
    """Procesa consultas de saldo y pagos usando datos 100% reales de MySQL por Cédula o Celular de forma natural, concisa y humana"""
    if mensaje.strip().lower() in ["cancelar", "salir", "cancel", "no", "menu", "menú"]:
        estados_skills[numero] = None
        clientes_identificados_sesion.pop(numero, None)
        return "Entendido, con gusto te ayudo con cualquier otra consulta sobre Opsatel 😊"

    ident_extraido = extraer_identificador_cliente(mensaje)
    cliente = None

    if ident_extraido:
        cliente = buscar_cliente_por_cedula_o_celular(ident_extraido, db)
        if cliente:
            clientes_identificados_sesion[numero] = cliente.id
        else:
            estados_skills[numero] = None
            return f"No encontré ningún contrato registrado con la cédula o celular **{ident_extraido}** en el sistema de OPSATEL. Por favor verifica que los dígitos sean correctos o indícame tu cédula/celular del titular para ayudarte 😊"

    if not cliente:
        cliente = obtener_cliente_sesion(numero, db, mensaje)

    if cliente:
        estados_skills[numero] = None
        clientes_identificados_sesion[numero] = cliente.id
        deuda = obtener_deuda_total_cliente(cliente)
        total_pendiente = deuda["total"]
        desglose = deuda["desglose"]

        nombre_limpio = " ".join((cliente.nombre or "").strip().split())
        primer_nombre = nombre_limpio.split()[0].capitalize() if nombre_limpio else "estimado/a cliente"

        prompt_pago = f"""Eres SAM, el asesor virtual oficial de OPSATEL.
Un cliente consulta su saldo pendiente por WhatsApp.
Genera una respuesta HUMANA, AMABLE Y MUY CORTA (máximo 2 a 3 líneas directas, sin rodeos ni discursos largos).

Datos oficiales del cliente en el sistema:
- Nombre: {cliente.nombre}
- Total a pagar hoy: ${total_pendiente:.2f}{desglose}
- Plan contratado: {cliente.plan or 'Internet'}
- Estado del servicio: {cliente.estado}

Directrices estrictas:
1. Saluda cordialmente por su primer nombre (*{primer_nombre}*).
2. Si el total a pagar es mayor a 0: Indica directamente el valor total de *${total_pendiente:.2f}*{desglose}. Pregúntale amablemente si desea las cuentas bancarias para realizar su pago.
3. Si el total a pagar es 0: Felicítalo calurosamente porque está completamente al día con sus pagos en OPSATEL.
4. No des discursos innecesarios. Sé directo y agradable."""
        try:
            return generar_respuesta_ia(prompt_pago, max_tokens=180, temperature=0.3)
        except Exception as e_ia:
            print(f"[SAM Chatbot] Error IA generando respuesta de pago: {e_ia}")
            if total_pendiente > 0:
                return f"¡Hola {primer_nombre}! Tu valor pendiente en OPSATEL es de *${total_pendiente:.2f}*{desglose}. ¿Deseas que te envíe nuestras cuentas bancarias oficiales para tu pago? 😊"
            else:
                return f"¡Hola {primer_nombre}! Te comento que te encuentras *al día* con tus pagos en OPSATEL 🎉 ¡Muchas gracias por tu puntualidad!"

    # Intento de búsqueda por nombre si se proporcionó
    texto_limpio = mensaje.strip()
    if len(texto_limpio.split()) >= 2 and not any(w in texto_limpio.lower() for w in ["cuanto", "debo", "saldo", "pago", "hola", "buenos"]):
        cliente_nom, _ = buscar_cliente_por_nombre(texto_limpio, db)
        if cliente_nom:
            estados_skills[numero] = None
            deuda_nom = obtener_deuda_total_cliente(cliente_nom)
            total_nom = deuda_nom["total"]
            desglose_nom = deuda_nom["desglose"]
            prompt_pago = f"""Eres SAM de OPSATEL. Informa de forma cortés, breve y humana (máximo 2 líneas) el saldo de {cliente_nom.nombre}:
- Total a pagar hoy: ${total_nom:.2f}{desglose_nom}
- Plan: {cliente_nom.plan or 'Internet'}
- Estado: {cliente_nom.estado}"""
            try:
                return generar_respuesta_ia(prompt_pago, max_tokens=150, temperature=0.3)
            except Exception:
                return f"El valor total pendiente de *{cliente_nom.nombre}* es de *${total_nom:.2f}*{desglose_nom} (Estado: {cliente_nom.estado})."

    estados_skills[numero] = "consultar_pagos_y_saldos"
    return "Con mucho gusto te ayudo a consultar tu saldo en OPSATEL 😊 Por favor indícame tu número de cédula o tu número de celular registrado para buscar tu contrato en el sistema."


def obtener_ruta_imagen_cuentas() -> Optional[str]:
    """Obtiene la ruta absoluta verificada de la imagen oficial de cuentas de pago de Opsatel"""
    candidatas = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads", "cuentas_pago.png"),
        os.path.abspath("uploads/cuentas_pago.png"),
        os.path.join(os.getcwd(), "uploads", "cuentas_pago.png")
    ]
    for c in candidatas:
        if os.path.exists(c):
            return c
    return None


def procesar_cuentas_pago(numero: str, mensaje: str, contexto: str, db: Session) -> Tuple[str, Optional[str]]:
    """
    Skill inteligente para responder de manera personalizada sobre las cuentas de pago
    oficiales de OPSATEL, adjuntando la imagen oficial y los datos para copiar.
    Retorna (texto_respuesta, ruta_imagen).
    """
    img_path = obtener_ruta_imagen_cuentas()

    cliente = None
    if db:
        try:
            cliente = obtener_cliente_sesion(numero, db, mensaje)
        except Exception as e_db:
            print(f"[SAM Chatbot] Aviso buscando cliente en BD para cuentas de pago: {e_db}")
            cliente = None

    if cliente and cliente.nombre:
        partes = [p.capitalize() for p in cliente.nombre.strip().split() if p]
        primer_nombre = partes[0] if partes else "Cliente"
        deuda = obtener_deuda_total_cliente(cliente)
        total_val = deuda["total"]
        desglose = deuda["desglose"]

        if total_val > 0:
            saludo = (
                f"¡Hola *{primer_nombre}*! Con mucho gusto te ayudo 😊\n"
                f"Tu valor total pendiente actual es de *${total_val:.2f}*{desglose} (Plan: *{cliente.plan or 'Contratado'}*).\n\n"
                f"Aquí tienes la imagen y los datos de nuestras cuentas bancarias oficiales de *OPSATEL* para que puedas realizar tu pago o transferencia:"
            )
        else:
            saludo = (
                f"¡Hola *{primer_nombre}*! Con mucho gusto te ayudo 😊\n"
                f"Te comento que te encuentras *al día con tus pagos* en OPSATEL 🎉\n\n"
                f"De igual manera, aquí tienes la imagen y los datos de nuestras cuentas bancarias oficiales por si deseas realizar algún abono o guardarlas:"
            )
    else:
        saludo = (
            "¡Hola! Con mucho gusto te comparto la información de pago 😊\n\n"
            "Aquí tienes la imagen y los datos de nuestras cuentas bancarias oficiales de *OPSATEL* para que puedas realizar tu pago o transferencia:"
        )

    texto_cuentas = (
        f"{saludo}\n\n"
        f"💳 *BANCO PICHINCHA*\n"
        f"• Tipo: Cuenta de Ahorros\n"
        f"• Número: `2209040900`\n"
        f"• Titular: Marco Andrés Solano Chalco\n"
        f"• C.I.: `0105905251`\n"
        f"• Correo: pagos@opsatel.net\n\n"
        f"🏦 *COOPERATIVA JEP*\n"
        f"• Tipo: Cuenta de Ahorros\n"
        f"• Número: `406180373200`\n"
        f"• Titular: Marco Andrés Solano Chalco\n"
        f"• C.I.: `0105905251`\n"
        f"• Correo: pagos@opsatel.net\n\n"
        f"📸 *IMPORTANTE*: Una vez realizada tu transferencia o depósito, por favor envíanos la foto o captura de tu comprobante por este mismo chat para registrar tu pago de inmediato. ¡Muchas gracias por preferirnos! ✨"
    )

    estados_skills[numero] = None
    return texto_cuentas, img_path


def procesar_recomendacion_peliculas(numero: str, mensaje: str, contexto: str) -> str:
    """Skill para dar recomendaciones dinámicas de películas o series para los usuarios de OPSATV."""
    try:
        from services.omdb_service import consultar_pelicula, formatear_para_whatsapp
        msg_lower = (mensaje or "").lower().strip()
        for trigger in ["de que trata", "de qué trata", "sinopsis de", "info de", "informacion de", "información de", "pelicula", "película", "serie"]:
            if trigger in msg_lower:
                candidato = msg_lower.replace(trigger, "").strip(" ?:!.,¿¡")
                if len(candidato) >= 3 and not any(g in candidato for g in ["accion", "acción", "comedia", "terror", "miedo", "drama", "suspenso", "recomienda", "recomendame"]):
                    data_omdb = consultar_pelicula(candidato)
                    if data_omdb.get("encontrado"):
                        return formatear_para_whatsapp(data_omdb)

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


def analizar_potencia_optica(potencia_str: str) -> dict:
    """
    Analiza la potencia óptica (dBm) según estándares de Opsatel:
    - Rango Óptimo: -16.0 a -25.0 dBm (Excelente señal de fibra)
    - Rango Límite: -25.01 a -27.0 dBm (Señal levemente atenuada)
    - Rango Crítico: peor a -27.0 dBm (< -27.0) o nula/desconectada
    """
    if not potencia_str:
        return {
            "valor": None,
            "estado": "critica",
            "descripcion": "Sin lectura de potencia registrada en el sistema",
            "es_optima": False,
            "es_critica": True
        }
    clean = re.sub(r'[^\d.-]', '', str(potencia_str).replace(',', '.')).strip()
    try:
        val = float(clean)
    except ValueError:
        return {
            "valor": None,
            "estado": "desconocida",
            "descripcion": f"Valor no numérico ({potencia_str})",
            "es_optima": False,
            "es_critica": False
        }

    if -25.0 <= val <= -16.0:
        return {
            "valor": val,
            "estado": "optima",
            "descripcion": f"{val:.2f} dBm (Señal óptica excelente y óptima)",
            "es_optima": True,
            "es_critica": False
        }
    elif -27.0 <= val < -25.0:
        return {
            "valor": val,
            "estado": "al_limite",
            "descripcion": f"{val:.2f} dBm (Señal en el límite permisible)",
            "es_optima": False,
            "es_critica": False
        }
    elif val < -27.0:
        return {
            "valor": val,
            "estado": "critica",
            "descripcion": f"{val:.2f} dBm (Potencia crítica fuera de rango)",
            "es_optima": False,
            "es_critica": True
        }
    else:  # val > -16.0
        return {
            "valor": val,
            "estado": "alta",
            "descripcion": f"{val:.2f} dBm (Potencia muy alta)",
            "es_optima": True,
            "es_critica": False
        }


def ejecutar_diagnostico_cliente(cliente, db: Session) -> dict:
    """
    Ejecuta el diagnóstico interno completo del cliente:
    1. Verificación de corte por falta de pago (BD y MikroTik Address List).
    2. Verificación de Potencia Óptica (-16 a -25 dBm óptima; peor a -27 dBm crítica).
    3. Prueba de Ping a través de MikroTik / red hacia cliente.ip.
    4. Determinación de gravedad (es_grave: True si potencia < -27 dBm o sin respuesta de ping).
    """
    resultado = {
        "cortado_por_pago": False,
        "motivo_corte": "",
        "potencia": {"valor": None, "estado": "desconocida", "es_optima": False, "es_critica": False, "descripcion": "Sin datos"},
        "ping": {"online": False, "packet_loss": 100, "avg_rtt": None, "detail": "Sin IP asignada"},
        "es_grave": False
    }
    if not cliente:
        return resultado

    # 1. Chequeo de corte por falta de pago en BD
    total_deuda = 0.0
    try:
        deuda_info = obtener_deuda_total_cliente(cliente)
        total_deuda = deuda_info.get("total", 0.0)
    except Exception:
        pass

    estado_cli = str(cliente.estado or "").strip().lower()
    if estado_cli in ["moroso", "suspendido"]:
        resultado["cortado_por_pago"] = True
        resultado["motivo_corte"] = f"Estado: {cliente.estado} (Saldo: ${total_deuda:.2f})"

    # 2. Análisis de Potencia Óptica de la última lectura guardada
    potencia_raw = getattr(cliente, "potencia", None) or getattr(cliente, "senal_optica", None)
    diag_pot = analizar_potencia_optica(str(potencia_raw) if potencia_raw else "")
    resultado["potencia"] = diag_pot

    # 3. Prueba de conectividad / Ping si tiene IP
    cliente_ip = str(getattr(cliente, "ip", "") or "").strip()
    if cliente_ip and re.match(r'^\d{1,3}(\.\d{1,3}){3}$', cliente_ip):
        try:
            import subprocess
            cmd = ["ping", "-c", "2", "-W", "2", cliente_ip]
            p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
            if p.returncode == 0:
                resultado["ping"] = {"online": True, "packet_loss": 0, "avg_rtt": "Normal", "detail": "Responde ping OK"}
            else:
                resultado["ping"] = {"online": False, "packet_loss": 100, "avg_rtt": None, "detail": "No responde a ping"}
        except Exception as e_ping:
            resultado["ping"] = {"online": False, "packet_loss": 100, "avg_rtt": None, "detail": f"Error probando ping: {e_ping}"}

    # 4. Clasificación de gravedad
    if diag_pot["es_critica"] or (not resultado["ping"]["online"] and not resultado["cortado_por_pago"]):
        resultado["es_grave"] = True

    return resultado


def notificar_alerta_tecnico_guardia(cliente, diagnostico: dict, mensaje_cliente: str, db: Session):
    """
    Envía reporte detallado de falla grave al WhatsApp del departamento técnico (098 880 4142)
    y crea la orden de trabajo en models.HojaRuta.
    SOLO se invoca si el caso es catalogado como GRAVE.
    """
    try:
        EC_TZ = pytz.timezone('America/Guayaquil')
        ahora = datetime.now(EC_TZ)
        fecha_hoy = ahora.strftime("%Y-%m-%d")
        hora_actual = ahora.strftime("%H:%M")

        nombre_c = cliente.nombre if cliente else "Cliente no registrado"
        ip_c = cliente.ip if cliente and cliente.ip else "N/A"
        nodo_c = cliente.nodo if cliente and cliente.nodo else "N/A"
        dir_c = cliente.direccion if cliente and cliente.direccion else "N/A"
        parroquia_c = cliente.parroquia if cliente and cliente.parroquia else "N/A"
        cel_c = cliente.celular if cliente and cliente.celular else "N/A"
        pot_desc = diagnostico.get("potencia", {}).get("descripcion", "N/A")
        ping_desc = diagnostico.get("ping", {}).get("detail", "N/A")

        # 1. Crear Orden en Hoja de Ruta
        ticket = models.HojaRuta(
            fecha=fecha_hoy,
            tecnico="Por Asignar",
            hora=hora_actual,
            cliente_id=cliente.id if cliente else None,
            nombre_cliente=nombre_c,
            ubicacion_cliente=f"{dir_c} (Sector/Nodo: {nodo_c})".strip(),
            celular_cliente=cel_c,
            actividad="SOPORTE TÉCNICO - FALLA CRÍTICA DETECTADA POR SAM",
            observacion=f"Potencia: {pot_desc} | Ping: {ping_desc} | Mensaje cliente: {mensaje_cliente}",
            parroquia=parroquia_c,
            estado="Pendiente"
        )
        db.add(ticket)
        db.commit()
        db.refresh(ticket)

        # 2. Notificar por WhatsApp al Técnico de Guardia
        mensaje_tecnico = (
            f"🚨 *[ALERTA DE SOPORTE TÉCNICO CRÍTICO — SAM]* 🚨\n\n"
            f"🎫 *Ticket Hoja de Ruta*: #{ticket.id}\n"
            f"👤 *Cliente*: {nombre_c}\n"
            f"📱 *Teléfono*: {cel_c}\n"
            f"📍 *Sector / Nodo*: {nodo_c} ({parroquia_c})\n"
            f"🏠 *Dirección*: {dir_c}\n"
            f"🌐 *IP Asignada*: {ip_c}\n\n"
            f"⚠️ *Diagnóstico en Tiempo Real:*\n"
            f"• Potencia Óptica: {pot_desc}\n"
            f"• Estado Ping: {ping_desc}\n"
            f"• Mensaje del Cliente: \"{mensaje_cliente}\"\n\n"
            f"🕒 *Fecha/Hora*: {fecha_hoy} {hora_actual}\n"
            f"_Orden agendada automáticamente en Hoja de Ruta para atención prioritaria._"
        )

        try:
            from routes.whatsapp import WhatsAppWebhookPayload
            import requests
            puerto_bridge = os.getenv("WHATSAPP_PORT", "3001")
            url_bridge = f"http://localhost:{puerto_bridge}/send"
            requests.post(url_bridge, json={"number": NUMERO_TECNICO_GUARDIA, "message": mensaje_tecnico}, timeout=5)
            print(f"[SAM Chatbot] 🚨 Alerta de falla crítica enviada con éxito al técnico de guardia ({NUMERO_TECNICO_GUARDIA}).")
        except Exception as e_send:
            print(f"[SAM Chatbot] Aviso enviando mensaje WhatsApp al técnico de guardia: {e_send}")

    except Exception as e:
        print(f"[SAM Chatbot] Error notificando alerta a técnico de guardia: {e}")
        db.rollback()


def procesar_soporte_tecnico(numero: str, mensaje: str, contexto: str, db: Session) -> str:
    """Procesa solicitudes de soporte técnico, diagnostica en tiempo real y notifica a técnicos de guardia si es crítico."""
    cliente = obtener_cliente_sesion(numero, db, mensaje)
    diag = ejecutar_diagnostico_cliente(cliente, db)

    msg_lower = mensaje.lower()
    palabras_persistencia = [
        "sigue", "persiste", "no vale", "no funciona", "no sirvió", "no sirvio",
        "continúa", "continua", "sigue igual", "sigue lento", "sigue la falla",
        "ya reinicié", "ya reinicie", "sigue sin valer"
    ]
    falla_persiste_tras_prueba = any(p in msg_lower for p in palabras_persistencia) and len(contexto.split("\n")) >= 3

    if diag["es_grave"] or falla_persiste_tras_prueba:
        notificar_alerta_tecnico_guardia(cliente, diag, mensaje, db)

    nombre_limpio = " ".join((cliente.nombre or "").strip().split()) if cliente else ""
    primer_nombre = nombre_limpio.split()[0].capitalize() if nombre_limpio else "estimado cliente"

    info_diagnostico_ia = f"""
DATOS CONFIDENCIALES DEL CLIENTE (SOLO PARA TU ANÁLISIS INTERNO):
- Cliente identificado: {"Sí (" + cliente.nombre + ")" if cliente else "No identificado (pedir nombre o cédula si se requiere)"}
- Primer nombre: {primer_nombre}
- Sector/Nodo: {cliente.nodo if cliente else 'N/A'}
- ¿Presenta corte por pago pendiente?: {"SÍ (" + diag["motivo_corte"] + ")" if diag["cortado_por_pago"] else "NO"}
- Estado de fibra óptica: {"ÓPTIMA (Potencia excelente entre -16 y -25 dBm)" if diag["potencia"]["es_optima"] else ("CRÍTICA (Potencia peor a -27 dBm o sin señal)" if diag["potencia"]["es_critica"] else "Aceptable")}
- Estado del equipo en red: {"EN LÍNEA Y RESPONDE" if diag["ping"]["online"] else "NO RESPONDE PING (Apagado o desconectado)"}
"""

    prompt_soporte = f"""{PROMPT_SOPORTE_TECNICO}
{info_diagnostico_ia}

HISTORIAL DE CONVERSACIÓN:
{contexto}

MENSAJE DEL CLIENTE: "{mensaje}"

INSTRUCCIONES CLAVE DE RESPUESTA:
- Si el cliente tiene CORTE POR PAGO: Indícale con delicadeza que su servicio presenta suspensión administrativa por saldo pendiente y pregúntale si desea las cuentas bancarias. No le hagas reiniciar equipos.
- Si el cliente tiene FALLA CRÍTICA o persistente (luz roja / sin señal / cable roto): Dile con tranquilidad que ya registraste su reporte de urgencia y alertaste al equipo técnico de guardia para su revisión.
- Si parece un problema menor o de lentitud puntual y no ha reiniciado: Sugiérele de forma amable y concisa reiniciar el router desconectándolo 15 segundos.
- Mensaje corto, cálido y profesional (máximo 2 a 3 líneas).
"""

    try:
        return generar_respuesta_ia(prompt_soporte, max_tokens=220, temperature=0.3)
    except Exception as e_ia:
        print(f"[SAM Chatbot] Error en IA de soporte técnico: {e_ia}")
        if diag["cortado_por_pago"]:
            return f"¡Hola {primer_nombre}! Veo en el sistema que tu servicio presenta una suspensión temporal por un valor pendiente. ¿Deseas que te facilite nuestras cuentas bancarias para reactivarlo de inmediato? 😊"
        elif diag["es_grave"]:
            return f"¡Hola {primer_nombre}! He detectado una interrupción en tu enlace de fibra óptica y ya notifiqué con prioridad a nuestro equipo técnico de guardia para revisarlo a la brevedad 🛠️"
        else:
            return f"¡Hola {primer_nombre}! Para ayudarte a restablecer tu conexión, por favor desconecta tu router de la corriente eléctrica durante 15 segundos y vuelve a conectarlo. Avísame si la luz se normaliza 😊"


def procesar_chat_general(numero: str, mensaje: str, contexto: str, db: Session = None) -> str:
    """Skill para manejar consultas generales, planes de internet, bancos y bienvenida a prospectos."""
    info_bd = []
    nombre_cliente = None
    primer_nombre = ""
    fecha_hora_ec = obtener_fecha_hora_ecuador()

    if db:
        try:
            cliente = obtener_cliente_sesion(numero, db, mensaje)
            if cliente and cliente.nombre:
                nombre_cliente = cliente.nombre
                partes = [p.capitalize() for p in cliente.nombre.strip().split() if p]
                primer_nombre = partes[0] if partes else ""
                deuda = obtener_deuda_total_cliente(cliente)
                info_bd.append(
                    f"DATOS DEL CLIENTE REGISTRADO QUE TE ESCRIBE:\n"
                    f"- Nombre del cliente: {cliente.nombre} (Tratarlo como: {primer_nombre})\n"
                    f"- Plan actual contratado: {cliente.plan or 'No definido'}\n"
                    f"- Valor total pendiente a pagar: ${deuda['total']:.2f}{deuda['desglose']}\n"
                    f"- Estado actual del servicio: {cliente.estado}"
                )
            else:
                info_bd.append("ESTADO DEL REMITENTE: Prospecto o nuevo cliente (Aún no registrado en la BD). Trátalo con máxima cordialidad y dale la bienvenida a OPSATEL.")

            planes = db.query(models.PlanInternet).all()
            if planes:
                lista_planes = []
                for p in planes:
                    linea = f"• *{p.nombre}*: {p.megas} Megas por ${float(p.precio):.2f} al mes"
                    if p.pantallas:
                        linea += f" ({p.pantallas} pantalla(s) de TV/IPTV)"
                    lista_planes.append(linea)
                info_bd.append("PLANES DE INTERNET VIGENTES EN OPSATEL (Datos oficiales de la base de datos):\n" + "\n".join(lista_planes))

            bancos = db.query(models.Banco).all()
            if bancos:
                nombres_bancos = [b.nombre for b in bancos if b.nombre]
                if nombres_bancos:
                    info_bd.append("BANCOS AUTORIZADOS PARA PAGOS Y TRANSFERENCIAS:\n" + ", ".join(nombres_bancos))

        except Exception as e_bd:
            print(f"[SAM Chatbot] Error cargando contexto de BD para chat general: {e_bd}")

    bloque_bd = ("\n\nINFORMACIÓN OFICIAL DE OPSATEL:\n" + "\n\n".join(info_bd)) if info_bd else ""

    system_prompt = f"""{PROMPT_GENERAL}
FECHA Y HORA ACTUAL EN ECUADOR: {fecha_hora_ec}
{bloque_bd}
"""

    prompt_usuario = f"""Conversación previa con el cliente:
{contexto}

Mensaje actual del cliente: "{mensaje}"

Instrucción: Responde al cliente de forma CORTA, HUMANA Y AGRADABLE (máximo 1 a 3 líneas). Responde con precisión a lo consultado sin textos innecesarios ni preguntas redundantes."""

    try:
        return generar_respuesta_ia(prompt_usuario, max_tokens=220, temperature=0.3, system_prompt=system_prompt)
    except Exception as e:
        print(f"[SAM Chatbot] Error en chat general: {e}")
        if primer_nombre:
            return f"¡Hola {primer_nombre}! Con gusto te ayudo hoy 😊 ¿En qué te puedo colaborar con tus servicios de OPSATEL?"
        return "¡Hola! Bienvenido a OPSATEL, con gusto te ayudo hoy 😊 ¿En qué te puedo colaborar?"
