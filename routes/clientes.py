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
import calendar

def try_float(val):
    try:
        # Limpieza robusta: eliminar '$' y corregir separadores decimales
        clean_val = str(val or 0).replace('$', '').replace(',', '.').strip()
        return float(clean_val) if clean_val else 0.0
    except:
        return 0.0


def sync_cliente_balances(cliente: models.Cliente, db: Session = None):
    # El total_pago representa el total real adeudado en tiempo real.
    # Incluye Saldo (deuda histórica neta de pagos) + Tarifa (valor del plan actual) + IPTV + Adicional.
    tarifa = 0.00
    if cliente.tercera_edad and cliente.precio_plan_especial:
        tarifa = float(cliente.precio_plan_especial)
    elif db:
        plan_info = db.query(models.PlanInternet).filter(models.PlanInternet.nombre == cliente.plan).first()
        if plan_info:
            tarifa = float(plan_info.precio or 0)
            
    plus = try_float(cliente.plus)
    adicional = try_float(cliente.adicional)
    saldo = float(cliente.saldo or 0)
    
    # El Pendiente Principal (total_pago) SEPARA el cargo adicional según requerimiento v1.2.
    # El adicional es un servicio aparte que NO afecta la deuda de internet/iptv en Pagos y Cobros.
    cliente.total_pago = saldo + tarifa + plus

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
            
    # Calculate Finanzas Globales
    fb = db.query(models.FinanzasBase).first()
    b_caja = float(fb.caja_chica) if fb else 0.0
    b_pich = float(fb.pichincha) if fb else 0.0
    b_jep = float(fb.jep) if fb else 0.0
    
    finanzas_globales = {
        "Caja Chica": b_caja + internet["Efectivo"] + plus["Efectivo"],
        "Pichincha": b_pich + internet["Pichincha"] + plus["Pichincha"],
        "JEP": b_jep + internet["JEP"]
    }
            
    return {"internet": internet, "plus": plus, "finanzas_globales": finanzas_globales}


@router.post("/", response_model=schemas.ClienteResponse, dependencies=[Depends(require_role(["administrador", "secretario", "tecnico"]))])
def crear_cliente(cliente: schemas.ClienteCreate, db: Session = Depends(get_db)):
    db_cliente = models.Cliente(
        nombre=cliente.nombre,
        cedula=cliente.cedula,
        celular=cliente.celular,
        correo=cliente.correo,
        direccion=cliente.direccion,
        nodo=cliente.nodo,
        plan=cliente.plan,
        plus=cliente.plus,
        cedula_tipo=cliente.cedula_tipo,
        ubicacion=cliente.ubicacion,
        fecha_firma=cliente.fecha_firma,
        tiempo=cliente.tiempo,
        tercera_edad=cliente.tercera_edad,
        precio_plan_especial=cliente.precio_plan_especial,
        estado="Pendiente"
    )
    db.add(db_cliente)
    db.commit()
    db.refresh(db_cliente)
    
    # Sincronizamos balances para que el total_pago se calcule (Costo Plan + Plus)
    sync_cliente_balances(db_cliente, db)
    db.commit()
    db.refresh(db_cliente)
    return db_cliente


@router.get("/siguiente-valor-tecnico")
def obtener_siguiente_valor_tecnico(
    nodo: str = None, 
    puerto: str = None, 
    mac: str = "",
    nombre: str = "",
    has_breach: bool = False,
    cliente_id: str = "",
    db: Session = Depends(get_db)
):
    import re
    # 1. Obtracción de prefijos y parámetros de red
    db_nodo = db.query(models.Nodo).filter(models.Nodo.nombre == nodo).first()
    
    # Lógica SAYAUSI vs Normal
    is_sayausi = str(nodo or "").upper() == "SAYAUSI"
    
    # El prefijo cambia para SAYAUSI a 172.18 si no se especifica otra cosa en el nodo
    if is_sayausi:
        prefijo = "172.18"
    else:
        prefijo = db_nodo.base_ip if db_nodo and db_nodo.base_ip else "172.16"
    
    puerto_num_str = puerto if puerto else "0"
    match = re.search(r'\d+', puerto_num_str)
    puerto_num_clean = match.group() if match else "0"
    p_num = int(puerto_num_clean)

    # 2. Búsqueda Recursiva de Valores Libres
    id_port_val = 0
    while True:
        service_port_val = p_num * 128 + id_port_val
        
        id_port_ocupado = db.query(models.Cliente).filter(
            models.Cliente.id_port == str(id_port_val),
            models.Cliente.nodo == nodo,
            models.Cliente.puerto == puerto
        ).first()

        sp_ocupado = db.query(models.Cliente).filter(
            models.Cliente.service_port == str(service_port_val)
        ).first()

        if not id_port_ocupado and not sp_ocupado:
            break
        id_port_val += 1
        if id_port_val > 127: break

    id_port = str(id_port_val)
    service_port = str(service_port_val)

    # 3. IP Verification
    ip_sugerida = ""
    ip_offset = 2
    while True:
        ip_temp = f"{prefijo}.{p_num}.{id_port_val + ip_offset}"
        ip_ocupada = db.query(models.Cliente).filter(models.Cliente.ip == ip_temp).first()
        if not ip_ocupada:
            ip_sugerida = ip_temp
            break
        ip_offset += 1

    # 4. Parámetros Técnicos Diferenciados
    mac_clean = re.sub(r'[^a-zA-Z0-9]', '', mac).upper()
    
    if is_sayausi:
        # SAYAUSI: Perfiles 400+, VLAN 400+, GPON 0/1/x
        profile_id = 400 + p_num
        vlan_val = 400 + p_num
        gpon_path = f"0/1/{p_num}"
        # Descripción incluye el CODIGO (cliente_id) formateado a 3 dígitos si es numérico
        try:
            cid_clean = str(cliente_id).zfill(3)
        except:
            cid_clean = str(cliente_id)
        description = f"{cid_clean} {nombre}"
    else:
        # NORMAL (Baños/Otros): Perfiles 100+, VLAN 100/300, GPON 0/0/x
        profile_id = 100 + p_num
        vlan_val = 100 + p_num # User vlan
        vlan_transport = 300 + p_num
        gpon_path = f"0/0/{p_num}"
        description = nombre

    # 5. Generación de Comandos OLT
    cmd_ont = f'ont add {p_num} {id_port} sn-auth "{mac_clean}" omci ont-lineprofile-id {profile_id} ont-srvprofile-id {profile_id} desc "{description}"'
    
    if is_sayausi:
        # Service port Sayausi: vlan 40X, gpon 0/1/X
        cmd_servicio = f'service-port {service_port} vlan {vlan_val} gpon {gpon_path} ont {id_port} gemport {vlan_val} multi-service user-vlan {vlan_val} tag-transform translate'
        cmd_breach = f'ont port native-vlan {p_num} {id_port} eth 1 vlan {vlan_val} priority 0'
    else:
        # Service port Normal: vlan 30X, gpon 0/0/X
        cmd_servicio = f'service-port {service_port} vlan {vlan_transport} gpon {gpon_path} ont {id_port} gemport {profile_id} multi-service user-vlan {vlan_val} tag-transform translate'
        cmd_breach = f'ont port native-vlan {p_num} {id_port} eth 1 vlan {vlan_val} priority 0'
    
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
        p_nodo = data.nodo if data.nodo is not None else cliente.nodo
        p_puerto = data.puerto if data.puerto is not None else cliente.puerto
        
        # Solo validamos si alguno de los 3 está cambiando o si se envió explícitamente el id_port
        if data.id_port is not None or data.nodo is not None or data.puerto is not None:
            existente_id = db.query(models.Cliente).filter(
                models.Cliente.id_port == p_id_port,
                models.Cliente.nodo == p_nodo,
                models.Cliente.puerto == p_puerto,
                models.Cliente.id != id
            ).first()
            if existente_id:
                raise HTTPException(status_code=400, detail=f"El ID Port '{p_id_port}' ya existe en el puerto '{p_puerto}' ({p_nodo}).")

    # 2. Validar Globales (Campos de red críticos)
    campos_globales = ["service_port", "ip", "mac"]
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
    try:
        cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
        if not cliente:
            raise HTTPException(status_code=404, detail="Cliente no encontrado")
        
        # Log para depuración
        print(f"DEBUG: Activando cliente {id}. MAC: {data.mac}, IP: {data.ip}, Puerto: {data.puerto}")
    
        # 1. Validar ID_PORT (per-port)
        if data.id_port:
            existente_id = db.query(models.Cliente).filter(
                models.Cliente.id_port == data.id_port,
                models.Cliente.nodo == cliente.nodo, 
                models.Cliente.puerto == data.puerto,
                models.Cliente.id != id
            ).first()
            if existente_id:
                raise HTTPException(status_code=400, detail=f"El ID Port '{data.id_port}' ya existe en el puerto '{data.puerto}' ({cliente.nodo}).")

        # 2. Validar Globales (Campos que NO deben repetirse en ningún lugar del sistema)
        campos_globales = ["service_port", "ip", "mac"]
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
                if p_val < -27.0:
                    raise HTTPException(status_code=400, detail=f"La potencia de {p_val} dBm es demasiado baja. El límite es -27.0 dBm.")
            except ValueError:
                pass # Si no es un número válido (ej: "S/N"), saltamos la validación numérica

        cliente.estado = "Activo"
        cliente.instalation_date = datetime.now().strftime("%Y-%m-%d")

        # --- SINCRONIZACIÓN CON HOJA DE RUTA ---
        # Al activar técnicamente, marcamos como 'Realizado' cualquier registro pendiente en Hoja de Ruta
        db.query(models.HojaRuta).filter(
            models.HojaRuta.cliente_id == id,
            models.HojaRuta.estado == "Pendiente"
        ).update({"estado": "Realizado"})

        # Lógica de Prorrateo
        try:
            now = datetime.now()
            _, total_days_in_month = calendar.monthrange(now.year, now.month)
            current_day = now.day
            active_days = (total_days_in_month - current_day) + 1
            
            if cliente.tercera_edad and cliente.precio_plan_especial:
                tarifa_base = float(cliente.precio_plan_especial)
            else:
                plan_info = db.query(models.PlanInternet).filter(models.PlanInternet.nombre == cliente.plan).first()
                tarifa_base = float(plan_info.precio or 0) if plan_info else 0.00
            
            plus_base = try_float(cliente.plus)
            total_full_month = tarifa_base + plus_base
            
            if total_days_in_month > 0 and total_full_month > 0:
                prorated_amount = (total_full_month / total_days_in_month) * active_days
                cliente.saldo = round(prorated_amount - total_full_month, 2)
                sync_cliente_balances(cliente, db)
        except Exception as e:
            print(f"Error calculando prorrateo: {e}")

        db.commit()
        return {"message": "Configuración técnica guardada, cliente ahora Activo (con pago prorrateado) y con fecha de instalación registrada."}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")



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
    


    # Extraemos montos del pago
    m_total = float(pago_data.monto)
    m_adic_p = try_float(pago_data.adicional)
    m_plus_p = try_float(pago_data.plus)
    
    # El m_internet_p fluye independiente del adicional según requerimiento v1.2.
    # El monto total recibido se destina prioritariamente a cubrir el Pendiente de Internet+TV.
    # Restamos tanto m_plus como m_adic para que no afecten el saldo de internet.
    m_internet_p = m_total - m_plus_p - m_adic_p

    # Registrar en historial con el monto total real recibido (m_total ya lo incluye todo)
    nuevo_pago = models.Pago(
        cliente_id=id,
        monto=m_total,
        metodo_pago=pago_data.metodo_pago,
        mes_correspondiente=pago_data.mes_correspondiente,
        referencia=pago_data.referencia,
        monto_internet=m_internet_p, # Only internet
        monto_plus=m_plus_p,         # Only plus
        monto_adicional=m_adic_p     # Only adicional
    )
    db.add(nuevo_pago)
    
    # 1. ACTUALIZAR ADICIONAL (Separado del pendiente principal)
    if m_adic_p > 0:
        curr_adic = try_float(cliente.adicional)
        # Si pagamos más adicional del que hay, el resto NO genera excedente en saldo (según req)
        # simplemente se limpia el campo adicional.
        cliente.adicional = str(max(0, curr_adic - m_adic_p))
        cliente.adicional_pagado = float(cliente.adicional_pagado or 0) + m_adic_p
        if cliente.adicional == "0.0": cliente.adicional = ""

    # 2. ACTUALIZAR PLUS (IPTV)
    if m_plus_p > 0:
        curr_plus = try_float(cliente.plus)
        cliente.plus = str(max(0, curr_plus - m_plus_p))
        cliente.plus_pagado = float(cliente.plus_pagado or 0) + m_plus_p
        if cliente.plus == "0.0": cliente.plus = ""

    # 3. ACTUALIZAR SALDO PRINCIPAL (Internet / Pendiente histórico)
    # Solo el pago destinado a internet afecta al saldo
    saldo_anterior = float(cliente.saldo or 0)
    cliente.saldo = saldo_anterior - m_internet_p
    
    # Actualizar pago mensual (solo para control del mes)
    cliente.pago_mensual = float(cliente.pago_mensual or 0) + m_total

    # Actualizar campos informativos
    if pago_data.facturas is not None: cliente.facturas = pago_data.facturas
    if pago_data.app is not None: cliente.app = pago_data.app
    if pago_data.payment_date is not None: cliente.payment_date = pago_data.payment_date
    if pago_data.bank is not None: cliente.bank = pago_data.bank
    if pago_data.comentarios is not None: cliente.comentarios = pago_data.comentarios

    sync_cliente_balances(cliente, db)
    db.commit()
    
    if float(cliente.saldo) < 0:
        return {"message": f"Pago registrado. Excedente en internet: ${abs(float(cliente.saldo)):.2f}", "nuevo_saldo": float(cliente.saldo)}
    return {"message": f"Pago registrado. Saldo pendiente: ${float(cliente.saldo):.2f}", "nuevo_saldo": float(cliente.saldo)}

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
        # La tarifa ahora se refleja en tiempo real en 'Pendiente' gracias a sync_balances.
        # Solo contabilizamos para el reporte de éxito de la operación.
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
        # 1. Obtener la tarifa vigente para consolidar la deuda al cierre del mes
        tarifa_cierre = 0.00
        plan_info = db.query(models.PlanInternet).filter(models.PlanInternet.nombre == c.plan).first()
        if plan_info:
            tarifa_cierre = float(plan_info.precio or 0)

        # 2. Consolidar deudas del mes al saldo acumulado (Persistent Debt)
        c.saldo = float(c.saldo or 0) + tarifa_cierre + try_float(c.plus) + try_float(c.adicional)
        
        # 3. Limpiar campos mensuales y resetear acumuladores
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
        c.pago_mensual = 0.00
        c.comentarios = ""
        
        # 4. Sincronizar balances (total_pago reflejará el nuevo saldo consolidado)
        sync_cliente_balances(c, db)
        
    save_config({"ultimo_cierre": datetime.now().strftime("%Y-%m")})
    db.commit()
    
    return {"message": "Reporte generado. Campos de pago vaciados (saldos intactos).", "reporte_id": nuevo_reporte.id, "archivo": nuevo_reporte.archivo_ruta_excel}

@router.delete("/{id}", dependencies=[Depends(require_role(["administrador"]))])
def eliminar_cliente(id: int, db: Session = Depends(get_db)):
    cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    # Eliminar archivos de cédula si existen
    if cliente.cedula_frontal:
        path = cliente.cedula_frontal.lstrip("/")
        if os.path.exists(path):
            try: os.remove(path)
            except: pass
    if cliente.cedula_posterior:
        path = cliente.cedula_posterior.lstrip("/")
        if os.path.exists(path):
            try: os.remove(path)
            except: pass

    # Eliminar pagos asociados (si los hubiera)
    db.query(models.Pago).filter(models.Pago.cliente_id == id).delete()
    
    db.delete(cliente)
    db.commit()

    # Lógica para "liberar" el ID: Si eliminamos el último ID, reseteamos el contador de la DB
    try:
        from sqlalchemy import text
        max_id_res = db.execute(text("SELECT MAX(NUMERO) FROM hoja_de_c__lculo_sin_t__tulo")).fetchone()
        max_id = max_id_res[0] if max_id_res and max_id_res[0] is not None else 0
        db.execute(text(f"ALTER TABLE hoja_de_c__lculo_sin_t__tulo AUTO_INCREMENT = {max_id + 1}"))
        db.commit()
    except Exception as e:
        print(f"Error al resetear auto_increment: {e}")

    return {"message": "Cliente eliminado correctamente y ID liberado para el siguiente registro."}
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
