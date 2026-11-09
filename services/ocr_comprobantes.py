"""
Servicio OCR Avanzado para Comprobantes de Pago de Opsatel.
Utiliza Tesseract OCR y Pillow para procesar automáticamente las fotos de transferencias y comprobantes,
apuntando al entorno virtual configurado en el servidor (/var/www/html/entornos/ia_env) con fallback al entorno actual.
Extrae:
- Banco emisor / origen
- Banco destino
- Monto monetario ($ USD)
- Destinatario / Beneficiario (A...)
- Ordenante / Remitente (De...)
- Cuenta destino
- Cuenta origen
- Número de comprobante / Referencia / Secuencial
- Fecha de la transacción
- Estado o tipo de transacción (Transferencia exitosa, etc.)
"""

import os
import sys
import json
import re
import logging
import subprocess
from typing import Dict, Any, Optional

logger = logging.getLogger("opsatel.ocr_comprobantes")

# Lista de intérpretes Python candidatos (priorizando el entorno virtual del servidor indicado por el usuario)
PYTHON_VENV_CANDIDATES = [
    "/var/www/html/entornos/ia_env/bin/python3",
    "/var/www/html/entornos/ia_env/bin/python",
    os.path.expanduser("~/entornos/ia_env/bin/python3"),
    os.path.expanduser("~/entornos/ia_env/bin/python")
]

# Lista de entidades financieras comunes en Ecuador
BANCOS_ECUADOR = [
    {"nombre": "Banco Pichincha", "patrones": [r"\bpichincha\b", r"bco\.?\s*pichincha"]},
    {"nombre": "DeUna", "patrones": [r"\bdeuna\b", r"\bde\s*una\b"]},
    {"nombre": "Banco Guayaquil", "patrones": [r"\bguayaquil\b", r"banco\s*del\s*barrio", r"bco\.?\s*guayaquil"]},
    {"nombre": "Peigo", "patrones": [r"\bpeigo\b"]},
    {"nombre": "Produbanco", "patrones": [r"\bprodubanco\b", r"\bpromerica\b", r"be\s*produbanco"]},
    {"nombre": "Banco del Pacífico", "patrones": [r"pac[ií]fico", r"bco\.?\s*pac[ií]fico"]},
    {"nombre": "Banco Bolivariano", "patrones": [r"bolivariano", r"veinti4"]},
    {"nombre": "Banco Internacional", "patrones": [r"banco\s*internacional", r"interbanco"]},
    {"nombre": "Banco del Austro", "patrones": [r"austro", r"bco\.?\s*austro"]},
    {"nombre": "Banco Solidario", "patrones": [r"solidario"]},
    {"nombre": "Banco de Machala", "patrones": [r"machala"]},
    {"nombre": "Cooperativa JEP", "patrones": [r"coop\.?\s*jep", r"\bjep\b", r"juventud\s*ecuatoriana"]},
    {"nombre": "Cooperativa Policía Nacional", "patrones": [r"polic[ií]a\s*nacional", r"\bcpn\b"]},
    {"nombre": "Cooperativa 29 de Octubre", "patrones": [r"29\s*de\s*octubre"]},
    {"nombre": "Cooperativa Alianza del Valle", "patrones": [r"alianza\s*del\s*valle"]},
    {"nombre": "Cooperativa Mushuc Runa", "patrones": [r"mushuc\s*runa"]},
    {"nombre": "Cooperativa CoopMego", "patrones": [r"coopmego", r"mego"]},
    {"nombre": "Cooperativa Oscus", "patrones": [r"oscus"]},
    {"nombre": "Cooperativa Andalucía", "patrones": [r"andaluc[ií]a"]},
    {"nombre": "Payphone", "patrones": [r"payphone"]}
]


def obtener_interprete_python() -> Optional[str]:
    """Retorna la ruta del intérprete en /var/www/html/entornos/ia_env si existe, o None."""
    for c in PYTHON_VENV_CANDIDATES:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def buscar_ruta_archivo(file_path_or_name: str) -> Optional[str]:
    """Busca la existencia real del archivo de imagen en múltiples rutas posibles."""
    if not file_path_or_name:
        return None

    clean_name = file_path_or_name.lstrip("/").replace("\\", "/")
    file_basename = os.path.basename(clean_name)

    candidatos = [
        file_path_or_name,
        clean_name,
        os.path.join("/app", clean_name),
        os.path.join("/app/uploadscr", file_basename),
        os.path.join(os.getcwd(), clean_name),
        os.path.join(os.getcwd(), "uploadscr", file_basename),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", clean_name)),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "uploadscr", file_basename)),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Opsatel-Frontend", "dist", "uploadscr", file_basename))
    ]

    for c in candidatos:
        if c and os.path.isfile(c) and os.path.getsize(c) > 0:
            return os.path.abspath(c)

    return None


def parsear_texto_comprobante(texto: str) -> Dict[str, Any]:
    """
    Analiza minuciosamente el texto extraído por Tesseract para extraer todos
    los campos posibles del comprobante (bancos, monto, beneficiario, ordenante, cuentas, referencia, fecha, etc.).
    """
    data: Dict[str, Any] = {
        "banco_origen": None,
        "banco_destino": None,
        "monto": None,
        "beneficiario": None,
        "ordenante": None,
        "cuenta_destino": None,
        "cuenta_origen": None,
        "numero_comprobante": None,
        "fecha": None,
        "estado_transaccion": None
    }

    if not texto:
        return data

    lineas = [l.strip() for l in texto.split("\n") if l.strip()]
    texto_lower = texto.lower()

    # 1. Banco emisor / origen (identificar por nombres de entidades ecuatorianas)
    for banco in BANCOS_ECUADOR:
        for patron in banco["patrones"]:
            if re.search(patron, texto_lower):
                data["banco_origen"] = banco["nombre"]
                break
        if data["banco_origen"]:
            break

    # 2. Banco destino (e.g. "Banco destino Banco Pichincha" o "Institución destino...")
    m_bd = re.search(r"(?:banco\s*destino|instituci[oó]n\s*destino|bco\.?\s*destino|entidad\s*destino)\s*[:.]?\s*([A-Za-z0-9\s]+?)(?=\n|cuenta|n\.|\$|ref|\Z)", texto, re.IGNORECASE)
    if m_bd:
        bd_raw = m_bd.group(1).strip()
        # Verificar si coincide con algún banco conocido
        for banco in BANCOS_ECUADOR:
            if re.search(banco["nombre"].lower(), bd_raw.lower()):
                data["banco_destino"] = banco["nombre"]
                break
        if not data["banco_destino"] and len(bd_raw) >= 4:
            data["banco_destino"] = bd_raw
    elif data["banco_origen"]:
        # Si no se especifica explícitamente otro banco destino, por defecto suele ser transferencia directa en la misma entidad
        data["banco_destino"] = data["banco_origen"]

    # 3. Monto monetario ($ USD)
    # Patrones con símbolo de dólar o etiqueta
    patrones_monto = [
        r"\$\s*(\d{1,5}[\.,]\d{2})\b",
        r"(?:monto|valor|total|importe|cantidad|usd)\s*[:.]?\s*(?:usd|\$)?\s*(\d{1,5}[\.,]\d{2})\b",
        r"(?:transferencia por|pagaste|enviaste|recibiste)\s*[:.]?\s*(?:usd|\$)?\s*(\d{1,5}[\.,]\d{2})\b"
    ]
    for p in patrones_monto:
        coincidencias = re.findall(p, texto, re.IGNORECASE)
        if coincidencias:
            for c in coincidencias:
                try:
                    val_float = float(c.replace(",", "."))
                    if 0.50 <= val_float <= 10000.00:
                        data["monto"] = val_float
                        break
                except ValueError:
                    continue
        if data["monto"] is not None:
            break

    # Fallback monto: cifras con decimales
    if data["monto"] is None:
        cifras = re.findall(r"\b(\d{1,4}[\.,]\d{2})\b", texto)
        for c in cifras:
            try:
                val_float = float(c.replace(",", "."))
                if 3.00 <= val_float <= 500.00:
                    data["monto"] = val_float
                    break
            except ValueError:
                continue

    # 4. Destinatario / Beneficiario (A: ...)
    m_ben = re.search(r"(?:^|\n)\s*(?:a|para|beneficiario|destinatario)\s*[:.]?\s*([A-Za-zÁÉÍÓÚáéíóúñÑ\s]{4,55}?)(?=\n|el\s+\d|\$|cuenta|banco|fecha|\Z)", texto, re.IGNORECASE)
    if m_ben:
        ben_str = m_ben.group(1).strip()
        if not re.match(r"^(cuenta|banco|fecha|transferencia|comprobante|monto|valor)", ben_str, re.IGNORECASE):
            data["beneficiario"] = ben_str

    # 5. Ordenante / Remitente (De: ...)
    m_ord = re.search(r"(?:^|\n)\s*(?:de|ordenante|remitente|debitado\s*de)\s*[:.]?\s*([A-Za-zÁÉÍÓÚáéíóúñÑ\s]{4,55}?)(?=\n|cuenta|banco|\$|fecha|comprobante|\Z)", texto, re.IGNORECASE)
    if m_ord:
        ord_str = m_ord.group(1).strip()
        if not re.match(r"^(cuenta|banco|comprobante|transferencia|fecha|monto|valor)", ord_str, re.IGNORECASE):
            data["ordenante"] = ord_str

    # 6. Cuenta destino (e.g. "*** *** 8858" o "2205849102")
    m_cd = re.search(r"(?:cuenta\s*destino|cta\.?\s*destino|destino)\s*[:.]?\s*([*0-9\s-]{4,25})", texto, re.IGNORECASE)
    if m_cd:
        data["cuenta_destino"] = m_cd.group(1).strip()

    # 7. Cuenta origen (e.g. "612 864 1400")
    m_co = re.search(r"(?:cuenta\s*origen|cta\.?\s*origen|origen|debitado\s*de\s*cuenta)\s*[:.]?\s*([*0-9\s-]{4,25})", texto, re.IGNORECASE)
    if m_co:
        data["cuenta_origen"] = m_co.group(1).strip()

    # 8. Número de comprobante / Referencia / Secuencial (e.g. "169609929")
    m_ref = re.search(r"(?:n\.?\s*de\s*comprobante|nro\.?\s*comprobante|no\.?\s*comprobante|comprobante|referencia|ref\.?|secuencial|transacci[oó]n|autorizaci[oó]n|control)\s*[:.]?\s*#?\s*([0-9A-Za-z-]{5,25})", texto, re.IGNORECASE)
    if m_ref:
        ref_val = m_ref.group(1).strip()
        if not re.match(r"^(cuenta|ahorros|corriente|fecha|banco|monto|valor)$", ref_val, re.IGNORECASE):
            data["numero_comprobante"] = ref_val

    # Si no hubo coincidencia con etiqueta, buscar secuencia numérica aislada típica de transacción bancaria
    if not data["numero_comprobante"]:
        numeros_largos = re.findall(r"\b(\d{6,14})\b", texto)
        for n in numeros_largos:
            if len(n) == 10 and int(n[:2]) <= 24:
                continue # Evitar confundir con cédula
            data["numero_comprobante"] = n
            break

    # 9. Fecha de la transacción (e.g. "El 09 de noviembre de 2026" o "09/11/2026")
    m_f_text = re.search(r"(?:el\s+)?(\d{1,2}\s+(?:de\s+)?(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre|ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)[a-z]*\s+(?:de\s+)?\d{2,4})", texto, re.IGNORECASE)
    if m_f_text:
        data["fecha"] = m_f_text.group(1).strip()
    else:
        m_f_num = re.search(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b", texto)
        if m_f_num:
            data["fecha"] = m_f_num.group(1).strip()

    # 10. Tipo de transacción / Estado
    m_est = re.search(r"(¡?transferencia\s*exitosa!?|transferencia\s*directa|transferencia\s*interbancaria|pago\s*exitoso|transacci[oó]n\s*exitosa)", texto, re.IGNORECASE)
    if m_est:
        data["estado_transaccion"] = m_est.group(1).replace("¡", "").replace("!", "").strip().capitalize()
    else:
        data["estado_transaccion"] = "Transferencia exitosa"

    return data


def ejecutar_tesseract_directo(image_path: str) -> str:
    """Ejecuta pytesseract directamente en el proceso actual."""
    try:
        import pytesseract
        from PIL import Image, ImageEnhance, ImageOps

        with Image.open(image_path) as img:
            gray = ImageOps.grayscale(img)
            enhancer = ImageEnhance.Contrast(gray)
            enhanced = enhancer.enhance(1.8)

            try:
                text = pytesseract.image_to_string(enhanced, lang="spa+eng", config="--psm 6")
            except Exception:
                try:
                    text = pytesseract.image_to_string(enhanced, lang="spa")
                except Exception:
                    text = pytesseract.image_to_string(enhanced)

            return text or ""
    except Exception as e:
        logger.warning(f"[OCR] Excepción en tesseract directo: {e}")
        return ""


def ejecutar_ocr_en_entorno_servidor(image_path: str, python_bin: str) -> str:
    """Invoca el intérprete en /var/www/html/entornos/ia_env para extraer texto con Tesseract."""
    try:
        codigo_inline = f"""
import sys
try:
    import pytesseract
    from PIL import Image, ImageEnhance, ImageOps

    with Image.open({json.dumps(image_path)}) as img:
        gray = ImageOps.grayscale(img)
        enhanced = ImageEnhance.Contrast(gray).enhance(1.8)
        try:
            txt = pytesseract.image_to_string(enhanced, lang='spa+eng', config='--psm 6')
        except Exception:
            try:
                txt = pytesseract.image_to_string(enhanced, lang='spa')
            except Exception:
                txt = pytesseract.image_to_string(enhanced)
        sys.stdout.write(txt or '')
except Exception as e:
    sys.stderr.write(str(e))
"""
        res = subprocess.run(
            [python_bin, "-c", codigo_inline],
            capture_output=True,
            text=True,
            timeout=30
        )
        if res.returncode == 0 and res.stdout:
            return res.stdout
        elif res.stderr:
            logger.warning(f"[OCR] Subproceso {python_bin} retornó stderr: {res.stderr}")
    except Exception as e_sub:
        logger.warning(f"[OCR] Error ejecutando subproceso en {python_bin}: {e_sub}")

    return ""


def analizar_comprobante_ocr(file_path_or_name: str) -> Dict[str, Any]:
    """
    Función principal de análisis OCR.
    1. Resuelve la ruta física del archivo.
    2. Apunta a /var/www/html/entornos/ia_env si existe, o al entorno local.
    3. Extrae y parsea todos los campos posibles del comprobante.
    """
    ruta_real = buscar_ruta_archivo(file_path_or_name)
    if not ruta_real:
        logger.warning(f"[OCR] No se encontró el archivo físico para '{file_path_or_name}'")
        return {
            "success": False,
            "error": "archivo_no_encontrado",
            "ruta_buscada": file_path_or_name
        }

    texto_extraido = ""

    # A. Prioridad 1: Si existe el entorno virtual del servidor en /var/www/html/entornos/ia_env
    ia_python = obtener_interprete_python()
    if ia_python:
        logger.info(f"[OCR] Utilizando intérprete de servidor: {ia_python}")
        texto_extraido = ejecutar_ocr_en_entorno_servidor(ruta_real, ia_python)

    # B. Prioridad 2 / Fallback: Ejecución directa en el proceso Python actual (Docker o host)
    if not texto_extraido:
        texto_extraido = ejecutar_tesseract_directo(ruta_real)

    if not texto_extraido or not texto_extraido.strip():
        logger.warning(f"[OCR] No se pudo extraer texto de '{os.path.basename(ruta_real)}'")
        return {
            "success": False,
            "error": "sin_texto_detectado",
            "ruta_archivo": ruta_real
        }

    # C. Parseo detallado de todos los datos del comprobante
    datos_extraidos = parsear_texto_comprobante(texto_extraido)

    # D. Construir resumen descriptivo
    partes = []
    if datos_extraidos.get("banco_origen"):
        partes.append(f"Banco: {datos_extraidos['banco_origen']}")
    if datos_extraidos.get("monto") is not None:
        partes.append(f"Monto: ${datos_extraidos['monto']:.2f}")
    if datos_extraidos.get("numero_comprobante"):
        partes.append(f"Ref: {datos_extraidos['numero_comprobante']}")
    if datos_extraidos.get("beneficiario"):
        partes.append(f"A: {datos_extraidos['beneficiario']}")
    if datos_extraidos.get("ordenante"):
        partes.append(f"De: {datos_extraidos['ordenante']}")
    if datos_extraidos.get("cuenta_destino"):
        partes.append(f"Cta: {datos_extraidos['cuenta_destino']}")
    if datos_extraidos.get("fecha"):
        partes.append(f"Fecha: {datos_extraidos['fecha']}")

    resumen_str = " | ".join(partes) if partes else "Texto extraído sin datos estructurados"

    logger.info(f"[OCR] ✅ Comprobante procesado exitosamente ({os.path.basename(ruta_real)}): {resumen_str}")

    return {
        "success": True,
        "banco_origen": datos_extraidos.get("banco_origen"),
        "banco_destino": datos_extraidos.get("banco_destino"),
        "monto": datos_extraidos.get("monto"),
        "beneficiario": datos_extraidos.get("beneficiario"),
        "ordenante": datos_extraidos.get("ordenante"),
        "cuenta_destino": datos_extraidos.get("cuenta_destino"),
        "cuenta_origen": datos_extraidos.get("cuenta_origen"),
        "numero_referencia": datos_extraidos.get("numero_comprobante"),
        "numero_comprobante": datos_extraidos.get("numero_comprobante"),
        "fecha": datos_extraidos.get("fecha"),
        "fecha_transaccion": datos_extraidos.get("fecha"),
        "estado_transaccion": datos_extraidos.get("estado_transaccion"),
        "resumen_ocr": f"[OCR] {resumen_str}",
        "texto_extraido": texto_extraido.strip(),
        "ruta_archivo": ruta_real
    }


# Ejecución standalone CLI:
# python services/ocr_comprobantes.py <ruta_imagen>
if __name__ == "__main__":
    if len(sys.argv) > 1:
        img_arg = sys.argv[1]
        res = analizar_comprobante_ocr(img_arg)
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        print("Uso: python ocr_comprobantes.py <ruta_imagen>")
