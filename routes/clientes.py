from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
import models, schemas
from database import get_db
from datetime import datetime

router = APIRouter(prefix="/clientes", tags=["clientes"])

# Definición de Precios por Plan
PLAN_PRICES = {
    "100mb": 17.25,
    "100M/100M": 17.25,
    "600mb": 17.87,
    "600M/600M": 17.87,
    "700mb": 21.73,
    "800mb": 32.20,
    "800M/800M": 32.20,
    "650M/650M": 20.00
}

@router.get("/")
def listar_clientes(db: Session = Depends(get_db)):
    try:
        data = db.query(models.Cliente).all()
        return data
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}

@router.post("/", response_model=schemas.ClienteResponse)
def crear_cliente(cliente: schemas.ClienteCreate, db: Session = Depends(get_db)):
    db_cliente = models.Cliente(
        nombre=cliente.nombre,
        cedula=cliente.cedula,
        celular=cliente.celular,
        correo=cliente.correo,
        direccion=cliente.direccion,
        parroquia=cliente.parroquia,
        plan=cliente.plan,
        plus=cliente.plus,
        fecha_firma=cliente.fecha_firma,
        estado="Pendiente"
    )
    db.add(db_cliente)
    db.commit()
    db.refresh(db_cliente)
    return db_cliente

@router.patch("/{id}/pasar-a-activacion")
def pasar_a_activacion(id: int, db: Session = Depends(get_db)):
    cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    cliente.estado = "En Activación"
    db.commit()
    return {"message": "Cliente pasado a etapa de activación", "estado": cliente.estado}

@router.get("/{id}", response_model=schemas.ClienteResponse)
def obtener_cliente(id: int, db: Session = Depends(get_db)):
    cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return cliente

@router.patch("/{id}")
def actualizar_cliente_general(id: int, data: schemas.ClienteUpdateGeneral, db: Session = Depends(get_db)):
    cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    for var, value in vars(data).items():
        if value is not None:
            setattr(cliente, var, value)
            
    db.commit()
    return {"message": "Cliente actualizado correctamente"}

@router.patch("/{id}/configuracion-tecnica")
def actualizar_datos_tecnicos(id: int, data: schemas.ClienteUpdateTecnico, db: Session = Depends(get_db)):
    cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    for var, value in vars(data).items():
        setattr(cliente, var, value)
    
    cliente.estado = "Activo"
    db.commit()
    return {"message": "Configuración técnica guardada, cliente ahora Activo"}

@router.patch("/{id}/administracion")
def actualizar_administracion(id: int, data: schemas.ClienteUpdateAdmin, db: Session = Depends(get_db)):
    cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    for var, value in vars(data).items():
        if value is not None:
            setattr(cliente, var, value)
            
    db.commit()
    return {"message": "Datos de administración actualizados"}

@router.post("/{id}/pagar")
def registrar_pago(id: int, pago_data: schemas.PagoCreate, db: Session = Depends(get_db)):
    cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    nuevo_pago = models.Pago(
        cliente_id=id,
        monto=pago_data.monto,
        metodo_pago=pago_data.metodo_pago,
        mes_correspondiente=pago_data.mes_correspondiente,
        referencia=pago_data.referencia
    )
    db.add(nuevo_pago)
    
    saldo_anterior = float(cliente.saldo or 0)
    nuevo_saldo = saldo_anterior - float(pago_data.monto)
    cliente.saldo = nuevo_saldo
    
    db.commit()
    
    if nuevo_saldo < 0:
        return {"message": f"Pago registrado con éxito. El cliente tiene un excedente de ${abs(nuevo_saldo):.2f}", "nuevo_saldo": nuevo_saldo}
    return {"message": f"Pago registrado con éxito. Nuevo saldo: ${nuevo_saldo:.2f}", "nuevo_saldo": nuevo_saldo}

@router.post("/facturacion-mensual-global")
def ejecutar_facturacion_mensual(db: Session = Depends(get_db)):
    # Normalizamos la búsqueda para que tome tanto "Activo" como "ACTIVO"
    clientes = db.query(models.Cliente).all()
    clientes_activos = [c for c in clientes if c.estado and c.estado.upper() == "ACTIVO"]
    
    count = 0
    for cliente in clientes_activos:
        # Se asigna el precio según el plan contratado
        tarifa = PLAN_PRICES.get(cliente.plan, 20.00)
        
        # Sumar el plus (plan adicional) si existe y es numérico
        try:
            monto_plus = float(cliente.plus) if cliente.plus else 0.0
        except (ValueError, TypeError):
            monto_plus = 0.0
            
        total_a_cobrar = tarifa + monto_plus
        
        cliente.saldo = (float(cliente.saldo or 0) + total_a_cobrar)
        count += 1
        
    db.commit()
    return {"message": f"Facturación procesada para {count} clientes."}

@router.post("/pago-global-test")
def liquidar_todas_las_deudas(db: Session = Depends(get_db)):
    clientes = db.query(models.Cliente).filter(models.Cliente.saldo > 0).all()
    count = 0
    for cliente in clientes:
        # Registrar un pago ficticio para el historial si se desea, 
        # pero para test solo resetearemos el saldo.
        cliente.saldo = 0.00
        count += 1
    db.commit()
    return {"message": f"Deudas liquidadas para {count} clientes (TEST)."}


@router.get("/pagos/historial")
def listar_pagos(db: Session = Depends(get_db)):
    return db.query(models.Pago).order_by(models.Pago.fecha_pago.desc()).all()
