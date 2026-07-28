"""
OPSATEL ISP - Resource Manager Service
======================================
Servicio encargado de la reserva atómica, asignación y liberación de recursos de red:
- ONT IDs (0-127)
- Service Ports
- Direcciones IP

REGLA DE ORO: Mantiene inventario local en BD, pero antes de realizar la reserva
valida en tiempo real la disponibilidad física en la OLT (la OLT es la fuente de verdad).

Autor: Arquitecto de Software Senior / CTO
Versión: 3.4.0 (Fase 3)
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple

from sqlalchemy.orm import Session
import inventory_models
import models
import observability
from services.olt_interface import OLTInterface

logger = logging.getLogger("opsatel.resource_manager")

class ResourceManager:
    """Administrador atómico de recursos de red"""

    def __init__(self, db: Session):
        self.db = db

    def reserve_ont_id(self, olt_id: int, gpon_port: str, olt_interface: Optional[OLTInterface] = None) -> int:
        """
        Reserva el primer ONT ID libre para el puerto GPON especificado.
        Valida en tiempo real en la OLT si la interfaz está disponible.
        """
        logger.info(f"[ResourceManager] Solicitando reserva de ONT ID en OLT {olt_id}, puerto GPON {gpon_port}...")

        # 1. Obtener ONT IDs ocupados en la OLT en tiempo real (si hay sesión activa)
        existing_in_olt = set()
        if olt_interface and olt_interface.is_connected:
            try:
                olt_interface._ensure_config_mode()
                existing_in_olt = set(olt_interface.get_existing_ont_ids(gpon_port))
            except Exception as e:
                logger.warning(f"[ResourceManager] No se pudo consultar OLT en tiempo real: {e}")

        # 2. Obtener ONT IDs ocupados o reservados en la BD de Opsatel
        reserved_in_db = self.db.query(inventory_models.InventoryOntId).filter(
            inventory_models.InventoryOntId.olt_id == olt_id,
            inventory_models.InventoryOntId.gpon_port == gpon_port,
            inventory_models.InventoryOntId.estado.in_(["RESERVADO", "OCUPADO"])
        ).all()
        db_occupied_ids = {r.ont_id for r in reserved_in_db}

        # 3. Buscar el primer ID libre entre 0 y 127
        selected_ont_id = None
        for i in range(128):
            if i not in existing_in_olt and i not in db_occupied_ids:
                selected_ont_id = i
                break

        if selected_ont_id is None:
            raise ValueError(f"No hay ONT IDs libres disponibles en {gpon_port} (0-127 agotados)")

        # 4. Registrar la reserva en el inventario
        rec = self.db.query(inventory_models.InventoryOntId).filter(
            inventory_models.InventoryOntId.olt_id == olt_id,
            inventory_models.InventoryOntId.gpon_port == gpon_port,
            inventory_models.InventoryOntId.ont_id == selected_ont_id
        ).first()

        if not rec:
            rec = inventory_models.InventoryOntId(
                olt_id=olt_id,
                gpon_port=gpon_port,
                ont_id=selected_ont_id,
                estado="RESERVADO",
                reserved_until=datetime.utcnow() + timedelta(minutes=15)
            )
            self.db.add(rec)
        else:
            rec.estado = "RESERVADO"
            rec.reserved_until = datetime.utcnow() + timedelta(minutes=15)

        self.db.commit()
        logger.info(f"[ResourceManager] ✓ ONT ID {selected_ont_id} reservado exitosamente para {gpon_port}")
        return selected_ont_id

    def reserve_service_port(self, olt_id: int, gpon_port: str, olt_interface: Optional[OLTInterface] = None) -> int:
        """
        Reserva el primer Service Port libre dentro del rango calculado por puerto GPON.
        """
        # Extraer número de puerto del gpon_port (ej: "0/0/15" -> 15)
        parts = [p.strip() for p in str(gpon_port).split('/') if p.strip()]
        port_index = int(parts[2]) if len(parts) >= 3 else 0

        sp_start = port_index * 128
        sp_end = sp_start + 127

        logger.info(f"[ResourceManager] Reservando Service Port en rango [{sp_start}..{sp_end}] para {gpon_port}...")

        # Consultar OLT en tiempo real
        existing_in_olt = set()
        if olt_interface and olt_interface.is_connected:
            try:
                olt_interface._ensure_config_mode()
                existing_in_olt = set(olt_interface.get_existing_service_ports(gpon_port))
            except Exception as e:
                logger.warning(f"[ResourceManager] Error consultando service ports en OLT: {e}")

        # Consultar BD
        reserved_in_db = self.db.query(inventory_models.InventoryServicePort).filter(
            inventory_models.InventoryServicePort.olt_id == olt_id,
            inventory_models.InventoryServicePort.service_port >= sp_start,
            inventory_models.InventoryServicePort.service_port <= sp_end,
            inventory_models.InventoryServicePort.estado.in_(["RESERVADO", "OCUPADO"])
        ).all()
        db_occupied_sps = {r.service_port for r in reserved_in_db}

        selected_sp = None
        for sp in range(sp_start, sp_end + 1):
            if sp not in existing_in_olt and sp not in db_occupied_sps:
                selected_sp = sp
                break

        if selected_sp is None:
            raise ValueError(f"No hay Service Ports libres en el rango {sp_start}-{sp_end}")

        # Guardar reserva
        rec = self.db.query(inventory_models.InventoryServicePort).filter(
            inventory_models.InventoryServicePort.olt_id == olt_id,
            inventory_models.InventoryServicePort.service_port == selected_sp
        ).first()

        if not rec:
            rec = inventory_models.InventoryServicePort(
                olt_id=olt_id,
                gpon_port=gpon_port,
                service_port=selected_sp,
                estado="RESERVADO",
                reserved_until=datetime.utcnow() + timedelta(minutes=15)
            )
            self.db.add(rec)
        else:
            rec.estado = "RESERVADO"
            rec.reserved_until = datetime.utcnow() + timedelta(minutes=15)

        self.db.commit()
        logger.info(f"[ResourceManager] ✓ Service Port {selected_sp} reservado exitosamente.")
        return selected_sp

    def release_resources(self, olt_id: int, gpon_port: str, ont_id: int, service_port: Optional[int] = None):
        """Libera la reserva u ocupación de un ONT ID y Service Port"""
        try:
            rec_ont = self.db.query(inventory_models.InventoryOntId).filter(
                inventory_models.InventoryOntId.olt_id == olt_id,
                inventory_models.InventoryOntId.gpon_port == gpon_port,
                inventory_models.InventoryOntId.ont_id == ont_id
            ).first()
            if rec_ont:
                rec_ont.estado = "LIBRE"
                rec_ont.cliente_id = None

            if service_port:
                rec_sp = self.db.query(inventory_models.InventoryServicePort).filter(
                    inventory_models.InventoryServicePort.olt_id == olt_id,
                    inventory_models.InventoryServicePort.service_port == service_port
                ).first()
                if rec_sp:
                    rec_sp.estado = "LIBRE"
                    rec_sp.cliente_id = None

            self.db.commit()
            logger.info(f"[ResourceManager] ✓ Recursos liberados: ONT {ont_id}, SP {service_port}")
        except Exception as e:
            self.db.rollback()
            logger.error(f"[ResourceManager] Error liberando recursos: {e}")
