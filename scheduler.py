"""
Scheduler para ejecutar tareas automáticas como envío de WhatsApp.
Se ejecuta en background y verifica cada minuto si hay envíos programados.
"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
import pytz
import pywhatkit as kit
from database import SessionLocal
import models
import traceback

ECUADOR_TZ = pytz.timezone('America/Guayaquil')
scheduler = None

def enviar_whatsapp_programado():
    """
    Tarea que se ejecuta cada minuto para verificar si hay envíos programados.
    """
    db = SessionLocal()
    try:
        # Obtener configuración activa
        config = db.query(models.WhatsAppConfiguracion).filter(
            models.WhatsAppConfiguracion.activo == True
        ).first()
        
        if not config:
            return  # No hay configuración activa
        
        # Obtener hora actual en Ecuador
        ahora = datetime.now(ECUADOR_TZ)
        hora_actual = ahora.strftime("%H:%M")
        
        # Verificar si la hora actual coincide con la programada
        if hora_actual == config.hora_programada:
            print(f"[WhatsApp] Iniciando envío automático a las {hora_actual}")
            
            # Obtener todos los clientes con celular
            clientes = db.query(models.Cliente).filter(
                models.Cliente.celular != None,
                models.Cliente.celular != ""
            ).all()
            
            if not clientes:
                print("[WhatsApp] No hay clientes con celular registrado")
                return
            
            # Enviar mensaje a cada cliente
            enviados = 0
            fallidos = 0
            
            for cliente in clientes:
                try:
                    # Normalizar número (asegurar que inicie con +)
                    numero = cliente.celular.strip()
                    if not numero.startswith('+'):
                        numero = '+593' + numero.lstrip('0')  # Agregar código Ecuador
                    
                    # Enviar mensaje
                    kit.sendwhatmsg_instantly(
                        numero, 
                        config.mensaje_programado,
                        wait_time=10,
                        tab_close=True
                    )
                    
                    # Guardar en historial
                    historial = models.WhatsAppHistorial(
                        numero_destino=numero,
                        mensaje=config.mensaje_programado,
                        tipo_envio="automatico",
                        estado="enviado",
                        fecha_envio=ahora.strftime("%Y-%m-%d %H:%M:%S"),
                        fecha_creacion=ahora
                    )
                    db.add(historial)
                    enviados += 1
                    print(f"[WhatsApp] Mensaje enviado a {numero}")
                    
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
                    print(f"[WhatsApp] Error enviando a {cliente.celular}: {str(e)}")
            
            db.commit()
            print(f"[WhatsApp] Envío completado. Enviados: {enviados}, Fallidos: {fallidos}")
    
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
    print("[Scheduler] ✅ Scheduler iniciado correctamente")

def detener_scheduler():
    """
    Detiene el scheduler.
    """
    global scheduler
    if scheduler is not None and scheduler.running:
        scheduler.shutdown()
        print("[Scheduler] ✅ Scheduler detenido")
