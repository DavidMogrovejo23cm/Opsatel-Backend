"""
OPSATEL ISP - Sync Engine (Reconciliación BD ↔ OLT)
====================================================
Motor encargador de comparar la inspección física capturada por Network Discovery
con los registros de la base de datos de Opsatel.

Identifica:
1. ORPHAN_IN_OLT: Recurso (ONT / Service Port) presente en la OLT pero sin cliente asignado en BD.
2. MISSING_IN_OLT: Cliente en BD marcado como "Activo" cuya ONT o Service Port ya no existe en la OLT.
3. CONFLICT: Inconsistencia entre el Service Port o VLAN registrado en BD y el real de la OLT.

Proporciona acciones de auto-reconciliación y sincronización en un solo clic.

Autor: Arquitecto de Software Senior / CTO
Versión: 3.3.0 (Fase 2)
"""

import logging
import time
from datetime import datetime
from typing import Dict, Any, List, Optional

# pyrefly: ignore [missing-import]
from sqlalchemy.orm import Session
from database import SessionLocal
import models
import discovery_models
import observability

logger = logging.getLogger("opsatel.sync")

class NetworkSyncEngine:
    """Motor de análisis y reconciliación entre la OLT y la Base de Datos"""

    def __init__(self, db: Session):
        self.db = db

    def analyze_discrepancies(self, olt_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Analiza las diferencias entre los registros de descubrimientos recientes y la base de datos:
        - Detecta ONTs huérfanas en la OLT.
        - Detecta Clientes en BD con ONT faltante en la OLT.
        - Detecta Service Ports huérfanos.
        """
        start_time = time.time()
        logger.info("[SyncEngine] Iniciando análisis de discrepancias BD ↔ OLT...")

        query_onts = self.db.query(discovery_models.DiscoveredONT)
        query_sps = self.db.query(discovery_models.DiscoveredServicePort)
        query_clientes = self.db.query(models.Cliente).filter(models.Cliente.estado == "Activo")

        if olt_id:
            query_onts = query_onts.filter(discovery_models.DiscoveredONT.olt_id == olt_id)
            query_sps = query_sps.filter(discovery_models.DiscoveredServicePort.olt_id == olt_id)

        discovered_onts = query_onts.all()
        discovered_sps = query_sps.all()
        active_clientes = query_clientes.all()

        orphans_in_olt = []
        missing_in_olt = []
        matched_count = 0
        conflict_sps = []

        # 1. Analizar ONTs descubiertas
        for ont in discovered_onts:
            if ont.sync_state == "ORPHAN_IN_OLT" or not ont.cliente_id:
                orphans_in_olt.append({
                    "type": "ONT",
                    "olt_id": ont.olt_id,
                    "gpon_port": ont.gpon_port,
                    "ont_id": ont.ont_id,
                    "sn_mac": ont.sn_mac,
                    "description": ont.description,
                    "last_seen": ont.last_discovered_at.isoformat() if ont.last_discovered_at else None
                })
            else:
                matched_count += 1

        # 2. Analizar Clientes activos en BD que no están en la OLT
        for cliente in active_clientes:
            if not cliente.puerto or not cliente.id_port:
                continue
            
            # Buscar en descubrimientos
            found = False
            for ont in discovered_onts:
                if ont.gpon_port == cliente.puerto and str(ont.ont_id) == str(cliente.id_port):
                    found = True
                    break

            if not found:
                missing_in_olt.append({
                    "cliente_id": cliente.id,
                    "nombre": cliente.nombre,
                    "cedula": cliente.cedula,
                    "gpon_port": cliente.puerto,
                    "ont_id": cliente.id_port,
                    "service_port": cliente.service_port,
                    "estado_bd": cliente.estado
                })

        # 3. Analizar Service Ports huérfanos
        orphan_sps = [
            {
                "type": "SERVICE_PORT",
                "olt_id": sp.olt_id,
                "service_port": sp.service_port,
                "vlan_id": sp.vlan_id,
                "gpon_port": sp.gpon_port,
                "ont_id": sp.ont_id
            }
            for sp in discovered_sps if sp.sync_state == "ORPHAN_IN_OLT" or not sp.cliente_id
        ]

        duration_ms = int((time.time() - start_time) * 1000)

        report = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "matched_clients_count": matched_count,
            "orphans_ont_count": len(orphans_in_olt),
            "orphans_sp_count": len(orphan_sps),
            "missing_clients_in_olt_count": len(missing_in_olt),
            "orphans_ont": orphans_in_olt,
            "orphans_service_ports": orphan_sps,
            "missing_in_olt": missing_in_olt,
            "analysis_duration_ms": duration_ms
        }

        logger.info(f"[SyncEngine] ✓ Análisis completado en {duration_ms}ms: {matched_count} emparejados, {len(orphans_in_olt)} ONTs huérfanas, {len(missing_in_olt)} faltantes en OLT.")
        return report

    def reconcile_client(self, cliente_id: int, discovered_ont_id: int) -> Dict[str, Any]:
        """
        Acción de auto-reconciliación: Vincula una ONT descubierta en la OLT con un cliente de la BD
        actualizando los campos técnicos del cliente.
        """
        start_time = time.time()
        cliente = self.db.query(models.Cliente).filter(models.Cliente.id == cliente_id).first()
        disc_ont = self.db.query(discovery_models.DiscoveredONT).filter(discovery_models.DiscoveredONT.id == discovered_ont_id).first()

        if not cliente:
            raise ValueError(f"Cliente {cliente_id} no existe")
        if not disc_ont:
            raise ValueError(f"ONT Descubierta {discovered_ont_id} no existe")

        estado_antes = {
            "puerto": cliente.puerto,
            "id_port": cliente.id_port,
            "mac": cliente.mac
        }

        # Actualizar datos del cliente con la realidad de la OLT
        cliente.puerto = disc_ont.gpon_port
        cliente.id_port = str(disc_ont.ont_id)
        if disc_ont.sn_mac and not disc_ont.sn_mac.startswith("DISCOVERED"):
            cliente.mac = disc_ont.sn_mac

        # Marcar vinculación en tabla de descubrimiento
        disc_ont.cliente_id = cliente.id
        disc_ont.sync_state = "MATCHED"

        self.db.commit()

        duration_ms = int((time.time() - start_time) * 1000)
        observability.log_audit_event_async(
            accion="RECONCILE_CLIENT",
            modulo="sync",
            usuario="ADMIN_SYNC",
            entidad_tipo="Cliente",
            entidad_id=str(cliente.id),
            estado_antes=estado_antes,
            estado_despues={"puerto": cliente.puerto, "id_port": cliente.id_port, "mac": cliente.mac},
            detalles=f"Cliente {cliente.id} reconciliado con ONT {disc_ont.gpon_port}:{disc_ont.ont_id} en la OLT.",
            duracion_ms=duration_ms
        )

        return {
            "success": True,
            "message": f"Cliente {cliente.id} ({cliente.nombre}) sincronizado exitosamente con ONT {disc_ont.gpon_port}:{disc_ont.ont_id}",
            "cliente_id": cliente.id,
            "gpon_port": cliente.puerto,
            "ont_id": cliente.id_port
        }
