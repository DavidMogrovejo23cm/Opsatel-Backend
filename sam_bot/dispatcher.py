"""
Módulo dispatcher principal para SAM Chatbot.
Recibe, clasifica, despacha y responde mensajes entrantes de WhatsApp.
"""
from sqlalchemy.orm import Session
import whatsapp_service

from .session_manager import (
    limpiar_numero_whatsapp,
    limpiar_sesion_si_expirada,
    esta_bot_pausado_por_operador,
    guardar_mensaje_historial,
    obtener_contexto_conversacion,
    estados_skills,
    historial_conversaciones,
    clientes_identificados_sesion,
)
from .client_lookup import extraer_identificador_cliente
from .admin_commands import es_numero_administrador, procesar_comando_administrador
from .skills import (
    clasificar_intencion,
    es_solicitud_cuentas_pago,
    procesar_cuentas_pago,
    procesar_registro_cliente,
    procesar_consulta_pago,
    procesar_recomendacion_peliculas,
    procesar_chat_general,
    obtener_ruta_imagen_cuentas,
)


def procesar_mensaje_entrante(numero: str, mensaje: str, db: Session, nombre_remitente: str = "", jid_original: str = "", telefono_real: str = "") -> str:
    """
    Punto de entrada principal para el chatbot SAM.
    Recibe el número telefónico o JID del remitente y el contenido del mensaje.
    Procesa según la intención detectada y devuelve la respuesta generada sin atascarse.
    """
    numero = limpiar_numero_whatsapp(numero)

    # 0. Limpiar sesión si expiró el tiempo de inactividad (TTL)
    limpiar_sesion_si_expirada(numero)

    # 0.0 Descartar en silencio eventos o notificaciones internas del protocolo de WhatsApp
    if mensaje.startswith("[NON_TEXT_MSG]"):
        tipo_recibido = mensaje.replace("[NON_TEXT_MSG]", "").strip().lower()
        tipos_ignorar = {
            "e2e_notification", "notification_template", "protocol", "ciphertext",
            "broadcast_notification", "call_log", "gp2", "notification", "revoked", "status"
        }
        if tipo_recibido in tipos_ignorar or any(t in tipo_recibido for t in ["notification", "protocol", "cipher"]):
            print(f"[SAM Chatbot] [SILENCIO] Evento/protocolo interno de WhatsApp descartado ({tipo_recibido}) de {numero}")
            return ""

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

    # 1. Manejo de comprobantes y mensajes no soportados
    if mensaje.startswith("🧾 [Comprobante"):
        return ""

    if mensaje.startswith("[NON_TEXT_MSG]"):
        response_text = "Hola, soy SAM de Opsatel 😊 Por el momento solo puedo leer mensajes de texto. Por favor, escríbeme tu consulta en texto y con gusto te ayudo."
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
        clientes_identificados_sesion.pop(numero, None)
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
        if intencion_detectada == "general":
            skill_activo = "general"
            estados_skills[numero] = None
        elif intencion_detectada != skill_previo:
            print(f"[SAM Chatbot] 🔄 Desenganche de tema: Cambiando de '{skill_previo}' a '{intencion_detectada}'")
            skill_activo = intencion_detectada
            estados_skills[numero] = None
        elif skill_previo == "consultar_pagos_y_saldos":
            if extraer_identificador_cliente(mensaje):
                skill_activo = "consultar_pagos_y_saldos"
                ya_solicitado = True
            else:
                skill_activo = "general"
                estados_skills[numero] = None
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
    media_a_enviar = None

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
    elif skill_activo == "solicitar_cuentas_pago":
        estados_skills[numero] = None
        response_text, media_a_enviar = procesar_cuentas_pago(numero, mensaje, contexto, db)
    elif skill_activo == "registrar_cliente_potencial":
        estados_skills[numero] = "registrar_cliente_potencial"
        response_text = procesar_registro_cliente(numero, mensaje, contexto, db)
    elif skill_activo == "consultar_pagos_y_saldos":
        if es_solicitud_cuentas_pago(mensaje):
            media_a_enviar = obtener_ruta_imagen_cuentas()
        response_text = procesar_consulta_pago(numero, mensaje, contexto, db, ya_solicitado)
    elif skill_activo == "recomendacion_peliculas_opsatv":
        estados_skills[numero] = None
        response_text = procesar_recomendacion_peliculas(numero, mensaje, contexto)
    elif skill_activo == "soporte_tecnico_foco_rojo":
        estados_skills[numero] = None
        from chatbot_service import procesar_mensaje_con_herramientas, resolver_identidad_whatsapp
        identidad = resolver_identidad_whatsapp(numero, jid_original=jid_original)
        historial_rec = historial_conversaciones.get(numero, [])
        response_text = procesar_mensaje_con_herramientas(
            mensaje=mensaje,
            numero=identidad["telefono_limpio"],
            db=db,
            historial_mensajes=historial_rec,
            metadata_identidad=identidad["metadata_ia"]
        )
    elif admin_obj and msg_limpio in ["menu", "menú", "admin", "comandos", "panel"]:
        estados_skills[numero] = None
        response_text = procesar_comando_administrador(numero, mensaje, contexto, db, admin_obj)
    else:
        estados_skills[numero] = None
        if es_solicitud_cuentas_pago(mensaje):
            media_a_enviar = obtener_ruta_imagen_cuentas()
        response_text = procesar_chat_general(numero, mensaje, contexto, db)

    # 8. Guardar la respuesta generada en el historial
    guardar_mensaje_historial(numero, "assistant", response_text)
    try:
        from routes.whatsapp import registrar_mensaje_chat
        tipo_msg = "multimedia" if media_a_enviar else "texto"
        registrar_mensaje_chat(db, numero, "asistente", response_text, tipo=tipo_msg)
    except Exception as e_chat:
        print(f"[SAM Chatbot] Error registrando respuesta SAM: {e_chat}")
    
    # 9. Despachar el mensaje por WhatsApp usando el servicio unificado
    whatsapp_service.send_whatsapp_message(numero, response_text, media_path=media_a_enviar)
    
    return response_text
