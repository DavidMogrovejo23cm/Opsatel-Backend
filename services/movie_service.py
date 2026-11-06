"""
@file movie_service.py
@author David Mogrovejo dmogrovejo87@gmail.com
@copyright (c) 2026 David Mogrovejo. All Rights Reserved.
@notice Developed with AI assistance.

Servicio de Recomendación, Búsqueda y Solicitud de Películas para WhatsApp (OPSATV).
1. Filtra y limpia el mensaje del usuario para evitar errores en peticiones.
2. Consulta primero en la base de datos interna (tabla 'peliculas') guiándose en los
   campos: nombre, descripcion, generos, actores y audio.
3. Si no existe en la base de datos, busca en The Movie Database (TMDb) con fallback a OMDb
   y presenta los resultados como sugerencias para solicitar su inclusión en OPSATV.
"""

import os
import re
import json
import logging
import urllib.request
import urllib.parse
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
import models

logger = logging.getLogger("opsatel.movie_service")

# Clave y URLs de The Movie Database (TMDb API v3)
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "cfe422613b250f702980a3bbf9e90716").strip()
TMDB_BASE_URL = "https://api.themoviedb.org/3"

# Géneros comunes para clasificación y búsqueda
GENEROS_KEYWORDS = {
    "accion": ["accion", "acción", "action", "balazos", "peleas"],
    "comedia": ["comedia", "comedy", "risa", "divertida", "graciosa", "chistosa"],
    "terror": ["terror", "miedo", "horror", "paranormal", "escalofriante", "espanto"],
    "drama": ["drama", "dramatica", "dramática", "emotiva", "sentimental"],
    "suspenso": ["suspenso", "thriller", "misterio", "intriga"],
    "romance": ["romance", "romantica", "romántica", "amor", "pareja"],
    "ciencia ficcion": ["ciencia ficcion", "ciencia ficción", "sci-fi", "scifi", "espacio", "futuro", "alien"],
    "aventura": ["aventura", "aventuras", "adventure"],
    "animacion": ["animacion", "animación", "animada", "animadas", "infantil", "infantiles", "dibujos", "niños", "caricatura"],
    "fantasia": ["fantasia", "fantasía", "magia", "fantasy"],
    "crimen": ["crimen", "policial", "mafia", "gangster", "detective"],
    "documental": ["documental", "documentales", "historia real"]
}

# Audios comunes
AUDIOS_KEYWORDS = {
    "latino": ["latino", "español latino", "audio latino"],
    "castellano": ["castellano", "españa", "español de españa"],
    "ingles": ["ingles", "inglés", "subtitulada", "subtitulado", "subtitulos", "subtítulos", "idioma original"],
    "dual": ["dual", "multiaudio"]
}

# Palabras de descarte para limpiar el término de búsqueda
NOISE_WORDS = [
    "hola", "buenas", "buenos dias", "buenas tardes", "buenas noches", "saludos", "amigo", "amiga",
    "por favor", "porfa", "favor", "sam", "opsatel", "opsatv",
    "me gustaria", "me gustaría", "quisiera", "quiero", "puedo", "podrias", "podrías", "deseo",
    "saber si tienen", "tienen", "tienes", "tienen la", "tienes la", "hay la", "hay", "esta la", "está la",
    "esta disponible", "está disponible", "disponible", "disponibles",
    "me recomiendas", "recomiendame", "recomiéndame", "recomienda", "recomendame", "recomendación",
    "recomendacion", "recomienden", "sugiereme", "sugiéreme", "sugerencia", "sugerencias",
    "una pelicula de", "una película de", "una pelicula", "una película", "pelicula de", "película de",
    "pelicula", "película", "peliculas", "películas", "peli de", "peli", "pelis", "film", "films",
    "cine", "en cine", "ver", "mirar", "catalogo", "catálogo", "en", "de", "con", "el", "la", "los", "las", "un", "una"
]


def filtrar_mensaje_pelicula(mensaje: str) -> Dict[str, Any]:
    """
    Filtra y sanitiza el mensaje del usuario para:
    1. Detectar si pregunta por películas/series o solicita una.
    2. Extraer de forma segura el término clave de búsqueda, género y audio.
    3. Evitar caracteres peligrosos o consultas vacías hacia la BD y APIs.
    """
    resultado = {
        "es_consulta": False,
        "es_solicitud": False,
        "termino_busqueda": "",
        "genero_detectado": None,
        "audio_detectado": None,
        "solicitud_titulo": ""
    }

    if not mensaje or not isinstance(mensaje, str):
        return resultado

    texto = mensaje.strip()
    texto_lower = texto.lower()

    # 1. Detectar si el usuario está solicitando formalmente una película
    # Ej: "Solicitar Gladiator", "Quiero solicitar la pelicula Matrix"
    m_solicitud = re.search(r'(?:solicitar|quiero solicitar|por favor agregar|agreguen|añadir)\s+(?:la\s+pelicula\s+|la\s+peli\s+|la\s+película\s+)?([a-zA-Z0-9\s:_-]{2,60})', texto, re.IGNORECASE)
    if m_solicitud:
        titulo_solic = m_solicitud.group(1).strip(" .!,;¿?\"'")
        if len(titulo_solic) >= 2:
            resultado["es_consulta"] = True
            resultado["es_solicitud"] = True
            resultado["solicitud_titulo"] = titulo_solic
            resultado["termino_busqueda"] = titulo_solic
            return resultado

    # 2. Palabras clave que indican que la persona está hablando de películas o series
    triggers_peliculas = [
        "pelicula", "película", "peliculas", "películas", "peli", "pelis",
        "cine", "film", "films", "opsatv", "estreno", "estrenos"
    ]
    triggers_accion = [
        "recomiendame", "recomiéndame", "recomienda", "recomendacion", "recomendación",
        "sugiereme", "sugiéreme", "sugerencia", "que ver", "qué ver", "ver hoy"
    ]

    tiene_trigger_pelicula = any(tp in texto_lower for tp in triggers_peliculas)
    tiene_trigger_accion = any(ta in texto_lower for ta in triggers_accion)

    # Detectar género mencionado
    genero_encontrado = None
    for gen_nombre, variantes in GENEROS_KEYWORDS.items():
        if any(re.search(r'\b' + re.escape(v) + r'\b', texto_lower) for v in variantes):
            genero_encontrado = gen_nombre
            break

    # Detectar audio mencionado
    audio_encontrado = None
    for aud_nombre, variantes in AUDIOS_KEYWORDS.items():
        if any(re.search(r'\b' + re.escape(v) + r'\b', texto_lower) for v in variantes):
            audio_encontrado = aud_nombre
            break

    # Si menciona trigger de película, o pide recomendación + género, es consulta de películas
    if tiene_trigger_pelicula or (tiene_trigger_accion and (genero_encontrado or "ver" in texto_lower)):
        resultado["es_consulta"] = True
    elif any(t in texto_lower for t in ["de que trata", "de qué trata", "sinopsis de"]):
        resultado["es_consulta"] = True
    else:
        return resultado

    resultado["genero_detectado"] = genero_encontrado
    resultado["audio_detectado"] = audio_encontrado

    # 3. Limpieza profunda y sanitización del término de búsqueda
    # Remover caracteres extraños, símbolos de puntuación y emojis
    limpio = re.sub(r'[^\w\s\d]', ' ', texto_lower)
    limpio = re.sub(r'\s+', ' ', limpio).strip()

    # Extraer el título específico si viene precedido de patrones como:
    # "tienen la pelicula X", "esta la peli X", "sinopsis de X", "info de X", "busca X"
    patrones_titulo = [
        r'(?:tienen|tienes|esta|está|hay|busco|quiero ver|ver|sinopsis de|de que trata|de qué trata|info de|informacion de)\s+(?:la\s+pelicula\s+|la\s+película\s+|la\s+peli\s+|el\s+film\s+)?([a-z0-9\s]{2,40})',
        r'(?:pelicula|película|peli)\s+([a-z0-9\s]{2,40})'
    ]
    candidato_titulo = None
    for pat in patrones_titulo:
        match = re.search(pat, limpio)
        if match:
            posible = match.group(1).strip()
            # Si el candidato no es solo una palabra vacía o el género
            if posible and posible not in GENEROS_KEYWORDS and len(posible) >= 2:
                candidato_titulo = posible
                break

    # Si se extrajo candidato_titulo, limpiarlo de conectores iniciales/finales
    if candidato_titulo:
        termino = candidato_titulo
    else:
        # Remover palabras de descarte
        palabras = limpio.split()
        palabras_filtradas = [p for p in palabras if p not in NOISE_WORDS and len(p) > 1]
        termino = " ".join(palabras_filtradas).strip()

    # Limpiar conectores comunes al inicio o final del término
    termino = re.sub(r'^(?:de|con|en|del|la|el|los|las|un|una|peli|pelicula|película)\s+', '', termino, flags=re.IGNORECASE)
    termino = re.sub(r'\s+(?:de|con|en|del|la|el|los|las|un|una)$', '', termino, flags=re.IGNORECASE).strip()

    # Si el término coincide exactamente con el género detectado o quedó en "accion", "terror", etc.
    if genero_encontrado and (not termino or termino == genero_encontrado or termino in GENEROS_KEYWORDS.get(genero_encontrado, [])):
        termino = ""

    # Si el término es solo el audio
    if audio_encontrado and termino == audio_encontrado:
        termino = ""

    resultado["termino_busqueda"] = termino[:60].strip()
    return resultado


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
    limit: int = 4
) -> List[Dict[str, Any]]:
    """
    Busca películas en la tabla local 'peliculas' de la base de datos.
    Se guía en los campos: nombre, descripcion, generos, actores y audio.
    """
    asegurar_tabla_peliculas(db)
    resultados = []
    
    try:
        query = db.query(models.Pelicula)
        condiciones = []

        # 1. Si hay un término de búsqueda (ej: nombre, palabra clave en descripción, actor)
        if termino and len(termino) >= 2:
            term_wild = f"%{termino}%"
            condiciones.extend([
                models.Pelicula.nombre.ilike(term_wild),
                models.Pelicula.descripcion.ilike(term_wild),
                models.Pelicula.generos.ilike(term_wild),
                models.Pelicula.actores.ilike(term_wild),
                models.Pelicula.audio.ilike(term_wild)
            ])

        # 2. Si hay género específico detectado, buscar con todas sus variantes ortográficas (con y sin tilde)
        if genero:
            variantes_gen = GENEROS_KEYWORDS.get(genero, [genero])
            conds_gen = []
            for v in variantes_gen:
                v_wild = f"%{v}%"
                conds_gen.extend([
                    models.Pelicula.generos.ilike(v_wild),
                    models.Pelicula.descripcion.ilike(v_wild),
                    models.Pelicula.nombre.ilike(v_wild)
                ])
            if conds_gen:
                query = query.filter(or_(*conds_gen))

        # 3. Si hay audio específico detectado, buscar con variantes
        if audio:
            variantes_aud = AUDIOS_KEYWORDS.get(audio, [audio])
            conds_aud = [models.Pelicula.audio.ilike(f"%{v}%") for v in variantes_aud]
            if conds_aud:
                query = query.filter(or_(*conds_aud))

        # Si tenemos condiciones por término, aplicarlas con OR
        if condiciones:
            query = query.filter(or_(*condiciones))

        peliculas_db = query.limit(limit).all()

        for p in peliculas_db:
            resultados.append({
                "id": p.id,
                "nombre": p.nombre,
                "descripcion": p.descripcion or "Disponible en catálogo.",
                "generos": p.generos or "General",
                "actores": p.actores or "Varios",
                "audio": p.audio or "Español Latino",
                "anio": getattr(p, "anio", None) or "",
                "calificacion": getattr(p, "calificacion", None) or "",
                "poster": getattr(p, "poster", None) or ""
            })

    except Exception as e:
        logger.error(f"[Movie Service] Error consultando tabla 'peliculas' en BD: {e}")

    return resultados


def buscar_en_tmdb(query_str: str, limit: int = 3) -> List[Dict[str, Any]]:
    """
    Busca películas en The Movie Database (TMDb API v3).
    Si TMDb falla o no devuelve resultados, realiza fallback automático a OMDb API.
    """
    if not query_str or len(query_str.strip()) < 2:
        return []

    query_clean = query_str.strip()
    resultados = []

    # 1. Consulta directa a The Movie Database (TMDb)
    try:
        encoded_q = urllib.parse.quote(query_clean)
        url = (
            f"{TMDB_BASE_URL}/search/movie?"
            f"api_key={TMDB_API_KEY}&query={encoded_q}&language=es-MX&include_adult=false&page=1"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Opsatel-Entertainment/1.0"})
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            if resp.status == 200:
                raw = resp.read().decode("utf-8")
                data = json.loads(raw)
                for item in data.get("results", [])[:limit]:
                    titulo = item.get("title") or item.get("original_title") or ""
                    release_date = item.get("release_date") or ""
                    anio = release_date.split("-")[0] if release_date else ""
                    overview = item.get("overview") or "Sinopsis no disponible en español actualmente."
                    vote = item.get("vote_average")
                    vote_str = f"{vote:.1f}" if vote else "N/A"
                    poster_path = item.get("poster_path")
                    poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None

                    resultados.append({
                        "titulo": titulo,
                        "anio": anio,
                        "sinopsis": overview[:220] + ("..." if len(overview) > 220 else ""),
                        "calificacion": vote_str,
                        "poster": poster_url,
                        "fuente": "TMDb"
                    })
    except Exception as e:
        logger.warning(f"[Movie Service] Falló consulta a TMDb ({e}). Intentando fallback a OMDb...")

    # 2. Fallback a OMDb API si TMDb no arrojó resultados
    if not resultados:
        try:
            from services.omdb_service import consultar_pelicula, buscar_peliculas
            # Probar búsqueda puntual
            data_omdb = consultar_pelicula(titulo=query_clean)
            if data_omdb.get("encontrado"):
                resultados.append({
                    "titulo": data_omdb.get("titulo"),
                    "anio": data_omdb.get("anio"),
                    "sinopsis": (data_omdb.get("sinopsis") or "")[:220],
                    "calificacion": data_omdb.get("calificacion_imdb") or "N/A",
                    "genero": data_omdb.get("genero"),
                    "actores": data_omdb.get("actores"),
                    "poster": data_omdb.get("poster"),
                    "fuente": "OMDb"
                })
            else:
                busq = buscar_peliculas(query=query_clean)
                for item in busq.get("peliculas", [])[:limit]:
                    resultados.append({
                        "titulo": item.get("titulo"),
                        "anio": item.get("anio"),
                        "sinopsis": "Película popular disponible para solicitud.",
                        "calificacion": "N/A",
                        "poster": item.get("poster"),
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
    Construye un mensaje limpio, amigable y estructurado para WhatsApp:
    - Si existe en la BD: Muestra la información disponible en OPSATV (nombre, géneros, audio, actores, etc.).
    - Si NO existe en BD: Muestra los resultados de The Movie Database como sugerencias para solicitarla.
    """
    # CASO 1: ENCONTRADAS EN LA BASE DE DATOS LOCAL ('peliculas')
    if peliculas_bd:
        msg = "🍿 *Películas disponibles en tu catálogo OPSATV* 🎬\n\n"
        if genero:
            msg = f"🍿 *Películas de {genero.upper()} en tu catálogo OPSATV* 🎬\n\n"

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

    # CASO 2: NO EXISTEN EN LA BASE DE DATOS LOCAL -> SUGERENCIA DESDE THE MOVIE DATABASE (TMDb)
    if peliculas_tmdb:
        termino_display = termino.capitalize() if termino else "la película solicitada"
        msg = (
            f"🎬 No encontramos *\"{termino_display}\"* directamente en el catálogo activo de OPSATV, "
            f"pero encontramos estas coincidencias en *The Movie Database (TMDb)*:\n\n"
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

    # CASO 3: NADA ENCONTRADO NI EN BD NI EN TMDB
    termino_display = f" \"{termino}\"" if termino else ""
    return (
        f"🎬 No logramos encontrar coincidencias para{termino_display} en nuestro catálogo ni en The Movie Database.\n\n"
        "💡 *Prueba lo siguiente:*\n"
        "• Escribe el nombre exacto de la película (ej: *Gladiator*, *Inception*, *Avatar*).\n"
        "• O pide un género específico (ej: *Recomiéndame una película de acción*, *terror*, *comedia*).\n\n"
        "_¡Estamos a tu servicio en OPSATV!_ 📺🍿"
    )


def gestionar_consulta_peliculas(mensaje: str, db: Session) -> Optional[str]:
    """
    Función principal llamada ANTES de que interactúe la IA Groq en WhatsApp.
    1. Filtra y evalúa el mensaje.
    2. Si es una confirmación de solicitud: confirma el ingreso de la solicitud al cliente.
    3. Si es una consulta de películas:
       a. Busca en la tabla 'peliculas' (campos: nombre, descripcion, generos, actores, audio).
       b. Si no existe, continúa la búsqueda en The Movie Database (TMDb) como sugerencia para solicitar.
       c. Retorna el texto listo para enviar al cliente por WhatsApp.
    4. Si NO es consulta de películas, retorna None (para que siga el flujo normal de IA).
    """
    filtro = filtrar_mensaje_pelicula(mensaje)

    if not filtro["es_consulta"]:
        return None

    # Manejar solicitud directa de cliente
    if filtro["es_solicitud"]:
        titulo = filtro["solicitud_titulo"]
        return (
            f"🎬 ¡Excelente! Hemos registrado tu solicitud para agregar *\"{titulo}\"* al catálogo de OPSATV.\n\n"
            "📥 Nuestro equipo técnico y de contenidos revisará la disponibilidad para subirla a la plataforma a la brevedad posible. "
            "¡Muchas gracias por ayudarnos a enriquecer tu experiencia de entretenimiento! 🍿📺"
        )

    termino = filtro["termino_busqueda"]
    genero = filtro["genero_detectado"]
    audio = filtro["audio_detectado"]

    # 1. Búsqueda en Base de Datos local (tabla peliculas)
    peliculas_bd = buscar_peliculas_en_bd(
        db=db,
        termino=termino,
        genero=genero,
        audio=audio,
        limit=3
    )

    # 2. Si no se encontró en la BD local, buscar en The Movie Database (TMDb)
    peliculas_tmdb = []
    if not peliculas_bd:
        # Usar el término de búsqueda o género para consultar TMDb
        q_tmdb = termino if termino else (genero or "peliculas populares")
        peliculas_tmdb = buscar_en_tmdb(q_tmdb, limit=3)

    # 3. Formatear y retornar la respuesta
    return formatear_respuesta_whatsapp(
        peliculas_bd=peliculas_bd,
        peliculas_tmdb=peliculas_tmdb,
        termino=termino or (genero or ""),
        genero=genero
    )
