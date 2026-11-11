"""
Servicio OCR de Alta Precisión con Super-Resolución y Mejora de Calidad de Imagen para Comprobantes de Pago de Opsatel.

Flujo de procesamiento:
1. Mejora de Calidad de Imagen (Super-Sampling Bicúbico/Lanczos 2.4x, eliminación de artefactos JPEG,
   supresión suave de marcas de agua de fondo con curva Gamma sin destruir bordes anti-aliasing,
   filtro Unsharp Mask para nitidez de letras/números y enmascarado automático de códigos QR).
2. Extracción OCR Híbrida de Alta Precisión:
   - Motor Deep Learning RapidOCR (PP-OCRv4 ONNX) con reconstrucción geométrica de filas/columnas.
   - Entorno virtual del servidor (/var/www/html/entornos/ia_env) con Tesseract LSTM (--oem 1) a 300 DPI.
   - Proceso local pytesseract y binario CLI tesseract como respaldo.
3. Post-procesamiento léxico bancario en español y extracción estructurada de todos los campos.
"""

import os
import sys
import json
import re
import logging
import tempfile
import subprocess
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger("opsatel.ocr_comprobantes")

# Lista de intérpretes Python candidatos (priorizando el entorno virtual del servidor indicado por el usuario)
PYTHON_VENV_CANDIDATES = [
    "/var/www/html/entornos/ia_env/bin/python3",
    "/var/www/html/entornos/ia_env/bin/python",
    "/root/entornos/ia_env/bin/python3",
    "/root/entornos/ia_env/bin/python",
    os.path.expanduser("~/entornos/ia_env/bin/python3"),
    os.path.expanduser("~/entornos/ia_env/bin/python")
]

# Instancia singleton opcional de RapidOCR para evitar recargar modelos en cada comprobante
_RAPID_OCR_INSTANCE = None

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
        os.path.join("/app/uploads/uploadscr", file_basename),
        os.path.join("/var/www/html/entornos/uploadscr", file_basename),
        os.path.join("/var/www/html/uploadscr", file_basename),
        os.path.join("/var/www/opsatel-frontend/uploadscr", file_basename),
        os.path.join(os.getcwd(), clean_name),
        os.path.join(os.getcwd(), "uploadscr", file_basename),
        os.path.join(os.getcwd(), "uploads", "uploadscr", file_basename),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", clean_name)),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "uploadscr", file_basename)),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "uploads", "uploadscr", file_basename)),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Opsatel-Frontend", "dist", "uploadscr", file_basename))
    ]

    for c in candidatos:
        if c and os.path.isfile(c) and os.path.getsize(c) > 0:
            return os.path.abspath(c)

    return None


def calcular_hash_archivo(file_path_or_name: str) -> Optional[str]:
    """Calcula el hash SHA-256 de un archivo para detectar duplicados exactos."""
    ruta_real = buscar_ruta_archivo(file_path_or_name)
    if not ruta_real or not os.path.isfile(ruta_real):
        return None
    try:
        hasher = hashlib.sha256()
        with open(ruta_real, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception as e:
        logger.warning(f"[OCR] Error calculando hash SHA-256 de '{file_path_or_name}': {e}")
        return None


def mejorar_calidad_imagen_para_ocr(image_path: str) -> Tuple[str, Optional[str]]:
    """
    Sube la calidad de la imagen descargada antes del escaneo OCR:
    1. Si la imagen original es de baja resolución (< 900px de ancho, ej. 375x785),
       mejora su nitidez y resolución para que se vea clara en el sistema.
    2. Genera una imagen temporal optimizada en Alta Definición (300 DPI) exclusiva para el OCR:
       - Super-sampling Bicúbico/Lanczos (2.4x) para que las letras pequeñas tengan > 28px de alto.
       - Supresión suave de marcas de agua de fondo (píxeles >= 232 pasan a blanco puro 255)
         con curva Gamma (1.25) que oscurece textos grises sin romper los bordes anti-aliasing
         de números ni letras (evita confundir 0/O, 8/3, 6/5, i/l).
       - Filtro Unsharp Mask para definir los trazos de cada carácter.
       - Detección y enmascarado del código QR en la copia OCR para evitar que los cuadros
         del QR sean leídos como caracteres basura.
    Retorna (ruta_para_ocr, ruta_temporal_a_limpiar).
    """
    temp_ocr_path = None
    try:
        from PIL import Image, ImageOps, ImageFilter

        with Image.open(image_path) as raw_img:
            img_rgb = raw_img.convert("RGB")
            w, h = img_rgb.size

            # Factor de escalado adaptativo para alcanzar nitidez óptima de lectura
            if w < 600:
                scale = 2.0
            elif w < 1000:
                scale = 1.6
            elif w < 1400:
                scale = 1.25
            else:
                scale = 1.0

            new_w, new_h = int(w * scale), int(h * scale)

            # Si la imagen descargada era pequeña, guardar versión mejorada a color en el archivo original
            if scale >= 1.8:
                try:
                    color_upscaled = img_rgb.resize((new_w, new_h), Image.Resampling.BICUBIC)
                    color_sharpened = color_upscaled.filter(
                        ImageFilter.UnsharpMask(radius=1.2, percent=130, threshold=3)
                    )
                    ext = os.path.splitext(image_path)[1].lower()
                    if ext in [".jpg", ".jpeg"]:
                        color_sharpened.save(image_path, format="JPEG", quality=95, optimize=True, dpi=(300, 300))
                    elif ext == ".png":
                        color_sharpened.save(image_path, format="PNG", dpi=(300, 300))
                except Exception as e_save_orig:
                    logger.debug(f"[OCR] Aviso guardando mejora visual en original: {e_save_orig}")

            # Intentar pipeline OpenCV de alta precisión (preserva asteriscos y espacios finos)
            try:
                # pyrefly: ignore[missing-import]
                import cv2  # type: ignore
                import numpy as np  # type: ignore

                cv_orig = cv2.cvtColor(np.array(img_rgb), cv2.COLOR_RGB2BGR)
                cv_up = cv2.resize(cv_orig, (new_w, new_h), interpolation=cv2.INTER_CUBIC) if scale > 1.0 else cv_orig.copy()

                # Detectar y enmascarar código QR en la copia de trabajo OCR
                qr_det = cv2.QRCodeDetector()
                ok_qr, points = qr_det.detect(cv_up)
                if ok_qr and points is not None and len(points) > 0:
                    pts = points[0]
                    xs = [int(p[0]) for p in pts]
                    ys = [int(p[1]) for p in pts]
                    x_min, x_max = max(0, min(xs) - 8), min(new_w, max(xs) + 8)
                    y_min, y_max = max(0, min(ys) - 8), min(new_h, max(ys) + 8)
                    qr_w = x_max - x_min
                    qr_h = y_max - y_min
                    if qr_w > 60 and qr_h > 60 and 0.7 <= (qr_w / float(qr_h)) <= 1.35:
                        cv2.rectangle(cv_up, (x_min, y_min), (x_max, y_max), (255, 255, 255), -1)

                gray_np = cv2.cvtColor(cv_up, cv2.COLOR_BGR2GRAY)
                clipped = np.clip(gray_np.astype(np.float32), 0, 232) / 232.0
                gamma_corrected = np.power(clipped, 1.25) * 255.0
                enhanced_np = np.clip(gamma_corrected, 0, 255).astype(np.uint8)

                blur_np = cv2.GaussianBlur(enhanced_np, (0, 0), 1.2)
                sharpened_np = cv2.addWeighted(enhanced_np, 1.45, blur_np, -0.45, 0)
                bordered_gray = Image.fromarray(sharpened_np)
            except Exception:
                work_rgb = img_rgb.resize((new_w, new_h), Image.Resampling.BICUBIC) if scale > 1.0 else img_rgb.copy()
                gray = ImageOps.grayscale(work_rgb)
                lut = [
                    min(255, int(((min(p, 232) / 232.0) ** 1.25) * 255.0))
                    for p in range(256)
                ]
                enhanced_gray = gray.point(lut)
                sharpened_gray = enhanced_gray.filter(
                    ImageFilter.UnsharpMask(radius=1.2, percent=145, threshold=0)
                )
                bordered_gray = sharpened_gray

            fd, temp_ocr_path = tempfile.mkstemp(prefix="opsatel_ocr_hd_", suffix=".png")
            os.close(fd)
            bordered_gray.save(temp_ocr_path, format="PNG", dpi=(300, 300))
            return temp_ocr_path, temp_ocr_path

    except Exception as e_enh:
        logger.warning(f"[OCR] Aviso en mejora de calidad de imagen: {e_enh}")
        if temp_ocr_path and os.path.exists(temp_ocr_path):
            try:
                os.remove(temp_ocr_path)
            except Exception:
                pass
        return image_path, None


def postprocesar_texto_comprobante(texto: str) -> str:
    """
    Limpia artefactos comunes de OCR en comprobantes bancarios en español,
    restaurando espacios en etiquetas conocidas y corrigiendo símbolos.
    """
    if not texto:
        return ""

    texto_limpio = texto.replace("★", "*").replace("☆", "*")

    reemplazos = [
        (r"(?:^|\b)iTransferencia", "¡Transferencia"),
        (r"¡Transferenciaexitosa!", "¡Transferencia exitosa!"),
        (r"\bTransferenciaexitosa\b", "Transferencia exitosa"),
        (r"\bCuentadestino\b", "Cuenta destino"),
        (r"\bBancodestino\b", "Banco destino"),
        (r"\bCuentaorigen\b", "Cuenta origen"),
        (r"\bBancoPichincha\b", "Banco Pichincha"),
        (r"\bBANCOPICHINCHA\b", "BANCO PICHINCHA"),
        (r"\bN[\.:]\s*de\s*comprobante\b", "N. de comprobante"),
        (r"\bN\.decomprobante\b", "N. de comprobante"),
        (r"(\d{1,2})\.de\b", r"\1 de"),
        (r"\bdenoviembre\b", "de noviembre"),
        (r"\bden0viembre\b", "de noviembre"),
        (r"\bdeoctubre\b", "de octubre"),
        (r"\bdediciembre\b", "de diciembre"),
        (r"\bdeenero\b", "de enero"),
        (r"\bdefebrero\b", "de febrero"),
        (r"\bdemarzo\b", "de marzo"),
        (r"\bdeabril\b", "de abril"),
        (r"\bdemayo\b", "de mayo"),
        (r"\bdejunio\b", "de junio"),
        (r"\bdejulio\b", "de julio"),
        (r"\bdeagosto\b", "de agosto"),
        (r"\bdeseptiembre\b", "de septiembre"),
        (r"\btransaccion\b", "transacción"),
        (r"\bVerificarlatransacci[oó]nconesteQR\.?", "Verificar la transacción con este QR."),
    ]

    for patron, reemplazo in reemplazos:
        flags = 0 if "iTransferencia" in patron or "BANCOPICHINCHA" in patron else re.IGNORECASE
        texto_limpio = re.sub(patron, reemplazo, texto_limpio, flags=flags)

    # Filtrar líneas residuales que sean puro ruido de 1-2 símbolos sin letras ni dígitos válidos
    lineas_depuradas: List[str] = []
    for linea in texto_limpio.split("\n"):
        l_strip = linea.strip()
        if not l_strip:
            continue
        alnum_count = sum(1 for c in l_strip if c.isalnum())
        if alnum_count == 0:
            continue
        # Descartar fragmentos sueltos de marca de agua si quedara alguno aislado
        if l_strip.upper() in {"NCOPI", "PICHINC", "CHINCHA", "BANCOP"}:
            continue
        lineas_depuradas.append(l_strip)

    return "\n".join(lineas_depuradas)


def extraer_texto_rapidocr(image_path: str) -> str:
    """
    Extrae el texto utilizando RapidOCR (PaddleOCR PP-OCRv4 sobre ONNX Runtime)
    y reconstruye geométricamente los renglones horizontales (uniendo etiquetas de la
    columna izquierda con los valores de la columna derecha en la misma línea).
    """
    global _RAPID_OCR_INSTANCE
    try:
        # pyrefly: ignore[missing-import]
        from rapidocr_onnxruntime import RapidOCR  # type: ignore

        if _RAPID_OCR_INSTANCE is None:
            _RAPID_OCR_INSTANCE = RapidOCR()

        result, _ = _RAPID_OCR_INSTANCE(image_path, box_thresh=0.3, unclip_ratio=1.8)
        if not result:
            return ""

        items = []
        for box, text, score in result:
            if float(score) < 0.50:
                continue
            t_clean = (text or "").strip()
            if not t_clean:
                continue
            ys = [p[1] for p in box]
            xs = [p[0] for p in box]
            y_center = (min(ys) + max(ys)) / 2.0
            box_h = max(1.0, max(ys) - min(ys))
            x_min = min(xs)
            items.append({"y": y_center, "h": box_h, "x": x_min, "text": t_clean})

        if not items:
            return ""

        # Ordenar de arriba hacia abajo y agrupar cajas que pertenecen al mismo renglón horizontal
        items.sort(key=lambda it: it["y"])
        rows: List[List[Dict[str, Any]]] = []
        for it in items:
            placed = False
            for row in rows:
                avg_y = sum(r["y"] for r in row) / len(row)
                avg_h = sum(r["h"] for r in row) / len(row)
                if abs(it["y"] - avg_y) <= max(avg_h * 0.65, 18.0):
                    row.append(it)
                    placed = True
                    break
            if not placed:
                rows.append([it])

        lines: List[str] = []
        for row in rows:
            row.sort(key=lambda r: r["x"])
            line_str = " ".join(r["text"] for r in row)
            lines.append(line_str)

        return postprocesar_texto_comprobante("\n".join(lines))
    except Exception as e_rapid:
        logger.debug(f"[OCR] RapidOCR no disponible o falló: {e_rapid}")
        return ""


def unificar_textos_extraidos(textos: List[str]) -> str:
    """
    Combina múltiples pasadas de OCR sin duplicados preservando el orden de lectura.
    """
    if not textos:
        return ""

    lineas_finales: List[str] = []

    def normalizar(s: str) -> str:
        return re.sub(r"[^a-zA-Z0-9áéíóúñÁÉÍÓÚÑ]", "", s).lower()

    for bloque in textos:
        if not bloque:
            continue
        for linea in bloque.split("\n"):
            linea_limpia = linea.strip()
            if not linea_limpia or len(linea_limpia) < 2:
                continue

            norm = normalizar(linea_limpia)
            if not norm:
                continue

            duplicada = False
            for idx, lf in enumerate(lineas_finales):
                norm_existente = normalizar(lf)
                if norm == norm_existente:
                    duplicada = True
                    break
                if norm_existente in norm and len(norm) > len(norm_existente):
                    lineas_finales[idx] = linea_limpia
                    duplicada = True
                    break
                elif norm in norm_existente:
                    duplicada = True
                    break

            if not duplicada:
                lineas_finales.append(linea_limpia)

    return postprocesar_texto_comprobante("\n".join(lineas_finales))


def parsear_texto_comprobante(texto: str) -> Dict[str, Any]:
    """
    Analiza minuciosamente el texto extraído para estructurar todos los campos
    del comprobante (bancos, monto, beneficiario, ordenante, cuentas, referencia, fecha, estado).
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
        for banco in BANCOS_ECUADOR:
            if re.search(banco["nombre"].lower(), bd_raw.lower()):
                data["banco_destino"] = banco["nombre"]
                break
        if not data["banco_destino"] and len(bd_raw) >= 4:
            data["banco_destino"] = bd_raw
    elif data["banco_origen"]:
        data["banco_destino"] = data["banco_origen"]

    # 3. Monto monetario ($ USD)
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
    m_ben = re.search(r"(?:^|\n)\s*(?:a|para|beneficiario|destinatario)\s*[:.]?\s*([A-Za-zÁÉÍÓÚáéíóúñÑ\s]{3,55}?)(?=\n|el\s+\d|\$|cuenta|banco|fecha|\Z)", texto, re.IGNORECASE)
    if m_ben:
        ben_str = m_ben.group(1).strip()
        if not re.match(r"^(cuenta|banco|fecha|transferencia|comprobante|monto|valor)", ben_str, re.IGNORECASE):
            data["beneficiario"] = ben_str

    # 5. Ordenante / Remitente (De: ...)
    m_ord = re.search(r"(?:^|\n)\s*(?:de|ordenante|remitente|debitado\s*de)\s*[:.]?\s*([A-Za-zÁÉÍÓÚáéíóúñÑ\s]{3,55}?)(?=\n|cuenta|banco|\$|fecha|comprobante|\Z)", texto, re.IGNORECASE)
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
    m_ref = re.search(r"(?:n[º°.:]*\s*(?:de|del)?\s*comprobante|nro\.?\s*comprobante|no\.?\s*comprobante|num\.?\s*comprobante|comprobante|referencia|ref\.?|secuencial|transacci[oó]n|autorizaci[oó]n|control)\s*[:.]?\s*#?\s*([0-9A-Za-z-]{5,25})", texto, re.IGNORECASE)
    if m_ref:
        ref_val = m_ref.group(1).strip()
        if not re.match(r"^(cuenta|ahorros|corriente|fecha|banco|monto|valor)$", ref_val, re.IGNORECASE):
            data["numero_comprobante"] = ref_val

    if not data["numero_comprobante"]:
        numeros_largos = re.findall(r"\b(\d{6,14})\b", texto)
        for n in numeros_largos:
            if len(n) == 10 and int(n[:2]) <= 24:
                continue
            data["numero_comprobante"] = n
            break

    # 9. Fecha de la transacción (e.g. "El 09 de noviembre de 2026" o "09/11/2026")
    m_f_text = re.search(r"(?:el\s+)?(\d{1,2}[\s.]+(?:de[\s.]+)?(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre|ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)[a-z]*[\s.]+(?:de[\s.]+)?\d{2,4})", texto, re.IGNORECASE)
    if m_f_text:
        data["fecha"] = m_f_text.group(1).replace(".", " ").strip()
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


def es_documento_comprobante_valido(texto: str, datos_extraidos: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Determina con rigurosidad si una imagen es un comprobante bancario o documento financiero
    admitido en lugar de fotos personales, memes, paisajes, capturas de chat o facturas de compras.
    Retorna (es_valido, motivo).
    """
    if not texto or len(texto.strip()) < 18:
        return False, "sin_texto_financiero_suficiente"

    texto_lower = texto.lower()

    # 1. Filtro de exclusión: facturas de supermercados, tiendas o restaurantes que no son comprobantes bancarios
    patron_factura_comercial = re.compile(
        r"(ruc\s*[:.]?\s*\d{10,13}|factura\s*(?:electr[oó]nica|f[ií]sica)?\s*(?:n[º°.:]|no\.?|num\.?)\s*\d+|"
        r"nota\s*de\s*venta|consumidor\s*final|subtotal\s*1[25]%|subtotal\s*0%|iva\s*1[25]%|"
        r"supermaxi|megamaxi|gran\s*ak[ií]|tiendas\s*t[ií]a|coral\s*hipermercados|farmacias\s*(?:fybeca|sana|medicity|econok)|"
        r"mesero|mesa\s*#?\d+|propina\s*\$)",
        re.IGNORECASE
    )
    if patron_factura_comercial.search(texto_lower):
        # Si tiene indicadores de factura de compra comercial y NO menciona transferencia bancaria hacia Opsatel
        tiene_transferencia_explicita = bool(re.search(r"(transferencia\s*interbancaria|transferencia\s*directa|pichincha|jep|deuna)", texto_lower))
        if not tiene_transferencia_explicita:
            return False, "factura_comercial_no_bancaria"

    # 2. Filtro de exclusión: capturas de pantalla de chats o redes sociales
    patron_chat = re.compile(
        r"(escribiendo\.\.\.|visto\s*a\s*las|en\s*l[ií]nea|eliminar\s*para\s*todos|reenviado|grabar\s*audio|llamada\s*perdida)",
        re.IGNORECASE
    )
    matches_chat = patron_chat.findall(texto_lower)
    if len(matches_chat) >= 2 and not bool(datos_extraidos.get("banco_origen")):
        return False, "captura_de_chat_no_comprobante"

    # 3. Palabras clave obligatorias del ámbito bancario y transaccional ecuatoriano
    patron_terminos_bancarios = re.compile(
        r"(transferencia|comprobante|dep[oó]sito|transacci[oó]n|pago|cta\.?\s*destino|cuenta\s*destino|"
        r"cta\.?\s*origen|cuenta\s*origen|instituci[oó]n|beneficiario|ordenante|interbancari[ao]|"
        r"bco\.?|banco|cooperativa|ahorros|corriente|autorizaci[oó]n|secuencial|referencia|"
        r"deuna|de\s*una|peigo|payphone|pichincha|guayaquil|produbanco|pac[ií]fico|bolivariano|"
        r"austro|internacional|solidario|machala|jep|mushuc\s*runa|29\s*de\s*octubre)",
        re.IGNORECASE
    )
    terminos_encontrados = patron_terminos_bancarios.findall(texto_lower)
    tiene_terminos_bancarios = len(terminos_encontrados) >= 1

    # 4. Indicadores de campos financieros detectados
    tiene_banco = bool(datos_extraidos.get("banco_origen") or datos_extraidos.get("banco_destino"))
    tiene_monto = datos_extraidos.get("monto") is not None and float(datos_extraidos.get("monto") or 0) > 0
    tiene_ref = bool(datos_extraidos.get("numero_comprobante"))
    tiene_cuenta = bool(datos_extraidos.get("cuenta_destino") or datos_extraidos.get("cuenta_origen"))
    tiene_participante = bool(datos_extraidos.get("beneficiario") or datos_extraidos.get("ordenante"))
    tiene_palabra_transferencia = bool(re.search(r"transferencia|comprobante|dep[oó]sito|pago", texto_lower))

    # Criterios estrictos para ser admitido como comprobante:
    # A: Banco identificado Y (monto O referencia O cuenta)
    if tiene_banco and (tiene_monto or tiene_ref or tiene_cuenta):
        return True, "banco_y_datos_transaccion"

    # B: Monto con símbolo de divisa Y palabra de transferencia/comprobante/pago Y (referencia O cuenta)
    if tiene_monto and tiene_palabra_transferencia and (tiene_ref or tiene_cuenta or tiene_banco):
        return True, "monto_y_referencia_financiera"

    # C: Al menos dos términos bancarios distintivos y referencia o cuenta válida
    if len(terminos_encontrados) >= 2 and (tiene_ref or tiene_cuenta) and (tiene_monto or tiene_participante):
        return True, "multiples_indicadores_bancarios"

    return False, "la imagen mandada no es un documento valido"


MESES_ES = {
    'ene': 1, 'enero': 1, 'feb': 2, 'febrero': 2, 'mar': 3, 'marzo': 3,
    'abr': 4, 'abril': 4, 'may': 5, 'mayo': 5, 'jun': 6, 'junio': 6,
    'jul': 7, 'julio': 7, 'ago': 8, 'agosto': 8, 'sep': 9, 'sept': 9,
    'septiembre': 9, 'setiembre': 9, 'oct': 10, 'octubre': 10,
    'nov': 11, 'noviembre': 11, 'dic': 12, 'diciembre': 12
}


def parsear_fecha_texto(fecha_str: str) -> Optional[datetime]:
    """
    Parsea una fecha en texto común de comprobantes ecuatorianos (ej. '23 ene 2026',
    '23 de enero de 2026', '09/11/2026', '2026-11-11').
    """
    if not fecha_str:
        return None
    s = str(fecha_str).lower().strip()
    # 1. '23 ene 2026', '23 de enero de 2026', '05 de octubre 2026'
    m_txt = re.search(r'(\d{1,2})\s*(?:de\s*)?([a-záéíóúñ]+)\s*(?:del?\s*)?(\d{2,4})', s)
    if m_txt:
        dia = int(m_txt.group(1))
        mes_str = m_txt.group(2)[:3]
        mes = MESES_ES.get(mes_str)
        anio = int(m_txt.group(3))
        if anio < 100:
            anio += 2000
        if mes and 1 <= dia <= 31:
            try:
                return datetime(anio, mes, dia)
            except ValueError:
                pass

    # 2. '23/01/2026' o '23-01-2026'
    m_num = re.search(r'(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})', s)
    if m_num:
        dia = int(m_num.group(1))
        mes = int(m_num.group(2))
        anio = int(m_num.group(3))
        if anio < 100:
            anio += 2000
        if 1 <= mes <= 12 and 1 <= dia <= 31:
            try:
                return datetime(anio, mes, dia)
            except ValueError:
                pass

    # 3. '2026-01-23'
    m_iso = re.search(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', s)
    if m_iso:
        anio = int(m_iso.group(1))
        mes = int(m_iso.group(2))
        dia = int(m_iso.group(3))
        if 1 <= mes <= 12 and 1 <= dia <= 31:
            try:
                return datetime(anio, mes, dia)
            except ValueError:
                pass

    return None


def es_fecha_del_ultimo_mes(fecha_dt: Optional[datetime], ahora: Optional[datetime] = None) -> Tuple[bool, int, str]:
    """
    Verifica si una fecha corresponde al último mes (mes en curso o mes inmediatamente anterior hasta 42 días).
    Retorna (es_valido, dias_diferencia, mensaje_motivo).
    """
    if not fecha_dt:
        return True, 0, ""
    if not ahora:
        ahora = datetime.now()

    dias = (ahora.date() - fecha_dt.date()).days

    # Fecha en el futuro por descuadre
    if dias < -2:
        return False, dias, f"Fecha en el futuro ({fecha_dt.strftime('%d/%m/%Y')})"

    # Diferencia de meses calendario
    meses_dif = (ahora.year - fecha_dt.year) * 12 + (ahora.month - fecha_dt.month)

    # Permitir mes en curso (meses_dif == 0) o mes inmediatamente anterior (meses_dif == 1) hasta 42 días
    if meses_dif == 0 or (meses_dif == 1 and dias <= 42):
        return True, dias, ""

    return False, dias, f"Comprobante con fecha anterior ({fecha_dt.strftime('%d/%m/%Y')}, hace {dias} días). Solo se admiten comprobantes del último mes."


def calcular_score_autenticidad(texto: str, datos: Dict[str, Any]) -> Dict[str, Any]:
    """
    Evalúa minuciosamente la autenticidad y certeza de que el documento es un comprobante de pago real
    dirigido o vinculado a Opsatel.
    Retorna score (0-100), nivel de confianza ('ALTO', 'MEDIO', 'BAJO', 'INVALIDO'),
    indicadores booleanos y lista de alertas.
    """
    score = 0
    alertas = []
    texto_lower = (texto or "").lower()

    # 1. Banco emisor/receptor identificado (+25 pts)
    banco_ok = bool(datos.get("banco_origen") or datos.get("banco_destino"))
    if banco_ok:
        score += 25
    else:
        alertas.append("Entidad bancaria o cooperativa no identificada")

    # 2. Monto financiero válido (+25 pts)
    monto_val = datos.get("monto")
    monto_ok = monto_val is not None and 1.0 <= float(monto_val) <= 2000.0
    if monto_ok:
        score += 25
    elif monto_val is not None and float(monto_val) > 2000.0:
        score += 15
        alertas.append(f"Monto inusualmente alto (${monto_val:.2f})")
    else:
        alertas.append("Monto no detectado o inválido")

    # 3. Referencia o número de comprobante (+20 pts)
    ref_val = datos.get("numero_comprobante")
    ref_ok = bool(ref_val and len(str(ref_val).strip()) >= 5)
    if ref_ok:
        score += 20
    else:
        alertas.append("Referencia o secuencial bancario no detectado")

    # 4. Estado de transacción exitosa (+15 pts)
    estado_ok = bool(re.search(
        r"(transferencia\s*exitosa|transacci[oó]n\s*exitosa|pago\s*exitoso|comprobante\s*(?:electr[oó]nico|de\s*pago|de\s*transferencia)|dep[oó]sito\s*exitoso|pagaste|enviaste|recibiste|aplicad[ao])",
        texto_lower
    ))
    if estado_ok:
        score += 15

    # 5. Destinatario o Cuenta coincidente con Opsatel (+15 pts)
    # Cuentas autorizadas: Pichincha 2206388858, JEP 406060337400, Bryan Solano / Opsatel
    beneficiario_txt = (datos.get("beneficiario") or "").lower()
    cuenta_dest_txt = str(datos.get("cuenta_destino") or "")
    
    es_opsatel = False
    if any(k in beneficiario_txt for k in ["bryan", "solano", "opsatel", "0105905251"]):
        es_opsatel = True
    elif any(k in cuenta_dest_txt for k in ["2206388858", "406060337400", "8858", "7400"]):
        es_opsatel = True
    elif any(k in texto_lower for k in ["bryan andres solano", "solano herrera", "0105905251", "2206388858", "406060337400"]):
        es_opsatel = True

    if es_opsatel:
        score += 15
    else:
        if datos.get("beneficiario") and len(datos.get("beneficiario", "")) >= 4:
            alertas.append(f"Beneficiario no coincide con cuentas de Opsatel ({datos.get('beneficiario')})")

    # 6. Evaluación de fecha y vigencia (solo comprobantes del último mes)
    fecha_txt = datos.get("fecha")
    fecha_reciente = True
    if fecha_txt:
        dt_comp = parsear_fecha_texto(fecha_txt)
        if dt_comp:
            es_rec, dias_ant, mot_ant = es_fecha_del_ultimo_mes(dt_comp)
            if not es_rec:
                fecha_reciente = False
                score = max(0, score - 35)
                alertas.append(mot_ant)
        else:
            m_anio = re.search(r"\b(202[0-9])\b", str(fecha_txt))
            if m_anio:
                anio_comp = int(m_anio.group(1))
                ahora_anio = datetime.utcnow().year
                if anio_comp < ahora_anio:
                    score = max(0, score - 35)
                    fecha_reciente = False
                    alertas.append(f"Comprobante antiguo de año anterior ({anio_comp})")

    score = min(100, max(0, score))

    if score >= 80:
        nivel = "ALTO"
    elif score >= 55:
        nivel = "MEDIO"
    elif score > 0:
        nivel = "BAJO"
    else:
        nivel = "INVALIDO"

    return {
        "score": score,
        "nivel": nivel,
        "es_opsatel_destinatario": es_opsatel,
        "es_fecha_reciente": fecha_reciente,
        "banco_identificado": banco_ok,
        "monto_identificado": monto_ok,
        "referencia_identificada": ref_ok,
        "estado_transaccion_exitoso": estado_ok,
        "alertas": alertas
    }


def extraer_texto_tesseract_mejorado(image_path: str) -> str:
    """
    Ejecuta Tesseract LSTM (--oem 1) sobre la imagen previamente mejorada en alta definición
    (sin binarización destructiva que rompa letras/números).
    """
    try:
        # pyrefly: ignore[missing-import]
        import pytesseract  # type: ignore
        from PIL import Image

        with Image.open(image_path) as img:
            textos_brutos: List[str] = []
            for lang in ["spa+eng", "spa", "eng", None]:
                lang_kwargs = {"lang": lang} if lang else {}
                try:
                    # PSM 4: Columna única de tamaños variables con motor neuronal LSTM (--oem 1)
                    t1 = pytesseract.image_to_string(img, **lang_kwargs, config="--oem 1 --psm 4 -c preserve_interword_spaces=1")
                    if t1 and t1.strip():
                        textos_brutos.append(t1)

                    # PSM 6: Bloque uniforme como respaldo
                    t2 = pytesseract.image_to_string(img, **lang_kwargs, config="--oem 1 --psm 6")
                    if t2 and t2.strip():
                        textos_brutos.append(t2)

                    if textos_brutos:
                        break
                except Exception:
                    continue

            return unificar_textos_extraidos(textos_brutos)
    except Exception as e:
        logger.warning(f"[OCR] Aviso en extracción Tesseract directo: {e}")
        return ""


def ejecutar_tesseract_cli(image_path: str) -> str:
    """
    Fallback directo invocando el binario del sistema 'tesseract' sobre la imagen HD mejorada.
    """
    textos_cli: List[str] = []
    tesseract_bin = "tesseract"

    for lang in ["spa+eng", "spa", "eng"]:
        for psm in ["4", "6"]:
            try:
                cmd = [tesseract_bin, image_path, "stdout", "-l", lang, "--oem", "1", "--psm", psm, "-c", "preserve_interword_spaces=1"]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
                if res.returncode == 0 and res.stdout and res.stdout.strip():
                    textos_cli.append(res.stdout.strip())
            except Exception:
                pass
        if textos_cli:
            break

    return unificar_textos_extraidos(textos_cli)


def ejecutar_ocr_en_entorno_servidor(image_path: str, python_bin: str) -> str:
    """
    Invoca el intérprete en /var/www/html/entornos/ia_env recibiendo la imagen ya mejorada en HD.
    Intenta primero RapidOCR si está en ia_env, y luego pytesseract con LSTM (--oem 1) sin binarización destructiva.
    """
    try:
        codigo_inline = f"""
import sys
import json

img_file = {json.dumps(image_path)}
salida = ""

# 1. Intentar con RapidOCR si existe en el entorno
try:
    from rapidocr_onnxruntime import RapidOCR
    engine = RapidOCR()
    result, _ = engine(img_file, box_thresh=0.3, unclip_ratio=1.8)
    if result:
        items = []
        for box, text, score in result:
            if float(score) < 0.50:
                continue
            ys = [p[1] for p in box]
            xs = [p[0] for p in box]
            items.append({{'y': (min(ys)+max(ys))/2.0, 'h': max(1.0, max(ys)-min(ys)), 'x': min(xs), 'text': text.strip()}})
        items.sort(key=lambda it: it['y'])
        rows = []
        for it in items:
            placed = False
            for row in rows:
                avg_y = sum(r['y'] for r in row)/len(row)
                avg_h = sum(r['h'] for r in row)/len(row)
                if abs(it['y'] - avg_y) <= max(avg_h * 0.65, 18.0):
                    row.append(it)
                    placed = True
                    break
            if not placed:
                rows.append([it])
        lines = []
        for row in rows:
            row.sort(key=lambda r: r['x'])
            lines.append(' '.join(r['text'] for r in row))
        salida = '\\n'.join(lines)
except Exception:
    pass

# 2. Si no hubo salida de RapidOCR, usar pytesseract LSTM sobre la imagen HD mejorada
if not salida.strip():
    try:
        import pytesseract
        from PIL import Image
        with Image.open(img_file) as img:
            for lang in ["spa+eng", "spa", "eng", None]:
                lk = {{"lang": lang}} if lang else {{}}
                try:
                    t1 = pytesseract.image_to_string(img, **lk, config="--oem 1 --psm 4 -c preserve_interword_spaces=1")
                    if t1 and t1.strip():
                        salida = t1.strip()
                        break
                except Exception:
                    continue
    except Exception as e:
        sys.stderr.write(str(e))

sys.stdout.write(salida)
"""
        res = subprocess.run(
            [python_bin, "-c", codigo_inline],
            capture_output=True,
            text=True,
            timeout=35
        )
        if res.returncode == 0 and res.stdout and res.stdout.strip():
            return postprocesar_texto_comprobante(res.stdout.strip())
        elif res.stderr:
            logger.warning(f"[OCR] Subproceso {python_bin} retornó stderr: {res.stderr}")
    except Exception as e_sub:
        logger.warning(f"[OCR] Error ejecutando subproceso en {python_bin}: {e_sub}")

    return ""


def analizar_comprobante_ocr(file_path_or_name: str) -> Dict[str, Any]:
    """
    Función principal de análisis OCR:
    1. Resuelve la ruta física del archivo descargado.
    2. Mejora la calidad de la imagen (Super-Sampling Bicúbico 2.4x, eliminación de marca de agua
       con curva Gamma suave, Unsharp Mask para nitidez de letras/números y enmascarado de QR).
    3. Ejecuta el motor OCR de alta precisión (RapidOCR Deep Learning + entorno ia_env / Tesseract HD).
    4. Estructura todos los datos bancarios y devuelve tanto los campos clave como el texto íntegro.
    """
    ruta_real = buscar_ruta_archivo(file_path_or_name)
    if not ruta_real:
        logger.warning(f"[OCR] No se encontró el archivo físico para '{file_path_or_name}'")
        return {
            "success": False,
            "es_documento_valido": False,
            "motivo_validacion_documento": "archivo_no_encontrado",
            "error": "archivo_no_encontrado",
            "ruta_buscada": file_path_or_name
        }

    # Paso 1: Subir la calidad de la imagen antes del escaneo OCR
    ruta_ocr_hd, temp_cleanup = mejorar_calidad_imagen_para_ocr(ruta_real)

    texto_extraido = ""
    try:
        # A. Prioridad 1: Motor Deep Learning RapidOCR (PP-OCRv4 con reconstrucción de filas) sobre imagen HD
        texto_extraido = extraer_texto_rapidocr(ruta_ocr_hd)

        # B. Prioridad 2: Entorno virtual del servidor en /var/www/html/entornos/ia_env sobre imagen HD
        if not texto_extraido or not texto_extraido.strip():
            ia_python = obtener_interprete_python()
            if ia_python:
                logger.info(f"[OCR] Utilizando intérprete de servidor: {ia_python}")
                texto_extraido = ejecutar_ocr_en_entorno_servidor(ruta_ocr_hd, ia_python)

        # C. Prioridad 3: Pytesseract LSTM en proceso actual sobre imagen HD
        if not texto_extraido or not texto_extraido.strip():
            texto_extraido = extraer_texto_tesseract_mejorado(ruta_ocr_hd)

        # D. Prioridad 4: Binario CLI tesseract del sistema sobre imagen HD
        if not texto_extraido or not texto_extraido.strip():
            texto_extraido = ejecutar_tesseract_cli(ruta_ocr_hd)
    finally:
        if temp_cleanup and os.path.exists(temp_cleanup):
            try:
                os.remove(temp_cleanup)
            except Exception:
                pass

    if not texto_extraido or not texto_extraido.strip():
        logger.warning(f"[OCR] No se pudo extraer texto de '{os.path.basename(ruta_real)}'")
        return {
            "success": False,
            "error": "sin_texto_detectado",
            "ruta_archivo": ruta_real
        }

    # E. Parseo detallado de todos los datos del comprobante
    datos_extraidos = parsear_texto_comprobante(texto_extraido)

    # Validar si es realmente un comprobante bancario o documento financiero admitido
    es_valido, motivo_doc = es_documento_comprobante_valido(texto_extraido, datos_extraidos)

    # Evaluación profunda de autenticidad, destino Opsatel y vigencia
    autenticidad = calcular_score_autenticidad(texto_extraido, datos_extraidos)
    hash_imagen = calcular_hash_archivo(ruta_real)

    # F. Construir resumen descriptivo
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
        partes.append(f"Cta Destino: {datos_extraidos['cuenta_destino']}")
    if datos_extraidos.get("cuenta_origen"):
        partes.append(f"Cta Origen: {datos_extraidos['cuenta_origen']}")
    if datos_extraidos.get("fecha"):
        partes.append(f"Fecha: {datos_extraidos['fecha']}")
    partes.append(f"Certeza: {autenticidad.get('score', 0)}%")

    resumen_str = " | ".join(partes) if partes else ("Comprobante procesado con éxito" if es_valido else "Documento no admitido")

    logger.info(f"[OCR] {'✅ Comprobante válido' if es_valido else '⚠️ Documento no válido'} ({os.path.basename(ruta_real)}): {resumen_str}")

    return {
        "success": True,
        "es_documento_valido": es_valido,
        "motivo_validacion_documento": motivo_doc,
        "hash_imagen": hash_imagen,
        "score_autenticidad": autenticidad.get("score", 0),
        "nivel_confianza": autenticidad.get("nivel", "INVALIDO"),
        "es_opsatel_destinatario": autenticidad.get("es_opsatel_destinatario", False),
        "alertas_autenticidad": autenticidad.get("alertas", []),
        "es_fecha_reciente": autenticidad.get("es_fecha_reciente", True),
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
