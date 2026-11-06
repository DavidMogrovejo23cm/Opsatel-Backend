"""
@file movie_service.py
@author David Mogrovejo dmogrovejo87@gmail.com
@copyright (c) 2026 David Mogrovejo. All Rights Reserved.
@notice Developed with AI assistance.

Servicio Inteligente de Búsqueda, Recomendación y Solicitud de Películas para WhatsApp (OPSATV).
- Reconoce automáticamente si el usuario pregunta o menciona una película en lenguaje natural,
  incluso con faltas de ortografía o sin palabras clave ("recomiéndame", "películas", etc.).
- Busca primero en la base de datos interna (tabla 'peliculas') guiándose en los campos:
  nombre, descripcion, generos, actores y audio, con tolerancia a errores ortográficos.
- Si no existe en la base de datos, continúa la búsqueda en The Movie Database (TMDb)
  y presenta los resultados como sugerencias para solicitar su inclusión en OPSATV.
- Protege los flujos operativos normales de Opsatel (cobranzas, soporte técnico y saludos).
"""

import os
import re
import json
import logging
import unicodedata
import difflib
import urllib.request
import urllib.parse
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import or_
import models

logger = logging.getLogger("opsatel.movie_service")

# Clave y URLs de The Movie Database (TMDb API v3)
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "cfe422613b250f702980a3bbf9e90716").strip()
TMDB_BASE_URL = "https://api.themoviedb.org/3"

# Palabras vacías y conectores para normalización
STOPWORDS = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al", "a",
    "y", "e", "o", "u", "en", "con", "por", "para", "que", "como", "si", "se"
}

# Palabras introductorias / frases de descarte en consultas de películas
INTRO_PHRASES = [
    r'^(?:hola|buenas|buenos dias|buenas tardes|buenas noches|saludos|amigo|amiga)\b',
    r'^(?:por favor|porfa|favor)\b',
    r'^(?:me gustaria ver|quisiera ver|quiero ver|deseo ver|puedo ver|voy a ver)\b',
    r'^(?:tienen la pelicula|tienen la película|tienen la peli|tienes la pelicula|tienes la película|tienes la peli)\b',
    r'^(?:tienen disponible|tienes disponible|esta disponible|está disponible)\b',
    r'^(?:tienen el|tienen la|tienen los|tienen las|tienen un|tienen una|tienen)\b',
    r'^(?:tienes el|tienes la|tienes los|tienes las|tienes un|tienes una|tienes)\b',
    r'^(?:hay la pelicula|hay la película|hay la peli|hay el film|hay peliculas|hay películas)\b',
    r'^(?:hay el|hay la|hay los|hay las|hay un|hay una|hay)\b',
    r'^(?:esta la pelicula|está la película|esta la peli|está la peli|esta el|está el|esta la|está la)\b',
    r'^(?:busco la pelicula|busco la película|busco la peli|busco el film|busco el|busco la|busco)\b',
    r'^(?:me recomiendas una pelicula de|me recomiendas una película de|me recomiendas una pelicula|me recomiendas una película)\b',
    r'^(?:me recomiendas una peli de|me recomiendas una peli|me recomiendas|recomiendame|recomiéndame|recomienda|recomendame)\b',
    r'^(?:sugiereme|sugiéreme|sugerencia de|recomendacion de|recomendación de)\b',
    r'^(?:de que trata la pelicula|de qué trata la película|de que trata la peli|de que trata|de qué trata|sinopsis de|info de|informacion de|información de)\b',
    r'^(?:que tal es|que tal esta|qué tal está|que tal)\b',
    r'^(?:una pelicula de|una película de|una peli de|pelicula de|película de|peli de|peliculas de|películas de)\b',
    r'^(?:una pelicula|una película|una peli|pelicula|película|peli|peliculas|películas)\b',
    r'\b(?:en opsatv|en la tv|en el catalogo|en el catálogo|por favor|porfa)\b'
]

# Palabras o intenciones que PERTENECEN A OPSATEL (Soporte, Cobranzas, Saludos) y NO son películas
INTENCIONES_OPERATIVAS_ISP = [
    # Cobranzas y pagos
    "saldo", "debo", "deuda", "cuanto debo", "cuánto debo", "cuenta", "banco", "pichincha", "jep",
    "transferencia", "pago", "pagar", "pagado", "factura", "facturacion", "facturación",
    "comprobante", "recibo", "deposito", "depósito", "corte", "cortaron", "suspension", "suspensión",
    "suspendido", "suspendida", "reconexion", "reconexión", "moroso", "morosidad",
    # Soporte técnico y fallas de internet
    "no tengo internet", "sin internet", "sin servicio", "no hay internet", "falla el internet",
    "internet lento", "lento el internet", "luz roja", "foco rojo", "los rojo", "pon rojo",
    "los parpadea", "foco los", "fibra rota", "cable roto", "sin señal", "router", "wifi",
    "ont", "clave del wifi", "cambio de clave", "reiniciar router", "soporte tecnico", "soporte técnico",
    "visita tecnica", "visita técnica", "tecnico", "técnico", "instalacion", "instalación", "traslado",
    # Planes y contrataciones
    "planes de internet", "cambiar de plan", "mejorar plan", "cuanto cuesta el internet", "contratar",
    # Operador humano
    "asesor", "humano", "operador", "persona", "hablar con alguien", "secretaria"
]

# Géneros comunes para clasificación y búsqueda
GENEROS_KEYWORDS = {
    "accion": ["accion", "acción", "action", "balazos", "peleas", "disparos"],
    "comedia": ["comedia", "comedy", "risa", "divertida", "graciosa", "chistosa"],
    "terror": ["terror", "miedo", "horror", "paranormal", "escalofriante", "espanto", "miedosa"],
    "drama": ["drama", "dramatica", "dramática", "emotiva", "sentimental", "llorar"],
    "suspenso": ["suspenso", "thriller", "misterio", "intriga"],
    "romance": ["romance", "romantica", "romántica", "amor", "pareja", "romanticas"],
    "ciencia ficcion": ["ciencia ficcion", "ciencia ficción", "sci-fi", "scifi", "espacio", "futuro", "alien"],
    "aventura": ["aventura", "aventuras", "adventure"],
    "animacion": ["animacion", "animación", "animada", "animadas", "infantil", "infantiles", "dibujos", "niños", "caricatura", "caricaturas", "anime"],
    "fantasia": ["fantasia", "fantasía", "magia", "fantasy"],
    "crimen": ["crimen", "policial", "mafia", "gangster", "detective"],
    "documental": ["documental", "documentales", "historia real"]
}

# Audios comunes
AUDIOS_KEYWORDS = {
    "latino": ["latino", "español latino", "audio latino", "en latino"],
    "castellano": ["castellano", "españa", "español de españa"],
    "ingles": ["ingles", "inglés", "subtitulada", "subtitulado", "subtitulos", "subtítulos", "idioma original", "en ingles"],
    "dual": ["dual", "multiaudio"]
}


def normalizar_texto(texto: str) -> str:
    """Normaliza texto removiendo acentos, mayúsculas y caracteres no alfanuméricos."""
    if not texto:
        return ""
    texto_str = str(texto).strip()
    texto_nfd = unicodedata.normalize("NFD", texto_str.lower())
    sin_tildes = "".join(c for c in texto_nfd if unicodedata.category(c) != "Mn")
    limpio = re.sub(r'[^a-z0-9\s]', ' ', sin_tildes)
    return re.sub(r'\s+', ' ', limpio).strip()


def es_intencion_operativa_isp(mensaje: str) -> bool:
    """
    Determina si el mensaje del usuario corresponde estrictamente a una gestión de ISP
    (soporte técnico de internet, saldo, facturas, comprobantes, saludos secos, cédulas).
    Si retorna True, NO se debe tratar como búsqueda de películas.
    """
    if not mensaje:
        return True

    msg_norm = normalizar_texto(mensaje)
    if not msg_norm:
        return True

    # 1. Saludos o expresiones de cortesía pura (ej: "hola", "buenas tardes", "hola amigo", "muchas gracias")
    saludos_palabras = {
        "hola", "buenas", "bueno", "buenos", "dias", "dia", "tardes", "tarde", "noches", "noche",
        "saludos", "amigo", "amiga", "sam", "opsatel", "opsatv", "menu", "cancelar", "salir",
        "inicio", "ok", "gracias", "muchas", "porfa", "favor", "por", "que", "tal", "como",
        "estas", "estan", "ayuda", "colaboras", "buenas tardes", "buenos dias", "buenas noches"
    }
    palabras_mensaje = set(msg_norm.split())
    if palabras_mensaje and palabras_mensaje.issubset(saludos_palabras):
        return True

    # 2. Número de cédula o teléfono puro (10 dígitos o RUC de 13 dígitos)
    solo_digitos = re.sub(r'\D', '', mensaje)
    if (len(solo_digitos) == 10 or len(solo_digitos) == 13) and len(msg_norm.split()) <= 2:
        return True

    # 3. Contiene términos operativos claros de internet/cobranzas
    for palabra_isp in INTENCIONES_OPERATIVAS_ISP:
        pal_norm = normalizar_texto(palabra_isp)
        if re.search(r'\b' + re.escape(pal_norm) + r'\b', msg_norm):
            # Excepción: si además menciona explícitamente "pelicula", "serie", "opsatv", no descartar
            if not any(k in msg_norm for k in ["pelicula", "peli", "serie", "opsatv", "cine"]):
                return True

    return False


def calcular_similitud_fuzzy(query: str, texto_candidato: str) -> float:
    """
    Calcula el puntaje de similitud (0.0 a 1.0) entre la consulta del usuario y un texto candidato
    (título, actores, descripción o género de la película).
    Tolera faltas de ortografía, transposición de letras, omisiones o pequeñas diferencias fonéticas.
    """
    q_norm = normalizar_texto(query)
    c_norm = normalizar_texto(texto_candidato)

    if not q_norm or not c_norm:
        return 0.0

    # Coincidencia exacta o subcadena directa
    if q_norm == c_norm:
        return 1.0
    if q_norm in c_norm:
        return 0.98

    q_words = [w for w in q_norm.split() if w not in STOPWORDS and len(w) >= 3]
    c_words = [w for w in c_norm.split() if w not in STOPWORDS and len(w) >= 3]

    if not q_words or not c_words:
        # Comparación general de caracteres si son palabras muy cortas
        return difflib.SequenceMatcher(None, q_norm, c_norm).ratio()

    q_content = " ".join(q_words)
    c_content = " ".join(c_words)
    if q_content in c_content:
        return 0.98

    # Para cada palabra del query, buscar la palabra más parecida en el candidato
    puntuaciones_palabras = []
    for qw in q_words:
        mejor_match = 0.0
        for cw in c_words:
            if qw == cw:
                mejor_match = 1.0
                break
            elif len(qw) >= 4 and len(cw) >= 4 and (qw.startswith(cw) or cw.startswith(qw)):
                mejor_match = max(mejor_match, 0.92)
            else:
                ratio = difflib.SequenceMatcher(None, qw, cw).ratio()
                mejor_match = max(mejor_match, ratio)
        puntuaciones_palabras.append(mejor_match)

    promedio_palabras = sum(puntuaciones_palabras) / len(puntuaciones_palabras)
    ratio_completo = difflib.SequenceMatcher(None, q_content, c_content).ratio()

    return max(promedio_palabras, ratio_completo)


def extraer_termino_y_filtros(mensaje: str) -> Tuple[str, Optional[str], Optional[str], bool, str]:
    """
    Extrae de forma limpia el término de búsqueda, género, audio y si es una solicitud formal.
    Retorna: (termino_limpio, genero_detectado, audio_detectado, es_solicitud, titulo_solicitud)
    """
    texto = mensaje.strip()
    texto_lower = texto.lower()

    # 1. Verificar si es una solicitud formal (ej: "SOLICITAR Gladiator", "quiero solicitar la pelicula Avatar")
    m_solic = re.search(r'(?:solicitar|quiero solicitar|por favor agregar|agreguen|añadir)\s+(?:la\s+pelicula\s+|la\s+peli\s+|la\s+película\s+)?([a-zA-Z0-9\s:_-]{2,60})', texto, re.IGNORECASE)
    if m_solic:
        tit = m_solic.group(1).strip(" .!,;¿?\"'")
        if len(tit) >= 2:
            return tit, None, None, True, tit

    # 2. Detectar género
    genero_detectado = None
    for gen, variantes in GENEROS_KEYWORDS.items():
        if any(re.search(r'\b' + re.escape(normalizar_texto(v)) + r'\b', normalizar_texto(texto_lower)) for v in variantes):
            genero_detectado = gen
            break

    # 3. Detectar audio
    audio_detectado = None
    for aud, variantes in AUDIOS_KEYWORDS.items():
        if any(re.search(r'\b' + re.escape(normalizar_texto(v)) + r'\b', normalizar_texto(texto_lower)) for v in variantes):
            audio_detectado = aud
            break

    # 4. Limpiar frases introductorias conversacionales
    limpio = texto_lower
    for pat in INTRO_PHRASES:
        limpio = re.sub(pat, '', limpio, flags=re.IGNORECASE).strip()

    # Quitar signos de puntuación iniciales y finales
    limpio = re.sub(r'^[^\w\d]+|[^\w\d]+$', '', limpio).strip()

    # Quitar conectores sueltos iniciales (ej: "de accion", "con audio latino")
    limpio = re.sub(r'^(?:de|con|en|del|la|el|los|las|un|una)\s+', '', limpio, flags=re.IGNORECASE).strip()

    # Si quedó exactamente igual al género detectado
    if genero_detectado and (not limpio or limpio == genero_detectado or limpio in GENEROS_KEYWORDS.get(genero_detectado, [])):
        limpio = ""

    # Si quedó exactamente igual al audio detectado
    if audio_detectado and limpio == audio_detectado:
        limpio = ""

    return limpio[:60].strip(), genero_detectado, audio_detectado, False, ""


def asegurar_tabla_peliculas(db: Session):
    """Garantiza que la tabla 'peliculas' exista en la base de datos sin generar errores."""
    try:
        bind = db.get_bind()
        models.Base.metadata.create_all(bind=bind, tables=[models.Pelicula.__table__], checkfirst=True)
    except Exception as e:
        logger.warning(f"[Movie Service] Aviso verificando tabla 'peliculas': {e}")


def buscar_peliculas_en_bd(
    db: Session,
    termino: str,
    genero: Optional[str] = None,
    audio: Optional[str] = None,
    limit: int = 3
) -> List[Dict[str, Any]]:
    """
    Busca películas en la tabla 'peliculas' guiándose en los campos:
    nombre, descripcion, generos, actores y audio.
    Aplica una búsqueda híbrida (SQL + Fuzzy Matching en memoria) para tolerar
    faltas de ortografía (ej: 'harry poter', 'interstelar', 'espiderman', etc.).
    """
    asegurar_tabla_peliculas(db)
    coincidencias = []

    try:
        # Cargar películas existentes de la base de datos
        query_all = db.query(models.Pelicula)
        todas = query_all.all()

        if not todas:
            return []

        candidatos_con_puntaje = []

        for p in todas:
            nombre = p.nombre or ""
            descripcion = p.descripcion or ""
            generos = p.generos or ""
            actores = p.actores or ""
            aud = p.audio or ""
            anio = getattr(p, "anio", "") or ""

            score_total = 0.0

            # 1. Si el usuario buscó por un término (título, actor, palabra de descripción)
            if termino and len(termino) >= 2:
                # Similitud con el nombre (peso mayor)
                score_nombre = calcular_similitud_fuzzy(termino, nombre)
                # Similitud con los actores
                score_actores = calcular_similitud_fuzzy(termino, actores) * 0.85
                # Similitud con los géneros
                score_generos = calcular_similitud_fuzzy(termino, generos) * 0.80
                # Similitud con la descripción
                score_desc = 0.90 if normalizar_texto(termino) in normalizar_texto(descripcion) else 0.0

                score_termino = max(score_nombre, score_actores, score_generos, score_desc)
                score_total = max(score_total, score_termino)

            # 2. Si se detectó género en el mensaje
            if genero:
                variantes = GENEROS_KEYWORDS.get(genero, [genero])
                gen_match = any(
                    normalizar_texto(v) in normalizar_texto(generos)
                    or normalizar_texto(v) in normalizar_texto(nombre)
                    or normalizar_texto(v) in normalizar_texto(descripcion)
                    for v in variantes
                )
                if gen_match:
                    score_total = max(score_total, 0.88)

            # 3. Si se detectó audio en el mensaje
            if audio:
                variantes_aud = AUDIOS_KEYWORDS.get(audio, [audio])
                aud_match = any(normalizar_texto(v) in normalizar_texto(aud) for v in variantes_aud)
                if aud_match:
                    score_total = max(score_total, 0.88)

            # Si supera el umbral de confianza (>= 0.70 tolera errores ortográficos típicos)
            if score_total >= 0.70:
                candidatos_con_puntaje.append((score_total, {
                    "id": p.id,
                    "nombre": nombre,
                    "descripcion": descripcion or "Disponible en catálogo de OPSATV.",
                    "generos": generos or "General",
                    "actores": actores or "Varios",
                    "audio": aud or "Español Latino",
                    "anio": anio,
                    "calificacion": getattr(p, "calificacion", "") or "",
                    "score": score_total
                }))

        # Ordenar por el mejor puntaje de similitud
        candidatos_con_puntaje.sort(key=lambda x: x[0], reverse=True)
        coincidencias = [item[1] for item in candidatos_con_puntaje[:limit]]

    except Exception as e:
        logger.error(f"[Movie Service] Error al buscar en la tabla 'peliculas': {e}")

    return coincidencias


def buscar_en_tmdb(query_str: str, limit: int = 3) -> List[Dict[str, Any]]:
    """
    Busca películas en The Movie Database (TMDb API v3).
    TMDb posee corrección ortográfica y alias de títulos incorporados.
    Si TMDb falla, realiza fallback a OMDb API.
    """
    if not query_str or len(query_str.strip()) < 2:
        return []

    query_clean = query_str.strip()
    resultados = []

    # 1. Petición a The Movie Database (TMDb)
    try:
        encoded_q = urllib.parse.quote(query_clean)
        url = (
            f"{TMDB_BASE_URL}/search/movie?"
            f"api_key={TMDB_API_KEY}&query={encoded_q}&language=es-MX&include_adult=false&page=1"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Opsatel-Entertainment/1.0"})
        with urllib.request.urlopen(req, timeout=4.5) as resp:
            if resp.status == 200:
                raw = resp.read().decode("utf-8")
                data = json.loads(raw)
                items = data.get("results", [])

                for item in items:
                    titulo = item.get("title") or item.get("original_title") or ""
                    release_date = item.get("release_date") or ""
                    anio = release_date.split("-")[0] if release_date else ""
                    overview = item.get("overview") or "Sinopsis no disponible en español actualmente."
                    vote = item.get("vote_average")
                    vote_str = f"{vote:.1f}" if vote else "N/A"
                    popularity = item.get("popularity", 0)

                    # Verificar relevancia del título respecto a la búsqueda del usuario
                    score_match = calcular_similitud_fuzzy(query_clean, titulo)
                    es_relevante = (
                        score_match >= 0.55
                        or normalizar_texto(query_clean) in normalizar_texto(titulo)
                        or any(query_clean in normalizar_texto(v) for v in GENEROS_KEYWORDS.get(query_clean, []))
                        or popularity >= 10.0
                    )

                    if es_relevante:
                        resultados.append({
                            "titulo": titulo,
                            "anio": anio,
                            "sinopsis": overview[:220] + ("..." if len(overview) > 220 else ""),
                            "calificacion": vote_str,
                            "popularidad": popularity,
                            "fuente": "TMDb"
                        })
                    if len(resultados) >= limit:
                        break
    except Exception as e:
        logger.warning(f"[Movie Service] Error consultando TMDb ({e}). Intentando fallback a OMDb...")

    # 2. Fallback a OMDb si TMDb falló o no devolvió resultados
    if not resultados:
        try:
            from services.omdb_service import consultar_pelicula, buscar_peliculas
            data_omdb = consultar_pelicula(titulo=query_clean)
            if data_omdb.get("encontrado"):
                resultados.append({
                    "titulo": data_omdb.get("titulo"),
                    "anio": data_omdb.get("anio"),
                    "sinopsis": (data_omdb.get("sinopsis") or "")[:220],
                    "calificacion": data_omdb.get("calificacion_imdb") or "N/A",
                    "fuente": "OMDb"
                })
            else:
                busq = buscar_peliculas(query=query_clean)
                for item in busq.get("peliculas", [])[:limit]:
                    resultados.append({
                        "titulo": item.get("titulo"),
                        "anio": item.get("anio"),
                        "sinopsis": "Película disponible para solicitud.",
                        "calificacion": "N/A",
                        "fuente": "OMDb"
                    })
        except Exception as e_omdb:
            logger.error(f"[Movie Service] Error en fallback OMDb: {e_omdb}")

    return resultados


def formatear_respuesta_whatsapp(
    peliculas_bd: List[Dict[str, Any]],
    peliculas_tmdb: List[Dict[str, Any]],
    termino: str,
    genero: Optional[str] = None
) -> str:
    """
    Construye la respuesta para WhatsApp según las películas encontradas en BD o en TMDb.
    """
    # CASO 1: ENCONTRADAS EN LA BASE DE DATOS LOCAL ('peliculas')
    if peliculas_bd:
        header = f"🍿 *Películas de {genero.upper()} en tu catálogo OPSATV* 🎬\n\n" if genero else "🍿 *Películas disponibles en tu catálogo OPSATV* 🎬\n\n"
        msg = header

        for p in peliculas_bd:
            anio_str = f" ({p['anio']})" if p.get("anio") else ""
            msg += f"🎬 *{p['nombre'].upper()}*{anio_str}\n"
            if p.get("generos"):
                msg += f"🎭 *Género:* {p['generos']}\n"
            if p.get("audio"):
                msg += f"🔊 *Audio:* {p['audio']}\n"
            if p.get("actores") and p["actores"] != "Varios":
                msg += f"👥 *Reparto:* {p['actores']}\n"
            if p.get("descripcion"):
                msg += f"📖 *Sinopsis:* {p['descripcion']}\n"
            msg += "\n"

        msg += "✨ _¡Disfrútalas ahora mismo desde tu TV o aplicación OPSATV!_ 📺🍿"
        return msg.strip()

    # CASO 2: NO EXISTEN EN LA BD -> RESULTADOS DE The Movie Database (TMDb) COMO SUGERENCIA
    if peliculas_tmdb:
        termino_display = termino.capitalize() if termino else "la producción consultada"
        msg = (
            f"🎬 No encontramos *\"{termino_display}\"* directamente en el catálogo activo de OPSATV, "
            f"pero encontramos estas opciones en *The Movie Database (TMDb)*:\n\n"
        )

        for m in peliculas_tmdb:
            anio_str = f" ({m['anio']})" if m.get("anio") else ""
            calif_str = f" — ⭐ {m['calificacion']}/10" if m.get("calificacion") and m['calificacion'] != "N/A" else ""
            msg += f"🎬 *{m['titulo']}*{anio_str}{calif_str}\n"
            if m.get("sinopsis"):
                msg += f"📖 {m['sinopsis']}\n"
            msg += "\n"

        primera = peliculas_tmdb[0]["titulo"]
        msg += (
            "💡 *¿Deseas verla en tu pantalla?*\n"
            "Puedes solicitar que nuestro equipo la agregue a tu plataforma respondiendo:\n"
            f"👉 *SOLICITAR {primera}*\n\n"
            "_¡Nuestro equipo la subirá al catálogo a la brevedad!_ ✨"
        )
        return msg.strip()

    return ""


def gestionar_consulta_peliculas(mensaje: str, db: Session) -> Optional[str]:
    """
    Función principal interceptora ejecutada ANTES de que interactúe la IA general de Groq.
    1. Si es mensaje operativo de soporte/cobranza/saludo: retorna None (no interfiere).
    2. Si es una solicitud explícita ('SOLICITAR X'): confirma la solicitud.
    3. Extrae el término en lenguaje natural (sin requerir palabras fijas como 'recomiendame').
    4. Busca en la tabla 'peliculas' con tolerancia a faltas de ortografía (nombre, descripción, géneros, actores, audio).
    5. Si no está en BD, busca en The Movie Database (TMDb) y si hay resultados, los presenta para solicitar.
    6. Si no es película: retorna None para que la IA atienda normalmente.
    """
    if not mensaje or not isinstance(mensaje, str):
        return None

    # Descartar de inmediato consultas operativas de internet, cobranzas o saludos secos
    if es_intencion_operativa_isp(mensaje):
        return None

    termino, genero, audio, es_solicitud, titulo_solic = extraer_termino_y_filtros(mensaje)

    # 1. Si el usuario está solicitando formalmente una película
    if es_solicitud and titulo_solic:
        return (
            f"🎬 ¡Excelente! Hemos registrado tu solicitud para agregar *\"{titulo_solic}\"* al catálogo de OPSATV.\n\n"
            "📥 Nuestro equipo técnico y de contenidos revisará la disponibilidad para subirla a la plataforma a la brevedad posible. "
            "¡Muchas gracias por ayudarnos a enriquecer tu experiencia de entretenimiento! 🍿📺"
        )

    # Si no quedó término, ni género, ni audio, no es una consulta válida de películas
    if not termino and not genero and not audio:
        return None

    # 2. Búsqueda en la tabla 'peliculas' de la base de datos
    peliculas_bd = buscar_peliculas_en_bd(
        db=db,
        termino=termino,
        genero=genero,
        audio=audio,
        limit=3
    )

    # Si se encontró en la BD local de OPSATV, retornar inmediatamente
    if peliculas_bd:
        return formatear_respuesta_whatsapp(
            peliculas_bd=peliculas_bd,
            peliculas_tmdb=[],
            termino=termino or (genero or ""),
            genero=genero
        )

    # 3. Si NO existe en la base de datos, buscar en The Movie Database (TMDb)
    # Solo buscar en TMDb si el término tiene longitud suficiente para ser un título o si es un género
    termino_para_tmdb = termino if (termino and len(termino) >= 2) else genero
    if not termino_para_tmdb:
        return None

    peliculas_tmdb = buscar_en_tmdb(termino_para_tmdb, limit=3)

    if peliculas_tmdb:
        return formatear_respuesta_whatsapp(
            peliculas_bd=[],
            peliculas_tmdb=peliculas_tmdb,
            termino=termino or (genero or ""),
            genero=genero
        )

    # Si no se encontró ni en BD ni en TMDb, retornar None para que la IA general atienda al usuario
    return None
