"""
Scheduler para ejecutar tareas automáticas como envío de WhatsApp.
Se ejecuta en background y verifica cada minuto si hay envíos programados.
"""

from apscheduler.schedulers.background import BackgroundScheduler
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
    
    # Ejecutar cada minuto
    scheduler.add_job(
        enviar_whatsapp_programado,
        trigger=CronTrigger(second=0),  # Cada minuto en el segundo 0
        id='whatsapp_programado',
        name='Envío automático de WhatsApp',
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
