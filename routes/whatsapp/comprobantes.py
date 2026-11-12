import os
import re
import time
import traceback
from datetime import datetime
from typing import Optional, List, Dict, Union, Any, Tuple
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_, func

import models
import schemas
import whatsapp_service
from text_utils import normalize_opsatel_text
from database import get_db
from .utils import (
    ECUADOR_TZ,
    _try_float_val,
    calcular_deuda_pendiente_cliente,
    buscar_cliente_por_telefono_comprobante
)

router = APIRouter()


# ============================================================================
# DESTINOS DE REENVÍO AUTOMÁTICO DE COMPROBANTES OCR
# ============================================================================

def asegurar_tabla_destinos_ocr(db: Session):
    try:
        models.WhatsAppDestinoOCR.__table__.create(bind=db.get_bind(), checkfirst=True)
        total = db.query(models.WhatsAppDestinoOCR).count()
        if total == 0:
            def_admin = models.WhatsAppDestinoOCR(
                numero="593987149097",
                nombre="Administración Principal",
                activo=True
            )
            db.add(def_admin)
            db.commit()
    except Exception as e_seed:
        db.rollback()
        print(f"[Destinos OCR] Verificación de tabla: {e_seed}")


@router.get("/destinos-ocr")
def listar_destinos_ocr(db: Session = Depends(get_db)):
    """Lista todos los números configurados para recibir comprobantes OCR."""
    asegurar_tabla_destinos_ocr(db)
    destinos = db.query(models.WhatsAppDestinoOCR).order_by(models.WhatsAppDestinoOCR.id.asc()).all()
    return destinos


@router.get("/destinos-ocr-public")
def listar_destinos_ocr_publico(db: Session = Depends(get_db)):
    """Endpoint público rápido para el puente de WhatsApp (whatsapp_bridge.js)."""
    asegurar_tabla_destinos_ocr(db)
    destinos = db.query(models.WhatsAppDestinoOCR).filter(models.WhatsAppDestinoOCR.activo == True).all()
    return [
        {"id": d.id, "numero": d.numero, "nombre": d.nombre, "activo": d.activo}
        for d in destinos
    ]


@router.post("/destinos-ocr")
def crear_destino_ocr(payload: schemas.WhatsAppDestinoOCRCreate, db: Session = Depends(get_db)):
    """Registra un nuevo número para reenvío automático de comprobantes OCR."""
    asegurar_tabla_destinos_ocr(db)
    num_clean = re.sub(r"\D", "", payload.numero)
    if not num_clean:
        raise HTTPException(status_code=400, detail="Número de teléfono inválido")

    if num_clean.startswith("0") and len(num_clean) == 10:
        num_clean = "593" + num_clean[1:]
    elif len(num_clean) == 9 and num_clean.startswith("9"):
        num_clean = "593" + num_clean

    existente = db.query(models.WhatsAppDestinoOCR).filter(models.WhatsAppDestinoOCR.numero == num_clean).first()
    if existente:
        existente.nombre = payload.nombre.strip()
        existente.activo = payload.activo if payload.activo is not None else True
        db.commit()
        db.refresh(existente)
        return existente

    nuevo = models.WhatsAppDestinoOCR(
        numero=num_clean,
        nombre=payload.nombre.strip(),
        activo=payload.activo if payload.activo is not None else True
    )
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return nuevo


@router.patch("/destinos-ocr/{destino_id}/toggle-activo")
def toggle_activo_destino_ocr(destino_id: int, db: Session = Depends(get_db)):
    """Activa o pausa un número destinatario de OCR."""
    destino = db.query(models.WhatsAppDestinoOCR).filter(models.WhatsAppDestinoOCR.id == destino_id).first()
    if not destino:
        raise HTTPException(status_code=404, detail="Destinatario no encontrado")
    destino.activo = not destino.activo
    db.commit()
    return {"success": True, "activo": destino.activo, "id": destino.id}


@router.delete("/destinos-ocr/{destino_id}")
def eliminar_destino_ocr(destino_id: int, db: Session = Depends(get_db)):
    """Elimina un número de la lista de reenvío OCR."""
    destino = db.query(models.WhatsAppDestinoOCR).filter(models.WhatsAppDestinoOCR.id == destino_id).first()
    if not destino:
        raise HTTPException(status_code=404, detail="Destinatario no encontrado")
    db.delete(destino)
    db.commit()
    return {"success": True, "message": "Destinatario eliminado correctamente"}


# ============================================================================
# COMPROBANTES DE PAGO, VALIDACIÓN CONTRA BD Y APROBACIÓN DE RECIBOS (uploadscr)
# ============================================================================

def asegurar_tabla_comprobantes(db: Session = None):
    """
    Garantiza que la tabla 'comprobantes' y todas sus columnas de validación OCR
    existan tanto en el motor activo (MySQL/PostgreSQL) como en SQLite opsatel.db.
    """
    columnas_nuevas = [
        ("cedula_cliente", "VARCHAR(100)"),
        ("cuenta_origen", "VARCHAR(100)"),
        ("cuenta_destino", "VARCHAR(100)"),
        ("beneficiario", "VARCHAR(255)"),
        ("ordenante", "VARCHAR(255)"),
        ("fecha_comprobante", "VARCHAR(100)"),
        ("texto_ocr", "TEXT"),
        ("saldo_pendiente_bd", "FLOAT"),
        ("categoria_validacion", "VARCHAR(60) DEFAULT 'PENDIENTES_COMPROBANTE'"),
        ("motivo_validacion", "TEXT"),
        ("hash_imagen", "VARCHAR(64)"),
        ("score_autenticidad", "INTEGER DEFAULT 0"),
        ("es_duplicado", "BOOLEAN DEFAULT 0"),
        ("duplicado_detalle", "TEXT"),
        ("pago_id", "INTEGER"),
    ]

    if db is not None:
        try:
            from sqlalchemy import inspect as sa_inspect, text as sa_text
            engine = db.get_bind()
            models.Comprobante.__table__.create(bind=engine, checkfirst=True)

            inspector = sa_inspect(engine)
            existentes = {col["name"].lower() for col in inspector.get_columns("comprobantes")}
            for col_name, col_type in columnas_nuevas:
                if col_name.lower() not in existentes:
                    try:
                        db.execute(sa_text(f"ALTER TABLE comprobantes ADD COLUMN {col_name} {col_type}"))
                        db.commit()
                    except Exception:
                        db.rollback()

            db.query(models.WhatsAppMensajeChat).filter(
                models.WhatsAppMensajeChat.mensaje == "[NON_TEXT_MSG] image"
            ).update({"mensaje": "📷 [Comprobante / Foto enviada]", "tipo": "multimedia"}, synchronize_session=False)
            db.commit()
        except Exception as e_bind:
            db.rollback()
            print(f"[Comprobantes] Verificación de tabla en motor activo: {e_bind}")

    try:
        backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        for candidate in [os.path.join(backend_dir, "opsatel.db"), os.path.join(backend_dir, "..", "opsatel.db")]:
            if os.path.exists(candidate):
                import sqlite3
                s_conn = sqlite3.connect(candidate)
                s_cur = s_conn.cursor()
                s_cur.execute("""
                    CREATE TABLE IF NOT EXISTS comprobantes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        cliente_id INTEGER,
                        numero_telefono VARCHAR(50),
                        nombre_remitente VARCHAR(255),
                        nombre_archivo VARCHAR(255),
                        ruta_archivo VARCHAR(500),
                        url_archivo VARCHAR(500),
                        mimetype VARCHAR(100),
                        tamano_bytes INTEGER,
                        mensaje_texto TEXT,
                        estado VARCHAR(50) DEFAULT 'PENDIENTE',
                        monto FLOAT,
                        banco_origen VARCHAR(100),
                        banco_destino VARCHAR(100),
                        numero_referencia VARCHAR(100),
                        cedula_cliente VARCHAR(100),
                        cuenta_origen VARCHAR(100),
                        cuenta_destino VARCHAR(100),
                        beneficiario VARCHAR(255),
                        ordenante VARCHAR(255),
                        fecha_comprobante VARCHAR(100),
                        texto_ocr TEXT,
                        saldo_pendiente_bd FLOAT,
                        categoria_validacion VARCHAR(60) DEFAULT 'PENDIENTES_COMPROBANTE',
                        motivo_validacion TEXT,
                        pago_id INTEGER,
                        observaciones TEXT,
                        fecha_hora DATETIME,
                        created_at DATETIME,
                        updated_at DATETIME
                    )
                """)
                s_cur.execute("PRAGMA table_info(comprobantes)")
                cols_sq = {row[1].lower() for row in s_cur.fetchall()}
                for col_name, col_type in columnas_nuevas:
                    if col_name.lower() not in cols_sq:
                        try:
                            s_cur.execute(f"ALTER TABLE comprobantes ADD COLUMN {col_name} {col_type}")
                        except Exception:
                            pass
                s_conn.commit()
                s_conn.close()
    except Exception as e_sq:
        print(f"[Comprobantes] Verificación de tabla en SQLite: {e_sq}")


def evaluar_validacion_comprobante(
    db: Session,
    numero_raw: str,
    nombre_remitente: Optional[str],
    ocr_data: Dict[str, Any],
    monto_final: Optional[float],
    referencia_final: Optional[str],
    nombre_archivo: str = "",
    comprobante_id_actual: Optional[int] = None,
    es_registro_historico_sin_ocr: bool = False,
    hash_imagen: Optional[str] = None
) -> Dict[str, Any]:
    cliente_por_telefono, num_clean = buscar_cliente_por_telefono_comprobante(db, numero_raw, nombre_archivo)
    telefono_registrado = cliente_por_telefono is not None

    ordenante_ocr = normalize_opsatel_text(ocr_data.get("ordenante") or "").strip()
    cliente_por_ordenante = None
    if not cliente_por_telefono and ordenante_ocr and len(ordenante_ocr) >= 6:
        try:
            partes = [p for p in ordenante_ocr.split() if len(p) >= 4]
            if partes:
                q_nom = db.query(models.Cliente)
                for p in partes[:2]:
                    q_nom = q_nom.filter(models.Cliente.nombre.ilike(f"%{p}%"))
                cliente_por_ordenante = q_nom.first()
        except Exception:
            pass

    cliente_por_pushname = None
    remitente_norm = normalize_opsatel_text(nombre_remitente or "").strip()
    if not cliente_por_telefono and not cliente_por_ordenante and remitente_norm and len(remitente_norm.split()) >= 2:
        try:
            partes_p = [p for p in remitente_norm.split() if len(p) >= 4]
            if partes_p:
                q_p = db.query(models.Cliente)
                for p in partes_p[:2]:
                    q_p = q_p.filter(models.Cliente.nombre.ilike(f"%{p}%"))
                cliente_por_pushname = q_p.first()
        except Exception:
            pass

    cliente = cliente_por_telefono or cliente_por_ordenante or cliente_por_pushname
    deuda_bd = calcular_deuda_pendiente_cliente(cliente, db) if cliente else 0.0

    monto_evaluado = monto_final
    if (monto_evaluado is None or monto_evaluado <= 0) and telefono_registrado and es_registro_historico_sin_ocr and deuda_bd > 0:
        monto_evaluado = deuda_bd

    razones_pendiente = []
    es_duplicado = False
    duplicado_detalle = None

    # 1. Verificación estricta de duplicados
    hash_evaluar = hash_imagen or ocr_data.get("hash_imagen")
    if hash_evaluar and len(str(hash_evaluar).strip()) >= 16:
        q_dup_hash = db.query(models.Comprobante).filter(
            models.Comprobante.hash_imagen == str(hash_evaluar).strip(),
            models.Comprobante.estado.notin_(["DESCARTADO", "RECHAZADO"])
        )
        if comprobante_id_actual:
            q_dup_hash = q_dup_hash.filter(models.Comprobante.id != comprobante_id_actual)
        dup_hash = q_dup_hash.first()
        if dup_hash:
            es_duplicado = True
            duplicado_detalle = f"Imagen idéntica (hash SHA-256) ya fue enviada en comprobante #{dup_hash.id} ({dup_hash.estado})"
            razones_pendiente.append(
                f"🚨 IMAGEN DUPLICADA: Esta misma foto/archivo ya fue registrada en el comprobante #{dup_hash.id} ({dup_hash.estado})."
            )

    ref_clean = str(referencia_final or "").strip()
    if ref_clean and len(ref_clean) >= 5 and ref_clean.lower() not in ["null", "none", "00000", "000000"]:
        q_dup_aprob = db.query(models.Comprobante).filter(
            models.Comprobante.numero_referencia == ref_clean,
            models.Comprobante.estado == "APROBADO"
        )
        if comprobante_id_actual:
            q_dup_aprob = q_dup_aprob.filter(models.Comprobante.id != comprobante_id_actual)
        dup_aprob = q_dup_aprob.first()
        if dup_aprob:
            es_duplicado = True
            duplicado_detalle = f"Referencia N° {ref_clean} ya fue cobrada en comprobante #{dup_aprob.id}"
            razones_pendiente.append(
                f"🚨 COMPROBANTE YA COBRADO: La referencia N° {ref_clean} ya fue cobrada en el comprobante #{dup_aprob.id}."
            )

        if not dup_aprob:
            q_dup_pend = db.query(models.Comprobante).filter(
                models.Comprobante.numero_referencia == ref_clean,
                models.Comprobante.estado == "PENDIENTE"
            )
            if comprobante_id_actual:
                q_dup_pend = q_dup_pend.filter(models.Comprobante.id != comprobante_id_actual)
            dup_pend = q_dup_pend.first()
            if dup_pend:
                es_duplicado = True
                duplicado_detalle = f"Referencia N° {ref_clean} ya registrada en comprobante #{dup_pend.id} (pendiente de aprobación)"
                razones_pendiente.append(
                    f"⚠️ COMPROBANTE REPETIDO: La referencia N° {ref_clean} ya fue enviada previamente y consta en el comprobante #{dup_pend.id} en revisión."
                )

        if not dup_aprob:
            try:
                pago_dup = db.query(models.Pago).filter(
                    models.Pago.referencia == ref_clean,
                    models.Pago.anulado == False
                ).first()
                if pago_dup:
                    es_duplicado = True
                    fecha_p_str = pago_dup.fecha_pago.strftime("%Y-%m-%d") if pago_dup.fecha_pago else ""
                    duplicado_detalle = f"Referencia N° {ref_clean} ya consta en el Pago #{pago_dup.id} (${pago_dup.monto}) del {fecha_p_str}"
                    razones_pendiente.append(
                        f"🚨 REFERENCIA COBRADA EN BD: El código N° {ref_clean} ya consta en el Pago #{pago_dup.id} (${pago_dup.monto}) de la fecha {fecha_p_str}."
                    )
            except Exception as e_pago:
                print(f"[Comprobantes] Error buscando referencia en historial_pagos: {e_pago}")

        if not dup_aprob and not es_duplicado:
            try:
                pe_dup = db.query(models.PagoExtra).filter(
                    models.PagoExtra.referencia == ref_clean,
                    models.PagoExtra.anulado == False
                ).first()
                if pe_dup:
                    es_duplicado = True
                    duplicado_detalle = f"Referencia N° {ref_clean} ya consta en Pagos Extras #{pe_dup.id} (${pe_dup.monto})"
                    razones_pendiente.append(
                        f"🚨 REFERENCIA COBRADA EN EXTRAS: El código N° {ref_clean} ya fue cobrado en Pago Extra #{pe_dup.id}."
                    )
            except Exception:
                pass

    # 2. Evaluación de autenticidad, destinatario y vigencia
    score_autenticidad = int(ocr_data.get("score_autenticidad") or 0)
    alertas_ocr = ocr_data.get("alertas_autenticidad") or []
    fecha_txt = ocr_data.get("fecha") or ocr_data.get("fecha_transaccion") or ocr_data.get("fecha_comprobante")
    es_fecha_reciente = bool(ocr_data.get("es_fecha_reciente", True))

    if fecha_txt:
        try:
            from services.ocr_comprobantes import parsear_fecha_texto, es_fecha_del_ultimo_mes
            dt_comp = parsear_fecha_texto(fecha_txt)
            if dt_comp:
                es_rec, dias_ant, mot_ant = es_fecha_del_ultimo_mes(dt_comp)
                if not es_rec:
                    es_fecha_reciente = False
                    razones_pendiente.append(f"⚠️ FECHA ANTERIOR: {mot_ant}")
        except Exception as e_fcheck:
            print(f"[Comprobantes] Aviso verificando fecha: {e_fcheck}")

    for al in alertas_ocr:
        if "antiguo" in al.lower() or "anterior" in al.lower():
            if not any("fecha" in r.lower() for r in razones_pendiente):
                razones_pendiente.append(f"⚠️ {al}")
            es_fecha_reciente = False

    if not cliente:
        razones_pendiente.append(
            f"Número remitente (+{num_clean or numero_raw}) no está registrado y no tiene coincidencia con ningún cliente en la base de datos."
        )
    elif not telefono_registrado:
        tel_titular = getattr(cliente, "celular", None) or "Sin celular en BD"
        razones_pendiente.append(
            f"Enviado desde otro número (+{num_clean or numero_raw}) distinto al registrado en BD para {cliente.nombre} (ID #{cliente.id}, Cel. titular: {tel_titular})."
        )

    if monto_evaluado is None or monto_evaluado <= 0:
        razones_pendiente.append(
            "No se logró reconocer el monto en el comprobante. Requiere revisión manual."
        )
    elif cliente and deuda_bd > 0.01 and monto_evaluado > deuda_bd + 0.05:
        exceso = round(monto_evaluado - deuda_bd, 2)
        razones_pendiente.append(
            f"Paga de más: El comprobante es por ${monto_evaluado:.2f}, pero el valor pendiente en BD es de ${deuda_bd:.2f} (excede por ${exceso:.2f})."
        )

    # Clasificación final
    if es_duplicado:
        categoria = "PENDIENTES_COMPROBANTE"
        motivo = " | ".join(razones_pendiente)
    elif not es_fecha_reciente:
        categoria = "PENDIENTES_COMPROBANTE"
        motivo = "⚠️ " + " | ".join(razones_pendiente) if razones_pendiente else "⚠️ Comprobante con fecha anterior (no es del último mes). Requiere revisión manual."
    elif score_autenticidad >= 80 and monto_evaluado and monto_evaluado > 0:
        categoria = "CONFIRMACION_RECIBO"
        sello_ops = " 🏛️ [Cuenta Opsatel Verificada]" if ocr_data.get("es_opsatel_destinatario") else ""
        nombre_cli_str = cliente.nombre if cliente else (nombre_remitente or "Cliente WhatsApp")
        id_cli_str = f" (ID #{cliente.id})" if cliente else ""

        detalles_aut = [f"🛡️ Real Verificado ({score_autenticidad}%)"]
        if cliente:
            if deuda_bd > 0 and abs(monto_evaluado - deuda_bd) <= 0.05:
                detalles_aut.append(f"Paga ${monto_evaluado:.2f} coincidiendo con valor pendiente (${deuda_bd:.2f})")
            elif deuda_bd > monto_evaluado:
                restante = round(deuda_bd - monto_evaluado, 2)
                detalles_aut.append(f"Abono parcial de ${monto_evaluado:.2f} (restará ${restante:.2f})")
            elif deuda_bd > 0:
                detalles_aut.append(f"Paga ${monto_evaluado:.2f} (deuda BD: ${deuda_bd:.2f})")
            else:
                detalles_aut.append(f"Monto: ${monto_evaluado:.2f}")

            if not telefono_registrado:
                detalles_aut.append(f"Enviado desde otro número (+{num_clean or numero_raw})")
        else:
            detalles_aut.append(f"Monto: ${monto_evaluado:.2f}")
            detalles_aut.append(f"Remitente +{num_clean or numero_raw}")

        motivo = f"✅ Listo para confirmar cobro: {nombre_cli_str}{id_cli_str}. " + " | ".join(detalles_aut) + f"{sello_ops}"

    elif len(razones_pendiente) == 0 and cliente and telefono_registrado and monto_evaluado and monto_evaluado > 0:
        categoria = "CONFIRMACION_RECIBO"
        sello_ops = " 🏛️ [Cuenta Opsatel Verificada]" if ocr_data.get("es_opsatel_destinatario") else ""
        if deuda_bd > 0 and abs(monto_evaluado - deuda_bd) <= 0.05:
            motivo = (
                f"✅ Listo para confirmar cobro: Número registrado de {cliente.nombre} (ID #{cliente.id}, Cédula: {getattr(cliente, 'cedula', 'S/N')}). "
                f"Paga ${monto_evaluado:.2f} coincidiendo con su valor pendiente en BD (${deuda_bd:.2f}).{sello_ops}"
            )
        elif deuda_bd > monto_evaluado:
            restante = round(deuda_bd - monto_evaluado, 2)
            motivo = (
                f"✅ Listo para confirmar cobro (Abono parcial): Número registrado de {cliente.nombre} (ID #{cliente.id}). "
                f"Paga ${monto_evaluado:.2f} de ${deuda_bd:.2f} pendiente en BD (restará ${restante:.2f}).{sello_ops}"
            )
        else:
            motivo = (
                f"✅ Listo para confirmar cobro: Número registrado de {cliente.nombre} (ID #{cliente.id}). "
                f"Monto a cobrar: ${monto_evaluado:.2f}.{sello_ops}"
            )
    else:
        categoria = "PENDIENTES_COMPROBANTE"
        motivo = "⚠️ " + " | ".join(razones_pendiente) if razones_pendiente else "⚠️ Requiere revisión manual antes de cobrar."

    return {
        "cliente": cliente,
        "numero_limpio": num_clean,
        "telefono_registrado": telefono_registrado,
        "saldo_pendiente_bd": deuda_bd,
        "monto_evaluado": monto_evaluado,
        "categoria_validacion": categoria,
        "motivo_validacion": motivo,
        "es_duplicado": es_duplicado,
        "duplicado_detalle": duplicado_detalle,
        "score_autenticidad": score_autenticidad
    }


_ULTIMA_REVALIDACION_COMPROBANTES: float = 0.0

def revalidar_comprobantes_existentes_pendientes(db: Session, force: bool = False):
    """
    Re-evalúa de forma ágil comprobantes pendientes para vincular números registrados en la BD.
    Utiliza una ventana de enfriamiento (cooldown) para no re-ejecutar en cada petición HTTP
    y nunca bloquea la respuesta con análisis OCR pesado sincrónico.
    """
    global _ULTIMA_REVALIDACION_COMPROBANTES
    ahora = time.time()
    if not force and (ahora - _ULTIMA_REVALIDACION_COMPROBANTES) < 60.0:
        return
    _ULTIMA_REVALIDACION_COMPROBANTES = ahora

    try:
        from services.ocr_comprobantes import buscar_ruta_archivo, es_documento_comprobante_valido
        pendientes = db.query(models.Comprobante).filter(
            models.Comprobante.estado == "PENDIENTE"
        ).order_by(models.Comprobante.id.desc()).limit(50).all()

        hubo_cambios = False
        for r in pendientes:
            msg_t = (r.mensaje_texto or "").lower()
            if "no es un comprobante válido" in msg_t or "no es un documento valido" in msg_t or "imagen descartada" in msg_t or "documento no válido" in msg_t:
                r.estado = "DESCARTADO"
                r.categoria_validacion = "NO_COMPROBANTE"
                r.motivo_validacion = "Imagen descartada: no es un comprobante de pago válido"
                hubo_cambios = True
                continue

            if r.texto_ocr:
                es_val, mot_val = es_documento_comprobante_valido(r.texto_ocr, {
                    "banco_origen": r.banco_origen,
                    "monto": r.monto,
                    "numero_comprobante": r.numero_referencia,
                    "cuenta_destino": r.cuenta_destino
                })
                if not es_val and not r.monto and not r.banco_origen and not r.numero_referencia:
                    r.estado = "DESCARTADO"
                    r.categoria_validacion = "NO_COMPROBANTE"
                    r.motivo_validacion = "Imagen no admitida: no contiene datos de comprobante bancario"
                    hubo_cambios = True
                    continue

            ruta_real = buscar_ruta_archivo(r.ruta_archivo or r.nombre_archivo or "")
            archivo_existe = bool(ruta_real and os.path.isfile(ruta_real))
            es_historico_sin_ocr = (not archivo_existe) and (not r.texto_ocr)

            score_aut = getattr(r, "score_autenticidad", 0) or 0
            if score_aut == 0 and r.texto_ocr:
                try:
                    from services.ocr_comprobantes import calcular_score_autenticidad
                    sc_res = calcular_score_autenticidad(r.texto_ocr, {
                        "banco_origen": r.banco_origen,
                        "banco_destino": r.banco_destino,
                        "monto": r.monto,
                        "numero_comprobante": r.numero_referencia,
                        "cuenta_destino": r.cuenta_destino,
                        "cuenta_origen": r.cuenta_origen,
                        "beneficiario": r.beneficiario,
                        "estado_transaccion": "EXITOSA"
                    })
                    score_aut = sc_res.get("score_autenticidad", 0)
                    r.score_autenticidad = score_aut
                except Exception:
                    pass

            es_opsatel = bool(
                "opsatel" in (r.observaciones or "").lower()
                or "opsatel" in (r.motivo_validacion or "").lower()
                or "solano herrera bryan" in (r.beneficiario or "").lower()
                or "2206388858" in str(r.cuenta_destino or "")
                or "406060337400" in str(r.cuenta_destino or "")
            )

            eval_res = evaluar_validacion_comprobante(
                db=db,
                numero_raw=r.numero_telefono,
                nombre_remitente=r.nombre_remitente,
                ocr_data={
                    "ordenante": r.ordenante,
                    "score_autenticidad": score_aut,
                    "es_opsatel_destinatario": es_opsatel,
                    "fecha": r.fecha_comprobante
                },
                monto_final=r.monto,
                referencia_final=r.numero_referencia,
                nombre_archivo=r.nombre_archivo or "",
                comprobante_id_actual=r.id,
                es_registro_historico_sin_ocr=es_historico_sin_ocr,
                hash_imagen=getattr(r, "hash_imagen", None)
            )

            cli = eval_res.get("cliente")
            nuevo_cid = cli.id if cli else r.cliente_id
            nueva_ced = (getattr(cli, "cedula", None) if cli else None) or r.cedula_cliente
            nuevo_saldo_bd = eval_res.get("saldo_pendiente_bd")
            nueva_cat = eval_res.get("categoria_validacion")
            nuevo_motivo = eval_res.get("motivo_validacion")
            nuevo_monto = eval_res.get("monto_evaluado")
            nuevo_dup = bool(eval_res.get("es_duplicado", False))
            nuevo_dup_det = eval_res.get("duplicado_detalle")

            if (
                r.cliente_id != nuevo_cid
                or r.categoria_validacion != nueva_cat
                or r.motivo_validacion != nuevo_motivo
                or r.cedula_cliente != nueva_ced
                or r.saldo_pendiente_bd != nuevo_saldo_bd
                or getattr(r, "es_duplicado", False) != nuevo_dup
                or getattr(r, "duplicado_detalle", None) != nuevo_dup_det
                or (r.monto is None and nuevo_monto is not None)
            ):
                r.cliente_id = nuevo_cid
                r.cedula_cliente = nueva_ced
                r.saldo_pendiente_bd = nuevo_saldo_bd
                r.categoria_validacion = nueva_cat
                r.motivo_validacion = nuevo_motivo
                r.es_duplicado = nuevo_dup
                r.duplicado_detalle = nuevo_dup_det
                r.score_autenticidad = score_aut
                if r.monto is None and nuevo_monto is not None:
                    r.monto = nuevo_monto
                if eval_res.get("numero_limpio") and (not r.numero_telefono or "@lid" in str(r.numero_telefono)):
                    r.numero_telefono = eval_res.get("numero_limpio")
                hubo_cambios = True

        if hubo_cambios:
            db.commit()
    except Exception as e_rev:
        db.rollback()
        print(f"[Comprobantes] Aviso en revalidación automática de pendientes: {e_rev}")


@router.get("/identificar-cliente-rapido")
def identificar_cliente_rapido(
    numero: str,
    db: Session = Depends(get_db)
):
    """
    Consulta rápida de cliente por teléfono para que el bridge de WhatsApp
    nombre el archivo de imagen con ID, Nombre y Fecha al momento de descargarlo en uploads.
    """
    try:
        cli, num_clean = buscar_cliente_por_telefono_comprobante(db, numero)
        if cli:
            return {
                "encontrado": True,
                "cliente_id": cli.id,
                "nombre": cli.nombre,
                "cedula": getattr(cli, "cedula", None),
                "numero_limpio": num_clean
            }
    except Exception as e:
        print(f"[Identificar Cliente] Error en consulta rápida: {e}")
    return {"encontrado": False, "cliente_id": None, "nombre": None, "numero_limpio": numero}


@router.post("/registrar-comprobante")
def registrar_comprobante_endpoint(
    payload: schemas.ComprobanteCreate,
    db: Session = Depends(get_db)
):
    """
    Endpoint invocado automáticamente por el puente de WhatsApp (whatsapp_bridge.js)
    cuando se detecta y descarga una imagen en la carpeta 'uploadscr'.
    1. Sube la calidad de la imagen y extrae todos los campos por OCR.
    2. Compara teléfono, cédula, titular y monto pagado contra la deuda pendiente en BD.
    3. Clasifica automáticamente en 'CONFIRMACION_RECIBO' o 'PENDIENTES_COMPROBANTE'.
    """
    try:
        asegurar_tabla_comprobantes(db)

        ocr_data = {}
        try:
            from services.ocr_comprobantes import analizar_comprobante_ocr
            ocr_data = analizar_comprobante_ocr(payload.ruta_archivo or payload.nombre_archivo)
        except Exception as e_ocr:
            print(f"[Comprobantes OCR] Error en extracción OCR: {e_ocr}")

        es_documento_valido = bool(ocr_data.get("es_documento_valido", False))
        if not es_documento_valido:
            print(f"[Comprobantes] ⚠️ La imagen recibida '{payload.nombre_archivo}' NO es un comprobante válido ({ocr_data.get('motivo_validacion_documento')})")
            return {
                "success": False,
                "es_documento_valido": False,
                "error": "la imagen mandada no es un documento valido",
                "message": "La imagen enviada no es un documento válido. Por favor, envía un comprobante de pago o transferencia bancaria válido.",
                "resumen_ocr": ocr_data.get("resumen_ocr"),
                "texto_extraido": ocr_data.get("texto_extraido", "")
            }

        monto_final = payload.monto if payload.monto is not None else ocr_data.get("monto")
        banco_final = payload.banco_origen or ocr_data.get("banco_origen")
        banco_destino_final = payload.banco_destino or ocr_data.get("banco_destino")
        referencia_final = payload.numero_referencia or ocr_data.get("numero_referencia")
        cuenta_origen_final = ocr_data.get("cuenta_origen")
        cuenta_destino_final = ocr_data.get("cuenta_destino")
        beneficiario_final = ocr_data.get("beneficiario")
        ordenante_final = ocr_data.get("ordenante")
        fecha_comp_final = ocr_data.get("fecha")
        texto_ocr_final = ocr_data.get("texto_extraido") or ""

        hash_final = payload.hash_imagen or ocr_data.get("hash_imagen")
        score_autenticidad = int(ocr_data.get("score_autenticidad") or 0)

        eval_res = evaluar_validacion_comprobante(
            db=db,
            numero_raw=payload.numero_telefono,
            nombre_remitente=payload.nombre_remitente,
            ocr_data=ocr_data,
            monto_final=monto_final,
            referencia_final=referencia_final,
            nombre_archivo=payload.nombre_archivo or "",
            hash_imagen=hash_final
        )
        cliente = eval_res["cliente"]
        saldo_pendiente_bd = eval_res["saldo_pendiente_bd"]
        categoria_validacion = eval_res["categoria_validacion"]
        motivo_validacion = eval_res["motivo_validacion"]
        monto_final = eval_res["monto_evaluado"]
        cedula_cliente = getattr(cliente, "cedula", None) if cliente else None
        es_duplicado = bool(eval_res.get("es_duplicado", False))
        duplicado_detalle = eval_res.get("duplicado_detalle")

        num_raw = payload.numero_telefono or ""
        num_clean = eval_res.get("numero_limpio") or "".join([c for c in num_raw if c.isdigit()])

        observaciones_lista = []
        if payload.observaciones:
            observaciones_lista.append(payload.observaciones)
        if motivo_validacion:
            observaciones_lista.append(motivo_validacion)
        if ocr_data.get("resumen_ocr"):
            observaciones_lista.append(ocr_data.get("resumen_ocr"))
        observaciones_final = "\n".join(observaciones_lista) if observaciones_lista else None

        ahora_ec = datetime.now(ECUADOR_TZ).replace(tzinfo=None)

        nombre_arch_final = payload.nombre_archivo or ""
        ruta_arch_final = payload.ruta_archivo or ""
        url_arch_final = payload.url_archivo or ""
        if cliente and cliente.id and "ID_sin_registrar" in nombre_arch_final:
            try:
                nom_limpio = re.sub(r'[^a-zA-Z0-9_\-]', '_', getattr(cliente, 'nombre', '') or 'Cliente')
                nom_limpio = re.sub(r'_+', '_', nom_limpio).strip('_')[:40]
                nuevo_nombre_arch = re.sub(
                    r"comp_ID_sin_registrar_[^_]+_(?:\d{8,13}_)?",
                    f"comp_ID_{cliente.id}_{nom_limpio}_",
                    nombre_arch_final
                )
                backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
                candidatos_dir = [
                    os.path.join(backend_dir, "uploadscr"),
                    os.path.join(backend_dir, "uploads", "uploadscr"),
                    os.path.join(backend_dir, "uploads", "comprobantes"),
                    os.path.join(backend_dir, "..", "Opsatel-Frontend", "uploadscr"),
                    os.path.join(backend_dir, "..", "Opsatel-Frontend", "public", "uploadscr"),
                ]
                renombrado = False
                for c_dir in candidatos_dir:
                    old_f = os.path.join(c_dir, nombre_arch_final)
                    new_f = os.path.join(c_dir, nuevo_nombre_arch)
                    if os.path.exists(old_f):
                        try:
                            os.rename(old_f, new_f)
                            renombrado = True
                        except Exception:
                            pass
                if renombrado:
                    nombre_arch_final = nuevo_nombre_arch
                    url_arch_final = f"/uploadscr/{nuevo_nombre_arch}"
                    ruta_arch_final = f"uploadscr/{nuevo_nombre_arch}"
            except Exception as e_ren:
                print(f"[Comprobante] Aviso renombrando archivo con cliente_id: {e_ren}")

        nuevo_comp = models.Comprobante(
            cliente_id=cliente.id if cliente else None,
            numero_telefono=num_clean or payload.numero_telefono,
            nombre_remitente=payload.nombre_remitente or (cliente.nombre if cliente else (ordenante_final or "Cliente WhatsApp")),
            nombre_archivo=nombre_arch_final,
            ruta_archivo=ruta_arch_final,
            url_archivo=url_arch_final,
            mimetype=payload.mimetype or "image/jpeg",
            tamano_bytes=payload.tamano_bytes,
            mensaje_texto=payload.mensaje_texto or "",
            estado="PENDIENTE",
            monto=monto_final,
            banco_origen=banco_final,
            banco_destino=banco_destino_final,
            numero_referencia=referencia_final,
            cedula_cliente=cedula_cliente,
            cuenta_origen=cuenta_origen_final,
            cuenta_destino=cuenta_destino_final,
            beneficiario=beneficiario_final,
            ordenante=ordenante_final,
            fecha_comprobante=fecha_comp_final,
            texto_ocr=texto_ocr_final,
            saldo_pendiente_bd=saldo_pendiente_bd,
            categoria_validacion=categoria_validacion,
            motivo_validacion=motivo_validacion,
            hash_imagen=hash_final,
            score_autenticidad=score_autenticidad,
            es_duplicado=es_duplicado,
            duplicado_detalle=duplicado_detalle,
            observaciones=observaciones_final,
            fecha_hora=ahora_ec,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )

        db.add(nuevo_comp)
        db.commit()
        db.refresh(nuevo_comp)

        print(
            f"[Comprobantes] ✅ Comprobante #{nuevo_comp.id} registrado [{categoria_validacion}] - "
            f"Cliente: {cliente.nombre if cliente else 'No vinculado'} | Monto: ${monto_final or 0:.2f} | Deuda BD: ${saldo_pendiente_bd:.2f}"
            + (f" | 🚨 DUPLICADO: {duplicado_detalle}" if es_duplicado else "")
        )

        return {
            "success": True,
            "es_documento_valido": True,
            "es_duplicado": es_duplicado,
            "duplicado_detalle": duplicado_detalle,
            "score_autenticidad": score_autenticidad,
            "hash_imagen": hash_final,
            "message": "Comprobante registrado y validado exitosamente",
            "comprobante_id": nuevo_comp.id,
            "url_archivo": nuevo_comp.url_archivo,
            "cliente_id": cliente.id if cliente else None,
            "cliente_nombre": cliente.nombre if cliente else None,
            "cliente_cedula": cedula_cliente,
            "cliente_telefono": getattr(cliente, "celular", None) or nuevo_comp.numero_telefono,
            "cliente_plan": getattr(cliente, "plan", None) if cliente else None,
            "telefono_registrado": eval_res["telefono_registrado"],
            "saldo_pendiente_bd": saldo_pendiente_bd,
            "categoria_validacion": categoria_validacion,
            "motivo_validacion": motivo_validacion,
            "monto": nuevo_comp.monto,
            "banco_origen": nuevo_comp.banco_origen,
            "banco_destino": banco_destino_final,
            "beneficiario": beneficiario_final,
            "ordenante": ordenante_final,
            "cuenta_destino": cuenta_destino_final,
            "cuenta_origen": cuenta_origen_final,
            "numero_referencia": nuevo_comp.numero_referencia,
            "fecha": fecha_comp_final,
            "estado_transaccion": ocr_data.get("estado_transaccion"),
            "ocr_detectado": bool(ocr_data.get("success")),
            "resumen_ocr": ocr_data.get("resumen_ocr"),
            "texto_extraido": texto_ocr_final,
            "ocr_completo": ocr_data
        }

    except Exception as e:
        db.rollback()
        print(f"[Comprobantes] ❌ Error registrando comprobante: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error al registrar comprobante: {str(e)}")


@router.get("/comprobantes")
def listar_comprobantes(
    estado: Optional[str] = None,
    categoria: Optional[str] = None,
    q: Optional[str] = None,
    cliente_id: Optional[int] = None,
    limit: int = 150,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """
    Lista todos los comprobantes guardados con detalles del cliente, comparación de saldos y sección:
    - CONFIRMACION_RECIBO (por confirmar para que se cobre en la BD)
    - PENDIENTES_COMPROBANTE (tuvieron algún problema: número no registrado, otro número, paga de más, dato no reconocido)
    - COBRADOS / HISTORIAL (registro de comprobantes ya cobrados en la BD)
    """
    try:
        asegurar_tabla_comprobantes(db)
        revalidar_comprobantes_existentes_pendientes(db)

        count_confirmacion = db.query(models.Comprobante).filter(
            models.Comprobante.estado == "PENDIENTE",
            models.Comprobante.categoria_validacion == "CONFIRMACION_RECIBO"
        ).count()
        count_pendientes_anomalia = db.query(models.Comprobante).filter(
            models.Comprobante.estado == "PENDIENTE",
            models.Comprobante.categoria_validacion == "PENDIENTES_COMPROBANTE"
        ).count()
        count_aprobados = db.query(models.Comprobante).filter(
            models.Comprobante.estado == "APROBADO"
        ).count()
        count_rechazados = db.query(models.Comprobante).filter(
            models.Comprobante.estado.in_(["RECHAZADO", "DESCARTADO"])
        ).count()

        query = db.query(models.Comprobante)

        if estado and estado.strip() and estado.upper() != "TODOS":
            query = query.filter(models.Comprobante.estado == estado.strip().upper())
        else:
            query = query.filter(models.Comprobante.estado != "DESCARTADO")

        if categoria and categoria.strip() and categoria.upper() != "TODOS":
            cat_up = categoria.strip().upper()
            if cat_up == "CONFIRMACION_RECIBO":
                query = query.filter(
                    models.Comprobante.categoria_validacion == "CONFIRMACION_RECIBO",
                    models.Comprobante.estado == "PENDIENTE"
                )
            elif cat_up == "PENDIENTES_COMPROBANTE":
                query = query.filter(
                    models.Comprobante.categoria_validacion == "PENDIENTES_COMPROBANTE",
                    models.Comprobante.estado == "PENDIENTE"
                )
            elif cat_up in ("COBRADOS", "YA_COBRADOS"):
                query = query.filter(models.Comprobante.estado == "APROBADO")
            elif cat_up == "HISTORIAL":
                query = query.filter(models.Comprobante.estado.in_(["APROBADO", "RECHAZADO", "REVISADO"]))

        if cliente_id:
            query = query.filter(models.Comprobante.cliente_id == cliente_id)

        if q and q.strip():
            filtro = f"%{normalize_opsatel_text(q.strip())}%"
            filtro_raw = f"%{q.strip()}%"
            query = query.filter(
                or_(
                    models.Comprobante.numero_telefono.ilike(filtro_raw),
                    models.Comprobante.nombre_remitente.ilike(filtro),
                    models.Comprobante.cedula_cliente.ilike(filtro_raw),
                    models.Comprobante.ordenante.ilike(filtro),
                    models.Comprobante.beneficiario.ilike(filtro),
                    models.Comprobante.banco_origen.ilike(filtro),
                    models.Comprobante.nombre_archivo.ilike(filtro_raw),
                    models.Comprobante.mensaje_texto.ilike(filtro_raw),
                    models.Comprobante.numero_referencia.ilike(filtro_raw)
                )
            )

        total = query.count()
        registros = query.order_by(models.Comprobante.id.desc()).offset(offset).limit(limit).all()

        resultado = []
        for r in registros:
            c_info = None
            deuda_actual_bd = r.saldo_pendiente_bd
            if r.cliente:
                deuda_actual_bd = calcular_deuda_pendiente_cliente(r.cliente, db)
                c_info = {
                    "id": r.cliente.id,
                    "nombre": r.cliente.nombre,
                    "cedula": getattr(r.cliente, "cedula", None) or r.cedula_cliente or "N/A",
                    "celular": getattr(r.cliente, "celular", None) or "N/A",
                    "plan": getattr(r.cliente, "plan", "N/A"),
                    "nodo": getattr(r.cliente, "nodo", "N/A"),
                    "estado_servicio": getattr(r.cliente, "estado", "Activo"),
                    "saldo": float(getattr(r.cliente, "saldo", 0.0) or 0.0),
                    "deuda_total": deuda_actual_bd,
                    "deuda_total_bd": deuda_actual_bd
                }
            resultado.append({
                "id": r.id,
                "cliente_id": r.cliente_id,
                "cliente": c_info,
                "cedula_cliente": (c_info["cedula"] if c_info else r.cedula_cliente) or "No registrada",
                "numero_telefono": r.numero_telefono,
                "nombre_remitente": r.nombre_remitente,
                "nombre_archivo": r.nombre_archivo,
                "ruta_archivo": r.ruta_archivo,
                "url_archivo": r.url_archivo,
                "mimetype": r.mimetype,
                "tamano_bytes": r.tamano_bytes,
                "mensaje_texto": r.mensaje_texto,
                "estado": r.estado or "PENDIENTE",
                "monto": r.monto,
                "banco_origen": r.banco_origen,
                "banco_destino": r.banco_destino,
                "numero_referencia": r.numero_referencia,
                "cuenta_origen": r.cuenta_origen,
                "cuenta_destino": r.cuenta_destino,
                "beneficiario": r.beneficiario,
                "ordenante": r.ordenante,
                "fecha_comprobante": r.fecha_comprobante,
                "texto_ocr": r.texto_ocr,
                "saldo_pendiente_bd": r.saldo_pendiente_bd if r.saldo_pendiente_bd is not None else deuda_actual_bd,
                "deuda_actual_bd": deuda_actual_bd,
                "categoria_validacion": r.categoria_validacion or "PENDIENTES_COMPROBANTE",
                "motivo_validacion": r.motivo_validacion,
                "hash_imagen": getattr(r, "hash_imagen", None),
                "score_autenticidad": getattr(r, "score_autenticidad", 0) or 0,
                "es_duplicado": bool(getattr(r, "es_duplicado", False)),
                "duplicado_detalle": getattr(r, "duplicado_detalle", None),
                "pago_id": r.pago_id,
                "observaciones": r.observaciones,
                "fecha_hora": r.fecha_hora.isoformat() if r.fecha_hora else None,
                "created_at": r.created_at.isoformat() if r.created_at else None
            })

        return {
            "success": True,
            "total": total,
            "resumen_categorias": {
                "confirmacion_recibo": count_confirmacion,
                "pendientes_comprobante": count_pendientes_anomalia,
                "total_por_atender": count_confirmacion + count_pendientes_anomalia,
                "cobrados": count_aprobados,
                "aprobados": count_aprobados,
                "rechazados": count_rechazados
            },
            "comprobantes": resultado
        }
    except Exception as e:
        print(f"[Comprobantes] Error listando comprobantes: {e}")
        return {
            "success": False,
            "total": 0,
            "resumen_categorias": {
                "confirmacion_recibo": 0,
                "pendientes_comprobante": 0,
                "total_por_atender": 0,
                "cobrados": 0,
                "aprobados": 0,
                "rechazados": 0
            },
            "comprobantes": [],
            "error": str(e)
        }


@router.post("/comprobantes/{comprobante_id}/aprobar-pago")
def aprobar_pago_comprobante(
    comprobante_id: int,
    payload: Optional[schemas.ComprobanteAprobarRequest] = None,
    db: Session = Depends(get_db)
):
    """
    Confirma y cobra un comprobante de pago (desde Confirmación de Recibo o Pendientes Comprobante):
    1. Vincula al cliente (el detectado automáticamente o el indicado por el operador).
    2. Registra el pago en 'historial_pagos' con el banco y número de referencia del OCR.
    3. Descuenta el monto pagado de la deuda pendiente del cliente (Adicional -> Plus -> Internet).
    4. Si la deuda queda en $0.00, reactiva automáticamente el servicio del cliente.
    5. Pasa el comprobante a 'APROBADO' (Registro de Comprobantes ya Cobrados) y envía confirmación por WhatsApp.
    """
    try:
        asegurar_tabla_comprobantes(db)
        comp = db.query(models.Comprobante).filter(models.Comprobante.id == comprobante_id).first()
        if not comp:
            raise HTTPException(status_code=404, detail="Comprobante no encontrado")

        if comp.estado == "APROBADO" and comp.pago_id:
            raise HTTPException(status_code=400, detail="Este comprobante ya fue cobrado y aplicado anteriormente.")

        target_cliente_id = (payload.cliente_id if payload and payload.cliente_id else None) or comp.cliente_id
        if not target_cliente_id:
            raise HTTPException(
                status_code=400,
                detail="Este comprobante no tiene un cliente vinculado. Selecciona o vincula primero el cliente para cobrar el pago."
            )

        cliente = db.query(models.Cliente).filter(models.Cliente.id == target_cliente_id).first()
        if not cliente:
            raise HTTPException(status_code=404, detail=f"Cliente ID #{target_cliente_id} no encontrado en la base de datos.")

        monto_payload = None
        if payload:
            if payload.monto_aplicar is not None:
                monto_payload = payload.monto_aplicar
            elif payload.monto is not None:
                monto_payload = payload.monto

        monto_pagar = monto_payload if monto_payload is not None else comp.monto
        if monto_pagar is None or float(monto_pagar) <= 0:
            deuda_fallback = calcular_deuda_pendiente_cliente(cliente, db)
            if deuda_fallback > 0:
                monto_pagar = deuda_fallback
            else:
                raise HTTPException(status_code=400, detail="El monto del comprobante debe ser mayor a $0.00 para cobrar el pago.")
        monto_pagar = round(float(monto_pagar), 2)

        metodo_pago = (
            (payload.metodo_pago if payload and payload.metodo_pago else None)
            or comp.banco_origen
            or comp.banco_destino
            or "Transferencia"
        )
        referencia_pago = (
            (payload.numero_referencia if payload and payload.numero_referencia else None)
            or comp.numero_referencia
            or f"COMP-{comp.id}"
        )

        ahora_ec = datetime.now(ECUADOR_TZ).replace(tzinfo=None)
        mes_actual = ahora_ec.strftime("%Y-%m")

        curr_adic = max(0.0, _try_float_val(cliente.adicional))
        curr_plus = max(0.0, _try_float_val(cliente.plus))
        restante_aplicar = monto_pagar

        m_adic = round(min(curr_adic, restante_aplicar), 2)
        restante_aplicar = round(restante_aplicar - m_adic, 2)

        m_plus = round(min(curr_plus, restante_aplicar), 2)
        restante_aplicar = round(restante_aplicar - m_plus, 2)

        m_internet = round(restante_aplicar, 2)

        turno = db.query(models.TurnoCaja).filter(models.TurnoCaja.estado == "Abierto").order_by(models.TurnoCaja.id.desc()).first()
        turno_id = turno.id if turno else None

        nuevo_pago = models.Pago(
            cliente_id=cliente.id,
            monto=monto_pagar,
            metodo_pago=metodo_pago,
            mes_correspondiente=mes_actual,
            referencia=referencia_pago,
            monto_internet=m_internet,
            monto_plus=m_plus,
            monto_adicional=m_adic,
            fecha_pago=ahora_ec,
            estado="Completado",
            anulado=False,
            turnocaja_id=turno_id
        )
        db.add(nuevo_pago)

        if m_adic > 0:
            nuevo_adic = max(0.0, round(curr_adic - m_adic, 2))
            cliente.adicional = str(nuevo_adic) if nuevo_adic > 0 else ""
            cliente.adicional_pagado = round(float(cliente.adicional_pagado or 0.0) + m_adic, 2)

        if m_plus > 0:
            nuevo_plus = max(0.0, round(curr_plus - m_plus, 2))
            cliente.plus = str(nuevo_plus) if nuevo_plus > 0 else ""
            cliente.plus_pagado = round(float(cliente.plus_pagado or 0.0) + m_plus, 2)

        cliente.saldo = round(float(cliente.saldo or 0.0) - m_internet, 2)
        cliente.pago_mensual = round(float(cliente.pago_mensual or 0.0) + monto_pagar, 2)
        cliente.bank = metodo_pago[:50]
        cliente.cod = str(referencia_pago)[:50]
        cliente.payment_date = ahora_ec.strftime("%Y-%m-%d")

        if m_internet > 0:
            prev_net = _try_float_val(cliente.internet_payment)
            cliente.internet_payment = str(round(prev_net + m_internet, 2))

        reactivado_fw = False
        try:
            from routes.clientes import sync_cliente_balances, verificar_y_reactivar_cliente_por_pago_completo
            sync_cliente_balances(cliente, db)
            info_react = verificar_y_reactivar_cliente_por_pago_completo(cliente, db, motivo="APROBAR_COMPROBANTE_OCR")
            reactivado_fw = bool(info_react.get("reactivado"))
        except Exception as e_sync:
            print(f"[Comprobantes] Aviso sincronizando balances/firewall: {e_sync}")
            cliente.total_pago = round(
                float(cliente.saldo or 0.0) + _try_float_val(cliente.plus) + _try_float_val(cliente.adicional), 2
            )

        db.flush()

        comp.cliente_id = cliente.id
        comp.cedula_cliente = getattr(cliente, "cedula", None)
        comp.monto = monto_pagar
        comp.banco_origen = metodo_pago
        comp.numero_referencia = referencia_pago
        comp.estado = "APROBADO"
        comp.pago_id = nuevo_pago.id
        if payload and payload.observaciones:
            comp.observaciones = payload.observaciones
        comp.updated_at = datetime.utcnow()

        db.commit()

        deuda_restante = max(0.0, round(
            max(0.0, _try_float_val(cliente.saldo)) +
            max(0.0, _try_float_val(cliente.plus)) +
            max(0.0, _try_float_val(cliente.adicional)),
            2
        ))

        notificar = True
        if payload is not None:
            if payload.notificar_cliente is not None:
                notificar = bool(payload.notificar_cliente)
            elif payload.notificar_whatsapp is not None:
                notificar = bool(payload.notificar_whatsapp)

        if notificar and comp.numero_telefono:
            try:
                estado_cuenta_txt = (
                    "✅ *Tu cuenta se encuentra al día ($0.00 pendiente).*"
                    if deuda_restante <= 0.01
                    else f"📌 *Saldo restante pendiente:* ${deuda_restante:.2f}"
                )
                msg_confirmacion = (
                    f"🧾 *RECIBO DE PAGO CONFIRMADO - OPSATEL*\n\n"
                    f"Hola *{cliente.nombre}* (ID #{cliente.id}), tu comprobante ha sido verificado y cobrado exitosamente:\n\n"
                    f"💰 *Valor abonado:* ${monto_pagar:.2f}\n"
                    f"🏦 *Entidad:* {metodo_pago}\n"
                    f"🔢 *N° Referencia:* {referencia_pago}\n"
                    f"📅 *Fecha:* {ahora_ec.strftime('%d/%m/%Y %H:%M')}\n"
                    f"{estado_cuenta_txt}\n\n"
                    f"¡Muchas gracias por tu pago puntual! 😊"
                )
                whatsapp_service.send_whatsapp_message(comp.numero_telefono, msg_confirmacion)
            except Exception as e_wa:
                print(f"[Comprobantes] Aviso enviando confirmación WhatsApp: {e_wa}")

        return {
            "success": True,
            "message": f"Pago de ${monto_pagar:.2f} cobrado en BD para {cliente.nombre} (ID #{cliente.id}). Movido a Registro de Comprobantes ya Cobrados.",
            "comprobante_id": comp.id,
            "pago_id": nuevo_pago.id,
            "cliente_id": cliente.id,
            "cliente_nombre": cliente.nombre,
            "monto_aplicado": monto_pagar,
            "saldo_restante": deuda_restante,
            "reactivado_firewall": reactivado_fw
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"[Comprobantes] ❌ Error aprobando comprobante: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error al aprobar el pago del comprobante: {str(e)}")


@router.patch("/comprobantes/{comprobante_id}")
def actualizar_comprobante(
    comprobante_id: int,
    payload: schemas.ComprobanteUpdate,
    db: Session = Depends(get_db)
):
    """Actualiza el estado, cliente vinculado, categoría o notas de verificación de un comprobante"""
    try:
        asegurar_tabla_comprobantes(db)
        comp = db.query(models.Comprobante).filter(models.Comprobante.id == comprobante_id).first()
        if not comp:
            raise HTTPException(status_code=404, detail="Comprobante no encontrado")

        if payload.estado is not None:
            comp.estado = payload.estado.strip().upper()
        if payload.monto is not None:
            comp.monto = payload.monto
        if payload.banco_origen is not None:
            comp.banco_origen = payload.banco_origen.strip()
        if payload.banco_destino is not None:
            comp.banco_destino = payload.banco_destino.strip()
        if payload.numero_referencia is not None:
            comp.numero_referencia = payload.numero_referencia.strip()
        if payload.observaciones is not None:
            comp.observaciones = payload.observaciones.strip()
        if payload.categoria_validacion is not None:
            comp.categoria_validacion = payload.categoria_validacion.strip().upper()
        if payload.motivo_validacion is not None:
            comp.motivo_validacion = payload.motivo_validacion.strip()
        if payload.cliente_id is not None:
            comp.cliente_id = payload.cliente_id
            c_vinc = db.query(models.Cliente).filter(models.Cliente.id == payload.cliente_id).first()
            if c_vinc:
                comp.cedula_cliente = getattr(c_vinc, "cedula", None)
                comp.saldo_pendiente_bd = calcular_deuda_pendiente_cliente(c_vinc)

        comp.updated_at = datetime.utcnow()
        db.commit()

        return {"success": True, "message": "Comprobante actualizado correctamente", "id": comp.id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al actualizar comprobante: {str(e)}")


@router.delete("/comprobantes/{comprobante_id}")
def eliminar_comprobante(
    comprobante_id: int,
    eliminar_archivo: bool = False,
    db: Session = Depends(get_db)
):
    """Elimina el registro de un comprobante y opcionalmente su archivo del disco"""
    try:
        asegurar_tabla_comprobantes(db)
        comp = db.query(models.Comprobante).filter(models.Comprobante.id == comprobante_id).first()
        if not comp:
            raise HTTPException(status_code=404, detail="Comprobante no encontrado")

        if eliminar_archivo and comp.nombre_archivo:
            for base in [
                os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "Opsatel-Frontend", "uploadscr")),
                os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "Opsatel-Frontend", "public", "uploadscr")),
                os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "uploadscr"))
            ]:
                f_path = os.path.join(base, comp.nombre_archivo)
                if os.path.exists(f_path):
                    try:
                        os.remove(f_path)
                    except Exception:
                        pass

        db.delete(comp)
        db.commit()
        return {"success": True, "message": "Comprobante eliminado correctamente"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al eliminar comprobante: {str(e)}")
