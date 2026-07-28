"""
OPSATEL ISP - Network Discovery Engine
=======================================
Modulo encardado de inspeccionar en tiempo real el estado físico-lógico de la OLT Huawei:
- ONTs registradas por puerto GPON
- Service Ports activos
- Tarjetas/Placas instaladas (display board)
- ONTs sin registrar / desatendidas (display autofind)

Sincroniza la realidad física del equipo con la base de datos de Opsatel.

Autor: Arquitecto de Software Senior / CTO
Versión: 3.2.0 (Fase 1)
"""

import logging
import re
import time
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

# pyrefly: ignore [missing-import]
from sqlalchemy.orm import Session
from database import SessionLocal
import models
import discovery_models
import observability
from services.olt_interface import OLTInterface, OLTConnectionError

logger = logging.getLogger("opsatel.discovery")

class HuaweiDiscoveryEngine:
    """Motor de inspección y descubrimiento para Huawei OLTs"""

    def __init__(self, olt_interface: OLTInterface, olt_id: int):
        self.olt = olt_interface
        self.olt_id = olt_id

    def run_full_discovery(self, db: Session) -> Dict[str, Any]:
        """
        Ejecuta el descubrimiento completo de la OLT:
        1. Estado de Boards/Tarjetas
        2. Barrido de ONTs por puerto GPON
        3. Service Ports activos
        4. ONTs en estado Autofind (pendientes de registro)
        """
        start_time = time.time()
        correlation_id = f"disc_{self.olt_id}_{int(start_time)}"
        logger.info(f"[Discovery] Iniciando auto-descubrimiento completo en OLT {self.olt.host} (ID {self.olt_id})...")

        if not self.olt.is_connected:
            if not self.olt.connect():
                raise OLTConnectionError(f"No se pudo conectar a OLT {self.olt.host}")

        results = {
            "olt_id": self.olt_id,
            "host": self.olt.host,
            "boards_found": 0,
            "onts_found": 0,
            "service_ports_found": 0,
            "autofind_count": 0,
            "duration_ms": 0,
            "status": "SUCCESS"
        }

        try:
            self.olt._ensure_config_mode()

            # 1. Descubrimiento de Boards/Tarjetas
            boards = self.discover_boards()
            results["boards_found"] = len(boards)
            self._sync_boards(db, boards)

            # 2. Descubrimiento de ONTs en todos los puertos GPON activos
            onts = self.discover_all_onts(boards)
            results["onts_found"] = len(onts)
            self._sync_onts(db, onts)

            # 3. Descubrimiento de Service Ports
            service_ports = self.discover_service_ports()
            results["service_ports_found"] = len(service_ports)
            self._sync_service_ports(db, service_ports)

            # 4. Descubrimiento de ONTs Autofind (No registradas)
            autofind_onts = self.discover_autofind()
            results["autofind_count"] = len(autofind_onts)

            duration_ms = int((time.time() - start_time) * 1000)
            results["duration_ms"] = duration_ms

            # Registrar en auditoría
            observability.log_audit_event_async(
                accion="NETWORK_DISCOVERY",
                modulo="discovery",
                usuario="DISCOVERY_WORKER",
                entidad_tipo="OLTConfig",
                entidad_id=str(self.olt_id),
                detalles=f"Descubrimiento completado en {duration_ms}ms: {results['onts_found']} ONTs, {results['service_ports_found']} Service Ports.",
                duracion_ms=duration_ms,
                correlation_id=correlation_id
            )

            logger.info(f"[Discovery] ✓ Auto-descubrimiento completado en {duration_ms}ms para OLT {self.olt.host}")
            return results

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            results["status"] = "ERROR"
            results["error"] = str(e)
            results["duration_ms"] = duration_ms
            logger.error(f"[Discovery] ✗ Error durante descubrimiento en OLT {self.olt.host}: {e}")
            return results

    def discover_boards(self) -> List[Dict[str, Any]]:
        """Ejecuta 'display board 0' y extrae placas/tarjetas activas"""
        boards = []
        try:
            resp = self.olt.send_command("display board 0", use_timing=True, delay_factor=1.5)
            # Parsear filas tipo: " 2    H806GPBD  Normal "
            for line in resp.splitlines():
                line_str = line.strip()
                match = re.search(r'^(\d+)\s+([A-Za-z0-9]+)\s+([A-Za-z0-9]+)', line_str)
                if match:
                    slot = int(match.group(1))
                    btype = match.group(2)
                    status = match.group(3)
                    boards.append({
                        "slot": slot,
                        "board_type": btype,
                        "status": status,
                        "is_gpon": "GP" in btype or "GPBD" in btype or "GPFD" in btype
                    })
        except Exception as e:
            logger.warning(f"[Discovery] Error leyendo display board: {e}")
        return boards

    def discover_all_onts(self, boards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Recorre todos los slots GPON y extrae las ONTs registradas"""
        all_onts = []
        # Identificar slots GPON activos
        gpon_slots = [b["slot"] for b in boards if b.get("is_gpon") and b.get("status") == "Normal"]
        if not gpon_slots:
            # Fallback: asumir slot 2 y 3 como comunes en MA5608T si no se detectaron
            gpon_slots = [2, 3]

        for slot in gpon_slots:
            for port in range(16): # 16 puertos GPON por tarjeta estándar
                gpon_port = f"0/{slot}/{port}"
                try:
                    existing_ont_ids = self.olt.get_existing_ont_ids(gpon_port)
                    for ont_id in existing_ont_ids:
                        all_onts.append({
                            "gpon_port": gpon_port,
                            "ont_id": ont_id,
                            "sn_mac": f"DISCOVERED_{gpon_port}_{ont_id}", # Se refinará con display ont info detail
                            "status": "online"
                        })
                except Exception:
                    continue
        return all_onts

    def discover_service_ports(self) -> List[Dict[str, Any]]:
        """Ejecuta 'display service-port all' para listar todos los Service Ports"""
        service_ports = []
        try:
            resp = self.olt.send_command("display service-port all", use_timing=True, delay_factor=3.0)
            # Parsear tabla Huawei: " 1920 308 gpon 0/0/15 3 108 ..."
            for line in resp.splitlines():
                line_str = line.strip()
                match = re.search(r'^(\d+)\s+(\d+)\s+gpon\s+([0-9/]+)\s+(\d+)', line_str)
                if match:
                    sp_id = int(match.group(1))
                    vlan_id = int(match.group(2))
                    gpon_port = match.group(3)
                    ont_id = int(match.group(4))
                    service_ports.append({
                        "service_port": sp_id,
                        "vlan_id": vlan_id,
                        "gpon_port": gpon_port,
                        "ont_id": ont_id
                    })
        except Exception as e:
            logger.warning(f"[Discovery] Error leyendo display service-port all: {e}")
        return service_ports

    def discover_autofind(self) -> List[Dict[str, Any]]:
        """Ejecuta 'display ont autofind all' para detectar ONTs conectadas no registradas"""
        autofind_list = []
        try:
            resp = self.olt.send_command("display ont autofind all", use_timing=True, delay_factor=1.5)
            # Parsear ONTs desatendidas
            for line in resp.splitlines():
                line_str = line.strip()
                if "Number" in line_str or "F/S/P" in line_str:
                    continue
                match = re.search(r'([0-9/]+)\s+([0-9A-Fa-f]{16})', line_str)
                if match:
                    gpon_port = match.group(1)
                    sn = match.group(2)
                    autofind_list.append({
                        "gpon_port": gpon_port,
                        "sn": sn
                    })
        except Exception as e:
            logger.debug(f"[Discovery] Sin ONTs autofind o error: {e}")
        return autofind_list

    # ============================================================================
    # PERSISTENCIA Y SINCRONIZACIÓN EN BD
    # ============================================================================

    def _sync_boards(self, db: Session, boards: List[Dict[str, Any]]):
        """Actualiza la tabla discovered_boards"""
        now = datetime.utcnow()
        for b in boards:
            existing = db.query(discovery_models.DiscoveredBoard).filter(
                discovery_models.DiscoveredBoard.olt_id == self.olt_id,
                discovery_models.DiscoveredBoard.slot == b["slot"]
            ).first()
            if existing:
                existing.board_type = b["board_type"]
                existing.status = b["status"]
                existing.last_discovered_at = now
            else:
                db.add(discovery_models.DiscoveredBoard(
                    olt_id=self.olt_id,
                    slot=b["slot"],
                    board_type=b["board_type"],
                    status=b["status"],
                    last_discovered_at=now
                ))
        db.commit()

    def _sync_onts(self, db: Session, onts: List[Dict[str, Any]]):
        """Sincroniza la tabla discovered_onts con la realidad física"""
        now = datetime.utcnow()
        for o in onts:
            # Buscar si el cliente existe en Opsatel por puerto y ONT ID
            cliente = db.query(models.Cliente).filter(
                models.Cliente.puerto == o["gpon_port"],
                models.Cliente.id_port == str(o["ont_id"])
            ).first()
            
            cliente_id = cliente.id if cliente else None
            sync_state = "MATCHED" if cliente else "ORPHAN_IN_OLT"

            existing = db.query(discovery_models.DiscoveredONT).filter(
                discovery_models.DiscoveredONT.olt_id == self.olt_id,
                discovery_models.DiscoveredONT.gpon_port == o["gpon_port"],
                discovery_models.DiscoveredONT.ont_id == o["ont_id"]
            ).first()

            if existing:
                existing.status = o["status"]
                existing.cliente_id = cliente_id
                existing.sync_state = sync_state
                existing.last_discovered_at = now
            else:
                db.add(discovery_models.DiscoveredONT(
                    olt_id=self.olt_id,
                    gpon_port=o["gpon_port"],
                    ont_id=o["ont_id"],
                    sn_mac=o["sn_mac"],
                    status=o["status"],
                    cliente_id=cliente_id,
                    sync_state=sync_state,
                    last_discovered_at=now
                ))
        db.commit()

    def _sync_service_ports(self, db: Session, service_ports: List[Dict[str, Any]]):
        """Sincroniza la tabla discovered_service_ports"""
        now = datetime.utcnow()
        for sp in service_ports:
            cliente = db.query(models.Cliente).filter(
                models.Cliente.service_port == str(sp["service_port"])
            ).first()

            cliente_id = cliente.id if cliente else None
            sync_state = "MATCHED" if cliente else "ORPHAN_IN_OLT"

            existing = db.query(discovery_models.DiscoveredServicePort).filter(
                discovery_models.DiscoveredServicePort.olt_id == self.olt_id,
                discovery_models.DiscoveredServicePort.service_port == sp["service_port"]
            ).first()

            if existing:
                existing.vlan_id = sp["vlan_id"]
                existing.gpon_port = sp["gpon_port"]
                existing.ont_id = sp["ont_id"]
                existing.cliente_id = cliente_id
                existing.sync_state = sync_state
                existing.last_discovered_at = now
            else:
                db.add(discovery_models.DiscoveredServicePort(
                    olt_id=self.olt_id,
                    service_port=sp["service_port"],
                    vlan_id=sp["vlan_id"],
                    gpon_port=sp["gpon_port"],
                    ont_id=sp["ont_id"],
                    cliente_id=cliente_id,
                    sync_state=sync_state,
                    last_discovered_at=now
                ))
        db.commit()
