# pyrefly: ignore [missing-import]
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Numeric, Boolean, Text, JSON, BigInteger, Enum
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import relationship
from database import Base
import datetime
import enum



class Cliente(Base):

    __tablename__ = "hoja_de_c__lculo_sin_t__tulo"



    id = Column("NUMERO", Integer, primary_key=True, index=True)

    nombre = Column("NOMBRE", String(255))

    cedula = Column("CEDULA", String(100))
    cedula_tipo = Column("CEDULA_TIPO", String(100))
    cedula_frontal = Column("CEDULA_FRONTAL", Text)
    cedula_posterior = Column("CEDULA_POSTERIOR", Text)

    celular = Column("CELULAR", String(255))

    correo = Column("CORREO", String(255))

    direccion = Column("DIRECCION", Text)

    nodo = Column("NODO", String(255))
    parroquia = Column("PARROQUIA", String(255))

    plan = Column("PLAN", String(255))

    fecha_firma = Column("FECHA_FIRMA", String(50))

    estado = Column("ESTADO", String(50), default="Activo")

    

                              

    puerto = Column("PUERTO", String(100))

    ont = Column("ONT", Text)

    servicio = Column("SERVICIO", Text)

    breach = Column("BREACH", Text)

    id_port = Column("ID_PORT", String(200))

    service_port = Column("SERVICE PORT", Text)

    ip = Column("IP", String(50))

    dispositivo = Column("DISPOSITIVO", String(50))

    potencia = Column("POTENCIA", String(50))

    nap = Column("NAP", String(50))

    ubicacion = Column("UBICACION", String(255))

    tecnico = Column("TECNICO", String(100))

    activador = Column("ACTIVADOR", String(100))

    red = Column("RED", String(100))

    clave = Column("CLAVE", String(100))
    mac = Column("MAC", String(50))
    instalation_date = Column("INSTALATION_DATE", String(50))




                              

    tiempo = Column("TIEMPO", String(50))

    arrienda = Column("ARRIENDA", String(50))

    cuenta = Column("CUENTA", String(50))

    facturas = Column("FACTURAS", String(100))

    internet_payment = Column("INTERNET PAYMENT", String(100))

    app = Column("APP", String(100))

    payment_date = Column("PAYMENT DATE", String(50))

    client_payment_date = Column("CLIENT PAYMENT DATE", String(50))

    bank = Column("BANK", String(50))

    cod = Column("COD", String(50))

    plus = Column("PLUS", String(50))

    bank_plus = Column("BANK_PLUS", String(50))

    adicional = Column("ADICIONAL", String(255))

    plus_pagado = Column("PLUS_PAGADO", Numeric(precision=10, scale=2), default=0.00)
    adicional_pagado = Column("ADICIONAL_PAGADO", Numeric(precision=10, scale=2), default=0.00)

    comentarios = Column("COMENTARIOS", Text)
    observaciones = Column("OBSERVACIONES", Text)
    notas_pago = Column("NOTAS_PAGO", Text)
    tercera_edad = Column("TERCERA_EDAD", Boolean, default=False)
    precio_plan_especial = Column("PRECIO_PLAN_ESPECIAL", Numeric(precision=10, scale=2), default=0.00)
    pago_mensual = Column("PAGO_MENSUAL", Numeric(precision=10, scale=2), default=0.00)
    total_pago = Column("TOTAL_PAGO", Numeric(precision=10, scale=2), default=0.00)
    saldo = Column("SALDO", Numeric(precision=10, scale=2), default=0.00)
    # Campos IPTV (Nuevo req v1.3)
    iptv_activar = Column("IPTV_ACTIVAR", Boolean, default=False)
    iptv_user = Column("IPTV_USER", String(255))
    iptv_pass = Column("IPTV_PASS", String(255))
    iptv_bouquets = Column("IPTV_BOUQUETS", String(255))
    iptv_exp_date = Column("IPTV_EXP_DATE", String(100))
    iptv_max_conn = Column("IPTV_MAX_CONN", Integer, default=0)
    iptv_outputs = Column("IPTV_OUTPUTS", Text)
    iptv_notes = Column("IPTV_NOTES", Text)
    iptv_member_id = Column("IPTV_MEMBER_ID", Integer, default=1)
    tv_tipo = Column("TV_TIPO", String(50), default="Ninguno")
    cortesia_total = Column("CORTESIA_TOTAL", Boolean, default=False)
    fecha_prorroga = Column("FECHA_PRORROGA", String(50), nullable=True)

    pagos = relationship("Pago", back_populates="cliente")



class Pago(Base):

    __tablename__ = "historial_pagos"



    id = Column(Integer, primary_key=True, index=True)

    cliente_id = Column(Integer, ForeignKey("hoja_de_c__lculo_sin_t__tulo.NUMERO"))

    monto = Column(Numeric(precision=10, scale=2))

    fecha_pago = Column(DateTime, default=datetime.datetime.utcnow)

    metodo_pago = Column(String(50))

    mes_correspondiente = Column(String(20))

    referencia = Column(String(100))
    monto_internet = Column(Numeric(precision=10, scale=2), default=0.00)
    monto_plus = Column(Numeric(precision=10, scale=2), default=0.00)
    monto_adicional = Column(Numeric(precision=10, scale=2), default=0.00)

    # Contabilidad y Auditoría avanzada
    anulado = Column(Boolean, default=False)
    fecha_anulacion = Column(DateTime, nullable=True)
    anulado_por = Column(String(100), nullable=True)
    motivo_anulacion = Column(Text, nullable=True)
    estado = Column(String(50), default="Completado") # Completado, Pendiente_Verificacion
    turnocaja_id = Column(Integer, ForeignKey("turnos_cajas.id"), nullable=True)

    cliente = relationship("Cliente", back_populates="pagos")
    turno = relationship("TurnoCaja", back_populates="pagos")



class ReporteMensual(Base):
    __tablename__ = 'reportes_mensuales'
    id = Column(Integer, primary_key=True, index=True)
    mes_anio = Column(String(20))
    fecha_generacion = Column(DateTime, default=datetime.datetime.utcnow)
    archivo_ruta_excel = Column(String(255))

class Usuario(Base):
    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True)
    password_hash = Column(String(255))
    rol = Column(String(20)) # administrador, secretario, tecnico

class Nodo(Base):
    __tablename__ = "nodos"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), unique=True, index=True)
    base_ip = Column(String(50), default="172.16")

class PlanInternet(Base):
    __tablename__ = "planes_internet"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), unique=True, index=True) 
    megas = Column(Integer, default=100)
    precio = Column(Numeric(precision=10, scale=2), default=0.00) 
    pantallas = Column(Integer, default=1) 

class Banco(Base):
    __tablename__ = "bancos"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), unique=True, index=True)

class Puerto(Base):
    __tablename__ = "puertos"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100)) 
    nodo_id = Column(Integer, ForeignKey("nodos.id"))
    nodo = relationship("Nodo", backref="puertos")
    limite_ip = Column(String(100), default="2 al 129")
    limite_device = Column(String(100), default="0 al 127")
    limite_service_port = Column(String(100), default="0 al 127")

class FinanzasBase(Base):
    __tablename__ = "finanzas_base"
    id = Column(Integer, primary_key=True, index=True)
    caja_chica = Column(Numeric(precision=10, scale=2), default=0.00)
    pichincha = Column(Numeric(precision=10, scale=2), default=0.00)
    jep = Column(Numeric(precision=10, scale=2), default=0.00)

class Parroquia(Base):
    __tablename__ = "parroquias"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), unique=True, index=True)

    class Config:
        from_attributes = True

class ClienteExtra(Base):
    __tablename__ = "clientes_extras"

    id = Column(Integer, primary_key=True, index=True)
    cod = Column(String(50))
    nombre_cliente = Column(String(255))
    contacto = Column(String(255))
    proveedor = Column(String(255))
    usuario = Column(String(255))
    contrasena = Column(String(255))
    cuentas = Column(String(50))
    mac_smart_one = Column(String(100))
    observaciones = Column(Text)
    estado = Column(String(50)) # FIJO, IRREGULAR, SEMIFIJO, EXTERNO
    valor = Column(Numeric(precision=10, scale=2), default=0.00)
    activo = Column(String(10), default="SI")
    fecha_ingreso = Column(String(50)) # Formato YYYY-MM-DD
    
    # Pendientes y saldos globales para el apartado de pagos
    saldo_pendiente = Column(Numeric(precision=10, scale=2), default=0.00)
    total_pagado = Column(Numeric(precision=10, scale=2), default=0.00)

    # Definir columnas para los 12 meses
    # Enero
    enero_factura = Column(String(100))
    enero_fecha_a_pagar = Column(String(50))
    enero_fecha_pago = Column(String(50))
    enero_pago = Column(Numeric(precision=10, scale=2), default=0.00)
    enero_banco = Column(String(100))
    enero_cod = Column(String(100))
    enero_saldo = Column(Numeric(precision=10, scale=2), default=0.00)

    # Febrero
    febrero_factura = Column(String(100))
    febrero_fecha_a_pagar = Column(String(50))
    febrero_fecha_pago = Column(String(50))
    febrero_pago = Column(Numeric(precision=10, scale=2), default=0.00)
    febrero_banco = Column(String(100))
    febrero_cod = Column(String(100))
    febrero_saldo = Column(Numeric(precision=10, scale=2), default=0.00)

    # Marzo
    marzo_factura = Column(String(100))
    marzo_fecha_a_pagar = Column(String(50))
    marzo_fecha_pago = Column(String(50))
    marzo_pago = Column(Numeric(precision=10, scale=2), default=0.00)
    marzo_banco = Column(String(100))
    marzo_cod = Column(String(100))
    marzo_saldo = Column(Numeric(precision=10, scale=2), default=0.00)

    # Abril
    abril_factura = Column(String(100))
    abril_fecha_a_pagar = Column(String(50))
    abril_fecha_pago = Column(String(50))
    abril_pago = Column(Numeric(precision=10, scale=2), default=0.00)
    abril_banco = Column(String(100))
    abril_cod = Column(String(100))
    abril_saldo = Column(Numeric(precision=10, scale=2), default=0.00)

    # Mayo
    mayo_factura = Column(String(100))
    mayo_fecha_a_pagar = Column(String(50))
    mayo_fecha_pago = Column(String(50))
    mayo_pago = Column(Numeric(precision=10, scale=2), default=0.00)
    mayo_banco = Column(String(100))
    mayo_cod = Column(String(100))
    mayo_saldo = Column(Numeric(precision=10, scale=2), default=0.00)

    # Junio
    junio_factura = Column(String(100))
    junio_fecha_a_pagar = Column(String(50))
    junio_fecha_pago = Column(String(50))
    junio_pago = Column(Numeric(precision=10, scale=2), default=0.00)
    junio_banco = Column(String(100))
    junio_cod = Column(String(100))
    junio_saldo = Column(Numeric(precision=10, scale=2), default=0.00)

    # Julio
    julio_factura = Column(String(100))
    julio_fecha_a_pagar = Column(String(50))
    julio_fecha_pago = Column(String(50))
    julio_pago = Column(Numeric(precision=10, scale=2), default=0.00)
    julio_banco = Column(String(100))
    julio_cod = Column(String(100))
    julio_saldo = Column(Numeric(precision=10, scale=2), default=0.00)

    # Agosto
    agosto_factura = Column(String(100))
    agosto_fecha_a_pagar = Column(String(50))
    agosto_fecha_pago = Column(String(50))
    agosto_pago = Column(Numeric(precision=10, scale=2), default=0.00)
    agosto_banco = Column(String(100))
    agosto_cod = Column(String(100))
    agosto_saldo = Column(Numeric(precision=10, scale=2), default=0.00)

    # Septiembre
    septiembre_factura = Column(String(100))
    septiembre_fecha_a_pagar = Column(String(50))
    septiembre_fecha_pago = Column(String(50))
    septiembre_pago = Column(Numeric(precision=10, scale=2), default=0.00)
    septiembre_banco = Column(String(100))
    septiembre_cod = Column(String(100))
    septiembre_saldo = Column(Numeric(precision=10, scale=2), default=0.00)

    # Octubre
    octubre_factura = Column(String(100))
    octubre_fecha_a_pagar = Column(String(50))
    octubre_fecha_pago = Column(String(50))
    octubre_pago = Column(Numeric(precision=10, scale=2), default=0.00)
    octubre_banco = Column(String(100))
    octubre_cod = Column(String(100))
    octubre_saldo = Column(Numeric(precision=10, scale=2), default=0.00)

    # Noviembre
    noviembre_factura = Column(String(100))
    noviembre_fecha_a_pagar = Column(String(50))
    noviembre_fecha_pago = Column(String(50))
    noviembre_pago = Column(Numeric(precision=10, scale=2), default=0.00)
    noviembre_banco = Column(String(100))
    noviembre_cod = Column(String(100))
    noviembre_saldo = Column(Numeric(precision=10, scale=2), default=0.00)

    # Diciembre
    diciembre_factura = Column(String(100))
    diciembre_fecha_a_pagar = Column(String(50))
    diciembre_fecha_pago = Column(String(50))
    diciembre_pago = Column(Numeric(precision=10, scale=2), default=0.00)
    diciembre_banco = Column(String(100))
    diciembre_cod = Column(String(100))
    diciembre_saldo = Column(Numeric(precision=10, scale=2), default=0.00)

    pagos = relationship("PagoExtra", back_populates="cliente")

class PagoExtra(Base):
    __tablename__ = "historial_pagos_extras"

    id = Column(Integer, primary_key=True, index=True)
    cliente_id = Column(Integer, ForeignKey("clientes_extras.id"))
    monto = Column(Numeric(precision=10, scale=2))
    fecha_pago = Column(DateTime, default=datetime.datetime.utcnow)
    metodo_pago = Column(String(50))
    mes_correspondiente = Column(String(20)) # Enero, Febrero, etc.
    referencia = Column(String(100))
    factura = Column(String(100))
    
    # Contabilidad y Auditoría avanzada
    anulado = Column(Boolean, default=False)
    fecha_anulacion = Column(DateTime, nullable=True)
    anulado_por = Column(String(100), nullable=True)
    motivo_anulacion = Column(Text, nullable=True)
    estado = Column(String(50), default="Completado") # Completado, Pendiente_Verificacion
    turnocaja_id = Column(Integer, ForeignKey("turnos_cajas.id"), nullable=True)

    cliente = relationship("ClienteExtra", back_populates="pagos")
    turno = relationship("TurnoCaja", back_populates="pagos_extras")

class HojaRuta(Base):
    __tablename__ = "hoja_ruta"

    id = Column(Integer, primary_key=True, index=True)
    fecha = Column(String(50))
    tecnico = Column(String(100))
    hora = Column(String(50))
    cliente_id = Column(Integer, ForeignKey("hoja_de_c__lculo_sin_t__tulo.NUMERO"))
    nombre_cliente = Column(String(255))
    ubicacion_cliente = Column(String(255))
    celular_cliente = Column(String(255))
    ubicacion_caja = Column(String(255))
    actividad = Column(String(255))
    observacion = Column(String(2000))
    observacion_tecnico = Column(String(2000))
    parroquia = Column(String(100))
    estado = Column(String(50), default="Pendiente") # Pendiente, Realizado, Cancelado
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    cliente_ref = relationship("Cliente")

class Ticket(Base):
    __tablename__ = "tickets_desarrollo"
    id = Column(Integer, primary_key=True, index=True)
    titulo = Column(String(255), nullable=False)
    contenido = Column(Text, nullable=False) # Soporta texto largo y fotos base64
    estado = Column(String(50), default="Pendiente")
    autor = Column(String(100), nullable=False)
    fecha_creacion = Column(DateTime, default=datetime.datetime.utcnow)

class CallCenterTicket(Base):
    __tablename__ = "call_center_tickets"
    id = Column(Integer, primary_key=True, index=True)
    cliente_nombre = Column(String(255))
    fecha_ingreso = Column(DateTime, default=datetime.datetime.utcnow)
    ip = Column(String(50))
    direccion = Column(String(255))
    telefono = Column(String(255))
    registrado_por = Column(String(100))
    estado = Column(String(50), default="PENDIENTE")
    a_cargo = Column(String(100))
    problema = Column(Text)
    observacion_revision = Column(Text)
    fecha_cambio_estado = Column(String(50))

class Egreso(Base):
    """Registro de egresos/gastos operacionales para el módulo de Balance."""
    __tablename__ = "egresos_balance"
    id = Column(Integer, primary_key=True, index=True)
    descripcion = Column(String(255), nullable=False)
    categoria = Column(String(100), default="operacional")  # operacional, proyecto, nomina, otro
    monto = Column(Numeric(precision=10, scale=2), default=0.00)
    subcategoria = Column(String(150))  # VIATICOS, CONSTRUCCION, COMPRAS, etc.
    fecha = Column(String(50))          # YYYY-MM-DD
    mes = Column(String(20))            # YYYY-MM  → para filtrado rápido
    metodo_pago = Column(String(100), default="Efectivo")
    notas = Column(String(255))


# ============================================================================
# OLT PROVISIONING MODELS
# ============================================================================

class OLTConfig(Base):
    """Configuración de OLTs (IP, credenciales, etc.)"""
    __tablename__ = "olt_config"
    
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), unique=True, nullable=False, index=True)
    host = Column(String(50), nullable=False)
    port = Column(Integer, default=23)
    username = Column(String(100), nullable=False)
    password = Column(String(100), nullable=False)
    device_type = Column(String(50), default="huawei_olt")
    
    connection_timeout = Column(Integer, default=30)
    command_timeout = Column(Integer, default=30)
    max_retries = Column(Integer, default=3)
    retry_backoff_base = Column(Integer, default=1)
    
    active = Column(Boolean, default=True, index=True)
    nodo_asociado = Column(String(100), index=True)
    
    # Credenciales MikroTik (RouterOS API) asociado a este nodo
    mikrotik_host     = Column(String(50),  nullable=True)
    mikrotik_port     = Column(Integer,     nullable=True, default=8728)
    mikrotik_username = Column(String(100), nullable=True)
    mikrotik_password = Column(String(100), nullable=True)

    # Relación con LibreQoS Server
    libreqos_server_id = Column(Integer, ForeignKey("libreqos_servers.id"), nullable=True)
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    created_by = Column(String(100))
    updated_by = Column(String(100))
    
    # Relaciones
    tasks = relationship("OLTTask", back_populates="olt_config")


class OLTTask(Base):
    """Cola de tareas para aprovisionamiento OLT"""
    __tablename__ = "olt_tasks"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    cliente_id = Column(Integer, ForeignKey("hoja_de_c__lculo_sin_t__tulo.NUMERO"), nullable=False, index=True)
    olt_id = Column(Integer, ForeignKey("olt_config.id"), nullable=False, index=True)
    
    action = Column(String(50), nullable=False, index=True)
    payload = Column(JSON, nullable=False)
    
    status = Column(String(50), default="pending", index=True, nullable=False)
    priority = Column(Integer, default=0)
    retry_count = Column(Integer, default=0)
    
    response = Column(Text)
    response_json = Column(JSON)
    error_message = Column(Text)
    error_code = Column(String(50))
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    created_by = Column(String(100))
    processed_by = Column(String(100))
    bulk_id = Column(String(100), nullable=True, index=True)
    
    olt_config = relationship("OLTConfig", back_populates="tasks")
    logs = relationship("OLTTaskLog", back_populates="task")


class OLTTaskLog(Base):
    """Auditoría detallada de cada intento de tarea"""
    __tablename__ = "olt_task_logs"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    task_id = Column(BigInteger, ForeignKey("olt_tasks.id"), nullable=False, index=True)
    attempt = Column(Integer, nullable=False)
    
    status_before = Column(String(50))
    status_after = Column(String(50))
    
    command_sent = Column(Text)
    raw_response = Column(Text)
    
    success = Column(Boolean)
    error_message = Column(Text)
    
    duration_ms = Column(Integer)
    connection_time_ms = Column(Integer)
    
    log_message = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    
    task = relationship("OLTTask", back_populates="logs")


class OLTPowerCheck(Base):
    """Histórico de verificaciones de potencia"""
    __tablename__ = "olt_power_checks"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    cliente_id = Column(Integer, ForeignKey("hoja_de_c__lculo_sin_t__tulo.NUMERO"), nullable=False, index=True)
    task_id = Column(BigInteger, ForeignKey("olt_tasks.id"), nullable=True)
    
    rx_power = Column(Numeric(5, 2))
    rx_power_status = Column(String(50))
    threshold_min = Column(Numeric(5, 2))
    
    ont_id = Column(Integer)
    gpon_port = Column(String(20))
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    notas = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Proyecto(Base):
    """Registro de proyectos e inversiones para el módulo de Balance."""
    __tablename__ = "proyectos_balance"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(255), nullable=False)
    descripcion = Column(Text)
    monto_total = Column(Numeric(precision=10, scale=2), default=0.00)
    monto_invertido = Column(Numeric(precision=10, scale=2), default=0.00)
    estado = Column(String(50), default="En progreso")  # En progreso, Completado, Pausado
    fecha_inicio = Column(String(50))
    fecha_fin = Column(String(50))
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class ProyectoPago(Base):
    """Cuotas/pagos realizados al proyecto (tabla de aportes)."""
    __tablename__ = "proyecto_pagos"
    id = Column(Integer, primary_key=True, index=True)
    proyecto_id = Column(Integer, ForeignKey("proyectos_balance.id", ondelete="CASCADE"))
    item = Column(Integer, default=1)
    descripcion = Column(String(255))
    fecha = Column(String(50))
    tipo_pago = Column(String(100), default="Pichincha")
    valor = Column(Numeric(precision=10, scale=2), default=0.00)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class GastoProyecto(Base):
    """Gastos generales internos de un proyecto, agrupados por subcategoría."""
    __tablename__ = "gastos_proyecto"
    id = Column(Integer, primary_key=True, index=True)
    proyecto_id = Column(Integer, ForeignKey("proyectos_balance.id", ondelete="CASCADE"))
    subcategoria = Column(String(150))  # VIATICOS, CONSTRUCCION, COMPRAS, HERRAJERIA…
    item = Column(Integer, default=1)
    descripcion = Column(String(255))
    fecha = Column(String(50))
    tipo_pago = Column(String(150), default="Pichincha")
    valor = Column(Numeric(precision=10, scale=2), default=0.00)
    pendiente = Column(Boolean, default=False)  # True = Pendiente de pago
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Colchon(Base):
    """Modelo para el 'Colchón' (Fondo de reserva/ahorro) solicitado por el usuario."""
    __tablename__ = "colchon_balance"
    id = Column(Integer, primary_key=True, index=True)
    descripcion = Column(String(255), nullable=False)
    monto = Column(Numeric(precision=10, scale=2), default=0.00)
    fecha = Column(String(50))  # YYYY-MM-DD
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class GastoFijo(Base):
    """Gastos fijos recurrentes que se incluyen automáticamente cada mes en los egresos."""
    __tablename__ = "gastos_fijos_balance"
    id = Column(Integer, primary_key=True, index=True)
    descripcion = Column(String(255), nullable=False)
    monto = Column(Numeric(precision=10, scale=2), default=0.00)
    categoria = Column(String(100), default="operacional")  # operacional, nomina, otro
    metodo_pago = Column(String(100), default="Efectivo")
    activo = Column(Boolean, default=True)  # Si False, no se suma ese mes
    notas = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Asistencia(Base):
    __tablename__ = "asistencias"
    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    nombre_usuario = Column(String(100))
    fecha = Column(String(50)) # YYYY-MM-DD
    hora_entrada = Column(String(50)) # HH:MM:SS
    ubicacion = Column(String(255)) # "lat, lng"
    distancia_metros = Column(Float)
    
    # Salida
    hora_salida = Column(String(50)) # HH:MM:SS
    ubicacion_salida = Column(String(255)) # "lat, lng"
    distancia_metros_salida = Column(Float)
    biometria_salida_validada = Column(Boolean, default=False)
    
    dispositivo_info = Column(String(255))
    biometria_validada = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    usuario = relationship("Usuario")


class HorarioEmpleado(Base):
    __tablename__ = "horarios_empleados"
    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), unique=True, nullable=False)
    hora_entrada_1 = Column(String(10), default="08:00")
    hora_salida_1 = Column(String(10), default="13:00")
    hora_entrada_2 = Column(String(10), default="14:00")
    hora_salida_2 = Column(String(10), default="18:00")
    horas_diarias_esperadas = Column(Float, default=8.0)
    dias_laborables = Column(String(50), default="1,2,3,4,5")
    tolerancia_minutos = Column(Integer, default=15)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    usuario = relationship("Usuario", backref="horario")


class WhatsAppHistorial(Base):
    """Historial de mensajes WhatsApp enviados"""
    __tablename__ = "whatsapp_historial"
    id = Column(Integer, primary_key=True, index=True)
    numero_destino = Column(String(50), nullable=False)  # +593XXXXXXXXX
    mensaje = Column(Text, nullable=False)
    tipo_envio = Column(String(50), default="manual")  # manual, automatico
    estado = Column(String(50), default="enviado")  # enviado, fallido, pendiente
    fecha_envio = Column(String(50))  # YYYY-MM-DD HH:MM:SS
    fecha_creacion = Column(DateTime, default=datetime.datetime.utcnow)

class WhatsAppConfiguracion(Base):
    """Configuración de envío automático de WhatsApp"""
    __tablename__ = "whatsapp_configuracion"
    id = Column(Integer, primary_key=True, index=True)
    hora_programada = Column(String(10), nullable=False)  # HH:MM
    mensaje_programado = Column(Text, nullable=False)
    activo = Column(Boolean, default=True)
    enviar_a_todos = Column(Boolean, default=True)  # True = a todos clientes
    fecha_programada = Column(DateTime, nullable=True)  # Fecha y hora exacta (opcional)
    recurrencia = Column(String(50), default="diario")  # diario, mensual, unico
    job_id = Column(String(200), nullable=True)  # Scheduler job id si es envío puntual
    fecha_creacion = Column(DateTime, default=datetime.datetime.utcnow)

class WhatsAppAdministrador(Base):
    """Números de teléfono autorizados como Administradores en WhatsApp"""
    __tablename__ = "whatsapp_administradores"
    id = Column(Integer, primary_key=True, index=True)
    numero = Column(String(50), unique=True, index=True, nullable=False)  # Número de teléfono limpio (ej. 593982520824 o 0982520824)
    nombre = Column(String(100), nullable=False)
    permisos = Column(String(100), default="admin_total")
    activo = Column(Boolean, default=True)
    fecha_creacion = Column(DateTime, default=datetime.datetime.utcnow)


class CajaNap(Base):
    __tablename__ = "cajas_nap"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), unique=True, index=True)
    nodo_id = Column(Integer, ForeignKey("nodos.id"), nullable=True)

class ClienteEliminado(Base):
    """Historial de auditoría para clientes eliminados"""
    __tablename__ = "clientes_eliminados"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    cliente_id = Column(Integer, index=True)
    nombre = Column(String(255))
    cedula = Column(String(100))
    plan = Column(String(255))
    ip = Column(String(50))
    mac = Column(String(50))
    deleted_at = Column(DateTime, default=datetime.datetime.utcnow)
    deleted_by = Column(String(100))
    estado_olt = Column(String(50))      # "ELIMINADO", "OMITIDO", "ERROR"
    estado_xui = Column(String(50))      # "ELIMINADO", "OMITIDO", "ERROR"
    estado_mikrotik = Column(String(50)) # "ELIMINADO", "OMITIDO", "ERROR"
    estado_libreqos = Column(String(50)) # "ELIMINADO", "OMITIDO", "ERROR"
    estado_db = Column(String(50))       # "ELIMINADO", "ERROR"
    datos_cliente = Column(JSON)         # Fotografía completa (snapshot)
    detalles_error = Column(Text)        # Logs o detalles de error si los hay

class TurnoCaja(Base):
    __tablename__ = "turnos_cajas"
    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    fecha_apertura = Column(DateTime, default=datetime.datetime.utcnow)
    fecha_cierre = Column(DateTime, nullable=True)
    
    # Apertura
    efectivo_apertura = Column(Numeric(precision=10, scale=2), default=0.00)
    pichincha_apertura = Column(Numeric(precision=10, scale=2), default=0.00)
    jep_apertura = Column(Numeric(precision=10, scale=2), default=0.00)
    
    # Cierre (calculados)
    efectivo_cierre = Column(Numeric(precision=10, scale=2), default=0.00)
    pichincha_cierre = Column(Numeric(precision=10, scale=2), default=0.00)
    jep_cierre = Column(Numeric(precision=10, scale=2), default=0.00)
    
    # Conteo Físico
    efectivo_real = Column(Numeric(precision=10, scale=2), default=0.00)
    pichincha_real = Column(Numeric(precision=10, scale=2), default=0.00)
    jep_real = Column(Numeric(precision=10, scale=2), default=0.00)
    
    estado = Column(String(20), default="Abierto") # "Abierto", "Cerrado"
    observaciones = Column(Text, nullable=True)
    
    usuario = relationship("Usuario", backref="turnos")
    pagos = relationship("Pago", back_populates="turno")
    pagos_extras = relationship("PagoExtra", back_populates="turno")

class LogFacturacion(Base):
    __tablename__ = "log_facturacion"
    id = Column(Integer, primary_key=True, index=True)
    periodo_mes = Column(String(20), unique=True, index=True) # YYYY-MM
    fecha_ejecucion = Column(DateTime, default=datetime.datetime.utcnow)
    estado = Column(String(50), default="Completado")
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)