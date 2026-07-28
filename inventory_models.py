"""
OPSATEL ISP - Network Inventory & Resource Manager Models
=========================================================
Modelos para la gestión centralizada de inventario de recursos de red:
- InventoryServicePort (Pool de Service Ports por OLT/Puerto GPON)
- InventoryOntId (Pool de ONT IDs 0-127 por puerto GPON)
- InventoryIpPool (Pool de Direcciones IP por Nodo)
- InventoryNap (Inventario de Cajas NAP y Splitters)

Autor: Arquitecto de Software Senior / CTO
Versión: 3.4.0 (Fase 3)
"""

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Numeric, Boolean, Text, JSON
from sqlalchemy.orm import relationship
from database import Base
import datetime

class InventoryServicePort(Base):
    """Pool de Service Ports inventariados"""
    __tablename__ = "inventory_service_ports"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    olt_id = Column(Integer, ForeignKey("olt_config.id"), nullable=False, index=True)
    gpon_port = Column(String(20), nullable=False, index=True) # ej: "0/0/15"
    service_port = Column(Integer, nullable=False, index=True) # ej: 1920
    
    estado = Column(String(50), default="LIBRE", index=True)    # LIBRE, RESERVADO, OCUPADO
    cliente_id = Column(Integer, ForeignKey("hoja_de_c__lculo_sin_t__tulo.NUMERO"), nullable=True, index=True)
    reserved_until = Column(DateTime, nullable=True)
    
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

class InventoryOntId(Base):
    """Pool de ONT IDs (0-127) por puerto GPON"""
    __tablename__ = "inventory_ont_ids"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    olt_id = Column(Integer, ForeignKey("olt_config.id"), nullable=False, index=True)
    gpon_port = Column(String(20), nullable=False, index=True) # ej: "0/0/15"
    ont_id = Column(Integer, nullable=False, index=True)       # 0 - 127
    
    estado = Column(String(50), default="LIBRE", index=True)    # LIBRE, RESERVADO, OCUPADO
    cliente_id = Column(Integer, ForeignKey("hoja_de_c__lculo_sin_t__tulo.NUMERO"), nullable=True, index=True)
    reserved_until = Column(DateTime, nullable=True)
    
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

class InventoryIpPool(Base):
    """Pool de Direcciones IP por Nodo"""
    __tablename__ = "inventory_ip_pools"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    nodo = Column(String(100), nullable=False, index=True)      # ej: "BAÑOS", "SAYAUSI"
    ip_address = Column(String(50), nullable=False, index=True)  # ej: "172.16.15.3"
    
    estado = Column(String(50), default="LIBRE", index=True)    # LIBRE, RESERVADO, OCUPADO
    cliente_id = Column(Integer, ForeignKey("hoja_de_c__lculo_sin_t__tulo.NUMERO"), nullable=True, index=True)
    pppoe_user = Column(String(100), nullable=True)
    
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
