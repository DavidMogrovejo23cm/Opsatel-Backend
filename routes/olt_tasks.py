"""
OPSATEL ISP - OLT Tasks API Routes
===================================
Endpoints para gestión de cola de tareas OLT.

Rutas:
- POST   /olt-tasks              Crear nueva tarea
- GET    /olt-tasks              Listar tareas (con filtros)
- GET    /olt-tasks/{id}         Obtener detalles de tarea
- GET    /olt-tasks/{id}/logs    Obtener auditoría de tarea
- GET    /clientes/{id}/olt-status  Estado OLT del cliente

Autor: Arquitecto de Software Senior
Versión: 1.0.0
"""

import json
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc

from database import get_db
import models
from services.command_sanitizer import CommandSanitizer, CommandSanitizationError
from routes.auth import require_role, get_current_user
from services.olt_interface import OLTInterface

router = APIRouter(prefix="/olt-tasks", tags=["OLT Tasks"])
logger = logging.getLogger(__name__)

# ============================================================================
# SCHEMAS/RESPONSES
# ============================================================================

class OLTTaskResponse:
    """Respuesta de tarea OLT"""
    pass  # Se usa dict directamente para simplificar


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.post("/", dependencies=[Depends(require_role(["administrador", "tecnico"]))])
def create_olt_task(
    cliente_id: int,
    action: str,
    payload: dict,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Crea una nueva tarea OLT en la cola.
    
    Args:
        cliente_id: ID del cliente a aprovisionarse
        action: Tipo de acción ('add_ont', 'add_service', etc.)
        payload: Parámetros de la acción (JSON)
    
    Returns:
        Tarea creada con ID
    """
    try:
        logger.info(f"Creando tarea OLT para cliente {cliente_id}, acción: {action}")
        
        # Validar cliente existe
        cliente = db.query(models.Cliente).filter(models.Cliente.id == cliente_id).first()
        if not cliente:
            raise HTTPException(status_code=404, detail=f"Cliente {cliente_id} no encontrado")
        
        # Validar acción
        valid_actions = ['add_ont', 'add_service', 'set_breach', 'check_power', 'remove_ont', 'del_service']
        if action not in valid_actions:
            raise HTTPException(status_code=400, detail=f"Acción inválida: {action}")
        
        # Sanitizar payload (esto es crítico de seguridad)
        try:
            validated_payload = CommandSanitizer.validate_payload(action, payload)
        except CommandSanitizationError as e:
            raise HTTPException(status_code=400, detail=f"Payload inválido: {e}")
        
        # Obtener OLT basada en el nodo del cliente
        olt_config = db.query(models.OLTConfig).filter(
            or_(
                models.OLTConfig.nodo_asociado == cliente.nodo,
                models.OLTConfig.nodo_asociado == None  # NULL significa todas
            ),
            models.OLTConfig.active == True
        ).first()
        
        if not olt_config:
            raise HTTPException(status_code=500, detail=f"No hay OLT configurada para nodo {cliente.nodo}")
        
        # Crear tarea
        task = models.OLTTask(
            cliente_id=cliente_id,
            olt_id=olt_config.id,
            action=action,
            payload=json.dumps(validated_payload),
            status='pending',
            priority=0,
            created_by=current_user.usuario,
            created_at=datetime.now()
        )
        
        db.add(task)
        
        # Actualizar estado del cliente
        cliente.olt_sync_status = 'in_queue'
        cliente.olt_task_id = task.id
        
        db.commit()
        db.refresh(task)
        
        logger.info(f"✓ Tarea OLT {task.id} creada para cliente {cliente_id}")
        
        return {
            'id': task.id,
            'cliente_id': task.cliente_id,
            'olt_id': task.olt_id,
            'action': task.action,
            'status': task.status,
            'created_at': task.created_at.isoformat(),
            'message': 'Tarea encolada exitosamente'
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creando tarea OLT: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error interno: {e}")


@router.get("/")
def list_olt_tasks(
    status: Optional[str] = Query(None, description="Filtrar por status (pending, processing, completed, failed)"),
    cliente_id: Optional[int] = Query(None, description="Filtrar por cliente"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Lista tareas OLT con filtros opcionales.
    """
    try:
        query = db.query(models.OLTTask)
        
        # Filtros
        if status:
            query = query.filter(models.OLTTask.status == status)
        if cliente_id:
            query = query.filter(models.OLTTask.cliente_id == cliente_id)
        
        # Contar total
        total = query.count()
        
        # Paginar y ordenar
        tasks = query.order_by(
            desc(models.OLTTask.priority),
            desc(models.OLTTask.created_at)
        ).offset(offset).limit(limit).all()
        
        return {
            'total': total,
            'limit': limit,
            'offset': offset,
            'tasks': [
                {
                    'id': t.id,
                    'cliente_id': t.cliente_id,
                    'action': t.action,
                    'status': t.status,
                    'retry_count': t.retry_count,
                    'created_at': t.created_at.isoformat() if t.created_at else None,
                    'started_at': t.started_at.isoformat() if t.started_at else None,
                    'completed_at': t.completed_at.isoformat() if t.completed_at else None,
                    'error_message': t.error_message
                }
                for t in tasks
            ]
        }
    
    except Exception as e:
        logger.error(f"Error listando tareas: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{task_id}")
def get_olt_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Obtiene detalles de una tarea específica.
    """
    try:
        task = db.query(models.OLTTask).filter(models.OLTTask.id == task_id).first()
        
        if not task:
            raise HTTPException(status_code=404, detail=f"Tarea {task_id} no encontrada")
        
        return {
            'id': task.id,
            'cliente_id': task.cliente_id,
            'olt_id': task.olt_id,
            'action': task.action,
            'payload': json.loads(task.payload) if task.payload else {},
            'status': task.status,
            'priority': task.priority,
            'retry_count': task.retry_count,
            'response': task.response,
            'response_json': task.response_json,
            'error_message': task.error_message,
            'error_code': task.error_code,
            'created_at': task.created_at.isoformat() if task.created_at else None,
            'started_at': task.started_at.isoformat() if task.started_at else None,
            'completed_at': task.completed_at.isoformat() if task.completed_at else None,
            'created_by': task.created_by,
            'processed_by': task.processed_by
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error obteniendo tarea: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{task_id}/logs")
def get_olt_task_logs(
    task_id: int,
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Obtiene auditoría/logs de una tarea (historial de intentos).
    """
    try:
        # Verificar que la tarea existe
        task = db.query(models.OLTTask).filter(models.OLTTask.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail=f"Tarea {task_id} no encontrada")
        
        # Obtener logs
        logs = db.query(models.OLTTaskLog).filter(
            models.OLTTaskLog.task_id == task_id
        ).order_by(models.OLTTaskLog.attempt).limit(limit).all()
        
        return {
            'task_id': task_id,
            'total_logs': len(logs),
            'logs': [
                {
                    'id': log.id,
                    'attempt': log.attempt,
                    'status_before': log.status_before,
                    'status_after': log.status_after,
                    'command_sent': log.command_sent,
                    'success': log.success,
                    'error_message': log.error_message,
                    'duration_ms': log.duration_ms,
                    'created_at': log.created_at.isoformat() if log.created_at else None
                }
                for log in logs
            ]
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error obteniendo logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# CLIENTE OLT STATUS
# ============================================================================

@router.get("/cliente/{cliente_id}/status")
def get_cliente_olt_status(
    cliente_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Obtiene estado OLT actual del cliente (última tarea, estado, potencia, etc.).
    Este endpoint es crítico para el frontend de activación.
    """
    try:
        # Obtener cliente
        cliente = db.query(models.Cliente).filter(models.Cliente.id == cliente_id).first()
        if not cliente:
            raise HTTPException(status_code=404, detail=f"Cliente {cliente_id} no encontrado")
        
        # Obtener última tarea OLT
        last_task = db.query(models.OLTTask).filter(
            models.OLTTask.cliente_id == cliente_id
        ).order_by(desc(models.OLTTask.created_at)).first()
        
        # Construir respuesta
        response = {
            'cliente_id': cliente_id,
            'cliente_nombre': cliente.nombre,
            'cliente_estado': cliente.estado,
            'olt_sync_status': cliente.olt_sync_status,
            'olt_error_message': cliente.olt_error_message,
            'potencia': cliente.potencia,
            'potencia_verificada': cliente.potencia_verificada,
            'potencia_last_check': cliente.potencia_last_check.isoformat() if cliente.potencia_last_check else None,
            'last_task': None
        }
        
        # Detalles de última tarea
        if last_task:
            response['last_task'] = {
                'id': last_task.id,
                'action': last_task.action,
                'status': last_task.status,
                'retry_count': last_task.retry_count,
                'error_message': last_task.error_message,
                'created_at': last_task.created_at.isoformat() if last_task.created_at else None,
                'completed_at': last_task.completed_at.isoformat() if last_task.completed_at else None,
                'response_json': last_task.response_json
            }
        
        logger.debug(f"Estado OLT para cliente {cliente_id}: {response}")
        return response
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error obteniendo estado OLT: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# MAC CANDIDATES (FRONTEND HELPERS)
# ============================================================================
@router.get("/mac-candidates")
def get_mac_candidates(
    cliente_id: Optional[int] = Query(None, description="ID de cliente para priorizar su MAC"),
    nodo: Optional[str] = Query(None, description="Filtrar por nodo"),
    puerto: Optional[str] = Query(None, description="Filtrar por puerto"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Obtiene candidatos reales de ONTs pendientes desde la OLT con 'display ont autofind all'.
    Si no es posible conectar, retorna fallback desde la base de datos de clientes.
    """
    try:
        # Primero intentar obtener la OLT activa para el nodo
        olt_config = None
        if nodo:
            olt_config = db.query(models.OLTConfig).filter(
                models.OLTConfig.active == True,
                models.OLTConfig.nodo_asociado == nodo
            ).first()
        
        # Si no se encuentra para ese nodo específico, buscar una genérica (sin nodo asociado)
        if not olt_config:
            olt_config = db.query(models.OLTConfig).filter(
                models.OLTConfig.active == True,
                or_(
                    models.OLTConfig.nodo_asociado == None,
                    models.OLTConfig.nodo_asociado == ""
                )
            ).first()
            
        # Como último recurso, obtener la primera OLT activa disponible
        if not olt_config:
            olt_config = db.query(models.OLTConfig).filter(models.OLTConfig.active == True).first()

        candidates = []
        olt_success = False
        
        if olt_config:
            logger.info(f"Conectando a OLT {olt_config.nombre} ({olt_config.host}:{olt_config.port})...")
            try:
                olt = OLTInterface(
                    host=olt_config.host,
                    port=olt_config.port or 23,
                    username=olt_config.username,
                    password=olt_config.password,
                    timeout=olt_config.connection_timeout or 30,
                    max_retries=olt_config.max_retries or 3,
                    retry_backoff_base=olt_config.retry_backoff_base or 1
                )
                olt.connect()
                logger.info("Ejecutando 'display ont autofind all'...")
                candidates = olt.display_autofind_all()
                olt_success = True
                logger.info(f"✓ OLT retornó {len(candidates)} candidatos")
                
                # Filtrar solo equipos con estado "pending" o "not activated"
                pending = [c for c in candidates if c.get('status', '').lower() in ('pending', 'not activated', 'not-activated', 'inactive')]
                if pending:
                    candidates = pending
                    logger.info(f"✓ Filtrados a {len(candidates)} candidatos pendientes")
                    
            except Exception as e:
                logger.error(f"✗ Error conectando a OLT o ejecutando comando: {e}", exc_info=True)
                logger.info("Cayendo al fallback de base de datos...")
                candidates = []
                olt_success = False

        if not olt_success:
            # Fallback a los MACs en la tabla de clientes PENDIENTES solamente
            logger.info("Buscando clientes pendientes en base de datos (fallback)...")
            q = db.query(models.Cliente).filter(
                models.Cliente.mac != None,
                models.Cliente.estado.in_(['Pendiente', 'En Activación'])
            )
            if nodo:
                q = q.filter(models.Cliente.nodo == nodo)
            if puerto:
                q = q.filter(models.Cliente.puerto == puerto)

            q = q.order_by(desc(models.Cliente.id)).limit(limit)
            rows = q.all()

            seen = set()
            for r in rows:
                mac = (r.mac or '').strip().upper()
                if not mac:
                    continue
                if mac in seen:
                    continue
                seen.add(mac)
                candidates.append({
                    'gpon_port': None,
                    'ont_id': None,
                    'mac': mac,
                    'status': 'db-fallback',
                    'cliente_id': r.id,
                    'cliente_nombre': r.nombre,
                    'instalation_date': getattr(r, 'instalation_date', None)
                })

        # Priorizar la MAC del cliente actual si existe
        if cliente_id:
            c = db.query(models.Cliente).filter(models.Cliente.id == cliente_id).first()
            if c and c.mac:
                m = c.mac.strip().upper()
                candidates = [x for x in candidates if x.get('mac', '').upper() != m]
                candidates.insert(0, {
                    'gpon_port': None,
                    'ont_id': None,
                    'mac': m,
                    'status': 'cliente-mac',
                    'cliente_id': c.id,
                    'cliente_nombre': c.nombre,
                    'instalation_date': getattr(c, 'instalation_date', None)
                })

        return {
            'total': len(candidates),
            'candidates': candidates,
            'source': 'olt' if olt_success else 'db'
        }

    except Exception as e:
        logger.error(f"Error obteniendo mac-candidates: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ADMIN: Gestión de OLT Config
# ============================================================================

@router.get("/config/")
def list_olt_configs(
    db: Session = Depends(get_db),
    current_user = Depends(require_role(["administrador"]))
):
    """Lista todas las OLTs configuradas"""
    try:
        configs = db.query(models.OLTConfig).all()
        
        return {
            'total': len(configs),
            'configs': [
                {
                    'id': c.id,
                    'nombre': c.nombre,
                    'host': c.host,
                    'port': c.port,
                    'device_type': c.device_type,
                    'nodo_asociado': c.nodo_asociado,
                    'active': c.active,
                    'max_retries': c.max_retries,
                    'created_at': c.created_at.isoformat() if c.created_at else None
                }
                for c in configs
            ]
        }
    
    except Exception as e:
        logger.error(f"Error listando OLT configs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/config/")
def create_olt_config(
    nombre: str,
    host: str,
    port: int = 23,
    username: str = "admin",
    password: str = "admin",
    nodo_asociado: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user = Depends(require_role(["administrador"]))
):
    """Crea una nueva configuración de OLT"""
    try:
        logger.info(f"Creando OLT config: {nombre} ({host}:{port})")
        
        # Validar que no exista
        existing = db.query(models.OLTConfig).filter(models.OLTConfig.nombre == nombre).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"OLT '{nombre}' ya existe")
        
        # Crear
        olt_config = models.OLTConfig(
            nombre=nombre,
            host=host,
            port=port,
            username=username,
            password=password,
            nodo_asociado=nodo_asociado,
            active=True,
            created_by=current_user.usuario
        )
        
        db.add(olt_config)
        db.commit()
        db.refresh(olt_config)
        
        logger.info(f"✓ OLT config {olt_config.id} creada")
        
        return {
            'id': olt_config.id,
            'nombre': olt_config.nombre,
            'host': olt_config.host,
            'message': 'OLT configurada exitosamente'
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creando OLT config: {e}")
        raise HTTPException(status_code=500, detail=str(e))
