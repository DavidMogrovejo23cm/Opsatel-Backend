"""
@file libreqos_manager.py
@author David Mogrovejo dmogrovejo87@gmail.com
@copyright (c) 2026 David Mogrovejo. All Rights Reserved.
@notice Developed with AI assistance.‍​‌​​​‌​​​‌‌​​​​‌​‌‌‌​‌‌​​‌‌​‌​​‌​‌‌​​‌​​​​‌​​​​​​‌​​‌‌​‌​‌‌​‌‌‌‌​‌‌​​‌‌‌​‌‌‌​​‌​​‌‌​‌‌‌‌​‌‌‌​‌‌​​‌‌​​‌​‌​‌‌​‌​‌​​‌‌​‌‌‌‌​​‌​​​​​​​‌​‌​​​​‌‌​​​‌‌​​‌​‌​​‌​​‌​​​​​​​‌‌​​‌​​​‌‌​​​​​​‌‌​​‌​​​‌‌​‌‌​​​‌​‌‌‌​​​‌​​​​​​‌​​​​​‌​‌‌​‌‌​​​‌‌​‌‌​​​​‌​​​​​​‌​‌​​‌​​‌‌​‌​​‌​‌‌​​‌‌‌​‌‌​‌​​​​‌‌‌​‌​​​‌‌‌​​‌‌​​‌​​​​​​‌​‌​​‌​​‌‌​​‌​‌​‌‌‌​​‌‌​‌‌​​‌​‌​‌‌‌​​‌​​‌‌‌​‌‌​​‌‌​​‌​‌​‌‌​​‌​​​​‌​‌‌‌​​​‌​​​​​​‌​​​‌​​​‌‌​​‌​‌​‌‌‌​‌‌​​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​‌‌‌‌​‌‌‌​​​​​‌‌​​‌​‌​‌‌​​‌​​​​‌​​​​​​‌‌‌​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​​‌​​​​​​‌​​​​​‌​‌​​‌​​‌​​‌​​​​​​‌‌​​​​‌​‌‌‌​​‌‌​‌‌‌​​‌‌​‌‌​‌​​‌​‌‌‌​​‌‌​‌‌‌​‌​​​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌‌​‌‌​​‌​‌​​‌​‌‌‌​​​‌​​​​​​‌​​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌‌​​‌‌‌​‌​​​‌‌​​​​‌​‌‌​​​‌‌​‌‌‌​‌​​​​‌‌‌​‌​​​‌​​​​​​‌‌​​‌​​​‌‌​‌‌​‌​‌‌​‌‌‌‌​‌‌​​‌‌‌​‌‌‌​​‌​​‌‌​‌‌‌‌​‌‌‌​‌‌​​‌‌​​‌​‌​‌‌​‌​‌​​‌‌​‌‌‌‌​​‌‌‌​​​​​‌‌​‌‌‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌​​​‌​​​​​​‌​​​‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌‌​​‌‌​‌‌​‌​​‌​‌‌​​​‌‌​​‌​​​​​​‌​‌​​‌‌​‌‌​‌​​‌​‌‌​​‌‌‌​​‌‌‌​‌​​​‌​​​​​​‌‌​​​‌​​‌‌​​‌‌​​​‌‌​​‌​​​‌‌​‌‌​​‌‌​​‌​‌​‌‌​​‌​‌​​‌‌​​​​​​‌‌​​‌‌​​‌‌​​‌‌​​‌‌​‌​​​​‌‌​​​‌​​‌‌‌​​​​‌‌​​‌​​​​‌‌​‌​‌​‌‌​​‌​​​‌‌​​​‌‌‍
@hash bf26ee033418d5dcd984ad8115334e7ce788cfb5d2bd456cf6e6ee21b877a762
"""
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
    def is_sayausi(nodo_val: Any) -> bool:
        """Determina si un nodo o parroquia corresponde a Sayausí."""
        if not nodo_val:
            return False
        import unicodedata
        s = unicodedata.normalize('NFD', str(nodo_val)).encode('ascii', 'ignore').decode('utf-8').upper()
        return "SAYAUS" in s

    @staticmethod
    def resolve_server(cliente: models.Cliente, db: Session) -> Optional[LibreQoSServer]:
        """
        Resuelve el servidor LibreQoS adecuado para el cliente en base a su topología:
        - Si es Sayausí (nodo/parroquia/IP 172.18) -> LibreQoS-SAYAUSI
        - Si es Baños o General (IP 172.16) -> LibreQoS-OLT-BAÑOS (o servidor de Baños)
        """
        cli_ip = (cliente.ip or "").strip()
        cli_is_sayausi = (
            LibreQoSManager.is_sayausi(cliente.nodo)
            or LibreQoSManager.is_sayausi(cliente.parroquia)
            or cli_ip.startswith("172.18.")
        )

        if cli_is_sayausi:
            server = db.query(LibreQoSServer).filter(
                LibreQoSServer.name.ilike("%SAYAUS%"),
                LibreQoSServer.enabled == True
            ).first()
            if not server:
                server = db.query(LibreQoSServer).filter(
                    LibreQoSServer.host == "172.30.0.34",
                    LibreQoSServer.enabled == True
                ).first()
            if server:
                return server
        else:
            # Baños / General
            server = db.query(LibreQoSServer).filter(
                LibreQoSServer.name.ilike("%BA%"),
                LibreQoSServer.enabled == True
            ).order_by(LibreQoSServer.id.desc()).first()
            if not server:
                server = db.query(LibreQoSServer).filter(
                    LibreQoSServer.host == "172.28.0.4",
                    LibreQoSServer.enabled == True
                ).first()
            if server:
                return server

        # Fallback a búsqueda por OLTConfig asociada
        if cliente.nodo:
            olt = db.query(models.OLTConfig).filter(
                models.OLTConfig.nodo_asociado == cliente.nodo,
                models.OLTConfig.active == True
            ).first()
            if olt and olt.libreqos_server_id:
                return db.query(LibreQoSServer).filter(
                    LibreQoSServer.id == olt.libreqos_server_id,
                    LibreQoSServer.enabled == True
                ).first()

        return db.query(LibreQoSServer).filter(LibreQoSServer.enabled == True).first()

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
    def get_client_qos_profile(cliente: models.Cliente, db: Session) -> Tuple[int, int, int, int]:
        """
        Calcula el perfil de velocidades QoS (Download Min, Upload Min, Download Max, Upload Max)
        para ShapedDevices.csv según las directrices de Opsatel:
        
        1. Planes Especiales (tercera edad, precio_plan_especial > 0 distinto a planes de lista,
           plan 'Plan Estándar' o no catalogado en planes_internet):
           -> Mínimo y Máximo 300 Mbps (300, 300, 300, 300).
           
        2. Plan de $17.25 ('PLAN PERSONAL' o precio ~ 17.25):
           -> Mínimo y Máximo 250 Mbps (250, 250, 250, 250).
           
        3. Planes Oficiales Superiores ('CONEXION ESTABLE', 'FULL CONECTADO', 'LAG CERO', 'GAMER PRO'):
           -> Max = megas // 2 (mínimo garantizado 250 Mbps).
           -> Min = 2 Mbps.
        """
        nombre_plan_raw = str(cliente.plan or "").strip().upper()
        es_tercera_edad = bool(getattr(cliente, 'tercera_edad', False))
        precio_esp = float(getattr(cliente, 'precio_plan_especial', 0) or 0)

        # 1. Detectar si es Plan Especial
        es_plan_especial = (
            es_tercera_edad
            or (precio_esp > 0 and abs(precio_esp - 17.25) > 0.1 and precio_esp not in [20.54, 23.0, 25.0, 32.2])
            or "ESPECIAL" in nombre_plan_raw
            or "ESTANDAR" in nombre_plan_raw
            or "ESTÁNDAR" in nombre_plan_raw
        )

        if es_plan_especial:
            # Requerimiento: Planes especiales deben tener mínimo y máximo 300 Mbps
            return (300, 300, 300, 300)

        # 2. Detectar si es el Plan de 17.25 ('PLAN PERSONAL' o precio ~ 17.25)
        es_plan_17_25 = (
            "PERSONAL" in nombre_plan_raw
            or "17.25" in nombre_plan_raw
            or abs(precio_esp - 17.25) < 0.1
        )

        # Buscar en catálogo oficial de planes_internet
        plan_rec = None
        if cliente.plan:
            plan_rec = db.query(models.PlanInternet).filter(
                models.PlanInternet.nombre == cliente.plan
            ).first()
            if not plan_rec:
                plan_rec = db.query(models.PlanInternet).filter(
                    models.PlanInternet.nombre.ilike(f"%{cliente.plan}%")
                ).first()

        if plan_rec:
            precio_plan = float(plan_rec.precio or 0)
            if abs(precio_plan - 17.25) < 0.1 or plan_rec.megas == 100:
                es_plan_17_25 = True

        if es_plan_17_25:
            # Requerimiento: En plan más bajo de 17.25, máximo y mínimo de 250 Mbps (¡nunca 50 ni 100!)
            return (250, 250, 250, 250)

        # 3. Planes Oficiales superiores en catálogo (600, 650, 700, 800)
        if plan_rec and plan_rec.megas and plan_rec.megas > 100:
            down_max = max(250, plan_rec.megas // 2)
            return (2, 2, down_max, down_max)

        # 4. Intento por número de megas en el texto del plan
        import re
        nums = re.findall(r'\d+', nombre_plan_raw)
        if nums:
            val = int(nums[0])
            if val > 100:
                down_max = max(250, val // 2)
                return (2, 2, down_max, down_max)
            elif val == 100:
                return (250, 250, 250, 250)

        # Fallback a Plan Especial (300/300) para no degradar a ningún cliente a 50
        return (300, 300, 300, 300)

    @staticmethod
    def calculate_speeds(cliente: models.Cliente, db: Session) -> Tuple[int, int]:
        """Calcula velocidades máximas (Download, Upload) para compatibilidad."""
        down_min, up_min, down_max, up_max = LibreQoSManager.get_client_qos_profile(cliente, db)
        return down_max, up_max

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
            "comment": cliente.nombre or f"Cliente_{cliente.id}"
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
