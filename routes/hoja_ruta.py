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
    # Ordenar por fecha (desc) y luego por hora (desc)
    return db.query(models.HojaRuta).order_by(models.HojaRuta.fecha.asc(), models.HojaRuta.hora.asc()).all()

@router.post("/", response_model=schemas.HojaRutaResponse, dependencies=[Depends(require_role(["administrador", "tecnico", "secretario"]))])
def crear_hoja_ruta(hoja: schemas.HojaRutaCreate, db: Session = Depends(get_db)):
    db_hoja = models.HojaRuta(**hoja.dict())
    db.add(db_hoja)
    db.commit()
    db.refresh(db_hoja)
    return db_hoja

@router.patch("/{id}", response_model=schemas.HojaRutaResponse)
def actualizar_hoja_ruta(
    id: int, 
    data: schemas.HojaRutaUpdate, 
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    db_hoja = db.query(models.HojaRuta).filter(models.HojaRuta.id == id).first()
    if not db_hoja:
        raise HTTPException(status_code=404, detail="Hoja de ruta no encontrada")
    
    update_data = data.dict(exclude_unset=True)
    
    # REGLA: El estado solo lo puede cambiar el administrador
    if "estado" in update_data and update_data["estado"] != db_hoja.estado:
        if current_user.rol != "administrador":
            raise HTTPException(
                status_code=403, 
                detail="Solo el administrador puede cambiar el estado de la hoja de ruta"
            )
            
    # REGLA: La observacion_tecnico solo la puede cambiar el tecnico (u admin)
    if "observacion_tecnico" in update_data:
         if current_user.rol not in ["administrador", "tecnico"]:
             raise HTTPException(
                 status_code=403,
                 detail="Solo el técnico o administrador pueden añadir observaciones de campo"
             )

    for var, value in update_data.items():
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
