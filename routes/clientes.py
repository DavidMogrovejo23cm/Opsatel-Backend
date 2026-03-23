from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile
import os
import shutil
from sqlalchemy.orm import Session
from typing import List
import models, schemas
from database import get_db
from datetime import datetime
from .auth import get_current_user, require_role

router = APIRouter(prefix="/clientes", tags=["clientes"])

import traceback
from datetime import datetime
from config_manager import get_config, save_config

def try_float(val):
    try:
        return float(str(val or 0).replace(',', '.').strip()) if val else 0.0
    except:
        return 0.0


def sync_cliente_balances(cliente: models.Cliente, db: Session = None):
    tarifa = 20.00 # Default fallback
    if db:
        plan_info = db.query(models.PlanInternet).filter(models.PlanInternet.nombre == cliente.plan).first()
        if plan_info:
            tarifa = float(plan_info.precio or 0)
        
    plus = try_float(cliente.plus)
    adicional = try_float(cliente.adicional)

    plus_p = float(cliente.plus_pagado or 0)
    adic_p = float(cliente.adicional_pagado or 0)
        
    cliente.total_pago = float(tarifa) + plus + adicional + plus_p + adic_p
    pago_m = float(cliente.pago_mensual or 0.0)
    cliente.saldo = float(cliente.total_pago) - pago_m

# El sistema ahora utiliza exclusivamente la tabla 'planes_internet' de la base de datos 
# para obtener los precios vigentes, permitiendo configurarlos desde el panel administrativo.

@router.get("/")
def listar_clientes(db: Session = Depends(get_db)):
    try:
        data = db.query(models.Cliente).all()
        return data
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/dashboard-stats")
def get_dashboard_stats(db: Session = Depends(get_db)):
    pagos = db.query(models.Pago).all()
    
    # Inicializamos contadores
    internet = {"Efectivo": 0.0, "Pichincha": 0.0, "JEP": 0.0}
    plus = {"Efectivo": 0.0, "Pichincha": 0.0}
    
    for p in pagos:
        metodo = (p.metodo_pago or "").upper()
        # Intentamos obtener valores flotantes
        try:
            m_total = float(p.monto or 0)
            m_internet = float(p.monto_internet or 0)
            m_plus = float(p.monto_plus or 0)
        except:
            continue
            
        # Reglas Internet
        if "JEP" in metodo:
            internet["JEP"] += m_total
        elif "PICHINCHA" in metodo:
            internet["Pichincha"] += m_internet
        elif "EFECTIVO" in metodo:
            internet["Efectivo"] += m_internet
        else: # Si no especifica, asumimos internet efectivo para no perder el registro
            internet["Efectivo"] += m_internet
            
        # Reglas Plus
        if "PICHINCHA" in metodo:
            plus["Pichincha"] += m_plus
        elif "JEP" not in metodo:
            plus["Efectivo"] += m_plus
            
    return {"internet": internet, "plus": plus}


@router.post("/", response_model=schemas.ClienteResponse, dependencies=[Depends(require_role(["administrador", "secretario", "tecnico"]))])
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
        cedula_tipo=cliente.cedula_tipo,
        ubicacion=cliente.ubicacion,
        fecha_firma=cliente.fecha_firma,
        estado="Pendiente"
    )
    db.add(db_cliente)
    db.commit()
    db.refresh(db_cliente)
    return db_cliente


@router.get("/siguiente-valor-tecnico")
def obtener_siguiente_valor_tecnico(
    parroquia: str = None, 
    puerto: str = None, 
    mac: str = "",
    nombre: str = "",
    has_breach: bool = False,
    db: Session = Depends(get_db)
):
    import re
    # 1. Obtracción de prefijos y parámetros de red
    db_parroquia = db.query(models.Parroquia).filter(models.Parroquia.nombre == parroquia).first()
    prefijo = db_parroquia.base_ip if db_parroquia and db_parroquia.base_ip else "172.16"
    
    puerto_num_str = puerto if puerto else "0"
    match = re.search(r'\d+', puerto_num_str)
    puerto_num_clean = match.group() if match else "0"
    p_num = int(puerto_num_clean)

    # 2. Búsqueda de valores según requerimiento (ONT ID por Puerto, Service Port Global)
    
    # --- ID PORT (ONT ID) por PUERTO ---
    # Se busca el máximo dentro del mismo puerto y parroquia
    id_ports_en_puerto = db.query(models.Cliente.id_port).filter(
        models.Cliente.id_port.isnot(None), 
        models.Cliente.id_port != "",
        models.Cliente.parroquia == parroquia,
        models.Cliente.puerto == puerto
    ).all()
    
    max_id_port = -1
    for (val,) in id_ports_en_puerto:
        try:
            num = int(val)
            if num > max_id_port: max_id_port = num
        except: continue
    
    id_port_val = max_id_port + 1 if max_id_port >= 0 else 0
    id_port = str(id_port_val)

    # --- SERVICE PORT GLOBAL (Tabla General) ---
    # Sigue siendo global como se solicitó para evitar colisiones en la OLT
    todos_service_ports = db.query(models.Cliente.service_port).filter(
        models.Cliente.service_port.isnot(None), 
        models.Cliente.service_port != ""
    ).all()
    
    max_service_port = 127 # Empezar en 128 si no hay nada
    for (val,) in todos_service_ports:
        try:
            num = int(val)
            if num > max_service_port: max_service_port = num
        except: continue
        
    service_port_val = max_service_port + 1
    service_port = str(service_port_val)

    # --- IP (Fórmula basada en el ID y el Puerto para evitar colisiones) ---
    ip_sugerida = f"{prefijo}.{p_num}.{id_port_val + 1}"
    
    # 3. Limpieza y Cálculos de Perfil
    mac_clean = re.sub(r'[^a-zA-Z0-9]', '', mac).upper()
    vlan_transport = 300 + p_num
    vlan_user = 100 + p_num
    profile_id = 100 + p_num
    gemport = 100 + p_num

    # 4. Fórmulas de generación de OLT Maestro Pro
    # Comando 1: ONT add
    cmd_ont = f'ont add {p_num} {id_port} sn-auth "{mac_clean}" omci ont-lineprofile-id {profile_id} ont-srvprofile-id {profile_id} desc "{nombre}"'
    
    # Comando 2: Service Port
    cmd_servicio = f'service-port {service_port} vlan {vlan_transport} gpon 0/0/{p_num} ont {id_port} gemport {gemport} multi-service user-vlan {vlan_user} tag-transform translate'
    
    # Comando 3: ONT Port (Native VLAN / Bridge)
    cmd_breach = f'ont port native-vlan {p_num} {id_port} eth 1 vlan {vlan_user} priority 0'
    
    return {
        "id_port": id_port,
        "service_port": service_port,
        "ip": ip_sugerida,
        "ont": cmd_ont,
        "servicio": cmd_servicio,
        "breach": cmd_breach
    }



@router.patch("/{id}/pasar-a-activacion", dependencies=[Depends(require_role(["administrador", "secretario"]))])
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

@router.patch("/{id}", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def actualizar_cliente_general(id: int, data: schemas.ClienteUpdateGeneral, db: Session = Depends(get_db)):
    cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    # 1. Validar ID_PORT (per-port)
    p_id_port = data.id_port if data.id_port is not None else cliente.id_port
    if p_id_port:
        p_parroquia = data.parroquia if data.parroquia is not None else cliente.parroquia
        p_puerto = data.puerto if data.puerto is not None else cliente.puerto
        
        # Solo validamos si alguno de los 3 está cambiando o si se envió explícitamente el id_port
        if data.id_port is not None or data.parroquia is not None or data.puerto is not None:
            existente_id = db.query(models.Cliente).filter(
                models.Cliente.id_port == p_id_port,
                models.Cliente.parroquia == p_parroquia,
                models.Cliente.puerto == p_puerto,
                models.Cliente.id != id
            ).first()
            if existente_id:
                raise HTTPException(status_code=400, detail=f"El ID Port '{p_id_port}' ya existe en el puerto '{p_puerto}' ({p_parroquia}).")

    # 2. Validar Globales
    campos_globales = ["ont", "servicio", "breach", "service_port", "ip"]
    for campo in campos_globales:
        nuevo_valor = getattr(data, campo)
        if nuevo_valor:
            columna = getattr(models.Cliente, campo)
            existente = db.query(models.Cliente).filter(columna == nuevo_valor, models.Cliente.id != id).first()
            if existente:
                raise HTTPException(status_code=400, detail=f"El campo '{campo}' con valor '{nuevo_valor}' ya está en uso globalmente.")

    for var, value in vars(data).items():
        if value is not None:
            setattr(cliente, var, value)
            
    sync_cliente_balances(cliente, db)
    db.commit()
    return {"message": "Cliente actualizado correctamente"}

@router.patch("/{id}/configuracion-tecnica", dependencies=[Depends(require_role(["administrador", "tecnico", "instalador"]))])

def actualizar_datos_tecnicos(id: int, data: schemas.ClienteUpdateTecnico, db: Session = Depends(get_db)):
    cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    # 1. Validar ID_PORT (per-port)
    if data.id_port:
        existente_id = db.query(models.Cliente).filter(
            models.Cliente.id_port == data.id_port,
            models.Cliente.parroquia == cliente.parroquia, 
            models.Cliente.puerto == data.puerto,
            models.Cliente.id != id
        ).first()
        if existente_id:
            raise HTTPException(status_code=400, detail=f"El ID Port '{data.id_port}' ya existe en el puerto '{data.puerto}' ({cliente.parroquia}).")

    # 2. Validar Globales
    campos_globales = ["ont", "servicio", "breach", "service_port", "ip"]
    for campo in campos_globales:
        nuevo_valor = getattr(data, campo)
        if nuevo_valor:
            columna = getattr(models.Cliente, campo)
            existente = db.query(models.Cliente).filter(columna == nuevo_valor, models.Cliente.id != id).first()
            if existente:
                raise HTTPException(status_code=400, detail=f"El campo '{campo}' con valor '{nuevo_valor}' ya está en uso globalmente.")

    for var, value in vars(data).items():
        setattr(cliente, var, value)
    
    # 3. Validar Potencia (No puede ser inferior a -26.0 dBm)
    if cliente.potencia:
        try:
            p_val = float(str(cliente.potencia).replace(',', '.').strip())
            if p_val < -26.0:
                raise HTTPException(status_code=400, detail=f"La potencia de {p_val} dBm es demasiado baja. El límite es -26.0 dBm.")
        except ValueError:
            pass # Si no es un número válido (ej: "S/N"), saltamos la validación numérica

    cliente.estado = "Activo"
    cliente.instalation_date = datetime.now().strftime("%Y-%m-%d")
    db.commit()
    return {"message": "Configuración técnica guardada, cliente ahora Activo y con fecha de instalación registrada."}



@router.patch("/{id}/administracion", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def actualizar_administracion(id: int, data: schemas.ClienteUpdateAdmin, db: Session = Depends(get_db)):
    cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    for var, value in vars(data).items():
        if value is not None:
            setattr(cliente, var, value)
            
    sync_cliente_balances(cliente, db)
    db.commit()
    return {"message": "Datos de administración actualizados"}

@router.post("/{id}/pagar", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def registrar_pago(id: int, pago_data: schemas.PagoCreate, db: Session = Depends(get_db)):
    cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    


    nuevo_pago = models.Pago(

        cliente_id=id,
        monto=pago_data.monto,
        metodo_pago=pago_data.metodo_pago,
        mes_correspondiente=pago_data.mes_correspondiente,
        referencia=pago_data.referencia,
        monto_internet=try_float(pago_data.internet_payment),
        monto_plus=try_float(pago_data.plus) + try_float(pago_data.adicional)
    )

    db.add(nuevo_pago)
    
    saldo_anterior = float(cliente.saldo or 0)
    pago_mensual_anterior = float(cliente.pago_mensual or 0)
    
    cliente.saldo = saldo_anterior - float(pago_data.monto)
    cliente.pago_mensual = pago_mensual_anterior + float(pago_data.monto)

    # para poder vaciar los campos de entrada originales sin crear excedente


    if pago_data.plus is not None: 
        cliente.plus_pagado = float(cliente.plus_pagado or 0) + try_float(cliente.plus)
        cliente.plus = ""
    if pago_data.adicional is not None: 
        cliente.adicional_pagado = float(cliente.adicional_pagado or 0) + try_float(cliente.adicional)
        cliente.adicional = ""

    if pago_data.facturas is not None: cliente.facturas = pago_data.facturas
    if pago_data.internet_payment is not None: cliente.internet_payment = pago_data.internet_payment
    if pago_data.app is not None: cliente.app = pago_data.app
    if pago_data.payment_date is not None: cliente.payment_date = pago_data.payment_date
    if pago_data.client_payment_date is not None: cliente.client_payment_date = pago_data.client_payment_date
    if pago_data.bank is not None: cliente.bank = pago_data.bank
    if pago_data.cod is not None: cliente.cod = pago_data.cod
    if pago_data.bank_plus is not None: cliente.bank_plus = pago_data.bank_plus
    if pago_data.comentarios is not None: cliente.comentarios = pago_data.comentarios

    sync_cliente_balances(cliente, db)
    db.commit()
    
    if float(cliente.saldo) < 0:
        return {"message": f"Pago registrado con éxito. Excedente en cuenta: ${abs(float(cliente.saldo)):.2f}", "nuevo_saldo": float(cliente.saldo)}
    return {"message": f"Pago registrado con éxito. Saldo pendiente: ${float(cliente.saldo):.2f}", "nuevo_saldo": float(cliente.saldo)}

@router.post("/facturacion-mensual-global", dependencies=[Depends(require_role(["administrador"]))])
def ejecutar_facturacion_mensual(db: Session = Depends(get_db)):
    config_sys = get_config()
    current_month = datetime.now().strftime("%Y-%m")
    
    # Primera vez (sistema nuevo): permitir facturación sin cierre previo
    # Después del primer mes, siempre se requiere cierre antes de facturar
    es_primera_vez = not config_sys.get("ultimo_cierre")
    
    if not es_primera_vez and config_sys.get("ultimo_cierre") != current_month:
        raise HTTPException(status_code=400, detail="Debe realizar el Cierre de Mes (en Reportes) antes de ejecutar la Facturación Mensual.")
    
    if config_sys.get("ultima_facturacion") == current_month:
        raise HTTPException(status_code=400, detail="La facturación para este mes ya fue realizada. Debe esperar al próximo mes.")

    clientes = db.query(models.Cliente).all()
    clientes_activos = [c for c in clientes if c.estado and c.estado.upper() == "ACTIVO"]
    
    count = 0
    for cliente in clientes_activos:
        tarifa = 0.00
        plan_info = db.query(models.PlanInternet).filter(models.PlanInternet.nombre == cliente.plan).first()
        if plan_info:
            tarifa = float(plan_info.precio or 0)
        
        try:
            monto_plus = float(cliente.plus) if cliente.plus else 0.0
        except (ValueError, TypeError):
            monto_plus = 0.0
            
        total_a_cobrar = tarifa + monto_plus
        
        cliente.saldo = (float(cliente.saldo or 0) + total_a_cobrar)
        count += 1
        
    save_config({"ultima_facturacion": current_month})
    db.commit()
    return {"message": f"Facturación procesada para {count} clientes exitosamente."}

@router.post("/cierre-mensual-global", dependencies=[Depends(require_role(["administrador"]))])
def ejecutar_cierre_mensual(db: Session = Depends(get_db)):
    config_sys = get_config()
    current_month = datetime.now().strftime("%Y-%m")
    
    if config_sys.get("ultimo_cierre") == current_month:
        raise HTTPException(status_code=400, detail="El cierre de este mes ya fue realizado.")
        
    clientes = db.query(models.Cliente).all()
    count = 0
    for cliente in clientes:
        # En el cierre de mes se resetean los marcadores de pagos del mes anterior
        # para empezar en blanco el nuevo mes. El 'saldo' histórico de deudas se mantiene.
        cliente.pago_mensual = 0.00
        cliente.plus_pagado = 0.00
        cliente.adicional_pagado = 0.00
        count += 1
        
    save_config({"ultimo_cierre": current_month})
    db.commit()
    return {"message": f"Cierre de mes completado para {count} clientes. Ahora puede ejecutar la Facturación Mensual."}

@router.post("/pago-global-test")
def liquidar_todas_las_deudas(db: Session = Depends(get_db)):
    clientes = db.query(models.Cliente).filter(models.Cliente.saldo > 0).all()
    count = 0
    for cliente in clientes:
        cliente.saldo = 0.00
        count += 1
    db.commit()
    return {"message": f"Deudas liquidadas para {count} clientes (TEST)."}


@router.get("/pagos/historial")
def listar_pagos(db: Session = Depends(get_db)):
    return db.query(models.Pago).order_by(models.Pago.fecha_pago.desc()).all()

import pandas as pd
import os

@router.get("/reportes/historial")
def listar_reportes(db: Session = Depends(get_db)):
    try:
        data = db.query(models.ReporteMensual).order_by(models.ReporteMensual.fecha_generacion.desc()).all()
        return data
    except Exception as e:
        return []

@router.post("/reportes/generar", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def generar_reporte_mensual(db: Session = Depends(get_db)):
    config_sys = get_config()
    current_month = datetime.now().strftime("%Y-%m")
    
    if config_sys.get("ultimo_cierre") == current_month:
        raise HTTPException(status_code=400, detail="El Cierre de Mes ya fue realizado este mes. Solo se puede hacer una vez por mes.")
    
    clientes = db.query(models.Cliente).all()
    
    data = []
    for c in clientes:
        fact_val = str(c.facturas or "").strip().upper()
        # Filtro: Solo si hay factura y no es "NONE"
        if not fact_val or fact_val == "NONE":
            continue

        data.append({
            "ID": c.id,
            "NOMBRE": c.nombre,
            "CELULAR": c.celular,
            "CEDULA": c.cedula,
            "CORREO": c.correo,
            "BANK": c.bank,
            "TOTAL": float(c.total_pago) if c.total_pago is not None else 0.00,
        })
        
    df = pd.DataFrame(data)
    os.makedirs("rutas_reportes", exist_ok=True)
    
    mes_actual = datetime.now().strftime("%m-%Y")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"Reporte_{mes_actual}_{timestamp}.xlsx"
    file_path = os.path.join("rutas_reportes", file_name)
    
    df.to_excel(file_path, index=False)
    
    nuevo_reporte = models.ReporteMensual(
        mes_anio=mes_actual,
        archivo_ruta_excel=f"/rutas_reportes/{file_name}"
    )
    db.add(nuevo_reporte)
    
    for c in clientes:
        c.facturas = ""
        c.internet_payment = ""
        c.app = ""
        c.payment_date = ""
        c.client_payment_date = ""
        c.bank = ""
        c.cod = ""
        c.plus = ""
        c.bank_plus = ""
        c.adicional = ""
        c.plus_pagado = 0.00
        c.adicional_pagado = 0.00
        c.comentarios = ""
        # Resetear campos mensuales
        c.pago_mensual = 0.00
        c.total_pago = 0.00
        # Saldo (deuda/excedente) se mantiene para el siguiente mes
        # c.saldo = ... (sin cambios)
        
    save_config({"ultimo_cierre": datetime.now().strftime("%Y-%m")})
    db.commit()
    
    return {"message": "Reporte generado. Campos de pago vaciados (saldos intactos).", "reporte_id": nuevo_reporte.id, "archivo": nuevo_reporte.archivo_ruta_excel}
@router.post("/{cliente_id}/upload-cedula")
async def upload_cedula(
    cliente_id: int,
    frontal: UploadFile = File(None),
    posterior: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    cliente = db.query(models.Cliente).filter(models.Cliente.id == cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    upload_dir = "uploads/cedulas"
    os.makedirs(upload_dir, exist_ok=True)
    
    if frontal:
        file_ext = os.path.splitext(frontal.filename)[1]
        file_path = f"{upload_dir}/{cliente_id}_frontal{file_ext}"
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(frontal.file, buffer)
        cliente.cedula_frontal = f"/uploads/cedulas/{cliente_id}_frontal{file_ext}"
        
    if posterior:
        file_ext = os.path.splitext(posterior.filename)[1]
        file_path = f"{upload_dir}/{cliente_id}_posterior{file_ext}"
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(posterior.file, buffer)
        cliente.cedula_posterior = f"/uploads/cedulas/{cliente_id}_posterior{file_ext}"
        
    db.commit()
    return {"message": "Fotos subidas con éxito", "frontal": cliente.cedula_frontal, "posterior": cliente.cedula_posterior}
