from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional
from datetime import datetime

class ClienteCreate(BaseModel):
    nombre: str
    cedula: str
    cedula_tipo: Optional[str] = None
    cedula_frontal: Optional[str] = None
    cedula_posterior: Optional[str] = None
    celular: str
    correo: Optional[EmailStr] = None
    direccion: str
    nodo: str
    parroquia: Optional[str] = None
    plan: str
    plus: Optional[str] = "0"
    fecha_firma: str
    ubicacion: Optional[str] = None
    tiempo: Optional[str] = "0"
    tercera_edad: Optional[bool] = False
    precio_plan_especial: Optional[float] = 0.0

class ClienteUpdateTecnico(BaseModel):
    mac: str
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

    @field_validator('potencia')
    @classmethod
    def validate_potencia(cls, v: str) -> str:
        try:
            val = float(v.replace(',', '.'))
            if val < -27 or val > -6:
                raise ValueError('La potencia debe estar entre -6 y -27')
        except ValueError as e:
            if 'La potencia debe estar' in str(e):
                raise e
            pass
        return v

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
    adicional: Optional[str] = None
    comentarios: Optional[str] = None
    observaciones: Optional[str] = None
    pago_mensual: Optional[float] = None
    total_pago: Optional[float] = None
    saldo: Optional[float] = None
    tercera_edad: Optional[bool] = None
    precio_plan_especial: Optional[float] = None

class ClienteUpdateGeneral(BaseModel):
    nombre: Optional[str] = None
    cedula: Optional[str] = None
    celular: Optional[str] = None
    correo: Optional[str] = None
    direccion: Optional[str] = None
    nodo: Optional[str] = None
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
    red: Optional[str] = None
    clave: Optional[str] = None
    mac: Optional[str] = None
    instalation_date: Optional[str] = None
    ubicacion: Optional[str] = None
    cedula_tipo: Optional[str] = None
    cedula_frontal: Optional[str] = None
    cedula_posterior: Optional[str] = None
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
    adicional: Optional[str] = None
    comentarios: Optional[str] = None
    observaciones: Optional[str] = None
    pago_mensual: Optional[float] = None
    total_pago: Optional[float] = None
    saldo: Optional[float] = None
    tercera_edad: Optional[bool] = None
    precio_plan_especial: Optional[float] = None

    @field_validator('potencia')
    @classmethod
    def validate_potencia(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        try:
            val = float(v.replace(',', '.'))
            if val < -27 or val > -6:
                raise ValueError('La potencia debe estar entre -6 y -27')
        except ValueError as e:
            if 'La potencia debe estar' in str(e):
                raise e
            pass
        return v

class PagoCreate(BaseModel):
    monto: float
    metodo_pago: str
    mes_correspondiente: str
    referencia: Optional[str] = None
    facturas: Optional[str] = None
    internet_payment: Optional[str] = None
    app: Optional[str] = None
    payment_date: Optional[str] = None
    client_payment_date: Optional[str] = None
    bank: Optional[str] = None
    cod: Optional[str] = None
    plus: Optional[str] = None
    bank_plus: Optional[str] = None
    adicional: Optional[str] = None
    comentarios: Optional[str] = None

class ClienteResponse(BaseModel):
    id: int
    nombre: Optional[str] = None
    cedula: Optional[str] = None
    celular: Optional[str] = None
    correo: Optional[str] = None
    direccion: Optional[str] = None
    nodo: Optional[str] = None
    parroquia: Optional[str] = None
    plan: Optional[str] = None
    cedula_tipo: Optional[str] = None
    cedula_frontal: Optional[str] = None
    cedula_posterior: Optional[str] = None
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
    mac: Optional[str] = None
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
    adicional: Optional[str] = None
    comentarios: Optional[str] = None
    observaciones: Optional[str] = None
    pago_mensual: Optional[float] = 0.0
    total_pago: Optional[float] = 0.0
    saldo: Optional[float] = 0.0
    plus_pagado: Optional[float] = 0.0
    adicional_pagado: Optional[float] = 0.0
    tercera_edad: Optional[bool] = False
    precio_plan_especial: Optional[float] = 0.0

    class Config:
        from_attributes = True

class ReporteMensualResponse(BaseModel):
    id: int
    mes_anio: Optional[str] = None
    fecha_generacion: Optional[datetime] = None
    archivo_ruta_excel: Optional[str] = None


    class Config:
        from_attributes = True

class UsuarioAuth(BaseModel):
    username: str
    password: str

class UsuarioCreate(UsuarioAuth):
    rol: str # administrador, secretario, tecnico

class UsuarioResponse(BaseModel):
    id: int
    username: str
    rol: str

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str
    username: str
    rol: str

class NodoBase(BaseModel):
    nombre: str
    base_ip: Optional[str] = "172.16"

class NodoResponse(NodoBase):
    id: int
    class Config:
        from_attributes = True

class NodoUpdate(BaseModel):
    nombre: Optional[str] = None
    base_ip: Optional[str] = None

class PlanInternetBase(BaseModel):
    nombre: str
    megas: Optional[int] = 100
    precio: Optional[float] = 0.0

class PlanInternetResponse(PlanInternetBase):
    id: int
    class Config:
        from_attributes = True

class PlanInternetUpdate(BaseModel):
    nombre: Optional[str] = None
    megas: Optional[int] = None
    precio: Optional[float] = None

class BancoBase(BaseModel):
    nombre: str

class BancoResponse(BancoBase):
    id: int
    class Config:
        from_attributes = True

class BancoUpdate(BaseModel):
    nombre: Optional[str] = None

class PuertoBase(BaseModel):
    nombre: str
    nodo_id: Optional[int] = None

class PuertoResponse(PuertoBase):
    id: int
    class Config:
        from_attributes = True

class PuertoUpdate(BaseModel):
    nombre: Optional[str] = None
    nodo_id: Optional[int] = None

class UsuarioUpdate(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    rol: Optional[str] = None

class FinanzasBaseResponse(BaseModel):
    id: int
    caja_chica: float
    pichincha: float
    jep: float

    class Config:
        from_attributes = True

class FinanzasBaseUpdate(BaseModel):
    caja_chica: Optional[float] = None
    pichincha: Optional[float] = None
    jep: Optional[float] = None

class ParroquiaBase(BaseModel):
    nombre: str

class ParroquiaResponse(ParroquiaBase):
    id: int
    class Config:
        from_attributes = True

class ParroquiaUpdate(BaseModel):
    nombre: Optional[str] = None
