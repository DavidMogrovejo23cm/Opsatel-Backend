import logging
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple, Optional
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import Session

import models
from libreqos_models import LibreQoSServer, ClientQoSState, LibreQoSJob, LibreQoSAuditLog

logger = logging.getLogger("opsatel.services.libreqos_manager")

# Semáforos en memoria por servidor para controlar la concurrencia máxima
_semaphores: Dict[int, threading.Semaphore] = {}
_semaphores_lock = threading.Lock()

class LibreQoSManager:
    """
    Manager de orquestación y lógica de negocio para LibreQoS.
    Resuelve topologías, calcula velocidades, encola tareas asíncronas
    y administra locks de concurrencia y cliente.
    """
    
    @staticmethod
    def get_semaphore(server_id: int, max_concurrent: int) -> threading.Semaphore:
        """Obtiene o crea un semáforo de concurrencia por ID de servidor."""
        with _semaphores_lock:
            if server_id not in _semaphores:
                _semaphores[server_id] = threading.Semaphore(max_concurrent)
            return _semaphores[server_id]

    @staticmethod
    def resolve_server(cliente: models.Cliente, db: Session) -> Optional[LibreQoSServer]:
        """
        Resuelve el servidor LibreQoS adecuado para el cliente en base a su topología:
        cliente.nodo -> OLTConfig.nodo_asociado -> OLTConfig.libreqos_server_id -> LibreQoSServer
        """
        if not cliente.nodo:
            logger.warning(f"resolve_server: Cliente {cliente.id} no tiene un nodo asignado.")
            return None
            
        # Buscar la OLT asociada al nodo del cliente
        # La relación se basa en el nodo_asociado o el nodo del cliente
        olt = db.query(models.OLTConfig).filter(
            models.OLTConfig.nodo_asociado == cliente.nodo,
            models.OLTConfig.active == True
        ).first()
        
        if not olt:
            # Fallback a buscar por coincidencia parcial o la OLT por defecto
            olt = db.query(models.OLTConfig).filter(models.OLTConfig.active == True).first()
            
        if not olt or not olt.libreqos_server_id:
            logger.warning(f"resolve_server: No se encontró una OLT activa o asociada con libreqos_server_id para el nodo '{cliente.nodo}'.")
            return None
            
        server = db.query(LibreQoSServer).filter(
            LibreQoSServer.id == olt.libreqos_server_id,
            LibreQoSServer.enabled == True
        ).first()
        
        return server

    @staticmethod
    def get_or_create_qos_state(cliente_id: int, db: Session) -> ClientQoSState:
        """Obtiene o crea el registro de estado QoS de un cliente."""
        state = db.query(ClientQoSState).filter(ClientQoSState.cliente_id == cliente_id).first()
        if not state:
            state = ClientQoSState(
                cliente_id=cliente_id,
                status="PENDING"
            )
            db.add(state)
            db.commit()
            db.refresh(state)
        return state

    @staticmethod
    def calculate_speeds(cliente: models.Cliente, db: Session) -> Tuple[int, int]:
        """
        Calcula las velocidades del plan asignado al cliente.
        Lógica:
          Download = megas definidos en PlanInternet.
          Upload = max(2, download // 2).
        """
        # Valor por defecto
        download_mbps = 100
        
        if cliente.plan:
            plan_rec = db.query(models.PlanInternet).filter(
                models.PlanInternet.nombre == cliente.plan
            ).first()
            if plan_rec:
                download_mbps = plan_rec.megas
            else:
                # Intento de extraer número del string del plan
                import re
                nums = re.findall(r'\d+', cliente.plan)
                if nums:
                    download_mbps = int(nums[0])
        # Aplicar regla del usuario: Máximo de bajada y subida son la mitad de lo que tiene el plan (ej: plan de 800 -> 400 DL y 400 UL)
        download_max = max(2, download_mbps // 2)
        upload_max = download_max
        return download_max, upload_max

    @classmethod
    def enqueue_job(
        cls,
        operation: str,
        cliente_id: int,
        db: Session,
        correlation_id: str,
        created_by: str = "SYSTEM"
    ) -> Optional[LibreQoSJob]:
        """
        Encola un trabajo en la cola de tareas asíncronas para LibreQoS.
        Implementa lock por cliente: evita duplicar tareas pendientes/procesando del mismo tipo.
        """
        cliente = db.query(models.Cliente).filter(models.Cliente.id == cliente_id).first()
        if not cliente:
            logger.error(f"enqueue_job: Cliente {cliente_id} no existe.")
            return None
            
        server = cls.resolve_server(cliente, db)
        if not server:
            logger.warning(f"enqueue_job: No se resolvió servidor LibreQoS para cliente {cliente_id} (QoS PENDING/FAILED).")
            # Actualizar estado del cliente a PENDING/FAILED
            state = cls.get_or_create_qos_state(cliente_id, db)
            state.status = "FAILED"
            state.last_error = "No se pudo mapear topología OLT -> LibreQoS."
            db.commit()
            return None

        # Verificar si ya existe un trabajo pendiente o en proceso para el cliente
        existing_job = db.query(LibreQoSJob).filter(
            LibreQoSJob.cliente_id == cliente_id,
            LibreQoSJob.operation == operation,
            LibreQoSJob.status.in_(["pending", "processing"])
        ).first()
        
        if existing_job:
            logger.info(f"enqueue_job: Ya existe una tarea {operation} '{existing_job.status}' para cliente {cliente_id}. Evitando duplicados.")
            return existing_job

        # Obtener datos de velocidad/IP para el payload
        download, upload = cls.calculate_speeds(cliente, db)
        
        payload = {
            "ip": cliente.ip,
            "download_mbps": download,
            "upload_mbps": upload,
            "comment": f"{str(cliente.id).zfill(6)} - {cliente.nombre}"
        }

        # Para suspensión, sobreescribir velocidades según la política del servidor
        if operation == "SUSPEND":
            payload["download_mbps"] = server.suspension_download_mbps
            payload["upload_mbps"] = server.suspension_upload_mbps

        job = LibreQoSJob(
            cliente_id=cliente_id,
            libreqos_server_id=server.id,
            operation=operation,
            payload=payload,
            status="pending",
            correlation_id=correlation_id,
            created_by=created_by
        )
        
        db.add(job)
        
        # Sincronizar estado deseado
        state = cls.get_or_create_qos_state(cliente_id, db)
        state.libreqos_server_id = server.id
        state.ip = cliente.ip
        state.download_mbps = payload["download_mbps"]
        state.upload_mbps = payload["upload_mbps"]
        state.status = "PENDING" if state.status != "DRIFT" else "DRIFT"
        state.correlation_id = correlation_id
        
        db.commit()
        db.refresh(job)
        
        logger.info(f"✓ Trabajo LibreQoS encolado con éxito: ID={job.id}, Op={operation}, Cliente={cliente_id}")
        return job
