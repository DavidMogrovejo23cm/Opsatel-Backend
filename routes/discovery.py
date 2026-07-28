"""
OPSATEL ISP - Discovery Router & API Endpoints
==============================================
Rutas API para inspeccionar los datos recopilados por Network Discovery:
- GET /discovery/onts           (Lista de ONTs descubiertas y estado de sync)
- GET /discovery/service-ports  (Lista de Service Ports en OLT)
- GET /discovery/boards         (Estado de placas/tarjetas)
- POST /discovery/run/{olt_id}  (Disparar auto-descubrimiento manual)

Autor: Arquitecto de Software Senior / CTO
Versión: 3.2.0 (Fase 1)
"""

# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import Session
from typing import List, Optional
import database
from database import get_db, SessionLocal
import models
import discovery_models
from routes.auth import require_role
from services.olt_interface import OLTInterface
from huawei_discovery import HuaweiDiscoveryEngine

router = APIRouter(prefix="/discovery", tags=["Network Discovery"])

@router.get("/onts", dependencies=[Depends(require_role(["administrador", "tecnico"]))])
def get_discovered_onts(
    olt_id: Optional[int] = None,
    sync_state: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Retorna la lista de ONTs descubiertas en la red y su estado de sincronización con BD"""
    query = db.query(discovery_models.DiscoveredONT)
    if olt_id:
        query = query.filter(discovery_models.DiscoveredONT.olt_id == olt_id)
    if sync_state:
        query = query.filter(discovery_models.DiscoveredONT.sync_state == sync_state)
    return query.order_by(discovery_models.DiscoveredONT.last_discovered_at.desc()).limit(500).all()

@router.get("/service-ports", dependencies=[Depends(require_role(["administrador", "tecnico"]))])
def get_discovered_service_ports(
    olt_id: Optional[int] = None,
    sync_state: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Retorna la lista de Service Ports descubiertos en la OLT"""
    query = db.query(discovery_models.DiscoveredServicePort)
    if olt_id:
        query = query.filter(discovery_models.DiscoveredServicePort.olt_id == olt_id)
    if sync_state:
        query = query.filter(discovery_models.DiscoveredServicePort.sync_state == sync_state)
    return query.order_by(discovery_models.DiscoveredServicePort.service_port.asc()).limit(500).all()

@router.get("/boards", dependencies=[Depends(require_role(["administrador", "tecnico"]))])
def get_discovered_boards(olt_id: Optional[int] = None, db: Session = Depends(get_db)):
    """Retorna el estado de las placas/tarjetas del chasis OLT"""
    query = db.query(discovery_models.DiscoveredBoard)
    if olt_id:
        query = query.filter(discovery_models.DiscoveredBoard.olt_id == olt_id)
    return query.all()

def _run_discovery_bg(olt_id: int):
    """Ejecuta el descubrimiento en background"""
    db = SessionLocal()
    try:
        olt_config = db.query(models.OLTConfig).filter(models.OLTConfig.id == olt_id).first()
        if not olt_config:
            return
        olt = OLTInterface(
            host=olt_config.host,
            port=olt_config.port,
            username=olt_config.username,
            password=olt_config.password
        )
        if olt.connect():
            engine = HuaweiDiscoveryEngine(olt, olt_id)
            engine.run_full_discovery(db)
            olt.disconnect()
    except Exception as e:
        print(f"Error en discovery background: {e}")
    finally:
        db.close()

@router.post("/run/{olt_id}", dependencies=[Depends(require_role(["administrador", "tecnico"]))])
def trigger_discovery(olt_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Dispara una inspección de Network Discovery en segundo plano para una OLT específica"""
    olt_config = db.query(models.OLTConfig).filter(models.OLTConfig.id == olt_id).first()
    if not olt_config:
        raise HTTPException(status_code=404, detail="OLT Config no encontrada")

    background_tasks.add_task(_run_discovery_bg, olt_id)
    return {
        "success": True,
        "message": f"Auto-descubrimiento iniciado en segundo plano para OLT {olt_config.nombre} ({olt_config.host})"
    }
