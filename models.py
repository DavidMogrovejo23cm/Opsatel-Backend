from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Numeric

from sqlalchemy.orm import relationship

from database import Base

import datetime



class Cliente(Base):

    __tablename__ = "hoja_de_c__lculo_sin_t__tulo"



    id = Column("NUMERO", Integer, primary_key=True, index=True)

    nombre = Column("NOMBRE", String(255))

    cedula = Column("CEDULA", String(20))

    celular = Column("CELULAR", String(20))

    correo = Column("CORREO", String(100))

    direccion = Column("DIRECCION", String(255))

    parroquia = Column("PARROQUIA", String(100))

    plan = Column("PLAN", String(100))

    fecha_firma = Column("FECHA_FIRMA", String(50))

    estado = Column("ESTADO", String(50), default="Pendiente")

    

                              

    puerto = Column("PUERTO", String(50))

    ont = Column("ONT", String(50))

    servicio = Column("SERVICIO", String(50))

    breach = Column("BREACH", String(50))

    id_port = Column("ID_PORT", String(50))

    service_port = Column("SERVICE PORT", String(50))

    ip = Column("IP", String(50))

    dispositivo = Column("DISPOSITIVO", String(50))

    potencia = Column("POTENCIA", String(50))

    nap = Column("NAP", String(50))

    ubicacion = Column("UBICACION", String(255))

    tecnico = Column("TECNICO", String(100))

    activador = Column("ACTIVADOR", String(100))

    red = Column("RED", String(100))

    clave = Column("CLAVE", String(100))



                              

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

    saldo = Column("SALDO", Numeric(precision=10, scale=2), default=0.00)



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



    cliente = relationship("Cliente", back_populates="pagos")

