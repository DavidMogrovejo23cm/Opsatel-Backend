# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, HTTPException, status
# pyrefly: ignore [missing-import]
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
    if not extra.fecha_ingreso:
        extra.fecha_ingreso = datetime.now().strftime("%Y-%m-%d")
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

def recalcular_cuadricula_extra(cliente: models.ClienteExtra, db: Session):
    meses_validos = [
        "enero", "febrero", "marzo", "abril", "mayo", "junio", 
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"
    ]
    
    valor_mensual = float(cliente.valor or 0)
    
    limite_ingreso_idx = 0
    if cliente.fecha_ingreso:
        try:
            mes_ingreso_num = int(cliente.fecha_ingreso.split("-")[1])
            limite_ingreso_idx = mes_ingreso_num - 1
        except:
            limite_ingreso_idx = 0

    # 1. Resetear cuadrícula
    for i in range(12):
        mes_actual = meses_validos[i]
        if i >= limite_ingreso_idx:
            setattr(cliente, f"{mes_actual}_saldo", valor_mensual)
        else:
            setattr(cliente, f"{mes_actual}_saldo", 0.0)
        setattr(cliente, f"{mes_actual}_pago", 0.0)
        setattr(cliente, f"{mes_actual}_fecha_pago", None)
        setattr(cliente, f"{mes_actual}_banco", None)
        setattr(cliente, f"{mes_actual}_factura", None)
        setattr(cliente, f"{mes_actual}_cod", None)

    # 2. Cargar pagos válidos
    pagos = db.query(models.PagoExtra).filter(
        models.PagoExtra.cliente_id == cliente.id,
        models.PagoExtra.anulado == False,
        models.PagoExtra.estado == "Completado"
    ).order_by(models.PagoExtra.id).all()
    
    total_pagado = 0.0
    
    for pago in pagos:
        monto_restante = float(pago.monto or 0)
        total_pagado += monto_restante
        mes_inicio = (pago.mes_correspondiente or "").lower()
        
        start_idx = limite_ingreso_idx
        if mes_inicio in meses_validos:
            start_idx = max(limite_ingreso_idx, meses_validos.index(mes_inicio))
            
        for i in range(start_idx, 12):
            if monto_restante <= 0:
                break
                
            mes_actual = meses_validos[i]
            pago_actual = float(getattr(cliente, f"{mes_actual}_pago") or 0)
            saldo_pendiente_mes = float(getattr(cliente, f"{mes_actual}_saldo") or 0)
            
            if saldo_pendiente_mes > 0:
                pago_a_aplicar = min(monto_restante, saldo_pendiente_mes)
                nuevo_pago_total = pago_actual + pago_a_aplicar
                setattr(cliente, f"{mes_actual}_pago", nuevo_pago_total)
                setattr(cliente, f"{mes_actual}_saldo", max(0, valor_mensual - nuevo_pago_total))
                setattr(cliente, f"{mes_actual}_fecha_pago", pago.fecha_pago.strftime("%d/%m/%Y") if pago.fecha_pago else datetime.now().strftime("%d/%m/%Y"))
                setattr(cliente, f"{mes_actual}_banco", pago.metodo_pago)
                setattr(cliente, f"{mes_actual}_factura", pago.factura)
                setattr(cliente, f"{mes_actual}_cod", pago.referencia)
                monto_restante -= pago_a_aplicar
                
    cliente.total_pagado = total_pagado

@router.post("/{id}/pagar")
def registrar_pago_extra(
    id: int, 
    pago_data: schemas.PagoExtraCreate, 
    db: Session = Depends(get_db), 
    current_user: models.Usuario = Depends(require_role(["administrador", "secretario"]))
):
    cliente = db.query(models.ClienteExtra).filter(models.ClienteExtra.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente extra no encontrado")

    # Enforzar caja abierta
    turno = db.query(models.TurnoCaja).filter(
        models.TurnoCaja.usuario_id == current_user.id,
        models.TurnoCaja.estado == "Abierto"
    ).first()
    if not turno:
        raise HTTPException(
            status_code=400, 
            detail="Debe abrir un turno de caja antes de poder registrar un pago."
        )

    monto = float(pago_data.monto)

    # Registrar en historial
    nuevo_pago = models.PagoExtra(
        cliente_id=id,
        monto=monto,
        metodo_pago=pago_data.metodo_pago,
        mes_correspondiente=pago_data.mes_correspondiente,
        referencia=pago_data.referencia,
        factura=pago_data.factura,
        estado=pago_data.estado or "Completado",
        turnocaja_id=turno.id
    )
    db.add(nuevo_pago)

    if nuevo_pago.estado == "Pendiente_Verificacion":
        db.commit()
        return {"message": "Pago extra registrado y pendiente de verificación bancaria."}

    # Recalcular cuadrícula si es completado
    recalcular_cuadricula_extra(cliente, db)
    db.commit()
    return {"message": "Pago extra registrado correctamente"}

@router.post("/{id}/pagos/{pago_id}/confirmar")
def confirmar_pago_extra(
    id: int, 
    pago_id: int, 
    db: Session = Depends(get_db), 
    current_user: models.Usuario = Depends(require_role(["administrador", "secretario"]))
):
    pago = db.query(models.PagoExtra).filter(models.PagoExtra.id == pago_id, models.PagoExtra.cliente_id == id).first()
    if not pago:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    if pago.estado != "Pendiente_Verificacion":
        raise HTTPException(status_code=400, detail="El pago ya está confirmado o anulado.")
    if pago.anulado:
        raise HTTPException(status_code=400, detail="No se puede confirmar un pago anulado.")
        
    cliente = db.query(models.ClienteExtra).filter(models.ClienteExtra.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente extra no encontrado")
        
    pago.estado = "Completado"
    recalcular_cuadricula_extra(cliente, db)
    db.commit()
    return {"message": "Pago extra confirmado y aplicado exitosamente."}

@router.post("/{id}/pagos/{pago_id}/anular")
def anular_pago_extra(
    id: int, 
    pago_id: int, 
    request_data: schemas.PagoAnularRequest, 
    db: Session = Depends(get_db), 
    current_user: models.Usuario = Depends(require_role(["administrador", "secretario"]))
):
    pago = db.query(models.PagoExtra).filter(models.PagoExtra.id == pago_id, models.PagoExtra.cliente_id == id).first()
    if not pago:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    if pago.anulado:
        raise HTTPException(status_code=400, detail="Este pago ya se encuentra anulado.")
        
    cliente = db.query(models.ClienteExtra).filter(models.ClienteExtra.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente extra no encontrado")
        
    pago.anulado = True
    pago.fecha_anulacion = datetime.utcnow()
    pago.anulado_por = current_user.username
    pago.motivo_anulacion = request_data.motivo_anulacion
    
    recalcular_cuadricula_extra(cliente, db)
    db.commit()
    return {"message": "Pago extra anulado exitosamente."}

@router.get("/pagos/historial")
def historial_pagos_extras(db: Session = Depends(get_db)):
    return db.query(models.PagoExtra).order_by(models.PagoExtra.fecha_pago.desc()).all()
