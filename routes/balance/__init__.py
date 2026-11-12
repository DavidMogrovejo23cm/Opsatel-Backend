from fastapi import APIRouter

# Importar sub-routers modulares
from .egresos import router as egresos_router
from .proyectos import router as proyectos_router
from .colchon import router as colchon_router
from .gastos_fijos import router as gastos_fijos_router
from .movimientos import router as movimientos_router
from .arcotel import router as arcotel_router
from .reportes import router as reportes_router

# Re-exportar funciones y utilidades para retrocompatibilidad con otros módulos (ej. routes/clientes/reports.py)
from .utils import (
    normalizar_parroquia,
    asegurar_columnas_egresos,
    sincronizar_gastos_fijos_mes,
    try_float_val,
    try_int_val
)
from .arcotel import (
    construir_datos_arcotel,
    guardar_excel_arcotel_congelado,
    generar_data_tarifas,
    MAP_COMERCIAL_TARIFAS
)
from .excel_generator import (
    generar_excel_balance_anual,
    generar_excel_balance_mensual
)
from .reportes import (
    reporte_mensual,
    reporte_plataforma,
    reporte_anual,
    exportar_reporte_anual_excel,
    historial_clientes,
    exportar_reporte_excel
)

# Router principal de Balance
router = APIRouter(prefix="/balance", tags=["balance"])

# Montar sub-routers en orden seguro
router.include_router(egresos_router)
router.include_router(gastos_fijos_router)
router.include_router(colchon_router)
router.include_router(proyectos_router)
router.include_router(movimientos_router)
router.include_router(arcotel_router)
router.include_router(reportes_router)

__all__ = [
    "router",
    "normalizar_parroquia",
    "asegurar_columnas_egresos",
    "sincronizar_gastos_fijos_mes",
    "try_float_val",
    "try_int_val",
    "construir_datos_arcotel",
    "guardar_excel_arcotel_congelado",
    "generar_data_tarifas",
    "MAP_COMERCIAL_TARIFAS",
    "generar_excel_balance_anual",
    "generar_excel_balance_mensual",
    "reporte_mensual",
    "reporte_plataforma",
    "reporte_anual",
    "exportar_reporte_anual_excel",
    "historial_clientes",
    "exportar_reporte_excel"
]
