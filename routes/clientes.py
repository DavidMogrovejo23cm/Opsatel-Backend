from database import engine
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


def clean_int_string_value(val):
    if val is None:
        return ""
    # Si ya es un float/int en Python
    if isinstance(val, (int, float)):
        if isinstance(val, float) and val.is_integer():
            return str(int(val))
        elif isinstance(val, int):
            return str(val)
        else:
            return str(val)
    
    # Si es string
    s_val = str(val).strip()
    if s_val.endswith('.0'):
        try:
            f_val = float(s_val)
            if f_val.is_integer():
                return str(int(f_val))
        except:
            pass
    return s_val


def clean_existing_database_formats(db: Session):
    try:
        clients = db.query(models.Cliente).all()
        fixed_count = 0
        for c in clients:
            changed = False
            
            # Campos a limpiar de terminaciones .0
            fields_to_clean = ["puerto", "id_port", "service_port", "tiempo", "cod", "nap"]
            for field in fields_to_clean:
                old_val = getattr(c, field)
                if old_val is not None:
                    new_val = clean_int_string_value(old_val)
                    if new_val != old_val:
                        setattr(c, field, new_val)
                        changed = True
            
            # Lógica especial para cédula (agregar cero a la izquierda si tiene 9 dígitos)
            if c.cedula is not None:
                old_ced = getattr(c, "cedula")
                clean_ced = clean_int_string_value(old_ced)
                if clean_ced and clean_ced.isdigit() and len(clean_ced) == 9:
                    clean_ced = "0" + clean_ced
                if clean_ced != old_ced:
                    c.cedula = clean_ced
                    changed = True
            
            # Lógica especial para celular (agregar cero a la izquierda si tiene 9 dígitos empezando por 9)
            if c.celular is not None:
                old_cel = getattr(c, "celular")
                clean_cel = clean_int_string_value(old_cel)
                if clean_cel and clean_cel.isdigit() and len(clean_cel) == 9 and clean_cel.startswith("9"):
                    clean_cel = "0" + clean_cel
                if clean_cel != old_cel:
                    c.celular = clean_cel
                    changed = True
                    
            if changed:
                fixed_count += 1
                
        if fixed_count > 0:
            db.commit()
            print(f"AUTOMIGRACIÓN: Se corrigieron {fixed_count} clientes con formatos inconsistentes de Excel (.0 o ceros a la izquierda).")
    except Exception as e:
        db.rollback()
        print(f"Error en AUTOMIGRACIÓN de formatos de clientes: {e}")



def sync_cliente_balances(cliente: models.Cliente, db: Session = None):
    # El total_pago representa el total real adeudado en tiempo real.
    # Incluye Saldo (deuda histórica neta de pagos) + Tarifa (valor del plan actual) + IPTV + Adicional.
    tarifa = 0.00
    if cliente.tercera_edad and cliente.precio_plan_especial is not None:
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

@router.get("/pendientes-count")
def get_pendientes_count(db: Session = Depends(get_db)):
    count = db.query(models.Cliente).filter(models.Cliente.estado == "Pendiente").count()
    return {"count": count}

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
    # Lógica para reutilizar IDs (Encontrar el primer hueco disponible)
    ids_query = db.query(models.Cliente.id).order_by(models.Cliente.id).all()
    ids = [i[0] for i in ids_query]
    
    nuevo_id = 1
    for current_id in ids:
        if current_id == nuevo_id:
            nuevo_id += 1
        elif current_id > nuevo_id:
            break # Encontramos un hueco
            
    db_cliente = models.Cliente(
        id=nuevo_id, # Asignamos el ID manualmente para llenar el hueco
        nombre=cliente.nombre,
        cedula=cliente.cedula,
        celular=cliente.celular,
        correo=cliente.correo,
        direccion=cliente.direccion,
        nodo=cliente.nodo,
        parroquia=cliente.parroquia,
        plan=cliente.plan,
        plus=cliente.plus,
        iptv_max_conn=cliente.iptv_max_conn,
        cedula_tipo=cliente.cedula_tipo,
        ubicacion=cliente.ubicacion,
        fecha_firma=cliente.fecha_firma,
        tiempo=cliente.tiempo,
        tercera_edad=cliente.tercera_edad,
        precio_plan_especial=cliente.precio_plan_especial,
        comentarios=cliente.comentarios,
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


@router.post("/{id}/upload-cedula", dependencies=[Depends(require_role(["administrador", "secretario", "tecnico"]))])
async def upload_cedula(id: int, frontal: UploadFile = File(None), posterior: UploadFile = File(None), db: Session = Depends(get_db)):
    cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    upload_dir = "uploads/cedulas"
    os.makedirs(upload_dir, exist_ok=True)
    
    if frontal:
        ext = os.path.splitext(frontal.filename)[1]
        file_path = f"{upload_dir}/frontal_{id}_{int(datetime.now().timestamp())}{ext}"
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(frontal.file, buffer)
        cliente.cedula_frontal = f"/{file_path}"
        
    if posterior:
        ext = os.path.splitext(posterior.filename)[1]
        file_path = f"{upload_dir}/posterior_{id}_{int(datetime.now().timestamp())}{ext}"
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(posterior.file, buffer)
        cliente.cedula_posterior = f"/{file_path}"
    
    db.commit()
    return {"message": "Imágenes subidas exitosamente"}


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

    # Convert cliente_id to integer if possible
    c_id = None
    if cliente_id:
        try:
            c_id = int(cliente_id)
        except ValueError:
            pass

    # 2. Búsqueda Recursiva de Valores Libres
    id_port_val = 0
    while True:
        service_port_val = p_num * 128 + id_port_val
        
        id_port_query = db.query(models.Cliente).filter(
            models.Cliente.id_port == str(id_port_val),
            models.Cliente.nodo == nodo,
            models.Cliente.puerto == puerto
        )
        if c_id is not None:
            id_port_query = id_port_query.filter(models.Cliente.id != c_id)
        id_port_ocupado = id_port_query.first()

        sp_query = db.query(models.Cliente).filter(
            models.Cliente.service_port == str(service_port_val)
        )
        if c_id is not None:
            sp_query = sp_query.filter(models.Cliente.id != c_id)
        sp_ocupado = sp_query.first()

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
        ip_query = db.query(models.Cliente).filter(models.Cliente.ip == ip_temp)
        if c_id is not None:
            ip_query = ip_query.filter(models.Cliente.id != c_id)
        ip_ocupada = ip_query.first()
        if not ip_ocupada:
            ip_sugerida = ip_temp
            break
        ip_offset += 1

    # 4. Parámetros Técnicos Diferenciados
    mac_clean = re.sub(r'[^a-zA-Z0-9]', '', str(mac or "")).upper()
    
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
        "breach": cmd_breach if has_breach else ""
    }



@router.patch("/{id}/pasar-a-activacion", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def pasar_a_activacion(id: int, db: Session = Depends(get_db)):
    cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    cliente.estado = "En Activación"
    db.commit()
    return {"message": "Cliente pasado a etapa de activación", "estado": cliente.estado}

@router.get("/test-db")
def test_database_tables(db: Session = Depends(get_db)):
    models_to_test = [
        ("Cliente", models.Cliente),
        ("Pago", models.Pago),
        ("Nodo", models.Nodo),
        ("PlanInternet", models.PlanInternet),
        ("Banco", models.Banco),
        ("Puerto", models.Puerto),
        ("FinanzasBase", models.FinanzasBase),
        ("Parroquia", models.Parroquia),
        ("ClienteExtra", models.ClienteExtra),
        ("PagoExtra", models.PagoExtra),
        ("HojaRuta", models.HojaRuta),
        ("Ticket", models.Ticket),
        ("CallCenterTicket", models.CallCenterTicket),
        ("Egreso", models.Egreso),
        ("Proyecto", models.Proyecto),
        ("ProyectoPago", models.ProyectoPago),
        ("GastoProyecto", models.GastoProyecto),
        ("Colchon", models.Colchon),
        ("GastoFijo", models.GastoFijo),
        ("Asistencia", models.Asistencia),
        ("WhatsAppHistorial", models.WhatsAppHistorial),
        ("WhatsAppConfiguracion", models.WhatsAppConfiguracion),
        ("ReporteMensual", models.ReporteMensual),
        ("Usuario", models.Usuario)
    ]
    results = {}
    for name, model in models_to_test:
        try:
            count = db.query(model).count()
            results[name] = {"status": "ok", "count": count}
        except Exception as e:
            results[name] = {"status": "error", "message": str(e)}
    return results

@router.get("/descargar-completo")
def descargar_completa_base_datos(db: Session = Depends(get_db)):
    """
    Exporta todas las tablas de la base de datos a un único archivo Excel con múltiples pestañas.
    """
    try:
        import io
        from decimal import Decimal
        from datetime import datetime, date
        import pandas as pd
        from fastapi.responses import StreamingResponse
        
        # Lista de todos los modelos a exportar
        models_to_export = [
            (models.Cliente, "Clientes"),
            (models.Pago, "Pagos"),
            (models.Nodo, "Nodos"),
            (models.PlanInternet, "Planes de Internet"),
            (models.Banco, "Bancos"),
            (models.Puerto, "Puertos"),
            (models.FinanzasBase, "Finanzas Base"),
            (models.Parroquia, "Parroquias"),
            (models.ClienteExtra, "Clientes Extras"),
            (models.PagoExtra, "Pagos Extras"),
            (models.HojaRuta, "Hojas de Ruta"),
            (models.Ticket, "Tickets de Asistencia"),
            (models.CallCenterTicket, "Tickets Call Center"),
            (models.Egreso, "Egresos"),
            (models.Proyecto, "Proyectos"),
            (models.ProyectoPago, "Proyecto Pagos"),
            (models.GastoProyecto, "Gasto Proyectos"),
            (models.Colchon, "Colchón de Reserva"),
            (models.GastoFijo, "Gastos Fijos"),
            (models.Asistencia, "Asistencias del Personal"),
            (models.WhatsAppHistorial, "Historial WhatsApp"),
            (models.WhatsAppConfiguracion, "Configuración WhatsApp"),
            (models.ReporteMensual, "Reportes Mensuales"),
            (models.Usuario, "Usuarios del Sistema")
        ]
        
        output = io.BytesIO()
        
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            for model, sheet_name in models_to_export:
                # Query all records for this model
                records = db.query(model).all()
                
                if records:
                    data_list = []
                    for rec in records:
                        d = {}
                        for col in model.__table__.columns:
                            # col.key es el nombre del atributo en Python (ej: 'id')
                            # col.name es el nombre del campo en la base de datos (ej: 'NUMERO')
                            val = getattr(rec, col.key)
                            if isinstance(val, (datetime, date)):
                                val = val.strftime("%Y-%m-%d %H:%M:%S") if hasattr(val, "strftime") else str(val)
                            elif isinstance(val, Decimal):
                                val = float(val)
                            d[col.name] = val
                        data_list.append(d)
                    df = pd.DataFrame(data_list)
                else:
                    columns = [c.name for c in model.__table__.columns]
                    df = pd.DataFrame(columns=columns)
                    
                # Limit sheet name to 31 characters
                sheet_name_limit = sheet_name[:31]
                df.to_excel(writer, sheet_name=sheet_name_limit, index=False)
                
        output.seek(0)
        
        headers = {
            'Content-Disposition': 'attachment; filename="Base_Datos_Completa_Opsatel.xlsx"'
        }
        return StreamingResponse(
            output,
            media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers=headers
        )
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error al generar la descarga de la base de datos: {str(e)}")


@router.get("/{id}", response_model=schemas.ClienteResponse)
def obtener_cliente(id: int, db: Session = Depends(get_db)):
    cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return cliente

@router.patch("/{id}", dependencies=[Depends(require_role(["administrador", "secretario", "tecnico"]))])
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
            if var == 'iptv_max_conn' and value is not None:
                # Obtener pantallas base desde la configuración del plan
                plan_info = db.query(models.PlanInternet).filter(models.PlanInternet.nombre == cliente.plan).first()
                base_screens = (plan_info.pantallas if plan_info.pantallas is not None else 0) if plan_info else 0
                # Las pantallas incluidas en el plan son gratis, las extras valen $2
                cliente.plus = str(max(0, (value - base_screens) * 2))
        
        sync_cliente_balances(cliente, db)
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
        # Al activar técnicamente, marcamos como 'En proceso' cualquier registro pendiente en Hoja de Ruta
        db.query(models.HojaRuta).filter(
            models.HojaRuta.cliente_id == id,
            models.HojaRuta.estado == "Pendiente"
        ).update({"estado": "En proceso"})
        db.commit() # Asegurar cambios persistentes

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
            # Sincronizar 'plus' si se cambia 'iptv_max_conn'
            if var == 'iptv_max_conn':
                plan_info = db.query(models.PlanInternet).filter(models.PlanInternet.nombre == cliente.plan).first()
                base_screens = (plan_info.pantallas if plan_info.pantallas is not None else 0) if plan_info else 0
                cliente.plus = str(max(0, (value - base_screens) * 2))
            
    sync_cliente_balances(cliente, db)
    db.commit()
    return {"message": "Datos de administración actualizados"}

@router.post("/{id}/pagar", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def registrar_pago(id: int, pago_data: schemas.PagoCreate, db: Session = Depends(get_db)):
    try:
        cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
        if not cliente:
            raise HTTPException(status_code=404, detail="Cliente no encontrado")

        # Extraemos montos reales pagados (Cash)
        m_total_cash = float(pago_data.monto)
        m_adic_cash = try_float(pago_data.adicional)
        m_plus_cash = try_float(pago_data.plus)
        m_internet_cash = m_total_cash - m_plus_cash - m_adic_cash

        # Validar que no haya NaN
        import math
        if math.isnan(m_total_cash) or math.isnan(m_internet_cash):
            raise HTTPException(status_code=400, detail="Monto inválido (NaN)")

        # Calculamos la reducción total de deuda: Cash + Descuentos
        deuda_internet = m_internet_cash + (pago_data.descuento_internet or 0.0)
        deuda_plus = m_plus_cash + (pago_data.descuento_plus or 0.0)
        deuda_adicional = m_adic_cash + (pago_data.descuento_adicional or 0.0)

        # Usamos el Cash real en models.Pago para mantener Finanzas correctas
        nuevo_pago = models.Pago(
            cliente_id=id,
            monto=m_total_cash,
            metodo_pago=pago_data.metodo_pago,
            mes_correspondiente=pago_data.mes_correspondiente,
            referencia=pago_data.referencia,
            monto_internet=m_internet_cash,
            monto_plus=m_plus_cash,
            monto_adicional=m_adic_cash
        )
        db.add(nuevo_pago)

        # 1. ACTUALIZAR ADICIONAL
        if deuda_adicional > 0:
            curr_adic = try_float(cliente.adicional)
            cliente.adicional = str(max(0, curr_adic - deuda_adicional))
            # Pagado refleja solo el efectivo
            if m_adic_cash > 0:
                cliente.adicional_pagado = float(cliente.adicional_pagado or 0) + m_adic_cash
            if cliente.adicional == "0.0": cliente.adicional = ""

        # 2. ACTUALIZAR PLUS (IPTV)
        if deuda_plus > 0:
            curr_plus = try_float(cliente.plus)
            cliente.plus = str(max(0, curr_plus - deuda_plus))
            # Pagado refleja solo el efectivo
            if m_plus_cash > 0:
                cliente.plus_pagado = float(cliente.plus_pagado or 0) + m_plus_cash
            if cliente.plus == "0.0": cliente.plus = ""

        # 3. ACTUALIZAR SALDO PRINCIPAL
        cliente.saldo = float(cliente.saldo or 0) - deuda_internet
        # El pago mensual refleja solo el dinero real ingresado a caja. Los descuentos no aumentan el total cobrado.
        cliente.pago_mensual = float(cliente.pago_mensual or 0) + m_total_cash

        if pago_data.facturas is not None: cliente.facturas = pago_data.facturas
        if pago_data.app is not None: cliente.app = pago_data.app
        if pago_data.payment_date is not None: cliente.payment_date = pago_data.payment_date
        if pago_data.bank is not None: cliente.bank = pago_data.bank
        if pago_data.notas_pago is not None: cliente.notas_pago = pago_data.notas_pago

        sync_cliente_balances(cliente, db)
        db.commit()

        nuevo_saldo = float(cliente.saldo or 0)
        if nuevo_saldo < 0:
            return {"message": f"Pago registrado. Excedente: ${abs(nuevo_saldo):.2f}", "nuevo_saldo": nuevo_saldo}
        return {"message": f"Pago registrado. Saldo pendiente: ${nuevo_saldo:.2f}", "nuevo_saldo": nuevo_saldo}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error al procesar pago: {str(e)}")

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
        # 1. Recargo mensual de IPTV PLUS ($2 por pantalla adicional contratada)
        # Obtenemos pantallas base del plan
        plan_info = db.query(models.PlanInternet).filter(models.PlanInternet.nombre == cliente.plan).first()
        base_screens = (plan_info.pantallas if plan_info.pantallas is not None else 0) if plan_info else 0
        
        if (cliente.iptv_max_conn or 0) > base_screens:
            cargo_plus = (cliente.iptv_max_conn - base_screens) * 2
            cliente.plus = str(try_float(cliente.plus) + cargo_plus)
            
        # 2. La tarifa de internet se refleja en Pendiente vía sync_balances
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
    
    # ── HOJA 1: FACTURACIÓN CLIENTES ──
    month_num = current_month.split("-")[1]
    month_name_en = {
        "01": "JANUARY", "02": "FEBRUARY", "03": "MARCH", "04": "APRIL",
        "05": "MAY", "06": "JUNE", "07": "JULY", "08": "AUGUST",
        "09": "SEPTEMBER", "10": "OCTOBER", "11": "NOVEMBER", "12": "DECEMBER"
    }.get(month_num, "MONTH")

    # Obtener planes y precios
    planes = db.query(models.PlanInternet).all()
    planes_precios = {p.nombre: float(p.precio) for p in planes}
    planes_megas = {p.nombre: int(p.megas or 0) for p in planes}

    data = []
    for c in clientes:
        id_str = f"C{c.id:02d}" if c.id is not None else ""
        fact_val = str(c.facturas or "").strip()
        has_factura = bool(fact_val and fact_val.upper() != "NONE" and fact_val != "")
        
        pago_mensual = float(c.pago_mensual or 0.00)
        confirmar = True if (has_factura and pago_mensual > 0) else False
        megas_val = f"{planes_megas.get(c.plan, 0)}MB" if (confirmar and c.plan and c.plan in planes_megas) else "FALSE"
        factura_val = fact_val if has_factura else "SIN FACTURA"

        data.append({
            "ID": id_str,
            "NAME": c.nombre or "",
            "DIRECTION": c.direccion or "",
            "CEL": c.celular or "",
            "PARISH": c.parroquia or "",
            "PLAN": c.plan or "",
            f"FACT {month_name_en}": factura_val,
            "CONFIRMAR": confirmar,
            f"MEGAS {month_name_en}": megas_val,
            "FACTURAS": factura_val,
        })
        
    df_clientes = pd.DataFrame(data)
    
    # ── HOJA 2: RESUMEN POR PLAN ──
    # Consultar todos los pagos del mes correspondiente
    pagos_todos = db.query(models.Pago).all()
    pagos_mes_actual = [p for p in pagos_todos if str(p.fecha_pago)[:7] == current_month]
    
    # Acumular pagos por cliente y por método de pago
    pago_por_cliente_metodo = {}
    for p in pagos_mes_actual:
        if p.cliente_id:
            monto_total_pago = float(p.monto_internet or 0) + float(p.monto_plus or 0) + float(p.monto_adicional or 0)
            metodo = (p.metodo_pago or "Efectivo").upper()
            key = (p.cliente_id, metodo)
            pago_por_cliente_metodo[key] = pago_por_cliente_metodo.get(key, 0.0) + monto_total_pago
            
    # Obtener planes únicos presentes en los clientes
    planes_nombres = sorted(list(set(c.plan for c in clientes if c.plan)))
    
    resumen_data = []
    gran_total_clientes = 0
    gran_total_estimado = 0.0
    gran_total_efectivo = 0.0
    gran_total_pichincha = 0.0
    gran_total_jep = 0.0
    gran_total_reunido = 0.0
    
    for plan_nombre in planes_nombres:
        clientes_en_plan = [c for c in clientes if c.plan == plan_nombre and c.estado == "Activo"]
        cant_clientes = len(clientes_en_plan)
        precio_plan = planes_precios.get(plan_nombre, 0.0)
        megas_plan = planes_megas.get(plan_nombre, 0)
        generacion_estimada = cant_clientes * precio_plan
        
        # Desglose por método de pago para este plan
        efectivo_plan = 0.0
        pichincha_plan = 0.0
        jep_plan = 0.0
        for c in clientes_en_plan:
            for metodo_key, monto in pago_por_cliente_metodo.items():
                cid, met = metodo_key
                if cid == c.id:
                    if "JEP" in met:
                        jep_plan += monto
                    elif "PICHINCHA" in met:
                        pichincha_plan += monto
                    else:
                        efectivo_plan += monto
        
        total_reunido_plan = efectivo_plan + pichincha_plan + jep_plan
        
        resumen_data.append({
            "PLAN": plan_nombre,
            "MEGAS": f"{megas_plan}MB",
            "CANTIDAD CLIENTES": cant_clientes,
            "PRECIO PLAN": precio_plan,
            "GENERACION ESTIMADA": round(generacion_estimada, 2),
            "EFECTIVO": round(efectivo_plan, 2),
            "PICHINCHA": round(pichincha_plan, 2),
            "JEP": round(jep_plan, 2),
            "TOTAL REUNIDO": round(total_reunido_plan, 2)
        })
        
        gran_total_clientes += cant_clientes
        gran_total_estimado += generacion_estimada
        gran_total_efectivo += efectivo_plan
        gran_total_pichincha += pichincha_plan
        gran_total_jep += jep_plan
        gran_total_reunido += total_reunido_plan
    
    # Fila de TOTALES al final
    resumen_data.append({
        "PLAN": "TOTAL GENERAL",
        "MEGAS": "",
        "CANTIDAD CLIENTES": gran_total_clientes,
        "PRECIO PLAN": "",
        "GENERACION ESTIMADA": round(gran_total_estimado, 2),
        "EFECTIVO": round(gran_total_efectivo, 2),
        "PICHINCHA": round(gran_total_pichincha, 2),
        "JEP": round(gran_total_jep, 2),
        "TOTAL REUNIDO": round(gran_total_reunido, 2)
    })
    df_resumen = pd.DataFrame(resumen_data)
    
    # ── HOJA 3: EGRESOS ──
    egresos_mes = db.query(models.Egreso).filter(models.Egreso.mes == current_month).all()
    egresos_data = []
    for eg in egresos_mes:
        egresos_data.append({
            "FECHA": eg.fecha or "",
            "DESCRIPCION": eg.descripcion,
            "CATEGORIA": eg.categoria,
            "SUBCATEGORIA": eg.subcategoria or "",
            "METODO PAGO": eg.metodo_pago or "Efectivo",
            "MONTO": float(eg.monto or 0.0),
            "NOTAS": eg.notas or ""
        })
    df_egresos = pd.DataFrame(egresos_data)
    if df_egresos.empty:
        df_egresos = pd.DataFrame(columns=["FECHA", "DESCRIPCION", "CATEGORIA", "SUBCATEGORIA", "METODO PAGO", "MONTO", "NOTAS"])

    # ── HOJA 4: PROYECTOS ──
    proyectos = db.query(models.Proyecto).all()
    proyectos_data = []
    for p in proyectos:
        proyectos_data.append({
            "NOMBRE PROYECTO": p.nombre,
            "DESCRIPCION": p.descripcion or "",
            "MONTO TOTAL PRESUPUESTO": float(p.monto_total or 0.0),
            "MONTO INVERTIDO": float(p.monto_invertido or 0.0),
            "ESTADO": p.estado or "",
            "FECHA INICIO": p.fecha_inicio or "",
            "FECHA FIN": p.fecha_fin or ""
        })
    df_proyectos = pd.DataFrame(proyectos_data)
    if df_proyectos.empty:
        df_proyectos = pd.DataFrame(columns=["NOMBRE PROYECTO", "DESCRIPCION", "MONTO TOTAL PRESUPUESTO", "MONTO INVERTIDO", "ESTADO", "FECHA INICIO", "FECHA FIN"])

    # ── HOJA 5: COLCHÓN DE LA EMPRESA ──
    colchon = db.query(models.Colchon).all()
    colchon_data = []
    for c in colchon:
        colchon_data.append({
            "FECHA": c.fecha or "",
            "CONCEPTO/DESCRIPCION": c.descripcion,
            "MONTO": float(c.monto or 0.0)
        })
    df_colchon = pd.DataFrame(colchon_data)
    if df_colchon.empty:
        df_colchon = pd.DataFrame(columns=["FECHA", "CONCEPTO/DESCRIPCION", "MONTO"])

    os.makedirs("rutas_reportes", exist_ok=True)
    
    mes_actual = datetime.now().strftime("%m-%Y")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"Reporte_{mes_actual}_{timestamp}.xlsx"
    file_path = os.path.join("rutas_reportes", file_name)
    
    # Escribir a Excel con 5 hojas ordenadas
    with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
        df_clientes.to_excel(writer, sheet_name="Facturación Clientes", index=False)
        df_resumen.to_excel(writer, sheet_name="Resumen por Plan", index=False)
        df_egresos.to_excel(writer, sheet_name="Egresos", index=False)
        df_proyectos.to_excel(writer, sheet_name="Proyectos", index=False)
        df_colchon.to_excel(writer, sheet_name="Colchón de la Empresa", index=False)
    
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
        c.notas_pago = ""
        
        # 4. Sincronizar balances (total_pago reflejará el nuevo saldo consolidado)
        sync_cliente_balances(c, db)
        
    save_config({"ultimo_cierre": datetime.now().strftime("%Y-%m")})
    db.commit()
    
    return {"message": "Reporte generado. Campos de pago vaciados (saldos intactos).", "reporte_id": nuevo_reporte.id, "archivo": nuevo_reporte.archivo_ruta_excel}



@router.delete("/all", dependencies=[Depends(require_role(["administrador"]))])
def eliminar_todos_clientes(db: Session = Depends(get_db)):
    """
    Elimina TODOS los clientes de la base de datos.
    Solo accesible para administradores.
    ESTA ACCIÓN ES IRREVERSIBLE.
    """
    try:
        # Obtener todos los clientes
        clientes = db.query(models.Cliente).all()
        
        # Eliminar archivos de cédulas
        for cliente in clientes:
            # Eliminar archivos de cédula
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
        
        # Contar cuántos se van a eliminar
        count = len(clientes)
        
        # Eliminar registros relacionados en el orden correcto (respetando foreign keys)
        # 1. Eliminar hojas de ruta (tienen foreign key a clientes)
        db.query(models.HojaRuta).delete()
        
        # 2. Eliminar pagos (tienen foreign key a clientes)
        db.query(models.Pago).delete()
        
        # 3. Eliminar todos los clientes
        db.query(models.Cliente).delete()
        
        db.commit()
        
        # Resetear AUTO_INCREMENT
        try:
            from sqlalchemy import text
            is_postgresql = "postgresql" in str(engine.url).lower() or "psycopg" in str(engine.url).lower()
            is_mysql = "mysql" in str(engine.url).lower()
            
            if is_postgresql:
                # Para PostgreSQL (usando sequences)
                db.execute(text("ALTER SEQUENCE hoja_de_c__lculo_sin_t__tulo_numero_seq RESTART WITH 1"))
                db.execute(text("ALTER SEQUENCE hoja_ruta_id_seq RESTART WITH 1"))
                db.execute(text("ALTER SEQUENCE pago_id_seq RESTART WITH 1"))
            elif is_mysql:
                db.execute(text("ALTER TABLE hoja_de_c__lculo_sin_t__tulo AUTO_INCREMENT = 1"))
                db.execute(text("ALTER TABLE hoja_ruta AUTO_INCREMENT = 1"))
                db.execute(text("ALTER TABLE pago AUTO_INCREMENT = 1"))
            
            db.commit()
        except Exception as e:
            print(f"Aviso: No se pudo resetear AUTO_INCREMENT: {e}")
        
        return {"message": f"{count} clientes eliminados correctamente. Hojas de ruta y pagos asociados también fueron eliminados. La base de datos ha sido limpiada."}
    
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al eliminar clientes: {str(e)}")

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

    # Resetear AUTO_INCREMENT solo en MySQL/MariaDB
    try:
        from sqlalchemy import text
        is_mysql = "mysql" in str(engine.url).lower() if 'engine' in dir() else False
        if is_mysql:
            max_id_res = db.execute(text("SELECT MAX(NUMERO) FROM hoja_de_c__lculo_sin_t__tulo")).fetchone()
            max_id = max_id_res[0] if max_id_res and max_id_res[0] is not None else 0
            db.execute(text(f"ALTER TABLE hoja_de_c__lculo_sin_t__tulo AUTO_INCREMENT = {max_id + 1}"))
            db.commit()
    except Exception as e:
        print(f"Aviso: No se pudo resetear AUTO_INCREMENT: {e}")

    return {"message": "Cliente eliminado correctamente y ID liberado para el siguiente registro."}

@router.post("/upload-db", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def upload_database(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="El archivo debe ser un Excel (.xlsx, .xls)")
    
    try:
        # Leer el archivo Excel
        df = pd.read_excel(file.file)
        # Reemplazar valores nulos de pandas por None de Python para SQLAlchemy
        df = df.replace([pd.NA, float('nan')], None)
        
        count_nuevos = 0
        count_actualizados = 0
        errores = 0
        detalles_errores = []
        
        # Diccionario de columnas del Excel para búsqueda insensible a mayúsculas/espacios
        columnas_df = {col.upper().strip(): col for col in df.columns if isinstance(col, str)}
        
        # Mapeo exhaustivo de campos del modelo Cliente a posibles alias en el Excel
        FIELD_MAPPING = {
            "nombre": ["NOMBRE", "NOMBRES", "CLIENTE", "NOMBRE COMPLETO"],
            "cedula": ["CEDULA", "CI", "RUC", "IDENTIFICACION", "DNI"],
            "cedula_tipo": ["CEDULA_TIPO", "TIPO_CEDULA", "TIPO_IDENTIFICACION", "CEDULA TIPO"],
            "celular": ["CELULAR", "TELEFONO", "MOVIL", "CONTACTO", "CEL"],
            "correo": ["CORREO", "EMAIL", "MAIL"],
            "direccion": ["DIRECCION", "DIR", "DOMICILIO"],
            "nodo": ["NODO", "SECTOR", "NODO_ACCESO"],
            "parroquia": ["PARROQUIA", "CIUDAD", "CANTON", "PARROQUIA/CANTON"],
            "plan": ["PLAN", "VELOCIDAD", "PAQUETE", "PLAN INTERNET"],
            "fecha_firma": ["FECHA_FIRMA", "FECHA_CONTRATO", "FIRMA", "CONTRATO", "FECHA FIRMA"],
            "estado": ["ESTADO", "STATUS", "ESTADO_CLIENTE"],
            "puerto": ["PUERTO", "PORT", "NAP_PORT", "PUERTO_PON"],
            "ont": ["ONT", "SCRIPT_ONT", "COMANDO_ONT"],
            "servicio": ["SERVICIO", "SCRIPT_SERVICIO", "COMANDO_SERVICIO"],
            "breach": ["BREACH", "SCRIPT_BREACH"],
            "id_port": ["ID_PORT", "ONT_ID", "ID PORT"],
            "service_port": ["SERVICE_PORT", "SERVICE PORT", "SP"],
            "ip": ["IP", "DIRECCION_IP", "IP_ADDRESS"],
            "dispositivo": ["DISPOSITIVO", "EQUIPO", "ROUTER", "ONU"],
            "potencia": ["POTENCIA", "DBM", "SEÑAL", "POTENCIA_RX"],
            "nap": ["NAP", "CAJA_NAP", "CAJA", "NUMERO_CAJA"],
            "ubicacion": ["UBICACION", "COORDENADAS", "LAT_LONG", "GPS"],
            "tecnico": ["TECNICO", "INSTALADOR_TECNICO", "TECNICO_RESPONSABLE"],
            "activador": ["ACTIVADOR", "QUIEN_ACTIVA"],
            "red": ["RED", "VLAN", "SEGMENTO"],
            "clave": ["CLAVE", "PASSWORD_WIFI", "CLAVE_ONT"],
            "mac": ["MAC", "MAC_ADDRESS", "PON_SN", "SERIAL"],
            "instalation_date": ["INSTALATION_DATE", "FECHA_INSTALACION", "FECHA_ACTIVA", "INSTALATION DATE"],
            "tiempo": ["TIEMPO", "DURACION_CONTRATO", "MESES", "CONTRATO_MESES"],
            "arrienda": ["ARRIENDA", "ARRIENDO"],
            "cuenta": ["CUENTA", "NUM_CUENTA"],
            "facturas": ["FACTURAS", "FACTURA", "NUM_FACTURA"],
            "internet_payment": ["INTERNET_PAYMENT", "INTERNET PAYMENT", "PAGO_INTERNET", "INTERNET PAY"],
            "app": ["APP", "USA_APP"],
            "payment_date": ["PAYMENT_DATE", "PAYMENT DATE", "FECHA_PAGO"],
            "client_payment_date": ["CLIENT_PAYMENT_DATE", "CLIENT PAYMENT DATE"],
            "bank": ["BANK", "BANCO", "ENTIDAD_FINANCIERA"],
            "cod": ["COD", "CODIGO_PAGO", "CODIGO_CLIENTE"],
            "plus": ["PLUS", "ADICIONAL_MENSUAL", "TV_PLUS", "VALOR_PLUS", "IPTV"],
            "bank_plus": ["BANK_PLUS", "BANCO_TV", "BANK PLUS"],
            "adicional": ["ADICIONAL", "MONTO_ADICIONAL", "CARGO_EXTRA"],
            "comentarios": ["COMENTARIOS", "NOTAS", "OBS", "DESCRIPCION"],
            "observaciones": ["OBSERVACIONES"],
            "notas_pago": ["NOTAS_PAGO", "OBSERVACION_PAGO"],
            "tercera_edad": ["TERCERA_EDAD", "DISCAPACIDAD", "MAYOR_EDAD"],
            "precio_plan_especial": ["PRECIO_PLAN_ESPECIAL", "VALOR_ESPECIAL", "TARIFA_REDUCIDA"],
            "saldo": ["SALDO", "DEUDA", "PENDIENTE", "SALDO_ANTERIOR", "TOTAL"],
            "pago_mensual": ["PAGO_MENSUAL", "COBRO_MES", "RECAUDACION"],
            "iptv_activar": ["IPTV_ACTIVAR", "ACTIVAR_IPTV"],
            "iptv_user": ["IPTV_USER", "USUARIO_IPTV"],
            "iptv_pass": ["IPTV_PASS", "CLAVE_IPTV"],
            "iptv_bouquets": ["IPTV_BOUQUETS", "PAQUETES_IPTV"],
            "iptv_exp_date": ["IPTV_EXP_DATE", "EXPIRACION_IPTV"],
            "iptv_max_conn": ["IPTV_MAX_CONN", "PANTALLAS_IPTV", "CONEXIONES"],
            "iptv_outputs": ["IPTV_OUTPUTS", "SALIDAS_IPTV"],
            "iptv_notes": ["IPTV_NOTES", "NOTAS_IPTV"],
            "iptv_member_id": ["IPTV_MEMBER_ID", "ID_SOCIO_IPTV"]
        }

        # Tipos de campos para conversión correcta
        NUMERIC_FIELDS = {"saldo", "precio_plan_especial", "pago_mensual", "total_pago", "plus_pagado", "adicional_pagado"}
        INT_FIELDS = {"id", "iptv_max_conn", "iptv_member_id"}
        BOOL_FIELDS = {"tercera_edad", "iptv_activar"}

        def get_raw_val(row, aliases):
            for alias in aliases:
                a_up = alias.upper().strip()
                if a_up in columnas_df:
                    val = row[columnas_df[a_up]]
                    if pd.notnull(val):
                        return val
            return None

        # Optimización: Obtener IDs existentes UNA SOLA VEZ antes del bucle
        ids_query = db.query(models.Cliente.id).order_by(models.Cliente.id).all()
        ids_existentes = set(i[0] for i in ids_query)
        proximo_id_hueco = 1

        for index, row in df.iterrows():
            try:
                # Validar nombre (Obligatorio)
                nombre_raw = get_raw_val(row, FIELD_MAPPING["nombre"])
                if not nombre_raw:
                    continue
                nombre = str(nombre_raw).strip()
                    
                cedula_raw = get_raw_val(row, FIELD_MAPPING["cedula"])
                cedula = str(cedula_raw).strip() if cedula_raw else None
                
                # Buscar cliente por Cédula o por Nombre
                cliente = None
                if cedula:
                    cliente = db.query(models.Cliente).filter(models.Cliente.cedula == cedula).first()
                if not cliente:
                    cliente = db.query(models.Cliente).filter(models.Cliente.nombre == nombre).first()
                
                if not cliente:
                    # Lógica de IDs para llenar huecos de forma eficiente
                    while proximo_id_hueco in ids_existentes:
                        proximo_id_hueco += 1
                    
                    cliente = models.Cliente(id=proximo_id_hueco, nombre=nombre)
                    ids_existentes.add(proximo_id_hueco)
                    db.add(cliente)
                    count_nuevos += 1
                else:
                    count_actualizados += 1

                # Mapear todos los campos del Excel al modelo
                for field, aliases in FIELD_MAPPING.items():
                    val = get_raw_val(row, aliases)
                    if val is None:
                        continue
                    
                    if field in NUMERIC_FIELDS:
                        setattr(cliente, field, try_float(val))
                    elif field in INT_FIELDS:
                        try:
                            setattr(cliente, field, int(float(val)))
                        except:
                            pass
                    elif field in BOOL_FIELDS:
                        if isinstance(val, bool):
                            setattr(cliente, field, val)
                        else:
                            s_val = str(val).upper().strip()
                            setattr(cliente, field, s_val in ["SI", "S", "TRUE", "1", "ACTIVO", "YES"])
                    elif field == "mac":
                        # Sanitizar MAC: solo letras y números en mayúsculas
                        import re
                        mac_clean = re.sub(r'[^a-zA-Z0-9]', '', str(val)).upper()
                        cliente.mac = mac_clean
                    else:
                        # Texto / String
                        clean_val = clean_int_string_value(val)
                        if field == "cedula":
                            if clean_val and clean_val.isdigit() and len(clean_val) == 9:
                                clean_val = "0" + clean_val
                        elif field == "celular":
                            if clean_val and clean_val.isdigit() and len(clean_val) == 9 and clean_val.startswith("9"):
                                clean_val = "0" + clean_val
                        setattr(cliente, field, clean_val)
                
                # Recalcular balances (Importante para que total_pago sea correcto)
                sync_cliente_balances(cliente, db)
                
                # Commit individual por cada cliente procesado exitosamente
                db.commit()

            except Exception as e:
                db.rollback()
                errores += 1
                import traceback
                error_detail = str(e)
                # Si el error es muy largo, lo recortamos
                if len(error_detail) > 200:
                    error_detail = error_detail[:200] + "..."
                error_msg = f"Fila {index + 2} ({nombre if 'nombre' in locals() else 'S/N'}): {error_detail}"
                print(f"Error procesando: {error_msg}")
                # Log traceback completo a la consola para depuración profunda
                traceback.print_exc()
                detalles_errores.append(error_msg)
                
        return {
            "message": f"Importación completada. {count_nuevos} nuevos, {count_actualizados} actualizados, {errores} errores.",
            "nuevos": count_nuevos,
            "actualizados": count_actualizados,
            "errores": errores,
            "total_procesados": len(df),
            "detalles": detalles_errores[:50] # Mostramos hasta 50 errores para mejor diagnóstico
        }
        
    except Exception as e:
        db.rollback()
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error crítico procesando Excel: {str(e)}")




