from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime

class ClienteCreate(BaseModel):
    nombre: str
    cedula: str
    celular: str
    correo: Optional[EmailStr] = None
    direccion: str
    parroquia: str
    plan: str
    plus: Optional[str] = "0"
    fecha_firma: str

class ClienteUpdateTecnico(BaseModel):
    puerto: str
    ont: str
    servicio: str
    breach: Optional[str] = None
    id_port: str
    service_port: str
    ip: str
    dispositivo: str
    potencia: str
    nap: str
    ubicacion: str
    tecnico: str
    activador: str
    red: str
    clave: str

class ClienteUpdateAdmin(BaseModel):
    plan: Optional[str] = None
    estado: Optional[str] = None
    tiempo: Optional[str] = None
    arrienda: Optional[str] = None
    cuenta: Optional[str] = None
    facturas: Optional[str] = None
    internet_payment: Optional[str] = None
    app: Optional[str] = None
    payment_date: Optional[str] = None
    client_payment_date: Optional[str] = None
    bank: Optional[str] = None
    cod: Optional[str] = None
    plus: Optional[str] = None
    bank_plus: Optional[str] = None
    saldo: Optional[float] = None

class ClienteUpdateGeneral(BaseModel):
    nombre: Optional[str] = None
    cedula: Optional[str] = None
    celular: Optional[str] = None
    correo: Optional[str] = None
    direccion: Optional[str] = None
    parroquia: Optional[str] = None
    plan: Optional[str] = None
    estado: Optional[str] = None
    puerto: Optional[str] = None
    ont: Optional[str] = None
    servicio: Optional[str] = None
    breach: Optional[str] = None
    id_port: Optional[str] = None
    service_port: Optional[str] = None
    ip: Optional[str] = None
    dispositivo: Optional[str] = None
    potencia: Optional[str] = None
    nap: Optional[str] = None
    ubicacion: Optional[str] = None
    tecnico: Optional[str] = None
    activador: Optional[str] = None
    red: Optional[str] = None
    clave: Optional[str] = None
    tiempo: Optional[str] = None
    arrienda: Optional[str] = None
    cuenta: Optional[str] = None
    facturas: Optional[str] = None
    internet_payment: Optional[str] = None
    app: Optional[str] = None
    payment_date: Optional[str] = None
    client_payment_date: Optional[str] = None
    bank: Optional[str] = None
    cod: Optional[str] = None
    plus: Optional[str] = None
    bank_plus: Optional[str] = None
    saldo: Optional[float] = None

class PagoCreate(BaseModel):
    monto: float
    metodo_pago: str
    mes_correspondiente: str
    referencia: Optional[str] = None

class ClienteResponse(BaseModel):
    id: int
    nombre: Optional[str] = None
    cedula: Optional[str] = None
    celular: Optional[str] = None
    correo: Optional[str] = None
    direccion: Optional[str] = None
    parroquia: Optional[str] = None
    plan: Optional[str] = None
    cedula_tipo: Optional[str] = None
    ubicacion: Optional[str] = None
    estado: Optional[str] = "Pendiente"
    tiempo: Optional[str] = None
    arrienda: Optional[str] = None
    cuenta: Optional[str] = None
    fecha_firma: Optional[str] = None
    instalation_date: Optional[str] = None
    puerto: Optional[str] = None
    ont: Optional[str] = None
    servicio: Optional[str] = None
    breach: Optional[str] = None
    id_port: Optional[str] = None
    service_port: Optional[str] = None
    ip: Optional[str] = None
    dispositivo: Optional[str] = None
    potencia: Optional[str] = None
    nap: Optional[str] = None
    tecnico: Optional[str] = None
    activador: Optional[str] = None
    red: Optional[str] = None
    clave: Optional[str] = None
    facturas: Optional[str] = None
    internet_payment: Optional[str] = None
    app: Optional[str] = None
    payment_date: Optional[str] = None
    client_payment_date: Optional[str] = None
    internet_payment_2: Optional[str] = None
    bank: Optional[str] = None
    cod: Optional[str] = None
    plus: Optional[str] = None
    bank_plus: Optional[str] = None
    saldo: Optional[float] = 0.0

    class Config:
        from_attributes = True
