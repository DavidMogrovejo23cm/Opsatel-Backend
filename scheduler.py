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
                # Envío mensual recurrente: mismo día del mes que fecha_programada
                if config.fecha_programada:
                    dia_programado = config.fecha_programada.day
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
            
            # Obtener clientes con celular
            clientes = db.query(models.Cliente).filter(
                models.Cliente.celular != None,
                models.Cliente.celular != ""
            ).all()
            
            if not clientes:
                print(f"[WhatsApp] No hay clientes con celular registrado para config ID {config.id}")
                if es_envio_unico:
                    config.activo = False
                    db.commit()
                continue
            
            # Enviar mensaje a cada cliente
            enviados = 0
            fallidos = 0
            
            for cliente in clientes:
                try:
                    numero = cliente.celular.strip()
                    
                    # Enviar mensaje usando el servicio unificado
                    success = whatsapp_service.send_whatsapp_message(numero, config.mensaje_programado)
                    
                    # Guardar en historial
                    historial = models.WhatsAppHistorial(
                        numero_destino=numero,
                        mensaje=config.mensaje_programado,
                        tipo_envio="automatico",
                        estado="enviado" if success else "fallido",
                        fecha_envio=ahora.strftime("%Y-%m-%d %H:%M:%S") if success else None,
                        fecha_creacion=ahora
                    )
                    db.add(historial)
                    
                    if success:
                        enviados += 1
                        print(f"[WhatsApp Scheduler] Mensaje enviado a {numero}")
                    else:
                        fallidos += 1
                        print(f"[WhatsApp Scheduler] Falló el envío a {numero}")
                    
                except Exception as e:
                    fallidos += 1
                    # Guardar como fallido en historial
                    historial = models.WhatsAppHistorial(
                        numero_destino=cliente.celular,
                        mensaje=config.mensaje_programado,
                        tipo_envio="automatico",
                        estado="fallido",
                        fecha_envio=ahora.strftime("%Y-%m-%d %H:%M:%S"),
                        fecha_creacion=ahora
                    )
                    db.add(historial)
                    print(f"[WhatsApp Scheduler] Error enviando a {cliente.celular}: {str(e)}")
            
            # Si era envío único, desactivarlo para que no se vuelva a mandar
            if es_envio_unico:
                config.activo = False
                print(f"[WhatsApp] Desactivando configuración única ID {config.id} tras envío.")
                
            db.commit()
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
    """
    from config_manager import get_config
    from network.adapters.mikrotik import MikroTikAdapter
    from sqlalchemy import or_ as _or

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
        from services.libreqos_manager import LibreQoSManager
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
                    if c.fecha_prorroga >= hoy_str:
                        print(f"[Scheduler] Omitiendo suspensión del cliente {c.id} ({c.nombre}) debido a prórroga activa hasta {c.fecha_prorroga}")
                        continue
                except Exception as e:
                    print(f"[Scheduler] Error al comparar fecha de prórroga para cliente {c.id}: {e}")

            # Cambiar estado a Moroso
            c.estado = "Moroso"
            count += 1

            # 1. Agregar a MikroTik Address List por Nodo
            if c.ip:
                try:
                    is_sayausi = is_nodo_sayausi(c.nodo)
                    list_name = "CLIENTES_SUSPENDIDOS_POR_PAGOS" if is_sayausi else "CLIENTES_SUSPENDIDOS_POR_PAGO"

                    olt_config = db.query(models.OLTConfig).filter(
                        _or(
                            models.OLTConfig.nodo_asociado == c.nodo,
                            models.OLTConfig.nodo_asociado.ilike("%SAYAUS%") if is_sayausi else models.OLTConfig.nodo_asociado.ilike("%BAN%"),
                            models.OLTConfig.nodo_asociado == None
                        ),
                        models.OLTConfig.active == True
                    ).first()

                    if olt_config and olt_config.mikrotik_host:
                        with MikroTikAdapter(
                            host=olt_config.mikrotik_host,
                            username=olt_config.mikrotik_username,
                            password=olt_config.mikrotik_password,
                            port=olt_config.mikrotik_port or 8728
                        ) as mt:
                            mt.add_to_address_list(
                                address=c.ip,
                                comment=c.nombre or f"Cliente #{c.id}",
                                list_name=list_name
                            )
                except Exception as mt_err:
                    print(f"[Scheduler] Error MikroTik al suspender a {c.nombre} ({c.ip}): {mt_err}")

            # 2. LibreQoS Sync
            try:
                correlation_id = f"auto_susp_{c.id}_{int(datetime.now().timestamp())}"
                LibreQoSManager.enqueue_job("SUSPEND", c.id, db, correlation_id, "SYSTEM_AUTO_SUSPENSION")
            except Exception as lq_err:
                print(f"[Scheduler] Error LibreQoS al suspender a {c.nombre}: {lq_err}")

        db.commit()
        print(f"[Scheduler] Suspensión automática por fecha completada. Clientes marcados como Moroso: {count}")
    except Exception as e:
        db.rollback()
        print(f"[Scheduler] Error en suspensión automática por mora: {str(e)}")
        traceback.print_exc()
    finally:
        db.close()

def iniciar_scheduler():
    """
    Inicia el scheduler en background.
    Debe ser llamado una sola vez al iniciar la aplicación.
    """
    global scheduler
    
    if scheduler is not None and scheduler.running:
        print("[Scheduler] Ya está corriendo")
        return
    
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

    # 4. Suspensión automática por mora (Todos los días a las 01:00 AM)
    scheduler.add_job(
        suspension_automatica_por_mora,
        trigger=CronTrigger(hour=1, minute=0, second=0),
        id='suspension_automatica_por_mora',
        name='Suspensión automática por mora',
        replace_existing=True
    )
    
    scheduler.start()
    print("[Scheduler] [OK] Scheduler iniciado correctamente")

def detener_scheduler():
    """
    Detiene el scheduler.
    """
    global scheduler
    if scheduler is not None and scheduler.running:
        scheduler.shutdown()
        print("[Scheduler] [OK] Scheduler detenido")
