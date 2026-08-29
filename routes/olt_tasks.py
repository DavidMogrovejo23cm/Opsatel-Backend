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

# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, HTTPException, Query
# pyrefly: ignore [missing-import]
from pydantic import BaseModel
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import Session
# pyrefly: ignore [missing-import]
from sqlalchemy import and_, or_, desc

from database import get_db
import models
# pyrefly: ignore [missing-import]
from services.command_sanitizer import CommandSanitizer, CommandSanitizationError
from routes.auth import require_role, get_current_user
from services.olt_interface import OLTInterface

import unicodedata

def is_nodo_sayausi(nodo_val) -> bool:
    if not nodo_val:
        return False
    s = unicodedata.normalize('NFD', str(nodo_val)).encode('ascii', 'ignore').decode('utf-8').upper()
    return "SAYAUSI" in s

router = APIRouter(prefix="/olt-tasks", tags=["OLT Tasks"])
logger = logging.getLogger(__name__)

# ============================================================================
# SCHEMAS/RESPONSES
# ============================================================================

class OLTTaskCreate(BaseModel):
    cliente_id: int
    action: str
    payload: dict

class OLTTaskResponse:
    """Respuesta de tarea OLT"""
    pass  # Se usa dict directamente para simplificar


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.post("/", dependencies=[Depends(require_role(["administrador", "tecnico"]))])
def create_olt_task(
    task_in: OLTTaskCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Crea una nueva tarea OLT en la cola.
    
    Args:
        task_in: Datos de la tarea a crear (cliente_id, action, payload)
    
    Returns:
        Tarea creada con ID
    """
    cliente_id = task_in.cliente_id
    action = task_in.action
    payload = task_in.payload
    
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
            created_by=current_user.username,
            created_at=datetime.now()
        )
        
        db.add(task)
        db.flush() # Generar el ID autoincremental de la tarea antes de usarlo
        
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
            with OLTInterface(
                host=olt_config.host,
                port=olt_config.port or 22,
                username=olt_config.username,
                password=olt_config.password,
                timeout=olt_config.connection_timeout or 30,
                max_retries=olt_config.max_retries or 2,
                retry_backoff_base=olt_config.retry_backoff_base or 1
            ) as olt:
                logger.info("Conectado. Ejecutando 'display ont autofind all' en modo config...")
                candidates = olt.display_autofind_all()
                olt_success = True
                logger.info(f"OLT retornó {len(candidates)} ONTs detectados")

        except Exception as e:
            logger.error(f"Error al contactar OLT {olt_config.host}: {e}", exc_info=True)
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
            # Campos técnicos adicionales solicitados
            'puerto': cliente.puerto,
            'ont': cliente.ont,
            'servicio': cliente.servicio,
            'breach': cliente.breach,
            'id_port': cliente.id_port,
            'service_port': cliente.service_port,
            'ip': cliente.ip,
            'dispositivo': cliente.dispositivo,
            'nap': cliente.nap,
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
    libreqos_server_id: Optional[int] = None,
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
            created_by=current_user.username
        )
        
        # Opcional libreqos_server_id
        try:
            # Dado que el endpoint recibe parámetros Query o Form, agregaremos el parámetro formal si lo reescribimos,
            # pero por ahora lo dejamos opcional para evitar romper clientes frontend viejos.
            pass
        except:
            pass
        
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


class OLTTestParams(BaseModel):
    host: str
    port: int = 22
    username: str = "root"
    password: str = "admin"
    device_type: str = "huawei"


@router.post("/config/test-raw")
def test_raw_olt_connection(
    params: OLTTestParams,
    current_user = Depends(require_role(["administrador"]))
):
    """Prueba la conexión a una OLT usando credenciales crudas (antes de guardar)"""
    try:
        logger.info(f"Probando conexión cruda a OLT: {params.host}:{params.port}")
        olt = OLTInterface(
            host=params.host,
            port=params.port or 22,
            username=params.username,
            password=params.password,
            timeout=10,
            max_retries=1
        )
        success = olt.connect()
        if success:
            olt.disconnect()
            return {
                'success': True,
                'message': f"¡Conexión SSH exitosa a {params.host}!"
            }
        else:
            return {
                'success': False,
                'message': f"No se pudo conectar a {params.host}."
            }
    except Exception as e:
        logger.error(f"Error probando conexión cruda a OLT: {e}")
        return {
            'success': False,
            'message': f"Error de conexión: {str(e)}"
        }


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
    libreqos_server_id: Optional[int] = None,
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
        
        if libreqos_server_id is not None:
            config.libreqos_server_id = libreqos_server_id if libreqos_server_id != 0 else None
        
        config.updated_by = current_user.username
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





@router.post("/config/{config_id}/test")
def test_olt_config_connection(
    config_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_role(["administrador"]))
):
    """Prueba la conexión a una OLT existente"""
    try:
        config = db.query(models.OLTConfig).filter(models.OLTConfig.id == config_id).first()
        if not config:
            raise HTTPException(status_code=404, detail="Configuración de OLT no encontrada")
        
        logger.info(f"Probando conexión a OLT registrada: {config.nombre} ({config.host}:{config.port})")
        olt = OLTInterface(
            host=config.host,
            port=config.port or 22,
            username=config.username,
            password=config.password,
            timeout=10,
            max_retries=1
        )
        
        success = olt.connect()
        if success:
            olt.disconnect()
            return {
                'success': True,
                'message': f"¡Conexión SSH exitosa a la OLT {config.nombre} ({config.host})!"
            }
        else:
            return {
                'success': False,
                'message': f"No se pudo conectar a la OLT {config.nombre} ({config.host})."
            }
    except Exception as e:
        logger.error(f"Error probando conexión a OLT: {e}")
        return {
            'success': False,
            'message': f"Error de conexión: {str(e)}"
        }


# ============================================================================
# MIKROTIK CONFIG
# ============================================================================

class MikroTikConfigUpdate(BaseModel):
    mikrotik_host: Optional[str] = None
    mikrotik_port: Optional[int] = 8728
    mikrotik_username: Optional[str] = None
    mikrotik_password: Optional[str] = None


@router.put("/config/{config_id}/mikrotik")
def update_mikrotik_config(
    config_id: int,
    data: MikroTikConfigUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(require_role(["administrador"]))
):
    """Configura las credenciales de MikroTik para un nodo OLT"""
    config = db.query(models.OLTConfig).filter(models.OLTConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="OLT config no encontrada")

    if data.mikrotik_host is not None:
        config.mikrotik_host = data.mikrotik_host
    if data.mikrotik_port is not None:
        config.mikrotik_port = data.mikrotik_port
    if data.mikrotik_username is not None:
        config.mikrotik_username = data.mikrotik_username
    if data.mikrotik_password is not None:
        config.mikrotik_password = data.mikrotik_password

    config.updated_by = current_user.username
    db.commit()

    return {
        "success": True,
        "message": f"MikroTik configurado para OLT '{config.nombre}'",
        "mikrotik_host": config.mikrotik_host,
        "mikrotik_port": config.mikrotik_port
    }


@router.post("/config/{config_id}/mikrotik/test")
def test_mikrotik_connection(
    config_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_role(["administrador"]))
):
    """Prueba la conexión a MikroTik para un nodo OLT"""
    from network.adapters.mikrotik import MikroTikAdapter, MikroTikAdapterError

    config = db.query(models.OLTConfig).filter(models.OLTConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="OLT config no encontrada")
    if not config.mikrotik_host:
        raise HTTPException(status_code=400, detail="No hay MikroTik configurado para este nodo")

    try:
        with MikroTikAdapter(
            host=config.mikrotik_host,
            username=config.mikrotik_username,
            password=config.mikrotik_password,
            port=config.mikrotik_port or 8728,
            timeout=8,
            max_retries=1
        ) as mt:
            sysres = mt.get_system_resource()
            return {
                "success": True,
                "message": f"Conexión exitosa a MikroTik {config.mikrotik_host}",
                "version": sysres.get("version", ""),
                "board": sysres.get("board-name", ""),
                "uptime": sysres.get("uptime", "")
            }
    except MikroTikAdapterError as e:
        return {"success": False, "message": str(e)}
    except Exception as e:
        return {"success": False, "message": f"Error inesperado: {str(e)}"}


# ============================================================================
# VER POTENCIA ONT
# ============================================================================

@router.get("/clientes/{cliente_id}/potencia")
def ver_potencia_ont(
    cliente_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_role(["administrador", "soporte", "tecnico"]))
):
    """
    Lee en tiempo real la potencia óptica de la ONT del cliente desde la OLT Huawei.
    Devuelve RX, TX, OLT RX, OLT TX, temperatura, voltaje, corriente, estado y tiempo online.
    """
    import observability
    # pyrefly: ignore [missing-import]
    from sqlalchemy import or_

    cliente = db.query(models.Cliente).filter(models.Cliente.id == cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    gpon_port = getattr(cliente, "puerto", None)
    ont_id_str = getattr(cliente, "id_port", None)

    if not gpon_port or not ont_id_str:
        raise HTTPException(status_code=400, detail="El cliente no tiene puerto GPON asignado")

    # El modelo suele guardar "Puerto 10"; la OLT necesita 0/0/10 o 0/1/10.
    if "/" not in str(gpon_port):
        import re
        match = re.search(r"\d+", str(gpon_port))
        if not match:
            raise HTTPException(status_code=400, detail=f"Puerto GPON inválido: {gpon_port}")
        frame = "1" if is_nodo_sayausi(getattr(cliente, "nodo", "")) else "0"
        gpon_port = f"0/{frame}/{match.group()}"

    try:
        ont_id = int(ont_id_str)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"ONT ID inválido: {ont_id_str}")

    # Buscar OLT activa para el nodo del cliente
    nodo = getattr(cliente, "nodo", None)
    if nodo:
        olt_config = db.query(models.OLTConfig).filter(
            models.OLTConfig.active == True,
            or_(
                models.OLTConfig.nodo_asociado == nodo,
                models.OLTConfig.nodo_asociado == None,
                models.OLTConfig.nodo_asociado == ""
            )
        ).first()
    else:
        olt_config = db.query(models.OLTConfig).filter(models.OLTConfig.active == True).first()

    if not olt_config:
        raise HTTPException(status_code=503, detail="No hay OLT activa configurada para este nodo")

    try:
        olt = OLTInterface(
            host=olt_config.host,
            port=olt_config.port or 23,
            username=olt_config.username,
            password=olt_config.password,
            timeout=15,
            max_retries=1
        )

        connected = olt.connect()
        if not connected:
            raise HTTPException(status_code=503, detail="No se pudo conectar a la OLT")

        try:
            power_data = olt.check_ont_power(gpon_port, ont_id)
        finally:
            olt.disconnect()

        # Auditoría
        import observability as obs
        obs.log_audit_event_async(
            accion="VER_POTENCIA_ONT",
            modulo="olt_tasks",
            usuario=current_user.username,
            entidad_tipo="Cliente",
            entidad_id=str(cliente_id),
            detalles=f"Potencia consultada: Puerto {gpon_port} ONT {ont_id} | RX={power_data.get('rx_power','N/A')} dBm"
        )

        return {
            "success": True,
            "cliente_id": cliente_id,
            "nombre": cliente.nombre,
            "gpon_port": gpon_port,
            "ont_id": ont_id,
            "olt": olt_config.nombre,
            "potencia": power_data
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error consultando potencia ONT para cliente {cliente_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error consultando potencia: {str(e)}")
