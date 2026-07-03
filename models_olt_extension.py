"""
OPSATEL ISP - OLT Models (Continuation of models.py)
======================================================
Modelos para gestión de tareas de aprovisionamiento OLT.

Nota: Este código debe ser agregado al final de models.py
"""

from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Numeric, Boolean, Text, JSON, BigInteger, Enum, TIMESTAMP
from sqlalchemy.orm import relationship
from database import Base
import datetime
import enum


class TaskStatusEnum(str, enum.Enum):
    """Estados posibles de una tarea"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRY = "retry"
    CANCELLED = "cancelled"


class OLTActionEnum(str, enum.Enum):
    """Acciones OLT disponibles"""
    ADD_ONT = "add_ont"
    REMOVE_ONT = "remove_ont"
    ADD_SERVICE = "add_service"
    DEL_SERVICE = "del_service"
    SET_BREACH = "set_breach"
    CHECK_POWER = "check_power"
    CONFIGURE_IPTV = "configure_iptv"


# ============================================================================
# MODELO: OLT Configuration
# ============================================================================

class OLTConfig(Base):
    """Configuración de OLTs (IP, credenciales, etc.)"""
    __tablename__ = "olt_config"
    
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), unique=True, nullable=False, index=True)
    host = Column(String(50), nullable=False)
    port = Column(Integer, default=23)
    username = Column(String(100), nullable=False)
    password = Column(String(100), nullable=False)
    device_type = Column(String(50), default="huawei_olt")  # huawei_olt, zte_olt, fiberhome_olt
    
    connection_timeout = Column(Integer, default=30)
    command_timeout = Column(Integer, default=30)
    max_retries = Column(Integer, default=3)
    retry_backoff_base = Column(Integer, default=1)
    
    active = Column(Boolean, default=True, index=True)
    nodo_asociado = Column(String(100), index=True)  # BAÑOS, SAYAUSI, etc.
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    created_by = Column(String(100))
    updated_by = Column(String(100))
    
    # Relaciones
    tasks = relationship("OLTTask", back_populates="olt_config")


# ============================================================================
# MODELO: OLT Task Queue
# ============================================================================

class OLTTask(Base):
    """Cola de tareas para aprovisionamiento OLT"""
    __tablename__ = "olt_tasks"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    cliente_id = Column(Integer, ForeignKey("hoja_de_c__lculo_sin_t__tulo.NUMERO"), nullable=False, index=True)
    olt_id = Column(Integer, ForeignKey("olt_config.id"), nullable=False, index=True)
    
    # Tipo y contenido de tarea
    action = Column(String(50), nullable=False, index=True)  # add_ont, add_service, etc.
    payload = Column(JSON, nullable=False)  # Parámetros en formato JSON
    
    # Estados y auditoría
    status = Column(String(50), default="pending", index=True, nullable=False)  # pending, processing, completed, failed, retry
    priority = Column(Integer, default=0)
    retry_count = Column(Integer, default=0)
    
    # Respuestas
    response = Column(Text)
    response_json = Column(JSON)
    error_message = Column(Text)
    error_code = Column(String(50))
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    # Auditoría
    created_by = Column(String(100))
    processed_by = Column(String(100))
    
    # Relaciones
    olt_config = relationship("OLTConfig", back_populates="tasks")
    logs = relationship("OLTTaskLog", back_populates="task")
    cliente = relationship("Cliente")


# ============================================================================
# MODELO: OLT Task Log (Auditoría)
# ============================================================================

class OLTTaskLog(Base):
    """Auditoría detallada de cada intento de tarea"""
    __tablename__ = "olt_task_logs"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    task_id = Column(BigInteger, ForeignKey("olt_tasks.id"), nullable=False, index=True)
    attempt = Column(Integer, nullable=False)
    
    # Estados
    status_before = Column(String(50))
    status_after = Column(String(50))
    
    # Detalles
    command_sent = Column(Text)  # Comando sanitizado
    raw_response = Column(Text)  # Respuesta raw de OLT
    
    # Resultado
    success = Column(Boolean)
    error_message = Column(String(500))
    
    # Timing
    duration_ms = Column(Integer)
    connection_time_ms = Column(Integer)
    
    log_message = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    
    # Relaciones
    task = relationship("OLTTask", back_populates="logs")


# ============================================================================
# MODELO: OLT Power Checks (Histórico)
# ============================================================================

class OLTPowerCheck(Base):
    """Histórico de verificaciones de potencia"""
    __tablename__ = "olt_power_checks"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    cliente_id = Column(Integer, ForeignKey("hoja_de_c__lculo_sin_t__tulo.NUMERO"), nullable=False, index=True)
    task_id = Column(BigInteger, ForeignKey("olt_tasks.id"), nullable=True)
    
    # Valores
    rx_power = Column(Numeric(5, 2))  # -23.45 dBm
    rx_power_status = Column(String(50))  # ok, warning, critical, error
    threshold_min = Column(Numeric(5, 2))  # -27.0
    
    # Equipo
    ont_id = Column(Integer)
    gpon_port = Column(String(20))  # 0/0/1
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)


# ============================================================================
# EXTENSIÓN: Cliente - Campos OLT
# ============================================================================
# Nota: Los siguientes campos deben ser agregados a la tabla Cliente via migration SQL:
#
# ALTER TABLE hoja_de_c__lculo_sin_t__tulo 
# ADD COLUMN IF NOT EXISTS olt_task_id BIGINT AFTER INSTALATION_DATE,
# ADD COLUMN IF NOT EXISTS potencia_verificada BOOLEAN DEFAULT FALSE,
# ADD COLUMN IF NOT EXISTS potencia_last_check TIMESTAMP NULL,
# ADD COLUMN IF NOT EXISTS olt_sync_status ENUM('pending', 'in_queue', 'synced', 'failed', 'error'),
# ADD COLUMN IF NOT EXISTS olt_error_message VARCHAR(500);
#
# Estos campos permiten:
# - olt_task_id: Última tarea OLT encolada
# - potencia_verificada: Flag de verificación exitosa
# - potencia_last_check: Timestamp de última verificación
# - olt_sync_status: Estado de sincronización con OLT
# - olt_error_message: Último mensaje de error

