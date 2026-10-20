# pyrefly: ignore [missing-import]
"""
@file backup.py
@author David Mogrovejo dmogrovejo87@gmail.com
@copyright (c) 2026 David Mogrovejo. All Rights Reserved.
@notice Sistema de Respaldo y Restauración Integral de Base de Datos (.sql) para Opsatel.
"""
import io
import os
import re
import json
import gzip
import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from decimal import Decimal
from typing import Generator, Optional, List
import requests
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from sqlalchemy.orm import Session
from database import engine, get_db
from config_manager import get_config, save_config
import logging

logger = logging.getLogger("backup")
router = APIRouter(prefix="/backup", tags=["backup"])

BACKUP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backups"))
os.makedirs(BACKUP_DIR, exist_ok=True)

def format_sql_value(val) -> str:
    """Formatea valores de Python al estándar exacto de MySQL/SQL."""
    if val is None:
        return "NULL"
    elif isinstance(val, bool):
        return "1" if val else "0"
    elif isinstance(val, (int,)):
        return str(val)
    elif isinstance(val, float):
        return repr(val)
    elif isinstance(val, Decimal):
        return str(val)
    elif isinstance(val, bytes):
        return f"0x{val.hex()}"
    elif isinstance(val, (datetime.datetime, datetime.date, datetime.time)):
        return f"'{val}'"
    elif isinstance(val, (dict, list)):
        s = json.dumps(val, ensure_ascii=False)
        escaped = (
            s.replace('\\', '\\\\')
             .replace("'", "\\'")
             .replace('\0', '\\0')
             .replace('\n', '\\n')
             .replace('\r', '\\r')
        )
        return f"'{escaped}'"
    else:
        s = str(val)
        escaped = (
            s.replace('\\', '\\\\')
             .replace("'", "\\'")
             .replace('\0', '\\0')
             .replace('\n', '\\n')
             .replace('\r', '\\r')
        )
        return f"'{escaped}'"


def split_sql_statements(sql_text: str):
    """
    Parser sintáctico de SQL que separa sentencias por ';' sin romper cadenas de texto,
    bloques con comillas simples/dobles, backticks o comentarios multilinea.
    """
    statements = []
    current = []
    in_single_quote = False
    in_double_quote = False
    in_backtick = False
    in_line_comment = False
    in_block_comment = False

    i = 0
    n = len(sql_text)

    while i < n:
        c = sql_text[i]
        next_c = sql_text[i + 1] if i + 1 < n else ''

        # Comentarios de una sola línea (-- o #)
        if not in_single_quote and not in_double_quote and not in_backtick and not in_block_comment:
            if c == '-' and next_c == '-':
                in_line_comment = True
                i += 2
                continue
            elif c == '#':
                in_line_comment = True
                i += 1
                continue

        if in_line_comment:
            if c == '\n':
                in_line_comment = False
            i += 1
            continue

        # Comentarios de bloque (/* ... */)
        if not in_single_quote and not in_double_quote and not in_backtick and not in_line_comment:
            if c == '/' and next_c == '*':
                # Permitir que comentarios ejecutables de MySQL como /*!40000 ... */ se procesen si es deseado
                if i + 2 < n and sql_text[i + 2] == '!':
                    pass
                else:
                    in_block_comment = True
                    i += 2
                    continue

        if in_block_comment:
            if c == '*' and next_c == '/':
                in_block_comment = False
                i += 2
            else:
                i += 1
            continue

        # Detección de cadenas con comillas simples
        if c == "'" and not in_double_quote and not in_backtick:
            num_backslashes = 0
            k = i - 1
            while k >= 0 and sql_text[k] == '\\':
                num_backslashes += 1
                k -= 1
            if num_backslashes % 2 == 0:
                in_single_quote = not in_single_quote

        # Detección de cadenas con comillas dobles
        elif c == '"' and not in_single_quote and not in_backtick:
            num_backslashes = 0
            k = i - 1
            while k >= 0 and sql_text[k] == '\\':
                num_backslashes += 1
                k -= 1
            if num_backslashes % 2 == 0:
                in_double_quote = not in_double_quote

        # Identificadores entre backticks
        elif c == '`' and not in_single_quote and not in_double_quote:
            in_backtick = not in_backtick

        # Terminador de sentencia ';' fuera de comillas y comentarios
        if c == ';' and not in_single_quote and not in_double_quote and not in_backtick:
            stmt = "".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
            i += 1
            continue

        current.append(c)
        i += 1

    tail = "".join(current).strip()
    if tail:
        statements.append(tail)

    return statements


def stream_mysql_dump() -> Generator[str, None, None]:
    """Generador que produce el volcado SQL completo de la base de datos MySQL."""
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    yield f"""-- ============================================================================
-- OPSATEL ISP - RESPALDO COMPLETO DE BASE DE DATOS (.SQL)
-- Fecha y Hora de Generación: {now_str}
-- Autor / Sistema: David Mogrovejo - Opsatel Management System
-- ============================================================================

SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT;
SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS;
SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION;
SET NAMES utf8mb4;
SET @OLD_TIME_ZONE=@@TIME_ZONE;
SET TIME_ZONE='+00:00';
SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0;
SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0;
SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO';

"""

    raw_conn = engine.raw_connection()
    try:
        cursor = raw_conn.cursor()

        # 1. Obtener tablas base
        cursor.execute("SHOW FULL TABLES WHERE Table_type = 'BASE TABLE'")
        tables = [row[0] for row in cursor.fetchall()]

        for table in tables:
            yield f"--\n-- Estructura de tabla para `{table}`\n--\n\n"
            yield f"DROP TABLE IF EXISTS `{table}`;\n"

            cursor.execute(f"SHOW CREATE TABLE `{table}`")
            create_result = cursor.fetchone()
            if create_result and len(create_result) > 1:
                create_stmt = create_result[1]
                # Normalizar colaciones para máxima compatibilidad (MySQL 8 / MariaDB / MySQL 5.7)
                create_stmt = re.sub(r'utf8mb4_0900_[a-z0-9_]+', 'utf8mb4_unicode_ci', create_stmt, flags=re.IGNORECASE)
                yield f"{create_stmt};\n\n"

            # 2. Volcado de datos de la tabla
            cursor.execute(f"SELECT * FROM `{table}`")
            columns = [desc[0] for desc in cursor.description]
            cols_escaped = ", ".join([f"`{c}`" for c in columns])

            has_data = False
            first_batch = True

            while True:
                rows = cursor.fetchmany(100)
                if not rows:
                    break

                if first_batch:
                    yield f"--\n-- Volcado de datos para la tabla `{table}`\n--\n\n"
                    yield f"LOCK TABLES `{table}` WRITE;\n"
                    yield f"/*!40000 ALTER TABLE `{table}` DISABLE KEYS */;\n"
                    first_batch = False
                    has_data = True

                vals_list = []
                for r in rows:
                    row_vals = ", ".join([format_sql_value(v) for v in r])
                    vals_list.append(f"({row_vals})")

                yield f"INSERT INTO `{table}` ({cols_escaped}) VALUES\n" + ",\n".join(vals_list) + ";\n"

            if has_data:
                yield f"/*!40000 ALTER TABLE `{table}` ENABLE KEYS */;\n"
                yield f"UNLOCK TABLES;\n\n"
            else:
                yield f"-- (La tabla `{table}` no contiene registros)\n\n"

        # 3. Vistas (si existen)
        try:
            cursor.execute("SHOW FULL TABLES WHERE Table_type = 'VIEW'")
            views = [row[0] for row in cursor.fetchall()]
            for view in views:
                yield f"--\n-- Estructura para la vista `{view}`\n--\n\n"
                yield f"DROP VIEW IF EXISTS `{view}`;\n"
                cursor.execute(f"SHOW CREATE VIEW `{view}`")
                create_view_res = cursor.fetchone()
                if create_view_res and len(create_view_res) > 1:
                    yield f"{create_view_res[1]};\n\n"
        except Exception as view_err:
            logger.warning(f"Aviso al exportar vistas: {view_err}")

        # Restaurar variables de sesión
        yield f"""--
-- Restauración de configuraciones del servidor
--
SET TIME_ZONE=@OLD_TIME_ZONE;
SET SQL_MODE=@OLD_SQL_MODE;
SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS;
SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS;
SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT;
SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS;
SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION;

-- ============================================================================
-- FIN DEL RESPALDO ({datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
-- ============================================================================
"""
    finally:
        try:
            cursor.close()
            raw_conn.close()
        except Exception:
            pass


def stream_sqlite_dump() -> Generator[str, None, None]:
    """Generador de respaldo para dialecto SQLite (pruebas / fallback)."""
    raw_conn = engine.raw_connection()
    try:
        for line in raw_conn.iterdump():
            yield f"{line}\n"
    finally:
        try:
            raw_conn.close()
        except Exception:
            pass


@router.get("/export-sql")
def exportar_backup_sql():
    """
    Genera y descarga en tiempo real un archivo .sql con el volcado completo e íntegro
    de toda la base de datos (estructura de tablas, índices, llaves y datos exactos).
    """
    try:
        now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"backup_opsatel_{now_str}.sql"

        if engine.dialect.name == "sqlite":
            generator = stream_sqlite_dump()
        else:
            generator = stream_mysql_dump()

        return StreamingResponse(
            generator,
            media_type="application/sql",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "Cache-Control": "no-cache",
                "X-Opsatel-Backup": "Full-Database-SQL"
            }
        )
    except Exception as e:
        logger.error(f"Error generando backup SQL: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al generar el respaldo SQL: {str(e)}"
        )


@router.post("/import-sql")
async def importar_backup_sql(file: UploadFile = File(...)):
    """
    Restaura la base de datos a partir de un archivo .sql completo.
    Deshabilita temporalmente verificaciones de claves foráneas para recrear exactamente
    todas las tablas y registros sin pérdidas ni errores de integridad.
    """
    if not file.filename.lower().endswith(".sql"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo proporcionado debe ser un archivo de respaldo SQL con extensión .sql"
        )

    try:
        content_bytes = await file.read()
        # Intentar decodificar con utf-8, con fallback a latin-1 para compatibilidad total
        try:
            sql_text = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            sql_text = content_bytes.decode("latin-1")

        # Normalizar colaciones de MySQL 8.0 incompatibles con MariaDB / MySQL 5.7
        sql_text = re.sub(r'utf8mb4_0900_[a-z0-9_]+', 'utf8mb4_unicode_ci', sql_text, flags=re.IGNORECASE)

        statements = split_sql_statements(sql_text)
        if not statements:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El archivo .sql no contiene sentencias SQL válidas para ejecutar."
            )

        raw_conn = engine.raw_connection()
        executed_count = 0
        tables_affected = set()

        try:
            cursor = raw_conn.cursor()

            # Deshabilitar chequeos de claves foráneas y comprobaciones únicas
            if engine.dialect.name != "sqlite":
                cursor.execute("SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0;")
                cursor.execute("SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0;")
                cursor.execute("SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO';")

            for stmt in statements:
                clean = stmt.strip()
                if not clean:
                    continue

                # Omitir comentarios puros si los hubiera
                if clean.startswith("--") or clean.startswith("#"):
                    continue

                try:
                    cursor.execute(clean)
                    executed_count += 1

                    # Extraer nombre de tabla para estadísticas
                    match = re.search(r'(?:CREATE\s+TABLE|DROP\s+TABLE(?:\s+IF\s+EXISTS)?|INSERT\s+INTO|ALTER\s+TABLE)\s+[`"]?([a-zA-Z0-9_]+)[`"]?', clean, flags=re.IGNORECASE)
                    if match:
                        tables_affected.add(match.group(1))
                except Exception as stmt_err:
                    logger.warning(f"Aviso ejecutando sentencia [{clean[:60]}...]: {stmt_err}")
                    # Continuar con la siguiente sentencia para no abortar si es un setting no compatible

            # Restaurar chequeos de claves foráneas
            if engine.dialect.name != "sqlite":
                cursor.execute("SET FOREIGN_KEY_CHECKS=IFNULL(@OLD_FOREIGN_KEY_CHECKS, 1);")
                cursor.execute("SET UNIQUE_CHECKS=IFNULL(@OLD_UNIQUE_CHECKS, 1);")
                cursor.execute("SET SQL_MODE=IFNULL(@OLD_SQL_MODE, '');")

            raw_conn.commit()

        finally:
            try:
                cursor.close()
                raw_conn.close()
            except Exception:
                pass

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "success": True,
                "message": f"Base de datos restaurada exitosamente desde '{file.filename}'.",
                "total_sentencias": executed_count,
                "tablas_afectadas": len(tables_affected),
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error restaurando base de datos: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error durante la restauración de la base de datos: {str(e)}"
        )


@router.get("/info")
def info_base_datos():
    """Retorna información general de la base de datos conectada y conteo de tablas."""
    try:
        dialect = engine.dialect.name
        raw_conn = engine.raw_connection()
        tables = []
        try:
            cursor = raw_conn.cursor()
            if dialect == "sqlite":
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            else:
                cursor.execute("SHOW FULL TABLES WHERE Table_type = 'BASE TABLE';")
            tables = [row[0] for row in cursor.fetchall()]
        finally:
            try:
                cursor.close()
                raw_conn.close()
            except Exception:
                pass

        return {
            "motor": dialect,
            "total_tablas": len(tables),
            "tablas": tables
        }
    except Exception as e:
        return {"error": str(e)}


# ============================================================================
# SISTEMA DE RESPALDOS AUTOMÁTICOS PROGRAMADOS (OPSATEL ISP)
# ============================================================================

class AutoBackupConfigRequest(BaseModel):
    enabled: bool
    frecuencia: str = "cada_dia"  # "cada_hora", "cada_dia", "cada_semana", "cada_mes"
    hora: str = "02:00"
    dia_semana: Optional[int] = 6  # 0=Lunes ... 6=Domingo
    dia_mes: Optional[int] = 1     # 1..31
    retencion_dias: int = 30
    telegram_enabled: bool = False
    telegram_bot_token: Optional[str] = ""
    telegram_chat_id: Optional[str] = ""
    email_enabled: bool = False
    smtp_host: Optional[str] = "smtp.gmail.com"
    smtp_port: Optional[int] = 587
    smtp_user: Optional[str] = ""
    smtp_password: Optional[str] = ""
    email_destinatario: Optional[str] = ""



class TestNotificationRequest(BaseModel):
    tipo: str  # "telegram" o "email"
    telegram_bot_token: Optional[str] = ""
    telegram_chat_id: Optional[str] = ""
    smtp_host: Optional[str] = "smtp.gmail.com"
    smtp_port: Optional[int] = 587
    smtp_user: Optional[str] = ""
    smtp_password: Optional[str] = ""
    email_destinatario: Optional[str] = ""


def enviar_alerta_telegram(bot_token: str, chat_id: str, mensaje: str, filepath: str = None) -> dict:
    """Envía un mensaje de texto y opcionalmente el archivo .sql por Telegram Bot API."""
    if not bot_token or not chat_id:
        return {"ok": False, "error": "Token de Telegram o Chat ID no configurados"}
    
    url_msg = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        resp = requests.post(url_msg, json={
            "chat_id": chat_id,
            "text": mensaje,
            "parse_mode": "Markdown"
        }, timeout=15)
        
        doc_sent = False
        doc_error = None
        
        # Enviar archivo .sql si existe
        if filepath and os.path.exists(filepath):
            url_doc = f"https://api.telegram.org/bot{bot_token}/sendDocument"
            filename = os.path.basename(filepath)
            filesize = os.path.getsize(filepath)
            
            # Límite oficial de Telegram Bot API es 50MB (usamos 45MB como margen de seguridad)
            if filesize <= 45 * 1024 * 1024:
                try:
                    with open(filepath, "rb") as f_doc:
                        resp_doc = requests.post(
                            url_doc,
                            data={"chat_id": chat_id, "caption": f"🗄️ Copia de Respaldo Base de Datos: {filename}"},
                            files={"document": (filename, f_doc, "application/sql")},
                            timeout=120
                        )
                        if resp_doc.status_code == 200:
                            doc_sent = True
                        else:
                            doc_error = resp_doc.text
                except Exception as ex_doc:
                    doc_error = str(ex_doc)
            else:
                doc_error = "El archivo supera los 45MB para envío directo por Telegram."
        
        return {
            "ok": resp.status_code == 200,
            "doc_sent": doc_sent,
            "doc_error": doc_error,
            "status_code": resp.status_code
        }
    except Exception as e:
        logger.error(f"[Telegram Backup] Error: {e}")
        return {"ok": False, "error": str(e)}


def enviar_alerta_email(smtp_host: str, smtp_port: int, smtp_user: str, smtp_pass: str, email_to: str, asunto: str, cuerpo: str, filepath: str = None) -> dict:
    """Envía un correo SMTP con el resumen y opcionalmente el archivo de respaldo adjunto."""
    if not smtp_host or not smtp_user or not email_to:
        return {"ok": False, "error": "Faltan datos de configuración SMTP (servidor, usuario o destinatario)"}
    
    try:
        msg = MIMEMultipart()
        msg["From"] = smtp_user
        msg["To"] = email_to
        msg["Subject"] = asunto
        
        msg.attach(MIMEText(cuerpo, "plain", "utf-8"))
        
        # Adjuntar archivo si existe
        if filepath and os.path.exists(filepath):
            filesize = os.path.getsize(filepath)
            filename = os.path.basename(filepath)
            
            # Si pesa entre 3MB y 40MB, comprimirlo con gzip para que el email sea ligero
            if filesize > 3 * 1024 * 1024 and filesize <= 40 * 1024 * 1024:
                try:
                    with open(filepath, "rb") as f_in:
                        gz_data = gzip.compress(f_in.read(), compresslevel=6)
                    part = MIMEBase("application", "gzip")
                    part.set_payload(gz_data)
                    encoders.encode_base64(part)
                    part.add_header("Content-Disposition", f'attachment; filename="{filename}.gz"')
                    msg.attach(part)
                except Exception as gz_err:
                    logger.warning(f"No se pudo comprimir en gzip para adjuntar: {gz_err}")
            elif filesize <= 25 * 1024 * 1024:
                with open(filepath, "rb") as f_in:
                    part = MIMEBase("application", "sql")
                    part.set_payload(f_in.read())
                    encoders.encode_base64(part)
                    part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
                    msg.attach(part)
        
        port = int(smtp_port or 587)
        if port == 465:
            server = smtplib.SMTP_SSL(smtp_host, port, timeout=30)
        else:
            server = smtplib.SMTP(smtp_host, port, timeout=30)
            server.starttls()
        
        if smtp_pass:
            server.login(smtp_user, smtp_pass)
            
        server.sendmail(smtp_user, [email_to], msg.as_string())
        server.quit()
        return {"ok": True}
    except Exception as e:
        logger.error(f"[Email Backup] Error: {e}")
        return {"ok": False, "error": str(e)}


def limpiar_respaldos_antiguos(dias_retencion: int = 30, max_archivos: int = 30) -> int:
    """
    Elimina archivos de respaldo antiguos para evitar saturar el almacenamiento en disco.
    """
    if not os.path.exists(BACKUP_DIR):
        return 0
    
    ahora = datetime.datetime.now()
    limite = ahora - datetime.timedelta(days=dias_retencion)
    
    archivos = []
    for f in os.listdir(BACKUP_DIR):
        if f.endswith(".sql") or f.endswith(".sql.gz"):
            p = os.path.join(BACKUP_DIR, f)
            if os.path.isfile(p):
                mtime = datetime.datetime.fromtimestamp(os.path.getmtime(p))
                archivos.append((p, mtime))
                
    # Ordenar de más reciente a más antiguo
    archivos.sort(key=lambda x: x[1], reverse=True)
    
    eliminados = 0
    for idx, (p, mtime) in enumerate(archivos):
        # Eliminar si superó los días de retención (manteniendo al menos el más reciente)
        # o si la cantidad de respaldos supera el máximo permitido
        if (mtime < limite and idx >= 1) or idx >= max_archivos:
            try:
                os.remove(p)
                eliminados += 1
                logger.info(f"[BACKUP] Eliminado respaldo antiguo por rotación: {os.path.basename(p)}")
            except Exception as e:
                logger.warning(f"Error borrando archivo de respaldo antiguo {p}: {e}")
                
    return eliminados


def ejecutar_proceso_backup_automatico(motivo: str = "programado") -> dict:
    """
    Genera el archivo .sql en disco, aplica política de rotación y envía notificaciones configuradas.
    """
    now = datetime.datetime.now()
    stamp = now.strftime("%Y%m%d_%H%M%S")
    filename = f"backup_opsatel_{stamp}.sql"
    filepath = os.path.join(BACKUP_DIR, filename)
    
    cfg = get_config()
    retencion = int(cfg.get("backup_auto_retencion_dias", 30))
    
    try:
        # 1. Generar y escribir el volcado SQL directamente a disco
        if engine.dialect.name == "sqlite":
            generator = stream_sqlite_dump()
        else:
            generator = stream_mysql_dump()
            
        with open(filepath, "w", encoding="utf-8") as f_out:
            for chunk in generator:
                f_out.write(chunk)
                
        size_bytes = os.path.getsize(filepath)
        size_mb = round(size_bytes / (1024 * 1024), 2)
        
        # 2. Aplicar rotación y limpieza de respaldos viejos
        archivos_depurados = limpiar_respaldos_antiguos(dias_retencion=retencion, max_archivos=retencion)
        
        # 3. Notificación por Telegram (si está habilitado)
        telegram_status = {"activo": False}
        if cfg.get("backup_telegram_enabled", False):
            token = cfg.get("backup_telegram_bot_token", "").strip()
            chat_id = cfg.get("backup_telegram_chat_id", "").strip()
            if token and chat_id:
                texto_tg = (
                    f"🛡️ *OPSATEL ISP - RESPALDO AUTOMÁTICO*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"✅ *Estado:* Generado exitosamente\n"
                    f"📁 *Archivo:* `{filename}`\n"
                    f"📦 *Tamaño:* `{size_mb} MB`\n"
                    f"🕒 *Fecha:* `{now.strftime('%Y-%m-%d %H:%M:%S')}`\n"
                    f"🏷️ *Motivo:* `{motivo.capitalize()}`\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━"
                )
                res_tg = enviar_alerta_telegram(token, chat_id, texto_tg, filepath)
                telegram_status = {"activo": True, "resultado": res_tg}
                
        # 4. Notificación por Correo Electrónico (si está habilitado)
        email_status = {"activo": False}
        if cfg.get("backup_email_enabled", False):
            host = cfg.get("backup_smtp_host", "").strip()
            port = int(cfg.get("backup_smtp_port", 587))
            user = cfg.get("backup_smtp_user", "").strip()
            pwd = cfg.get("backup_smtp_password", "").strip()
            dest = cfg.get("backup_email_destinatario", "").strip()
            if host and user and dest:
                asunto = f"[OPSATEL ISP] Respaldo de Base de Datos - {now.strftime('%Y-%m-%d %H:%M')}"
                cuerpo = (
                    f"Respaldo automático de la base de datos de Opsatel ISP generado exitosamente.\n\n"
                    f"Detalles:\n"
                    f"- Archivo: {filename}\n"
                    f"- Tamaño: {size_mb} MB\n"
                    f"- Fecha: {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"- Motivo: {motivo}\n"
                    f"- Retención configurada: {retencion} días\n\n"
                    f"El archivo se encuentra resguardado en el servidor y adjunto en este mensaje (si aplica)."
                )
                res_mail = enviar_alerta_email(host, port, user, pwd, dest, asunto, cuerpo, filepath)
                email_status = {"activo": True, "resultado": res_mail}
                
        # 5. Guardar registro en configuración
        registro_respaldo = {
            "fecha": now.strftime("%Y-%m-%d %H:%M:%S"),
            "archivo": filename,
            "tamano_mb": size_mb,
            "estado": "exitoso",
            "motivo": motivo
        }
        save_config({"ultimo_respaldo_automatico": registro_respaldo})
        
        return {
            "success": True,
            "mensaje": f"Respaldo '{filename}' ({size_mb} MB) generado exitosamente en el servidor.",
            "archivo": filename,
            "tamano_mb": size_mb,
            "fecha": now.strftime("%Y-%m-%d %H:%M:%S"),
            "archivos_depurados": archivos_depurados,
            "telegram": telegram_status,
            "email": email_status
        }
        
    except Exception as e:
        logger.error(f"Error generando respaldo automático: {e}")
        error_registro = {
            "fecha": now.strftime("%Y-%m-%d %H:%M:%S"),
            "archivo": filename,
            "estado": "error",
            "error": str(e),
            "motivo": motivo
        }
        save_config({"ultimo_respaldo_automatico": error_registro})
        raise e


@router.get("/config")
def get_auto_backup_config():
    """Obtiene la configuración actual de respaldos automáticos programados."""
    cfg = get_config()
    return {
        "enabled": bool(cfg.get("backup_auto_enabled", True)),
        "frecuencia": str(cfg.get("backup_auto_frecuencia", "cada_dia")),
        "hora": str(cfg.get("backup_auto_hora", "02:00")),
        "dia_semana": int(cfg.get("backup_auto_dia_semana", 6)),
        "dia_mes": int(cfg.get("backup_auto_dia_mes", 1)),
        "retencion_dias": int(cfg.get("backup_auto_retencion_dias", 30)),
        "telegram_enabled": bool(cfg.get("backup_telegram_enabled", False)),
        "telegram_bot_token": str(cfg.get("backup_telegram_bot_token", "")),
        "telegram_chat_id": str(cfg.get("backup_telegram_chat_id", "")),
        "email_enabled": bool(cfg.get("backup_email_enabled", False)),
        "smtp_host": str(cfg.get("backup_smtp_host", "smtp.gmail.com")),
        "smtp_port": int(cfg.get("backup_smtp_port", 587)),
        "smtp_user": str(cfg.get("backup_smtp_user", "")),
        "smtp_password": str(cfg.get("backup_smtp_password", "")),
        "email_destinatario": str(cfg.get("backup_email_destinatario", "")),
        "ultimo_respaldo": cfg.get("ultimo_respaldo_automatico")
    }


@router.put("/config")
def update_auto_backup_config(data: AutoBackupConfigRequest):
    """Actualiza la configuración de respaldos automáticos y reprograma el scheduler."""
    import re
    
    frecuencias_validas = ["cada_hora", "cada_dia", "cada_semana", "cada_mes"]
    frecuencia = data.frecuencia.lower() if data.frecuencia else "cada_dia"
    if frecuencia not in frecuencias_validas:
        raise HTTPException(status_code=400, detail="Frecuencia inválida. Opciones: cada_hora, cada_dia, cada_semana, cada_mes")
        
    if frecuencia != "cada_hora":
        if not re.match(r"^\d{2}:\d{2}$", data.hora):
            raise HTTPException(status_code=400, detail="El formato de hora debe ser HH:MM (ej. 02:00)")
        
    if data.retencion_dias < 1 or data.retencion_dias > 365:
        raise HTTPException(status_code=400, detail="Los días de retención deben ser entre 1 y 365 días")
        
    email_dest = (data.email_destinatario or "").strip()
    # Si ingresa un correo de destino, habilitar email_enabled
    email_enabled = data.email_enabled
    if email_dest and not data.email_enabled:
        email_enabled = True

    save_config({
        "backup_auto_enabled": data.enabled,
        "backup_auto_frecuencia": frecuencia,
        "backup_auto_hora": data.hora,
        "backup_auto_dia_semana": data.dia_semana if data.dia_semana is not None else 6,
        "backup_auto_dia_mes": data.dia_mes if data.dia_mes is not None else 1,
        "backup_auto_retencion_dias": data.retencion_dias,
        "backup_telegram_enabled": data.telegram_enabled,
        "backup_telegram_bot_token": (data.telegram_bot_token or "").strip(),
        "backup_telegram_chat_id": (data.telegram_chat_id or "").strip(),
        "backup_email_enabled": email_enabled,
        "backup_smtp_host": (data.smtp_host or "smtp.gmail.com").strip(),
        "backup_smtp_port": data.smtp_port or 587,
        "backup_smtp_user": (data.smtp_user or "").strip(),
        "backup_smtp_password": (data.smtp_password or "").strip(),
        "backup_email_destinatario": email_dest
    })
    
    try:
        from scheduler import reprogramar_job_backup
        reprogramar_job_backup()
    except Exception as e:
        logger.warning(f"Aviso reprogramando scheduler de backup: {e}")
        
    return {"success": True, "message": "Configuración de respaldos automáticos guardada exitosamente."}



@router.get("/archivos")
def listar_archivos_backup():
    """Lista todos los respaldos generados y almacenados en la carpeta local del servidor."""
    if not os.path.exists(BACKUP_DIR):
        return []
        
    archivos = []
    for f in os.listdir(BACKUP_DIR):
        if f.endswith(".sql") or f.endswith(".sql.gz"):
            p = os.path.join(BACKUP_DIR, f)
            if os.path.isfile(p):
                stat = os.stat(p)
                mtime = datetime.datetime.fromtimestamp(stat.st_mtime)
                size_mb = round(stat.st_size / (1024 * 1024), 2)
                archivos.append({
                    "nombre": f,
                    "tamano_mb": size_mb,
                    "tamano_bytes": stat.st_size,
                    "fecha": mtime.strftime("%Y-%m-%d %H:%M:%S"),
                    "mtime_timestamp": stat.st_mtime
                })
                
    archivos.sort(key=lambda x: x["mtime_timestamp"], reverse=True)
    return archivos


@router.get("/descargar/{filename}")
def descargar_archivo_backup(filename: str):
    """Descarga al navegador un archivo de respaldo específico almacenado en el servidor."""
    clean_name = os.path.basename(filename)
    if not (clean_name.endswith(".sql") or clean_name.endswith(".sql.gz")):
        raise HTTPException(status_code=400, detail="Nombre de archivo inválido")
        
    filepath = os.path.join(BACKUP_DIR, clean_name)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="El archivo de respaldo solicitado no existe en el servidor.")
        
    media_type = "application/gzip" if clean_name.endswith(".gz") else "application/sql"
    return FileResponse(
        filepath,
        filename=clean_name,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={clean_name}"}
    )


@router.delete("/archivo/{filename}")
def eliminar_archivo_backup(filename: str):
    """Elimina permanentemente un archivo de respaldo del servidor."""
    clean_name = os.path.basename(filename)
    if not (clean_name.endswith(".sql") or clean_name.endswith(".sql.gz")):
        raise HTTPException(status_code=400, detail="Nombre de archivo inválido")
        
    filepath = os.path.join(BACKUP_DIR, clean_name)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="El archivo no existe")
        
    try:
        os.remove(filepath)
        return {"success": True, "message": f"Archivo '{clean_name}' eliminado correctamente."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al eliminar el archivo: {str(e)}")


@router.post("/ejecutar-ahora")
def ejecutar_backup_ahora():
    """Ejecuta de inmediato el pipeline de respaldo automático en segundo plano / demanda."""
    try:
        resultado = ejecutar_proceso_backup_automatico(motivo="manual-inmediato")
        return resultado
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al ejecutar respaldo automático: {str(e)}")


@router.post("/probar-notificacion")
def probar_notificacion(data: TestNotificationRequest):
    """Prueba el canal de notificación (Telegram o Email) con un mensaje de prueba."""
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if data.tipo == "telegram":
        if not data.telegram_bot_token or not data.telegram_chat_id:
            raise HTTPException(status_code=400, detail="Debe ingresar Bot Token y Chat ID de Telegram")
        msg = (
            f"🔔 *PRUEBA DE NOTIFICACIÓN - OPSATEL ISP*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ La conexión con el bot de Telegram funciona correctamente.\n"
            f"🕒 Fecha de prueba: `{now_str}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        res = enviar_alerta_telegram(data.telegram_bot_token.strip(), data.telegram_chat_id.strip(), msg)
        if not res.get("ok"):
            raise HTTPException(status_code=400, detail=f"Error al conectar con Telegram: {res.get('error')}")
        return {"success": True, "message": "Mensaje de prueba enviado exitosamente a Telegram."}
        
    elif data.tipo == "email":
        if not data.smtp_host or not data.smtp_user or not data.email_destinatario:
            raise HTTPException(status_code=400, detail="Debe ingresar Servidor SMTP, Usuario y Destinatario")
        asunto = f"[OPSATEL ISP] Prueba de Configuración de Correo - {now_str}"
        cuerpo = (
            f"Este es un mensaje de prueba del sistema de respaldos automáticos de Opsatel ISP.\n\n"
            f"Si recibes este correo, tu configuración SMTP es correcta.\n"
            f"Fecha de prueba: {now_str}"
        )
        res = enviar_alerta_email(
            data.smtp_host.strip(),
            data.smtp_port or 587,
            data.smtp_user.strip(),
            data.smtp_password or "",
            data.email_destinatario.strip(),
            asunto,
            cuerpo
        )
        if not res.get("ok"):
            raise HTTPException(status_code=400, detail=f"Error al enviar correo SMTP: {res.get('error')}")
        return {"success": True, "message": "Correo de prueba enviado exitosamente."}
        
    else:
        raise HTTPException(status_code=400, detail="Tipo de notificación no válido ('telegram' o 'email')")

