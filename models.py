from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Numeric, Boolean

from sqlalchemy.orm import relationship

from database import Base

import datetime



class Cliente(Base):

    __tablename__ = "hoja_de_c__lculo_sin_t__tulo"



    id = Column("NUMERO", Integer, primary_key=True, index=True)

    nombre = Column("NOMBRE", String(255))

    cedula = Column("CEDULA", String(20))
    cedula_tipo = Column("CEDULA_TIPO", String(50))
    cedula_frontal = Column("CEDULA_FRONTAL", String(255))
    cedula_posterior = Column("CEDULA_POSTERIOR", String(255))

    celular = Column("CELULAR", String(20))

    correo = Column("CORREO", String(100))

    direccion = Column("DIRECCION", String(255))

    nodo = Column("NODO", String(100))
    parroquia = Column("PARROQUIA", String(100))

    plan = Column("PLAN", String(100))

    fecha_firma = Column("FECHA_FIRMA", String(50))

    estado = Column("ESTADO", String(50), default="Pendiente")

    

                              

    puerto = Column("PUERTO", String(100))

    ont = Column("ONT", String(2000))

    servicio = Column("SERVICIO", String(2000))

    breach = Column("BREACH", String(2000))

    id_port = Column("ID_PORT", String(200))

    service_port = Column("SERVICE PORT", String(2000))

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

    comentarios = Column("COMENTARIOS", String(500))
    observaciones = Column("OBSERVACIONES", String(500))
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
    iptv_outputs = Column("IPTV_OUTPUTS", String(1255))
    iptv_notes = Column("IPTV_NOTES", String(500))
    iptv_member_id = Column("IPTV_MEMBER_ID", Integer, default=1)

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




    cliente = relationship("Cliente", back_populates="pagos")



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
    observaciones = Column(String(500))
    estado = Column(String(50)) # FIJO, IRREGULAR, SEMIFIJO, EXTERNO
    valor = Column(Numeric(precision=10, scale=2), default=0.00)
    activo = Column(String(10), default="SI")
    
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
    
    cliente = relationship("ClienteExtra", back_populates="pagos")

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
    observacion = Column(String(500))
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
    fecha_creacion = Column(DateTime, default=datetime.utcnow)
