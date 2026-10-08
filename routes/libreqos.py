# pyrefly: ignore [missing-import]
import models
# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
# pyrefly: ignore [missing-import]
from pydantic import BaseModel, Field
from datetime import datetime

from database import get_db
from routes.auth import require_role
from libreqos_models import LibreQoSServer, ClientQoSState, LibreQoSJob
from services.libreqos_manager import LibreQoSManager
# pyrefly: ignore [missing-import]
from sync.libreqos_sync import LibreQoSReconciler
# pyrefly: ignore [missing-import]
from network.adapters.libreqos import LibreQoSAdapter

router = APIRouter(prefix="/libreqos", tags=["LibreQoS Admin"])

# ============================================================================
# SCHEMAS (Pydantic)
# ============================================================================

class LibreQoSServerBase(BaseModel):
    name: str = Field(..., example="LibreQoS-Norte")
    host: str = Field(..., example="172.20.10.10")
    ssh_port: int = Field(22, example=22)
    username: str = Field(..., example="root")
    auth_method: str = Field("password", example="password")
    password: Optional[str] = None
    private_key_path: Optional[str] = None
    passphrase: Optional[str] = None
    enabled: bool = True
    ssh_timeout: int = 30
    ssh_retries: int = 3
    max_concurrent_jobs: int = 5
    libreqos_path: str = "/opt/libreqos"
    libreqos_apply_cmd: str = "cd /opt/libreqos && sudo python3 src/rust_integration/generate_and_apply.sh"
    libreqos_list_cmd: str = "sudo python3 /opt/libreqos/src/rust_integration/ispConfig.py --list-shaped-json"
    suspension_download_mbps: int = 1
    suspension_upload_mbps: int = 1

class LibreQoSServerCreate(LibreQoSServerBase):
    pass

class LibreQoSServerResponse(LibreQoSServerBase):
    id: int
    status: str
    last_check: Optional[datetime] = None
    last_error: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True

class CustomIpRequest(BaseModel):
    ip: str = Field(..., example="172.16.5.99")
    name: Optional[str] = Field("Dispositivo", example="Antena_AP")
    download_mbps: Optional[int] = Field(100, example=100)
    upload_mbps: Optional[int] = Field(50, example=50)
    circuit_id: Optional[int] = None

class LibreQoSJobResponse(BaseModel):
    id: int
    cliente_id: int
    libreqos_server_id: Optional[int]
    operation: str
    status: str
    retry_count: int
    max_retries: int
    error: Optional[str]
    created_at: datetime
    completed_at: Optional[datetime]

    class Config:
        from_attributes = True

# ============================================================================
# ENDPOINTS
# ============================================================================

@router.get("/servers", response_model=List[LibreQoSServerResponse], dependencies=[Depends(require_role(["administrador", "tecnico"]))])
def list_servers(db: Session = Depends(get_db)):
    """Lista todos los servidores LibreQoS registrados."""
    return db.query(LibreQoSServer).all()

@router.post("/servers", response_model=LibreQoSServerResponse, dependencies=[Depends(require_role(["administrador"]))])
def create_server(req: LibreQoSServerCreate, db: Session = Depends(get_db)):
    """Registra un nuevo servidor LibreQoS."""
    existing = db.query(LibreQoSServer).filter(LibreQoSServer.name == req.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Ya existe un servidor con este nombre.")
        
    server = LibreQoSServer(**req.dict())
    db.add(server)
    db.commit()
    db.refresh(server)
    return server

@router.put("/servers/{server_id}", response_model=LibreQoSServerResponse, dependencies=[Depends(require_role(["administrador"]))])
def update_server(server_id: int, req: LibreQoSServerCreate, db: Session = Depends(get_db)):
    """Modifica la configuración de un servidor LibreQoS."""
    server = db.query(LibreQoSServer).filter(LibreQoSServer.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Servidor no encontrado.")
        
    for k, v in req.dict().items():
        setattr(server, k, v)
        
    db.commit()
    db.refresh(server)
    return server

@router.delete("/servers/{server_id}", dependencies=[Depends(require_role(["administrador"]))])
def delete_server(server_id: int, db: Session = Depends(get_db)):
    """Elimina un servidor de la base de datos."""
    server = db.query(LibreQoSServer).filter(LibreQoSServer.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Servidor no encontrado.")
        
    db.delete(server)
    db.commit()
    return {"success": True, "detail": "Servidor eliminado correctamente."}

@router.post("/servers/{server_id}/test", dependencies=[Depends(require_role(["administrador", "tecnico"]))])
def test_ssh_connection(server_id: int, db: Session = Depends(get_db)):
    """Realiza una prueba de conexión SSH al servidor remoto."""
    server = db.query(LibreQoSServer).filter(LibreQoSServer.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Servidor no encontrado.")
        
    try:
        with LibreQoSAdapter(server) as adapter:
            ver = adapter.get_version()
            server.status = "ONLINE"
            server.last_check = datetime.utcnow()
            server.last_error = None
            db.commit()
            return {"success": True, "message": f"Conexión exitosa. Versión de LibreQoS: {ver}"}
    except Exception as e:
        server.status = "OFFLINE"
        server.last_check = datetime.utcnow()
        server.last_error = str(e)
        db.commit()
        return {"success": False, "message": f"Fallo de conexión SSH: {e}"}

@router.post("/servers/{server_id}/sync", dependencies=[Depends(require_role(["administrador", "tecnico"]))])
def run_manual_sync(server_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Ejecuta una reconciliación manual en segundo plano para este servidor."""
    server = db.query(LibreQoSServer).filter(LibreQoSServer.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Servidor no encontrado.")
        
    def run_sync():
        db_sync = get_db().__next__()
        try:
            LibreQoSReconciler.reconcile_server(server_id, db_sync)
        finally:
            db_sync.close()
            
    background_tasks.add_task(run_sync)
    return {"success": True, "detail": f"Reconciliación para '{server.name}' iniciada en segundo plano."}

@router.post("/servers/{server_id}/clean-duplicates", dependencies=[Depends(require_role(["administrador", "tecnico"]))])
def clean_server_duplicates(server_id: int, db: Session = Depends(get_db)):
    """
    Limpia filas duplicadas en ShapedDevices.csv:
    - Si la IP coincide con un cliente en BD: usa el nombre, ID y velocidades exactas de su plan.
    - Si la IP no coincide (IP libre o equipo no registrado): la conserva intacta sin duplicarla.
    """
    server = db.query(LibreQoSServer).filter(LibreQoSServer.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Servidor LibreQoS no encontrado.")

    # Mapear todos los clientes activos con IP desde la BD de Opsatel
    all_clients = db.query(models.Cliente).filter(
        models.Cliente.estado == "Activo",
        models.Cliente.ip != None
    ).all()

    db_clients_by_ip = {}
    for c in all_clients:
        ip = (c.ip or "").strip()
        if not ip:
            continue
        down, up = LibreQoSManager.calculate_speeds(c, db)
        safe_name = (c.nombre or f"Cliente_{c.id}").replace(",", " ").replace('"', '').replace("'", "").strip()
        db_clients_by_ip[ip] = {
            "client_id": c.id,
            "name": safe_name,
            "download": down,
            "upload": up
        }

    try:
        with LibreQoSAdapter(server) as adapter:
            res = adapter.clean_duplicates_csv(db_clients_by_ip=db_clients_by_ip)
            server.status = "ONLINE"
            server.last_check = datetime.utcnow()
            server.last_error = None
            db.commit()
            return {
                "success": True,
                "server_name": server.name,
                "total_previous": res["total_previous"],
                "total_clean": res["total_clean"],
                "duplicates_removed": res["duplicates_removed"],
                "enriched_from_db": res.get("enriched_from_db", 0),
                "unmatched_preserved": res.get("unmatched_preserved", 0),
                "backup_file": res["backup_file"],
                "message": f"✓ Limpieza exitosa en {server.name}: {res['duplicates_removed']} duplicados eliminados. {res.get('enriched_from_db', 0)} clientes sincronizados con su plan de BD y {res.get('unmatched_preserved', 0)} IPs libres/externas conservadas intactas."
            }
    except Exception as e:
        server.last_error = str(e)
        db.commit()
        raise HTTPException(status_code=500, detail=f"Error al limpiar duplicados en {server.name}: {str(e)}")

@router.post("/servers/{server_id}/regenerate", dependencies=[Depends(require_role(["administrador", "tecnico"]))])
def regenerate_server_shaped_devices(server_id: int, db: Session = Depends(get_db)):
    """Regenera ShapedDevices.csv completo desde la base de datos de Opsatel con los planes actuales."""
    server = db.query(LibreQoSServer).filter(LibreQoSServer.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Servidor LibreQoS no encontrado.")

    # 1. Obtener clientes que pertenecen a este servidor según OLTConfig
    clientes = db.query(models.Cliente).join(
        models.OLTConfig, models.OLTConfig.nodo_asociado == models.Cliente.nodo
    ).filter(
        models.OLTConfig.libreqos_server_id == server.id,
        models.OLTConfig.active == True,
        models.Cliente.estado == "Activo",
        models.Cliente.ip != None
    ).all()

    # Si no se encontraron por OLT, o si es un nodo directo, buscar clientes cuyos nodos coincidan
    if not clientes:
        # Intento secundario: clientes activos con IP
        clientes = db.query(models.Cliente).filter(
            models.Cliente.estado == "Activo",
            models.Cliente.ip != None
        ).all()

    seen_ips = set()
    csv_lines = [
        "Circuit ID,Circuit Name,Device ID,Device Name,Parent Node,MAC,IPv4,IPv6,Download Min,Upload Min,Download Max,Upload Max,Comment"
    ]

    count_added = 0
    for c in clientes:
        ip = (c.ip or "").strip()
        if not ip or ip in seen_ips:
            continue
        seen_ips.add(ip)

        down, up = LibreQoSManager.calculate_speeds(c, db)
        safe_name = (c.nombre or f"Cliente_{c.id}").replace(",", " ").replace('"', '').replace("'", "").strip()
        line = f"{c.id},{safe_name},{c.id},{c.id},,,{ip},,2,2,{down},{up},"
        csv_lines.append(line)
        count_added += 1

        # Actualizar estado QoS en BD
        state = LibreQoSManager.get_or_create_qos_state(c.id, db)
        state.libreqos_server_id = server.id
        state.ip = ip
        state.download_mbps = down
        state.upload_mbps = up
        state.status = "APPLIED"
        state.last_applied_at = datetime.utcnow()
        state.last_verified_at = datetime.utcnow()

    db.commit()

    full_csv = "\n".join(csv_lines) + "\n"

    try:
        with LibreQoSAdapter(server) as adapter:
            res = adapter.write_full_csv(full_csv)
            server.status = "ONLINE"
            server.last_check = datetime.utcnow()
            server.last_error = None
            db.commit()
            return {
                "success": True,
                "server_name": server.name,
                "total_clients": count_added,
                "backup_file": res["backup_file"],
                "message": f"✓ Regeneración completa en {server.name}: {count_added} clientes aprovisionados con sus planes actuales."
            }
    except Exception as e:
        server.last_error = str(e)
        db.commit()
        raise HTTPException(status_code=500, detail=f"Error al regenerar ShapedDevices.csv en {server.name}: {str(e)}")

@router.post("/servers/{server_id}/add-custom-ip", dependencies=[Depends(require_role(["administrador", "tecnico"]))])
def add_custom_ip(server_id: int, req: CustomIpRequest, db: Session = Depends(get_db)):
    """
    Añade una IP suelta / manual o busca si pertenece a un cliente en la BD:
    - Si la IP coincide con un cliente en BD: usa el ID real, nombre y plan de Opsatel.
    - Si no coincide: la agrega con los datos manuales provistos.
    """
    server = db.query(LibreQoSServer).filter(LibreQoSServer.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Servidor LibreQoS no encontrado.")

    clean_ip = req.ip.strip()
    if not clean_ip:
        raise HTTPException(status_code=400, detail="La dirección IP es requerida.")

    # Buscar coincidencia en la Base de Datos
    matched_client = db.query(models.Cliente).filter(models.Cliente.ip == clean_ip).first()

    if matched_client:
        down, up = LibreQoSManager.calculate_speeds(matched_client, db)
        c_id = matched_client.id
        c_name = matched_client.nombre or f"Cliente_{matched_client.id}"
        is_from_db = True
    else:
        # Generar un Circuit ID único si no se proveyó
        c_id = req.circuit_id or int(datetime.utcnow().timestamp()) % 1000000 + 900000
        c_name = req.name or f"IP_{clean_ip.replace('.', '_')}"
        down = req.download_mbps or 100
        up = req.upload_mbps or 50
        is_from_db = False

    try:
        with LibreQoSAdapter(server) as adapter:
            success = adapter.provision_client(c_id, clean_ip, down, up, c_name)
            server.status = "ONLINE"
            server.last_check = datetime.utcnow()
            server.last_error = None
            db.commit()
            return {
                "success": success,
                "server_name": server.name,
                "ip": clean_ip,
                "name": c_name,
                "circuit_id": c_id,
                "download_mbps": down,
                "upload_mbps": up,
                "matched_db_client": is_from_db,
                "message": f"✓ IP {clean_ip} ({c_name}) {'[Cliente de BD]' if is_from_db else '[Manual]'} agregada con {down}M/{up}M y LibreQoS recargado."
            }
    except Exception as e:
        server.last_error = str(e)
        db.commit()
        raise HTTPException(status_code=500, detail=f"Error al agregar IP suelta en {server.name}: {str(e)}")

@router.post("/servers/{server_id}/sync-missing-clients", dependencies=[Depends(require_role(["administrador", "tecnico"]))])
def sync_missing_clients(server_id: int, db: Session = Depends(get_db)):
    """
    Busca clientes activos en la base de datos de Opsatel que aún no estén en ShapedDevices.csv
    y los agrega automáticamente con sus planes, sin borrar las IPs ya existentes.
    """
    server = db.query(LibreQoSServer).filter(LibreQoSServer.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Servidor LibreQoS no encontrado.")

    # 1. Obtener clientes teóricos de este servidor
    clientes = db.query(models.Cliente).join(
        models.OLTConfig, models.OLTConfig.nodo_asociado == models.Cliente.nodo
    ).filter(
        models.OLTConfig.libreqos_server_id == server.id,
        models.OLTConfig.active == True,
        models.Cliente.estado == "Activo",
        models.Cliente.ip != None
    ).all()

    if not clientes:
        clientes = db.query(models.Cliente).filter(
            models.Cliente.estado == "Activo",
            models.Cliente.ip != None
        ).all()

    try:
        with LibreQoSAdapter(server) as adapter:
            # Leer clientes existentes en el CSV
            existing_clients = adapter.list_shaped_clients()
            existing_ips = {row.get("IPv4", "").strip() for row in existing_clients if row.get("IPv4")}
            existing_ids = {row.get("Circuit ID", "").strip() for row in existing_clients if row.get("Circuit ID")}

            new_lines = []
            added_count = 0
            for c in clientes:
                ip = (c.ip or "").strip()
                cid_str = str(c.id)
                if not ip or ip in existing_ips or cid_str in existing_ids:
                    continue

                down, up = LibreQoSManager.calculate_speeds(c, db)
                safe_name = (c.nombre or f"Cliente_{c.id}").replace(",", " ").replace('"', '').replace("'", "").strip()
                line = f"{c.id},{safe_name},{c.id},{c.id},,,{ip},,2,2,{down},{up},"
                new_lines.append(line)
                existing_ips.add(ip)
                existing_ids.add(cid_str)
                added_count += 1

            if added_count > 0:
                # Agregar al final del CSV
                append_text = "\n".join(new_lines) + "\n"
                import base64
                b64 = base64.b64encode(append_text.encode('utf-8')).decode('ascii')
                adapter._execute(f"echo '{b64}' | base64 -d >> {adapter.csv_path}")
                adapter.apply_config()

            server.status = "ONLINE"
            server.last_check = datetime.utcnow()
            server.last_error = None
            db.commit()

            return {
                "success": True,
                "server_name": server.name,
                "added_count": added_count,
                "message": f"✓ {added_count} clientes faltantes de la BD fueron añadidos a LibreQoS." if added_count > 0 else "✓ Todas las IPs de clientes ya están presentes en LibreQoS."
            }
    except Exception as e:
        server.last_error = str(e)
        db.commit()
        raise HTTPException(status_code=500, detail=f"Error al sincronizar clientes faltantes en {server.name}: {str(e)}")

@router.get("/jobs", response_model=List[LibreQoSJobResponse], dependencies=[Depends(require_role(["administrador", "tecnico"]))])
def get_jobs(status: Optional[str] = None, db: Session = Depends(get_db)):
    """Obtiene el historial/cola de trabajos."""
    query = db.query(LibreQoSJob)
    if status:
        query = query.filter(LibreQoSJob.status == status)
    return query.order_by(LibreQoSJob.created_at.desc()).limit(100).all()

@router.post("/jobs/{job_id}/retry", dependencies=[Depends(require_role(["administrador", "tecnico"]))])
def retry_job(job_id: int, db: Session = Depends(get_db)):
    """Fuerza el reintento de un trabajo fallido."""
    job = db.query(LibreQoSJob).filter(LibreQoSJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado.")
        
    job.status = "pending"
    job.retry_count = 0
    job.next_retry_at = None
    db.commit()
    return {"success": True, "detail": "Trabajo restablecido a PENDING."}

@router.get("/clients/{cliente_id}/qos", dependencies=[Depends(require_role(["administrador", "tecnico"]))])
def get_client_qos_status(cliente_id: int, db: Session = Depends(get_db)):
    """Obtiene el estado actual QoS del cliente."""
    state = db.query(ClientQoSState).filter(ClientQoSState.cliente_id == cliente_id).first()
    if not state:
        return {"status": "NOT_CONFIGURED", "detail": "El cliente no tiene QoS aprovisionado."}
    return state


@router.post("/clients/{cliente_id}/sync-now", dependencies=[Depends(require_role(["administrador", "tecnico"]))])
def force_sync_client_now(cliente_id: int, db: Session = Depends(get_db)):
    """Encola o fuerza una sincronización instantánea de este cliente en LibreQoS."""
    cliente = db.query(models.Cliente).filter(models.Cliente.id == cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")
    
    correlation_id = f"manual_sync_{cliente_id}_{int(datetime.now().timestamp())}"
    job = LibreQoSManager.enqueue_job("PROVISION", cliente_id, db, correlation_id, "MANUAL_UI")
    if not job:
         raise HTTPException(status_code=400, detail="No se pudo encolar. Verifica si tiene OLT / Nodo asociado y servidor de LibreQoS activo configurado.")
    
    return {"success": True, "detail": "Trabajo de aprovisionamiento encolado con éxito.", "job_id": job.id, "status": job.status}

