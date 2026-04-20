from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
import models, schemas
from database import get_db
from datetime import datetime
from .auth import get_current_user, require_role

router = APIRouter(prefix="/callcenter", tags=["callcenter"])

@router.post("/", response_model=schemas.CallCenterTicketResponse)
def crear_ticket_callcenter(ticket: schemas.CallCenterTicketCreate, db: Session = Depends(get_db), current_user = Depends(require_role(["administrador", "secretario", "tecnico"]))):
    db_ticket = models.CallCenterTicket(
        cliente_nombre=ticket.cliente_nombre,
        ip=ticket.ip,
        direccion=ticket.direccion,
        telefono=ticket.telefono,
        registrado_por=current_user.username,
        estado=ticket.estado or "PENDIENTE",
        a_cargo=ticket.a_cargo,
        problema=ticket.problema,
        observacion_revision=ticket.observacion_revision,
        fecha_cambio_estado=datetime.now().strftime("%Y-%m-%d %H:%M") if ticket.estado else None
    )
    db.add(db_ticket)
    db.commit()
    db.refresh(db_ticket)
    return db_ticket

@router.get("/", response_model=List[schemas.CallCenterTicketResponse])
def listar_tickets_callcenter(db: Session = Depends(get_db), current_user = Depends(require_role(["administrador", "secretario", "tecnico"]))):
    return db.query(models.CallCenterTicket).order_by(models.CallCenterTicket.fecha_ingreso.desc()).all()

@router.patch("/{id}", response_model=schemas.CallCenterTicketResponse)
def actualizar_ticket_callcenter(id: int, data: schemas.CallCenterTicketUpdate, db: Session = Depends(get_db), current_user = Depends(require_role(["administrador", "secretario", "tecnico"]))):
    db_ticket = db.query(models.CallCenterTicket).filter(models.CallCenterTicket.id == id).first()
    if not db_ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    
    estado_anterior = db_ticket.estado
    
    for var, value in vars(data).items():
        if value is not None:
            setattr(db_ticket, var, value)
            
    if data.estado and data.estado != estado_anterior:
        db_ticket.fecha_cambio_estado = datetime.now().strftime("%Y-%m-%d %H:%M")
        
    db.commit()
    db.refresh(db_ticket)
    return db_ticket

@router.delete("/{id}")
def eliminar_ticket_callcenter(id: int, db: Session = Depends(get_db), current_user = Depends(require_role(["administrador"]))):
    db_ticket = db.query(models.CallCenterTicket).filter(models.CallCenterTicket.id == id).first()
    if not db_ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    db.delete(db_ticket)
    db.commit()
    return {"message": "Ticket de Call Center eliminado"}
