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
    Obtiene candidatos reales de ONTs detectados por la OLT con 'display ont autofind all'.
    SOLO retorna lo que la OLT detecta en tiempo real. No hay fallback a base de datos.
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

        # Si no hay OLT configurada, retornar error claro
        if not olt_config:
            return {
                'total': 0,
                'candidates': [],
                'source': 'error',
                'error': 'No hay OLTs activas configuradas. Registra una OLT en Configuraciones → OLTs Huawei.'
            }

        candidates = []
        olt_success = False
        error_detail = None

        logger.info(f"Conectando a OLT {olt_config.nombre} ({olt_config.host}:{olt_config.port}) para autofind...")
        try:
            olt = OLTInterface(
                host=olt_config.host,
                port=olt_config.port or 22,
                username=olt_config.username,
                password=olt_config.password,
                timeout=olt_config.connection_timeout or 30,
                max_retries=olt_config.max_retries or 2,
                retry_backoff_base=olt_config.retry_backoff_base or 1
            )
            olt.connect()
            logger.info("✓ Conectado. Ejecutando 'display ont autofind all' en modo config...")
            candidates = olt.display_autofind_all()
            olt_success = True
            logger.info(f"✓ OLT retornó {len(candidates)} ONTs detectados")

            # No filtrar por estado aquí: mostrar TODOS los que autofind reporta
            # (pending, not-activated, etc.) ya que el admin decide cuál activar

        except Exception as e:
            logger.error(f"✗ Error al contactar OLT {olt_config.host}: {e}", exc_info=True)
            error_detail = str(e)
            candidates = []
            olt_success = False

        return {
            'total': len(candidates),
            'candidates': candidates,
            'source': 'olt' if olt_success else 'error',
            'olt_nombre': olt_config.nombre,
            'olt_host': olt_config.host,
            'error': error_detail if not olt_success else None,
        }

    except Exception as e:
        logger.error(f"Error en get_mac_candidates: {e}")
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
    port: int = 22,
    username: str = "root",
    password: str = "admin",
    nodo_asociado: Optional[str] = None,
    device_type: str = "huawei",
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
            device_type=device_type,
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
            'port': olt_config.port,
            'username': olt_config.username,
            'device_type': olt_config.device_type,
            'nodo_asociado': olt_config.nodo_asociado,
            'active': olt_config.active,
            'message': 'OLT configurada exitosamente'
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creando OLT config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/config/{config_id}")
def update_olt_config(
    config_id: int,
    nombre: Optional[str] = None,
    host: Optional[str] = None,
    port: Optional[int] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    nodo_asociado: Optional[str] = None,
    device_type: Optional[str] = None,
    active: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user = Depends(require_role(["administrador"]))
):
    """Actualiza una configuración de OLT"""
    try:
        config = db.query(models.OLTConfig).filter(models.OLTConfig.id == config_id).first()
        if not config:
            raise HTTPException(status_code=404, detail=f"OLT config {config_id} no encontrada")
        
        if nombre is not None:
            config.nombre = nombre
        if host is not None:
            config.host = host
        if port is not None:
            config.port = port
        if username is not None:
            config.username = username
        if password is not None:
            config.password = password
        if nodo_asociado is not None:
            config.nodo_asociado = nodo_asociado
        if device_type is not None:
            config.device_type = device_type
        if active is not None:
            config.active = active
        
        config.updated_by = current_user.usuario
        db.commit()
        db.refresh(config)
        
        logger.info(f"✓ OLT config {config_id} actualizada")
        return {
            'id': config.id,
            'nombre': config.nombre,
            'host': config.host,
            'port': config.port,
            'username': config.username,
            'device_type': config.device_type,
            'nodo_asociado': config.nodo_asociado,
            'active': config.active,
            'message': 'OLT actualizada exitosamente'
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error actualizando OLT config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/config/{config_id}")
def delete_olt_config(
    config_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_role(["administrador"]))
):
    """Elimina una configuración de OLT"""
    try:
        config = db.query(models.OLTConfig).filter(models.OLTConfig.id == config_id).first()
        if not config:
            raise HTTPException(status_code=404, detail=f"OLT config {config_id} no encontrada")
        
        nombre = config.nombre
        db.delete(config)
        db.commit()
        
        logger.info(f"✓ OLT config '{nombre}' eliminada")
        return {'message': f"OLT '{nombre}' eliminada exitosamente"}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error eliminando OLT config: {e}")
        raise HTTPException(status_code=500, detail=str(e))

