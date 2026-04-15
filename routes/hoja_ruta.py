from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
import models, schemas
from database import get_db
from datetime import datetime
from .auth import get_current_user, require_role

router = APIRouter(prefix="/hoja-ruta", tags=["hoja-ruta"])

@router.get("/", response_model=List[schemas.HojaRutaResponse])
def listar_hoja_ruta(db: Session = Depends(get_db)):
    return db.query(models.HojaRuta).all()

@router.post("/", response_model=schemas.HojaRutaResponse, dependencies=[Depends(require_role(["administrador", "tecnico"]))])
def crear_hoja_ruta(hoja: schemas.HojaRutaCreate, db: Session = Depends(get_db)):
    db_hoja = models.HojaRuta(**hoja.dict())
    db.add(db_hoja)
    db.commit()
    db.refresh(db_hoja)
    return db_hoja

@router.patch("/{id}", response_model=schemas.HojaRutaResponse)
def actualizar_hoja_ruta(id: int, data: schemas.HojaRutaUpdate, db: Session = Depends(get_db), current_user: models.Usuario = Depends(get_current_user)):
    db_hoja = db.query(models.HojaRuta).filter(models.HojaRuta.id == id).first()
    if not db_hoja:
        raise HTTPException(status_code=404, detail="Hoja de ruta no encontrada")
    
    # Restringir cambio de estado solo a administradores
    if data.estado is not None and data.estado != db_hoja.estado:
        if current_user.rol not in ["administrador", "admin"]:
            raise HTTPException(status_code=403, detail="Solo el administrador puede cambiar el estado de la hoja de ruta")
    
    # Técnicos solo pueden editar si son administradores o técnicos (require_role logic manual)
    if current_user.rol not in ["administrador", "admin", "tecnico"]:
        raise HTTPException(status_code=403, detail="No tienes permisos para editar hojas de ruta")

    for var, value in data.dict(exclude_unset=True).items():
        setattr(db_hoja, var, value)
    
    db.commit()
    db.refresh(db_hoja)
    return db_hoja

@router.delete("/{id}", dependencies=[Depends(require_role(["administrador"]))])
def eliminar_hoja_ruta(id: int, db: Session = Depends(get_db)):
    db_hoja = db.query(models.HojaRuta).filter(models.HojaRuta.id == id).first()
    if not db_hoja:
        raise HTTPException(status_code=404, detail="Hoja de ruta no encontrada")
    db.delete(db_hoja)
    db.commit()
    return {"message": "Registro de hoja de ruta eliminado"}
