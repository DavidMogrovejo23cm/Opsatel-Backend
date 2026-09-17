"""
Servicio de Integración con OMDb API (Open Movie Database) para Opsatel.
Permite consultar información en tiempo real de películas y series (título, año,
género, director, actores, sinopsis, poster y calificaciones) para el catálogo de OPSATV
y el asistente inteligente SAM.
"""

import os
import json
import logging
import urllib.request
import urllib.parse
from typing import Dict, Any, Optional, List

logger = logging.getLogger("opsatel.omdb_service")

# Clave de API provista para OMDb API
OMDB_API_KEY = os.getenv("OMDB_API_KEY", "c7c5f35f").strip()
OMDB_BASE_URL = "http://www.omdbapi.com/"


def _hacer_peticion_omdb(params: Dict[str, str], timeout: float = 8.0) -> Dict[str, Any]:
    """Realiza una petición HTTP GET segura a OMDb API con manejo de timeout y errores."""
    params["apikey"] = OMDB_API_KEY
    url = f"{OMDB_BASE_URL}?{urllib.parse.urlencode(params)}"
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Opsatel-Entertainment/1.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status == 200:
                raw = response.read().decode("utf-8")
                data = json.loads(raw)
                return data
            else:
                logger.warning(f"[OMDb] Respuesta HTTP {response.status} de OMDb API")
                return {"Response": "False", "Error": f"HTTP {response.status}"}
    except Exception as e:
        logger.error(f"[OMDb] Error conectando con OMDb API ({url}): {e}")
        return {"Response": "False", "Error": str(e)}


def consultar_pelicula(
    titulo: str,
    anio: Optional[str] = None,
    tipo: Optional[str] = None,
    plot: str = "short"
) -> Dict[str, Any]:
    """
    Busca una película o serie específica por título exacto o aproximado.
    
    Args:
        titulo: Nombre de la película/serie (ej: 'Inception', 'Breaking Bad', 'Gladiador').
        anio: Año de estreno opcional (ej: '2010').
        tipo: 'movie', 'series' o 'episode'.
        plot: 'short' para sinopsis concisa o 'full' para extendida.
        
    Returns:
        Diccionario normalizado con la información de la película.
    """
    if not titulo or not titulo.strip():
        return {
            "success": False,
            "encontrado": False,
            "mensaje": "Debe proporcionar un título para buscar."
        }

    params = {
        "t": titulo.strip(),
        "plot": plot
    }
    if anio and str(anio).strip():
        params["y"] = str(anio).strip()
    if tipo and str(tipo).strip() in ["movie", "series", "episode"]:
        params["type"] = str(tipo).strip()

    data = _hacer_peticion_omdb(params)

    if data.get("Response") == "True":
        return {
            "success": True,
            "encontrado": True,
            "imdb_id": data.get("imdbID"),
            "titulo": data.get("Title"),
            "anio": data.get("Year"),
            "clasificacion": data.get("Rated"),
            "estreno": data.get("Released"),
            "duracion": data.get("Runtime"),
            "genero": data.get("Genre"),
            "director": data.get("Director"),
            "escritor": data.get("Writer"),
            "actores": data.get("Actors"),
            "sinopsis": data.get("Plot"),
            "idioma": data.get("Language"),
            "pais": data.get("Country"),
            "premios": data.get("Awards"),
            "poster": data.get("Poster"),
            "calificacion_imdb": data.get("imdbRating"),
            "votos_imdb": data.get("imdbVotes"),
            "tipo": data.get("Type")
        }
    else:
        # Si falló la búsqueda exacta por título, intentar una búsqueda general con '?s='
        busqueda = buscar_peliculas(query=titulo, anio=anio, tipo=tipo)
        if busqueda.get("success") and busqueda.get("total_resultados", 0) > 0:
            primer_item = busqueda["resultados"][0]
            # Obtener el detalle completo del primer resultado encontrado
            return obtener_por_imdb_id(primer_item["imdb_id"])

        return {
            "success": True,
            "encontrado": False,
            "titulo_buscado": titulo,
            "mensaje": f"No se encontró ninguna película o serie con el título '{titulo}' en OMDb API."
        }


def buscar_peliculas(
    query: str,
    anio: Optional[str] = None,
    tipo: Optional[str] = None,
    pagina: int = 1
) -> Dict[str, Any]:
    """
    Busca una lista de películas o series coincidentes con una palabra clave.
    
    Args:
        query: Término de búsqueda (ej: 'Batman', 'Spider-Man', 'Avatar').
        anio: Año de estreno opcional.
        tipo: 'movie', 'series', o 'episode'.
        pagina: Página de resultados (por defecto 1).
    """
    if not query or not query.strip():
        return {
            "success": False,
            "total_resultados": 0,
            "resultados": [],
            "mensaje": "Debe ingresar un término de búsqueda."
        }

    try:
        page_num = max(1, int(pagina))
    except (TypeError, ValueError):
        page_num = 1

    params = {
        "s": query.strip(),
        "page": str(page_num)
    }
    if anio and str(anio).strip():
        params["y"] = str(anio).strip()
    if tipo and str(tipo).strip() in ["movie", "series", "episode"]:
        params["type"] = str(tipo).strip()

    data = _hacer_peticion_omdb(params)

    if data.get("Response") == "True":
        resultados_raw = data.get("Search", [])
        resultados_limpios = []
        for item in resultados_raw:
            resultados_limpios.append({
                "imdb_id": item.get("imdbID"),
                "titulo": item.get("Title"),
                "anio": item.get("Year"),
                "tipo": item.get("Type"),
                "poster": item.get("Poster")
            })
        return {
            "success": True,
            "total_resultados": int(data.get("totalResults", len(resultados_limpios))),
            "resultados": resultados_limpios
        }
    else:
        return {
            "success": True,
            "total_resultados": 0,
            "resultados": [],
            "mensaje": data.get("Error", "No se encontraron coincidencias.")
        }


def obtener_por_imdb_id(imdb_id: str, plot: str = "short") -> Dict[str, Any]:
    """Obtiene el detalle completo de una película o serie dado su código IMDb (ej: 'tt1375666')."""
    if not imdb_id or not imdb_id.strip():
        return {"success": False, "encontrado": False, "mensaje": "ID de IMDb no provisto."}

    data = _hacer_peticion_omdb({"i": imdb_id.strip(), "plot": plot})

    if data.get("Response") == "True":
        return {
            "success": True,
            "encontrado": True,
            "imdb_id": data.get("imdbID"),
            "titulo": data.get("Title"),
            "anio": data.get("Year"),
            "clasificacion": data.get("Rated"),
            "estreno": data.get("Released"),
            "duracion": data.get("Runtime"),
            "genero": data.get("Genre"),
            "director": data.get("Director"),
            "escritor": data.get("Writer"),
            "actores": data.get("Actors"),
            "sinopsis": data.get("Plot"),
            "idioma": data.get("Language"),
            "pais": data.get("Country"),
            "premios": data.get("Awards"),
            "poster": data.get("Poster"),
            "calificacion_imdb": data.get("imdbRating"),
            "votos_imdb": data.get("imdbVotes"),
            "tipo": data.get("Type")
        }
    else:
        return {
            "success": True,
            "encontrado": False,
            "imdb_id": imdb_id,
            "mensaje": f"No se encontró información para el ID {imdb_id}."
        }


def formatear_para_whatsapp(datos: Dict[str, Any]) -> str:
    """Formatea la información de una película o serie de forma amigable y atractiva para WhatsApp."""
    if not datos.get("encontrado"):
        return datos.get("mensaje", "No se encontró información sobre la producción solicitada.")

    titulo = datos.get("titulo", "Película")
    anio = datos.get("anio", "")
    genero = datos.get("genero", "Varios")
    duracion = datos.get("duracion", "")
    rating = datos.get("calificacion_imdb", "")
    director = datos.get("director", "")
    actores = datos.get("actores", "")
    sinopsis = datos.get("sinopsis", "")

    lineas = [f"🎬 *{titulo}* ({anio}) — _{genero}_"]
    
    detalles = []
    if duracion and duracion != "N/A":
        detalles.append(f"⏱️ {duracion}")
    if rating and rating != "N/A":
        detalles.append(f"⭐ IMDb: {rating}/10")
    if detalles:
        lineas.append(" | ".join(detalles))

    if director and director != "N/A":
        lineas.append(f"🎬 *Director:* {director}")
    if actores and actores != "N/A":
        lineas.append(f"🎭 *Reparto:* {actores}")

    if sinopsis and sinopsis != "N/A":
        lineas.append(f"\n📖 *Sinopsis:*\n{sinopsis}")

    lineas.append("\n📺 _Disponible para disfrutar en tu servicio de entretenimiento OPSATV._")
    return "\n".join(lineas)
