#!/usr/bin/env python3
"""
OPSATEL ISP - LibreQoS Provisioning Worker Daemon
==================================================
Daemon en segundo plano que procesa la cola de tareas asíncronas de LibreQoS.

Características:
- Polling cada N segundos a la BD por tareas pendientes
- Limita la concurrencia a través de semáforos por cada servidor LibreQoS
- Reintentos robustos con backoff exponencial
- Actualización de salud / WorkerHeartbeat
- Auditoría integrada y publicación de eventos en el EventBus

Autor: Arquitecto de Software Senior / CTO
Versión: 1.0.0
"""

import os
import sys
import logging
import logging.handlers
import signal
import time
import socket
from datetime import datetime, timedelta
from pathlib import Path

# Configurar path para importar módulos del proyecto
_WORKERS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_WORKERS_DIR)
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, _WORKERS_DIR)

from database import SessionLocal
import models
from libreqos_models import LibreQoSJob, ClientQoSState, LibreQoSServer, LibreQoSAuditLog
from network.adapters.libreqos import LibreQoSAdapter
from services.libreqos_manager import LibreQoSManager
from workflow_engine import EventBus
import observability

# ============================================================================
# CONFIGURACIÓN
# ============================================================================

LOG_DIR = Path("/var/log/opsatel") if os.path.exists("/var/log") else Path("./logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

PID_FILE = Path("/var/run/opsatel-libreqos-worker.pid") if os.path.exists("/var/run") else Path("./opsatel-libreqos-worker.pid")
LOCK_FILE = Path("/var/run/opsatel-libreqos-worker.lock") if os.path.exists("/var/run") else Path("./opsatel-libreqos-worker.lock")

LOG_FILE = LOG_DIR / "libreqos-worker.log"
LOG_LEVEL = logging.DEBUG if os.getenv("DEBUG", "false").lower() == "true" else logging.INFO

POLL_INTERVAL = int(os.getenv("LIBREQOS_WORKER_POLL_INTERVAL", "10"))
BATCH_SIZE = int(os.getenv("LIBREQOS_WORKER_BATCH_SIZE", "5"))

logger = logging.getLogger("opsatel.libreqos_worker")

def setup_logger():
    """Configura logger con rotación de archivos."""
    formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    file_handler = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=10*1024*1024, backupCount=5)
    file_handler.setFormatter(formatter)
    
    # También imprimir a consola para systemd
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    
    logger.setLevel(LOG_LEVEL)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

# Estado de ejecución global
running = True

def handle_sigterm(signum, frame):
    global running
    logger.info("Recibida señal SIGTERM/SIGINT. Deteniendo de forma ordenada...")
    running = False

class LibreQoSWorker:
    def __init__(self):
        self.worker_name = "libreqos_worker"
        self.hostname = socket.gethostname()
        self.pid = os.getpid()
        self.cycle_count = 0
        self.processed_count = 0
        self.error_count = 0

    def update_heartbeat(self, db_session):
        """Actualiza el latido de salud en la BD."""
        try:
            hb = db_session.query(observability.WorkerHeartbeat).filter(
                observability.WorkerHeartbeat.worker_name == self.worker_name
            ).first()
            if not hb:
                hb = observability.WorkerHeartbeat(worker_name=self.worker_name)
                db_session.add(hb)
            
            hb.pid = self.pid
            hb.hostname = self.hostname
            hb.status = "RUNNING" if running else "STOPPING"
            hb.cycle_count = self.cycle_count
            hb.processed_count = self.processed_count
            hb.error_count = self.error_count
            hb.last_seen = datetime.utcnow()
            
            db_session.commit()
        except Exception as e:
            logger.error(f"Error actualizando heartbeat: {e}")

    def run(self):
        logger.info(f"=== INICIANDO LIBREQOS WORKER DAEMON (PID: {self.pid}) ===")
        setup_logger()
        
        import threading
        if threading.current_thread() == threading.main_thread():
            try:
                signal.signal(signal.SIGTERM, handle_sigterm)
                signal.signal(signal.SIGINT, handle_sigterm)
            except ValueError:
                logger.warning("No se pudieron registrar los manejadores de señales (no es el intérprete principal).")
        
        while running:
            self.cycle_count += 1
            db = SessionLocal()
            try:
                self.update_heartbeat(db)
                self.process_jobs_cycle(db)
            except Exception as e:
                logger.error(f"Error inesperado en ciclo del worker: {e}")
                self.error_count += 1
            finally:
                db.close()
                
            # Esperar antes del siguiente ciclo
            for _ in range(POLL_INTERVAL):
                if not running:
                    break
                time.sleep(1)
                
        # Heartbeat de apagado
        db = SessionLocal()
        try:
            self.update_heartbeat(db)
        finally:
            db.close()
        logger.info("=== WORKER DAEMON DETENIDO CORRECTAMENTE ===")

    def process_jobs_cycle(self, db):
        """Obtiene y procesa un lote de trabajos pendientes."""
        now = datetime.utcnow()
        # Buscar trabajos pendientes o en reintento listos
        jobs = db.query(LibreQoSJob).filter(
            LibreQoSJob.status.in_(["pending", "retry"]),
            (LibreQoSJob.next_retry_at == None) | (LibreQoSJob.next_retry_at <= now)
        ).order_by(LibreQoSJob.priority.desc(), LibreQoSJob.created_at.asc()).limit(BATCH_SIZE).all()

        if not jobs:
            return

        logger.info(f"Detectados {len(jobs)} trabajos de LibreQoS listos para procesar.")
        
        for job in jobs:
            if not running:
                break
            
            # Lock en base de datos marcando como processing
            job.status = "processing"
            job.started_at = datetime.utcnow()
            job.processed_by = f"{self.worker_name}_{self.pid}"
            db.commit()
            
            # Lanzar el procesamiento en un hilo o secuencialmente
            # Dada la concurrencia limitada por server y la simplicidad secuencial robusta
            # procesamos utilizando el Manager.
            try:
                self.execute_job(job, db)
                self.processed_count += 1
            except Exception as ex:
                self.error_count += 1
                logger.exception(f"Error crítico procesando job ID {job.id}: {ex}")

    def execute_job(self, job: LibreQoSJob, db):
        """Lógica de ejecución individual de cada trabajo."""
        start_time = time.time()
        server = db.query(LibreQoSServer).filter(LibreQoSServer.id == job.libreqos_server_id).first()
        cliente = db.query(models.Cliente).filter(models.Cliente.id == job.cliente_id).first()
        
        if not server or not server.enabled:
            self.handle_job_failure(job, db, "El servidor LibreQoS no existe o está deshabilitado.")
            return

        if not cliente:
            self.handle_job_failure(job, db, "El cliente asociado a este trabajo ya no existe.")
            return

        if not cliente.ip:
            self.handle_job_failure(job, db, "El cliente no cuenta con una IP asignada. QoS imposible.")
            return

        # Obtener semáforo para respetar max_concurrent_jobs del servidor
        sem = LibreQoSManager.get_semaphore(server.id, server.max_concurrent_jobs)
        
        acquired = sem.acquire(blocking=True, timeout=30)
        if not acquired:
            # Reencolar para evitar blocking general
            job.status = "retry"
            job.error = "Timeout adquiriendo semáforo de concurrencia."
            job.next_retry_at = datetime.utcnow() + timedelta(seconds=15)
            db.commit()
            return
            
        try:
            logger.info(f"SSH: Iniciando provisión para cliente {job.cliente_id} en LibreQoS {server.name} ({server.host})")
            
            with LibreQoSAdapter(server) as adapter:
                payload = job.payload or {}
                ip = payload.get("ip") or cliente.ip
                down = payload.get("download_mbps") or 100
                up = payload.get("upload_mbps") or 50
                comment = payload.get("comment") or f"CLIENT {job.cliente_id}"
                
                # Ejecutar según operación
                success = False
                if job.operation == "PROVISION":
                    success = adapter.provision_client(job.cliente_id, ip, down, up, comment)
                elif job.operation == "UPDATE":
                    success = adapter.update_client(job.cliente_id, ip, down, up, comment)
                elif job.operation == "REMOVE":
                    success = adapter.remove_client(job.cliente_id, ip)
                elif job.operation == "SUSPEND":
                    success = adapter.update_client(job.cliente_id, ip, down, up, comment)  # Suspensión es update a baja velocidad
                elif job.operation == "RESUME":
                    success = adapter.update_client(job.cliente_id, ip, down, up, comment)  # Reactivación
                
                if success:
                    duration = int((time.time() - start_time) * 1000)
                    job.status = "completed"
                    job.completed_at = datetime.utcnow()
                    job.result = {"status": "SUCCESS", "duration_ms": duration}
                    
                    # Actualizar estado QoS del cliente
                    state = LibreQoSManager.get_or_create_qos_state(job.cliente_id, db)
                    status_map = {
                        "PROVISION": "APPLIED",
                        "UPDATE": "APPLIED",
                        "REMOVE": "REMOVED",
                        "SUSPEND": "SUSPENDED",
                        "RESUME": "APPLIED"
                    }
                    
                    # Guardar auditoría antes de cambiar
                    aud = LibreQoSAuditLog(
                        cliente_id=job.cliente_id,
                        libreqos_server_id=server.id,
                        job_id=job.id,
                        operation=job.operation,
                        ip=ip,
                        download_before=state.download_mbps,
                        upload_before=state.upload_mbps,
                        status_before=state.status,
                        download_after=down if job.operation != "REMOVE" else 0,
                        upload_after=up if job.operation != "REMOVE" else 0,
                        status_after=status_map.get(job.operation, "APPLIED"),
                        result="SUCCESS",
                        duration_ms=duration,
                        correlation_id=job.correlation_id,
                        usuario=job.created_by
                    )
                    db.add(aud)
                    
                    state.status = status_map.get(job.operation, "APPLIED")
                    state.ip = ip if job.operation != "REMOVE" else None
                    state.download_mbps = down if job.operation != "REMOVE" else 0
                    state.upload_mbps = up if job.operation != "REMOVE" else 0
                    state.last_applied_at = datetime.utcnow()
                    state.last_verified_at = datetime.utcnow()
                    state.last_error = None
                    
                    db.commit()
                    
                    # EventBus Publish
                    EventBus.publish(f"LIBREQOS_{job.operation}ED", {
                        "cliente_id": job.cliente_id,
                        "server_id": server.id,
                        "ip": ip,
                        "download_mbps": down,
                        "upload_mbps": up
                    })
                    logger.info(f"✓ Operación {job.operation} ejecutada con éxito para cliente {job.cliente_id}")
                else:
                    self.handle_job_failure(job, db, "El adaptador SSH no retornó confirmación exitosa.")
                    
        except Exception as e:
            self.handle_job_failure(job, db, str(e))
        finally:
            sem.release()

    def handle_job_failure(self, job: LibreQoSJob, db, error_msg: str):
        """Gestiona el fallo de un trabajo, reencolando o marcando como fallido definitivo."""
        job.retry_count += 1
        job.error = error_msg
        
        # Guardar log de auditoría del fallo
        aud = LibreoQoSAuditLog_failed = LibreQoSAuditLog(
            cliente_id=job.cliente_id,
            libreqos_server_id=job.libreqos_server_id,
            job_id=job.id,
            operation=job.operation,
            result="FAILED",
            error=error_msg[:1000],
            correlation_id=job.correlation_id,
            usuario=job.created_by
        )
        db.add(aud)
        
        if job.retry_count < job.max_retries:
            # Backoff exponencial en minutos
            delay_minutes = 2 ** job.retry_count
            job.status = "retry"
            job.next_retry_at = datetime.utcnow() + timedelta(minutes=delay_minutes)
            logger.warning(f"Job {job.id} falló ({job.retry_count}/{job.max_retries}). Programado reintento en {delay_minutes} min. Error: {error_msg}")
        else:
            job.status = "failed"
            job.completed_at = datetime.utcnow()
            logger.error(f"Job {job.id} falló definitivamente tras {job.max_retries} intentos. Error: {error_msg}")
            
            # Actualizar estado QoS del cliente a FAILED
            state = LibreQoSManager.get_or_create_qos_state(job.cliente_id, db)
            state.status = "FAILED"
            state.last_error = error_msg
            
            EventBus.publish("LIBREQOS_FAILED", {
                "cliente_id": job.cliente_id,
                "error": error_msg,
                "operation": job.operation
            })
            
        db.commit()

if __name__ == "__main__":
    worker = LibreQoSWorker()
    worker.run()
