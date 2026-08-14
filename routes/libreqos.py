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

