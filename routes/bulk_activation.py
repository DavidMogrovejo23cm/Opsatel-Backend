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

import unicodedata

def is_nodo_sayausi(nodo_val) -> bool:
    if not nodo_val:
        return False
    s = unicodedata.normalize('NFD', str(nodo_val)).encode('ascii', 'ignore').decode('utf-8').upper()
    return "SAYAUSI" in s

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
    Cambia automáticamente el estado en la Hoja de Ruta a 'Realizado'.
    """
    task = db.query(models.OLTTask).filter(models.OLTTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Tarea OLT no encontrada.")

    cid = task.cliente_id
    if not cid and task.payload and isinstance(task.payload, dict):
        cid = task.payload.get("cliente_id")

    updated_count = 0
    if cid:
        try:
            # 1. Actualizar por cliente_id
            updated_count = db.query(models.HojaRuta).filter(
                models.HojaRuta.cliente_id == cid,
                models.HojaRuta.estado != "Cancelado"
            ).update({"estado": "Realizado"}, synchronize_session=False)

            # 2. Actualizar también por coincidencia de nombre si fuera necesario
            cliente_obj = db.query(models.Cliente).filter(models.Cliente.id == cid).first()
            if cliente_obj and cliente_obj.nombre:
                name_count = db.query(models.HojaRuta).filter(
                    models.HojaRuta.nombre_cliente == cliente_obj.nombre,
                    models.HojaRuta.estado != "Cancelado"
                ).update({"estado": "Realizado"}, synchronize_session=False)
                updated_count += name_count

            db.commit()
            logger.info(f"[confirm_task_activation] Hoja de Ruta actualizada a 'Realizado' ({updated_count} registros) para cliente {cid}")
        except Exception as hr_err:
            logger.error(f"[confirm_task_activation] Error actualizando estado en Hoja de Ruta para cliente {cid}: {hr_err}")
            db.rollback()

    obs.log_audit_event_async(
        accion="ACTIVATION_CONFIRMED",
        modulo="bulk_activation",
        usuario=current_user.username,
        entidad_tipo="Cliente",
        entidad_id=str(cid or task.cliente_id),
        detalles=f"El técnico confirmó la activación correcta de la ONT/MikroTik. Tarea OLT: {task_id}. Hoja de Ruta actualizada a Realizado ({updated_count} registros)."
    )
    return {
        "status": "ok",
        "message": "Activación confirmada por el técnico. Hoja de ruta actualizada a Realizado.",
        "hoja_ruta_actualizada": updated_count
    }


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

    is_sayausi = is_nodo_sayausi(cliente.nodo)
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

    is_sayausi = is_nodo_sayausi(cliente.nodo)
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
    Aprende la MAC real del router conectado detrás del ONT/Bridge desde la OLT
    y actualiza MikroTik de forma determinista sin seleccionar leases de otros clientes.
    """
    cliente = db.query(models.Cliente).filter(models.Cliente.id == cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")

    # Conectar al MikroTik (Usando OLT configurada para el nodo del cliente)
    from network.adapters.mikrotik import is_nodo_sayausi
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
    
    if not olt_config or not olt_config.mikrotik_host:
        raise HTTPException(status_code=500, detail="MikroTik no configurado para el nodo del cliente.")

    import re
    import time
    from network.adapters.mikrotik import MikroTikAdapter
    from services.olt_interface import OLTInterface

    # Intentar obtener la MAC real del router conectado detrás del ONT/Bridge en la OLT
    real_client_mac = None
    gpon_port_str = str(cliente.puerto or "")
    if "/" not in gpon_port_str:
        match_p = re.search(r"\d+", gpon_port_str)
        if match_p:
            frame = "1" if is_nodo_sayausi(cliente.nodo) else "0"
            gpon_port_str = f"0/{frame}/{match_p.group()}"
    ont_id_str = str(cliente.id_port or "").strip()

    try:
        olt = OLTInterface(
            host=olt_config.host,
            port=olt_config.port or 23,
            username=olt_config.username or "admin",
            password=olt_config.password or ""
        )
        olt.connect()
        # Reintentar lectura de MAC en OLT (hasta 5 intentos con 1.5s entre reintentos)
        for mac_attempt in range(5):
            if mac_attempt > 0:
                time.sleep(1.5)
            if cliente.service_port:
                real_client_mac = olt.get_mac_from_service_port(str(cliente.service_port))
            if not real_client_mac and gpon_port_str and ont_id_str:
                real_client_mac = olt.get_mac_from_port_ont(gpon_port_str, ont_id_str)
            if real_client_mac:
                logger.info(f"[refresh-ip] MAC del router aprendida desde la OLT: {real_client_mac}")
                cliente.mac = real_client_mac
                db.commit()
                break
    except Exception as olt_err:
        logger.warning(f"No se pudo consultar la MAC en la OLT para cliente {cliente.id}: {olt_err}")
    finally:
        try:
            olt.disconnect()
        except Exception:
            pass

    mt_mac = real_client_mac or cliente.mac or ""
    client_code = str(cliente.id).zfill(6)
    clean_mac = mt_mac.replace(":", "").replace("-", "").upper() if mt_mac else ""
    lease_found = None

    # Determinar los servidores DHCP candidatos basados en el puerto GPON
    puerto_raw = str(cliente.puerto or "0")
    m = re.search(r'\d+', puerto_raw)
    port_idx = int(m.group()) if m else 0

    dhcp_servers_to_try = [
        f"dhcp{port_idx + 1}",
        f"dhcp{port_idx}",
        f"dhcp-{port_idx + 1}",
        f"dhcp-{port_idx}",
    ]
    if cliente.nodo:
        dhcp_servers_to_try.append(f"dhcp-{cliente.nodo.lower()}")

    try:
        mt = MikroTikAdapter(
            host=olt_config.mikrotik_host,
            port=olt_config.mikrotik_port or 8728,
            username=olt_config.mikrotik_username or "admin",
            password=olt_config.mikrotik_password or ""
        )
        mt.connect()

        # Obtener leases dinámicos
        dynamic_leases = []
        for srv in dhcp_servers_to_try:
            try:
                leases_found = mt.get_dynamic_leases(server=srv)
                if leases_found:
                    dynamic_leases.extend(leases_found)
            except Exception:
                pass

        if not dynamic_leases:
            try:
                dynamic_leases = mt.get_dynamic_leases()
            except Exception:
                dynamic_leases = []

        # 1. Buscar coincidencia exacta por MAC aprendida / registrada
        if clean_mac:
            for dl in dynamic_leases:
                dl_mac = dl.get('mac-address', '').replace(":", "").replace("-", "").upper()
                if dl_mac == clean_mac:
                    lease_found = dl
                    logger.info(f"[refresh-ip] Match dinámico exacto por MAC: {dl.get('address')} ({dl_mac})")
                    break

        # 2. Buscar por comentario si ya fue convertido a estático o por ID
        if not lease_found:
            for dl in dynamic_leases:
                comment = dl.get('comment', '')
                client_id_opt = dl.get('client-id', '')
                if client_code in comment or client_id_opt == str(cliente.id):
                    lease_found = dl
                    break

        # 3. Buscar en TODOS los leases (estáticos y dinámicos) por MAC o comentario
        if not lease_found:
            all_leases = mt.api.get_resource('/ip/dhcp-server/lease').get()
            for l in all_leases:
                comment = l.get('comment', '')
                l_mac = l.get('mac-address', '').replace(":", "").replace("-", "").upper()
                if (clean_mac and l_mac == clean_mac) or (client_code in comment):
                    lease_found = l
                    logger.info(f"[refresh-ip] Match en leases estáticos/activos: {l.get('address')} ({l_mac})")
                    break

        if not lease_found:
            mac_info = f"MAC aprendida en OLT: {mt_mac}" if mt_mac else "La OLT aún no registra tráfico MAC en el service-port"
            raise HTTPException(
                status_code=404,
                detail=f"No se encontró un Lease DHCP en MikroTik para el cliente {client_code} ({mac_info}). Verifique que el router esté encendido y conectado por cable Ethernet al puerto LAN de la ONT/Bridge."
            )

        lease_id = lease_found.get('.id') or lease_found.get('id')
        lease_ip = lease_found.get('address')
        lease_mac_real = lease_found.get('mac-address')

        # Persistir MAC si vino del lease
        if lease_mac_real and not real_client_mac:
            cliente.mac = lease_mac_real
            db.commit()

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

        # Siempre forzar a que sea estático por seguridad para fijar la IP
        try:
            mt.make_lease_static(lease_id)
        except Exception as mt_static_err:
            logger.info(f"Ignorando error al hacer static (probablemente ya lo era): {mt_static_err}")

        # Actualizar la IP si difiere
        if target_ip and target_ip != lease_ip:
            mt.update_lease_ip(lease_id, target_ip)
        
        # Actualizar comentario con formato estándar
        standard_comment = f"{client_code} - {cliente.nombre}"
        if lease_found.get('comment') != standard_comment:
            mt.update_lease_comment(lease_id, standard_comment)

        mt.disconnect()

        return {
            "status": "ok",
            "ip": target_ip,
            "mac": lease_mac_real or mt_mac,
            "message": f"IP del cliente refrescada y asignada con éxito: {target_ip}"
        }

    except HTTPException:
        if 'mt' in locals():
            try: mt.disconnect()
            except: pass
        raise
    except Exception as e:
        if 'mt' in locals():
            try: mt.disconnect()
            except: pass
        raise HTTPException(status_code=500, detail=f"Error al conectar/actualizar MikroTik: {str(e)}")

