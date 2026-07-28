"""
OPSATEL ISP - Network Discovery Models
=======================================
Modelos de datos para almacenar el estado físico-lógico de la OLT
recopilado en tiempo real durante los ciclos de Auto-Descubrimiento.

Autor: Arquitecto de Software Senior / CTO
Versión: 3.2.0 (Fase 1)
"""

# pyrefly: ignore [missing-import]
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Numeric, Boolean, Text, JSON
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import relationship
from database import Base
import datetime

class DiscoveredONT(Base):
    """Representa una ONT descubierta en tiempo real en la OLT"""
    __tablename__ = "discovered_onts"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    olt_id = Column(Integer, ForeignKey("olt_config.id"), nullable=False, index=True)
    
    gpon_port = Column(String(20), nullable=False, index=True) # ej: "0/0/15"
    ont_id = Column(Integer, nullable=False, index=True)      # ej: 3
    sn_mac = Column(String(50), nullable=False, index=True)    # ej: "48575443A1B2C3D4"
    
    status = Column(String(50), default="online")              # online, offline, initial
    description = Column(String(255), nullable=True)          # Descripción asignada en OLT
    
    # Vinculación con BD Opsatel
    cliente_id = Column(Integer, ForeignKey("hoja_de_c__lculo_sin_t__tulo.NUMERO"), nullable=True, index=True)
    sync_state = Column(String(50), default="MATCHED")         # MATCHED, ORPHAN_IN_OLT, MISSING_IN_OLT
    
    last_discovered_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class DiscoveredServicePort(Base):
    """Representa un Service Port descubierto en la OLT"""
    __tablename__ = "discovered_service_ports"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    olt_id = Column(Integer, ForeignKey("olt_config.id"), nullable=False, index=True)
    
    service_port = Column(Integer, nullable=False, index=True) # ej: 1920
    vlan_id = Column(Integer, nullable=False)                  # ej: 308
    gpon_port = Column(String(20), nullable=False, index=True) # ej: "0/0/15"
    ont_id = Column(Integer, nullable=False)                   # ej: 3
    gemport = Column(Integer, nullable=True)                   # ej: 108
    user_vlan = Column(Integer, nullable=True)                # ej: 108
    
    cliente_id = Column(Integer, ForeignKey("hoja_de_c__lculo_sin_t__tulo.NUMERO"), nullable=True, index=True)
    sync_state = Column(String(50), default="MATCHED")         # MATCHED, ORPHAN_IN_OLT
    
    last_discovered_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)

class DiscoveredBoard(Base):
    """Estado de placas/tarjetas del chasis OLT"""
    __tablename__ = "discovered_boards"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    olt_id = Column(Integer, ForeignKey("olt_config.id"), nullable=False, index=True)
    
    slot = Column(Integer, nullable=False)                     # ej: 0, 1, 2
    board_type = Column(String(50), nullable=False)            # ej: "H806GPBD", "Control Board"
    status = Column(String(50), default="Normal")              # Normal, Failed, Empty
    ports_count = Column(Integer, default=16)
    
    last_discovered_at = Column(DateTime, default=datetime.datetime.utcnow)
