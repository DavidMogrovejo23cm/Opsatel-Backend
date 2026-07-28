"""
OPSATEL ISP - Sync Router & API Endpoints
=========================================
Rutas API para analizar e iniciar procesos de reconciliación de red:
- GET  /sync/discrepancies       (Genera el reporte de discrepancias OLT ↔ BD)
- POST /sync/reconcile           (Vincular cliente en BD con ONT/SP en la OLT)

Autor: Arquitecto de Software Senior / CTO
Versión: 3.3.0 (Fase 2)
"""

# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, HTTPException, Body
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import Session
from typing import Optional
# pyrefly: ignore [missing-import]
from pydantic import BaseModel

from database import get_db
from routes.auth import require_role
from sync_engine import NetworkSyncEngine

router = APIRouter(prefix="/sync", tags=["Network Synchronization"])

class ReconcileRequest(BaseModel):
    cliente_id: int
    discovered_ont_id: int

@router.get("/discrepancies", dependencies=[Depends(require_role(["administrador", "tecnico"]))])
def get_discrepancies_report(olt_id: Optional[int] = None, db: Session = Depends(get_db)):
    """
    Analiza e identifica todas las discrepancias entre la realidad física de la OLT
    y la información registrada en la Base de Datos de Opsatel.
    """
    engine = NetworkSyncEngine(db)
    report = engine.analyze_discrepancies(olt_id=olt_id)
    return report

@router.post("/reconcile", dependencies=[Depends(require_role(["administrador", "tecnico"]))])
def reconcile_client_with_olt(payload: ReconcileRequest, db: Session = Depends(get_db)):
    """
    Ejecuta una acción de auto-reconciliación: Vincula una ONT descubierta en la OLT
    con un cliente de Opsatel y actualiza la BD para reflejar la realidad del equipo.
    """
    try:
        engine = NetworkSyncEngine(db)
        res = engine.reconcile_client(payload.cliente_id, payload.discovered_ont_id)
        return res
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en reconciliación: {e}")
