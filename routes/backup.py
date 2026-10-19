# pyrefly: ignore [missing-import]
"""
@file backup.py
@author David Mogrovejo dmogrovejo87@gmail.com
@copyright (c) 2026 David Mogrovejo. All Rights Reserved.
@notice Sistema de Respaldo y Restauración Integral de Base de Datos (.sql) para Opsatel.
"""
import io
import os
import json
import datetime
from decimal import Decimal
from typing import Generator
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.orm import Session
from database import engine, get_db
import logging

logger = logging.getLogger("backup")
router = APIRouter(prefix="/backup", tags=["backup"])

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
                    upper_stmt = clean.upper()
                    if "CREATE TABLE" in upper_stmt or "DROP TABLE" in upper_stmt or "INSERT INTO" in upper_stmt:
                        words = clean.replace("`", "").replace('"', '').split()
                        for idx, w in enumerate(words):
                            if w.upper() in ("TABLE", "INTO") and idx + 1 < len(words):
                                raw_tbl = words[idx + 1].split("(")[0].strip()
                                if raw_tbl:
                                    tables_affected.add(raw_tbl)
                                break
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
