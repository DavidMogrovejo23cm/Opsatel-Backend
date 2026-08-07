import json
import logging
import uuid
from datetime import datetime
from typing import List, Optional

# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, HTTPException, Query
# pyrefly: ignore [missing-import]
from pydantic import BaseModel
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import Session
# pyrefly: ignore [missing-import]
from sqlalchemy import or_, desc

from database import get_db
import models
import observability as obs
from routes.auth import require_role, get_current_user
from services.command_sanitizer import CommandSanitizer, CommandSanitizationError

bulk_router = APIRouter(prefix="/olt-tasks/bulk", tags=["OLT Bulk Tasks"])
logger = logging.getLogger("opsatel.bulk")

# ============================================================================
# SCHEMAS
# ============================================================================

class BulkItem(BaseModel):
    cliente_id: Optional[int] = None
    mac: str
    gpon_port: str
    ont_id: Optional[str] = None
    provision_type: str  # "ont" o "bridge"

class BulkActivationRequest(BaseModel):
    items: List[BulkItem]
    provision_type: Optional[str] = "ont"

# ============================================================================
# ENDPOINTS
# ============================================================================

@bulk_router.post("/activate", dependencies=[Depends(require_role(["administrador", "tecnico"]))])
def bulk_activate(
    req: BulkActivationRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Crea múltiples tareas de activación OLT agrupadas por un bulk_id único.
    Si no se provee cliente_id, crea un cliente temporal ficticio de forma automática.
    """
    if not req.items:
        raise HTTPException(status_code=400, detail="La lista de clientes a activar está vacía.")
    
    bulk_id = f"bulk_{uuid.uuid4().hex[:12]}"
    created_tasks = []
    
    # Registrar auditoría de inicio
    obs.log_audit_event_async(
        accion="BULK_ACTIVATION_STARTED",
        modulo="bulk_activation",
        usuario=current_user.username,
        detalles=f"Inicio de activación masiva para {len(req.items)} terminales. Bulk ID: {bulk_id}"
    )
    
    # Buscar una OLT activa por defecto si es necesario
    default_olt = db.query(models.OLTConfig).filter(models.OLTConfig.active == True).first()
    
    for idx, item in enumerate(req.items):
        gpon_port = item.gpon_port or "0/0/1"
        puerto_num = "1"
        try:
            puerto_num = gpon_port.split('/')[-1]
        except Exception:
            pass

        cliente_id = item.cliente_id
        cliente = None
        
        if cliente_id:
            # Validar cliente existente
            cliente = db.query(models.Cliente).filter(models.Cliente.id == cliente_id).first()
        
        if not cliente:
            # Crear cliente temporal random
            random_suffix = uuid.uuid4().hex[:6].upper()
            temp_name = f"TEMP_{random_suffix}"
            
            # Obtener el MAX id actual para evitar colisiones
            max_id = db.query(models.Cliente.id).order_by(desc(models.Cliente.id)).first()
            next_id = (max_id[0] + 1) if max_id else 50000
            
            # Crear objeto cliente temporal
            cliente = models.Cliente(
                id=next_id,
                nombre=temp_name,
                estado="Pendiente",
                puerto=str(puerto_num),
                nodo=default_olt.nodo_asociado if default_olt else "BAÑOS",
                plan="GAMER PRO"
            )
            db.add(cliente)
            db.flush()
            cliente_id = cliente.id
            logger.info(f"[Bulk] Creado cliente temporal {temp_name} (ID: {cliente_id}) para puerto {gpon_port}")
            
        # Determinar OLT por nodo del cliente
        olt_config = db.query(models.OLTConfig).filter(
            or_(
                models.OLTConfig.nodo_asociado == cliente.nodo,
                models.OLTConfig.nodo_asociado == None
            ),
            models.OLTConfig.active == True
        ).first()
        
        if not olt_config:
            olt_config = default_olt
            
        if not olt_config:
            logger.warning(f"[Bulk] No hay OLT activa configurada. Saltando.")
            continue

        profile = str(100 + int(puerto_num) if puerto_num.isdigit() else 101)

        raw_payload = {
            "mac": item.mac.replace(":", "").replace("-", "").upper(),
            "gpon_port": gpon_port,
            "ont_id": item.ont_id or cliente.id_port or "1",
            "description": f"{cliente.id} {cliente.nombre}",
            "profile_id": profile,
            "srvprofile_id": profile,
            "provision_type": item.provision_type or req.provision_type or "ont"
        }

        try:
            validated_payload = CommandSanitizer.validate_payload("add_ont", raw_payload)
        except CommandSanitizationError as e:
            logger.warning(f"[Bulk] Payload inválido para cliente {cliente_id}: {e}. Saltando.")
            continue

        # Crear OLTTask
        task = models.OLTTask(
            cliente_id=cliente_id,
            olt_id=olt_config.id,
            action="add_ont",
            payload=json.dumps(validated_payload),
            status="pending",
            priority=5 - idx,
            created_by=current_user.username,
            created_at=datetime.now(),
            bulk_id=bulk_id
        )
        db.add(task)
        
        # Marcar cliente en cola
        cliente.olt_sync_status = "in_queue"
        created_tasks.append(task)
        
    db.commit()
    
    for t in created_tasks:
        db.refresh(t)
        
    obs.log_audit_event_async(
        accion="BULK_ACTIVATION_FINISHED",
        modulo="bulk_activation",
        usuario=current_user.username,
        detalles=f"Finalizado encolamiento de {len(created_tasks)} tareas con Bulk ID: {bulk_id}"
    )

    return {
        "bulk_id": bulk_id,
        "total_queued": len(created_tasks),
        "tasks": [{"id": t.id, "cliente_id": t.cliente_id} for t in created_tasks]
    }


@bulk_router.get("/{bulk_id}/status", dependencies=[Depends(require_role(["administrador", "tecnico"]))])
def get_bulk_status(
    bulk_id: str,
    db: Session = Depends(get_db)
):
    """
    Retorna el estado y avance de un lote de activación masiva.
    """
    tasks = db.query(models.OLTTask).filter(models.OLTTask.bulk_id == bulk_id).all()
    if not tasks:
        raise HTTPException(status_code=404, detail=f"Lote de activación masiva '{bulk_id}' no encontrado.")
        
    total = len(tasks)
    completed = sum(1 for t in tasks if t.status == 'completed')
    failed = sum(1 for t in tasks if t.status == 'failed')
    pending = sum(1 for t in tasks if t.status in ['pending', 'processing'])
    
    current_task = None
    processing_tasks = [t for t in tasks if t.status == 'processing']
    if processing_tasks:
        current_task = {
            "id": processing_tasks[0].id,
            "cliente_id": processing_tasks[0].cliente_id,
            "status": "processing"
        }
    
    return {
        "bulk_id": bulk_id,
        "total": total,
        "completed": completed,
        "failed": failed,
        "pending": pending,
        "current_task": current_task,
        "tasks": [
            {
                "id": t.id,
                "cliente_id": t.cliente_id,
                "status": t.status,
                "error_message": t.error_message,
                "response_json": t.response_json
            } for t in tasks
        ]
    }


@bulk_router.post("/{task_id}/confirm", dependencies=[Depends(require_role(["administrador", "tecnico"]))])
def confirm_task_activation(
    task_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Confirma que una activación individual fue exitosa tras verificación del técnico.
    """
    task = db.query(models.OLTTask).filter(models.OLTTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Tarea OLT no encontrada.")
        
    obs.log_audit_event_async(
        accion="ACTIVATION_CONFIRMED",
        modulo="bulk_activation",
        usuario=current_user.username,
        entidad_tipo="Cliente",
        entidad_id=str(task.cliente_id),
        detalles=f"El técnico confirmó la activación correcta de la ONT/MikroTik. Tarea OLT: {task_id}"
    )
    return {"status": "ok", "message": "Activación confirmada por el técnico."}


@bulk_router.post("/{task_id}/retry-activation", dependencies=[Depends(require_role(["administrador", "tecnico"]))])
def retry_activation(
    task_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Realiza un reintento controlado:
    1. Borra la ONT y configuración anterior (remove_ont).
    2. Espera a que se elimine (el frontend realiza polling, o encolamos la recreación).
       Para máxima robustez en backend sin bloquear hilos, creamos una tarea 'remove_ont'
       de prioridad ultra alta. Cuando el frontend detecte que se completó el remove_ont,
       automáticamente lanzará de nuevo el flujo de 'add_ont'.
    """
    task = db.query(models.OLTTask).filter(models.OLTTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Tarea OLT origen no encontrada.")
        
    cliente = db.query(models.Cliente).filter(models.Cliente.id == task.cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente asociado no encontrado.")

    # Registramos la intención de reintento
    obs.log_audit_event_async(
        accion="ACTIVATION_RETRY",
        modulo="bulk_activation",
        usuario=current_user.username,
        entidad_tipo="Cliente",
        entidad_id=str(cliente.id),
        detalles=f"Se solicitó reactivación del cliente. Creando tarea de eliminación previa. Tarea origen: {task_id}"
    )

    # Extraer puerto numérico
    puerto_raw = str(cliente.puerto or "0")
    import re as _re
    m = _re.search(r'\d+', puerto_raw)
    puerto_num = m.group() if m else "0"

    is_sayausi = str(cliente.nodo or "").upper() == "SAYAUSI"
    gpon_port = f"0/1/{puerto_num}" if is_sayausi else f"0/0/{puerto_num}"

    # Crear payload para eliminar
    remove_payload = {
        "gpon_port": gpon_port,
        "ont_id": str(cliente.id_port or "0").strip(),
        "service_port": str(cliente.service_port or "").strip(),
        "mac": str(cliente.mac or "000000000000").replace(":", "").replace("-", "") or "000000000000",
    }

    # Encolar remove_ont
    remove_task = models.OLTTask(
        cliente_id=cliente.id,
        olt_id=task.olt_id,
        action="remove_ont",
        payload=json.dumps(remove_payload),
        status="pending",
        priority=12,  # Ultra prioridad
        created_by=current_user.username,
        created_at=datetime.now()
    )
    
    # Limpiar estado técnico en base de datos para re-activación
    cliente.estado = "En Activación"
    cliente.service_port = None
    cliente.id_port = None
    cliente.mac = None
    cliente.ip = None
    cliente.potencia = None

    db.add(remove_task)
    db.commit()
    db.refresh(remove_task)

    return {
        "status": "ok",
        "message": "Reactivación iniciada. Encolada tarea de eliminación previa.",
        "remove_task_id": remove_task.id
    }


@bulk_router.post("/undo-last", dependencies=[Depends(require_role(["administrador", "tecnico"]))])
def undo_last_activation(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Deshace la última activación exitosa (add_ont completed).
    Elimina la config en OLT y MikroTik, libera la IP reservada.
    """
    # Buscar última tarea add_ont completada
    last_task = db.query(models.OLTTask).filter(
        models.OLTTask.action == "add_ont",
        models.OLTTask.status == "completed"
    ).order_by(models.OLTTask.completed_at.desc()).first()

    if not last_task:
        raise HTTPException(status_code=404, detail="No se encontró ninguna activación reciente completada.")

    cliente = db.query(models.Cliente).filter(models.Cliente.id == last_task.cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="El cliente de la última activación ya no existe.")

    obs.log_audit_event_async(
        accion="UNDO_LAST_ACTIVATION",
        modulo="bulk_activation",
        usuario=current_user.username,
        entidad_tipo="Cliente",
        entidad_id=str(cliente.id),
        detalles=f"Deshaciendo última activación exitosa. Tarea origen: {last_task.id}"
    )

    # Extraer puerto numérico
    puerto_raw = str(cliente.puerto or "0")
    import re as _re
    m = _re.search(r'\d+', puerto_raw)
    puerto_num = m.group() if m else "0"

    is_sayausi = str(cliente.nodo or "").upper() == "SAYAUSI"
    gpon_port = f"0/1/{puerto_num}" if is_sayausi else f"0/0/{puerto_num}"

    # Crear payload para eliminar
    remove_payload = {
        "gpon_port": gpon_port,
        "ont_id": str(cliente.id_port or "0").strip(),
        "service_port": str(cliente.service_port or "").strip(),
        "mac": str(cliente.mac or "000000000000").replace(":", "").replace("-", "") or "000000000000",
    }

    # Encolar tarea de eliminación (remove_ont)
    remove_task = models.OLTTask(
        cliente_id=cliente.id,
        olt_id=last_task.olt_id,
        action="remove_ont",
        payload=json.dumps(remove_payload),
        status="pending",
        priority=12,
        created_by=current_user.username,
        created_at=datetime.now()
    )
    db.add(remove_task)

    # Liberar IP en inventory_ip_pools
    import inventory_models
    pool_ip = db.query(inventory_models.InventoryIpPool).filter(
        inventory_models.InventoryIpPool.cliente_id == cliente.id
    ).first()
    if pool_ip:
        pool_ip.estado = "LIBRE"
        pool_ip.cliente_id = None
        pool_ip.updated_at = datetime.now()

    # Resetear cliente a "En Activación" y limpiar
    cliente.estado = "En Activación"
    cliente.service_port = None
    cliente.id_port = None
    cliente.mac = None
    cliente.ip = None
    cliente.potencia = None

    db.commit()
    db.refresh(remove_task)

    return {
        "status": "ok",
        "message": f"Última activación deshecha (Cliente: {cliente.nombre}). Eliminación encolada.",
        "remove_task_id": remove_task.id
    }


@bulk_router.post("/clientes/{cliente_id}/refresh-ip", dependencies=[Depends(require_role(["administrador", "tecnico"]))])
def refresh_client_ip(
    cliente_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Fuerza el refresco y asignación correcta de IP estática de un cliente desde su pool.
    Normaliza los nombres de nodo y actualiza el MikroTik de forma interactiva.
    """
    cliente = db.query(models.Cliente).filter(models.Cliente.id == cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")

    # Conectar al MikroTik (Usando OLT configurada para el nodo del cliente)
    olt_config = db.query(models.OLTConfig).filter(
        or_(
            models.OLTConfig.nodo_asociado == cliente.nodo,
            models.OLTConfig.nodo_asociado == None
        ),
        models.OLTConfig.active == True
    ).first()
    
    if not olt_config or not olt_config.mikrotik_host:
        raise HTTPException(status_code=500, detail="MikroTik no configurado para el nodo del cliente.")

    import re
    from network.adapters.mikrotik import MikroTikAdapter
    mt = MikroTikAdapter(
        host=olt_config.mikrotik_host,
        port=olt_config.mikrotik_port or 8728,
        username=olt_config.mikrotik_username or "admin",
        password=olt_config.mikrotik_password or ""
    )

    # 1. Buscar lease en MikroTik por el comentario del cliente
    # La OLT usa el formato: "{cliente_id} {nombre}" o similar
    # Buscamos coincidencias con el ID de cliente de 6 dígitos
    client_code = str(cliente.id).zfill(6)
    lease_found = None

    try:
        mt.connect()
        leases = mt.api.get_resource('/ip/dhcp-server/lease').get()
        
        # Primero intentar match exacto o parcial por el comentario
        for l in leases:
            comment = l.get('comment', '')
            if client_code in comment:
                lease_found = l
                break

        # Si no se encuentra por comentario, intentar por MAC si el cliente tiene registrada
        if not lease_found and cliente.mac:
            clean_mac = cliente.mac.replace(":", "").replace("-", "").upper()
            for l in leases:
                l_mac = l.get('mac-address', '').replace(":", "").replace("-", "").upper()
                if clean_mac == l_mac:
                    lease_found = l
                    break

        if not lease_found:
            raise HTTPException(status_code=404, detail=f"No se encontró un Lease DHCP en el MikroTik para el cliente {client_code}.")

        lease_id = lease_found.get('.id') or lease_found.get('id')
        lease_ip = lease_found.get('address')

        # 2. Lógica de asignación de IP robusta (Normalizando acentos, espacios y mayúsculas en memoria)
        def clean_node(name):
            if not name: return ""
            name = name.strip().lower()
            name = re.sub(r'[áàäâ]', 'a', name)
            name = re.sub(r'[éèëê]', 'e', name)
            name = re.sub(r'[íìïî]', 'i', name)
            name = re.sub(r'[óòöô]', 'o', name)
            name = re.sub(r'[úùüû]', 'u', name)
            return name

        clean_client_nodo = clean_node(cliente.nodo)

        # Buscar si el cliente ya tiene IP reservada históricamente
        import inventory_models
        existing_pool = db.query(inventory_models.InventoryIpPool).filter(
            inventory_models.InventoryIpPool.cliente_id == cliente.id
        ).first()

        target_ip = None
        if existing_pool:
            target_ip = existing_pool.ip_address
            if existing_pool.estado != "OCUPADO":
                existing_pool.estado = "OCUPADO"
                existing_pool.updated_at = datetime.now()
        else:
            # Buscar en la BD todas las libres de la tabla
            all_free = db.query(inventory_models.InventoryIpPool).filter(
                inventory_models.InventoryIpPool.estado == "LIBRE"
            ).all()

            # Ordenamos las IPs encontradas numéricamente
            import socket, struct
            def ip_key(ip_str):
                try:
                    return struct.unpack("!L", socket.inet_aton(ip_str))[0]
                except:
                    return 0

            sorted_free = sorted([p for p in all_free if clean_node(p.nodo) == clean_client_nodo], key=lambda x: ip_key(x.ip_address))
            if sorted_free:
                free_pool = sorted_free[0]
                target_ip = free_pool.ip_address
                free_pool.estado = "OCUPADO"
                free_pool.cliente_id = cliente.id
                free_pool.updated_at = datetime.now()
            else:
                target_ip = lease_ip

        # 3. Actualizar en MikroTik y base de datos
        cliente.ip = target_ip
        db.commit()

        if target_ip and target_ip != lease_ip:
            mt.update_lease_ip(lease_id, target_ip)
            # Volver a hacer estático por seguridad
            mt.make_lease_static(lease_id)
        
        # Actualizar comentario si no tiene el formato estándar
        standard_comment = f"{client_code} - {cliente.nombre}"
        if lease_found.get('comment') != standard_comment:
            mt.update_lease_comment(lease_id, standard_comment)

        mt.disconnect()

        return {
            "status": "ok",
            "ip": target_ip,
            "message": f"IP del cliente refrescada y asignada con éxito: {target_ip}"
        }

    except Exception as e:
        if 'mt' in locals():
            try: mt.disconnect()
            except: pass
        raise HTTPException(status_code=500, detail=f"Error al conectar/actualizar MikroTik: {str(e)}")

