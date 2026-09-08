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
    try:
        # Ordenar por fecha (desc) y luego por hora (desc)
        return db.query(models.HojaRuta).order_by(models.HojaRuta.fecha.asc(), models.HojaRuta.hora.asc()).all()
    except Exception as e:
        print(f"Error en listar_hoja_ruta: {e}")
        raise HTTPException(status_code=500, detail=f"Error al obtener hoja de ruta: {str(e)}")

@router.post("/", response_model=schemas.HojaRutaResponse, dependencies=[Depends(require_role(["administrador", "tecnico", "secretario"]))])
def crear_hoja_ruta(hoja: schemas.HojaRutaCreate, db: Session = Depends(get_db)):
    db_hoja = models.HojaRuta(**hoja.dict())
    db.add(db_hoja)
    db.commit()
    db.refresh(db_hoja)
    return db_hoja

@router.patch("/{id}", response_model=schemas.HojaRutaResponse)
def actualizar_hoja_ruta(id: int, data: schemas.HojaRutaUpdate, db: Session = Depends(get_db), current_user: models.Usuario = Depends(get_current_user)):
    try:
        db_hoja = db.query(models.HojaRuta).filter(models.HojaRuta.id == id).first()
        if not db_hoja:
            raise HTTPException(status_code=404, detail="Hoja de ruta no encontrada")
        
        # Obtener el rol en minúsculas para comparaciones seguras
        user_role = (current_user.rol or "").lower()
        is_admin = user_role in ["administrador", "admin"]
        is_staff = is_admin or user_role in ["tecnico", "secretario", "instalador"]

        # 1. Permisos para cambiar el estado: Solo administradores
        # Usamos getattr por seguridad si hay problemas de recarga de schemas
        new_estado = getattr(data, 'estado', None)
        if new_estado is not None and new_estado != db_hoja.estado:
            if not is_admin:
                raise HTTPException(status_code=403, detail="Solo el administrador puede cambiar el estado de la hoja de ruta")
        
        # 2. Control de Calidad: No cerrar instalaciones como Realizado sin potencia óptica
        target_estado = new_estado if new_estado is not None else db_hoja.estado
        if target_estado == "Realizado" and "INSTAL" in (db_hoja.actividad or "").upper():
            nueva_obs = getattr(data, 'observacion_tecnico', None)
            obs_a_verificar = nueva_obs if nueva_obs is not None else (db_hoja.observacion_tecnico or "")
            import re
            tiene_potencia = bool(re.search(r'(?:-\s*\d{1,2}(?:[\.,]\d+)?\s*(?:dbm|db)?)|potencia', obs_a_verificar, re.IGNORECASE))
            if not tiene_potencia:
                raise HTTPException(
                    status_code=400,
                    detail="Control de Calidad: No se puede cerrar una instalación sin registrar la potencia óptica medida en dBm (-12.0 a -27.0 dBm)."
                )

        # 3. Permisos generales para editar cualquier campo: Staff autorizado
        if not is_staff:
            raise HTTPException(status_code=403, detail="No tienes permisos para editar hojas de ruta")

        # 3. Aplicar cambios de forma segura
        # Usamos model_dump para Pydantic v2 (o dict para compatibilidad)
        if hasattr(data, "model_dump"):
            update_data = data.model_dump(exclude_unset=True)
        else:
            update_data = data.dict(exclude_unset=True)

        for var, value in update_data.items():
            # Manejo de campos numéricos que vienen como string vacío desde el frontend
            if var == "cliente_id" and (value == "" or value == 0):
                value = None
            setattr(db_hoja, var, value)
        
        db.commit()
        db.refresh(db_hoja)
        return db_hoja
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print("--- ERROR CRÍTICO EN HOJA DE RUTA PATCH ---")
        traceback.print_exc()
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{id}", dependencies=[Depends(require_role(["administrador"]))])
def eliminar_hoja_ruta(id: int, db: Session = Depends(get_db)):
    db_hoja = db.query(models.HojaRuta).filter(models.HojaRuta.id == id).first()
    if not db_hoja:
        raise HTTPException(status_code=404, detail="Hoja de ruta no encontrada")
    db.delete(db_hoja)
    db.commit()
    return {"message": "Registro de hoja de ruta eliminado"}
