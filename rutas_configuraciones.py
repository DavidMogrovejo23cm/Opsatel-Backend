# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, HTTPException, status
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import Session
from typing import List, Optional
# pyrefly: ignore [missing-import]
from pydantic import BaseModel

from database import get_db
import models
import schemas
from config_manager import get_config, save_config

router = APIRouter(
    prefix="/configuraciones",
    tags=["configuraciones"],
    responses={404: {"description": "Not found"}},
)

# --- Nodos ---
@router.post("/nodos", response_model=schemas.NodoResponse)
def create_nodo(nodo: schemas.NodoBase, db: Session = Depends(get_db)):
    db_nodo = models.Nodo(nombre=nodo.nombre, base_ip=nodo.base_ip)
    db.add(db_nodo)
    try:
        db.commit()
        db.refresh(db_nodo)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail="Error o nodo duplicado")
    return db_nodo

@router.get("/nodos", response_model=List[schemas.NodoResponse])
def get_nodos(db: Session = Depends(get_db)):
    return db.query(models.Nodo).all()

@router.delete("/nodos/{nodo_id}")
def delete_nodo(nodo_id: int, db: Session = Depends(get_db)):
    nodo = db.query(models.Nodo).filter(models.Nodo.id == nodo_id).first()
    if not nodo:
        raise HTTPException(status_code=404, detail="Nodo no encontrado")
    
    # Cascade delete puertos
    db.query(models.Puerto).filter(models.Puerto.nodo_id == nodo_id).delete()
    
    db.delete(nodo)
    db.commit()
    return {"message": "Nodo eliminado exitosamente"}

@router.patch("/nodos/{nodo_id}", response_model=schemas.NodoResponse)
def update_nodo(nodo_id: int, nodo_data: schemas.NodoUpdate, db: Session = Depends(get_db)):
    db_nodo = db.query(models.Nodo).filter(models.Nodo.id == nodo_id).first()
    if not db_nodo:
        raise HTTPException(status_code=404, detail="Nodo no encontrado")
    
    for key, value in nodo_data.dict(exclude_unset=True).items():
        setattr(db_nodo, key, value)
    
    try:
        db.commit()
        db.refresh(db_nodo)
    except:
        db.rollback()
        raise HTTPException(status_code=400, detail="Error al actualizar nodo")
    return db_nodo

# --- Planes ---
@router.post("/planes", response_model=schemas.PlanInternetResponse)
def create_plan(plan: schemas.PlanInternetBase, db: Session = Depends(get_db)):
    db_plan = models.PlanInternet(
        nombre=plan.nombre,
        megas=plan.megas or 0,
        precio=plan.precio,
        pantallas=plan.pantallas if (hasattr(plan, 'pantallas') and plan.pantallas is not None) else 0
    )
    db.add(db_plan)
    try:
        db.commit()
        db.refresh(db_plan)
    except:
        db.rollback()
        raise HTTPException(status_code=400, detail="Error o plan duplicado")
    return db_plan

@router.get("/planes", response_model=List[schemas.PlanInternetResponse])
def get_planes(db: Session = Depends(get_db)):
    return db.query(models.PlanInternet).all()

@router.delete("/planes/{plan_id}")
def delete_plan(plan_id: int, db: Session = Depends(get_db)):
    plan = db.query(models.PlanInternet).filter(models.PlanInternet.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    db.delete(plan)
    db.commit()
    return {"message": "Plan eliminado"}

@router.patch("/planes/{plan_id}", response_model=schemas.PlanInternetResponse)
def update_plan(plan_id: int, plan_data: schemas.PlanInternetUpdate, db: Session = Depends(get_db)):
    db_plan = db.query(models.PlanInternet).filter(models.PlanInternet.id == plan_id).first()
    if not db_plan:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    
    for key, value in plan_data.dict(exclude_unset=True).items():
        setattr(db_plan, key, value)
        
    try:
        db.commit()
        db.refresh(db_plan)
    except:
        db.rollback()
        raise HTTPException(status_code=400, detail="Error al actualizar plan")
    return db_plan

# --- Bancos ---
@router.post("/bancos", response_model=schemas.BancoResponse)
def create_banco(banco: schemas.BancoBase, db: Session = Depends(get_db)):
    db_banco = models.Banco(nombre=banco.nombre)
    db.add(db_banco)
    try:
        db.commit()
        db.refresh(db_banco)
    except:
        db.rollback()
        raise HTTPException(status_code=400, detail="Error o banco duplicado")
    return db_banco

@router.get("/bancos", response_model=List[schemas.BancoResponse])
def get_bancos(db: Session = Depends(get_db)):
    return db.query(models.Banco).all()

@router.delete("/bancos/{banco_id}")
def delete_banco(banco_id: int, db: Session = Depends(get_db)):
    banco = db.query(models.Banco).filter(models.Banco.id == banco_id).first()
    if not banco:
        raise HTTPException(status_code=404, detail="Banco no encontrado")
    db.delete(banco)
    db.commit()
    return {"message": "Banco eliminado"}

@router.patch("/bancos/{banco_id}", response_model=schemas.BancoResponse)
def update_banco(banco_id: int, banco_data: schemas.BancoUpdate, db: Session = Depends(get_db)):
    db_banco = db.query(models.Banco).filter(models.Banco.id == banco_id).first()
    if not db_banco:
        raise HTTPException(status_code=404, detail="Banco no encontrado")
    
    for key, value in banco_data.dict(exclude_unset=True).items():
        setattr(db_banco, key, value)
        
    try:
        db.commit()
        db.refresh(db_banco)
    except:
        db.rollback()
        raise HTTPException(status_code=400, detail="Error al actualizar banco")
    return db_banco

# --- Puertos ---
@router.post("/puertos", response_model=schemas.PuertoResponse)
def create_puerto(puerto: schemas.PuertoBase, db: Session = Depends(get_db)):
    db_puerto = models.Puerto(
        nombre=puerto.nombre, 
        nodo_id=puerto.nodo_id,
        limite_ip=puerto.limite_ip,
        limite_device=puerto.limite_device,
        limite_service_port=puerto.limite_service_port
    )
    db.add(db_puerto)
    try:
        db.commit()
        db.refresh(db_puerto)
    except:
        db.rollback()
        raise HTTPException(status_code=400, detail="Error al crear puerto")
    return db_puerto

@router.get("/puertos", response_model=List[schemas.PuertoResponse])
def get_puertos(nodo_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(models.Puerto)
    if nodo_id:
        query = query.filter(models.Puerto.nodo_id == nodo_id)
    return query.all()

@router.delete("/puertos/{puerto_id}")
def delete_puerto(puerto_id: int, db: Session = Depends(get_db)):
    puerto = db.query(models.Puerto).filter(models.Puerto.id == puerto_id).first()
    if not puerto:
        raise HTTPException(status_code=404, detail="Puerto no encontrado")
    db.delete(puerto)
    db.commit()
    return {"message": "Puerto eliminado"}

@router.patch("/puertos/{puerto_id}", response_model=schemas.PuertoResponse)
def update_puerto(puerto_id: int, puerto_data: schemas.PuertoUpdate, db: Session = Depends(get_db)):
    db_puerto = db.query(models.Puerto).filter(models.Puerto.id == puerto_id).first()
    if not db_puerto:
        raise HTTPException(status_code=404, detail="Puerto no encontrado")
    
    for key, value in puerto_data.dict(exclude_unset=True).items():
        setattr(db_puerto, key, value)
        
    try:
        db.commit()
        db.refresh(db_puerto)
    except:
        db.rollback()
        raise HTTPException(status_code=400, detail="Error al actualizar puerto")
    return db_puerto

# --- Finanzas Base ---
@router.get("/finanzas-base", response_model=schemas.FinanzasBaseResponse)
def get_finanzas_base(db: Session = Depends(get_db)):
    finanzas = db.query(models.FinanzasBase).first()
    if not finanzas:
        finanzas = models.FinanzasBase(caja_chica=0.00, pichincha=0.00, jep=0.00)
        db.add(finanzas)
        db.commit()
        db.refresh(finanzas)
    return finanzas

@router.put("/finanzas-base", response_model=schemas.FinanzasBaseResponse)
def update_finanzas_base(data: schemas.FinanzasBaseUpdate, db: Session = Depends(get_db)):
    finanzas = db.query(models.FinanzasBase).first()
    if not finanzas:
        finanzas = models.FinanzasBase()
        db.add(finanzas)
        
    if data.caja_chica is not None:
        finanzas.caja_chica = data.caja_chica
    if data.pichincha is not None:
        finanzas.pichincha = data.pichincha
    if data.jep is not None:
        finanzas.jep = data.jep
        
    try:
        db.commit()
        db.refresh(finanzas)
    except:
        db.rollback()
        raise HTTPException(status_code=400, detail="Error al actualizar finanzas base")
    return finanzas

# --- Parroquias ---
@router.post("/parroquias", response_model=schemas.ParroquiaResponse)
def create_parroquia(parroquia: schemas.ParroquiaBase, db: Session = Depends(get_db)):
    db_parr = models.Parroquia(nombre=parroquia.nombre)
    db.add(db_parr)
    try:
        db.commit()
        db.refresh(db_parr)
    except:
        db.rollback()
        raise HTTPException(status_code=400, detail="Error o parroquia duplicada")
    return db_parr

@router.get("/parroquias", response_model=List[schemas.ParroquiaResponse])
def get_parroquias(db: Session = Depends(get_db)):
    return db.query(models.Parroquia).all()

@router.delete("/parroquias/{parr_id}")
def delete_parroquia(parr_id: int, db: Session = Depends(get_db)):
    parr = db.query(models.Parroquia).filter(models.Parroquia.id == parr_id).first()
    if not parr:
        raise HTTPException(status_code=404, detail="Parroquia no encontrada")
    db.delete(parr)
    db.commit()
    return {"message": "Parroquia eliminada"}

@router.patch("/parroquias/{parr_id}", response_model=schemas.ParroquiaResponse)
def update_parroquia(parr_id: int, parr_data: schemas.ParroquiaUpdate, db: Session = Depends(get_db)):
    db_parr = db.query(models.Parroquia).filter(models.Parroquia.id == parr_id).first()
    if not db_parr:
        raise HTTPException(status_code=404, detail="Parroquia no encontrada")
    
    for key, value in parr_data.dict(exclude_unset=True).items():
        setattr(db_parr, key, value)
        
    try:
        db.commit()
        db.refresh(db_parr)
    except:
        db.rollback()
        raise HTTPException(status_code=400, detail="Error al actualizar parroquia")
    return db_parr

@router.get("/WIPE-ALL-DB-DANGEROUS")
def wipe_all(db: Session = Depends(get_db)):
    try:
        db.query(models.Pago).delete()
        db.query(models.HojaRuta).delete()
        db.query(models.Cliente).delete()
        db.query(models.Puerto).delete()
        db.query(models.Nodo).delete()
        db.commit()
        return {"message": "WIPED"}
    except Exception as e:
        db.rollback()
        return {"error": str(e)}

# --- Cajas NAP ---
def _enrich_caja(caja, db):
    """Agrega nodo_nombre al dict de respuesta de una CajaNap."""
    d = {c.key: getattr(caja, c.key) for c in caja.__table__.columns}
    nodo = db.query(models.Nodo).filter(models.Nodo.id == caja.nodo_id).first() if caja.nodo_id else None
    d["nodo_nombre"] = nodo.nombre if nodo else None
    return d

@router.post("/cajas-nap", response_model=schemas.CajaNapResponse)
def create_caja_nap(caja: schemas.CajaNapBase, db: Session = Depends(get_db)):
    db_caja = models.CajaNap(nombre=caja.nombre, nodo_id=caja.nodo_id)
    db.add(db_caja)
    try:
        db.commit()
        db.refresh(db_caja)
    except:
        db.rollback()
        raise HTTPException(status_code=400, detail="Error o caja NAP duplicada")
    return _enrich_caja(db_caja, db)

@router.get("/cajas-nap", response_model=List[schemas.CajaNapResponse])
def get_cajas_nap(db: Session = Depends(get_db)):
    cajas = db.query(models.CajaNap).all()
    return [_enrich_caja(c, db) for c in cajas]

@router.delete("/cajas-nap/{caja_id}")
def delete_caja_nap(caja_id: int, db: Session = Depends(get_db)):
    caja = db.query(models.CajaNap).filter(models.CajaNap.id == caja_id).first()
    if not caja:
        raise HTTPException(status_code=404, detail="Caja NAP no encontrada")
    db.delete(caja)
    db.commit()
    return {"message": "Caja NAP eliminada"}

@router.patch("/cajas-nap/{caja_id}", response_model=schemas.CajaNapResponse)
def update_caja_nap(caja_id: int, caja_data: schemas.CajaNapUpdate, db: Session = Depends(get_db)):
    db_caja = db.query(models.CajaNap).filter(models.CajaNap.id == caja_id).first()
    if not db_caja:
        raise HTTPException(status_code=404, detail="Caja NAP no encontrada")

    for key, value in caja_data.dict(exclude_unset=True).items():
        setattr(db_caja, key, value)

    try:
        db.commit()
        db.refresh(db_caja)
    except:
        db.rollback()
        raise HTTPException(status_code=400, detail="Error al actualizar caja NAP")
    return _enrich_caja(db_caja, db)
