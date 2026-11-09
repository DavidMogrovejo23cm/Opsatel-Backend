"""
Servicio OCR para Comprobantes de Pago de Opsatel.
Utiliza Tesseract OCR y Pillow para procesar automáticamente las fotos recibidas por WhatsApp,
extrayendo: Banco de origen, Monto pagado, Número de referencia/comprobante y Fecha.
"""

import os
import re
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("opsatel.ocr_comprobantes")

# Lista de bancos y billeteras populares en Ecuador
BANCOS_ECUADOR = [
    {"nombre": "Banco Pichincha", "patrones": [r"pichincha", r"bco\.?\s*pichincha"]},
    {"nombre": "DeUna", "patrones": [r"deuna", r"de\s*una"]},
    {"nombre": "Banco Guayaquil", "patrones": [r"guayaquil", r"banco\s*del\s*barrio", r"bco\.?\s*guayaquil"]},
    {"nombre": "Peigo", "patrones": [r"peigo"]},
    {"nombre": "Produbanco", "patrones": [r"produbanco", r"promerica", r"be\s*produbanco"]},
    {"nombre": "Banco del Pacífico", "patrones": [r"pac[ií]fico", r"bco\.?\s*pac[ií]fico"]},
    {"nombre": "Banco Bolivariano", "patrones": [r"bolivariano", r"veinti4"]},
    {"nombre": "Banco Internacional", "patrones": [r"banco\s*internacional", r"interbanco"]},
    {"nombre": "Banco del Austro", "patrones": [r"austro", r"bco\.?\s*austro"]},
    {"nombre": "Banco Solidario", "patrones": [r"solidario"]},
    {"nombre": "Banco de Machala", "patrones": [r"machala"]},
    {"nombre": "Cooperativa JEP", "patrones": [r"coop\.?\s*jep", r"\bjep\b", r"juventud\s*ecuatoriana"]},
    {"nombre": "Cooperativa Policía Nacional", "patrones": [r"polic[ií]a\s*nacional", r"cpn\b"]},
    {"nombre": "Cooperativa 29 de Octubre", "patrones": [r"29\s*de\s*octubre"]},
    {"nombre": "Cooperativa Alianza del Valle", "patrones": [r"alianza\s*del\s*valle"]},
    {"nombre": "Cooperativa Mushuc Runa", "patrones": [r"mushuc\s*runa"]},
    {"nombre": "Cooperativa CoopMego", "patrones": [r"coopmego", r"mego"]},
    {"nombre": "Cooperativa Oscus", "patrones": [r"oscus"]},
    {"nombre": "Cooperativa Andalucía", "patrones": [r"andaluc[ií]a"]},
    {"nombre": "Payphone", "patrones": [r"payphone"]}
]


def buscar_ruta_archivo(file_path_or_name: str) -> Optional[str]:
    """Busca la existencia real del archivo de imagen en múltiples rutas posibles."""
    if not file_path_or_name:
        return None

    # Limpiar prefijo web si viene como /uploadscr/xxx.jpg
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


def extraer_texto_tesseract(image_path: str) -> str:
    """Invoca pytesseract sobre la imagen con preprocesamiento básico de contraste."""
    try:
        # pyrefly: ignore[missing-import]
        import pytesseract
        from PIL import Image, ImageEnhance, ImageOps
    except ImportError:
        logger.warning("[OCR] pytesseract o Pillow no están instalados. No se puede ejecutar OCR.")
        return ""

    try:
        with Image.open(image_path) as img:
            # Convertir a escala de grises
            gray = ImageOps.grayscale(img)
            
            # Mejorar contraste para comprobantes con fondo tenue o capturas móviles
            enhancer = ImageEnhance.Contrast(gray)
            enhanced = enhancer.enhance(1.8)

            # Intentar primero con idiomas español e inglés
            try:
                text = pytesseract.image_to_string(enhanced, lang="spa+eng", config="--psm 6")
            except Exception:
                # Fallback al idioma por defecto si no están instalados los diccionarios específicos
                try:
                    text = pytesseract.image_to_string(enhanced, lang="spa")
                except Exception:
                    text = pytesseract.image_to_string(enhanced)

            return text or ""
    except Exception as e:
        logger.error(f"[OCR] Error procesando imagen '{image_path}' con Tesseract: {e}")
        return ""


def detectar_banco(texto: str) -> Optional[str]:
    """Identifica el banco o entidad financiera emisora del comprobante."""
    texto_lower = texto.lower()
    for banco in BANCOS_ECUADOR:
        for patron in banco["patrones"]:
            if re.search(patron, texto_lower):
                return banco["nombre"]
    return None


def detectar_monto(texto: str) -> Optional[float]:
    """Extrae el monto monetario de la transacción en dólares (USD)."""
    # 1. Patrones prioritarios con etiquetas explícitas
    patrones_etiqueta = [
        r"(?:monto|valor|total|importe|cantidad|usd|\$)\s*[:.]?\s*(?:usd|\$)?\s*(\d{1,5}[\.,]\d{2})\b",
        r"(?:transferencia por|pagaste|enviaste|recibiste)\s*[:.]?\s*(?:usd|\$)?\s*(\d{1,5}[\.,]\d{2})\b",
        r"\$\s*(\d{1,5}[\.,]\d{2})\b"
    ]

    for p in patrones_etiqueta:
        coincidencias = re.findall(p, texto, re.IGNORECASE)
        if coincidencias:
            for c in coincidencias:
                try:
                    val_str = c.replace(",", ".")
                    val_float = float(val_str)
                    if 0.50 <= val_float <= 10000.00:
                        return val_float
                except ValueError:
                    continue

    # 2. Búsqueda secundaria de cifras con formato de moneda en el cuerpo
    cifras = re.findall(r"\b(\d{1,4}[\.,]\d{2})\b", texto)
    for c in cifras:
        try:
            val_str = c.replace(",", ".")
            val_float = float(val_str)
            # Descartar montos inverosímiles para cuotas de ISP típicas si es ambiguo
            if 3.00 <= val_float <= 500.00:
                return val_float
        except ValueError:
            continue

    return None


def detectar_referencia(texto: str) -> Optional[str]:
    """Extrae el número de comprobante, autorización, control o referencia."""
    patrones_ref = [
        r"(?:referencia|ref\.?|comprobante|transacci[oó]n|secuencial|autorizaci[oó]n|control|n[uú]mero|no\.?)\s*[:.]?\s*#?\s*([0-9A-Za-z-]{5,25})\b",
        r"(?:nro|num)\s*[:.]?\s*([0-9A-Za-z-]{5,25})\b"
    ]

    for p in patrones_ref:
        m = re.search(p, texto, re.IGNORECASE)
        if m:
            ref_val = m.group(1).strip()
            # Descartar palabras comunes que pudieran capturarse por error
            if not re.match(r"^(cuenta|ahorros|corriente|fecha|banco|monto|valor)$", ref_val, re.IGNORECASE):
                return ref_val

    # Si hay una secuencia numérica aislada típica de transacción bancaria (6 a 12 dígitos)
    numeros_largos = re.findall(r"\b(\d{6,14})\b", texto)
    for n in numeros_largos:
        # Descartar cédulas de 10 dígitos si comienzan en 01-24 para no confundir con identificación
        if len(n) == 10 and int(n[:2]) <= 24:
            continue
        return n

    return None


def detectar_fecha(texto: str) -> Optional[str]:
    """Extrae la fecha en que se emitió la transacción."""
    m_fecha = re.search(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b", texto)
    if m_fecha:
        return m_fecha.group(1)

    m_fecha_texto = re.search(r"\b(\d{1,2}\s+(?:de\s+)?(?:ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)[a-z]*\s+(?:de\s+)?\d{2,4})\b", texto, re.IGNORECASE)
    if m_fecha_texto:
        return m_fecha_texto.group(1)

    return None


def analizar_comprobante_ocr(file_path_or_name: str) -> Dict[str, Any]:
    """
    Función principal de análisis OCR.
    Recibe la ruta o nombre del archivo en uploadscr, ejecuta Tesseract OCR
    y devuelve los metadatos financieros detectados.
    """
    ruta_real = buscar_ruta_archivo(file_path_or_name)
    if not ruta_real:
        logger.warning(f"[OCR] No se encontró el archivo físico para '{file_path_or_name}'")
        return {
            "success": False,
            "error": "archivo_no_encontrado",
            "ruta_buscada": file_path_or_name
        }

    texto_extraido = extraer_texto_tesseract(ruta_real)
    if not texto_extraido or not texto_extraido.strip():
        return {
            "success": False,
            "error": "sin_texto_detectado",
            "ruta_archivo": ruta_real
        }

    banco = detectar_banco(texto_extraido)
    monto = detectar_monto(texto_extraido)
    referencia = detectar_referencia(texto_extraido)
    fecha = detectar_fecha(texto_extraido)

    resumen_partes = []
    if banco:
        resumen_partes.append(f"Banco: {banco}")
    if monto is not None:
        resumen_partes.append(f"Monto: ${monto:.2f}")
    if referencia:
        resumen_partes.append(f"Ref: {referencia}")
    if fecha:
        resumen_partes.append(f"Fecha: {fecha}")

    resumen_str = " | ".join(resumen_partes) if resumen_partes else "Texto detectado sin datos estructurados"

    logger.info(f"[OCR] ✅ Procesado '{os.path.basename(ruta_real)}': {resumen_str}")

    return {
        "success": True,
        "banco_origen": banco,
        "monto": monto,
        "numero_referencia": referencia,
        "fecha_transaccion": fecha,
        "resumen_ocr": f"[OCR] {resumen_str}",
        "texto_extraido": texto_extraido.strip(),
        "ruta_archivo": ruta_real
    }

