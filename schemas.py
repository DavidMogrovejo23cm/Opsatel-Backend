# pyrefly: ignore [missing-import]
from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional, List, Dict
from datetime import datetime

class ClienteCreate(BaseModel):
    nombre: str
    cedula: str
    cedula_tipo: Optional[str] = None
    cedula_frontal: Optional[str] = None
    cedula_posterior: Optional[str] = None
    celular: str
    correo: Optional[str] = None
    direccion: str
    nodo: str
    parroquia: Optional[str] = None
    plan: str
    plus: Optional[str] = "0"
    fecha_firma: str
    ubicacion: Optional[str] = None
    tiempo: Optional[str] = "0"
    tercera_edad: Optional[bool] = False
    plan_corporativo: Optional[bool] = False
    precio_plan_especial: Optional[float] = 0.0
    mantenimiento: Optional[bool] = False
    iptv_max_conn: Optional[int] = 0
    iptv_activar: Optional[bool] = False
    iptv_user: Optional[str] = None
    iptv_pass: Optional[str] = None
    tv_tipo: Optional[str] = "Ninguno"  # "Ninguno", "IPTV", "CATV"
    comentarios: Optional[str] = None

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
    plus: Optional[str] = None
    # IPTV (Nuevo req v1.3)
    iptv_activar: Optional[bool] = False
    iptv_user: Optional[str] = None
    iptv_pass: Optional[str] = None
    iptv_bouquets: Optional[str] = None
    iptv_exp_date: Optional[str] = None
    iptv_max_conn: Optional[int] = 0
    iptv_outputs: Optional[str] = None
    iptv_notes: Optional[str] = None
    iptv_member_id: Optional[int] = 1

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
    notas_pago: Optional[str] = None
    iptv_max_conn: Optional[int] = None
    pago_mensual: Optional[float] = None
    total_pago: Optional[float] = None
    saldo: Optional[float] = None
    tercera_edad: Optional[bool] = None
    precio_plan_especial: Optional[float] = None
    cortesia_total: Optional[bool] = None
    mantenimiento: Optional[bool] = None
    fecha_firma: Optional[str] = None
    instalation_date: Optional[str] = None

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
    fecha_firma: Optional[str] = None
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
    notas_pago: Optional[str] = None
    pago_mensual: Optional[float] = None
    total_pago: Optional[float] = None
    saldo: Optional[float] = None
    tercera_edad: Optional[bool] = None
    precio_plan_especial: Optional[float] = None
    mantenimiento: Optional[bool] = None
    # IPTV (Nuevo req v1.3)
    iptv_activar: Optional[bool] = None
    iptv_user: Optional[str] = None
    iptv_pass: Optional[str] = None
    iptv_bouquets: Optional[str] = None
    iptv_exp_date: Optional[str] = None
    iptv_max_conn: Optional[int] = None
    iptv_outputs: Optional[str] = None
    iptv_notes: Optional[str] = None
    iptv_member_id: Optional[int] = None
    tv_tipo: Optional[str] = None

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

class ClienteEliminarCompleto(BaseModel):
    pin: str

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
    notas_pago: Optional[str] = None
    descuento_internet: Optional[float] = 0.0
    descuento_plus: Optional[float] = 0.0
    descuento_adicional: Optional[float] = 0.0
    estado: Optional[str] = "Completado" # Completado, Pendiente_Verificacion

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
    estado: Optional[str] = "Activo"
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
    notas_pago: Optional[str] = None
    pago_mensual: Optional[float] = 0.0
    total_pago: Optional[float] = 0.0
    saldo: Optional[float] = 0.0
    plus_pagado: Optional[float] = 0.0
    adicional_pagado: Optional[float] = 0.0
    tercera_edad: Optional[bool] = False
    precio_plan_especial: Optional[float] = 0.0
    # IPTV (Nuevo req v1.3)
    iptv_activar: Optional[bool] = False
    iptv_user: Optional[str] = None
    iptv_pass: Optional[str] = None
    iptv_bouquets: Optional[str] = None
    iptv_exp_date: Optional[str] = None
    iptv_max_conn: Optional[int] = 0
    iptv_outputs: Optional[str] = None
    iptv_notes: Optional[str] = None
    iptv_member_id: Optional[int] = 1
    

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

class UsuarioCreate(BaseModel):
    username: str
    password: Optional[str] = None
    rol: str # administrador, secretario, tecnico
    acceso_general_sin_clave: Optional[bool] = False

class UsuarioResponse(BaseModel):
    id: int
    username: str
    rol: str
    acceso_general_sin_clave: Optional[bool] = False

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str
    username: str
    rol: str
    acceso_general_sin_clave: Optional[bool] = False


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
    pantallas: Optional[int] = 0

class PlanInternetResponse(PlanInternetBase):
    id: int
    class Config:
        from_attributes = True

class PlanInternetUpdate(BaseModel):
    nombre: Optional[str] = None
    megas: Optional[int] = None
    precio: Optional[float] = None
    pantallas: Optional[int] = None

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
    limite_ip: Optional[str] = None
    limite_device: Optional[str] = None
    limite_service_port: Optional[str] = None

class PuertoResponse(PuertoBase):
    id: int
    class Config:
        from_attributes = True

class PuertoUpdate(BaseModel):
    nombre: Optional[str] = None
    nodo_id: Optional[int] = None
    limite_ip: Optional[str] = None
    limite_device: Optional[str] = None
    limite_service_port: Optional[str] = None

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
    class Config:
        from_attributes = True

class ClienteExtraBase(BaseModel):
    cod: Optional[str] = None
    nombre_cliente: Optional[str] = None
    contacto: Optional[str] = None
    proveedor: Optional[str] = None
    usuario: Optional[str] = None
    contrasena: Optional[str] = None
    cuentas: Optional[str] = None
    mac_smart_one: Optional[str] = None
    observaciones: Optional[str] = None
    estado: Optional[str] = None
    valor: Optional[float] = 0.0
    activo: Optional[str] = "SI"
    saldo_pendiente: Optional[float] = 0.0
    total_pagado: Optional[float] = 0.0
    fecha_ingreso: Optional[str] = None

    # Campos mensuales (Opcionales todos)
    enero_factura: Optional[str] = None
    enero_fecha_a_pagar: Optional[str] = None
    enero_fecha_pago: Optional[str] = None
    enero_pago: Optional[float] = 0.0
    enero_banco: Optional[str] = None
    enero_cod: Optional[str] = None
    enero_saldo: Optional[float] = 0.0

    febrero_factura: Optional[str] = None
    febrero_fecha_a_pagar: Optional[str] = None
    febrero_fecha_pago: Optional[str] = None
    febrero_pago: Optional[float] = 0.0
    febrero_banco: Optional[str] = None
    febrero_cod: Optional[str] = None
    febrero_saldo: Optional[float] = 0.0

    marzo_factura: Optional[str] = None
    marzo_fecha_a_pagar: Optional[str] = None
    marzo_fecha_pago: Optional[str] = None
    marzo_pago: Optional[float] = 0.0
    marzo_banco: Optional[str] = None
    marzo_cod: Optional[str] = None
    marzo_saldo: Optional[float] = 0.0

    abril_factura: Optional[str] = None
    abril_fecha_a_pagar: Optional[str] = None
    abril_fecha_pago: Optional[str] = None
    abril_pago: Optional[float] = 0.0
    abril_banco: Optional[str] = None
    abril_cod: Optional[str] = None
    abril_saldo: Optional[float] = 0.0

    mayo_factura: Optional[str] = None
    mayo_fecha_a_pagar: Optional[str] = None
    mayo_fecha_pago: Optional[str] = None
    mayo_pago: Optional[float] = 0.0
    mayo_banco: Optional[str] = None
    mayo_cod: Optional[str] = None
    mayo_saldo: Optional[float] = 0.0

    junio_factura: Optional[str] = None
    junio_fecha_a_pagar: Optional[str] = None
    junio_fecha_pago: Optional[str] = None
    junio_pago: Optional[float] = 0.0
    junio_banco: Optional[str] = None
    junio_cod: Optional[str] = None
    junio_saldo: Optional[float] = 0.0

    julio_factura: Optional[str] = None
    julio_fecha_a_pagar: Optional[str] = None
    julio_fecha_pago: Optional[str] = None
    julio_pago: Optional[float] = 0.0
    julio_banco: Optional[str] = None
    julio_cod: Optional[str] = None
    julio_saldo: Optional[float] = 0.0

    agosto_factura: Optional[str] = None
    agosto_fecha_a_pagar: Optional[str] = None
    agosto_fecha_pago: Optional[str] = None
    agosto_pago: Optional[float] = 0.0
    agosto_banco: Optional[str] = None
    agosto_cod: Optional[str] = None
    agosto_saldo: Optional[float] = 0.0

    septiembre_factura: Optional[str] = None
    septiembre_fecha_a_pagar: Optional[str] = None
    septiembre_fecha_pago: Optional[str] = None
    septiembre_pago: Optional[float] = 0.0
    septiembre_banco: Optional[str] = None
    septiembre_cod: Optional[str] = None
    septiembre_saldo: Optional[float] = 0.0

    octubre_factura: Optional[str] = None
    octubre_fecha_a_pagar: Optional[str] = None
    octubre_fecha_pago: Optional[str] = None
    octubre_pago: Optional[float] = 0.0
    octubre_banco: Optional[str] = None
    octubre_cod: Optional[str] = None
    octubre_saldo: Optional[float] = 0.0

    noviembre_factura: Optional[str] = None
    noviembre_fecha_a_pagar: Optional[str] = None
    noviembre_fecha_pago: Optional[str] = None
    noviembre_pago: Optional[float] = 0.0
    noviembre_banco: Optional[str] = None
    noviembre_cod: Optional[str] = None
    noviembre_saldo: Optional[float] = 0.0

    diciembre_factura: Optional[str] = None
    diciembre_fecha_a_pagar: Optional[str] = None
    diciembre_fecha_pago: Optional[str] = None
    diciembre_pago: Optional[float] = 0.0
    diciembre_banco: Optional[str] = None
    diciembre_cod: Optional[str] = None
    diciembre_saldo: Optional[float] = 0.0

class ClienteExtraCreate(ClienteExtraBase):
    pass

class ClienteExtraUpdate(ClienteExtraBase):
    pass

class ClienteExtraResponse(ClienteExtraBase):
    id: int
    class Config:
        from_attributes = True

class PagoExtraCreate(BaseModel):
    monto: float
    metodo_pago: str
    mes_correspondiente: str
    referencia: Optional[str] = None
    factura: Optional[str] = None
    estado: Optional[str] = "Completado" # Completado, Pendiente_Verificacion

class HojaRutaBase(BaseModel):
    fecha: Optional[str] = None
    tecnico: Optional[str] = None
    hora: Optional[str] = None
    cliente_id: Optional[int] = None
    nombre_cliente: Optional[str] = None
    ubicacion_cliente: Optional[str] = None
    celular_cliente: Optional[str] = None
    ubicacion_caja: Optional[str] = None
    actividad: Optional[str] = None
    observacion: Optional[str] = None
    observacion_tecnico: Optional[str] = None
    parroquia: Optional[str] = None
    estado: Optional[str] = "Pendiente"

class HojaRutaCreate(HojaRutaBase):
    pass

class HojaRutaUpdate(BaseModel):
    fecha: Optional[str] = None
    tecnico: Optional[str] = None
    hora: Optional[str] = None
    cliente_id: Optional[int] = None
    nombre_cliente: Optional[str] = None
    ubicacion_cliente: Optional[str] = None
    celular_cliente: Optional[str] = None
    ubicacion_caja: Optional[str] = None
    actividad: Optional[str] = None
    observacion: Optional[str] = None
    observacion_tecnico: Optional[str] = None
    parroquia: Optional[str] = None
    estado: Optional[str] = None

class HojaRutaResponse(HojaRutaBase):
    id: int
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class TicketBase(BaseModel):
    titulo: str
    contenido: str
    estado: Optional[str] = "Pendiente"
    autor: Optional[str] = None

class TicketCreate(TicketBase):
    pass

class TicketUpdate(BaseModel):
    estado: Optional[str] = None
    contenido: Optional[str] = None

class TicketResponse(TicketBase):
    id: int
    fecha_creacion: datetime

    class Config:
        from_attributes = True

class CallCenterTicketBase(BaseModel):
    cliente_nombre: Optional[str] = None
    ip: Optional[str] = None
    direccion: Optional[str] = None
    telefono: Optional[str] = None
    estado: Optional[str] = "PENDIENTE"
    a_cargo: Optional[str] = None
    problema: Optional[str] = None
    observacion_revision: Optional[str] = None
    fecha_cambio_estado: Optional[str] = None

class CallCenterTicketCreate(CallCenterTicketBase):
    pass

class CallCenterTicketUpdate(CallCenterTicketBase):
    pass

class CallCenterTicketResponse(CallCenterTicketBase):
    id: int
    fecha_ingreso: datetime
    registrado_por: Optional[str] = None

    class Config:
        from_attributes = True

class AsistenciaCreate(BaseModel):
    ubicacion: str
    distancia_metros: float
    dispositivo_info: Optional[str] = None
    biometria_validada: bool = False
    hora_dispositivo: Optional[str] = None

class AsistenciaResponse(BaseModel):
    id: int
    usuario_id: int
    nombre_usuario: str
    fecha: str
    hora_entrada: str
    ubicacion: str
    distancia_metros: float
    hora_salida: Optional[str] = None
    ubicacion_salida: Optional[str] = None
    distancia_metros_salida: Optional[float] = None
    biometria_validada: bool
    biometria_salida_validada: Optional[bool] = False
    created_at: datetime

    class Config:
        from_attributes = True

class AsistenciaStatusResponse(BaseModel):
    ha_entrado: bool
    ha_salido: bool
    hora_entrada: Optional[str] = None
    asistencia_id: Optional[int] = None
    puede_salir: bool = True
    mensaje_restriccion: Optional[str] = None
    horario: Optional[dict] = None
    punches_today: Optional[List[dict]] = None


class HorarioEmpleadoBase(BaseModel):
    hora_entrada_1: str = "08:00"
    hora_salida_1: str = "13:00"
    hora_entrada_2: str = "14:00"
    hora_salida_2: str = "18:00"
    horas_diarias_esperadas: float = 8.0
    dias_laborables: str = "1,2,3,4,5"
    tolerancia_minutos: int = 15

class HorarioEmpleadoCreate(HorarioEmpleadoBase):
    usuario_id: int

class HorarioEmpleadoResponse(HorarioEmpleadoBase):
    id: int
    usuario_id: int
    nombre_usuario: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DetalleAsistenciaDia(BaseModel):
    fecha: str
    dia_nombre: str
    entrado: bool
    salido: bool
    hora_entrada: Optional[str] = None
    hora_salida: Optional[str] = None
    horas_trabajadas: float = 0.0
    horas_extras: float = 0.0
    atraso_minutos: int = 0
    estado: str # "Presente", "Atraso", "Incompleto", "Ausente", "Descanso"

class ResumenEmpleadoMensual(BaseModel):
    usuario_id: int
    nombre_usuario: str
    rol: str
    dias_trabajados: int
    horas_trabajadas: float
    horas_esperadas: float
    horas_extras: float
    atraso_minutos: int
    detalles_dias: List[DetalleAsistenciaDia] = []

class ReporteAsistenciaMensualResponse(BaseModel):
    mes: str
    total_empleados: int
    total_horas_trabajadas: float
    total_horas_extras: float
    resumen_empleados: List[ResumenEmpleadoMensual]

class TrucoDatesallRequest(BaseModel):
    username: str


class WhatsAppConfiguracionCreate(BaseModel):
    hora: str
    mensaje: str
    enviar_a_todos: Optional[bool] = True
    fecha: Optional[str] = None # Formato: YYYY-MM-DD
    recurrencia: Optional[str] = "diario" # diario, mensual, unico
    dia_mes: Optional[int] = None # 1 al 31 para mensual

class WhatsAppConfiguracionUpdate(BaseModel):
    hora: Optional[str] = None
    mensaje: Optional[str] = None
    activo: Optional[bool] = None
    enviar_a_todos: Optional[bool] = None
    fecha: Optional[str] = None # Formato: YYYY-MM-DD, o "vaciar" si se quiere eliminar
    recurrencia: Optional[str] = None # diario, mensual, unico
    dia_mes: Optional[int] = None # 1 al 31 para mensual

class WhatsAppManualSend(BaseModel):
    numero: str
    mensaje: str

class WhatsAppGlobalSend(BaseModel):
    mensaje: str
    nodo: Optional[str] = None

class WhatsAppAdministradorCreate(BaseModel):
    numero: str
    nombre: str
    permisos: Optional[str] = "admin_total"
    activo: Optional[bool] = True

class WhatsAppAdministradorUpdate(BaseModel):
    numero: Optional[str] = None
    nombre: Optional[str] = None
    permisos: Optional[str] = None
    activo: Optional[bool] = None

class WhatsAppAdministradorResponse(BaseModel):
    id: int
    numero: str
    nombre: str
    permisos: Optional[str] = "admin_total"
    activo: bool
    fecha_creacion: Optional[datetime] = None

    class Config:
        from_attributes = True


class CajaNapBase(BaseModel):
    nombre: str
    nodo_id: Optional[int] = None

class CajaNapResponse(CajaNapBase):
    id: int
    nodo_nombre: Optional[str] = None
    class Config:
        from_attributes = True

class CajaNapUpdate(BaseModel):
    nombre: Optional[str] = None
    nodo_id: Optional[int] = None
    class Config:
        from_attributes = True

class SmartParseRequest(BaseModel):
    text: str

class PagoAnularRequest(BaseModel):
    motivo_anulacion: str

class TurnoCajaCreate(BaseModel):
    efectivo_apertura: Optional[float] = 0.0
    pichincha_apertura: Optional[float] = 0.0
    jep_apertura: Optional[float] = 0.0

class TurnoCajaClose(BaseModel):
    efectivo_real: float
    pichincha_real: float
    jep_real: float
    observaciones: Optional[str] = None

class TurnoCajaResponse(BaseModel):
    id: int
    usuario_id: int
    fecha_apertura: datetime
    fecha_cierre: Optional[datetime] = None
    efectivo_apertura: float
    pichincha_apertura: float
    jep_apertura: float
    efectivo_cierre: float
    pichincha_cierre: float
    jep_cierre: float
    efectivo_real: float
    pichincha_real: float
    jep_real: float
    estado: str
    observaciones: Optional[str] = None

    class Config:
        from_attributes = True

class MovimientoInternoCreate(BaseModel):
    origen: str
    destino: str
    monto: float
    fecha: str
    observacion: Optional[str] = None

class MovimientoInternoUpdate(BaseModel):
    origen: Optional[str] = None
    destino: Optional[str] = None
    monto: Optional[float] = None
    fecha: Optional[str] = None
    observacion: Optional[str] = None

class MovimientoInternoOut(BaseModel):
    id: int
    origen: str
    destino: str
    monto: float
    fecha: str
    mes: str
    observacion: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True



