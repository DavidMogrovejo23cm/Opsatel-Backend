import os
import re
import time
import traceback
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
import whatsapp_service
from database import get_db
from .schemas import WhatsAppWebhookPayload
from .utils import (
    ECUADOR_TZ,
    _ultimos_comprobantes_respondidos,
    obtener_info_contacto_bridge,
    registrar_mensaje_chat
)
from .comprobantes import asegurar_tabla_comprobantes, evaluar_validacion_comprobante

router = APIRouter()


@router.post("/webhook-mensaje")
def webhook_mensaje_whatsapp(
    payload: WhatsAppWebhookPayload,
    db: Session = Depends(get_db)
):
    """
    Webhook principal que recibe mensajes entrantes de WhatsApp desde el puente local (Node.js).
    Orquestado al 100% por IA (Groq Tool Calling), con resolución de identificadores LID y
    desactivación total del 'Skill Router' obsoleto para evitar tickets vacíos.
    """
    try:
        import sam_bot_service
        from chatbot_service import procesar_mensaje_con_herramientas, resolver_identidad_whatsapp

        mensaje = (payload.mensaje or "").strip()
        if not mensaje:
            return {"success": True, "response": ""}

        # 1. Descartar eventos o notificaciones internas del protocolo de WhatsApp
        if mensaje.startswith("[NON_TEXT_MSG]"):
            tipo_rec = mensaje.replace("[NON_TEXT_MSG]", "").strip().lower()
            if any(t in tipo_rec for t in ["notification", "protocol", "cipher", "call", "broadcast", "status"]):
                return {"success": True, "response": ""}

        # 2. Resolución de Identidad: detecta si es un @lid o número celular real
        identidad = resolver_identidad_whatsapp(
            numero_raw=payload.numero,
            jid_original=payload.jid_original or ""
        )
        jid_destino = identidad["jid_destino"]
        tel_real = identidad["telefono_limpio"]

        # Si aún no tenemos tel_real y el remitente es un LID, intentar resolverlo mediante el bridge o BD
        if not tel_real and (identidad["es_lid"] or "@lid" in str(jid_destino).lower()):
            info_contacto = obtener_info_contacto_bridge(jid_destino)
            if info_contacto and info_contacto.get("number"):
                num_c = re.sub(r'\D', '', str(info_contacto["number"]))
                if 8 <= len(num_c) <= 13:
                    tel_real = num_c

            if not tel_real:
                prev_chat = db.query(models.WhatsAppMensajeChat).filter(
                    models.WhatsAppMensajeChat.numero == jid_destino,
                    models.WhatsAppMensajeChat.cliente_id.isnot(None)
                ).order_by(models.WhatsAppMensajeChat.id.desc()).first()
                if prev_chat and prev_chat.cliente_id:
                    c_asoc = db.query(models.Cliente).filter(models.Cliente.id == prev_chat.cliente_id).first()
                    if c_asoc and c_asoc.celular:
                        tel_real = re.sub(r'\D', '', str(c_asoc.celular))

            if tel_real:
                identidad["es_lid"] = False
                identidad["telefono_limpio"] = tel_real
                identidad["metadata_ia"] = (
                    f"El cliente escribe desde el número celular registrado '{tel_real}'. "
                    f"Tu PRIMERA ACCIÓN OBLIGATORIA ante cualquier consulta, saludo o reclamo es ejecutar "
                    f"'consultar_estado_cliente(identificador='{tel_real}')' para verificar su contrato, saldo y servicio. "
                    "Si la herramienta encuentra sus datos, trátalo con calidez por su primer nombre y "
                    "NO LE PIDAS CÉDULA NI TELÉFONO. "
                    "REGLA CRÍTICA: Si el usuario únicamente saluda ('hola', 'buenas'), responde exclusivamente con un saludo cálido y pregunta amablemente en qué le colaboras hoy. "
                    "PROHIBIDO cobrarle, mencionarle moras, saldos o enviarle cuentas bancarias en un simple saludo."
                )

        # C. Comprobar si el cliente ya fue identificado en la sesión o si proporcionó cédula/celular en el mensaje
        cand_id = sam_bot_service.extraer_identificador_cliente(mensaje)
        c_por_msg = None
        if cand_id:
            c_por_msg = sam_bot_service.buscar_cliente_por_cedula_o_celular(cand_id, db)
        elif sam_bot_service.clientes_identificados_sesion.get(jid_destino):
            c_id = sam_bot_service.clientes_identificados_sesion[jid_destino]
            c_por_msg = db.query(models.Cliente).filter(models.Cliente.id == c_id).first()
        elif payload.numero and sam_bot_service.clientes_identificados_sesion.get(payload.numero):
            c_id = sam_bot_service.clientes_identificados_sesion[payload.numero]
            c_por_msg = db.query(models.Cliente).filter(models.Cliente.id == c_id).first()
        elif tel_real and sam_bot_service.clientes_identificados_sesion.get(tel_real):
            c_id = sam_bot_service.clientes_identificados_sesion[tel_real]
            c_por_msg = db.query(models.Cliente).filter(models.Cliente.id == c_id).first()

        # D. Si aún no está en memoria de sesión, consultar en MySQL si este chat ya tiene un cliente_id vinculado históricamente
        if not c_por_msg:
            nums_hist_cliente = [jid_destino]
            if tel_real:
                nums_hist_cliente.extend([tel_real, f"{tel_real}@c.us"])
            if payload.numero and payload.numero not in nums_hist_cliente:
                nums_hist_cliente.append(payload.numero)

            prev_chat_con_cid = db.query(models.WhatsAppMensajeChat.cliente_id).filter(
                models.WhatsAppMensajeChat.numero.in_(nums_hist_cliente),
                models.WhatsAppMensajeChat.cliente_id.isnot(None)
            ).order_by(models.WhatsAppMensajeChat.id.desc()).first()

            if prev_chat_con_cid and prev_chat_con_cid[0]:
                c_por_msg = db.query(models.Cliente).filter(models.Cliente.id == prev_chat_con_cid[0]).first()

        # E. Si aún no se encontró y tenemos tel_real, buscar directamente en BD por celular
        if not c_por_msg and tel_real:
            c_por_msg = sam_bot_service.buscar_cliente_por_celular(tel_real, db)

        if c_por_msg:
            sam_bot_service.clientes_identificados_sesion[jid_destino] = c_por_msg.id
            if payload.numero:
                sam_bot_service.clientes_identificados_sesion[payload.numero] = c_por_msg.id
            if tel_real:
                sam_bot_service.clientes_identificados_sesion[tel_real] = c_por_msg.id
            deuda_c = sam_bot_service.obtener_deuda_total_cliente(c_por_msg)
            identidad["metadata_ia"] = (
                f"El cliente ha sido identificado exitosamente en la base de datos como '{c_por_msg.nombre}' "
                f"(Cédula: {c_por_msg.cedula}, Celular registrado: {c_por_msg.celular}, Plan: {c_por_msg.plan or 'Internet'}, "
                f"Total pendiente: ${deuda_c['total']:.2f}{deuda_c['desglose']}). "
                f"Dirígete a él cordialmente por su primer nombre y responde directamente a su solicitud sin volver a pedirle cédula ni celular."
            )

        # 3. Verificar si el bot está en pausa por intervención de un operador humano
        if sam_bot_service.esta_bot_pausado_por_operador(jid_destino) or (payload.numero and sam_bot_service.esta_bot_pausado_por_operador(payload.numero)):
            registrar_mensaje_chat(db, jid_destino, "cliente", mensaje, cliente_id=c_por_msg.id if c_por_msg else None, nombre_remitente=payload.nombre or "")
            return {"success": True, "response": "", "pausado": True}

        # 4. Obtener historial previo de conversación
        numeros_filtro = [jid_destino]
        if tel_real:
            numeros_filtro.extend([tel_real, f"{tel_real}@c.us"])
        if payload.numero and payload.numero not in numeros_filtro:
            numeros_filtro.append(payload.numero)

        msgs_previos_db = db.query(models.WhatsAppMensajeChat).filter(
            models.WhatsAppMensajeChat.numero.in_(numeros_filtro)
        ).order_by(models.WhatsAppMensajeChat.id.desc()).limit(12).all()

        if msgs_previos_db:
            historial_previo = []
            for m in reversed(msgs_previos_db):
                rol_formato = "user" if m.rol == "cliente" else "assistant"
                historial_previo.append({"role": rol_formato, "content": m.mensaje})
        else:
            historial_previo = list(sam_bot_service.historial_conversaciones.get(jid_destino, []))

        # 4.0 DESCARTE INMEDIATO DE IMÁGENES NO VÁLIDAS (NO COMPROBANTES)
        es_imagen_invalida = bool(
            payload.es_documento_valido is False or
            payload.es_invalido is True or
            "[Imagen descartada" in mensaje or
            "[Imagen no válida]" in mensaje or
            "[Imagen recibida - Documento no válido]" in mensaje or
            "no es un comprobante válido" in mensaje.lower() or
            "la imagen mandada no es un documento valido" in mensaje.lower()
        )
        if es_imagen_invalida:
            resp_invalido = "La imagen enviada no es un documento válido. Por favor, envía un comprobante de pago o transferencia bancaria válido."
            url_img = payload.url_archivo or ""
            if not url_img:
                m_url = re.search(r'(?:https?://[^\s]+)?(/uploadscr/[a-zA-Z0-9_\-\.\/]+)', mensaje)
                if m_url:
                    url_img = m_url.group(1)

            msg_chat_user = f"📷 [Imagen recibida - No es un comprobante válido] {url_img}".strip()
            registrar_mensaje_chat(
                db, jid_destino, "cliente", msg_chat_user,
                cliente_id=c_por_msg.id if c_por_msg else None,
                tipo="multimedia",
                nombre_remitente=payload.nombre or ""
            )
            registrar_mensaje_chat(
                db, jid_destino, "asistente", resp_invalido,
                cliente_id=c_por_msg.id if c_por_msg else None
            )
            sam_bot_service.guardar_mensaje_historial(jid_destino, "user", msg_chat_user)
            sam_bot_service.guardar_mensaje_historial(jid_destino, "assistant", resp_invalido)

            if not payload.ya_notificado_cliente:
                try:
                    whatsapp_service.send_whatsapp_message(jid_destino, resp_invalido)
                except Exception as e_send_inv:
                    print(f"[WhatsApp] Aviso al enviar rechazo de documento inválido: {e_send_inv}")

            return {"success": False, "response": resp_invalido, "comprobante": False}

        # 4.1 DETECCIÓN Y PROCESAMIENTO GARANTIZADO DE COMPROBANTES / IMÁGENES
        es_comprobante = bool(
            payload.url_archivo or
            "uploadscr" in mensaje or
            mensaje.startswith("🧾 [Comprobante") or
            mensaje.startswith("[NON_TEXT_MSG] image") or
            mensaje.strip() == "[NON_TEXT_MSG] image" or
            (payload.mimetype and str(payload.mimetype).startswith("image/"))
        )

        if es_comprobante:
            asegurar_tabla_comprobantes(db)

            url_final = payload.url_archivo
            if not url_final:
                m_url = re.search(r'(?:https?://[^\s]+)?(/uploadscr/[a-zA-Z0-9_\-\.\/]+)', mensaje)
                if m_url:
                    url_final = m_url.group(1)

            nombre_archivo = payload.nombre_archivo or (os.path.basename(url_final) if url_final else None)

            backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            candidatos_dir = [
                os.path.join(backend_dir, "uploadscr"),
                os.path.join(backend_dir, "uploads", "uploadscr"),
                os.path.join(backend_dir, "..", "Opsatel-Frontend", "uploadscr"),
                os.path.join(backend_dir, "..", "Opsatel-Frontend", "public", "uploadscr"),
                os.path.join(backend_dir, "..", "Opsatel-Frontend", "dist", "uploadscr"),
            ]
            if not url_final or not nombre_archivo:
                arch_reciente = None
                for c_dir in candidatos_dir:
                    if os.path.exists(c_dir):
                        try:
                            archivos = [os.path.join(c_dir, f) for f in os.listdir(c_dir) if os.path.isfile(os.path.join(c_dir, f))]
                            if archivos:
                                mas_nuevo = max(archivos, key=os.path.getmtime)
                                if (datetime.now().timestamp() - os.path.getmtime(mas_nuevo)) < 300:
                                    arch_reciente = os.path.basename(mas_nuevo)
                                    break
                        except Exception:
                            pass

                if arch_reciente:
                    nombre_archivo = arch_reciente
                    url_final = f"/uploadscr/{arch_reciente}"
                else:
                    ts_now = int(datetime.utcnow().timestamp())
                    t_dig = (tel_real or jid_destino).replace("@c.us", "").replace("@lid", "")
                    nombre_archivo = f"comp_{ts_now}_{t_dig}.jpg"
                    url_final = f"/uploadscr/{nombre_archivo}"

            ruta_archivo = payload.ruta_archivo or f"uploadscr/{nombre_archivo}"
            mimetype = payload.mimetype or "image/jpeg"
            tamano_bytes = payload.tamano_bytes or 0

            from services.ocr_comprobantes import analizar_comprobante_ocr
            ocr_verif = {}
            try:
                ocr_verif = analizar_comprobante_ocr(ruta_archivo or nombre_archivo)
            except Exception as e_ocr_err:
                print(f"[WhatsApp] Error analizando comprobante OCR en webhook: {e_ocr_err}")

            es_doc_valido = bool(ocr_verif and ocr_verif.get("es_documento_valido", False))
            if not es_doc_valido:
                resp_invalido = "La imagen enviada no es un documento válido. Por favor, envía un comprobante de pago o transferencia bancaria válido."
                msg_formateado_chat = f"📷 [Imagen recibida - No es un comprobante válido] {url_final}"

                registrar_mensaje_chat(
                    db, jid_destino, "cliente", msg_formateado_chat,
                    cliente_id=c_por_msg.id if c_por_msg else None,
                    tipo="multimedia",
                    nombre_remitente=payload.nombre or ""
                )
                registrar_mensaje_chat(
                    db, jid_destino, "asistente", resp_invalido,
                    cliente_id=c_por_msg.id if c_por_msg else None
                )
                sam_bot_service.guardar_mensaje_historial(jid_destino, "user", msg_formateado_chat)
                sam_bot_service.guardar_mensaje_historial(jid_destino, "assistant", resp_invalido)

                if not payload.ya_notificado_cliente:
                    try:
                        whatsapp_service.send_whatsapp_message(jid_destino, resp_invalido)
                    except Exception as e_send_inv:
                        print(f"[WhatsApp] Aviso al enviar rechazo de documento inválido: {e_send_inv}")

                return {"success": False, "response": resp_invalido, "comprobante": False}

            texto_adjunto = ""
            if " - " in mensaje and not mensaje.startswith("[NON_TEXT_MSG]"):
                texto_adjunto = mensaje.split(" - ", 1)[1].strip()
            elif not mensaje.startswith("🧾") and not mensaje.startswith("[NON_TEXT_MSG]"):
                texto_adjunto = mensaje.strip()

            num_db = tel_real or jid_destino.replace("@c.us", "").replace("@lid", "")
            nombre_db = payload.nombre or (c_por_msg.nombre if c_por_msg else "Cliente WhatsApp")
            ahora_ec = datetime.now(ECUADOR_TZ).replace(tzinfo=None)

            comp_existente = db.query(models.Comprobante).filter(
                (models.Comprobante.nombre_archivo == nombre_archivo) |
                (
                    (models.Comprobante.numero_telefono == num_db) &
                    (models.Comprobante.created_at >= datetime.utcnow() - timedelta(minutes=2))
                )
            ).first()

            es_dup_wh = bool(getattr(comp_existente, "es_duplicado", False)) if comp_existente else False

            if not comp_existente:
                eval_webhook = evaluar_validacion_comprobante(
                    db=db,
                    numero_raw=num_db,
                    nombre_remitente=nombre_db,
                    ocr_data=ocr_verif,
                    monto_final=ocr_verif.get("monto"),
                    referencia_final=ocr_verif.get("numero_referencia"),
                    nombre_archivo=nombre_archivo or "",
                    hash_imagen=ocr_verif.get("hash_imagen")
                )
                cli_wh = eval_webhook.get("cliente")
                cat_val = eval_webhook.get("categoria_validacion") or "CONFIRMACION_RECIBO"
                mot_val = eval_webhook.get("motivo_validacion") or ""
                ced_val = getattr(cli_wh, "cedula", None) if cli_wh else None
                es_dup_wh = bool(eval_webhook.get("es_duplicado", False))
                dup_det_wh = eval_webhook.get("duplicado_detalle")
                score_aut_wh = int(ocr_verif.get("score_autenticidad") or 0)

                nuevo_comp = models.Comprobante(
                    cliente_id=cli_wh.id if cli_wh else (c_por_msg.id if c_por_msg else None),
                    numero_telefono=eval_webhook.get("numero_limpio") or num_db,
                    nombre_remitente=nombre_db,
                    nombre_archivo=nombre_archivo,
                    ruta_archivo=ruta_archivo,
                    url_archivo=url_final,
                    mimetype=mimetype,
                    tamano_bytes=tamano_bytes,
                    mensaje_texto=texto_adjunto or "Comprobante de pago recibido por WhatsApp",
                    estado="PENDIENTE",
                    banco_origen=ocr_verif.get("banco_origen"),
                    banco_destino=ocr_verif.get("banco_destino"),
                    monto=eval_webhook.get("monto_evaluado"),
                    numero_referencia=ocr_verif.get("numero_referencia"),
                    cuenta_origen=ocr_verif.get("cuenta_origen"),
                    cuenta_destino=ocr_verif.get("cuenta_destino"),
                    beneficiario=ocr_verif.get("beneficiario"),
                    ordenante=ocr_verif.get("ordenante"),
                    fecha_comprobante=ocr_verif.get("fecha"),
                    texto_ocr=ocr_verif.get("texto_extraido"),
                    cedula_cliente=ced_val,
                    saldo_pendiente_bd=eval_webhook.get("saldo_pendiente_bd"),
                    categoria_validacion=cat_val,
                    motivo_validacion=mot_val,
                    hash_imagen=ocr_verif.get("hash_imagen"),
                    score_autenticidad=score_aut_wh,
                    es_duplicado=es_dup_wh,
                    duplicado_detalle=dup_det_wh,
                    observaciones=ocr_verif.get("resumen_ocr"),
                    fecha_hora=ahora_ec,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                db.add(nuevo_comp)
                db.commit()
                db.refresh(nuevo_comp)

                try:
                    for db_sqlite in [os.path.join(backend_dir, "opsatel.db"), os.path.join(backend_dir, "..", "opsatel.db")]:
                        if os.path.exists(db_sqlite) and "sqlite" not in str(db.get_bind().url).lower():
                            import sqlite3
                            sc = sqlite3.connect(db_sqlite)
                            sc.execute("""
                                INSERT INTO comprobantes (
                                    cliente_id, numero_telefono, nombre_remitente, nombre_archivo,
                                    ruta_archivo, url_archivo, mimetype, tamano_bytes, mensaje_texto,
                                    estado, fecha_hora, created_at, updated_at
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDIENTE', ?, ?, ?)
                            """, (
                                c_por_msg.id if c_por_msg else None,
                                num_db,
                                nombre_db,
                                nombre_archivo,
                                ruta_archivo,
                                url_final,
                                mimetype,
                                tamano_bytes,
                                texto_adjunto or "Comprobante de pago recibido por WhatsApp",
                                ahora_ec.strftime("%Y-%m-%d %H:%M:%S"),
                                datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                                datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                            ))
                            sc.commit()
                            sc.close()
                except Exception as e_sq_sync:
                    print(f"[Comprobante] Aviso replicando a sqlite: {e_sq_sync}")

            msg_formateado_chat = f"🧾 [Comprobante guardado en uploadscr] {url_final}"
            if texto_adjunto:
                msg_formateado_chat += f" - {texto_adjunto}"

            registrar_mensaje_chat(
                db, jid_destino, "cliente", msg_formateado_chat,
                cliente_id=c_por_msg.id if c_por_msg else None,
                tipo="multimedia",
                nombre_remitente=payload.nombre or ""
            )
            sam_bot_service.guardar_mensaje_historial(jid_destino, "user", msg_formateado_chat)

            ahora_ts = time.time()
            num_clean_track = re.sub(r'\D', '', str(num_db or jid_destino or ""))

            for k, ts in list(_ultimos_comprobantes_respondidos.items()):
                if ahora_ts - ts > 180:
                    _ultimos_comprobantes_respondidos.pop(k, None)

            ya_respondido = False
            if num_clean_track and (ahora_ts - _ultimos_comprobantes_respondidos.get(num_clean_track, 0)) < 25:
                ya_respondido = True
            if jid_destino and (ahora_ts - _ultimos_comprobantes_respondidos.get(jid_destino, 0)) < 25:
                ya_respondido = True

            if ya_respondido:
                print(f"[WhatsApp Webhook] ⏭️ Confirmación de comprobante ya enviada recientemente a {num_clean_track or jid_destino}. Omitiendo envío duplicado.")
                return {"success": True, "response": "", "comprobante": True, "duplicado_omitido": True}

            if getattr(payload, "ya_notificado_cliente", False) or getattr(payload, "es_duplicado", False) or es_dup_wh:
                print(f"[WhatsApp Webhook] Cliente {num_clean_track or jid_destino} ya notificado o comprobante duplicado. Omitiendo mensaje de agradecimiento normal.")
                return {"success": True, "response": "", "comprobante": True, "ya_notificado": True}

            if num_clean_track:
                _ultimos_comprobantes_respondidos[num_clean_track] = ahora_ts
            if jid_destino:
                _ultimos_comprobantes_respondidos[jid_destino] = ahora_ts

            resp_comprobante = (
                "¡Muchas gracias! 🧾 Hemos recibido tu comprobante de pago.\n"
                "Ha sido registrado exitosamente y se encuentra en estado de verificación y aprobación. "
                "No es necesario enviarlo de nuevo. ¡Que tengas un excelente día! 😊"
            )
            registrar_mensaje_chat(
                db, jid_destino, "asistente", resp_comprobante,
                cliente_id=c_por_msg.id if c_por_msg else None
            )
            sam_bot_service.guardar_mensaje_historial(jid_destino, "assistant", resp_comprobante)
            try:
                whatsapp_service.send_whatsapp_message(jid_destino, resp_comprobante)
            except Exception as e_send_w:
                print(f"[WhatsApp] Aviso al enviar confirmación de comprobante: {e_send_w}")

            return {"success": True, "response": resp_comprobante, "comprobante": True}

        cid_vinculado = c_por_msg.id if c_por_msg else None
        nuevo_msg_guardado = registrar_mensaje_chat(
            db, jid_destino, "cliente", mensaje,
            cliente_id=cid_vinculado,
            tipo="texto",
            nombre_remitente=payload.nombre or ""
        )
        if nuevo_msg_guardado and nuevo_msg_guardado.cliente_id and not c_por_msg:
            c_por_msg = db.query(models.Cliente).filter(models.Cliente.id == nuevo_msg_guardado.cliente_id).first()
            if c_por_msg:
                sam_bot_service.clientes_identificados_sesion[jid_destino] = c_por_msg.id
                if tel_real:
                    sam_bot_service.clientes_identificados_sesion[tel_real] = c_por_msg.id

        sam_bot_service.guardar_mensaje_historial(jid_destino, "user", mensaje)

        if mensaje.startswith("[NON_TEXT_MSG]"):
            tipo_media = mensaje.replace("[NON_TEXT_MSG]", "").strip().lower()
            resp_media = f"Hemos recibido tu archivo adjunto ({tipo_media}). Un asesor humano lo revisará en breve. ¡Muchas gracias!"
            registrar_mensaje_chat(db, jid_destino, "asistente", resp_media, cliente_id=c_por_msg.id if c_por_msg else None)
            sam_bot_service.guardar_mensaje_historial(jid_destino, "assistant", resp_media)
            try:
                whatsapp_service.send_whatsapp_message(jid_destino, resp_media)
            except Exception:
                pass
            return {"success": True, "response": resp_media}

        if mensaje.lower() in ["cancelar", "salir", "menu", "menú", "inicio", "empezar de nuevo", "reset", "reiniciar"]:
            sam_bot_service.estados_skills[jid_destino] = None
            sam_bot_service.historial_conversaciones[jid_destino] = []
            sam_bot_service.clientes_identificados_sesion.pop(jid_destino, None)
            if payload.numero:
                sam_bot_service.clientes_identificados_sesion.pop(payload.numero, None)
            if tel_real:
                sam_bot_service.clientes_identificados_sesion.pop(tel_real, None)
            response_text = "¡Listo! He reiniciado la conversación. ¿En qué te puedo colaborar hoy con tus servicios de Opsatel? 😊"
            registrar_mensaje_chat(db, jid_destino, "asistente", response_text, cliente_id=c_por_msg.id if c_por_msg else None)
            sam_bot_service.guardar_mensaje_historial(jid_destino, "assistant", response_text)
            whatsapp_service.send_whatsapp_message(jid_destino, response_text)
            return {"success": True, "response": response_text}

        admin_obj = sam_bot_service.es_numero_administrador(
            jid_destino, db, jid_original=payload.jid_original,
            nombre_remitente=payload.nombre or "", telefono_real=tel_real
        )
        es_cmd_admin = admin_obj and (
            sam_bot_service.estados_skills.get(jid_destino) == "alta_instalacion_admin"
            or any(w in mensaje.lower() for w in [
                "caja", "cobro", "cobros", "recaudacion", "recaudación", "ingresos", "cierre",
                "moroso", "morosos", "corte", "cortes", "suspendido", "suspendidos", "deudores",
                "instalacion", "instalación", "nuevo cliente", "ingresar cliente", "registrar cliente",
                "registrar", "alta"
            ])
        )
        if es_cmd_admin:
            contexto = sam_bot_service.obtener_contexto_conversacion(jid_destino, mensaje)
            response_text = sam_bot_service.procesar_comando_administrador(jid_destino, mensaje, contexto, db, admin_obj)
            registrar_mensaje_chat(db, jid_destino, "asistente", response_text, cliente_id=c_por_msg.id if c_por_msg else None)
            sam_bot_service.guardar_mensaje_historial(jid_destino, "assistant", response_text)
            whatsapp_service.send_whatsapp_message(jid_destino, response_text)
            return {"success": True, "response": response_text}

        try:
            from services.movie_service import gestionar_consulta_peliculas
            resp_pelicula = gestionar_consulta_peliculas(mensaje=mensaje, db=db)
            if resp_pelicula:
                registrar_mensaje_chat(db, jid_destino, "asistente", resp_pelicula, cliente_id=c_por_msg.id if c_por_msg else None)
                sam_bot_service.guardar_mensaje_historial(jid_destino, "assistant", resp_pelicula)
                whatsapp_service.send_whatsapp_message(jid_destino, resp_pelicula)
                return {
                    "success": True,
                    "response": resp_pelicula,
                    "modulo": "peliculas"
                }
        except Exception as e_pel:
            print(f"[WhatsApp Webhook] Aviso al consultar módulo de películas: {e_pel}")

        response_text = procesar_mensaje_con_herramientas(
            mensaje=mensaje,
            numero=tel_real or jid_destino,
            db=db,
            historial_mensajes=historial_previo,
            metadata_identidad=identidad["metadata_ia"],
            cliente_id=c_por_msg.id if c_por_msg else None
        )

        registrar_mensaje_chat(db, jid_destino, "asistente", response_text, cliente_id=c_por_msg.id if c_por_msg else None)
        sam_bot_service.guardar_mensaje_historial(jid_destino, "assistant", response_text)
        whatsapp_service.send_whatsapp_message(jid_destino, response_text)

        return {
            "success": True,
            "response": response_text
        }

    except Exception as e:
        print(f"[Webhook Mensaje Error] {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Error interno procesando mensaje en SAM: {str(e)}"
        )
