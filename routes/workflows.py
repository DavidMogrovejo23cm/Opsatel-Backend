"""
OPSATEL ISP - Workflows Router & API Endpoints
==============================================
Rutas API para disparar e inspeccionar Workflows y Recursos de Inventario:
- GET  /inventory/onts          (Estado del Pool de ONT IDs)
- GET  /inventory/service-ports (Estado del Pool de Service Ports)
- POST /workflows/execute       (Punto de entrada universal para Workflows)

Autor: Arquitecto de Software Senior / CTO
Versión: 3.5.0 (Fase 4)
"""

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any
from pydantic import BaseModel

from database import get_db, SessionLocal
import models
import inventory_models
from routes.auth import require_role
from workflow_engine import WorkflowEngine
from services.olt_interface import OLTInterface

router = APIRouter(prefix="", tags=["Workflows & Inventory"])

class WorkflowExecuteRequest(BaseModel):
    workflow_type: str # ej: "ACTIVAR_CLIENTE"
    payload: Dict[str, Any]

@router.get("/inventory/onts", dependencies=[Depends(require_role(["administrador", "tecnico"]))])
def get_inventory_onts(olt_id: int, gpon_port: str, db: Session = Depends(get_db)):
    """Retorna la lista de ONT IDs inventariados y su estado (LIBRE/RESERVADO/OCUPADO)"""
    res = db.query(inventory_models.InventoryOntId).filter(
        inventory_models.InventoryOntId.olt_id == olt_id,
        inventory_models.InventoryOntId.gpon_port == gpon_port
    ).all()
    return res

@router.get("/inventory/service-ports", dependencies=[Depends(require_role(["administrador", "tecnico"]))])
def get_inventory_service_ports(olt_id: int, db: Session = Depends(get_db)):
    """Retorna el mapa de Service Ports inventariados"""
    res = db.query(inventory_models.InventoryServicePort).filter(
        inventory_models.InventoryServicePort.olt_id == olt_id
    ).all()
    return res

@router.post("/workflows/execute", dependencies=[Depends(require_role(["administrador", "tecnico"]))])
def execute_workflow_endpoint(req: WorkflowExecuteRequest, db: Session = Depends(get_db)):
    """
    Ejecuta un Workflow completo de negocio (ej: ACTIVAR_CLIENTE).
    Coordina reserva de inventario, comandos OLT, auditoría y rollback automático.
    """
    try:
        olt_id = req.payload.get("olt_id", 1)
        olt_config = db.query(models.OLTConfig).filter(models.OLTConfig.id == olt_id).first()
        
        olt = None
        if olt_config:
            olt = OLTInterface(
                host=olt_config.host,
                port=olt_config.port,
                username=olt_config.username,
                password=olt_config.password
            )
            try:
                olt.connect()
            except Exception:
                pass # Continuará en modo simulación/reserva BD si no conecta

        engine = WorkflowEngine(db)
        result = engine.execute_workflow(req.workflow_type, req.payload, olt_interface=olt)
        
        if olt:
            olt.disconnect()
            
        return result
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error ejecutando Workflow: {e}")
