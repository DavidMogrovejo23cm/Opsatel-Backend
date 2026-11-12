"""
@file network.py
@description Operaciones técnicas de red: cálculo GPON, OLT, migración y MikroTik.
"""
import re
import json
import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_

import models
from database import get_db
from routes.auth import get_current_user, require_role
from .utils import is_nodo_sayausi

logger = logging.getLogger("opsatel.routes.clientes.network")

router = APIRouter()

@router.get("/siguiente-valor-tecnico")
def obtener_siguiente_valor_tecnico(
    nodo: str = None, 
    puerto: str = None, 
    mac: str = "",
    nombre: str = "",
    has_breach: bool = False,
    cliente_id: str = "",
    db: Session = Depends(get_db)
):
    # 1. Obtención de prefijos y parámetros de red
    db_nodo = db.query(models.Nodo).filter(models.Nodo.nombre == nodo).first()
    
    # Lógica SAYAUSI vs Normal
    is_sayausi = is_nodo_sayausi(nodo)
    
    # El prefijo cambia para SAYAUSI a 172.18 si no se especifica otra cosa en el nodo
    if is_sayausi:
        prefijo = "172.18"
    else:
        prefijo = db_nodo.base_ip if db_nodo and db_nodo.base_ip else "172.16"
    
    puerto_num_str = puerto if puerto else "0"
    match = re.search(r'\d+', puerto_num_str)
    puerto_num_clean = match.group() if match else "0"
    p_num = int(puerto_num_clean)

    # Convert cliente_id to integer if possible
    c_id = None
    if cliente_id:
        try:
            c_id = int(cliente_id)
        except ValueError:
            pass

    # 2. Búsqueda Recursiva de Valores Libres
    id_port_val = 0
    while True:
        service_port_val = p_num * 128 + id_port_val
        
        id_port_query = db.query(models.Cliente).filter(
            models.Cliente.id_port == str(id_port_val),
            models.Cliente.nodo == nodo,
            models.Cliente.puerto == puerto
        )
        if c_id is not None:
            id_port_query = id_port_query.filter(models.Cliente.id != c_id)
        id_port_ocupado = id_port_query.first()

        sp_query = db.query(models.Cliente).filter(
            models.Cliente.service_port == str(service_port_val)
        )
        if c_id is not None:
            sp_query = sp_query.filter(models.Cliente.id != c_id)
        sp_ocupado = sp_query.first()

        if not id_port_ocupado and not sp_ocupado:
            break
        id_port_val += 1
        if id_port_val > 127: break

    id_port = str(id_port_val)
    service_port = str(service_port_val)

    # 3. IP Verification
    ip_sugerida = ""
    ip_offset = 2
    while True:
        ip_temp = f"{prefijo}.{p_num}.{id_port_val + ip_offset}"
        ip_query = db.query(models.Cliente).filter(models.Cliente.ip == ip_temp)
        if c_id is not None:
            ip_query = ip_query.filter(models.Cliente.id != c_id)
        ip_ocupada = ip_query.first()
        if not ip_ocupada:
            ip_sugerida = ip_temp
            break
        ip_offset += 1

    # 4. Parámetros Técnicos Diferenciados
    mac_clean = re.sub(r'[^a-zA-Z0-9]', '', str(mac or "")).upper()
    
    if is_sayausi:
        # SAYAUSI: Perfiles 400+, VLAN 400+, GPON 0/1/x
        profile_id = 400 + p_num
        vlan_val = 400 + p_num
        gpon_path = f"0/1/{p_num}"
        # Descripción incluye el CODIGO (cliente_id) formateado a 3 dígitos si es numérico
        try:
            cid_clean = str(cliente_id).zfill(3)
        except Exception:
            cid_clean = str(cliente_id)
        description = f"{cid_clean} {nombre}"
    else:
        # NORMAL (Banos/Otros): Perfiles 100+, VLAN 100/300, GPON 0/0/x
        profile_id = 100 + p_num
        vlan_val = 100 + p_num # User vlan
        vlan_transport = 300 + p_num
        gpon_path = f"0/0/{p_num}"
        description = nombre

    # 5. Generación de Comandos OLT
    cmd_ont = f'ont add {p_num} {id_port} sn-auth "{mac_clean}" omci ont-lineprofile-id {profile_id} ont-srvprofile-id {profile_id} desc "{description}"'
    
    if is_sayausi:
        # Service port Sayausi: vlan 40X, gpon 0/1/X
        cmd_servicio = f'service-port {service_port} vlan {vlan_val} gpon {gpon_path} ont {id_port} gemport {vlan_val} multi-service user-vlan {vlan_val} tag-transform translate'
        cmd_breach = f'ont port native-vlan {p_num} {id_port} eth 1 vlan {vlan_val} priority 0'
    else:
        # Service port Normal: vlan 30X, gpon 0/0/X
        cmd_servicio = f'service-port {service_port} vlan {vlan_transport} gpon {gpon_path} ont {id_port} gemport {profile_id} multi-service user-vlan {vlan_val} tag-transform translate'
        cmd_breach = f'ont port native-vlan {p_num} {id_port} eth 1 vlan {vlan_val} priority 0'
    
    return {
        "id_port": id_port,
        "service_port": service_port,
        "ip": ip_sugerida,
        "ont": cmd_ont,
        "servicio": cmd_servicio,
        "breach": cmd_breach if has_breach else ""
    }


@router.patch("/{id}/pasar-a-activacion", dependencies=[Depends(require_role(["administrador", "secretario", "tecnico"]))])
def pasar_a_activacion(id: int, db: Session = Depends(get_db)):
    cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    cliente.estado = "En Activación"
    db.commit()
    return {"message": "Cliente pasado a etapa de activación", "estado": cliente.estado}


@router.post("/{id}/borrar-de-olt", dependencies=[Depends(require_role(["administrador", "tecnico"]))])
def borrar_cliente_de_olt(id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """
    Borra al cliente de la OLT Huawei y lo regresa al estado 'En Activación'.
    """
    cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    if not cliente.id_port and not cliente.service_port:
        raise HTTPException(
            status_code=400,
            detail="El cliente no tiene datos OLT registrados (id_port / service_port). No se puede borrar de la OLT."
        )

    puerto_raw = str(cliente.puerto or "0")
    m = re.search(r'\d+', puerto_raw)
    puerto_num = m.group() if m else "0"

    is_sayausi = is_nodo_sayausi(cliente.nodo)
    if is_sayausi:
        gpon_port = f"0/1/{puerto_num}"
    else:
        gpon_port = f"0/0/{puerto_num}"

    ont_id = str(cliente.id_port or "0").strip()
    service_port = str(cliente.service_port or "").strip()

    olt_config = db.query(models.OLTConfig).filter(
        or_(
            models.OLTConfig.nodo_asociado == cliente.nodo,
            models.OLTConfig.nodo_asociado.ilike("%SAYAUS%") if is_sayausi else models.OLTConfig.nodo_asociado.ilike("%BAN%"),
            models.OLTConfig.nodo_asociado == None
        ),
        models.OLTConfig.active == True
    ).first()

    if not olt_config:
        raise HTTPException(
            status_code=500,
            detail=f"No hay OLT activa configurada para el nodo '{cliente.nodo}'. Configura una OLT primero."
        )

    payload = {
        "gpon_port": gpon_port,
        "ont_id": ont_id,
        "service_port": service_port,
        "mac": str(cliente.mac or "000000000000").replace(":", "").replace("-", "") or "000000000000",
    }

    task = models.OLTTask(
        cliente_id=id,
        olt_id=olt_config.id,
        action="remove_ont",
        payload=json.dumps(payload),
        status="pending",
        priority=10,
        created_by=current_user.username,
        created_at=datetime.now(),
    )
    db.add(task)
    db.flush()

    cliente.estado = "En Activación"
    cliente.service_port = None
    cliente.id_port = None
    cliente.ont = None
    cliente.servicio = None
    cliente.breach = None
    cliente.mac = None
    cliente.ip = None
    cliente.potencia = None
    cliente.instalation_date = None

    db.commit()
    db.refresh(task)

    return {
        "message": (
            f"✅ Tarea de borrado encolada (ID tarea: {task.id}). "
            f"El cliente '{cliente.nombre}' fue regresado a 'En Activación'. "
            f"La OLT ejecutará: undo service-port {service_port} → ont delete {puerto_num} {ont_id}."
        ),
        "task_id": task.id,
        "cliente_estado": cliente.estado,
        "gpon_port": gpon_port,
        "ont_id": ont_id,
        "service_port": service_port,
    }


@router.post("/{id}/migrar", dependencies=[Depends(require_role(["administrador", "tecnico"]))])
def migrar_cliente(id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """
    Acción de Migración de Cliente:
    1. Preserva el cliente, su ID y toda su información financiera intacta.
    2. Desactiva y borra ONT y Service Port de la OLT Huawei.
    3. Borra el DHCP lease y address-lists del router MikroTik.
    4. Encola la remoción en LibreQoS.
    5. Libera recursos de inventario.
    6. Resetea los campos técnicos físicos y pasa su estado a 'En Activación'.
    """
    cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    username = getattr(current_user, "username", "admin") if current_user else "admin"
    correlation_id = f"migracion_{id}_{int(datetime.now().timestamp())}"

    snapshot_tecnico = {
        "puerto": cliente.puerto,
        "id_port": cliente.id_port,
        "service_port": cliente.service_port,
        "ont": cliente.ont,
        "mac": cliente.mac,
        "ip": cliente.ip,
        "nodo": cliente.nodo,
        "potencia": cliente.potencia,
        "estado_anterior": cliente.estado,
        "fecha_migracion": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    olt_resumen = "OMITIDO"
    mikrotik_resumen = "OMITIDO"
    libreqos_resumen = "OMITIDO"

    # 1. DESAPROVISIONAR DE OLT (Huawei GPON)
    if cliente.id_port or cliente.service_port:
        try:
            puerto_raw = str(cliente.puerto or "0")
            m = re.search(r'\d+', puerto_raw)
            puerto_num = m.group() if m else "0"

            is_sayausi = is_nodo_sayausi(cliente.nodo)
            gpon_port = f"0/1/{puerto_num}" if is_sayausi else f"0/0/{puerto_num}"
            ont_id = str(cliente.id_port or "0").strip()
            service_port = str(cliente.service_port or "").strip()

            olt_config = db.query(models.OLTConfig).filter(
                or_(
                    models.OLTConfig.nodo_asociado == cliente.nodo,
                    models.OLTConfig.nodo_asociado.ilike("%SAYAUS%") if is_sayausi else models.OLTConfig.nodo_asociado.ilike("%BAN%"),
                    models.OLTConfig.nodo_asociado == None
                ),
                models.OLTConfig.active == True
            ).first()

            if olt_config:
                olt_payload = {
                    "gpon_port": gpon_port,
                    "ont_id": ont_id,
                    "service_port": service_port,
                    "mac": str(cliente.mac or "000000000000").replace(":", "").replace("-", "") or "000000000000"
                }

                task = models.OLTTask(
                    cliente_id=id,
                    olt_id=olt_config.id,
                    action="remove_ont",
                    payload=json.dumps(olt_payload),
                    status="pending",
                    priority=15,
                    created_by=username,
                    created_at=datetime.now(),
                )
                db.add(task)
                db.flush()

                try:
                    from services.olt_interface import OLTInterface
                    olt_direct = OLTInterface(
                        host=olt_config.host,
                        port=olt_config.port or 23,
                        username=olt_config.username,
                        password=olt_config.password,
                        timeout=5
                    )
                    olt_direct.connect()
                    res_direct = olt_direct.execute_removal_sequence(olt_payload)
                    olt_direct.disconnect()
                    if res_direct.get("success"):
                        task.status = "success"
                        task.result = json.dumps(res_direct)
                        task.completed_at = datetime.now()
                        olt_resumen = "ELIMINADO_DIRECTO"
                    else:
                        olt_resumen = f"ENCOLADO_TAREA (ID {task.id})"
                except Exception as direct_err:
                    logger.info(f"[Migración] OLT directa omitida ({direct_err}), procesando vía daemon OLT (Tarea {task.id})")
                    olt_resumen = f"ENCOLADO_TAREA (ID {task.id})"
            else:
                olt_resumen = "SIN_CONFIG_OLT"
        except Exception as olt_err:
            logger.error(f"[Migración] Error al preparar borrado OLT (cliente {id}): {olt_err}")
            olt_resumen = f"ERROR: {str(olt_err)}"

    # 2. BORRAR DEL MIKROTIK
    if cliente.mac or cliente.ip:
        try:
            from network.adapters.mikrotik import MikroTikAdapter

            olt_config_mt = db.query(models.OLTConfig).filter(
                or_(
                    models.OLTConfig.nodo_asociado == cliente.nodo,
                    models.OLTConfig.nodo_asociado == None
                ),
                models.OLTConfig.active == True
            ).first()

            if olt_config_mt and olt_config_mt.mikrotik_host:
                clean_mac = str(cliente.mac or "").replace(":", "").replace("-", "").upper()
                clean_ip = str(cliente.ip or "").strip()

                with MikroTikAdapter(
                    host=olt_config_mt.mikrotik_host,
                    port=olt_config_mt.mikrotik_port or 8728,
                    username=olt_config_mt.mikrotik_username or "admin",
                    password=olt_config_mt.mikrotik_password or "",
                    timeout=5
                ) as mt:
                    resource = mt._get_resource('/ip/dhcp-server/lease')
                    all_leases = resource.get()
                    removed_leases = 0

                    for lease in all_leases:
                        lease_mac = lease.get('mac-address', '').replace(":", "").replace("-", "").upper()
                        lease_ip = str(lease.get('address', '')).strip()
                        if (clean_mac and lease_mac == clean_mac) or (clean_ip and lease_ip == clean_ip):
                            l_id = lease.get('.id') or lease.get('id')
                            if l_id:
                                try:
                                    resource.remove(**{'.id': l_id})
                                    removed_leases += 1
                                except Exception:
                                    pass

                    if clean_ip:
                        try:
                            al_res = mt._get_resource('/ip/firewall/address-list')
                            for al in al_res.get(address=clean_ip):
                                al_id = al.get('.id') or al.get('id')
                                if al_id:
                                    try:
                                        al_res.remove(**{'.id': al_id})
                                    except Exception:
                                        pass
                        except Exception as al_err:
                            logger.warning(f"[Migración] Aviso al limpiar address-list MikroTik: {al_err}")

                    mikrotik_resumen = f"ELIMINADO ({removed_leases} lease)" if removed_leases > 0 else "OMITIDO (No se halló lease activo)"
            else:
                mikrotik_resumen = "SIN_CONFIG_MIKROTIK"
        except Exception as mt_err:
            logger.error(f"[Migración] Error al borrar de MikroTik (cliente {id}): {mt_err}")
            mikrotik_resumen = f"ERROR: {str(mt_err)}"

    # 3. BORRAR DE LIBREQOS
    try:
        from services.libreqos_manager import LibreQoSManager
        job = LibreQoSManager.enqueue_job(
            operation="REMOVE",
            cliente_id=id,
            db=db,
            correlation_id=correlation_id,
            created_by=f"MIGRACION_{username}"
        )
        libreqos_resumen = f"ENCOLADO_REMOVE (Job ID {job.id})" if job else "OMITIDO_O_YA_ENCOLADO"
    except Exception as lq_err:
        logger.error(f"[Migración] Error encolando LibreQoS (cliente {id}): {lq_err}")
        libreqos_resumen = f"ERROR: {str(lq_err)}"

    # 4. LIBERAR RECURSOS DE INVENTARIO
    try:
        import inventory_models
        db.query(inventory_models.InventoryIpPool).filter(
            inventory_models.InventoryIpPool.cliente_id == id
        ).update({
            inventory_models.InventoryIpPool.estado: "LIBRE",
            inventory_models.InventoryIpPool.cliente_id: None,
            inventory_models.InventoryIpPool.updated_at: datetime.now()
        })
        db.query(inventory_models.InventoryServicePort).filter(
            inventory_models.InventoryServicePort.cliente_id == id
        ).update({
            inventory_models.InventoryServicePort.estado: "LIBRE",
            inventory_models.InventoryServicePort.cliente_id: None,
            inventory_models.InventoryServicePort.updated_at: datetime.now()
        })
        db.query(inventory_models.InventoryOntId).filter(
            inventory_models.InventoryOntId.cliente_id == id
        ).update({
            inventory_models.InventoryOntId.estado: "LIBRE",
            inventory_models.InventoryOntId.cliente_id: None,
            inventory_models.InventoryOntId.updated_at: datetime.now()
        })
    except Exception as inv_err:
        logger.error(f"[Migración] Error al liberar recursos de inventario (cliente {id}): {inv_err}")

    # 5. ACTUALIZAR CLIENTE A 'En Activación'
    cliente.estado = "En Activación"
    cliente.service_port = None
    cliente.id_port = None
    cliente.ont = None
    cliente.servicio = None
    cliente.breach = None
    cliente.mac = None
    cliente.ip = None
    cliente.potencia = None
    cliente.instalation_date = None

    db.commit()
    db.refresh(cliente)

    # 6. REGISTRAR AUDITORÍA
    try:
        import observability as obs
        obs.log_audit_event_async(
            accion="MIGRAR_CLIENTE",
            modulo="clientes",
            usuario=username,
            entidad_tipo="Cliente",
            entidad_id=str(cliente.id),
            detalles=(
                f"Cliente migrado a 'En Activación'. "
                f"OLT: {olt_resumen} | MikroTik: {mikrotik_resumen} | LibreQoS: {libreqos_resumen}. "
                f"Datos previos: {json.dumps(snapshot_tecnico, ensure_ascii=False)}"
            ),
            correlation_id=correlation_id
        )
    except Exception as aud_err:
        logger.warning(f"[Migración] Aviso al registrar auditoría: {aud_err}")

    return {
        "success": True,
        "message": (
            f"✅ Cliente '{cliente.nombre}' migrado con éxito. "
            f"Fue desprovisionado de la red (OLT: {olt_resumen}, MikroTik: {mikrotik_resumen}, LibreQoS: {libreqos_resumen}). "
            f"Su estado pasó a 'En Activación' manteniendo sus finanzas y datos personales intactos."
        ),
        "cliente_id": cliente.id,
        "nombre": cliente.nombre,
        "nuevo_estado": cliente.estado,
        "olt": olt_resumen,
        "mikrotik": mikrotik_resumen,
        "libreqos": libreqos_resumen
    }


@router.post("/{id}/suspender-mikrotik", dependencies=[Depends(require_role(["administrador", "tecnico", "secretario"]))])
def suspender_cliente_mikrotik(id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """
    Agrega al cliente a la lista de suspendidos en MikroTik:
    - Banos: list=CLIENTES_SUSPENDIDOS_POR_PAGO
    - Sayausí: list=CLIENTES_SUSPENDIDOS_POR_PAGOS
    """
    from network.adapters.mikrotik import suspender_cliente_mikrotik_backend

    cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    if not cliente.ip:
        raise HTTPException(status_code=400, detail=f"El cliente '{cliente.nombre}' no tiene una IP asignada para suspender en MikroTik.")

    res = suspender_cliente_mikrotik_backend(cliente, db)
    if not res.get("success"):
        raise HTTPException(status_code=500, detail=f"Error MikroTik al suspender servicio: {res.get('error')}")

    cliente.estado = "Suspendido"
    db.commit()

    try:
        import observability as obs
        obs.log_audit_event_async(
            accion="SUSPENDER_CLIENTE_MIKROTIK",
            modulo="clientes",
            usuario=current_user.username,
            entidad_tipo="Cliente",
            entidad_id=str(cliente.id),
            detalles=f"Cliente {cliente.nombre} ({cliente.ip}) agregado a list '{res.get('list_name')}' en MikroTik {res.get('host')}"
        )
    except Exception:
        pass

    return {
        "success": True,
        "message": f"Servicio suspendido exitosamente para '{cliente.nombre}' (IP: {cliente.ip}) en MikroTik '{res.get('list_name')}'.",
        "estado": cliente.estado,
        "list_name": res.get("list_name"),
        "ip": cliente.ip
    }


@router.post("/{id}/reactivar-mikrotik", dependencies=[Depends(require_role(["administrador", "tecnico", "secretario"]))])
def reactivar_cliente_mikrotik(id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """
    Remueve al cliente de la lista de suspendidos en MikroTik y actualiza su estado a 'Activo'.
    """
    from network.adapters.mikrotik import reactivar_cliente_mikrotik_backend

    cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    if not cliente.ip:
        raise HTTPException(status_code=400, detail=f"El cliente '{cliente.nombre}' no tiene una IP asignada.")

    res = reactivar_cliente_mikrotik_backend(cliente, db)
    cliente.estado = "Activo"
    db.commit()

    try:
        import observability as obs
        obs.log_audit_event_async(
            accion="REACTIVAR_CLIENTE_MIKROTIK",
            modulo="clientes",
            usuario=current_user.username,
            entidad_tipo="Cliente",
            entidad_id=str(cliente.id),
            detalles=f"Cliente {cliente.nombre} ({cliente.ip}) reactivado y removido de listas de suspensión en MikroTik"
        )
    except Exception:
        pass

    return {
        "success": True,
        "message": f"Servicio reactivado exitosamente para '{cliente.nombre}' (IP: {cliente.ip}) en MikroTik.",
        "estado": cliente.estado,
        "ip": cliente.ip
    }
