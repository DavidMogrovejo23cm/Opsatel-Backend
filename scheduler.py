"""
Scheduler para ejecutar tareas automáticas como envío de WhatsApp.
Se ejecuta en background y verifica cada minuto si hay envíos programados.
"""

# pyrefly: ignore [missing-import]
from apscheduler.schedulers.background import BackgroundScheduler
# pyrefly: ignore [missing-import]
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
import pytz
from database import SessionLocal
import models
import traceback
import whatsapp_service

ECUADOR_TZ = pytz.timezone('America/Guayaquil')
scheduler = None

def enviar_whatsapp_programado():
    """
    Tarea que se ejecuta cada minuto para verificar si hay envíos programados.
    """
    db = SessionLocal()
    try:
        # Obtener todas las configuraciones activas
        configs = db.query(models.WhatsAppConfiguracion).filter(
            models.WhatsAppConfiguracion.activo == True
        ).all()
        
        if not configs:
            return  # No hay configuraciones activas
        
        # Obtener hora y fecha actual en Ecuador
        ahora = datetime.now(ECUADOR_TZ)
        hora_actual = ahora.strftime("%H:%M")
        fecha_actual_str = ahora.strftime("%Y-%m-%d")
        
        for config in configs:
            # Verificar si la hora actual coincide con la programada
            if hora_actual != config.hora_programada:
                continue
                
            # Obtener el tipo de recurrencia
            rec = getattr(config, 'recurrencia', None)
            if not rec:
                # Compatibilidad hacia atrás
                if config.fecha_programada is None:
                    rec = 'diario'
                else:
                    rec = 'unico'
            
            debe_enviar = False
            es_envio_unico = False

            if rec == 'diario':
                # Envío diario recurrente
                debe_enviar = True
            elif rec == 'mensual':
                # Envío mensual recurrente: mismo día del mes que fecha_programada (por defecto día 1)
                dia_programado = config.fecha_programada.day if config.fecha_programada else 1
                dia_actual = ahora.day
                if dia_programado == dia_actual:
                    debe_enviar = True
            elif rec == 'unico':
                # Envío único programado
                if config.fecha_programada:
                    fecha_prog_str = config.fecha_programada.strftime("%Y-%m-%d")
                    if fecha_prog_str == fecha_actual_str:
                        debe_enviar = True
                        es_envio_unico = True
            
            if not debe_enviar:
                continue
                
            print(f"[WhatsApp] Iniciando envío automático para config ID {config.id} a las {hora_actual}")
            
            # Obtener clientes activos con celular registrado según el filtro configurado
            from sqlalchemy import func, or_
            import time
            import random
            from routes.whatsapp import personalizar_mensaje_cliente

            filtro = getattr(config, 'filtro_clientes', 'todos') or 'todos'
            query_clientes = db.query(models.Cliente).filter(
                func.upper(models.Cliente.estado).in_(["ACTIVO", "ACTIVA"]),
                models.Cliente.celular != None,
                models.Cliente.celular != ""
            )

            if filtro == "deuda":
                # Solo clientes con deuda pendiente (saldo > 0)
                query_clientes = query_clientes.filter(models.Cliente.saldo > 0)
            elif filtro in ["al_dia", "pago", "sin_deuda"]:
                # Solo clientes al día (saldo <= 0 o None)
                query_clientes = query_clientes.filter(
                    or_(models.Cliente.saldo == None, models.Cliente.saldo <= 0)
                )

            clientes = query_clientes.all()
            
            if not clientes:
                print(f"[WhatsApp] No hay clientes activos para el filtro '{filtro}' con celular registrado para config ID {config.id}")
                if es_envio_unico:
                    config.activo = False
                    db.commit()
                continue
            
            # Enviar mensaje personalizado a cada cliente activo
            enviados = 0
            fallidos = 0
            
            for cliente in clientes:
                try:
                    raw_num = (cliente.celular or "").strip()
                    numeros_validos = whatsapp_service.extract_all_whatsapp_numbers(raw_num)
                    if not numeros_validos:
                        print(f"[WhatsApp Scheduler] Saltando cliente {cliente.nombre}: '{cliente.celular}' no contiene números móviles válidos para WhatsApp.")
                        continue

                    # Personalizar mensaje con los datos reales del cliente en la BD
                    mensaje_personalizado = personalizar_mensaje_cliente(config.mensaje_programado, cliente)
                    
                    # Enviar mensaje usando el servicio unificado a todos los números del cliente
                    success = whatsapp_service.send_whatsapp_message(raw_num, mensaje_personalizado)
                    
                    # Guardar en historial con el mensaje final personalizado
                    historial = models.WhatsAppHistorial(
                        numero_destino=raw_num,
                        mensaje=mensaje_personalizado,
                        tipo_envio="automatico",
                        estado="enviado" if success else "fallido",
                        fecha_envio=ahora.strftime("%Y-%m-%d %H:%M:%S") if success else None,
                        fecha_creacion=ahora
                    )
                    db.add(historial)
                    
                    if success:
                        enviados += 1
                        print(f"[WhatsApp Scheduler] Mensaje personalizado enviado a {raw_num} ({len(numeros_validos)} números)")
                        try:
                            from routes.whatsapp import registrar_mensaje_chat
                            for num_tgt in numeros_validos:
                                registrar_mensaje_chat(db, num_tgt, "operador", mensaje_personalizado, cliente_id=cliente.id)
                        except Exception as e_chat:
                            print(f"[WhatsApp Scheduler] Aviso registrando chat: {e_chat}")
                    else:
                        fallidos += 1
                        print(f"[WhatsApp Scheduler] Falló el envío a {raw_num}")
                    
                    # Confirmar cambios en la base de datos tras cada mensaje
                    db.commit()

                    # Pequeña pausa prudencial para simular comportamiento orgánico
                    whatsapp_service.apply_rate_limit()

                except Exception as e:
                    fallidos += 1
                    try:
                        historial = models.WhatsAppHistorial(
                            numero_destino=cliente.celular,
                            mensaje=config.mensaje_programado,
                            tipo_envio="automatico",
                            estado="fallido",
                            fecha_envio=ahora.strftime("%Y-%m-%d %H:%M:%S"),
                            fecha_creacion=ahora
                        )
                        db.add(historial)
                        db.commit()
                    except Exception:
                        db.rollback()
                    print(f"[WhatsApp Scheduler] Error enviando a {cliente.celular}: {str(e)}")
            
            # Si era envío único, desactivarlo para que no se vuelva a mandar
            if es_envio_unico:
                config.activo = False
                print(f"[WhatsApp] Desactivando configuración única ID {config.id} tras envío.")
                db.commit()
                
            # Registrar resumen de envío programado en historial de difusiones
            try:
                rec_tag = "Mensual" if rec == 'mensual' else ("Diario" if rec == 'diario' else "Único")
                if filtro == "deuda":
                    alcance_desc = "Clientes activos con DEUDA"
                elif filtro in ["al_dia", "pago", "sin_deuda"]:
                    alcance_desc = "Clientes activos AL DÍA (Sin deuda)"
                else:
                    alcance_desc = "TODOS los clientes activos"

                difusion_prog = models.WhatsAppDifusionHistorial(
                    tipo="envio_programado",
                    alcance=f"{alcance_desc} (Recurrencia {rec_tag})",
                    mensaje=config.mensaje_programado,
                    total_destinatarios=len(clientes),
                    total_exitosos=enviados,
                    total_fallidos=fallidos,
                    estado="completado" if fallidos < len(clientes) else "fallido",
                    fecha_envio=ahora.strftime("%Y-%m-%d %H:%M:%S"),
                    fecha_creacion=ahora
                )
                db.add(difusion_prog)
                db.commit()
            except Exception as e_dif:
                print(f"[WhatsApp Scheduler] Error guardando difusion_prog: {e_dif}")

            print(f"[WhatsApp] Envío completado para config ID {config.id}. Enviados: {enviados}, Fallidos: {fallidos}")
    
    except Exception as e:
        print(f"[WhatsApp] Error en scheduler: {str(e)}")
        print(traceback.format_exc())
    finally:
        db.close()

def facturacion_mensual_automatica():
    """
    Ejecuta el proceso de facturación mensual automática de manera segura e idempotente.
    """
    current_month = datetime.now(ECUADOR_TZ).strftime("%Y-%m")
    print(f"[Scheduler] Iniciando facturación mensual automática para el período {current_month}...")
    db = SessionLocal()
    
    # pyrefly: ignore [missing-import]
    from sqlalchemy.exc import IntegrityError
    log_fact = models.LogFacturacion(
        periodo_mes=current_month,
        fecha_ejecucion=datetime.utcnow(),
        estado="Procesando",
        usuario_id=None
    )
    db.add(log_fact)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        print(f"[Scheduler] La facturación del mes {current_month} ya fue realizada anteriormente. Omitiendo.")
        db.close()
        return

    try:
        from routes.clientes import procesar_facturacion_global
        count = procesar_facturacion_global(db)
        log_fact.estado = "Completado"
        db.commit()
        print(f"[Scheduler] Facturación mensual automática completada para {count} clientes.")
    except Exception as e:
        db.rollback()
        db.query(models.LogFacturacion).filter(models.LogFacturacion.periodo_mes == current_month).delete()
        db.commit()
        print(f"[Scheduler] Error en facturación automática: {str(e)}")
        traceback.print_exc()
    finally:
        db.close()

def cierre_mensual_automatico():
    """
    Ejecuta el cierre de mes automático al iniciar un nuevo mes.
    Resetea los contadores de pago_mensual para iniciar el nuevo ciclo desde cero,
    manteniendo la deuda/saldo pendiente.
    """
    current_month = datetime.now(ECUADOR_TZ).strftime("%Y-%m")
    print(f"[Scheduler] Iniciando cierre de mes automático para el período {current_month}...")
    
    from config_manager import get_config, save_config
    config_sys = get_config()
    
    if config_sys.get("ultimo_cierre") == current_month:
        print(f"[Scheduler] El cierre de mes para {current_month} ya fue realizado. Omitiendo.")
        return
        
    db = SessionLocal()
    try:
        clientes = db.query(models.Cliente).all()
        count = 0
        for cliente in clientes:
            cliente.pago_mensual = 0.00
            cliente.plus_pagado = 0.00
            cliente.adicional_pagado = 0.00
            count += 1
        save_config({"ultimo_cierre": current_month})
        db.commit()
        print(f"[Scheduler] Cierre de mes automático completado para {count} clientes.")
    except Exception as e:
        db.rollback()
        print(f"[Scheduler] Error en cierre de mes automático: {str(e)}")
        traceback.print_exc()
    finally:
        db.close()

def is_nodo_sayausi(nodo_val) -> bool:
    if not nodo_val:
        return False
    import unicodedata
    s = unicodedata.normalize('NFD', str(nodo_val)).encode('ascii', 'ignore').decode('utf-8').upper()
    return "SAYAUSI" in s

def suspension_automatica_por_mora(force_run: bool = False):
    """
    Ejecuta el proceso de suspensión automática por corte de fecha (ej. día 20 de cada mes).
    Agrega las IPs de clientes morosos a la lista de MikroTik por nodo:
      - Baños: CLIENTES_SUSPENDIDOS_POR_PAGO
      - Sayausí: CLIENTES_SUSPENDIDOS_POR_PAGOS
    Y cambia el estado del cliente a 'Moroso'.
    NOTA: No altera ni suspende en LibreQoS, el corte se gestiona exclusivamente en MikroTik.
    """
    from config_manager import get_config
    from network.adapters.mikrotik import suspender_cliente_mikrotik_backend

    config_sys = get_config()
    enabled = config_sys.get("auto_suspension_enabled", True)
    dia_corte = int(config_sys.get("dia_corte", 20))

    ahora = datetime.now(ECUADOR_TZ)
    dia_actual = ahora.day

    if not force_run:
        if not enabled:
            print("[Scheduler] Suspensión automática desactivada en configuración. Omitiendo.")
            return
        if dia_actual != dia_corte:
            print(f"[Scheduler] Hoy es día {dia_actual}, la fecha de corte configurada es el día {dia_corte}. Omitiendo corte.")
            return

    print(f"[Scheduler] Iniciando proceso de suspensión por corte de fecha (Día {dia_corte})...")
    db = SessionLocal()
    try:
        hoy_str = ahora.strftime("%Y-%m-%d")

        clientes = db.query(models.Cliente).filter(
            models.Cliente.estado == "Activo"
        ).all()

        count = 0
        for c in clientes:
            saldo_pend = float(c.saldo or 0)
            try:
                plus_pend = float(c.plus or 0)
            except:
                plus_pend = 0.0

            if saldo_pend <= 0 and plus_pend <= 0:
                continue

            # Verificar si el cliente está en la lista de Excepciones / Exentos de corte
            exentos_corte = config_sys.get("clientes_exentos_corte", [])
            if c.id in exentos_corte or str(c.id) in [str(x) for x in exentos_corte]:
                print(f"[Scheduler] Omitiendo suspensión del cliente {c.id} ({c.nombre}) por estar en la Lista de Excepciones de corte.")
                continue

            # Verificar prórroga de pago
            if c.fecha_prorroga:
                try:
                    if str(c.fecha_prorroga).strip() >= hoy_str:
                        print(f"[Scheduler] Omitiendo suspensión del cliente {c.id} ({c.nombre}) debido a prórroga activa hasta {c.fecha_prorroga}")
                        continue
                except Exception as e:
                    print(f"[Scheduler] Error al comparar fecha de prórroga para cliente {c.id}: {e}")

            # Cambiar estado a Moroso
            c.estado = "Moroso"
            count += 1

            # 1. Suspender exclusivamente en MikroTik
            if c.ip:
                try:
                    res_mt = suspender_cliente_mikrotik_backend(c, db)
                    if not res_mt.get("success"):
                        print(f"[Scheduler] Aviso MikroTik al suspender a {c.nombre} ({c.ip}): {res_mt.get('error')}")
                except Exception as mt_err:
                    print(f"[Scheduler] Error MikroTik al suspender a {c.nombre} ({c.ip}): {mt_err}")

        db.commit()
        print(f"[Scheduler] Suspensión automática por fecha completada. Clientes marcados como Moroso y suspendidos en MikroTik: {count}")
    except Exception as e:
        db.rollback()
        print(f"[Scheduler] Error en suspensión automática por mora: {str(e)}")
        traceback.print_exc()
    finally:
        db.close()

def reprogramar_job_suspension():
    """
    Reprograma el trabajo de corte automático en el scheduler según la hora configurada en config.json.
    """
    global scheduler
    if scheduler is not None and scheduler.running:
        try:
            from config_manager import get_config
            cfg = get_config()
            hora_str = str(cfg.get("hora_corte", "01:00"))
            parts = hora_str.split(":")
            h = int(parts[0]) if len(parts) > 0 and parts[0].isdigit() else 1
            m = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0

            scheduler.reschedule_job(
                'suspension_automatica_por_mora',
                trigger=CronTrigger(hour=h, minute=m, second=0)
            )
            print(f"[Scheduler] [OK] Job de suspensión reprogramado para las {h:02d}:{m:02d} diariamente.")
        except Exception as e:
            print(f"[Scheduler] Error al reprogramar job de suspensión: {e}")

def iniciar_scheduler():
    """
    Inicia el scheduler en background.
    Debe ser llamado una sola vez al iniciar la aplicación.
    """
    global scheduler
    
    if scheduler is not None and scheduler.running:
        print("[Scheduler] Ya está corriendo")
        return
    
    from config_manager import get_config
    cfg = get_config()
    hora_str = str(cfg.get("hora_corte", "01:00"))
    parts = hora_str.split(":")
    h = int(parts[0]) if len(parts) > 0 and parts[0].isdigit() else 1
    m = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0

    scheduler = BackgroundScheduler(timezone=ECUADOR_TZ)
    
    # 1. Envío automático de WhatsApp (cada minuto)
    scheduler.add_job(
        enviar_whatsapp_programado,
        trigger=CronTrigger(second=0),
        id='whatsapp_programado',
        name='Envío automático de WhatsApp',
        replace_existing=True
    )

    # 2. Cierre mensual automático (Día 1 de cada mes a las 00:01 AM)
    scheduler.add_job(
        cierre_mensual_automatico,
        trigger=CronTrigger(day=1, hour=0, minute=1, second=0),
        id='cierre_mensual_automatico',
        name='Cierre de mes automático',
        replace_existing=True
    )

    # 3. Facturación mensual automática (Día 1 de cada mes a las 00:05 AM)
    scheduler.add_job(
        facturacion_mensual_automatica,
        trigger=CronTrigger(day=1, hour=0, minute=5, second=0),
        id='facturacion_mensual_automatica',
        name='Facturación mensual automática',
        replace_existing=True
    )

    # 4. Suspensión automática por mora (Hora configurada)
    scheduler.add_job(
        suspension_automatica_por_mora,
        trigger=CronTrigger(hour=h, minute=m, second=0),
        id='suspension_automatica_por_mora',
        name='Suspensión automática por mora',
        replace_existing=True
    )
    
    scheduler.start()
    print(f"[Scheduler] [OK] Scheduler iniciado correctamente (Suspensión programada a las {h:02d}:{m:02d})")

def detener_scheduler():
    """
    Detiene el scheduler.
    """
    global scheduler
    if scheduler is not None and scheduler.running:
        scheduler.shutdown()
        print("[Scheduler] [OK] Scheduler detenido")

