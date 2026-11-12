"""
@file schemas.py
@description Esquemas Pydantic específicos para el módulo de balance y finanzas.
"""
from typing import Optional
from pydantic import BaseModel

class EgresoCreate(BaseModel):
    descripcion: str
    categoria: str          # "operacional", "proyecto", "nomina", "otro"
    subcategoria: Optional[str] = None   # VIATICOS, CONSTRUCCION, COMPRAS…
    monto: float
    fecha: str              # YYYY-MM-DD
    mes: str                # "2026-04"
    metodo_pago: Optional[str] = "Efectivo"
    estado: Optional[str] = "Realizado"  # "Realizado" o "Pendiente"
    gasto_fijo_id: Optional[int] = None
    notas: Optional[str] = None

class EgresoUpdate(BaseModel):
    descripcion: Optional[str] = None
    categoria: Optional[str] = None
    subcategoria: Optional[str] = None
    monto: Optional[float] = None
    fecha: Optional[str] = None
    mes: Optional[str] = None
    metodo_pago: Optional[str] = None
    estado: Optional[str] = None
    gasto_fijo_id: Optional[int] = None
    notas: Optional[str] = None

class ProyectoCreate(BaseModel):
    nombre: str
    descripcion: Optional[str] = None
    monto_total: float
    monto_invertido: float = 0.0
    estado: str = "En progreso"
    fecha_inicio: str
    fecha_fin: Optional[str] = None
    ganancia: Optional[float] = 0.0
    banco_ganancia: Optional[str] = "Pichincha"

class ProyectoUpdate(BaseModel):
    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    monto_total: Optional[float] = None
    monto_invertido: Optional[float] = None
    estado: Optional[str] = None
    fecha_inicio: Optional[str] = None
    fecha_fin: Optional[str] = None
    ganancia: Optional[float] = None
    banco_ganancia: Optional[str] = None

class ProyectoPagoCreate(BaseModel):
    item: int = 1
    descripcion: str
    fecha: Optional[str] = None
    tipo_pago: Optional[str] = "Pichincha"
    valor: float

class ProyectoPagoUpdate(BaseModel):
    item: Optional[int] = None
    descripcion: Optional[str] = None
    fecha: Optional[str] = None
    tipo_pago: Optional[str] = None
    valor: Optional[float] = None

class GastoProyectoCreate(BaseModel):
    subcategoria: str         # VIATICOS, CONSTRUCCION, COMPRAS, HERRAJERIA…
    item: int = 1
    descripcion: str
    fecha: Optional[str] = None
    tipo_pago: Optional[str] = "Pichincha"
    valor: float
    pendiente: bool = False

class GastoProyectoUpdate(BaseModel):
    subcategoria: Optional[str] = None
    item: Optional[int] = None
    descripcion: Optional[str] = None
    fecha: Optional[str] = None
    tipo_pago: Optional[str] = None
    valor: Optional[float] = None
    pendiente: Optional[bool] = None

class ColchonCreate(BaseModel):
    descripcion: str
    monto: float
    fecha: str

class ColchonUpdate(BaseModel):
    descripcion: Optional[str] = None
    monto: Optional[float] = None
    fecha: Optional[str] = None

class ConsolidarMesRequest(BaseModel):
    mes: str
    forzar: Optional[bool] = False

class GastoFijoCreate(BaseModel):
    descripcion: str
    monto: float
    categoria: str = "operacional"   # operacional, nomina, otro
    metodo_pago: Optional[str] = "Efectivo"
    activo: bool = True
    notas: Optional[str] = None

class GastoFijoUpdate(BaseModel):
    descripcion: Optional[str] = None
    monto: Optional[float] = None
    categoria: Optional[str] = None
    metodo_pago: Optional[str] = None
    activo: Optional[bool] = None
    notas: Optional[str] = None
