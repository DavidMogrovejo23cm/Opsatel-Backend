from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional

from database import get_db
import models
import schemas

router = APIRouter(
    prefix="/configuraciones",
    tags=["configuraciones"],
    responses={404: {"description": "Not found"}},
)

# --- Parroquias ---
@router.post("/parroquias", response_model=schemas.ParroquiaResponse)
def create_parroquia(parroquia: schemas.ParroquiaBase, db: Session = Depends(get_db)):
    db_parroquia = models.Parroquia(nombre=parroquia.nombre, base_ip=parroquia.base_ip)
    db.add(db_parroquia)
    try:
        db.commit()
        db.refresh(db_parroquia)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail="Error o parroquia duplicada")
    return db_parroquia

@router.get("/parroquias", response_model=List[schemas.ParroquiaResponse])
def get_parroquias(db: Session = Depends(get_db)):
    return db.query(models.Parroquia).all()

@router.delete("/parroquias/{parroquia_id}")
def delete_parroquia(parroquia_id: int, db: Session = Depends(get_db)):
    parroquia = db.query(models.Parroquia).filter(models.Parroquia.id == parroquia_id).first()
    if not parroquia:
        raise HTTPException(status_code=404, detail="Parroquia no encontrada")
    
    # Cascade delete puertos
    db.query(models.Puerto).filter(models.Puerto.parroquia_id == parroquia_id).delete()
    
    db.delete(parroquia)
    db.commit()
    return {"message": "Parroquia eliminada exitosamente"}

@router.patch("/parroquias/{parroquia_id}", response_model=schemas.ParroquiaResponse)
def update_parroquia(parroquia_id: int, parroquia_data: schemas.ParroquiaUpdate, db: Session = Depends(get_db)):
    db_parroquia = db.query(models.Parroquia).filter(models.Parroquia.id == parroquia_id).first()
    if not db_parroquia:
        raise HTTPException(status_code=404, detail="Parroquia no encontrada")
    
    for key, value in parroquia_data.dict(exclude_unset=True).items():
        setattr(db_parroquia, key, value)
    
    try:
        db.commit()
        db.refresh(db_parroquia)
    except:
        db.rollback()
        raise HTTPException(status_code=400, detail="Error al actualizar parroquia")
    return db_parroquia

# --- Planes ---
@router.post("/planes", response_model=schemas.PlanInternetResponse)
def create_plan(plan: schemas.PlanInternetBase, db: Session = Depends(get_db)):
    db_plan = models.PlanInternet(nombre=plan.nombre, precio=plan.precio)
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
    db_puerto = models.Puerto(nombre=puerto.nombre, parroquia_id=puerto.parroquia_id)
    db.add(db_puerto)
    try:
        db.commit()
        db.refresh(db_puerto)
    except:
        db.rollback()
        raise HTTPException(status_code=400, detail="Error al crear puerto")
    return db_puerto

@router.get("/puertos", response_model=List[schemas.PuertoResponse])
def get_puertos(parroquia_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(models.Puerto)
    if parroquia_id:
        query = query.filter(models.Puerto.parroquia_id == parroquia_id)
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

