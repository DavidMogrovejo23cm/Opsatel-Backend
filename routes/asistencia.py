# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, HTTPException, status, Response
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import Session
from typing import List, Optional, Union
import models, schemas
from database import get_db
from datetime import datetime, timedelta, date
import calendar
from io import BytesIO
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from .auth import get_current_user, require_role

router = APIRouter(prefix="/asistencia", tags=["asistencia"])

def get_ecuador_time():
    # Ecuador es UTC-5 fijo (sin horario de verano)
    return datetime.utcnow() - timedelta(hours=5)

def parse_time_to_minutes(t_str: str) -> Optional[int]:
    """Convierte 'HH:MM' o 'HH:MM:SS' a minutos desde medianoche."""
    if not t_str:
        return None
    try:
        parts = [int(p) for p in t_str.split(":")]
        return parts[0] * 60 + parts[1]
    except Exception:
        return None

def get_user_schedule_dict(db: Session, user_id: int):
    horario = db.query(models.HorarioEmpleado).filter(models.HorarioEmpleado.usuario_id == user_id).first()
    if horario:
        return {
            "id": horario.id,
            "usuario_id": horario.usuario_id,
            "hora_entrada_1": horario.hora_entrada_1 or "08:00",
            "hora_salida_1": horario.hora_salida_1 or "13:00",
            "hora_entrada_2": horario.hora_entrada_2 or "14:00",
            "hora_salida_2": horario.hora_salida_2 or "18:00",
            "horas_diarias_esperadas": horario.horas_diarias_esperadas if horario.horas_diarias_esperadas is not None else 8.0,
            "dias_laborables": horario.dias_laborables or "1,2,3,4,5",
            "tolerancia_minutos": horario.tolerancia_minutos if horario.tolerancia_minutos is not None else 15
        }
    return {
        "id": 0,
        "usuario_id": user_id,
        "hora_entrada_1": "08:00",
        "hora_salida_1": "13:00",
        "hora_entrada_2": "14:00",
        "hora_salida_2": "18:00",
        "horas_diarias_esperadas": 8.0,
        "dias_laborables": "1,2,3,4,5",
        "tolerancia_minutos": 15
    }

@router.post("/registrar", response_model=schemas.AsistenciaResponse)
def registrar_asistencia(
    data: schemas.AsistenciaCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    ahora_ec = get_ecuador_time()
    hoy = ahora_ec.strftime("%Y-%m-%d")

    # Verificar si hay alguna marcación de entrada sin salida hoy
    abierta = db.query(models.Asistencia).filter(
        models.Asistencia.usuario_id == current_user.id,
        models.Asistencia.fecha == hoy,
        models.Asistencia.hora_salida.is_(None)
    ).first()

    if abierta:
        raise HTTPException(
            status_code=400, 
            detail="Ya registraste tu entrada. Debes registrar tu salida antes de marcar una nueva entrada."
        )

    nueva_asistencia = models.Asistencia(
        usuario_id=current_user.id,
        nombre_usuario=current_user.username,
        fecha=hoy,
        hora_entrada=data.hora_dispositivo if data.hora_dispositivo else ahora_ec.strftime("%H:%M:%S"),
        ubicacion=data.ubicacion,
        distancia_metros=data.distancia_metros,
        dispositivo_info=data.dispositivo_info,
        biometria_validada=data.biometria_validada
    )
    db.add(nueva_asistencia)
    db.commit()
    db.refresh(nueva_asistencia)
    return nueva_asistencia


@router.post("/registrar-salida", response_model=schemas.AsistenciaResponse)
def registrar_salida(
    data: schemas.AsistenciaCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    ahora_ec = get_ecuador_time()
    hoy = ahora_ec.strftime("%Y-%m-%d")
    
    # Buscar sesión abierta hoy
    asistencia = db.query(models.Asistencia).filter(
        models.Asistencia.usuario_id == current_user.id,
        models.Asistencia.fecha == hoy,
        models.Asistencia.hora_salida.is_(None)
    ).order_by(models.Asistencia.created_at.desc()).first()

    if not asistencia:
        # Buscar la última de hoy para mensaje amigable
        ultima = db.query(models.Asistencia).filter(
            models.Asistencia.usuario_id == current_user.id,
            models.Asistencia.fecha == hoy
        ).first()
        if ultima and ultima.hora_salida:
            raise HTTPException(status_code=400, detail="Ya registraste tu salida para esta marcación. Marca entrada si inicias un nuevo turno.")
        raise HTTPException(status_code=400, detail="No has registrado entrada hoy.")

    # Registro de salida flexible sin bloqueos rígidos
    asistencia.hora_salida = data.hora_dispositivo if data.hora_dispositivo else ahora_ec.strftime("%H:%M:%S")
    asistencia.ubicacion_salida = data.ubicacion
    asistencia.distancia_metros_salida = data.distancia_metros
    asistencia.biometria_salida_validada = data.biometria_validada
    
    db.commit()
    db.refresh(asistencia)
    return asistencia


@router.get("/estado-hoy", response_model=schemas.AsistenciaStatusResponse)
def estado_asistencia_hoy(
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    ahora_ec = get_ecuador_time()
    hoy = ahora_ec.strftime("%Y-%m-%d")
    
    todas_hoy = db.query(models.Asistencia).filter(
        models.Asistencia.usuario_id == current_user.id,
        models.Asistencia.fecha == hoy
    ).order_by(models.Asistencia.created_at.asc()).all()

    horario_dict = get_user_schedule_dict(db, current_user.id)
    punches_list = [
        {
            "id": a.id,
            "hora_entrada": a.hora_entrada,
            "hora_salida": a.hora_salida
        }
        for a in todas_hoy
    ]

    # Sesión abierta activa
    sesion_abierta = next((a for a in todas_hoy if not a.hora_salida), None)

    if sesion_abierta:
        return {
            "ha_entrado": True,
            "ha_salido": False,
            "hora_entrada": sesion_abierta.hora_entrada,
            "asistencia_id": sesion_abierta.id,
            "puede_salir": True,
            "mensaje_restriccion": None,
            "horario": horario_dict,
            "punches_today": punches_list
        }
    
    # Si no hay sesión abierta pero existen marcaciones completas hoy
    if todas_hoy:
        ultima = todas_hoy[-1]
        return {
            "ha_entrado": False,
            "ha_salido": True,
            "hora_entrada": ultima.hora_entrada,
            "asistencia_id": ultima.id,
            "puede_salir": False,
            "mensaje_restriccion": None,
            "horario": horario_dict,
            "punches_today": punches_list
        }

    # No ha marcado nada hoy
    return {
        "ha_entrado": False,
        "ha_salido": False,
        "hora_entrada": None,
        "asistencia_id": None,
        "puede_salir": False,
        "mensaje_restriccion": None,
        "horario": horario_dict,
        "punches_today": []
    }


# ============================================================================
# HORARIOS ENDPOINTS
# ============================================================================

@router.get("/horarios", response_model=List[schemas.HorarioEmpleadoResponse])
def listar_horarios(
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(require_role(["administrador"]))
):
    usuarios = db.query(models.Usuario).all()
    resultado = []
    for u in usuarios:
        h_dict = get_user_schedule_dict(db, u.id)
        h_dict["nombre_usuario"] = u.username
        resultado.append(h_dict)
    return resultado


@router.get("/mi-horario", response_model=schemas.HorarioEmpleadoResponse)
def mi_horario(
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    h_dict = get_user_schedule_dict(db, current_user.id)
    h_dict["nombre_usuario"] = current_user.username
    return h_dict


@router.put("/horarios/{usuario_id}", response_model=schemas.HorarioEmpleadoResponse)
def actualizar_horario(
    usuario_id: int,
    data: schemas.HorarioEmpleadoBase,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(require_role(["administrador"]))
):
    usuario = db.query(models.Usuario).filter(models.Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    horario = db.query(models.HorarioEmpleado).filter(models.HorarioEmpleado.usuario_id == usuario_id).first()
    if not horario:
        horario = models.HorarioEmpleado(usuario_id=usuario_id)
        db.add(horario)

    horario.hora_entrada_1 = data.hora_entrada_1
    horario.hora_salida_1 = data.hora_salida_1
    horario.hora_entrada_2 = data.hora_entrada_2
    horario.hora_salida_2 = data.hora_salida_2
    horario.horas_diarias_esperadas = data.horas_diarias_esperadas
    horario.dias_laborables = data.dias_laborables
    horario.tolerancia_minutos = data.tolerancia_minutos

    db.commit()
    db.refresh(horario)

    res = get_user_schedule_dict(db, usuario_id)
    res["nombre_usuario"] = usuario.username
    return res


# ============================================================================
# LÓGICA DE REPORTE MENSUAL
# ============================================================================

def calcular_reporte_mensual_datos(db: Session, mes: Optional[str] = None, usuario_id_filtro: Optional[int] = None):
    """
    Calcula los datos resumidos y detallados para el mes seleccionado (YYYY-MM).
    """
    if not mes or len(mes) != 7:
        ahora = get_ecuador_time()
        mes = ahora.strftime("%Y-%m")

    ano_str, mes_str = mes.split("-")
    ano, mes_num = int(ano_str), int(mes_str)

    num_days = calendar.monthrange(ano, mes_num)[1]
    fecha_inicio = f"{mes}-01"
    fecha_fin = f"{mes}-{num_days:02d}"

    query_users = db.query(models.Usuario)
    if usuario_id_filtro:
        query_users = query_users.filter(models.Usuario.id == usuario_id_filtro)
    usuarios = query_users.all()

    resumen_empleados = []
    gran_total_horas = 0.0
    gran_total_extras = 0.0

    dias_semana_esp = {0: "Lunes", 1: "Martes", 2: "Miércoles", 3: "Jueves", 4: "Viernes", 5: "Sábado", 6: "Domingo"}

    for u in usuarios:
        horario = get_user_schedule_dict(db, u.id)
        dias_lab_list = [int(d.strip()) for d in horario["dias_laborables"].split(",") if d.strip().isdigit()]

        asistencias_mes = db.query(models.Asistencia).filter(
            models.Asistencia.usuario_id == u.id,
            models.Asistencia.fecha >= fecha_inicio,
            models.Asistencia.fecha <= fecha_fin
        ).order_by(models.Asistencia.fecha.asc(), models.Asistencia.created_at.asc()).all()

        asistencias_por_dia = {}
        for a in asistencias_mes:
            if a.fecha not in asistencias_por_dia:
                asistencias_por_dia[a.fecha] = []
            asistencias_por_dia[a.fecha].append(a)

        detalles_dias = []
        emp_horas_trabajadas = 0.0
        emp_horas_esperadas = 0.0
        emp_horas_extras = 0.0
        emp_atrasos_min = 0
        emp_dias_trabajados = 0

        for day in range(1, num_days + 1):
            fecha_dia = f"{mes}-{day:02d}"
            fecha_obj = date(ano, mes_num, day)
            weekday_idx = fecha_obj.weekday() # 0 = Lunes, 6 = Domingo
            weekday_num = weekday_idx + 1     # 1 = Lunes, 7 = Domingo

            es_laborable = weekday_num in dias_lab_list
            horas_esperadas_hoy = horario["horas_diarias_esperadas"] if es_laborable else 0.0
            emp_horas_esperadas += horas_esperadas_hoy

            lista_hoy = asistencias_por_dia.get(fecha_dia, [])

            if not lista_hoy:
                detalles_dias.append({
                    "fecha": fecha_dia,
                    "dia_nombre": dias_semana_esp.get(weekday_idx, ""),
                    "entrado": False,
                    "salido": False,
                    "hora_entrada": None,
                    "hora_salida": None,
                    "horas_trabajadas": 0.0,
                    "horas_extras": 0.0,
                    "atraso_minutos": 0,
                    "estado": "Ausente" if es_laborable else "Descanso"
                })
                continue

            emp_dias_trabajados += 1
            primera_entrada = lista_hoy[0].hora_entrada
            ultima_salida = lista_hoy[-1].hora_salida

            # Calcular total de tiempo trabajado sumando cada sesión
            segundos_trabajados_hoy = 0
            for a in lista_hoy:
                if a.hora_entrada and a.hora_salida:
                    try:
                        t1 = datetime.strptime(f"{fecha_dia} {a.hora_entrada}", "%Y-%m-%d %H:%M:%S")
                        t2 = datetime.strptime(f"{fecha_dia} {a.hora_salida}", "%Y-%m-%d %H:%M:%S")
                        diff = (t2 - t1).total_seconds()
                        if diff > 0:
                            segundos_trabajados_hoy += diff
                    except Exception:
                        pass
            
            horas_trabajadas_hoy = round(segundos_trabajados_hoy / 3600.0, 2)

            # Descuento de almuerzo si hay una sola sesión larga que cubre el horario de almuerzo
            if len(lista_hoy) == 1 and primera_entrada and ultima_salida:
                m_ent = parse_time_to_minutes(primera_entrada)
                m_sal = parse_time_to_minutes(ultima_salida)
                m_alm_in = parse_time_to_minutes(horario["hora_salida_1"])
                m_alm_out = parse_time_to_minutes(horario["hora_entrada_2"])
                if m_ent and m_sal and m_alm_in and m_alm_out:
                    if m_ent <= m_alm_in and m_sal >= m_alm_out:
                        duracion_almuerzo_hrs = (m_alm_out - m_alm_in) / 60.0
                        if duracion_almuerzo_hrs > 0 and horas_trabajadas_hoy > duracion_almuerzo_hrs:
                            horas_trabajadas_hoy = round(horas_trabajadas_hoy - duracion_almuerzo_hrs, 2)

            # Atraso (comparar primera entrada con hora_entrada_1 + tolerancia)
            atraso_min_hoy = 0
            m_primera = parse_time_to_minutes(primera_entrada)
            m_esperada = parse_time_to_minutes(horario["hora_entrada_1"])
            if es_laborable and m_primera is not None and m_esperada is not None:
                diferencia = m_primera - (m_esperada + horario["tolerancia_minutos"])
                if diferencia > 0:
                    atraso_min_hoy = diferencia

            # Horas extras del día
            horas_extras_hoy = 0.0
            if es_laborable and horas_trabajadas_hoy > horario["horas_diarias_esperadas"]:
                horas_extras_hoy = round(horas_trabajadas_hoy - horario["horas_diarias_esperadas"], 2)
            elif not es_laborable and horas_trabajadas_hoy > 0:
                horas_extras_hoy = horas_trabajadas_hoy

            # Determinación del Estado del día
            estado_dia = "Presente"
            if atraso_min_hoy > 0:
                estado_dia = "Atraso"
            if any(not a.hora_salida for a in lista_hoy):
                estado_dia = "Incompleto"

            emp_horas_trabajadas += horas_trabajadas_hoy
            emp_horas_extras += horas_extras_hoy
            emp_atrasos_min += atraso_min_hoy

            detalles_dias.append({
                "fecha": fecha_dia,
                "dia_nombre": dias_semana_esp.get(weekday_idx, ""),
                "entrado": True,
                "salido": bool(ultima_salida),
                "hora_entrada": primera_entrada,
                "hora_salida": ultima_salida,
                "horas_trabajadas": horas_trabajadas_hoy,
                "horas_extras": horas_extras_hoy,
                "atraso_minutos": atraso_min_hoy,
                "estado": estado_dia
            })

        emp_horas_trabajadas = round(emp_horas_trabajadas, 2)
        emp_horas_esperadas = round(emp_horas_esperadas, 2)
        emp_horas_extras = round(emp_horas_extras, 2)

        gran_total_horas += emp_horas_trabajadas
        gran_total_extras += emp_horas_extras

        resumen_empleados.append({
            "usuario_id": u.id,
            "nombre_usuario": u.username,
            "rol": u.rol,
            "dias_trabajados": emp_dias_trabajados,
            "horas_trabajadas": emp_horas_trabajadas,
            "horas_esperadas": emp_horas_esperadas,
            "horas_extras": emp_horas_extras,
            "atraso_minutos": emp_atrasos_min,
            "detalles_dias": detalles_dias
        })

    return {
        "mes": mes,
        "total_empleados": len(usuarios),
        "total_horas_trabajadas": round(gran_total_horas, 2),
        "total_horas_extras": round(gran_total_extras, 2),
        "resumen_empleados": resumen_empleados
    }


@router.get("/reporte-mensual", response_model=schemas.ReporteAsistenciaMensualResponse)
def reporte_mensual_json(
    mes: Optional[str] = None,
    usuario_id: Optional[Union[int, str]] = None,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    uid = None
    if usuario_id not in (None, "", "null", "undefined"):
        try:
            uid = int(usuario_id)
        except (ValueError, TypeError):
            uid = None

    # Si no es admin, solo puede ver su propio reporte
    if current_user.rol != "administrador":
        uid = current_user.id
        
    return calcular_reporte_mensual_datos(db, mes, uid)


@router.get("/reporte-mensual/excel")
def reporte_mensual_excel(
    mes: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(require_role(["administrador"]))
):
    data = calcular_reporte_mensual_datos(db, mes)
    mes_str = data["mes"]

    wb = openpyxl.Workbook()
    
    # ------------------------------------------------------------------------
    # HOJA 1: RESUMEN MENSUAL
    # ------------------------------------------------------------------------
    ws_resumen = wb.active
    ws_resumen.title = "Resumen Mensual"

    header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    title_font = Font(name="Calibri", size=16, bold=True, color="1E3A8A")

    ws_resumen.merge_cells("A1:G1")
    ws_resumen["A1"] = f"REPORTE MENSUAL DE ASISTENCIA Y HORAS EXTRAS - {mes_str}"
    ws_resumen["A1"].font = title_font
    ws_resumen["A1"].alignment = Alignment(horizontal="center", vertical="center")

    headers_resumen = [
        "Empleado", "Rol", "Días Trab.", "Horas Esperadas", "Horas Trabajadas", "Horas Extras", "Atrasos (min)"
    ]
    
    ws_resumen.append([]) # Fila 2 vacía
    ws_resumen.append(headers_resumen) # Fila 3

    for col_num, header_title in enumerate(headers_resumen, 1):
        cell = ws_resumen.cell(row=3, column=col_num)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for emp in data["resumen_empleados"]:
        row = [
            emp["nombre_usuario"],
            emp["rol"].capitalize(),
            emp["dias_trabajados"],
            emp["horas_esperadas"],
            emp["horas_trabajadas"],
            emp["horas_extras"],
            emp["atraso_minutos"]
        ]
        ws_resumen.append(row)

    for col in ws_resumen.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = openpyxl.utils.get_column_letter(col[0].column)
        ws_resumen.column_dimensions[col_letter].width = max(max_len + 4, 15)

    # ------------------------------------------------------------------------
    # HOJA 2: DETALLE DIARIO
    # ------------------------------------------------------------------------
    ws_detalle = wb.create_sheet(title="Detalle Diario")
    ws_detalle.merge_cells("A1:I1")
    ws_detalle["A1"] = f"DESGLOSE DIARIO DE ASISTENCIA - {mes_str}"
    ws_detalle["A1"].font = title_font
    ws_detalle["A1"].alignment = Alignment(horizontal="center", vertical="center")

    headers_detalle = [
        "Empleado", "Fecha", "Día", "Entrada", "Salida", "Horas Trab.", "Horas Extras", "Atraso (min)", "Estado"
    ]
    ws_detalle.append([])
    ws_detalle.append(headers_detalle)

    for col_num, header_title in enumerate(headers_detalle, 1):
        cell = ws_detalle.cell(row=3, column=col_num)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for emp in data["resumen_empleados"]:
        for d in emp["detalles_dias"]:
            row = [
                emp["nombre_usuario"],
                d["fecha"],
                d["dia_nombre"],
                d["hora_entrada"] or "--:--",
                d["hora_salida"] or "--:--",
                d["horas_trabajadas"],
                d["horas_extras"],
                d["atraso_minutos"],
                d["estado"]
            ]
            ws_detalle.append(row)

    for col in ws_detalle.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = openpyxl.utils.get_column_letter(col[0].column)
        ws_detalle.column_dimensions[col_letter].width = max(max_len + 4, 14)

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f"Reporte_Asistencia_{mes_str}.xlsx"
    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/", response_model=List[schemas.AsistenciaResponse])
def listar_asistencias(
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(require_role(["administrador"]))
):
    query = db.query(models.Asistencia)
    
    if fecha_inicio:
        query = query.filter(models.Asistencia.fecha >= fecha_inicio)
    if fecha_fin:
        query = query.filter(models.Asistencia.fecha <= fecha_fin)
        
    return query.order_by(models.Asistencia.created_at.desc()).all()
