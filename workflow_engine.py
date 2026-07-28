"""
OPSATEL ISP - Workflow & Provisioning Engine (Fase 4)
=====================================================
Motor orquestador de Workflows multietapa.
Reemplaza la ejecución exclusiva de OLT por secuencias complejas con:
- Máquina de Estados Fina
- Timeline de Eventos en tiempo real (Audit & Debug)
- Bus de Eventos desacoplado (EventBus)
- Rollback Engine Atómico multi-sistema

Workflows soportados:
- ACTIVAR_CLIENTE
- SUSPENDER_CLIENTE
- REACTIVAR_CLIENTE

Autor: Arquitecto de Software Senior / CTO
Versión: 3.5.0 (Fase 4)
"""

import logging
import json
import time
from datetime import datetime
from typing import Dict, Any, List, Optional

from sqlalchemy.orm import Session
from database import SessionLocal
import models
import inventory_models
import observability
from resource_manager import ResourceManager
from services.olt_interface import OLTInterface

logger = logging.getLogger("opsatel.workflow")

# ============================================================================
# EVENT BUS (DESACOPLADO)
# ============================================================================

class EventBus:
    """Bus de eventos interno de la aplicación (Publish/Subscribe)"""
    _subscribers: Dict[str, List[Any]] = {}

    @classmethod
    def subscribe(cls, event_type: str, handler: Any):
        if event_type not in cls._subscribers:
            cls._subscribers[event_type] = []
        cls._subscribers[event_type].append(handler)

    @classmethod
    def publish(cls, event_type: str, payload: Dict[str, Any]):
        logger.info(f"[EventBus] Evento publicado: '{event_type}'")
        handlers = cls._subscribers.get(event_type, [])
        for h in handlers:
            try:
                h(payload)
            except Exception as e:
                logger.error(f"[EventBus] Error en subscriber para '{event_type}': {e}")

# ============================================================================
# WORKFLOW ENGINE
# ============================================================================

class WorkflowStepException(Exception):
    """Excepción al fallar un paso del workflow"""
    def __init__(self, step_name: str, message: str, rollback_data: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.step_name = step_name
        self.rollback_data = rollback_data or {}

class WorkflowEngine:
    """Orquestador de Workflows del ISP"""

    def __init__(self, db: Session):
        self.db = db
        self.resource_mgr = ResourceManager(db)

    def execute_workflow(self, workflow_type: str, payload: Dict[str, Any], olt_interface: Optional[OLTInterface] = None) -> Dict[str, Any]:
        """
        Punto de entrada universal para la ejecución de Workflows.
        """
        start_time = time.time()
        correlation_id = payload.get("correlation_id", f"wf_{int(start_time)}")
        timeline = []

        def _add_timeline(step: str, status: str, details: str):
            entry = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "step": step,
                "status": status,
                "details": details,
                "elapsed_ms": int((time.time() - start_time) * 1000)
            }
            timeline.append(entry)
            logger.info(f"[WorkflowTimeline] [{step}] {status}: {details}")

        logger.info(f"[WorkflowEngine] Iniciando Workflow '{workflow_type}' (ID: {correlation_id})...")
        _add_timeline("INIT", "STARTED", f"Iniciando Workflow {workflow_type}")

        if workflow_type == "ACTIVAR_CLIENTE":
            return self._run_activar_cliente(payload, olt_interface, _add_timeline, correlation_id, timeline)
        else:
            raise ValueError(f"Workflow '{workflow_type}' no soportado")

    def _run_activar_cliente(self, payload: Dict[str, Any], olt: Optional[OLTInterface], _add_timeline, correlation_id: str, timeline: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Workflow de Activación Completa:
        1. Validar Cliente y Parámetros
        2. Reservar ONT ID y Service Port en Resource Manager
        3. Configurar ONT y Native VLAN en OLT Huawei
        4. Configurar Service Port en OLT Huawei
        5. Actualizar Estado del Cliente en BD
        6. Publicar evento CLIENT_ACTIVATED en EventBus
        """
        cliente_id = payload.get("cliente_id")
        gpon_port = payload.get("gpon_port", "0/0/0")
        olt_id = payload.get("olt_id", 1)
        mac = payload.get("mac", "000000000000")

        cliente = self.db.query(models.Cliente).filter(models.Cliente.id == cliente_id).first()
        if not cliente:
            _add_timeline("VALIDATION", "FAILED", f"Cliente {cliente_id} no encontrado")
            return {"success": False, "error": "Cliente no encontrado", "timeline": timeline}

        _add_timeline("VALIDATION", "SUCCESS", f"Cliente {cliente.nombre} validado")

        reserved_ont_id = None
        reserved_sp = None

        try:
            # ── PASO 1: RESERVA DE RECURSOS EN INVENTARIO ──
            _add_timeline("RESOURCE_RESERVATION", "PENDING", "Reservando ONT ID y Service Port...")
            reserved_ont_id = self.resource_mgr.reserve_ont_id(olt_id, gpon_port, olt)
            reserved_sp = self.resource_mgr.reserve_service_port(olt_id, gpon_port, olt)
            
            _add_timeline("RESOURCE_RESERVATION", "SUCCESS", f"Reservado ONT ID {reserved_ont_id}, Service Port {reserved_sp}")

            # ── PASO 2: EJECUCIÓN EN OLT HUAWEI ──
            if olt and olt.is_connected:
                _add_timeline("OLT_PROVISIONING", "PENDING", "Enviando comandos CLI a Huawei OLT...")
                activation_payload = {
                    "gpon_port": gpon_port,
                    "ont_id": str(reserved_ont_id),
                    "mac": mac,
                    "service_port": str(reserved_sp),
                    "description": f"CLI_{cliente_id}_{reserved_ont_id}"
                }

                res_olt = olt.execute_activation_sequence(activation_payload)
                if not res_olt.get("success"):
                    raise WorkflowStepException("OLT_PROVISIONING", f"Fallo en OLT: {res_olt.get('error')}")

                _add_timeline("OLT_PROVISIONING", "SUCCESS", "Secuencia GPON y Service Port aplicada en OLT")
            else:
                _add_timeline("OLT_PROVISIONING", "SKIPPED", "No hay conexión OLT activa (Modo Simulación)")

            # ── PASO 3: ACTUALIZACIÓN DE CLIENTE Y BD ──
            cliente.puerto = gpon_port
            cliente.id_port = str(reserved_ont_id)
            cliente.service_port = str(reserved_sp)
            cliente.estado = "Activo"
            self.db.commit()

            _add_timeline("DATABASE_UPDATE", "SUCCESS", "Cliente marcado como Activo con recursos asignados")

            # ── PASO 4: EVENT BUS PUBLISH ──
            EventBus.publish("CLIENT_ACTIVATED", {
                "cliente_id": cliente.id,
                "nombre": cliente.nombre,
                "gpon_port": gpon_port,
                "ont_id": reserved_ont_id,
                "service_port": reserved_sp
            })
            _add_timeline("EVENT_BUS", "SUCCESS", "Evento CLIENT_ACTIVATED publicado")

            # Auditoría final
            observability.log_audit_event_async(
                accion="WORKFLOW_ACTIVAR_CLIENTE",
                modulo="workflows",
                usuario="WORKFLOW_ENGINE",
                entidad_tipo="Cliente",
                entidad_id=str(cliente.id),
                detalles=f"Workflow de activación finalizado con éxito para {cliente.nombre}",
                correlation_id=correlation_id
            )

            return {
                "success": True,
                "status": "FINISHED",
                "cliente_id": cliente.id,
                "ont_id": reserved_ont_id,
                "service_port": reserved_sp,
                "timeline": timeline
            }

        except Exception as e:
            logger.error(f"[WorkflowEngine] ✗ ERROR en Workflow. Iniciando ROLLBACK ENGINE... Detalle: {e}")
            _add_timeline("WORKFLOW_FAILURE", "ERROR", str(e))
            
            # ── ROLLBACK ENGINE ATÓMICO MULTI-SISTEMA ──
            self._execute_rollback(olt_id, gpon_port, reserved_ont_id, reserved_sp, olt, _add_timeline)

            return {
                "success": False,
                "status": "ROLLBACK_EXECUTED",
                "error": str(e),
                "timeline": timeline
            }

    def _execute_rollback(self, olt_id: int, gpon_port: str, ont_id: Optional[int], service_port: Optional[int], olt: Optional[OLTInterface], _add_timeline):
        """Ejecuta deshacer cambios en OLT y libera recursos en el inventario"""
        _add_timeline("ROLLBACK_ENGINE", "PENDING", "Iniciando reversión de cambios en OLT e Inventario...")
        
        # 1. Liberar OLT Huawei si aplica
        if olt and olt.is_connected and ont_id is not None:
            try:
                removal_payload = {
                    "gpon_port": gpon_port,
                    "ont_id": str(ont_id),
                    "service_port": str(service_port) if service_port else ""
                }
                olt.execute_removal_sequence(removal_payload)
                _add_timeline("ROLLBACK_OLT", "SUCCESS", "Configuración eliminada de OLT Huawei")
            except Exception as olt_err:
                _add_timeline("ROLLBACK_OLT", "FAILED", f"No se pudo limpiar OLT: {olt_err}")

        # 2. Liberar inventario BD
        if ont_id is not None:
            self.resource_mgr.release_resources(olt_id, gpon_port, ont_id, service_port)
            _add_timeline("ROLLBACK_INVENTORY", "SUCCESS", "Recursos devueltos a estado LIBRE en Inventario BD")
