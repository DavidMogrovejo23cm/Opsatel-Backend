"""
OPSATEL ISP - LibreQoS Multi-Server Models
==========================================
Modelos para la gestión de múltiples servidores LibreQoS remotos mediante SSH.

Tablas:
- LibreQoSServer     : Inventario de servidores LibreQoS
- ClientQoSState     : Estado QoS por cliente (desired vs actual)
- LibreQoSJob        : Cola de trabajos asíncronos por servidor
- LibreQoSAuditLog   : Auditoría inmutable de operaciones (sin credenciales)

Autor: Arquitecto de Software Senior / CTO
Versión: 1.0.0
"""

# pyrefly: ignore [missing-import]
from sqlalchemy import (
    Column, Integer, BigInteger, String, Boolean, DateTime,
    Text, JSON, ForeignKey, Numeric
)
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import relationship
from database import Base
import datetime


# ============================================================================
# LIBREQOS SERVER — Inventario de servidores remotos
# ============================================================================

class LibreQoSServer(Base):
    """Inventario de servidores LibreQoS remotos accedidos por SSH."""
    __tablename__ = "libreqos_servers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)  # ej: "LibreQoS-Norte"
    host = Column(String(255), nullable=False)                            # IP o hostname
    ssh_port = Column(Integer, default=22, nullable=False)
    username = Column(String(100), nullable=False)

    # Autenticación SSH (password o clave privada)
    auth_method = Column(String(20), default="password", nullable=False)  # "password" | "key"
    password = Column(String(255), nullable=True)                          # Solo si auth_method="password"
    private_key_path = Column(String(500), nullable=True)                  # Ruta en sistema de archivos Opsatel
    passphrase = Column(String(255), nullable=True)                        # Passphrase opcional de la clave

    # Estado operativo
    enabled = Column(Boolean, default=True, index=True)
    status = Column(String(20), default="UNKNOWN", index=True)            # ONLINE | OFFLINE | UNKNOWN
    last_check = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)

    # Parámetros de conexión
    ssh_timeout = Column(Integer, default=30)
    ssh_retries = Column(Integer, default=3)
    max_concurrent_jobs = Column(Integer, default=5)

    # Configuración LibreQoS en el servidor remoto
    libreqos_path = Column(String(500), default="/opt/libreqos")
    # Comando para listar clientes shaped (debe escribir JSON a stdout)
    libreqos_list_cmd = Column(String(500), default="sudo python3 /opt/libreqos/src/rust_integration/ispConfig.py --list-shaped-json 2>/dev/null || cat /etc/libreqos/shaped_clients.json 2>/dev/null || echo '[]'")
    # Comando para aplicar la configuración luego de modificar ispConfig.py
    libreqos_apply_cmd = Column(String(500), default="cd /opt/libreqos && sudo python3 src/rust_integration/generate_and_apply.sh 2>&1 || sudo python3 /opt/libreqos/src/ispConfig.py apply 2>&1 || echo 'APPLY_DONE'")
    # Ruta del archivo de configuración de clientes (ispConfig.py o equivalente)
    libreqos_config_file = Column(String(500), default="/opt/libreqos/src/ispConfig.py")

    # Política de suspensión (velocidad aplicada cuando el cliente está suspendido)
    suspension_download_mbps = Column(Integer, default=1)
    suspension_upload_mbps = Column(Integer, default=1)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    created_by = Column(String(100), nullable=True)

    # Relaciones
    qos_states = relationship("ClientQoSState", back_populates="libreqos_server")
    jobs = relationship("LibreQoSJob", back_populates="libreqos_server")
    audit_logs = relationship("LibreQoSAuditLog", back_populates="libreqos_server")


# ============================================================================
# CLIENT QOS STATE — Estado QoS deseado vs aplicado por cliente
# ============================================================================

class ClientQoSState(Base):
    """Estado QoS deseado y aplicado para cada cliente."""
    __tablename__ = "client_qos_state"

    id = Column(Integer, primary_key=True, index=True)
    cliente_id = Column(Integer, ForeignKey("hoja_de_c__lculo_sin_t__tulo.NUMERO"), nullable=False, unique=True, index=True)
    libreqos_server_id = Column(Integer, ForeignKey("libreqos_servers.id"), nullable=True, index=True)

    # Estado QoS actual
    status = Column(String(30), default="PENDING", index=True)
    # Posibles: PENDING | APPLYING | APPLIED | FAILED | DRIFT | SUSPENDED | REMOVED

    # Configuración aplicada en LibreQoS
    ip = Column(String(50), nullable=True)
    download_mbps = Column(Integer, nullable=True)
    upload_mbps = Column(Integer, nullable=True)

    # Timestamps de operaciones
    last_applied_at = Column(DateTime, nullable=True)
    last_verified_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)

    # Snapshot de la configuración aplicada (para rollback)
    applied_config = Column(JSON, nullable=True)

    # Trazabilidad
    correlation_id = Column(String(100), nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relaciones
    libreqos_server = relationship("LibreQoSServer", back_populates="qos_states")


# ============================================================================
# LIBREQOS JOB — Cola de trabajos asíncronos
# ============================================================================

class LibreQoSJob(Base):
    """Cola de trabajos asíncronos para el worker de LibreQoS."""
    __tablename__ = "libreqos_jobs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    cliente_id = Column(Integer, ForeignKey("hoja_de_c__lculo_sin_t__tulo.NUMERO"), nullable=False, index=True)
    libreqos_server_id = Column(Integer, ForeignKey("libreqos_servers.id"), nullable=True, index=True)

    # Operación
    operation = Column(String(30), nullable=False, index=True)
    # Posibles: PROVISION | UPDATE | SUSPEND | RESUME | REMOVE | VERIFY | RECONCILE

    # Datos del job
    payload = Column(JSON, nullable=True)  # {ip, download_mbps, upload_mbps, ...}

    # Control de estado
    status = Column(String(20), default="pending", index=True, nullable=False)
    # pending | processing | completed | failed | retry | cancelled

    priority = Column(Integer, default=0, index=True)                  # Mayor = más urgente
    retry_count = Column(Integer, default=0, nullable=False)
    max_retries = Column(Integer, default=3, nullable=False)
    next_retry_at = Column(DateTime, nullable=True, index=True)        # Para reintentos con backoff

    # Resultado
    result = Column(JSON, nullable=True)                               # Resultado de la operación
    error = Column(Text, nullable=True)                                # Último error

    # Trazabilidad
    correlation_id = Column(String(100), nullable=True, index=True)
    created_by = Column(String(100), nullable=True)
    processed_by = Column(String(100), nullable=True)                 # Nombre del worker

    # Timestamps
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Relaciones
    libreqos_server = relationship("LibreQoSServer", back_populates="jobs")


# ============================================================================
# LIBREQOS AUDIT LOG — Auditoría sin credenciales
# ============================================================================

class LibreQoSAuditLog(Base):
    """
    Registro de auditoría inmutable de operaciones LibreQoS.
    NUNCA contiene: passwords, private keys, passphrases.
    """
    __tablename__ = "libreqos_audit"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    cliente_id = Column(Integer, ForeignKey("hoja_de_c__lculo_sin_t__tulo.NUMERO"), nullable=True, index=True)
    libreqos_server_id = Column(Integer, ForeignKey("libreqos_servers.id"), nullable=True, index=True)
    job_id = Column(BigInteger, nullable=True, index=True)

    # Qué se hizo
    operation = Column(String(30), nullable=False, index=True)
    ip = Column(String(50), nullable=True)

    # Estado antes y después
    download_before = Column(Integer, nullable=True)
    upload_before = Column(Integer, nullable=True)
    status_before = Column(String(30), nullable=True)
    download_after = Column(Integer, nullable=True)
    upload_after = Column(Integer, nullable=True)
    status_after = Column(String(30), nullable=True)

    # Resultado
    result = Column(String(20), nullable=False)  # SUCCESS | FAILED | SKIPPED | DRIFT
    duration_ms = Column(Integer, default=0)
    error = Column(Text, nullable=True)

    # Trazabilidad
    correlation_id = Column(String(100), nullable=True, index=True)
    usuario = Column(String(100), nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)

    # Relaciones
    libreqos_server = relationship("LibreQoSServer", back_populates="audit_logs")
