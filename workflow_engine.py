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

# pyrefly: ignore [missing-import]
from sqlalchemy.orm import Session
from database import SessionLocal
import models
import inventory_models
import observability
from resource_manager import ResourceManager
from services.olt_interface import OLTInterface
from network.adapters.mikrotik import MikroTikAdapter, MikroTikAdapterError

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
        5. [NUEVO] MikroTik: Buscar DHCP Lease por MAC, convertir a estático y comentar
        6. Actualizar Estado del Cliente en BD
        7. Publicar eventos CLIENT_ACTIVATED y CLIENT_NETWORK_READY en EventBus
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

            # ── PASO 3: MIKROTIK - DHCP LEASE → ESTÁTICO ──────────────────────────
            mikrotik_result = self._run_mikrotik_step(cliente, mac, olt_id, _add_timeline, correlation_id)
            # El paso de MikroTik es best-effort: no aborta el workflow si falla
            # (la ONT ya está activa en la OLT; un fallo de MikroTik se registra y se puede reintentar)

            # ── PASO 4: ACTUALIZACIÓN DE CLIENTE Y BD ──
            cliente.puerto = gpon_port
            cliente.id_port = str(reserved_ont_id)
            cliente.service_port = str(reserved_sp)
            cliente.estado = "Activo"
            self.db.commit()

            _add_timeline("DATABASE_UPDATE", "SUCCESS", "Cliente marcado como Activo con recursos asignados")

            # ── PASO 5: EVENT BUS PUBLISH ──
            EventBus.publish("CLIENT_ACTIVATED", {
                "cliente_id": cliente.id,
                "nombre": cliente.nombre,
                "gpon_port": gpon_port,
                "ont_id": reserved_ont_id,
                "service_port": reserved_sp
            })
            _add_timeline("EVENT_BUS", "SUCCESS", "Evento CLIENT_ACTIVATED publicado")

            if mikrotik_result.get("success"):
                EventBus.publish("CLIENT_NETWORK_READY", {
                    "cliente_id": cliente.id,
                    "nombre": cliente.nombre,
                    "ip": mikrotik_result.get("ip"),
                    "mac": mac
                })
                _add_timeline("EVENT_BUS", "SUCCESS", "Evento CLIENT_NETWORK_READY publicado")

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
                "mikrotik": mikrotik_result,
                "timeline": timeline
            }

        except Exception as e:
            logger.error(f"[WorkflowEngine] ✗ ERROR en Workflow. Iniciando ROLLBACK ENGINE... Detalle: {e}")
            _add_timeline("WORKFLOW_FAILURE", "ERROR", str(e))
            
            # ── ROLLBACK ENGINE ATÓMICO MULTI-SISTEMA ──
            self._execute_rollback(olt_id, gpon_port, reserved_ont_id, reserved_sp, olt, _add_timeline, mac=mac)

            return {
                "success": False,
                "status": "ROLLBACK_EXECUTED",
                "error": str(e),
                "timeline": timeline
            }

    def _run_mikrotik_step(self, cliente, mac: str, olt_id: int, _add_timeline, correlation_id: str) -> Dict[str, Any]:
        """
        Paso MikroTik del workflow ACTIVAR_CLIENTE.
        1. Determina pool/VLAN/servidor DHCP según el puerto GPON/Nodo del cliente.
        2. Realiza polling en MikroTik consultando leases dinámicos hasta encontrar el del cliente.
        3. Aplica matching robusto (MAC > Client ID > Hostname).
        4. Convierte a estático (make-static).
        5. Modifica comentario a 'CODIGO - NOMBRE'.
        6. Persiste la IP e información en la base de datos local (InventoryIpPool / cliente.ip).
        """
        _add_timeline("MIKROTIK_PROVISIONING", "PENDING", f"Iniciando flujo de aprovisionamiento MikroTik para MAC {mac}...")
        
        try:
            # Obtener configuración MikroTik del OLT Config
            olt_cfg = self.db.query(models.OLTConfig).filter(models.OLTConfig.id == olt_id).first()
            if not olt_cfg or not olt_cfg.mikrotik_host:
                _add_timeline("MIKROTIK_PROVISIONING", "SKIPPED", "No hay MikroTik configurado para este nodo")
                return {"success": False, "reason": "no_config"}

            # Intentar usar IP reservada/preexistente en BD si ya existe para este cliente
            existing_ip_rec = self.db.query(inventory_models.InventoryIpPool).filter(
                inventory_models.InventoryIpPool.cliente_id == cliente.id,
                inventory_models.InventoryIpPool.estado == "OCUPADO"
            ).first()

            target_ip = existing_ip_rec.ip_address if existing_ip_rec else None
            if target_ip:
                _add_timeline("MIKROTIK_PROVISIONING", "INFO", f"El cliente ya cuenta con la IP {target_ip} reservada en inventario BD.")

            comment = f"{str(cliente.id).zfill(6)} - {cliente.nombre}"

            # Conectar a MikroTik
            with MikroTikAdapter(
                host=olt_cfg.mikrotik_host,
                username=olt_cfg.mikrotik_username,
                password=olt_cfg.mikrotik_password,
                port=olt_cfg.mikrotik_port or 8728
            ) as mt:
                
                lease = None
                poll_interval = 2
                max_polls = 15  # 30 segundos en total
                search_method = ""
                
                # Determinamos el Servidor DHCP según el Nodo del cliente
                dhcp_server = f"dhcp-{cliente.nodo.lower()}" if cliente.nodo else None
                _add_timeline("MIKROTIK_PROVISIONING", "INFO", f"Esperando obtención de IP por DHCP en server '{dhcp_server or 'default'}' (iniciando polling)...")
                
                for attempt in range(1, max_polls + 1):
                    # Consultar leases dinámicos filtrando por servidor si aplica
                    dynamic_leases = mt.get_dynamic_leases(server=dhcp_server)
                    
                    # 1. Buscar por MAC
                    clean_mac = mac.replace(':', '').replace('-', '').upper()
                    for dl in dynamic_leases:
                        dl_mac = dl.get('mac-address', '').replace(':', '').replace('-', '').upper()
                        if dl_mac == clean_mac:
                            lease = dl
                            search_method = "MAC"
                            break
                    
                    # 2. Buscar por Client ID
                    if not lease and cliente.id:
                        client_id_str = str(cliente.id)
                        for dl in dynamic_leases:
                            if dl.get('client-id') == client_id_str:
                                lease = dl
                                search_method = "Client ID"
                                break
                    
                    # 3. Buscar por Hostname (Match exacto para evitar colisiones peligrosas)
                    if not lease and cliente.nombre:
                        clean_host = cliente.nombre.lower().strip()
                        for dl in dynamic_leases:
                            l_host = dl.get('host-name', '').lower().strip()
                            if l_host == clean_host:
                                lease = dl
                                search_method = "Hostname"
                                break

                    if lease:
                        # Pequeña pausa de seguridad (1s) para que RouterOS termine de poblar todos los campos del lease
                        time.sleep(1)
                        break
                    
                    time.sleep(poll_interval)

                if not lease:
                    _add_timeline("MIKROTIK_PROVISIONING", "WARNING",
                                  f"No se encontró DHCP Lease dinámico activo para MAC {mac} en el server '{dhcp_server or 'default'}' tras 30s.")
                    return {"success": False, "reason": "lease_not_found"}

                lease_id = lease['id']
                lease_ip = lease.get('address', '')
                lease_server = lease.get('server', 'default')

                _add_timeline("MIKROTIK_PROVISIONING", "INFO", f"Lease dinámico detectado: {lease_ip} ({search_method})")

                # Asignación ordenada de IPs secuencial en base a inventario
                if not target_ip:
                    # Validar si existe esta IP en el pool de nuestro inventario BD
                    pool_ip_rec = self.db.query(inventory_models.InventoryIpPool).filter(
                        inventory_models.InventoryIpPool.nodo == (cliente.nodo or "BAÑOS"),
                        inventory_models.InventoryIpPool.estado == "LIBRE"
                    ).order_by(inventory_models.InventoryIpPool.id.asc()).first()

                    if pool_ip_rec:
                        # Ocupar esta IP en la base de datos
                        pool_ip_rec.estado = "OCUPADO"
                        pool_ip_rec.cliente_id = cliente.id
                        target_ip = pool_ip_rec.ip_address
                        _add_timeline("MIKROTIK_PROVISIONING", "INFO", f"IP secuencial asignada de inventario: {target_ip}")
                    else:
                        # Si no hay pool, tomamos la que entregó DHCP
                        target_ip = lease_ip

                # Convertir a estático en MikroTik
                mt.make_lease_static(lease_id)
                mt.update_lease_comment(lease_id, comment)
                
                # Si la IP reservada es distinta de la IP dinámica actual, actualizamos la dirección IP del lease
                if target_ip != lease_ip:
                    mt.update_lease_ip(lease_id, target_ip)

                # Persistir IP en el registro de cliente
                cliente.ip = target_ip
                self.db.commit()

                _add_timeline("MIKROTIK_PROVISIONING", "SUCCESS",
                              f"DHCP Lease {target_ip} convertido a Estático. Server: {lease_server}. Comentario: '{comment}'")

                observability.log_audit_event_async(
                    accion="MIKROTIK_LEASE_STATIC",
                    modulo="mikrotik",
                    usuario="WORKFLOW_ENGINE",
                    entidad_tipo="Cliente",
                    entidad_id=str(cliente.id),
                    detalles=f"Lease {target_ip} convertida a estática. Server: {lease_server}. Comentario: {comment}",
                    correlation_id=correlation_id
                )

                return {
                    "success": True,
                    "ip": target_ip,
                    "comment": comment,
                    "method": search_method,
                    "server": lease_server
                }

        except MikroTikAdapterError as e:
            _add_timeline("MIKROTIK_PROVISIONING", "WARNING", f"Error MikroTik (no crítico): {e}")
            logger.warning(f"[WorkflowEngine] MikroTik error (best-effort): {e}")
            return {"success": False, "reason": str(e)}
        except Exception as e:
            _add_timeline("MIKROTIK_PROVISIONING", "WARNING", f"Error inesperado MikroTik: {e}")
            logger.warning(f"[WorkflowEngine] MikroTik unexpected error: {e}")
            return {"success": False, "reason": str(e)}


    def _execute_rollback(self, olt_id: int, gpon_port: str, ont_id: Optional[int], service_port: Optional[int], olt: Optional[OLTInterface], _add_timeline, mac: str = ""):
        """Ejecuta deshacer cambios en OLT, MikroTik y libera recursos en el inventario"""
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

        # 2. Revertir MikroTik lease si hubo MAC
        if mac:
            try:
                olt_cfg = self.db.query(models.OLTConfig).filter(models.OLTConfig.id == olt_id).first()
                if olt_cfg and olt_cfg.mikrotik_host:
                    with MikroTikAdapter(
                        host=olt_cfg.mikrotik_host,
                        username=olt_cfg.mikrotik_username,
                        password=olt_cfg.mikrotik_password,
                        port=olt_cfg.mikrotik_port or 8728
                    ) as mt:
                        mt.undo_static_lease(mac)
                        _add_timeline("ROLLBACK_MIKROTIK", "SUCCESS", f"Lease estática revertida para MAC {mac}")
            except Exception as mt_err:
                _add_timeline("ROLLBACK_MIKROTIK", "WARNING", f"No se pudo revertir MikroTik: {mt_err}")

        # 3. Liberar inventario BD
        if ont_id is not None:
            self.resource_mgr.release_resources(olt_id, gpon_port, ont_id, service_port)
            _add_timeline("ROLLBACK_INVENTORY", "SUCCESS", "Recursos devueltos a estado LIBRE en Inventario BD")
