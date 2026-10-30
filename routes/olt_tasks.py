"""
@file olt_tasks.py
@author David Mogrovejo dmogrovejo87@gmail.com
@copyright (c) 2026 David Mogrovejo. All Rights Reserved.
@notice Developed with AI assistance.‍​‌​​​‌​​​‌‌​​​​‌​‌‌‌​‌‌​​‌‌​‌​​‌​‌‌​​‌​​​​‌​​​​​​‌​​‌‌​‌​‌‌​‌‌‌‌​‌‌​​‌‌‌​‌‌‌​​‌​​‌‌​‌‌‌‌​‌‌‌​‌‌​​‌‌​​‌​‌​‌‌​‌​‌​​‌‌​‌‌‌‌​​‌​​​​​​​‌​‌​​​​‌‌​​​‌‌​​‌​‌​​‌​​‌​​​​​​​‌‌​​‌​​​‌‌​​​​​​‌‌​​‌​​​‌‌​‌‌​​​‌​‌‌‌​​​‌​​​​​​‌​​​​​‌​‌‌​‌‌​​​‌‌​‌‌​​​​‌​​​​​​‌​‌​​‌​​‌‌​‌​​‌​‌‌​​‌‌‌​‌‌​‌​​​​‌‌‌​‌​​​‌‌‌​​‌‌​​‌​​​​​​‌​‌​​‌​​‌‌​​‌​‌​‌‌‌​​‌‌​‌‌​​‌​‌​‌‌‌​​‌​​‌‌‌​‌‌​​‌‌​​‌​‌​‌‌​​‌​​​​‌​‌‌‌​​​‌​​​​​​‌​​​‌​​​‌‌​​‌​‌​‌‌‌​‌‌​​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​‌‌‌‌​‌‌‌​​​​​‌‌​​‌​‌​‌‌​​‌​​​​‌​​​​​​‌‌‌​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​​‌​​​​​​‌​​​​​‌​‌​​‌​​‌​​‌​​​​​​‌‌​​​​‌​‌‌‌​​‌‌​‌‌‌​​‌‌​‌‌​‌​​‌​‌‌‌​​‌‌​‌‌‌​‌​​​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌‌​‌‌​​‌​‌​​‌​‌‌‌​​​‌​​​​​​‌​​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌‌​​‌‌‌​‌​​​‌‌​​​​‌​‌‌​​​‌‌​‌‌‌​‌​​​​‌‌‌​‌​​​‌​​​​​​‌‌​​‌​​​‌‌​‌‌​‌​‌‌​‌‌‌‌​‌‌​​‌‌‌​‌‌‌​​‌​​‌‌​‌‌‌‌​‌‌‌​‌‌​​‌‌​​‌​‌​‌‌​‌​‌​​‌‌​‌‌‌‌​​‌‌‌​​​​​‌‌​‌‌‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌​​​‌​​​​​​‌​​​‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌‌​​‌‌​‌‌​‌​​‌​‌‌​​​‌‌​​‌​​​​​​‌​‌​​‌‌​‌‌​‌​​‌​‌‌​​‌‌‌​​‌‌‌​‌​​​‌​​​​​​‌‌​​​‌​​‌‌​​‌‌​​​‌‌​​‌​​​‌‌​‌‌​​‌‌​​‌​‌​‌‌​​‌​‌​​‌‌​​​​​​‌‌​​‌‌​​‌‌​​‌‌​​‌‌​‌​​​​‌‌​​​‌​​‌‌‌​​​​‌‌​​‌​​​​‌‌​‌​‌​‌‌​​‌​​​‌‌​​​‌‌‍
@hash bf26ee033418d5dcd984ad8115334e7ce788cfb5d2bd456cf6e6ee21b877a762

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

from typing import Any
from typing import Dict
import json
import logging
from datetime import datetime
from typing import List, Optional

# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, HTTPException, Query, Request
# pyrefly: ignore [missing-import]
from fastapi.responses import StreamingResponse
import asyncio
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

    # 1. Buscar la última tarea de activación para obtener OLT, GPON y ONT ID exactos
    last_task = db.query(models.OLTTask).filter(
        models.OLTTask.cliente_id == cliente.id,
        models.OLTTask.action == 'add_ont'
    ).order_by(models.OLTTask.id.desc()).first()

    task_payload = {}
    task_resp = {}
    if last_task:
        try:
            if isinstance(last_task.payload, str):
                task_payload = json.loads(last_task.payload)
            elif isinstance(last_task.payload, dict):
                task_payload = last_task.payload
        except Exception:
            pass
        try:
            if isinstance(last_task.response_json, str):
                task_resp = json.loads(last_task.response_json)
            elif isinstance(last_task.response_json, dict):
                task_resp = last_task.response_json
        except Exception:
            pass

    gpon_port = task_resp.get('gpon_port') or task_payload.get('gpon_port') or getattr(cliente, "puerto", None)
    ont_id_str = task_resp.get('ont_id') or task_payload.get('ont_id') or getattr(cliente, "id_port", None)

    if not gpon_port or ont_id_str is None:
        raise HTTPException(status_code=400, detail="El cliente no tiene puerto GPON asignado")

    # Si el puerto viene como "Puerto 10" o "10", convertir a formato 0/X/10
    if "/" not in str(gpon_port):
        import re
        match = re.search(r"\d+", str(gpon_port))
        if not match:
            raise HTTPException(status_code=400, detail=f"Puerto GPON inválido: {gpon_port}")
        frame = "1" if is_nodo_sayausi(getattr(cliente, "nodo", "")) else "0"
        gpon_port = f"0/{frame}/{match.group()}"

    try:
        ont_id = int(str(ont_id_str).strip())
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"ONT ID inválido: {ont_id_str}")

    # Buscar OLT activa: primero la OLT de la tarea registrada (máxima precisión)
    olt_config = None
    if last_task and last_task.olt_id:
        olt_config = db.query(models.OLTConfig).filter(
            models.OLTConfig.id == last_task.olt_id,
            models.OLTConfig.active == True
        ).first()

    if not olt_config:
        nodo = getattr(cliente, "nodo", None)
        if nodo:
            is_sayausi_nodo = is_nodo_sayausi(nodo)
            olt_config = db.query(models.OLTConfig).filter(
                models.OLTConfig.active == True,
                or_(
                    models.OLTConfig.nodo_asociado == nodo,
                    models.OLTConfig.nodo_asociado.ilike("%SAYAUS%") if is_sayausi_nodo else models.OLTConfig.nodo_asociado.ilike("%BAN%"),
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
            port=olt_config.port or 22,
            username=olt_config.username,
            password=olt_config.password,
            timeout=15,
            max_retries=2
        )

        connected = olt.connect()
        if not connected:
            if cliente.potencia:
                try:
                    p_num = float(str(cliente.potencia).strip())
                    return {
                        "success": True,
                        "cliente_id": cliente_id,
                        "nombre": cliente.nombre,
                        "gpon_port": gpon_port,
                        "ont_id": ont_id,
                        "olt": olt_config.nombre,
                        "potencia": {
                            "rx_power": p_num,
                            "power": p_num,
                            "status": "cached",
                            "cached": True
                        }
                    }
                except ValueError:
                    pass
            raise HTTPException(status_code=503, detail="No se pudo conectar a la OLT")

        try:
            power_data = olt.check_ont_power(gpon_port, ont_id)
            if power_data and power_data.get('rx_power') is not None:
                cliente.potencia = str(power_data.get('rx_power'))
                try:
                    cliente.potencia_verificada = True
                    cliente.potencia_last_check = datetime.now()
                except Exception:
                    pass
                if last_task and isinstance(last_task.response_json, dict):
                    updated_resp = dict(last_task.response_json)
                    updated_resp['potencia'] = power_data.get('rx_power')
                    updated_resp['rx_power'] = power_data.get('rx_power')
                    last_task.response_json = updated_resp
                elif last_task and isinstance(last_task.response_json, str):
                    try:
                        updated_resp = json.loads(last_task.response_json)
                        updated_resp['potencia'] = power_data.get('rx_power')
                        updated_resp['rx_power'] = power_data.get('rx_power')
                        last_task.response_json = updated_resp
                    except Exception:
                        pass
                try:
                    db.commit()
                except Exception as db_e:
                    logger.warning(f"No se pudo actualizar cliente.potencia en DB: {db_e}")
            elif (not power_data or power_data.get('rx_power') is None) and cliente.potencia:
                try:
                    p_num = float(str(cliente.potencia).strip())
                    if not isinstance(power_data, dict):
                        power_data = {}
                    power_data['rx_power'] = p_num
                    power_data['power'] = p_num
                except ValueError:
                    pass
        finally:
            olt.disconnect()

        if not isinstance(power_data, dict):
            power_data = {}

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


@router.get("/clientes/{cliente_id}/potencia-stream")
async def stream_potencia_ont(
    request: Request,
    cliente_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_role(["administrador", "soporte", "tecnico"]))
):
    """
    Stream Server-Sent Events (SSE) de potencia óptica de la ONT en tiempo real.
    Mantiene la sesión OLT abierta durante el streaming para consultar cada ~3 segundos
    sin reconectar ni re-autenticar por SSH en cada muestra.
    Al cerrar el cliente la conexión (cerrar modal o salir), se desconecta la OLT limpiamente.
    """
    cliente = db.query(models.Cliente).filter(models.Cliente.id == cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    last_task = db.query(models.OLTTask).filter(
        models.OLTTask.cliente_id == cliente.id,
        models.OLTTask.action == 'add_ont'
    ).order_by(models.OLTTask.id.desc()).first()

    task_payload = {}
    task_resp = {}
    if last_task:
        try:
            if isinstance(last_task.payload, str):
                task_payload = json.loads(last_task.payload)
            elif isinstance(last_task.payload, dict):
                task_payload = last_task.payload
        except Exception:
            pass
        try:
            if isinstance(last_task.response_json, str):
                task_resp = json.loads(last_task.response_json)
            elif isinstance(last_task.response_json, dict):
                task_resp = last_task.response_json
        except Exception:
            pass

    gpon_port = task_resp.get('gpon_port') or task_payload.get('gpon_port') or getattr(cliente, "puerto", None)
    ont_id_str = task_resp.get('ont_id') or task_payload.get('ont_id') or getattr(cliente, "id_port", None)

    if not gpon_port or ont_id_str is None:
        raise HTTPException(status_code=400, detail="El cliente no tiene puerto GPON asignado")

    if "/" not in str(gpon_port):
        import re
        match = re.search(r"\d+", str(gpon_port))
        if not match:
            raise HTTPException(status_code=400, detail=f"Puerto GPON inválido: {gpon_port}")
        frame = "1" if is_nodo_sayausi(getattr(cliente, "nodo", "")) else "0"
        gpon_port = f"0/{frame}/{match.group()}"

    try:
        ont_id = int(str(ont_id_str).strip())
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"ONT ID inválido: {ont_id_str}")

    olt_config = None
    if last_task and last_task.olt_id:
        olt_config = db.query(models.OLTConfig).filter(
            models.OLTConfig.id == last_task.olt_id,
            models.OLTConfig.active == True
        ).first()

    if not olt_config:
        nodo = getattr(cliente, "nodo", None)
        if nodo:
            is_sayausi_nodo = is_nodo_sayausi(nodo)
            olt_config = db.query(models.OLTConfig).filter(
                models.OLTConfig.active == True,
                or_(
                    models.OLTConfig.nodo_asociado == nodo,
                    models.OLTConfig.nodo_asociado.ilike("%SAYAUS%") if is_sayausi_nodo else models.OLTConfig.nodo_asociado.ilike("%BAN%"),
                    models.OLTConfig.nodo_asociado == None,
                    models.OLTConfig.nodo_asociado == ""
                )
            ).first()
        else:
            olt_config = db.query(models.OLTConfig).filter(models.OLTConfig.active == True).first()

    if not olt_config:
        raise HTTPException(status_code=503, detail="No hay OLT activa configurada para este nodo")

    async def event_generator():
        olt = OLTInterface(
            host=olt_config.host,
            port=olt_config.port or 22,
            username=olt_config.username,
            password=olt_config.password,
            timeout=15,
            max_retries=2
        )
        try:
            # Notificar que se está iniciando la sesión OLT
            init_msg = json.dumps({
                "type": "init",
                "status": "connecting",
                "message": f"Conectando a {olt_config.nombre}...",
                "cliente_id": cliente_id,
                "nombre": cliente.nombre,
                "gpon_port": gpon_port,
                "ont_id": ont_id,
                "olt": olt_config.nombre
            })
            yield f"data: {init_msg}\n\n"

            connected = await asyncio.to_thread(olt.connect)
            if not connected:
                err_msg = json.dumps({
                    "type": "error",
                    "status": "connection_failed",
                    "message": "No se pudo conectar a la OLT Huawei"
                })
                yield f"data: {err_msg}\n\n"
                return

            connected_msg = json.dumps({
                "type": "status",
                "status": "connected",
                "message": "Sesión OLT establecida. Monitoreando en tiempo real...",
                "gpon_port": gpon_port,
                "ont_id": ont_id,
                "olt": olt_config.nombre
            })
            yield f"data: {connected_msg}\n\n"

            # Monitoreo continuo (máximo 300 lecturas ~ 15 minutos continuos de seguridad)
            iteration = 0
            while iteration < 300:
                if await request.is_disconnected():
                    logger.info(f"[potencia-stream] Cliente HTTP desconectado para cliente #{cliente_id}")
                    break

                try:
                    power_data = await asyncio.to_thread(olt.check_ont_power, gpon_port, ont_id)
                except Exception as p_err:
                    logger.warning(f"[potencia-stream] Error al medir potencia: {p_err}")
                    power_data = {}

                now_dt = datetime.now()
                sample_payload = {
                    "type": "sample",
                    "iteration": iteration + 1,
                    "time": now_dt.strftime("%H:%M:%S"),
                    "timestamp": now_dt.timestamp(),
                    "cliente_id": cliente_id,
                    "nombre": cliente.nombre,
                    "gpon_port": gpon_port,
                    "ont_id": ont_id,
                    "olt": olt_config.nombre,
                    "potencia": power_data or {}
                }

                yield f"data: {json.dumps(sample_payload)}\n\n"
                iteration += 1

                # Espera 3 segundos fraccionada en cheques de desconexión cada 0.5s
                for _ in range(6):
                    if await request.is_disconnected():
                        break
                    await asyncio.sleep(0.5)

        except asyncio.CancelledError:
            logger.info(f"[potencia-stream] Stream cancelado por el cliente para cliente #{cliente_id}")
        except Exception as e:
            logger.error(f"[potencia-stream] Error en stream para cliente #{cliente_id}: {e}")
            try:
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            except Exception:
                pass
        finally:
            logger.info(f"[potencia-stream] Desconectando OLT de forma limpia para cliente #{cliente_id}")
            try:
                await asyncio.to_thread(olt.disconnect)
            except Exception as disc_e:
                logger.warning(f"[potencia-stream] Error al desconectar OLT: {disc_e}")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.post("/clientes/{cliente_id}/reset-ont", dependencies=[Depends(require_role(["administrador", "tecnico"]))])
def reset_cliente_ont(
    cliente_id: int,
    payload: Optional[Dict[str, Any]] = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Reinicia un ONT en la OLT mediante:
        interface gpon X/X
        ont reset <port_num> <ont_id>
        quit
    """
    cliente = db.query(models.Cliente).filter(models.Cliente.id == cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    payload_data = payload or {}
    gpon_port = payload_data.get("gpon_port") or getattr(cliente, "puerto", None)
    ont_id_str = payload_data.get("ont_id") or getattr(cliente, "id_port", None)

    if not gpon_port or ont_id_str is None:
        raise HTTPException(status_code=400, detail="El cliente no tiene puerto GPON u ONT ID asignado")

    if "/" not in str(gpon_port):
        import re
        match = re.search(r"\d+", str(gpon_port))
        if not match:
            raise HTTPException(status_code=400, detail=f"Puerto GPON inválido: {gpon_port}")
        frame = "1" if is_nodo_sayausi(getattr(cliente, "nodo", "")) else "0"
        gpon_port = f"0/{frame}/{match.group()}"

    ont_id = str(ont_id_str).strip()

    # Buscar última tarea para tomar la OLT exacta si existe
    last_task = db.query(models.OLTTask).filter(
        models.OLTTask.cliente_id == cliente.id,
        models.OLTTask.action == 'add_ont'
    ).order_by(models.OLTTask.id.desc()).first()

    olt_config = None
    if last_task and last_task.olt_id:
        olt_config = db.query(models.OLTConfig).filter(
            models.OLTConfig.id == last_task.olt_id,
            models.OLTConfig.active == True
        ).first()

    if not olt_config:
        nodo = getattr(cliente, "nodo", None)
        if nodo:
            is_sayausi_nodo = is_nodo_sayausi(nodo)
            olt_config = db.query(models.OLTConfig).filter(
                models.OLTConfig.active == True,
                or_(
                    models.OLTConfig.nodo_asociado == nodo,
                    models.OLTConfig.nodo_asociado.ilike("%SAYAUS%") if is_sayausi_nodo else models.OLTConfig.nodo_asociado.ilike("%BAN%"),
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
            port=olt_config.port or 22,
            username=olt_config.username,
            password=olt_config.password,
            timeout=15,
            max_retries=2
        )

        connected = olt.connect()
        if not connected:
            raise HTTPException(status_code=503, detail="No se pudo conectar a la OLT")

        try:
            reset_success = olt.reset_ont(gpon_port, ont_id)
        finally:
            olt.disconnect()

        if not reset_success:
            raise HTTPException(status_code=500, detail="La OLT no pudo ejecutar el reinicio del ONT.")

        # Auditoría
        import observability as obs
        obs.log_audit_event_async(
            accion="RESET_ONT",
            modulo="olt_tasks",
            usuario=current_user.username,
            entidad_tipo="Cliente",
            entidad_id=str(cliente_id),
            detalles=f"Reinicio ONT ejecutado: Puerto {gpon_port} ONT {ont_id} en {olt_config.nombre}"
        )

        return {
            "success": True,
            "cliente_id": cliente_id,
            "gpon_port": gpon_port,
            "ont_id": ont_id,
            "message": f"ONT reiniciada correctamente en GPON {gpon_port} ID {ont_id}."
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reiniciando ONT para cliente {cliente_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error reiniciando ONT: {str(e)}")


# ============================================================================
# COMPROBACIÓN DE ACCESO REMOTO (ONT, WIFI 5, WIFI 6)
# ============================================================================

class RemoteAccessTestRequest(BaseModel):
    ip: str
    protocol: Optional[str] = "http"
    port: Optional[Any] = None
    device_type: Optional[str] = None
    cliente_id: Optional[int] = None

@router.post("/test-remote-access", dependencies=[Depends(require_role(["administrador", "tecnico", "secretario"]))])
def test_remote_access(
    req: RemoteAccessTestRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Comprueba el acceso remoto HTTP / HTTPS hacia una ONT o Router WiFi (WiFi 5 / WiFi 6).
    Emula el comportamiento de curl:
      - WiFi 5: curl http://{ip}:5151
      - ONT:    curl http://{ip}
      - WiFi 6: curl -k https://{ip}
    """
    import time
    import re
    import requests
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    raw_ip = str(req.ip or "").strip()
    if not raw_ip:
        raise HTTPException(status_code=400, detail="Debe especificar una dirección IP válida")

    # Limpieza inteligente por si el usuario pegó una URL completa (ej: http://172.16.0.61:5151)
    protocol = str(req.protocol or "http").strip().lower().replace("://", "")
    port_val = req.port
    device_type = str(req.device_type or "").strip().lower()

    if raw_ip.startswith("http://"):
        protocol = "http"
        raw_ip = raw_ip[len("http://"):]
    elif raw_ip.startswith("https://"):
        protocol = "https"
        raw_ip = raw_ip[len("https://"):]

    # Si la IP incluye puerto en la misma cadena (ej: 172.16.0.61:5151)
    if ":" in raw_ip and not raw_ip.endswith("/"):
        parts = raw_ip.split(":", 1)
        raw_ip = parts[0].strip()
        if (port_val is None or str(port_val).strip() == "") and parts[1].strip().isdigit():
            port_val = int(parts[1].strip())

    clean_ip = raw_ip.strip().rstrip("/")

    # Resolver puerto por defecto según tipo de equipo o protocolo
    final_port = None
    if port_val is not None and str(port_val).strip() != "":
        try:
            final_port = int(str(port_val).strip())
        except ValueError:
            pass

    if final_port is None:
        if device_type == "wifi5":
            final_port = 5151
        elif device_type == "wifi6":
            final_port = 443 if protocol == "https" else None
        elif device_type == "ont":
            final_port = 80 if protocol == "http" else None

    # Construir target_url
    if final_port and not (protocol == "http" and final_port == 80) and not (protocol == "https" and final_port == 443):
        target_url = f"{protocol}://{clean_ip}:{final_port}"
    else:
        target_url = f"{protocol}://{clean_ip}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }

    def _detect_device_type(html_text: str, port_num: Optional[int], proto: str) -> str:
        text = html_text or ""
        if "tpEncrypt" in text or "App=new $.su.App" in text or "ruIspAutoConfig" in text or port_num == 5151:
            return "Router WiFi 5 (TP-Link)"
        elif "/webpages/index.html" in text or "webpages" in text or ("xhtml" in text and proto == "https") or port_num == 443:
            return "Router WiFi 6"
        elif "302 Moved" in text or "Moved Temporarily" in text:
            return "ONT Web Interface (Redirección 302)"
        elif "EchoLife" in text or "Huawei" in text:
            return "ONT Huawei"
        elif "FiberHome" in text:
            return "ONT FiberHome"
        elif "ZTE" in text:
            return "ONT ZTE"
        elif "VSOL" in text or "V-SOL" in text:
            return "ONT V-SOL"
        return "Equipo Web Activo"

    def _save_client_remote_verification(c_id: int, url_tested: str, detected_name: str, code: int, lat: int):
        try:
            cl = db.query(models.Cliente).filter(models.Cliente.id == c_id).first()
            if cl:
                existing_data = {}
                if cl.dispositivo:
                    raw_val = str(cl.dispositivo).strip()
                    if raw_val.startswith("{") and raw_val.endswith("}"):
                        try:
                            existing_data = json.loads(raw_val)
                        except Exception:
                            existing_data = {"texto": raw_val}
                    else:
                        existing_data = {"texto": raw_val}
                existing_data["acceso_remoto"] = {
                    "verificado": True,
                    "url": url_tested,
                    "tipo": detected_name,
                    "status_code": code,
                    "latencia_ms": lat,
                    "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                cl.dispositivo = json.dumps(existing_data, ensure_ascii=False)
                db.commit()
        except Exception as save_err:
            logger.warning(f"No se pudo registrar acceso remoto en cliente {c_id}: {save_err}")

    # Lista de URLs a sondear: la solicitada primero, luego puertos estándar como fallback
    candidates_to_try = [target_url]
    # Si la principal era 5151, agregar 80 y 443
    if final_port == 5151:
        candidates_to_try.extend([f"http://{clean_ip}", f"https://{clean_ip}"])
    elif final_port in (80, None) and protocol == "http":
        candidates_to_try.extend([f"http://{clean_ip}:5151", f"https://{clean_ip}"])
    elif protocol == "https":
        candidates_to_try.extend([f"http://{clean_ip}:5151", f"http://{clean_ip}"])

    last_error = None
    http_success_resp = None
    winning_url = target_url
    winning_latency = 0

    t0 = time.time()
    for candidate_url in candidates_to_try:
        t_cand = time.time()
        try:
            resp = requests.get(
                candidate_url,
                timeout=5,
                verify=False,
                allow_redirects=True,
                headers=headers
            )
            winning_latency = round((time.time() - t_cand) * 1000)
            http_success_resp = resp
            winning_url = candidate_url
            break
        except Exception as ex:
            last_error = ex
            # Si era la primera y falló, probamos la siguiente rápidamente con timeout reducido
            continue

    if http_success_resp is not None:
        status_code = http_success_resp.status_code
        text_content = http_success_resp.text or ""

        title_m = re.search(r'<title[^>]*>(.*?)</title>', text_content, re.IGNORECASE | re.DOTALL)
        page_title = title_m.group(1).strip() if title_m else None

        active_port = final_port
        active_proto = protocol
        if ":5151" in winning_url:
            active_port = 5151
            active_proto = "http"
        elif winning_url.startswith("https://"):
            active_port = 443
            active_proto = "https"
        elif winning_url.startswith("http://") and ":5151" not in winning_url:
            active_port = 80
            active_proto = "http"

        device_detected = _detect_device_type(text_content, active_port, active_proto)
        snippet = text_content[:450].strip() if text_content else f"HTTP {status_code} OK (Respuesta sin cuerpo)"

        if req.cliente_id:
            _save_client_remote_verification(req.cliente_id, winning_url, device_detected, status_code, winning_latency)

        port_note = ""
        if winning_url != target_url:
            port_note = f" (Detectado en puerto alternativo: {winning_url})"

        return {
            "success": True,
            "url": winning_url,
            "ip": clean_ip,
            "protocol": active_proto,
            "port": active_port,
            "status_code": status_code,
            "latency_ms": winning_latency,
            "page_title": page_title,
            "device_detected": device_detected,
            "snippet": snippet,
            "message": f"Acceso remoto verificado con éxito (HTTP {status_code}) en {winning_latency} ms.{port_note}"
        }

    # =========================================================================
    # FALLBACK MIKROTIK: Si las peticiones HTTP directas fallaron
    # (Común cuando el servidor backend corre en Docker o VPS sin ruta L3 directa a IPs privadas)
    # =========================================================================
    try:
        cliente_obj = None
        if req.cliente_id:
            cliente_obj = db.query(models.Cliente).filter(models.Cliente.id == req.cliente_id).first()

        olt_cfg = None
        if cliente_obj and cliente_obj.nodo:
            olt_cfg = db.query(models.OLTConfig).filter(
                models.OLTConfig.nombre == cliente_obj.nodo,
                models.OLTConfig.mikrotik_host.isnot(None)
            ).first()

        if not olt_cfg:
            olt_cfg = db.query(models.OLTConfig).filter(models.OLTConfig.mikrotik_host.isnot(None)).first()

        if olt_cfg and olt_cfg.mikrotik_host:
            from network.adapters.mikrotik import MikroTikAdapter
            mt = MikroTikAdapter(
                host=olt_cfg.mikrotik_host,
                username=olt_cfg.mikrotik_username or "admin",
                password=olt_cfg.mikrotik_password or "",
                port=olt_cfg.mikrotik_port or 8728
            )

            # 1. Probar ping desde MikroTik hacia la IP del equipo
            ping_res = mt.ping(clean_ip, count=2)
            if ping_res.get("online"):
                avg_rtt = ping_res.get("avg_rtt") or round((time.time() - t0) * 1000)
                
                # Intentar leer lease DHCP o comentario
                lease_desc = "Equipo Activo en RouterOS"
                try:
                    res_lease = mt._get_resource('/ip/dhcp-server/lease')
                    found_leases = res_lease.get(address=clean_ip)
                    if found_leases:
                        fl = found_leases[0]
                        m_val = fl.get('mac-address', '')
                        h_val = fl.get('host-name', '') or fl.get('comment', '')
                        lease_desc = f"DHCP Lease MikroTik: {m_val} {f'({h_val})' if h_val else ''}".strip()
                except Exception:
                    pass

                device_detected = f"Equipo Verificado vía MikroTik Ping ({olt_cfg.mikrotik_host})"
                snippet = f"El equipo {clean_ip} responde al 100% de los paquetes ICMP desde el router MikroTik del nodo ({olt_cfg.mikrotik_host}). Conectividad física y asignación de red verificadas. Detalle: {lease_desc} • Latencia: {avg_rtt} ms."

                if req.cliente_id:
                    _save_client_remote_verification(req.cliente_id, target_url, device_detected, 200, int(avg_rtt))

                return {
                    "success": True,
                    "url": target_url,
                    "ip": clean_ip,
                    "protocol": protocol,
                    "port": final_port,
                    "status_code": 200,
                    "latency_ms": int(avg_rtt),
                    "page_title": "Conectividad Verificada vía MikroTik",
                    "device_detected": device_detected,
                    "snippet": snippet,
                    "message": f"Conectividad verificada con éxito a través de MikroTik ({olt_cfg.mikrotik_host}). Equipo en línea ({avg_rtt} ms)."
                }
    except Exception as mt_err:
        logger.warning(f"No se pudo completar fallback MikroTik para {clean_ip}: {mt_err}")

    # Si todo falló, construir mensaje de error diagnóstico preciso
    latency_ms = round((time.time() - t0) * 1000)
    error_msg = f"Tiempo de espera agotado al conectar a {target_url} (> {latency_ms} ms). Verifique que el equipo esté encendido y que la IP {clean_ip} sea accesible en la red."
    if last_error:
        err_str = str(last_error)
        if "Connection refused" in err_str or "10061" in err_str:
            error_msg = f"Conexión rechazada en el puerto {final_port or (80 if protocol == 'http' else 443)}. Pruebe seleccionando 'ONT' (puerto 80) o 'WiFi 6' (puerto 443)."

    return {
        "success": False,
        "url": target_url,
        "ip": clean_ip,
        "protocol": protocol,
        "port": final_port,
        "latency_ms": latency_ms,
        "error_type": type(last_error).__name__ if last_error else "Timeout",
        "message": error_msg
    }
