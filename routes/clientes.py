from database import engine
# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile
import os
import shutil
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import Session
from typing import List
import models, schemas
from database import get_db
from datetime import datetime
from .auth import get_current_user, require_role
from services.smart_parser import parse_unstructured_client_data

import logging
logger = logging.getLogger("opsatel.routes.clientes")

router = APIRouter(prefix="/clientes", tags=["clientes"])

_stats_cache = None
_stats_cache_time = None

import traceback
from datetime import datetime
from config_manager import get_config, save_config
import calendar

import unicodedata

def is_nodo_sayausi(nodo_val) -> bool:
    if not nodo_val:
        return False
    s = unicodedata.normalize('NFD', str(nodo_val)).encode('ascii', 'ignore').decode('utf-8').upper()
    return "SAYAUSI" in s

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
    if getattr(cliente, 'cortesia_total', False):
        cliente.total_pago = 0.00
        cliente.saldo = 0.00
        cliente.plus = "0"
        cliente.adicional = ""
        return

    if getattr(cliente, 'mantenimiento', False):
        cliente.saldo = 10.00

    plus = try_float(cliente.plus)
    saldo = float(cliente.saldo or 0)
    
    # El Pendiente Principal (total_pago) SEPARA el cargo adicional según requerimiento v1.2.
    # El adicional es un servicio aparte que NO afecta la deuda de internet/iptv en Pagos y Cobros.
    cliente.total_pago = saldo + plus

@router.get("/pendientes-count")
def get_pendientes_count(db: Session = Depends(get_db)):
    count = db.query(models.Cliente).filter(models.Cliente.estado == "Pendiente").count()
    return {"count": count}

# El sistema ahora utiliza exclusivamente la tabla 'planes_internet' de la base de datos 
# para obtener los precios vigentes, permitiendo configurarlos desde el panel administrativo.

@router.get("/")
def listar_clientes(db: Session = Depends(get_db)):
    try:
        from libreqos_models import ClientQoSState
        data = db.query(models.Cliente).all()
        
        # Mapear estados QoS de manera eficiente
        qos_map = {state.cliente_id: state.status for state in db.query(ClientQoSState).all()}
        
        for c in data:
            # Asociar el estado QoS al objeto
            c.qos_status = qos_map.get(c.id, "NOT_CONFIGURED")
            
        return data
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/dashboard-stats")
def get_dashboard_stats(db: Session = Depends(get_db)):
    global _stats_cache, _stats_cache_time
    now = datetime.now()
    if _stats_cache is not None and _stats_cache_time is not None and (now - _stats_cache_time).total_seconds() < 300:
        return _stats_cache

    # pyrefly: ignore [missing-import]
    from sqlalchemy import func
    # Consulta SQL optimizada agrupada por método de pago
    results = db.query(
        models.Pago.metodo_pago,
        func.sum(models.Pago.monto).label("total"),
        func.sum(models.Pago.monto_internet).label("internet"),
        func.sum(models.Pago.monto_plus).label("plus")
    ).filter(
        models.Pago.anulado == False,
        models.Pago.estado == "Completado"
    ).group_by(models.Pago.metodo_pago).all()
    
    # Inicializamos contadores
    internet = {"Efectivo": 0.0, "Pichincha": 0.0, "JEP": 0.0}
    plus = {"Efectivo": 0.0, "Pichincha": 0.0}
    
    for r in results:
        metodo = (r.metodo_pago or "").upper()
        m_total = float(r.total or 0)
        m_internet = float(r.internet or 0)
        m_plus = float(r.plus or 0)
            
        # Reglas Internet
        if "JEP" in metodo:
            internet["JEP"] += m_total
        elif "PICHINCHA" in metodo:
            internet["Pichincha"] += m_internet
            plus["Pichincha"] += m_plus
        else:
            internet["Efectivo"] += m_internet
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
            
    _stats_cache = {"internet": internet, "plus": plus, "finanzas_globales": finanzas_globales}
    _stats_cache_time = now
    return _stats_cache

@router.post("/parse-smart", dependencies=[Depends(require_role(["administrador", "secretario", "tecnico"]))])
def parse_smart_client_data(request: schemas.SmartParseRequest, db: Session = Depends(get_db)):
    try:
        # Obtener entidades de la base de datos para fuzzy mapping
        valid_nodos = [n[0] for n in db.query(models.Nodo.nombre).filter(models.Nodo.nombre != None).all()]
        valid_parroquias = [p[0] for p in db.query(models.Parroquia.nombre).filter(models.Parroquia.nombre != None).all()]
        valid_planes = [pl[0] for pl in db.query(models.PlanInternet.nombre).filter(models.PlanInternet.nombre != None).all()]
        
        parsed_data = parse_unstructured_client_data(
            text=request.text,
            valid_nodos=valid_nodos,
            valid_parroquias=valid_parroquias,
            valid_planes=valid_planes
        )
        return parsed_data
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Error al interpretar los datos con Inteligencia Artificial: {str(e)}"
        )

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

    # Lógica IPTV auto-generación de credenciales
    iptv_act = False
    iptv_u = None
    iptv_p = None
    iptv_max = 0
    iptv_b = "[]"
    iptv_out = "[]"

    if cliente.tv_tipo == "IPTV":
        iptv_act = True
        # Generar nombre de usuario sugerido: ID + Primer Apellido + Primera Letra Nombre
        name_parts = (cliente.nombre or "").strip().split(" ")
        name_parts = [p for p in name_parts if len(p) > 0]
        generated_user = str(nuevo_id)
        if len(name_parts) >= 2:
            generated_user += name_parts[0].lower() + name_parts[1][0].lower()
        elif len(name_parts) == 1:
            generated_user += name_parts[0].lower()
        
        iptv_u = generated_user
        iptv_p = "TV" + str(datetime.now().year) + ".@"
        iptv_max = cliente.iptv_max_conn or 1
        iptv_b = "[1,2,5]"
        iptv_out = "[1,2]"
            
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
        iptv_max_conn=iptv_max,
        cedula_tipo=cliente.cedula_tipo,
        ubicacion=cliente.ubicacion,
        fecha_firma=cliente.fecha_firma,
        tiempo=cliente.tiempo,
        tercera_edad=bool(cliente.tercera_edad or cliente.plan_corporativo),
        precio_plan_especial=cliente.precio_plan_especial,
        mantenimiento=bool(cliente.mantenimiento),
        comentarios=cliente.comentarios,
        estado="Activo",
        iptv_activar=iptv_act,
        iptv_user=iptv_u,
        iptv_pass=iptv_p,
        iptv_bouquets=iptv_b,
        iptv_outputs=iptv_out,
        iptv_exp_date="Nunca",
        tv_tipo=cliente.tv_tipo or "Ninguno"
    )
    try:
        db.add(db_cliente)
        # Sincronizamos balances para que el total_pago se calcule (Costo Plan + Plus)
        sync_cliente_balances(db_cliente, db)
        db.commit()
        db.refresh(db_cliente)

        # Si requiere IPTV, realizar la creación en el panel de fondo de forma asíncrona
        if iptv_act:
            import asyncio
            from services.xui_service import create_xui_user
            async def run_xui_creation():
                try:
                    res = await create_xui_user(
                        username=iptv_u,
                        password=iptv_p,
                        max_connections=iptv_max,
                        bouquets=["1", "2", "5"],
                        allowed_outputs=["1", "2"]
                    )
                    print(f"IPTV: Cuenta de XUI creada exitosamente para {iptv_u}. Detalle: {res}")
                except Exception as xui_err:
                    print(f"ERROR IPTV: Falló la creación en panel XUI para {iptv_u}: {xui_err}")

            # Correr en background para no ralentizar la respuesta del API principal
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(run_xui_creation())
            except RuntimeError:
                asyncio.run(run_xui_creation())

        return db_cliente
    except Exception as e:
        db.rollback()
        import traceback
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Error en la base de datos al registrar el cliente: {str(e)}"
        )


@router.post("/{id}/upload-cedula", dependencies=[Depends(require_role(["administrador", "secretario", "tecnico"]))])
async def upload_cedula(id: int, frontal: UploadFile = File(None), posterior: UploadFile = File(None), db: Session = Depends(get_db)):
    cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    upload_dir = "uploads/cedulas"
    os.makedirs(upload_dir, exist_ok=True)
    
    if frontal:
        ext = os.path.splitext(frontal.filename)[1] if frontal.filename else ""
        if not ext:
            ctype = str(getattr(frontal, 'content_type', '') or '').lower()
            if 'jpeg' in ctype or 'jpg' in ctype:
                ext = ".jpg"
            elif 'webp' in ctype:
                ext = ".webp"
            elif 'gif' in ctype:
                ext = ".gif"
            else:
                ext = ".png"
        file_path = f"{upload_dir}/frontal_{id}_{int(datetime.now().timestamp())}{ext}"
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(frontal.file, buffer)
        cliente.cedula_frontal = f"/{file_path}"
        
    if posterior:
        ext = os.path.splitext(posterior.filename)[1] if posterior.filename else ""
        if not ext:
            ctype = str(getattr(posterior, 'content_type', '') or '').lower()
            if 'jpeg' in ctype or 'jpg' in ctype:
                ext = ".jpg"
            elif 'webp' in ctype:
                ext = ".webp"
            elif 'gif' in ctype:
                ext = ".gif"
            else:
                ext = ".png"
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
    is_sayausi = is_nodo_sayausi(nodo)
    
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


@router.post("/{id}/borrar-de-olt", dependencies=[Depends(require_role(["administrador", "tecnico"]))])
def borrar_cliente_de_olt(id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """
    Borra al cliente de la OLT Huawei y lo regresa al estado 'En Activación'.

    Secuencia OLT ejecutada por el worker:
      1. (config)# undo service-port <service_port>
      2. interface gpon 0/0
      3. (config-if-gpon-0/0)# ont delete <puerto_num> <id_port>

    Tras encolar la tarea, el cliente queda en 'En Activación' con sus
    campos OLT borrados para que pueda ser re-activado correctamente.
    """
    import json as _json
    # pyrefly: ignore [missing-import]
    from sqlalchemy import or_ as _or

    cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    # Validar que el cliente tenga datos OLT para poder borrar
    if not cliente.id_port and not cliente.service_port:
        raise HTTPException(
            status_code=400,
            detail="El cliente no tiene datos OLT registrados (id_port / service_port). No se puede borrar de la OLT."
        )

    # Extraer número de puerto desde campo "Puerto 8" → "8"
    puerto_raw = str(cliente.puerto or "0")
    import re as _re
    m = _re.search(r'\d+', puerto_raw)
    puerto_num = m.group() if m else "0"

    # Construir gpon_port a partir del puerto numérico
    # Por defecto la OLT de Baños usa 0/0/X; si el nodo es SAYAUSI usa 0/1/X
    is_sayausi = is_nodo_sayausi(cliente.nodo)
    if is_sayausi:
        gpon_port = f"0/1/{puerto_num}"
    else:
        gpon_port = f"0/0/{puerto_num}"

    ont_id = str(cliente.id_port or "0").strip()
    service_port = str(cliente.service_port or "").strip()

    # Obtener OLT configurada para el nodo del cliente
    olt_config = db.query(models.OLTConfig).filter(
        _or(
            models.OLTConfig.nodo_asociado == cliente.nodo,
            models.OLTConfig.nodo_asociado.ilike("%SAYAUS%") if is_sayausi else models.OLTConfig.nodo_asociado.ilike("%BAN%"),
            models.OLTConfig.nodo_asociado == None
        ),
        models.OLTConfig.active == True
    ).first()

    if not olt_config:
        raise HTTPException(
            status_code=500,
            detail=f"No hay OLT activa configurada para el nodo '{cliente.nodo}'. Configura una OLT primero."
        )

    # Construir payload para la tarea remove_ont
    payload = {
        "gpon_port": gpon_port,
        "ont_id": ont_id,
        "service_port": service_port,
        # mac es requerido por el sanitizador para algunas acciones; para remove_ont se ignora
        # pero lo pasamos vacío para no romper validaciones genéricas
        "mac": str(cliente.mac or "000000000000").replace(":", "").replace("-", "") or "000000000000",
    }

    # Crear la tarea en la cola OLT
    task = models.OLTTask(
        cliente_id=id,
        olt_id=olt_config.id,
        action="remove_ont",
        payload=_json.dumps(payload),
        status="pending",
        priority=10,  # Alta prioridad para borrar rápido
        created_by=current_user.username,
        created_at=datetime.now(),
    )
    db.add(task)
    db.flush()  # Obtener el ID generado

    # ── Resetear cliente a "En Activación" y limpiar campos OLT ──────────
    cliente.estado = "En Activación"
    cliente.service_port = None
    cliente.id_port = None
    cliente.ont = None
    cliente.servicio = None
    cliente.breach = None
    cliente.mac = None
    cliente.ip = None
    cliente.potencia = None
    cliente.instalation_date = None

    db.commit()
    db.refresh(task)

    return {
        "message": (
            f"✅ Tarea de borrado encolada (ID tarea: {task.id}). "
            f"El cliente '{cliente.nombre}' fue regresado a 'En Activación'. "
            f"La OLT ejecutará: undo service-port {service_port} → ont delete {puerto_num} {ont_id}."
        ),
        "task_id": task.id,
        "cliente_estado": cliente.estado,
        "gpon_port": gpon_port,
        "ont_id": ont_id,
        "service_port": service_port,
    }

@router.post("/{id}/suspender-mikrotik", dependencies=[Depends(require_role(["administrador", "tecnico", "secretario"]))])
def suspender_cliente_mikrotik(id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """
    Agrega al cliente a la lista de suspendidos en MikroTik:
    - Baños: list=CLIENTES_SUSPENDIDOS_POR_PAGO
    - Sayausí: list=CLIENTES_SUSPENDIDOS_POR_PAGOS
    Comando ejecutado en MikroTik:
    /ip firewall address-list add address={ip} comment="{nombre}" list={list_name}
    """
    from sqlalchemy import or_ as _or
    from network.adapters.mikrotik import MikroTikAdapter, MikroTikAdapterError

    cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    if not cliente.ip:
        raise HTTPException(status_code=400, detail=f"El cliente '{cliente.nombre}' no tiene una IP asignada para suspender en MikroTik.")

    # Determinar si es Sayausí o Baños
    is_sayausi = is_nodo_sayausi(cliente.nodo)
    list_name = "CLIENTES_SUSPENDIDOS_POR_PAGOS" if is_sayausi else "CLIENTES_SUSPENDIDOS_POR_PAGO"

    # Buscar OLT / MikroTik Config activa para el nodo
    olt_config = db.query(models.OLTConfig).filter(
        _or(
            models.OLTConfig.nodo_asociado == cliente.nodo,
            models.OLTConfig.nodo_asociado.ilike("%SAYAUS%") if is_sayausi else models.OLTConfig.nodo_asociado.ilike("%BAN%"),
            models.OLTConfig.nodo_asociado == None
        ),
        models.OLTConfig.active == True
    ).first()

    if not olt_config or not olt_config.mikrotik_host:
        raise HTTPException(status_code=503, detail=f"No hay MikroTik activo o configurado para el nodo '{cliente.nodo}'.")

    try:
        with MikroTikAdapter(
            host=olt_config.mikrotik_host,
            username=olt_config.mikrotik_username,
            password=olt_config.mikrotik_password,
            port=olt_config.mikrotik_port or 8728
        ) as mt:
            mt.add_to_address_list(
                address=cliente.ip,
                comment=cliente.nombre or f"Cliente #{cliente.id}",
                list_name=list_name
            )

        # Actualizar estado del cliente a Suspendido
        cliente.estado = "Suspendido"
        db.commit()

        # Auditoría
        import observability as obs
        obs.log_audit_event_async(
            accion="SUSPENDER_CLIENTE_MIKROTIK",
            modulo="clientes",
            usuario=current_user.username,
            entidad_tipo="Cliente",
            entidad_id=str(cliente.id),
            detalles=f"Cliente {cliente.nombre} ({cliente.ip}) agregado a list '{list_name}' en MikroTik {olt_config.mikrotik_host}"
        )

        return {
            "success": True,
            "message": f"Servicio suspendido exitosamente para '{cliente.nombre}' (IP: {cliente.ip}) en MikroTik '{list_name}'.",
            "estado": cliente.estado,
            "list_name": list_name,
            "ip": cliente.ip
        }
    except MikroTikAdapterError as mt_err:
        logger.error(f"Error MikroTik al suspender cliente {cliente.id}: {mt_err}")
        raise HTTPException(status_code=500, detail=f"Error MikroTik ({olt_config.mikrotik_host}): {str(mt_err)}")
    except Exception as e:
        logger.error(f"Error al suspender cliente {cliente.id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error al suspender servicio: {str(e)}")

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
    Exporta TODAS las tablas de la base de datos a un único archivo Excel (.xlsx) con múltiples pestañas,
    garantizando la exportación completa e íntegra de todos los datos existentes en el sistema (clientes en
    cualquier estado, pagos, saldos, call center, balance, asistencias, configuraciones, etc.).
    """
    try:
        import io
        import re
        import json
        from decimal import Decimal
        from datetime import datetime, date
        import pandas as pd
        from sqlalchemy import inspect, text
        from fastapi.responses import StreamingResponse
        
        # Mapeo de nombres de tablas de la base de datos a títulos legibles en español
        TABLE_SHEET_NAMES = {
            "hoja_de_c__lculo_sin_t__tulo": "Clientes",
            "historial_pagos": "Historial de Pagos",
            "clientes_extras": "Clientes Extras",
            "historial_pagos_extras": "Pagos Extras",
            "call_center_tickets": "Tickets Call Center",
            "tickets_desarrollo": "Tickets de Desarrollo",
            "hoja_ruta": "Hojas de Ruta",
            "egresos_balance": "Egresos Balance",
            "gastos_fijos_balance": "Gastos Fijos",
            "proyectos_balance": "Proyectos",
            "proyecto_pagos": "Proyecto Pagos",
            "gastos_proyecto": "Gastos Proyectos",
            "colchon_balance": "Colchón de Reserva",
            "asistencias": "Asistencia Personal",
            "horarios_empleados": "Horarios de Empleados",
            "turnos_cajas": "Turnos de Caja",
            "finanzas_base": "Finanzas Base",
            "nodos": "Nodos",
            "planes_internet": "Planes de Internet",
            "bancos": "Bancos",
            "puertos": "Puertos",
            "parroquias": "Parroquias",
            "cajas_nap": "Cajas NAP",
            "clientes_eliminados": "Clientes Eliminados",
            "reportes_mensuales": "Reportes Mensuales",
            "usuarios": "Usuarios del Sistema",
            "whatsapp_historial": "Historial WhatsApp",
            "whatsapp_configuracion": "Configuración WhatsApp",
            "whatsapp_administradores": "Administradores WhatsApp",
            "log_facturacion": "Logs de Facturación",
            "olt_config": "Configuración OLT",
            "olt_tasks": "Tareas OLT",
            "olt_task_logs": "Logs Tareas OLT",
            "olt_power_checks": "Potencia OLT",
            "audit_events": "Eventos Auditoría",
            "network_commands": "Comandos Red",
            "worker_heartbeats": "Workers Heartbeat",
            "inventory_service_ports": "Puertos Inventario",
            "inventory_ont_ids": "IDs ONT Inventario",
            "inventory_ip_pools": "Pools IP Inventario",
            "discovered_onts": "ONTs Descubiertas",
            "discovered_service_ports": "Puertos Descubiertos",
            "discovered_boards": "Tarjetas Descubiertas",
            "libreqos_servers": "Servidores LibreQoS",
            "client_qos_state": "Estados QoS Clientes",
            "libreqos_audit": "Auditoría LibreQoS",
            "libreqos_jobs": "Trabajos LibreQoS"
        }

        # 1. Obtener todas las tablas directamente del motor de la base de datos
        inspector = inspect(db.bind)
        db_tables = inspector.get_table_names()
        
        # 2. Agregar cualquier tabla definida en los modelos que no aparezca aún en inspector
        all_tables = list(db_tables)
        if hasattr(models.Base, 'metadata') and hasattr(models.Base.metadata, 'tables'):
            for table_name in models.Base.metadata.tables.keys():
                if table_name not in all_tables:
                    all_tables.append(table_name)
                    
        # Priorizar la pestaña "Clientes" al inicio si existe
        if "hoja_de_c__lculo_sin_t__tulo" in all_tables:
            all_tables.remove("hoja_de_c__lculo_sin_t__tulo")
            all_tables.insert(0, "hoja_de_c__lculo_sin_t__tulo")
            
        output = io.BytesIO()
        used_sheet_names = set()

        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            sheets_written = 0
            quote_fn = db.bind.dialect.identifier_preparer.quote
            
            for table_name in all_tables:
                try:
                    quoted_name = quote_fn(table_name)
                    query_str = f"SELECT * FROM {quoted_name}"
                    result = db.execute(text(query_str))
                    columns = list(result.keys())
                    raw_rows = result.mappings().all()

                    processed_rows = []
                    for row in raw_rows:
                        d = {}
                        for col, val in row.items():
                            if isinstance(val, (datetime, date)):
                                val = val.strftime("%Y-%m-%d %H:%M:%S") if hasattr(val, "strftime") else str(val)
                            elif isinstance(val, Decimal):
                                val = float(val)
                            elif isinstance(val, (dict, list)):
                                val = json.dumps(val, default=str, ensure_ascii=False)
                            elif isinstance(val, bytes):
                                val = val.decode("utf-8", errors="ignore")
                            d[col] = val
                        processed_rows.append(d)

                    if processed_rows:
                        df = pd.DataFrame(processed_rows)
                    else:
                        df = pd.DataFrame(columns=columns)

                    # Determinar nombre legible de la pestaña
                    display_name = TABLE_SHEET_NAMES.get(table_name, table_name.replace("_", " ").title())
                    sanitized_name = re.sub(r'[\\/*?:\[\]]', '_', display_name)
                    base_sheet_name = sanitized_name[:31]

                    # Evitar nombres de pestañas duplicados en Excel
                    final_sheet_name = base_sheet_name
                    counter = 1
                    while final_sheet_name in used_sheet_names:
                        suffix = f"_{counter}"
                        final_sheet_name = f"{base_sheet_name[:31 - len(suffix)]}{suffix}"
                        counter += 1

                    used_sheet_names.add(final_sheet_name)
                    df.to_excel(writer, sheet_name=final_sheet_name, index=False)
                    sheets_written += 1
                except Exception as sheet_err:
                    print(f"Aviso: No se pudo exportar la tabla '{table_name}': {sheet_err}")
                    continue

            # Garantizar que al menos una hoja exista para evitar error de openpyxl
            if sheets_written == 0:
                pd.DataFrame({"Info": ["No se encontraron tablas exportables"]}).to_excel(writer, sheet_name="Info", index=False)

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


@router.get("/eliminados", dependencies=[Depends(require_role(["administrador"]))])
def listar_clientes_eliminados(db: Session = Depends(get_db)):
    """
    Lista el historial de clientes eliminados.
    """
    try:
        data = db.query(models.ClienteEliminado).order_by(models.ClienteEliminado.deleted_at.desc()).all()
        return data
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error al listar historial de eliminados: {str(e)}")


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

    # Guardar valores anteriores para comparar
    estado_prev = cliente.estado
    ip_prev = cliente.ip
    plan_prev = cliente.plan

    for var, value in vars(data).items():
        if value is not None:
            setattr(cliente, var, value)
            
    sync_cliente_balances(cliente, db)
    db.commit()

    # Encolar tareas en LibreQoS basadas en los cambios detectados
    try:
        from services.libreqos_manager import LibreQoSManager
        correlation_id = f"up_client_{id}_{int(datetime.now().timestamp())}"
        
        # Consultar estado actual en la base de datos de QoS
        qos_state = LibreQoSManager.get_or_create_qos_state(id, db)

        # Caso 1: Cambio de estado a Suspendido
        if cliente.estado == "Suspendido" and estado_prev != "Suspendido":
            LibreQoSManager.enqueue_job("SUSPEND", id, db, correlation_id, "CLIENT_UPDATE_API")
        # Caso 2: Reactivación (de Suspendido a Activo)
        elif cliente.estado == "Activo" and estado_prev == "Suspendido":
            LibreQoSManager.enqueue_job("RESUME", id, db, correlation_id, "CLIENT_UPDATE_API")
        # Caso 3: Aprovisionamiento inicial (Pasa a Activo por primera vez o no ha sido aplicado exitosamente)
        elif cliente.estado == "Activo" and (estado_prev != "Activo" or qos_state.status != "APPLIED") and cliente.ip:
            LibreQoSManager.enqueue_job("PROVISION", id, db, correlation_id, "CLIENT_UPDATE_API")
        # Caso 4: Cambio de IP o cambio de Plan (velocidades) cuando ya está Activo y aplicado
        elif cliente.estado == "Activo" and estado_prev == "Activo" and qos_state.status == "APPLIED" and (cliente.ip != ip_prev or cliente.plan != plan_prev):
            LibreQoSManager.enqueue_job("UPDATE", id, db, correlation_id, "CLIENT_UPDATE_API")
    except Exception as lq_err:
        print(f"Aviso: No se pudo encolar la tarea en LibreQoS tras actualización: {lq_err}")

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
        cliente.instalation_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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
            
            if getattr(cliente, 'mantenimiento', False):
                tarifa_base = 10.00
            elif cliente.tercera_edad and cliente.precio_plan_especial:
                tarifa_base = float(cliente.precio_plan_especial)
            else:
                plan_info = db.query(models.PlanInternet).filter(models.PlanInternet.nombre == cliente.plan).first()
                tarifa_base = float(plan_info.precio or 0) if plan_info else 0.00
            
            plus_base = try_float(cliente.plus)
            
            if total_days_in_month > 0:
                prorated_internet = (tarifa_base / total_days_in_month) * active_days
                prorated_plus = (plus_base / total_days_in_month) * active_days
                cliente.saldo = round(prorated_internet, 2)
                cliente.plus = str(round(prorated_plus, 2))
                sync_cliente_balances(cliente, db)
        except Exception as e:
            print(f"Error calculando prorrateo: {e}")

        db.commit()

        # Encolar en LibreQoS de forma automática al completar activación técnica
        try:
            from services.libreqos_manager import LibreQoSManager
            lq_cid = f"ct_{id}_{int(datetime.now().timestamp())}"
            LibreQoSManager.enqueue_job("PROVISION", id, db, lq_cid, "TECHNICAL_CONFIG_AUTO")
        except Exception as lq_err:
            print(f"Error al encolar LibreQoS en actualizacion tecnica: {lq_err}")

        return {"message": "Configuración técnica guardada, cliente ahora Activo (con pago prorrateado) y con fecha de instalación registrada y encolado en LibreQoS."}
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
    
    old_internet_payment = cliente.internet_payment

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

@router.post("/{id}/pagar")
def registrar_pago(
    id: int, 
    pago_data: schemas.PagoCreate, 
    db: Session = Depends(get_db), 
    current_user: models.Usuario = Depends(require_role(["administrador", "secretario"]))
):
    try:
        cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
        if not cliente:
            raise HTTPException(status_code=404, detail="Cliente no encontrado")

        # Obtener turno de caja abierto (si existe)
        turno = db.query(models.TurnoCaja).filter(
            models.TurnoCaja.usuario_id == current_user.id,
            models.TurnoCaja.estado == "Abierto"
        ).first()
        turno_id = turno.id if turno else None

        # Extraemos montos reales pagados (Cash)
        m_total_cash = float(pago_data.monto)
        m_adic_cash = try_float(pago_data.adicional)
        m_plus_cash = try_float(pago_data.plus)
        if min(m_total_cash, m_adic_cash, m_plus_cash) < 0:
            raise HTTPException(status_code=400, detail="Los montos de pago no pueden ser negativos")

        componentes_cash = m_plus_cash + m_adic_cash
        if componentes_cash > m_total_cash + 0.01:
            raise HTTPException(
                status_code=400,
                detail="La suma de Plus y Adicional no puede superar el monto total recibido"
            )
        m_internet_cash = round(m_total_cash - componentes_cash, 2)

        # Validar que no haya NaN
        import math
        if math.isnan(m_total_cash) or math.isnan(m_internet_cash):
            raise HTTPException(status_code=400, detail="Monto inválido (NaN)")

        deuda_internet = m_internet_cash + (pago_data.descuento_internet or 0.0)
        deuda_plus = m_plus_cash + (pago_data.descuento_plus or 0.0)
        deuda_adicional = m_adic_cash + (pago_data.descuento_adicional or 0.0)

        # Crear registro de Pago en base de datos
        nuevo_pago = models.Pago(
            cliente_id=id,
            monto=m_total_cash,
            metodo_pago=pago_data.metodo_pago,
            mes_correspondiente=pago_data.mes_correspondiente,
            referencia=pago_data.referencia,
            monto_internet=m_internet_cash,
            monto_plus=m_plus_cash,
            monto_adicional=m_adic_cash,
            estado=pago_data.estado or "Completado",
            turnocaja_id=turno_id
        )
        db.add(nuevo_pago)

        # Si el pago es Pendiente de Verificación, no aplicamos balances aún
        if nuevo_pago.estado == "Pendiente_Verificacion":
            db.commit()
            global _stats_cache
            _stats_cache = None # Vaciar caché
            return {
                "message": "Pago registrado y pendiente de verificación bancaria. El saldo del cliente no se actualizará hasta que la transferencia sea confirmada.",
                "nuevo_saldo": float(cliente.saldo or 0),
                "saldo_internet": float(cliente.saldo or 0),
                "saldo_plus": round(try_float(cliente.plus), 2),
                "saldo_adicional": round(try_float(cliente.adicional), 2),
                "saldo_extras": round(try_float(cliente.plus) + try_float(cliente.adicional), 2)
            }

        # 1. ACTUALIZAR ADICIONAL
        if deuda_adicional > 0:
            curr_adic = try_float(cliente.adicional)
            cliente.adicional = str(max(0, curr_adic - deuda_adicional))
            if m_adic_cash > 0:
                cliente.adicional_pagado = float(cliente.adicional_pagado or 0) + m_adic_cash
            if cliente.adicional == "0.0": cliente.adicional = ""

        # 2. ACTUALIZAR PLUS (IPTV)
        if deuda_plus > 0:
            curr_plus = try_float(cliente.plus)
            cliente.plus = str(max(0, curr_plus - deuda_plus))
            if m_plus_cash > 0:
                cliente.plus_pagado = float(cliente.plus_pagado or 0) + m_plus_cash
            if cliente.plus == "0.0": cliente.plus = ""

        # 3. ACTUALIZAR SALDO PRINCIPAL
        cliente.saldo = float(cliente.saldo or 0) - deuda_internet
        cliente.pago_mensual = float(cliente.pago_mensual or 0) + m_total_cash

        if pago_data.facturas is not None: cliente.facturas = pago_data.facturas
        if pago_data.app is not None: cliente.app = pago_data.app
        if pago_data.payment_date is not None and not str(cliente.payment_date or "").strip():
            cliente.payment_date = pago_data.payment_date
        if pago_data.bank is not None: cliente.bank = pago_data.bank
        if pago_data.cod is not None: cliente.cod = pago_data.cod
        if pago_data.bank_plus is not None: cliente.bank_plus = pago_data.bank_plus
        if pago_data.notas_pago is not None: cliente.notas_pago = pago_data.notas_pago

        # 4. GUARDAR INTERNET PAYMENT
        new_net_str = str(pago_data.internet_payment or "").strip()
        if new_net_str not in ["", "NONE", "0", "0.0", "0.00"]:
            val_net = try_float(new_net_str)
            if val_net > 0:
                prev_internet = try_float(cliente.internet_payment)
                if prev_internet > 0 and val_net != prev_internet:
                    cliente.internet_payment = str(round(prev_internet + val_net, 2))
                else:
                    cliente.internet_payment = str(round(val_net, 2))
        elif m_internet_cash > 0:
            prev_internet = try_float(cliente.internet_payment)
            cliente.internet_payment = str(round(prev_internet + m_internet_cash, 2))

        # 5. Reactivación automática si corresponde (remueve de MikroTik y pasa a Activo)
        if cliente.estado in ["Moroso", "Suspendido"] and cliente.saldo <= 0 and try_float(cliente.plus) <= 0:
            cliente.estado = "Activo"
            # Remover de MikroTik Address List por Nodo
            if cliente.ip:
                try:
                    from network.adapters.mikrotik import MikroTikAdapter
                    from sqlalchemy import or_ as _or
                    is_sayausi = is_nodo_sayausi(cliente.nodo)
                    list_name = "CLIENTES_SUSPENDIDOS_POR_PAGOS" if is_sayausi else "CLIENTES_SUSPENDIDOS_POR_PAGO"

                    olt_config = db.query(models.OLTConfig).filter(
                        _or(
                            models.OLTConfig.nodo_asociado == cliente.nodo,
                            models.OLTConfig.nodo_asociado.ilike("%SAYAUS%") if is_sayausi else models.OLTConfig.nodo_asociado.ilike("%BAN%"),
                            models.OLTConfig.nodo_asociado == None
                        ),
                        models.OLTConfig.active == True
                    ).first()

                    if olt_config and olt_config.mikrotik_host:
                        with MikroTikAdapter(
                            host=olt_config.mikrotik_host,
                            username=olt_config.mikrotik_username,
                            password=olt_config.mikrotik_password,
                            port=olt_config.mikrotik_port or 8728
                        ) as mt:
                            mt.remove_from_address_list(cliente.ip, list_name)
                except Exception as mt_err:
                    logger.error(f"Error MikroTik al reactivar cliente {cliente.id} ({cliente.ip}): {mt_err}")

            try:
                from services.libreqos_manager import LibreQoSManager
                correlation_id = f"auto_res_{id}_{int(datetime.now().timestamp())}"
                LibreQoSManager.enqueue_job("RESUME", id, db, correlation_id, "AUTO_REACTIVATION_PAYMENT")
            except Exception as lq_err:
                print(f"Error al encolar LibreQoS tras reactivación automática: {lq_err}")

        sync_cliente_balances(cliente, db)
        db.commit()

        _stats_cache = None # Vaciar caché

        nuevo_saldo = float(cliente.saldo or 0)
        remaining_plus = round(try_float(cliente.plus), 2)
        remaining_adicional = round(try_float(cliente.adicional), 2)
        remaining_internet = round(max(0, nuevo_saldo), 2)
        response = {
            "message": f"Pago registrado. Saldo pendiente: ${nuevo_saldo:.2f}",
            "nuevo_saldo": nuevo_saldo,
            "saldo_internet": remaining_internet,
            "saldo_plus": remaining_plus,
            "saldo_adicional": remaining_adicional,
            "saldo_extras": round(remaining_plus + remaining_adicional, 2),
        }
        if nuevo_saldo < 0:
            response["message"] = f"Pago registrado. Excedente: ${abs(nuevo_saldo):.2f}"
        return response
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error al registrar pago: {str(e)}")

@router.post("/{id}/pagos/{pago_id}/confirmar")
def confirmar_pago(
    id: int, 
    pago_id: int, 
    db: Session = Depends(get_db), 
    current_user: models.Usuario = Depends(require_role(["administrador", "secretario"]))
):
    pago = db.query(models.Pago).filter(models.Pago.id == pago_id, models.Pago.cliente_id == id).first()
    if not pago:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    if pago.estado != "Pendiente_Verificacion":
        raise HTTPException(status_code=400, detail="El pago ya está confirmado o anulado.")
    if pago.anulado:
        raise HTTPException(status_code=400, detail="No se puede confirmar un pago anulado.")
        
    cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
        
    deuda_internet = float(pago.monto_internet or 0)
    deuda_plus = float(pago.monto_plus or 0)
    deuda_adicional = float(pago.monto_adicional or 0)
    
    if deuda_adicional > 0:
        curr_adic = try_float(cliente.adicional)
        cliente.adicional = str(max(0, curr_adic - deuda_adicional))
        cliente.adicional_pagado = float(cliente.adicional_pagado or 0) + float(pago.monto_adicional)
        if cliente.adicional == "0.0": cliente.adicional = ""
        
    if deuda_plus > 0:
        curr_plus = try_float(cliente.plus)
        cliente.plus = str(max(0, curr_plus - deuda_plus))
        cliente.plus_pagado = float(cliente.plus_pagado or 0) + float(pago.monto_plus)
        if cliente.plus == "0.0": cliente.plus = ""
        
    cliente.saldo = float(cliente.saldo or 0) - deuda_internet
    cliente.pago_mensual = float(cliente.pago_mensual or 0) + float(pago.monto)
    
    pago.estado = "Completado"
    
    if cliente.estado == "Suspendido" and cliente.saldo <= 0 and try_float(cliente.plus) <= 0:
        cliente.estado = "Activo"
        try:
            from services.libreqos_manager import LibreQoSManager
            correlation_id = f"auto_res_{id}_{int(datetime.now().timestamp())}"
            LibreQoSManager.enqueue_job("RESUME", id, db, correlation_id, "AUTO_REACTIVATION_PAYMENT_CONFIRM")
        except Exception as lq_err:
            print(f"Error al encolar LibreQoS tras reactivación automática: {lq_err}")
             
    sync_cliente_balances(cliente, db)
    db.commit()
    
    global _stats_cache
    _stats_cache = None
    
    return {"message": "Pago confirmado exitosamente. Balances de cliente actualizados."}

@router.post("/{id}/pagos/{pago_id}/anular")
def anular_pago(
    id: int, 
    pago_id: int, 
    request_data: schemas.PagoAnularRequest, 
    db: Session = Depends(get_db), 
    current_user: models.Usuario = Depends(require_role(["administrador", "secretario"]))
):
    try:
        pago = db.query(models.Pago).filter(models.Pago.id == pago_id, models.Pago.cliente_id == id).first()
        if not pago:
            raise HTTPException(status_code=404, detail="Pago no encontrado")
        if pago.anulado:
            raise HTTPException(status_code=400, detail="Este pago ya se encuentra anulado.")
            
        cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
        if not cliente:
            raise HTTPException(status_code=404, detail="Cliente no encontrado")
            
        if pago.estado == "Completado":
            deuda_internet = float(pago.monto_internet or 0)
            deuda_plus = float(pago.monto_plus or 0)
            deuda_adicional = float(pago.monto_adicional or 0)
            
            if deuda_adicional > 0:
                curr_adic = try_float(cliente.adicional)
                cliente.adicional = str(curr_adic + deuda_adicional)
                cliente.adicional_pagado = max(0.0, float(cliente.adicional_pagado or 0) - float(pago.monto_adicional))
                
            if deuda_plus > 0:
                curr_plus = try_float(cliente.plus)
                cliente.plus = str(curr_plus + deuda_plus)
                cliente.plus_pagado = max(0.0, float(cliente.plus_pagado or 0) - float(pago.monto_plus))
                
            cliente.saldo = float(cliente.saldo or 0) + deuda_internet
            cliente.pago_mensual = max(0.0, float(cliente.pago_mensual or 0) - float(pago.monto))
            
        pago.anulado = True
        pago.fecha_anulacion = datetime.utcnow()
        pago.anulado_por = current_user.username
        pago.motivo_anulacion = request_data.motivo_anulacion
        
        sync_cliente_balances(cliente, db)
        db.commit()
        
        global _stats_cache
        _stats_cache = None
        
        return {"message": "Pago anulado exitosamente. Balances revertidos contablemente."}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error al procesar pago: {str(e)}")

def procesar_facturacion_global(db: Session):
    clientes = db.query(models.Cliente).all()
    clientes_activos = [c for c in clientes if c.estado and c.estado.upper() == "ACTIVO"]
    
    count = 0
    for cliente in clientes_activos:
        # 1. Recargo mensual de IPTV PLUS ($2 por pantalla adicional contratada)
        plan_info = db.query(models.PlanInternet).filter(models.PlanInternet.nombre == cliente.plan).first()
        base_screens = (plan_info.pantallas if plan_info.pantallas is not None else 0) if plan_info else 0
        
        cargo_plus = 0.0
        if (cliente.iptv_max_conn or 0) > base_screens:
            cargo_plus = float((cliente.iptv_max_conn - base_screens) * 2)
            
        if getattr(cliente, 'cortesia_total', False):
            cliente.plus = "0"
        else:
            cliente.plus = str(cargo_plus) if cargo_plus > 0 else ""
            
        # 2. La tarifa de internet se agrega al saldo directamente
        tarifa = 0.00
        if getattr(cliente, 'mantenimiento', False):
            tarifa = 10.00
        elif cliente.tercera_edad and cliente.precio_plan_especial is not None:
            tarifa = float(cliente.precio_plan_especial)
        elif plan_info:
            tarifa = float(plan_info.precio or 0)
            
        cliente.saldo = float(cliente.saldo or 0) + tarifa
        
        # 3. Reiniciar campos mensuales para la vista General
        cliente.facturas = ""
        cliente.payment_date = ""
        cliente.bank = ""
        cliente.cod = ""
        cliente.bank_plus = ""
        cliente.adicional = ""
        cliente.internet_payment = ""
        cliente.pago_mensual = 0.00
        cliente.plus_pagado = 0.00
        cliente.adicional_pagado = 0.00
        
        # 4. Sincronizar balances
        sync_cliente_balances(cliente, db)
        count += 1
        
    db.commit()
    return count

@router.post("/facturacion-mensual-global")
def ejecutar_facturacion_mensual(
    db: Session = Depends(get_db), 
    current_user: models.Usuario = Depends(require_role(["administrador"]))
):
    config_sys = get_config()
    now_utc = datetime.utcnow()
    current_month = now_utc.strftime("%Y-%m")
    
    # 1. Comprobar que hayan transcurrido al menos 60 segundos (1 minuto) desde la última facturación (modo prueba)
    last_log = db.query(models.LogFacturacion).order_by(models.LogFacturacion.fecha_ejecucion.desc()).first()
    if last_log and last_log.fecha_ejecucion:
        elapsed = (now_utc - last_log.fecha_ejecucion).total_seconds()
        if elapsed < 60:
            remaining = int(60 - elapsed)
            raise HTTPException(
                status_code=400, 
                detail=f"Modo de prueba: Debe esperar {remaining} segundos antes de ejecutar la facturación nuevamente (límite: 1 por minuto)."
            )

    # 2. Intentar registrar de forma atómica la facturación para evitar carrera de hilos
    # pyrefly: ignore [missing-import]
    from sqlalchemy.exc import IntegrityError
    periodo_key = now_utc.strftime("%Y-%m-%d %H:%M:%S")
    log_fact = models.LogFacturacion(
        periodo_mes=periodo_key,
        fecha_ejecucion=now_utc,
        estado="Procesando",
        usuario_id=current_user.id
    )
    db.add(log_fact)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400, 
            detail="Error al iniciar la facturación. Intente nuevamente en unos segundos."
        )
        
    try:
        count = procesar_facturacion_global(db)
        log_fact.estado = "Completado"
        save_config({"ultima_facturacion": current_month})
        db.commit()
        return {"message": f"Facturación procesada para {count} clientes exitosamente."}
    except Exception as e:
        db.rollback()
        db.query(models.LogFacturacion).filter(models.LogFacturacion.periodo_mes == periodo_key).delete()
        db.commit()
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error en facturación: {str(e)}")

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
    
    # ── FILTRAR SOLO CLIENTES CON FACTURA Y CÓDIGO VÁLIDO ──
    clientes_con_factura = []
    clientes_con_factura_ids = set()
    for c in clientes:
        fact_raw = str(c.facturas or "").strip().upper()
        cod_raw = str(c.cod or "").strip()
        if fact_raw == "SI" and cod_raw:
            clientes_con_factura.append(c)
            clientes_con_factura_ids.add(c.id)

    # ── HOJA 1: FACTURACIÓN CLIENTES ──
    data = []
    for c in clientes_con_factura:
        id_str = f"C{c.id:02d}" if c.id is not None else ""
        pago_mensual = float(c.pago_mensual or 0.00)
        confirmar = True if pago_mensual > 0 else False
        megas_val = f"{planes_megas.get(c.plan, 0)}MB" if (confirmar and c.plan and c.plan in planes_megas) else "FALSE"

        data.append({
            "ID": id_str,
            "RUC / CEDULA": str(c.cedula or "").strip(),
            "NAME": c.nombre or "",
            "DIRECTION": c.direccion or "",
            "CEL": str(c.celular or "").strip(),
            "PARISH": c.parroquia or "",
            "PLAN": c.plan or "",
            f"FACT {month_name_en}": "SI",
            "ESTADO": c.estado or "Pendiente",
            "CONFIRMAR": confirmar,
            f"MEGAS {month_name_en}": megas_val,
            "FACTURAS": str(c.cod or "").strip(),
        })
        
    df_clientes = pd.DataFrame(data)
    
    # ── HOJA 2: RESUMEN POR PLAN (SOLO CLIENTES CON FACTURA) ──
    pagos_todos = db.query(models.Pago).all()
    pagos_mes_actual = [
        p for p in pagos_todos 
        if str(p.fecha_pago)[:7] == current_month 
        and p.cliente_id in clientes_con_factura_ids 
        and not getattr(p, 'anulado', False)
    ]
    
    # Acumular pagos por cliente y por método de pago
    pago_por_cliente_metodo = {}
    for p in pagos_mes_actual:
        if p.cliente_id:
            m_total = float(p.monto or 0)
            m_parts = float(p.monto_internet or 0) + float(p.monto_plus or 0) + float(p.monto_adicional or 0)
            monto_total_pago = m_total if m_total > 0 else m_parts
            metodo = (p.metodo_pago or "Efectivo").upper()
            key = (p.cliente_id, metodo)
            pago_por_cliente_metodo[key] = pago_por_cliente_metodo.get(key, 0.0) + monto_total_pago
            
    planes_nombres = sorted(list(set(c.plan for c in clientes_con_factura if c.plan)))
    
    resumen_data = []
    gran_total_clientes = 0
    gran_total_estimado = 0.0
    gran_total_efectivo = 0.0
    gran_total_pichincha = 0.0
    gran_total_jep = 0.0
    gran_total_reunido = 0.0
    
    for plan_nombre in planes_nombres:
        clientes_en_plan = [c for c in clientes_con_factura if c.plan and c.plan.strip() == plan_nombre.strip() and (c.estado and c.estado.strip().upper() == "ACTIVO")]
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

        # 3. Eliminar tareas OLT y sus logs
        try:
            db.query(models.OLTTaskLog).delete()
            db.query(models.OLTTask).delete()
        except Exception as e:
            print(f"Aviso: No se pudieron eliminar las tareas OLT: {e}")

        # 4. Eliminar verificaciones de potencia OLT
        try:
            db.query(models.OLTPowerCheck).delete()
        except Exception as e:
            print(f"Aviso: No se pudieron eliminar las verificaciones de potencia OLT: {e}")

        # 5. Limpiar/Resetear tablas de inventario
        try:
            import inventory_models
            db.query(inventory_models.InventoryIpPool).update({
                inventory_models.InventoryIpPool.estado: "LIBRE",
                inventory_models.InventoryIpPool.cliente_id: None,
                inventory_models.InventoryIpPool.updated_at: datetime.now()
            })
            db.query(inventory_models.InventoryServicePort).update({
                inventory_models.InventoryServicePort.estado: "LIBRE",
                inventory_models.InventoryServicePort.cliente_id: None,
                inventory_models.InventoryServicePort.updated_at: datetime.now()
            })
            db.query(inventory_models.InventoryOntId).update({
                inventory_models.InventoryOntId.estado: "LIBRE",
                inventory_models.InventoryOntId.cliente_id: None,
                inventory_models.InventoryOntId.updated_at: datetime.now()
            })
        except Exception as e:
            print(f"Aviso: No se pudo resetear el inventario: {e}")

        # 6. Limpiar tablas de LibreQoS (estados, trabajos y auditoría)
        try:
            from libreqos_models import ClientQoSState, LibreQoSJob, LibreQoSAuditLog
            db.query(ClientQoSState).delete()
            db.query(LibreQoSJob).delete()
            db.query(LibreQoSAuditLog).update({LibreQoSAuditLog.cliente_id: None})
        except Exception as e:
            print(f"Aviso: No se pudieron limpiar las tablas de LibreQoS: {e}")

        # 7. Desvincular ONTs y Service Ports descubiertos
        try:
            from discovery_models import DiscoveredONT, DiscoveredServicePort
            db.query(DiscoveredONT).update({DiscoveredONT.cliente_id: None})
            db.query(DiscoveredServicePort).update({DiscoveredServicePort.cliente_id: None})
        except Exception as e:
            print(f"Aviso: No se pudieron desvincular los dispositivos descubiertos: {e}")
        
        # 8. Eliminar todos los clientes
        db.query(models.Cliente).delete()
        
        db.commit()
        
        # Resetear AUTO_INCREMENT
        try:
            # pyrefly: ignore [missing-import]
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

    # Eliminar logs y tareas OLT asociadas (para evitar violación de clave foránea)
    try:
        task_ids = [t.id for t in db.query(models.OLTTask).filter(models.OLTTask.cliente_id == id).all()]
        if task_ids:
            db.query(models.OLTTaskLog).filter(models.OLTTaskLog.task_id.in_(task_ids)).delete(synchronize_session=False)
            db.query(models.OLTTask).filter(models.OLTTask.id.in_(task_ids)).delete(synchronize_session=False)
    except Exception as e:
        print(f"Aviso: No se pudieron eliminar las tareas OLT del cliente: {e}")

    # Eliminar verificaciones de potencia OLT asociadas (para evitar violación de clave foránea)
    try:
        db.query(models.OLTPowerCheck).filter(models.OLTPowerCheck.cliente_id == id).delete()
    except Exception as e:
        print(f"Aviso: No se pudieron eliminar las verificaciones de potencia OLT: {e}")

    # Eliminar pagos asociados (si los hubiera)
    db.query(models.Pago).filter(models.Pago.cliente_id == id).delete()
    
    # Eliminar registros de hoja de ruta asociados (para evitar violación de clave foránea)
    db.query(models.HojaRuta).filter(models.HojaRuta.cliente_id == id).delete()
    
    # Liberar la IP, Service Port y ONT ID en el inventario
    try:
        import inventory_models
        db.query(inventory_models.InventoryIpPool).filter(
            inventory_models.InventoryIpPool.cliente_id == id
        ).update({
            inventory_models.InventoryIpPool.estado: "LIBRE",
            inventory_models.InventoryIpPool.cliente_id: None,
            inventory_models.InventoryIpPool.updated_at: datetime.now()
        })
        db.query(inventory_models.InventoryServicePort).filter(
            inventory_models.InventoryServicePort.cliente_id == id
        ).update({
            inventory_models.InventoryServicePort.estado: "LIBRE",
            inventory_models.InventoryServicePort.cliente_id: None,
            inventory_models.InventoryServicePort.updated_at: datetime.now()
        })
        db.query(inventory_models.InventoryOntId).filter(
            inventory_models.InventoryOntId.cliente_id == id
        ).update({
            inventory_models.InventoryOntId.estado: "LIBRE",
            inventory_models.InventoryOntId.cliente_id: None,
            inventory_models.InventoryOntId.updated_at: datetime.now()
        })
    except Exception as e:
        print(f"Aviso: No se pudieron liberar los recursos del inventario: {e}")
        
    # Encolar la eliminación en LibreQoS antes de borrar el cliente
    try:
        from services.libreqos_manager import LibreQoSManager
        # Encolar directamente ya que después no existirá el registro Cliente en la BD
        LibreQoSManager.enqueue_job(
            operation="REMOVE",
            cliente_id=id,
            db=db,
            correlation_id=f"del_client_{id}_{int(datetime.now().timestamp())}",
            created_by="CLIENT_DELETE_API"
        )
    except Exception as lq_err:
        print(f"Aviso: No se pudo encolar la eliminación en LibreQoS: {lq_err}")

    # Eliminar registros de ClientQoSState asociados si existen
    try:
        from libreqos_models import ClientQoSState
        db.query(ClientQoSState).filter(ClientQoSState.cliente_id == id).delete()
    except Exception as qos_err:
        print(f"Aviso: No se pudo eliminar el estado QoS del cliente: {qos_err}")

    # Eliminar trabajos de LibreQoS asociados si existen
    try:
        from libreqos_models import LibreQoSJob
        db.query(LibreQoSJob).filter(LibreQoSJob.cliente_id == id).delete()
    except Exception as job_err:
        print(f"Aviso: No se pudieron eliminar los trabajos de LibreQoS: {job_err}")

    # Desvincular registros de auditoría de LibreQoS asociados si existen
    try:
        from libreqos_models import LibreQoSAuditLog
        db.query(LibreQoSAuditLog).filter(LibreQoSAuditLog.cliente_id == id).update({LibreQoSAuditLog.cliente_id: None})
    except Exception as audit_err:
        print(f"Aviso: No se pudieron desvincular los registros de auditoría de LibreQoS: {audit_err}")

    # Desvincular ONTs y Service Ports descubiertos si existen
    try:
        from discovery_models import DiscoveredONT, DiscoveredServicePort
        db.query(DiscoveredONT).filter(DiscoveredONT.cliente_id == id).update({DiscoveredONT.cliente_id: None})
        db.query(DiscoveredServicePort).filter(DiscoveredServicePort.cliente_id == id).update({DiscoveredServicePort.cliente_id: None})
    except Exception as disc_err:
        print(f"Aviso: No se pudieron desvincular los dispositivos descubiertos: {disc_err}")

    db.delete(cliente)
    db.commit()

    # Resetear AUTO_INCREMENT solo en MySQL/MariaDB
    try:
        # pyrefly: ignore [missing-import]
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
            "mantenimiento": ["MANTENIMIENTO", "PLAN_MANTENIMIENTO"],
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
        BOOL_FIELDS = {"tercera_edad", "iptv_activar", "mantenimiento"}

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
                    
                    cliente = models.Cliente(id=proximo_id_hueco, nombre=nombre, estado="Activo")
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
                
                # Garantizar que clientes importados queden en 'Activo' (base de datos / general)
                # y no pasen por 'Administrar' (Pendiente) ni generen colas en LibreQoS.
                if not cliente.estado or str(cliente.estado).strip().lower() in ["", "none", "null", "pendiente"]:
                    cliente.estado = "Activo"

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




@router.post("/{id}/eliminar-completamente", dependencies=[Depends(require_role(["administrador"]))])
async def eliminar_cliente_completamente(
    id: int,
    payload_confirm: schemas.ClienteEliminarCompleto,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Elimina a un cliente de forma secuencial y controlada de todos los sistemas:
    OLT, XUI (IPTV), LibreQoS y base de datos local.
    """
    # 1. Verificar PIN
    expected_pin = os.getenv("DELETE_CLIENT_PIN", "1234566")
    if payload_confirm.pin != expected_pin:
        raise HTTPException(status_code=400, detail="El PIN de seguridad es incorrecto.")
        
    cliente = db.query(models.Cliente).filter(models.Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")

    # 2. Generar Snapshot (fotografía) completa en JSON
    from decimal import Decimal
    from datetime import datetime as dt_class, date as d_class
    
    snapshot = {}
    for col in models.Cliente.__table__.columns:
        # col.key o col.name pueden diferir de los atributos declarativos de SQLAlchemy (ej: 'id' vs 'NUMERO')
        val = None
        if hasattr(cliente, col.key):
            val = getattr(cliente, col.key)
        elif col.key == "NUMERO" and hasattr(cliente, "id"):
            val = getattr(cliente, "id")
        else:
            val = getattr(cliente, col.name, None)

        if isinstance(val, (dt_class, d_class)):
            val = val.strftime("%Y-%m-%d %H:%M:%S") if hasattr(val, "strftime") else str(val)
        elif isinstance(val, Decimal):
            val = float(val)
        snapshot[col.name] = val

    # Crear el registro de backup en la base de datos (con estado PENDIENTE)
    backup_rec = models.ClienteEliminado(
        cliente_id=id,
        nombre=cliente.nombre,
        cedula=cliente.cedula,
        plan=cliente.plan,
        ip=cliente.ip,
        mac=cliente.mac,
        deleted_by=current_user.username,
        estado_olt="PENDIENTE",
        estado_mikrotik="PENDIENTE",
        estado_xui="PENDIENTE",
        estado_libreqos="PENDIENTE",
        estado_db="PENDIENTE",
        datos_cliente=snapshot
    )
    db.add(backup_rec)
    db.commit()
    db.refresh(backup_rec)

    # Variables de estado del proceso
    estado_olt = "OMITIDO"
    estado_mikrotik = "OMITIDO"
    estado_xui = "OMITIDO"
    estado_libreqos = "OMITIDO"
    estado_db = "PENDIENTE"
    
    # ── ETAPA 1: ELIMINAR DE OLT (SÍNCRONO) ──
    if cliente.id_port and cliente.service_port:
        try:
            from services.olt_interface import OLTInterface
            # pyrefly: ignore [missing-import]
            from sqlalchemy import or_ as _or
            
            # Extraer número de puerto
            puerto_raw = str(cliente.puerto or "0")
            import re as _re
            m = _re.search(r'\d+', puerto_raw)
            puerto_num = m.group() if m else "0"
            
            is_sayausi = is_nodo_sayausi(cliente.nodo)
            gpon_port = f"0/1/{puerto_num}" if is_sayausi else f"0/0/{puerto_num}"
            
            # Obtener OLT activa
            olt_config = db.query(models.OLTConfig).filter(
                _or(
                    models.OLTConfig.nodo_asociado == cliente.nodo,
                    models.OLTConfig.nodo_asociado.ilike("%SAYAUS%") if is_sayausi else models.OLTConfig.nodo_asociado.ilike("%BAN%"),
                    models.OLTConfig.nodo_asociado == None
                ),
                models.OLTConfig.active == True
            ).first()
            
            if not olt_config:
                raise Exception(f"No hay OLT activa configurada para el nodo '{cliente.nodo}'.")
                
            # Conectar y eliminar
            olt = OLTInterface(
                host=olt_config.host,
                port=olt_config.port or 23,
                username=olt_config.username,
                password=olt_config.password
            )
            olt.connect()
            olt_payload = {
                "gpon_port": gpon_port,
                "ont_id": str(cliente.id_port).strip(),
                "service_port": str(cliente.service_port).strip(),
                "mac": str(cliente.mac or "000000000000").replace(":", "").replace("-", "")
            }
            res_olt = olt.execute_removal_sequence(olt_payload)
            olt.disconnect()
            
            if not res_olt.get("success", False):
                raise Exception(f"Fallo en la OLT: {res_olt.get('error', 'Error desconocido')}")
                
            estado_olt = "ELIMINADO"
            backup_rec.estado_olt = estado_olt
            db.commit()
            
        except Exception as olt_err:
            estado_olt = "ERROR"
            backup_rec.estado_olt = estado_olt
            backup_rec.detalles_error = f"Error en Etapa OLT: {str(olt_err)}"
            db.commit()
            raise HTTPException(
                status_code=500,
                detail={"stage": "olt", "message": f"Error al eliminar en la OLT: {str(olt_err)}"}
            )
            
    # ── ETAPA 2: ELIMINAR DE MIKROTIK (DHCP LEASE) ──
    if cliente.mac:
        try:
            from network.adapters.mikrotik import MikroTikAdapter
            # pyrefly: ignore [missing-import]
            from sqlalchemy import or_ as _or_mt
            
            olt_config_mt = db.query(models.OLTConfig).filter(
                _or_mt(
                    models.OLTConfig.nodo_asociado == cliente.nodo,
                    models.OLTConfig.nodo_asociado == None
                ),
                models.OLTConfig.active == True
            ).first()
            
            if olt_config_mt and olt_config_mt.mikrotik_host:
                mt = MikroTikAdapter(
                    host=olt_config_mt.mikrotik_host,
                    port=olt_config_mt.mikrotik_port or 8728,
                    username=olt_config_mt.mikrotik_username or "admin",
                    password=olt_config_mt.mikrotik_password or ""
                )
                mt.connect()
                
                # Buscar el lease DHCP del cliente por MAC
                clean_mac = str(cliente.mac).replace(":", "").replace("-", "").upper()
                resource = mt.api.get_resource('/ip/dhcp-server/lease')
                all_leases = resource.get()
                
                removed_count = 0
                for lease in all_leases:
                    lease_mac = lease.get('mac-address', '').replace(":", "").replace("-", "").upper()
                    if lease_mac == clean_mac:
                        lease_id = lease.get('.id') or lease.get('id')
                        if lease_id:
                            resource.remove(**{'.id': lease_id})
                            removed_count += 1
                
                # También buscar por IP si la MAC no matcheó
                if removed_count == 0 and cliente.ip:
                    for lease in all_leases:
                        if lease.get('address') == cliente.ip:
                            lease_id = lease.get('.id') or lease.get('id')
                            if lease_id:
                                resource.remove(**{'.id': lease_id})
                                removed_count += 1
                
                mt.disconnect()
                
                if removed_count > 0:
                    estado_mikrotik = "ELIMINADO"
                else:
                    estado_mikrotik = "OMITIDO"  # No se encontró lease, no es error
            else:
                estado_mikrotik = "OMITIDO"  # MikroTik no configurado para este nodo
                
            backup_rec.estado_mikrotik = estado_mikrotik
            db.commit()
                
        except Exception as mt_err:
            estado_mikrotik = "ERROR"
            backup_rec.estado_mikrotik = estado_mikrotik
            backup_rec.detalles_error = (backup_rec.detalles_error or "") + f" | Error en Etapa MikroTik: {str(mt_err)}"
            db.commit()
            # No detenemos el proceso por MikroTik - se registra el error pero se continúa
            print(f"[WARN] Error eliminando de MikroTik (cliente {id}): {mt_err}")

    # ── ETAPA 3: ELIMINAR DE XUI/IPTV (SÍNCRONO) ──
    if cliente.iptv_user and str(cliente.iptv_user).strip():
        try:
            from services.xui_service import delete_xui_user
            res_xui = await delete_xui_user(cliente.iptv_user)
            
            if not res_xui.get("success", False):
                # Si no se encontró el usuario en el panel, se puede considerar omitido o ya eliminado
                if "not found" in str(res_xui.get("detail", "")).lower():
                    estado_xui = "OMITIDO"
                else:
                    raise Exception(f"Fallo en panel XUI: {res_xui.get('detail', 'Error desconocido')}")
            else:
                estado_xui = "ELIMINADO"
                
            backup_rec.estado_xui = estado_xui
            db.commit()
            
        except Exception as xui_err:
            estado_xui = "ERROR"
            backup_rec.estado_xui = estado_xui
            backup_rec.detalles_error = (backup_rec.detalles_error or "") + f" | Error en Etapa XUI: {str(xui_err)}"
            db.commit()
            print(f"[WARN] Error eliminando de XUI IPTV (cliente {id}): {xui_err}")

    # ── ETAPA 4: ELIMINAR DE LIBREQOS ──
    try:
        from services.libreqos_manager import LibreQoSManager
        LibreQoSManager.enqueue_job(
            operation="REMOVE",
            cliente_id=id,
            db=db,
            correlation_id=f"del_client_{id}_{int(datetime.now().timestamp())}",
            created_by="CLIENT_DELETE_API"
        )
        estado_libreqos = "ELIMINADO"
        backup_rec.estado_libreqos = estado_libreqos
        db.commit()
    except Exception as lq_err:
        estado_libreqos = "ERROR"
        backup_rec.estado_libreqos = estado_libreqos
        backup_rec.detalles_error = f"Error en Etapa LibreQoS: {str(lq_err)}"
        db.commit()
        raise HTTPException(
            status_code=500,
            detail={"stage": "libreqos", "message": f"Error al encolar eliminación en LibreQoS: {str(lq_err)}"}
        )

    # ── ETAPA 5: ELIMINAR RELACIONES INTERNAS Y CLIENTE DE LA BASE DE DATOS ──
    try:
        # Eliminar archivos de cédula si existen físicamente
        for file_path in [cliente.cedula_frontal, cliente.cedula_posterior]:
            if file_path:
                path_clean = file_path.lstrip("/")
                if os.path.exists(path_clean):
                    try: os.remove(path_clean)
                    except: pass

        # Eliminar logs y tareas OLT asociadas
        task_ids = [t.id for t in db.query(models.OLTTask).filter(models.OLTTask.cliente_id == id).all()]
        if task_ids:
            db.query(models.OLTTaskLog).filter(models.OLTTaskLog.task_id.in_(task_ids)).delete(synchronize_session=False)
            db.query(models.OLTTask).filter(models.OLTTask.id.in_(task_ids)).delete(synchronize_session=False)

        # Eliminar verificaciones de potencia OLT asociadas
        db.query(models.OLTPowerCheck).filter(models.OLTPowerCheck.cliente_id == id).delete()

        # Eliminar pagos asociados
        db.query(models.Pago).filter(models.Pago.cliente_id == id).delete()
        
        # Eliminar registros de hoja de ruta asociados
        db.query(models.HojaRuta).filter(models.HojaRuta.cliente_id == id).delete()
        
        # Liberar IP, Service Port y ONT ID en el inventario
        try:
            import inventory_models
            db.query(inventory_models.InventoryIpPool).filter(
                inventory_models.InventoryIpPool.cliente_id == id
            ).update({
                inventory_models.InventoryIpPool.estado: "LIBRE",
                inventory_models.InventoryIpPool.cliente_id: None,
                inventory_models.InventoryIpPool.updated_at: datetime.now()
            })
            db.query(inventory_models.InventoryServicePort).filter(
                inventory_models.InventoryServicePort.cliente_id == id
            ).update({
                inventory_models.InventoryServicePort.estado: "LIBRE",
                inventory_models.InventoryServicePort.cliente_id: None,
                inventory_models.InventoryServicePort.updated_at: datetime.now()
            })
            db.query(inventory_models.InventoryOntId).filter(
                inventory_models.InventoryOntId.cliente_id == id
            ).update({
                inventory_models.InventoryOntId.estado: "LIBRE",
                inventory_models.InventoryOntId.cliente_id: None,
                inventory_models.InventoryOntId.updated_at: datetime.now()
            })
        except Exception as inv_err:
            print(f"Aviso Inventario al eliminar: {inv_err}")

        # Eliminar registros de ClientQoSState asociados si existen
        try:
            from libreqos_models import ClientQoSState
            db.query(ClientQoSState).filter(ClientQoSState.cliente_id == id).delete()
        except Exception:
            pass

        # Eliminar trabajos de LibreQoS asociados si existen
        try:
            from libreqos_models import LibreQoSJob
            db.query(LibreQoSJob).filter(LibreQoSJob.cliente_id == id).delete()
        except Exception:
            pass

        # Desvincular registros de auditoría de LibreQoS
        try:
            from libreqos_models import LibreQoSAuditLog
            db.query(LibreQoSAuditLog).filter(LibreQoSAuditLog.cliente_id == id).update({LibreQoSAuditLog.cliente_id: None})
        except Exception:
            pass

        # Desvincular ONTs y Service Ports descubiertos
        try:
            from discovery_models import DiscoveredONT, DiscoveredServicePort
            db.query(DiscoveredONT).filter(DiscoveredONT.cliente_id == id).update({DiscoveredONT.cliente_id: None})
            db.query(DiscoveredServicePort).filter(DiscoveredServicePort.cliente_id == id).update({DiscoveredServicePort.cliente_id: None})
        except Exception:
            pass

        # Eliminar finalmente al cliente
        db.delete(cliente)
        
        # Marcar éxito en el registro de backup
        backup_rec.estado_db = "ELIMINADO"
        db.commit()
        
    except Exception as db_err:
        backup_rec.estado_db = "ERROR"
        backup_rec.detalles_error = f"Error en Etapa Base de Datos: {str(db_err)}"
        db.commit()
        raise HTTPException(
            status_code=500,
            detail={"stage": "database", "message": f"Error al eliminar registros locales: {str(db_err)}"}
        )

    return {
        "success": True,
        "olt": estado_olt,
        "mikrotik": estado_mikrotik,
        "xui": estado_xui,
        "libreqos": estado_libreqos,
        "database": "ELIMINADO"
    }





