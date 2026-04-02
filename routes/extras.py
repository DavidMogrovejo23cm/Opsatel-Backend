from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
import models, schemas
from database import get_db
from datetime import datetime
from .auth import get_current_user, require_role

router = APIRouter(prefix="/extras", tags=["extras"])

@router.get("/", response_model=List[schemas.ClienteExtraResponse])
def listar_extras(db: Session = Depends(get_db)):
    return db.query(models.ClienteExtra).all()

@router.post("/", response_model=schemas.ClienteExtraResponse, dependencies=[Depends(require_role(["administrador", "secretario", "tecnico"]))])
def crear_extra(extra: schemas.ClienteExtraCreate, db: Session = Depends(get_db)):
    db_extra = models.ClienteExtra(**extra.dict())
    db.add(db_extra)
    db.commit()
    db.refresh(db_extra)
    return db_extra

@router.patch("/{id}", response_model=schemas.ClienteExtraResponse, dependencies=[Depends(require_role(["administrador", "secretario"]))])
def actualizar_extra(id: int, data: schemas.ClienteExtraUpdate, db: Session = Depends(get_db)):
    db_extra = db.query(models.ClienteExtra).filter(models.ClienteExtra.id == id).first()
    if not db_extra:
        raise HTTPException(status_code=404, detail="Cliente extra no encontrado")
    
    for var, value in data.dict(exclude_unset=True).items():
        setattr(db_extra, var, value)
    
    db.commit()
    db.refresh(db_extra)
    return db_extra

@router.delete("/{id}", dependencies=[Depends(require_role(["administrador"]))])
def eliminar_extra(id: int, db: Session = Depends(get_db)):
    db_extra = db.query(models.ClienteExtra).filter(models.ClienteExtra.id == id).first()
    if not db_extra:
        raise HTTPException(status_code=404, detail="Cliente extra no encontrado")
    db.delete(db_extra)
    db.commit()
    return {"message": "Cliente extra eliminado"}

@router.post("/{id}/pagar", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def registrar_pago_extra(id: int, pago_data: schemas.PagoExtraCreate, db: Session = Depends(get_db)):
    cliente = db.query(models.ClienteExtra).filter(models.ClienteExtra.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente extra no encontrado")

    monto = float(pago_data.monto)
    mes = (pago_data.mes_correspondiente or "").lower()

    # Registrar en historial
    nuevo_pago = models.PagoExtra(
        cliente_id=id,
        monto=monto,
        metodo_pago=pago_data.metodo_pago,
        mes_correspondiente=pago_data.mes_correspondiente,
        referencia=pago_data.referencia,
        factura=pago_data.factura
    )
    db.add(nuevo_pago)

    # Actualizar campos del cliente según el mes
    meses_validos = [
        "enero", "febrero", "marzo", "abril", "mayo", "junio", 
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"
    ]
    
    if mes in meses_validos:
        setattr(cliente, f"{mes}_pago", float(getattr(cliente, f"{mes}_pago") or 0) + monto)
        setattr(cliente, f"{mes}_fecha_pago", datetime.now().strftime("%d/%m/%Y"))
        setattr(cliente, f"{mes}_banco", pago_data.metodo_pago)
        setattr(cliente, f"{mes}_factura", pago_data.factura)
        
        # Recalcular saldo del mes
        valor_base = float(cliente.valor or 0)
        pago_mes = float(getattr(cliente, f"{mes}_pago") or 0)
        setattr(cliente, f"{mes}_saldo", max(0, valor_base - pago_mes))

    # Actualizar totales globales
    cliente.total_pagado = float(cliente.total_pagado or 0) + monto
    # El saldo_pendiente global podría ser la suma de los saldos mensuales o algo similar
    # Por ahora lo dejamos manual o basado en el valor actual
    
    db.commit()
    return {"message": "Pago extra registrado correctamente"}

@router.get("/pagos/historial")
def historial_pagos_extras(db: Session = Depends(get_db)):
    return db.query(models.PagoExtra).order_by(models.PagoExtra.fecha_pago.desc()).all()
