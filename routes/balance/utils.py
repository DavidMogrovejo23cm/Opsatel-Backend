"""
@file utils.py
@description Utilidades, normalización y saneamiento de esquemas para el módulo de Balance.
"""
import re
import logging
from sqlalchemy import text, inspect
from sqlalchemy.orm import Session
import models

logger = logging.getLogger("opsatel.routes.balance.utils")

def normalizar_parroquia(parr: str) -> str:
    if not parr or not str(parr).strip():
        return "BANOS"
    p = str(parr).strip().upper()
    p = p.replace("Á", "A").replace("É", "E").replace("Í", "I").replace("Ó", "O").replace("Ú", "U")
    p = p.replace("Ñ", "N")
    if "BANO" in p:
        return "BANOS"
    if "SAYAUS" in p:
        return "SAYAUSI"
    if "YANUN" in p:
        return "YANUNCAY"
    if "JOAQUIN" in p:
        return "SAN JOAQUIN"
    if "VALLE" in p:
        return "EL VALLE"
    if "RICAURT" in p:
        return "RICAURTE"
    if "TARQUI" in p:
        return "TARQUI"
    return p if p else "BANOS"

def try_float_val(val, default=0.0):
    try:
        if val is None:
            return default
        s = str(val).replace("$", "").replace(",", ".").strip()
        return float(s) if s else default
    except Exception:
        return default

def try_int_val(val, default=0):
    try:
        if val is None:
            return default
        m = re.search(r'(\d+)', str(val))
        return int(m.group(1)) if m else default
    except Exception:
        return default

def asegurar_columnas_egresos(db: Session):
    """
    Verifica y repara dinámicamente la tabla egresos_balance y gastos_fijos_balance en tiempo de ejecución.
    """
    try:
        bind = db.get_bind()
        insp = inspect(bind)

        if not insp.has_table("gastos_fijos_balance"):
            try:
                models.Base.metadata.tables["gastos_fijos_balance"].create(bind, checkfirst=True)
            except Exception as t_err:
                logger.warning(f"Aviso creando tabla gastos_fijos_balance: {t_err}")

        if insp.has_table("egresos_balance"):
            cols = {c["name"] for c in insp.get_columns("egresos_balance")}
            is_postgres = "postgresql" in str(bind.url).lower()
            quote = '"' if is_postgres else '`'

            if "estado" not in cols:
                try:
                    db.execute(text(f"ALTER TABLE {quote}egresos_balance{quote} ADD COLUMN {quote}estado{quote} VARCHAR(50) DEFAULT 'Realizado'"))
                    db.commit()
                except Exception as e_col:
                    db.rollback()
                    logger.warning(f"Aviso agregando columna estado: {e_col}")

            if "gasto_fijo_id" not in cols:
                try:
                    db.execute(text(f"ALTER TABLE {quote}egresos_balance{quote} ADD COLUMN {quote}gasto_fijo_id{quote} INT DEFAULT NULL"))
                    db.commit()
                except Exception as e_col:
                    db.rollback()
                    logger.warning(f"Aviso agregando columna gasto_fijo_id: {e_col}")

            if "mes" not in cols:
                try:
                    db.execute(text(f"ALTER TABLE {quote}egresos_balance{quote} ADD COLUMN {quote}mes{quote} VARCHAR(7) DEFAULT NULL"))
                    db.commit()
                except Exception as e_col:
                    db.rollback()
                    logger.warning(f"Aviso agregando columna mes: {e_col}")

            try:
                db.execute(text(f"UPDATE {quote}egresos_balance{quote} SET {quote}estado{quote} = 'Realizado' WHERE {quote}estado{quote} IS NULL OR {quote}estado{quote} = ''"))
                db.execute(text(f"UPDATE {quote}egresos_balance{quote} SET {quote}mes{quote} = SUBSTR({quote}fecha{quote}, 1, 7) WHERE ({quote}mes{quote} IS NULL OR {quote}mes{quote} = '') AND {quote}fecha{quote} IS NOT NULL AND LENGTH({quote}fecha{quote}) >= 7"))
                db.commit()
            except Exception as e_upd:
                db.rollback()
                logger.warning(f"Aviso actualizando estado y mes de egresos: {e_upd}")
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        logger.warning(f"Aviso general en asegurar_columnas_egresos: {e}")

def sincronizar_gastos_fijos_mes(mes: str, db: Session):
    """
    Garantiza que para el mes indicado, cada gasto fijo activo tenga su registro en egresos_balance.
    """
    asegurar_columnas_egresos(db)
    if not mes or len(mes) < 7:
        return
    mes_str = str(mes)[:7]
    gastos_fijos = db.query(models.GastoFijo).filter(models.GastoFijo.activo == True).all()
    if not gastos_fijos:
        return

    egresos_existentes = db.query(models.Egreso).filter(
        models.Egreso.mes == mes_str,
        models.Egreso.gasto_fijo_id.isnot(None)
    ).all()
    gf_registrados_ids = {eg.gasto_fijo_id for eg in egresos_existentes}

    modificado = False
    for gf in gastos_fijos:
        if gf.id not in gf_registrados_ids:
            nuevo_eg = models.Egreso(
                descripcion=gf.descripcion,
                categoria=gf.categoria or "operacional",
                subcategoria="Gasto Fijo",
                monto=gf.monto or 0.0,
                fecha=f"{mes_str}-01",
                mes=mes_str,
                metodo_pago=gf.metodo_pago or "Efectivo",
                estado="Pendiente",
                gasto_fijo_id=gf.id,
                notas=gf.notas
            )
            db.add(nuevo_eg)
            modificado = True

    if modificado:
        db.commit()
