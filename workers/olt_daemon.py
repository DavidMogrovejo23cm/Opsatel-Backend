#!/usr/bin/env python3
"""
OPSATEL ISP - OLT Provisioning Daemon
======================================
Servicio background que procesa la cola de tareas OLT.
Se ejecuta como: systemctl start opsatel-olt-worker

Características:
- Polling cada N segundos a BD por tareas pendientes
- Procesamiento secuencial (una tarea a la vez)
- Graceful shutdown (SIGTERM)
- File lock para una única instancia
- Logging detallado a archivo
- Compatible con systemd

Autor: Arquitecto de Software Senior
Versión: 1.0.0
"""

import os
import sys
import logging
import logging.handlers
import signal
import time
import fcntl
import json
import threading
from datetime import datetime
from pathlib import Path

# Configurar path para importar módulos del proyecto
# Agrega el directorio raíz del proyecto (/app) para poder importar database, services, etc.
_WORKERS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_WORKERS_DIR)
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, _WORKERS_DIR)

from database import SessionLocal
from services.task_processor import TaskProcessor
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import Session
# pyrefly: ignore [missing-import]
from sqlalchemy import text

# ============================================================================
# CONFIGURACIÓN
# ============================================================================

# Ubicaciones importantes (ajustar según deployment)
LOG_DIR = Path("/var/log/opsatel") if os.path.exists("/var/log") else Path("./logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

PID_FILE = Path("/var/run/opsatel-olt-worker.pid") if os.path.exists("/var/run") else Path("./opsatel-olt-worker.pid")
LOCK_FILE = Path("/var/run/opsatel-olt-worker.lock") if os.path.exists("/var/run") else Path("./opsatel-olt-worker.lock")

LOG_FILE = LOG_DIR / "olt-worker.log"
LOG_LEVEL = logging.DEBUG if os.getenv("DEBUG", "false").lower() == "true" else logging.INFO

# Parámetros del worker
POLL_INTERVAL = int(os.getenv("WORKER_POLL_INTERVAL", "1"))  # Segundos entre polls
BATCH_SIZE = int(os.getenv("WORKER_BATCH_SIZE", "5"))  # Tareas por ciclo
STARTUP_DELAY = int(os.getenv("WORKER_STARTUP_DELAY", "2"))  # Segundos antes de empezar

# ============================================================================
# LOGGER CONFIGURATION
# ============================================================================

def setup_logger():
    """Configura logging a archivo con rotación"""
    formatter = logging.Formatter(
        '[%(asctime)s] [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Handler: Archivo (con rotación)
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5  # Mantener 5 archivos viejos
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(LOG_LEVEL)
    
    # Handler: Consola (para systemd journal)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(LOG_LEVEL)
    
    # Logger raíz
    logger = logging.getLogger()
    logger.setLevel(LOG_LEVEL)
    logger.handlers.clear()
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

logger = setup_logger()

# ============================================================================
# DAEMON CLASS
# ============================================================================

class OLTDaemon:
    """
    Daemon para procesar tareas OLT.
    Maneja ciclo de vida, señales, locking.
    """
    
    def __init__(self):
        self.running = True
        self.lock_file_handle = None
        self.processor = None
        self.cycle_count = 0
        self.processed_count = 0
        self.error_count = 0
        self.last_error = None
        self.last_keepalive_time = 0
        
        # Registrar handlers de señales
        # Los handlers solo pueden registrarse desde el hilo principal.
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGTERM, self._handle_sigterm)
            signal.signal(signal.SIGINT, self._handle_sigterm)
            signal.signal(signal.SIGHUP, self._handle_sighup)
        
        logger.info("OLTDaemon inicializado")
    
    def _handle_sigterm(self, signum, frame):
        """Manejador de SIGTERM para graceful shutdown"""
        logger.warning(f"Recibida señal {signum} (SIGTERM/SIGINT). Iniciando graceful shutdown...")
        self.running = False
    
    def _handle_sighup(self, signum, frame):
        """Manejador de SIGHUP para recargar config (no implementado por ahora)"""
        logger.info(f"Recibida señal {signum} (SIGHUP). Reloading config...")
        # Aquí se podría recargar config de BD
    
    def acquire_lock(self) -> bool:
        """
        Adquiere file lock para asegurar que solo una instancia corre.
        Retorna: True si lock adquirido, False si otro proceso tiene el lock.
        """
        try:
            self.lock_file_handle = open(LOCK_FILE, 'w')
            fcntl.flock(self.lock_file_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.lock_file_handle.write(f"{os.getpid()}\n")
            self.lock_file_handle.flush()
            logger.info(f"Lock adquirido exitosamente: {LOCK_FILE}")
            return True
        except IOError:
            logger.error(f"No se puede adquirir lock (otro worker está activo): {LOCK_FILE}")
            return False
        except Exception as e:
            logger.error(f"Error adquiriendo lock: {e}")
            return False
    
    def release_lock(self):
        """Libera el file lock"""
        if self.lock_file_handle:
            try:
                fcntl.flock(self.lock_file_handle.fileno(), fcntl.LOCK_UN)
                self.lock_file_handle.close()
                logger.info(f"Lock liberado: {LOCK_FILE}")
            except:
                pass
    
    def write_pid_file(self):
        """Escribe el PID a archivo"""
        try:
            with open(PID_FILE, 'w') as f:
                f.write(f"{os.getpid()}\n")
            logger.info(f"PID escrito a: {PID_FILE}")
        except Exception as e:
            logger.warning(f"No se pudo escribir PID file: {e}")
    
    def remove_pid_file(self):
        """Borra el archivo PID"""
        try:
            PID_FILE.unlink()
        except:
            pass
    
    def _test_db_connection(self) -> bool:
        """Verifica que la conexión a BD esté disponible antes de empezar."""
        try:
            db = SessionLocal()
            db.execute(text("SELECT 1"))
            db.close()
            logger.info("Conexión a BD verificada")
            return True
        except Exception as e:
            logger.error(f"Error conectando a BD: {e}")
            return False

    def _rescue_stuck_tasks(self):
        """Al arrancar, rescata tareas atascadas en estado 'processing'.
        Esto ocurre cuando el worker se cae mientras estaba ejecutando una tarea.
        Las marca de vuelta a 'pending' para que se reintenten.
        """
        try:
            import models
            db = SessionLocal()
            stuck = db.query(models.OLTTask).filter(
                models.OLTTask.status == 'processing'
            ).all()
            if stuck:
                logger.warning(f"Encontradas {len(stuck)} tarea(s) atascadas en 'processing'. Rescatando...")
                for t in stuck:
                    t.status = 'pending'
                    t.error_message = (t.error_message or '') + ' | Rescatada al reinicio del worker'
                db.commit()
                logger.info(f"{len(stuck)} tarea(s) devueltas a 'pending'")
            db.close()
        except Exception as e:
            logger.error(f"Error rescatando tareas: {e}")
    
    def start(self):
        """Inicia el daemon"""
        logger.info("="*70)
        logger.info("OPSATEL OLT PROVISIONING DAEMON - INICIO")
        logger.info("="*70)
        logger.info(f"Versión: 1.0.0")
        logger.info(f"PID: {os.getpid()}")
        logger.info(f"Poll Interval: {POLL_INTERVAL}s")
        logger.info(f"Batch Size: {BATCH_SIZE}")
        logger.info(f"Log File: {LOG_FILE}")
        
        # Adquirir lock
        if not self.acquire_lock():
            logger.error("No se puede iniciar: otro worker está activo")
            return False
        
        # Escribir PID
        self.write_pid_file()
        
        # Verificar BD
        if not self._test_db_connection():
            logger.error("No se puede conectar a BD. Abortando.")
            self.release_lock()
            self.remove_pid_file()
            return False
        
        # Rescatar tareas atascadas de una corrida anterior
        self._rescue_stuck_tasks()

        # Inicializar el procesador de tareas una única vez para preservar caché SSH
        try:
            self.processor = TaskProcessor()
            logger.info("TaskProcessor inicializado")
            
            # Pre-conectar a todas las OLTs activas en segundo plano
            try:
                db_session = SessionLocal()
                self.processor.pre_connect_active_olts(db_session)
                db_session.close()
            except Exception as pe:
                logger.error(f"Error en pre-conexión de OLTs: {pe}")
        except Exception as e:
            logger.error(f"Error inicializando TaskProcessor: {e}")
            self.release_lock()
            self.remove_pid_file()
            return False
        
        # Esperar antes de empezar
        logger.info(f"Esperando {STARTUP_DELAY}s antes de iniciar ciclos...")
        time.sleep(STARTUP_DELAY)
        
        # LOOP PRINCIPAL
        # IMPORTANTE: Se crea una sesión nueva por ciclo para evitar que
        # una sesión SQLAlchemy estancada bloquee el procesamiento.
        logger.info("Iniciando loop de procesamiento...")
        
        try:
            while self.running:
                self.cycle_count += 1
                cycle_start = time.time()
                db = None
                
                try:
                    logger.debug(f"========== CICLO {self.cycle_count} ==========")
                    
                    # Crear sesión fresca en cada ciclo
                    db = SessionLocal()
                    self.processor.db = db
                    
                    # ── Heartbeat Update en DB ──
                    try:
                        import observability
                        import socket
                        hb = db.query(observability.WorkerHeartbeat).filter(
                            observability.WorkerHeartbeat.worker_name == "olt_daemon"
                        ).first()
                        if not hb:
                            hb = observability.WorkerHeartbeat(
                                worker_name="olt_daemon",
                                pid=os.getpid(),
                                hostname=socket.gethostname(),
                                status="RUNNING"
                            )
                            db.add(hb)
                        else:
                            hb.pid = os.getpid()
                            hb.status = "RUNNING"
                            hb.cycle_count = self.cycle_count
                            hb.processed_count = self.processed_count
                            hb.error_count = self.error_count
                            hb.last_seen = datetime.utcnow()
                        db.commit()
                    except Exception as hb_err:
                        logger.warning(f"No se pudo actualizar Heartbeat: {hb_err}")

                    # Contar pendientes (diagnóstico)
                    import models as _m
                    pending_count = db.query(_m.OLTTask).filter(
                        _m.OLTTask.status.in_(['pending', 'retry'])
                    ).count()
                    
                    if pending_count > 0:
                        logger.info(f"[Ciclo {self.cycle_count}] {pending_count} tarea(s) pendiente(s)")
                    
                    # Procesar
                    processed = self.processor.process_pending_tasks(batch_size=BATCH_SIZE)
                    self.processed_count += processed

                    
                    if processed > 0:
                        logger.info(f"[Ciclo {self.cycle_count}] Procesadas {processed} tarea(s)")
                    else:
                        # Si no hay tareas procesadas, ejecutar keepalive silencioso cada 60s
                        now = time.time()
                        if now - self.last_keepalive_time >= 60:
                            try:
                                self.processor.run_keepalive()
                            except Exception as ke:
                                logger.warning(f"Error ejecutando keepalive en daemon: {ke}")
                            self.last_keepalive_time = now
                    
                    self.error_count = 0
                    self.last_error = None
                
                except Exception as e:
                    self.error_count += 1
                    self.last_error = str(e)
                    logger.exception(f"[Ciclo {self.cycle_count}] Error en procesamiento")
                    
                    if self.error_count > 5:
                        logger.warning(f"Demasiados errores ({self.error_count}). Esperando 30s...")
                        time.sleep(30)
                
                finally:
                    # Siempre cerrar y limpiar la sesión del ciclo
                    if db is not None:
                        try:
                            db.close()
                        except:
                            pass
                    if self.processor:
                        self.processor.db = None
                
                # Esperar hasta el siguiente ciclo
                cycle_duration = time.time() - cycle_start
                wait_time = max(0, POLL_INTERVAL - cycle_duration)
                if wait_time > 0:
                    time.sleep(wait_time)
        
        except KeyboardInterrupt:
            logger.info("Interrumpido por usuario")
        
        except Exception as e:
            logger.error(f"Error crítico en loop principal: {type(e).__name__}: {e}")
        
        finally:
            self.shutdown()
        
        return True
    
    def shutdown(self):
        """Shutdown graceful"""
        logger.info("="*70)
        logger.info("INICIANDO GRACEFUL SHUTDOWN")
        logger.info("="*70)
        
        # Estadísticas
        logger.info(f"Ciclos completados: {self.cycle_count}")
        logger.info(f"Tareas procesadas: {self.processed_count}")
        logger.info(f"Errores: {self.error_count}")
        if self.last_error:
            logger.info(f"Último error: {self.last_error}")
        
        # Desconectar OLTs
        if self.processor:
            try:
                logger.info("Desconectando OLTs...")
                self.processor.disconnect_all()
            except Exception as e:
                logger.warning(f"Error desconectando: {e}")

        # Liberar lock y PID
        self.release_lock()
        self.remove_pid_file()
        
        logger.info("="*70)
        logger.info("DAEMON DETENIDO")
        logger.info("="*70)


# ============================================================================
# ENTRY POINT
# ============================================================================

def main():
    """Punto de entrada principal"""
    try:
        daemon = OLTDaemon()
        success = daemon.start()
        return 0 if success else 1
    
    except Exception as e:
        logger.error(f"Error fatal en main: {type(e).__name__}: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
