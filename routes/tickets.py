from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
import models, schemas
from database import get_db
from .auth import get_current_user, require_role

router = APIRouter(prefix="/tickets", tags=["tickets"])

@router.post("/", response_model=schemas.TicketResponse)
def crear_ticket(ticket: schemas.TicketCreate, db: Session = Depends(get_db), current_user = Depends(require_role(["administrador"]))):
    db_ticket = models.Ticket(
        titulo=ticket.titulo,
        contenido=ticket.contenido,
        autor=current_user.username,
        estado="Pendiente"
    )
    db.add(db_ticket)
    db.commit()
    db.refresh(db_ticket)
    return db_ticket

@router.get("/", response_model=List[schemas.TicketResponse])
def listar_tickets(db: Session = Depends(get_db), current_user = Depends(require_role(["administrador"]))):
    return db.query(models.Ticket).order_by(models.Ticket.fecha_creacion.desc()).all()

@router.patch("/{id}", response_model=schemas.TicketResponse)
def actualizar_ticket(id: int, data: schemas.TicketUpdate, db: Session = Depends(get_db), current_user = Depends(require_role(["administrador"]))):
    db_ticket = db.query(models.Ticket).filter(models.Ticket.id == id).first()
    if not db_ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    
    if data.estado:
        db_ticket.estado = data.estado
    if data.contenido:
        db_ticket.contenido = data.contenido
        
    db.commit()
    db.refresh(db_ticket)
    return db_ticket

@router.delete("/{id}")
def eliminar_ticket(id: int, db: Session = Depends(get_db), current_user = Depends(require_role(["administrador"]))):
    db_ticket = db.query(models.Ticket).filter(models.Ticket.id == id).first()
    if not db_ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    db.delete(db_ticket)
    db.commit()
    return {"message": "Ticket eliminado"}
