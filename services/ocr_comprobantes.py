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

    resumen_str = " | ".join(partes) if partes else "Comprobante procesado con éxito"

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
