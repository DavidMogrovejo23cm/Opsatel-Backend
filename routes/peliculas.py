"""
Rutas API para Consulta y Búsqueda de Películas y Series (OMDb API / OPSATV).
Permite consultar información en tiempo real para el catálogo de entretenimiento
y para herramientas externas/dashboard.
"""

from fastapi import APIRouter, Query, HTTPException
from typing import Optional, Dict, Any
from services.omdb_service import consultar_pelicula, buscar_peliculas, obtener_por_imdb_id

router = APIRouter(prefix="/peliculas", tags=["peliculas"])


@router.get("/detalle")
def obtener_detalle_pelicula(
    titulo: str = Query(..., description="Nombre o título de la película o serie"),
    anio: Optional[str] = Query(None, description="Año opcional de lanzamiento"),
    tipo: Optional[str] = Query(None, description="movie, series o episode")
) -> Dict[str, Any]:
    """Obtiene la ficha técnica completa de una película o serie dada su denominación."""
    res = consultar_pelicula(titulo=titulo, anio=anio, tipo=tipo)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("mensaje", "Error en la consulta."))
    return res


@router.get("/buscar")
def buscar_listado_peliculas(
    q: str = Query(..., description="Término de búsqueda (ej: Marvel, Batman, Star Wars)"),
    anio: Optional[str] = Query(None, description="Año opcional"),
    tipo: Optional[str] = Query(None, description="movie, series o episode"),
    pagina: int = Query(1, ge=1, description="Número de página")
) -> Dict[str, Any]:
    """Busca títulos que coincidan con la palabra clave proporcionada."""
    try:
        p_num = int(getattr(pagina, "default", pagina)) if not isinstance(pagina, int) else pagina
    except Exception:
        p_num = 1
    res = buscar_peliculas(query=q, anio=anio, tipo=tipo, pagina=p_num)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("mensaje", "Error en la búsqueda."))
    return res


@router.get("/id/{imdb_id}")
def obtener_por_id_imdb(
    imdb_id: str
) -> Dict[str, Any]:
    """Obtiene el detalle de una película o serie mediante su identificador único de IMDb (ej: tt1375666)."""
    res = obtener_por_imdb_id(imdb_id=imdb_id)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("mensaje", "Error en la consulta."))
    return res
