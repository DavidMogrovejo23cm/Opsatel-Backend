"""
Módulo de verificación y atención de comandos de administradores en SAM Chatbot.
"""
import re
import json
from typing import Optional
from sqlalchemy.orm import Session
from rapidfuzz import fuzz
import pytz
from datetime import datetime

import models
from .session_manager import estados_skills, historial_conversaciones
from .llm_client import generar_respuesta_ia
from .client_lookup import buscar_cliente_por_celular, normalizar_texto_busqueda


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
    Revisa y valida los datos, resuelve el plan por nombre, megas o precio,
    crea el Cliente y genera la orden en Hoja de Ruta.
    """
    from ai_tools import crear_orden_instalacion_hoja_ruta

    msg_clean = mensaje.strip()
    msg_lower = msg_clean.lower()

    # 1. Comprobar si el mensaje es solo una solicitud/intención de registrar instalación sin datos del cliente
    intenciones_solo = [
        "nueva instalacion", "nueva instalación", "registrar instalacion", "registrar instalación",
        "ingresar instalacion", "ingresar instalación", "alta", "alta de cliente", "nuevo cliente",
        "registrar cliente", "quiero registrar una instalacion", "quiero ingresar una instalacion",
        "instalacion", "instalación"
    ]
    es_solo_intencion = (
        len(msg_clean.split()) <= 4 and any(intent in msg_lower for intent in intenciones_solo)
    ) or (
        msg_lower in intenciones_solo
    )

    if es_solo_intencion:
        estados_skills[numero] = "alta_instalacion_admin"
        return (
            f"👑 *¡Hola {admin_obj.nombre}! Modo Alta de Instalación Activo.* 🛠️\n\n"
            f"Para ingresar al nuevo cliente y agendar su orden en la *Hoja de Ruta*, por favor facilítame los datos:\n\n"
            f"• 👤 *Nombre del cliente*:\n"
            f"• 📱 *Celular de contacto*:\n"
            f"• 📍 *Dirección y Sector / Nodo*:\n"
            f"• 📦 *Plan*: (Puedes indicarlo por *nombre*, *megas* o *precio*. Ej: *100 megas*, *$20*, *LAG CERO*)\n"
            f"• 🆔 *Cédula*: (Opcional)\n\n"
            f"_Envíame los datos en un solo mensaje o como te resulte más cómodo y yo lo agendo de inmediato._ 😊"
        )

    # 2. Extraer datos con IA a partir del mensaje y contexto previo
    valid_nodos = [n[0] for n in db.query(models.Nodo.nombre).filter(models.Nodo.nombre != None).all()]
    valid_planes = [
        f"{pl.nombre} ({pl.megas} Mbps - ${float(pl.precio or 0):.2f})"
        for pl in db.query(models.PlanInternet).all()
    ]

    prompt_admin = f"""# Skill: Extracción de Datos de Instalación para Administrador: {admin_obj.nombre}
Un administrador de Opsatel está enviando los datos para dar de alta una nueva instalación en la Hoja de Ruta.
Tu objetivo es EXTRAER y estructurar los datos disponibles en un JSON limpio de una sola línea.

Campos:
* nombre: Nombre y apellido del cliente.
* celular: Teléfono celular del cliente.
* direccion: Dirección domiciliaria y referencias.
* plan: Plan solicitado. Puede decirse por nombre (ej: LAG CERO), velocidad (ej: 100 megas, 150 Mbps) o precio (ej: $17.50, 20 dólares, 20).
* nodo: Sector, barrio o nodo de red (ej: Banos, Sayausí, Centro, Misicata).
* parroquia: Parroquia (opcional).
* cedula: Cédula o RUC (10 o 13 dígitos, opcional).
* comentarios: Observaciones adicionales o promociones.

CATÁLOGO DE PLANES VIGENTES: {json.dumps(valid_planes, ensure_ascii=False)}
NODOS / SECTORES: {json.dumps(valid_nodos, ensure_ascii=False)}

Responde ÚNICAMENTE con el JSON en este formato:
{{"nombre": "", "celular": "", "direccion": "", "plan": "", "nodo": "", "parroquia": "", "cedula": "", "comentarios": ""}}
"""
    try:
        texto_analizar = f"Mensaje actual del Administrador:\n{mensaje}"
        if contexto and len(contexto.strip()) > 10:
            texto_analizar = f"Historial previo:\n{contexto}\n\n{texto_analizar}"

        res_text = generar_respuesta_ia(f"{prompt_admin}\n\n{texto_analizar}", max_tokens=600, temperature=0.1)

        json_match = re.search(r'\{.*"nombre".*\}', res_text)
        datos = {}
        if json_match:
            try:
                datos = json.loads(json_match.group(0))
            except Exception:
                pass

        if not datos:
            datos = {}
        if not datos.get("nombre"):
            datos["nombre"] = ""
        if not datos.get("celular"):
            datos["celular"] = ""
        if not datos.get("direccion"):
            datos["direccion"] = ""
        if not datos.get("plan"):
            datos["plan"] = ""

        # 3. Validar y crear en la base de datos y Hoja de Ruta
        resultado = crear_orden_instalacion_hoja_ruta(datos, db, registrado_por=admin_obj.nombre)

        if resultado.get("success"):
            estados_skills[numero] = None
            if numero in historial_conversaciones:
                historial_conversaciones[numero] = []

            return (
                f"👑 *[Modo Administrador — {admin_obj.nombre}]*\n\n"
                f"✅ *¡Instalación registrada y agendada en la Hoja de Ruta exitosamente!* 🛠️\n\n"
                f"🎫 *Orden Hoja de Ruta*: #{resultado['hoja_ruta_id']}\n"
                f"👤 *Cliente #{resultado['cliente_id']}*: {resultado['nombre_cliente']}\n"
                f"🆔 *Cédula*: {resultado.get('cedula') or 'No especificada'}\n"
                f"📱 *Celular*: {resultado.get('celular') or 'No especificado'}\n"
                f"📍 *Ubicación / Sector*: {resultado.get('direccion')} ({resultado.get('nodo') or 'N/A'})\n"
                f"📦 *Plan Asignado*: {resultado.get('detalles_plan')}\n"
                f"📅 *Fecha*: {resultado.get('fecha')} ({resultado.get('hora')})\n"
                f"🛠️ *Estado*: Pendiente de asignación técnica\n\n"
                f"_La orden ya está disponible en la pestaña 'Hoja de Ruta' del panel de Opsatel._"
            )
        else:
            # Mantiene el skill activo para que el admin pueda enviar el dato faltante
            estados_skills[numero] = "alta_instalacion_admin"
            error_msg = resultado.get("error", "Faltan datos del cliente.")
            return (
                f"👑 *Hola {admin_obj.nombre}*, para poder agendar la instalación en la *Hoja de Ruta* por favor revisa los datos:\n"
                f"⚠️ *{error_msg}*\n\n"
                f"Por favor indícame ese dato para completar el registro de inmediato."
            )

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

    elif estados_skills.get(numero) == "alta_instalacion_admin" or any(w in msg_lower for w in [
        "instalacion", "instalación", "nuevo cliente", "ingresar cliente", "registrar cliente", "registrar", "alta"
    ]):
        return procesar_registro_cliente_admin_directo(numero, mensaje, contexto, db, admin_obj)
        
    return (
        f"👑 *¡Hola {admin_obj.nombre}!* Reconozco tu perfil de Administrador en Opsatel.\n\n"
        f"Como tu número está registrado en el *apartado de Administradores*, tienes acceso prioritario a tus funciones exclusivas de gestión:\n"
        f"• 💰 *'Resumen de caja'* (recaudación y pagos del día)\n"
        f"• ⚠️ *'Reporte de morosos'* (clientes suspendidos o en corte)\n"
        f"• 🛠️ *Datos de instalación* (ej: *INSTALACION BANOS ...* para registrarla y pasarla directo a la Hoja de Ruta)\n\n"
        f"💡 _Nota: Como también eres cliente de Opsatel, si deseas consultar tu propio saldo personal solo pregúntame '¿cuánto debo?' o solicita soporte técnico cuando lo requieras._ 😊\n\n"
        f"¿En qué te colaboro hoy?"
    )
