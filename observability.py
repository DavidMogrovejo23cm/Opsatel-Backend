"""
OPSATEL ISP - Observability & Telemetry Module v3.1
==================================================
Proporciona:
- Middleware de Correlation-ID (X-Correlation-ID)
- AuditEvent con ejecución en background no-bloqueante (Best-Effort)
- NetworkCommand History (trazabilidad de comandos CLI a equipos)
- WorkerHeartbeat (sistema de salud en tiempo real de workers)
- Health Check avanzado (/health y /health/live)
- Logger Estructurado JSON (apto para Grafana/Loki)

Autor: Arquitecto de Software Senior / CTO
Versión: 3.1.0
"""

import os
import sys
import time
import logging
import json
import uuid
import threading
from queue import Queue
from datetime import datetime
from typing import Dict, Any, Optional, List

# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, Header, Request, Response
# pyrefly: ignore [missing-import]
from starlette.middleware.base import BaseHTTPMiddleware
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import Session
# pyrefly: ignore [missing-import]
from sqlalchemy import text, Column, Integer, String, DateTime, Text, JSON, Float, Boolean
import database
from database import get_db, Base, SessionLocal

logger = logging.getLogger("opsatel.observability")

# ============================================================================
# LOGGING ESTRUCTURADO JSON
# ============================================================================

class JSONFormatter(logging.Formatter):
    """Formateador de logs en formato JSON estructurado"""
    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
        }
        if hasattr(record, "correlation_id"):
            log_obj["correlation_id"] = getattr(record, "correlation_id")
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_obj, ensure_ascii=False)

def setup_json_logging():
    """Configura el logger de observabilidad para usar salida JSON estructurada"""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

# ============================================================================
# MODELOS DE DATOS: AUDITORÍA, COMANDOS Y HEARTBEAT
# ============================================================================

class AuditEvent(Base):
    """Modelo de base de datos para auditoría inmutable de eventos"""
    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    usuario = Column(String(100), index=True, nullable=True)
    ip_origen = Column(String(50), nullable=True)
    accion = Column(String(100), index=True, nullable=False) # ej: "ONT_ADD", "PAYMENT_REGISTER"
    modulo = Column(String(50), index=True, nullable=False) # ej: "huawei", "mikrotik", "billing"
    entidad_tipo = Column(String(50), nullable=True) # ej: "Cliente", "OLTTask"
    entidad_id = Column(String(100), nullable=True)
    
    estado_antes = Column(JSON, nullable=True)
    estado_despues = Column(JSON, nullable=True)
    detalles = Column(Text, nullable=True)
    duracion_ms = Column(Integer, default=0)
    
    correlation_id = Column(String(100), index=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

class NetworkCommand(Base):
    """Historial detallado de comandos CLI ejecutados en equipos de red (OLT/RouterOS)"""
    __tablename__ = "network_commands"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    workflow = Column(String(100), index=True, nullable=True)  # ej: "ACTIVAR_CLIENTE"
    equipo = Column(String(100), index=True, nullable=False)   # ej: "OLT_BAÑOS_01"
    comando = Column(Text, nullable=False)                     # ej: "ont add 0 1 sn-auth ..."
    respuesta = Column(Text, nullable=True)                    # Respuesta cruda del CLI
    duracion_ms = Column(Integer, default=0)
    exit_status = Column(String(50), default="SUCCESS")        # SUCCESS, ERROR, TIMEOUT, ALREADY_EXISTS
    retry_count = Column(Integer, default=0)
    correlation_id = Column(String(100), index=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

class WorkerHeartbeat(Base):
    """Mecanismo de salud en tiempo real para Workers independientes"""
    __tablename__ = "worker_heartbeats"

    worker_name = Column(String(100), primary_key=True, index=True) # ej: "olt_daemon"
    pid = Column(Integer, nullable=False)
    hostname = Column(String(100), nullable=True)
    status = Column(String(50), default="RUNNING")                   # RUNNING, STOPPING, FAILED
    cycle_count = Column(Integer, default=0)
    processed_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    last_seen = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    started_at = Column(DateTime, default=datetime.utcnow)

# ============================================================================
# AUDITORÍA ASÍNCRONA BEST-EFFORT (WORKER THREAD)
# ============================================================================

_audit_queue: Queue = Queue(maxsize=5000)

def _audit_worker_loop():
    """Hilo secundario que procesa la cola de auditoría de forma asíncrona"""
    while True:
        try:
            event_data = _audit_queue.get()
            if event_data is None:
                break
            
            db = SessionLocal()
            try:
                audit_entry = AuditEvent(**event_data)
                db.add(audit_entry)
                db.commit()
            except Exception as e:
                db.rollback()
                logger.error(f"[AsyncAudit] Error guardando evento en DB: {e}")
            finally:
                db.close()
                _audit_queue.task_done()
        except Exception as err:
            logger.error(f"[AsyncAudit] Error insospechado en loop de auditoría: {err}")

# Iniciar hilo de auditoría background
_audit_thread = threading.Thread(target=_audit_worker_loop, daemon=True, name="AsyncAuditThread")
_audit_thread.start()

def log_audit_event_async(
    accion: str,
    modulo: str,
    usuario: Optional[str] = "SYSTEM",
    ip_origen: Optional[str] = None,
    entidad_tipo: Optional[str] = None,
    entidad_id: Optional[str] = None,
    estado_antes: Optional[Dict[str, Any]] = None,
    estado_despues: Optional[Dict[str, Any]] = None,
    detalles: Optional[str] = None,
    duracion_ms: int = 0,
    correlation_id: Optional[str] = None
) -> None:
    """
    Encola un evento de auditoría para ser procesado asíncronamente sin bloquear la transacción principal.
    Garantiza 'best effort' (nunca rompe el flujo de negocio si la auditoría falla).
    """
    event_data = {
        "usuario": usuario,
        "ip_origen": ip_origen,
        "accion": accion,
        "modulo": modulo,
        "entidad_tipo": entidad_tipo,
        "entidad_id": str(entidad_id) if entidad_id is not None else None,
        "estado_antes": estado_antes,
        "estado_despues": estado_despues,
        "detalles": detalles,
        "duracion_ms": duracion_ms,
        "correlation_id": correlation_id
    }
    try:
        _audit_queue.put_nowait(event_data)
    except Exception as e:
        logger.warning(f"[AsyncAudit] Cola llena o inservible: {e}")

# ============================================================================
# HELPER COMANDOS DE RED (NETWORK COMMAND LOGGING)
# ============================================================================

def log_network_command(
    equipo: str,
    comando: str,
    respuesta: Optional[str] = None,
    workflow: Optional[str] = None,
    duracion_ms: int = 0,
    exit_status: str = "SUCCESS",
    retry_count: int = 0,
    correlation_id: Optional[str] = None
) -> None:
    """Registra en DB el comando CLI enviado a un equipo de red (OLT/RouterOS)"""
    def _save():
        db = SessionLocal()
        try:
            cmd_entry = NetworkCommand(
                workflow=workflow,
                equipo=equipo,
                comando=comando,
                respuesta=respuesta[:4000] if respuesta else None, # Limitar tamaño
                duracion_ms=duracion_ms,
                exit_status=exit_status,
                retry_count=retry_count,
                correlation_id=correlation_id
            )
            db.add(cmd_entry)
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"Fallo al registrar comando de red: {e}")
        finally:
            db.close()

    # Ejecutar en hilo no-bloqueante
    threading.Thread(target=_save, daemon=True).start()

# ============================================================================
# MIDDLEWARE: CORRELATION ID & REQUEST TIME
# ============================================================================

class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """
    Middleware FastAPI/Starlette que inyecta un Correlation-ID único en cada petición HTTP.
    Si el cliente o proxy envía 'X-Correlation-ID', lo reutiliza; de lo contrario genera un UUIDv4.
    """
    async def dispatch(self, request: Request, call_next) -> Response:
        correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
        request.state.correlation_id = correlation_id
        start_time = time.time()
        
        response: Response = await call_next(request)
        
        duration_ms = int((time.time() - start_time) * 1000)
        response.headers["X-Correlation-ID"] = correlation_id
        response.headers["X-Process-Time-MS"] = str(duration_ms)
        return response

# ============================================================================
# HEALTH CHECK ROUTER
# ============================================================================

router = APIRouter(prefix="/health", tags=["Observability & Health"])

@router.get("", summary="Health Check completo del sistema")
def get_system_health(db: Session = Depends(get_db)):
    """
    Verifica la salud detallada de los servicios críticos del ISP:
    - Base de Datos MySQL (Conexiones y Latencia)
    - Heartbeat activo de Workers (OLT Worker)
    """
    start_time = time.time()
    db_status = "DOWN"
    db_latency_ms = 0
    active_connections = 0
    
    # 1. Verificar MySQL y pool de conexiones
    try:
        db_start = time.time()
        res = db.execute(text("SHOW STATUS LIKE 'Threads_connected'")).fetchone()
        if res:
            active_connections = int(res[1])
        db_latency_ms = int((time.time() - db_start) * 1000)
        db_status = "UP"
    except Exception as e:
        logger.error(f"Health Check: MySQL DOWN - {e}")
        db_status = f"DOWN: {str(e)}"

    # 2. Verificar Heartbeat de OLT Worker en DB
    worker_health = "UNKNOWN"
    worker_last_seen = None
    try:
        hb = db.query(WorkerHeartbeat).filter(WorkerHeartbeat.worker_name == "olt_daemon").first()
        if hb:
            worker_last_seen = hb.last_seen.isoformat() + "Z"
            # Si el último latido fue hace menos de 30 segundos, está VIVO
            seconds_since = (datetime.utcnow() - hb.last_seen).total_seconds()
            if seconds_since <= 30 and hb.status == "RUNNING":
                worker_health = "RUNNING"
            else:
                worker_health = f"DEAD (last seen {int(seconds_since)}s ago)"
        else:
            worker_health = "NO_HEARTBEAT_RECORD"
    except Exception as e:
        worker_health = f"ERROR_CHECKING: {e}"

    total_latency_ms = int((time.time() - start_time) * 1000)
    overall_status = "HEALTHY" if (db_status == "UP" and "RUNNING" in worker_health) else "DEGRADED"

    return {
        "status": overall_status,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "latency_ms": total_latency_ms,
        "components": {
            "database": {
                "status": db_status,
                "latency_ms": db_latency_ms,
                "active_connections": active_connections
            },
            "olt_worker": {
                "status": worker_health,
                "last_seen": worker_last_seen
            }
        },
        "system": {
            "python_version": sys.version.split()[0],
            "pid": os.getpid()
        }
    }

@router.get("/live", summary="Liveness probe para Docker/K8s")
def liveness_probe():
    """Retorna 200 OK inmediatamente si la API está respondiendo HTTP"""
    return {"status": "ALIVE", "timestamp": datetime.utcnow().isoformat() + "Z"}

