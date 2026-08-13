import logging
from datetime import datetime
from typing import Dict, Any, List
from sqlalchemy.orm import Session

import models
from libreqos_models import LibreQoSServer, ClientQoSState, LibreQoSJob, LibreQoSAuditLog
from network.adapters.libreqos import LibreQoSAdapter
from services.libreqos_manager import LibreQoSManager

logger = logging.getLogger("opsatel.sync.libreqos_sync")

class LibreQoSReconciler:
    """
    Motor de reconciliación para LibreQoS.
    Descarga el estado real de los servidores remotos, lo compara
    con la base de datos de Opsatel y corrige diferencias (Drifts) de forma automática.
    """

    @classmethod
    def reconcile_server(cls, server_id: int, db: Session, correlation_id: str = None) -> Dict[str, Any]:
        """Sincroniza y reconcilia un único servidor LibreQoS."""
        server = db.query(LibreQoSServer).filter(
            LibreQoSServer.id == server_id,
            LibreQoSServer.enabled == True
        ).first()

        if not server:
            return {"success": False, "error": "Servidor no encontrado o deshabilitado"}

        logger.info(f"Iniciando reconciliación para servidor: {server.name} ({server.host})")
        cid = correlation_id or f"sync_lq_{int(datetime.utcnow().timestamp())}"

        # 1. Obtener clientes que deberían estar en este servidor según la base de datos
        # Un cliente va a este servidor si su OLT apunta a este libreqos_server_id
        db_clients = db.query(models.Cliente).join(
            models.OLTConfig, models.OLTConfig.nodo_asociado == models.Cliente.nodo
        ).filter(
            models.OLTConfig.libreqos_server_id == server.id,
            models.OLTConfig.active == True,
            models.Cliente.estado == "Activo",
            models.Cliente.ip != None
        ).all()

        db_client_map = {c.id: c for c in db_clients}
        logger.info(f"Clientes teóricos en BD para este servidor: {len(db_client_map)}")

        # 2. Conectarse al LibreQoS real y obtener la lista shaped real
        shaped_clients = []
        try:
            with LibreQoSAdapter(server) as adapter:
                shaped_clients = adapter.list_shaped_clients()
                server.status = "ONLINE"
                server.last_check = datetime.utcnow()
                server.last_error = None
                db.commit()
        except Exception as e:
            logger.error(f"Error conectando a LibreQoS para reconciliación: {e}")
            server.status = "OFFLINE"
            server.last_check = datetime.utcnow()
            server.last_error = str(e)
            db.commit()
            return {"success": False, "error": f"Servidor OFFLINE: {e}"}

        # Mapear clientes reales en LibreQoS por ID
        # LibreQoS suele reportar id en el JSON
        real_client_map = {}
        for rc in shaped_clients:
            rc_id = rc.get("id")
            if rc_id:
                try:
                    real_client_map[int(rc_id)] = rc
                except ValueError:
                    pass

        logger.info(f"Clientes reales detectados en el shaper LibreQoS: {len(real_client_map)}")

        # 3. Comparación y detección de drifts
        drifts_detected = 0
        repaired_count = 0

        # Caso A: Clientes en BD que faltan en LibreQoS o tienen diferencias de velocidad/IP
        for cid_db, cliente in db_client_map.items():
            state = LibreQoSManager.get_or_create_qos_state(cliente.id, db)
            target_down, target_up = LibreQoSManager.calculate_speeds(cliente, db)
            
            # Si el cliente está suspendido en Opsatel
            if cliente.estado == "Suspendido":
                target_down = server.suspension_download_mbps
                target_up = server.suspension_upload_mbps

            real_node = real_client_map.get(cid_db)

            if not real_node:
                # Falta en el shaper real
                logger.warning(f"DRIFT: Cliente {cliente.id} ({cliente.nombre}) falta en el shaper LibreQoS.")
                drifts_detected += 1
                
                # Encolar aprovisionamiento
                op = "SUSPEND" if cliente.estado == "Suspendido" else "PROVISION"
                LibreQoSManager.enqueue_job(op, cliente.id, db, cid, "RECONCILER")
                repaired_count += 1
                
                state.status = "DRIFT"
                state.last_error = "Reconciliador: El cliente faltaba en el shaper LibreQoS."
                db.commit()
            else:
                # Existe, verificar si los parámetros coinciden
                # ispConfig.py suele usar 'ip', 'download', 'upload' en el JSON
                real_ip = real_node.get("ip")
                real_down = real_node.get("download") or real_node.get("down")
                real_up = real_node.get("upload") or real_node.get("up")

                # Normalizar velocidades para comparar
                try:
                    real_down = int(real_down) if real_down else 0
                    real_up = int(real_up) if real_up else 0
                except ValueError:
                    real_down, real_up = 0, 0

                has_drift = False
                reasons = []

                if real_ip != cliente.ip:
                    has_drift = True
                    reasons.append(f"IP mismatch: Real={real_ip}, BD={cliente.ip}")
                if real_down != target_down:
                    has_drift = True
                    reasons.append(f"Down mismatch: Real={real_down}, BD={target_down}")
                if real_up != target_up:
                    has_drift = True
                    reasons.append(f"Up mismatch: Real={real_up}, BD={target_up}")

                if has_drift:
                    drift_reason = "; ".join(reasons)
                    logger.warning(f"DRIFT: Cliente {cliente.id} ({cliente.nombre}) desincronizado: {drift_reason}")
                    drifts_detected += 1
                    
                    # Encolar actualización
                    op = "SUSPEND" if cliente.estado == "Suspendido" else "UPDATE"
                    LibreQoSManager.enqueue_job(op, cliente.id, db, cid, "RECONCILER")
                    repaired_count += 1
                    
                    state.status = "DRIFT"
                    state.last_error = f"Reconciliador: {drift_reason}"
                    db.commit()
                else:
                    # Todo correcto
                    state.status = "SUSPENDED" if cliente.estado == "Suspendido" else "APPLIED"
                    state.last_verified_at = datetime.utcnow()
                    db.commit()

        # Caso B: Clientes en LibreQoS que no deberían estar (eliminados o movidos de OLT/servidor)
        for cid_real, real_node in real_client_map.items():
            if cid_real not in db_client_map:
                # Cliente huérfano en el shaper
                real_ip = real_node.get("ip")
                logger.warning(f"DRIFT: Cliente {cid_real} (IP: {real_ip}) está configurado en LibreQoS pero no le corresponde en Opsatel.")
                drifts_detected += 1
                
                # Encolar eliminación del cliente huérfano
                job = LibreQoSJob(
                    cliente_id=cid_real,
                    libreqos_server_id=server.id,
                    operation="REMOVE",
                    payload={"ip": real_ip},
                    status="pending",
                    correlation_id=cid,
                    created_by="RECONCILER"
                )
                db.add(job)
                repaired_count += 1
                db.commit()

        # Registrar evento de reconciliación
        if drifts_detected > 0:
            logger.info(f"Reconciliación completa para {server.name}. Detectados {drifts_detected} drifts, {repaired_count} reparaciones encoladas.")
        else:
            logger.info(f"✓ Servidor {server.name} sincronizado al 100%. Sin drifts.")

        return {
            "success": True,
            "server_id": server.id,
            "drifts_detected": drifts_detected,
            "repaired_count": repaired_count
        }

    @classmethod
    def reconcile_all(cls, db: Session) -> List[Dict[str, Any]]:
        """Reconcilia todos los servidores activos habilitados."""
        servers = db.query(LibreQoSServer).filter(LibreQoSServer.enabled == True).all()
        results = []
        for s in servers:
            try:
                res = cls.reconcile_server(s.id, db)
                results.append(res)
            except Exception as e:
                logger.error(f"Error reconciliando servidor {s.name}: {e}")
                results.append({"server_id": s.id, "success": False, "error": str(e)})
        return results
