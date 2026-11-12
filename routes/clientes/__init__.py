"""
@file __init__.py
@description Paquete modular de Clientes para Opsatel-Backend.
Desacopla la lógica en componentes:
- utils: formateo, cálculos de saldo, auto-corrección de formatos y reactivación
- crud: listado, creación, edición general/técnica/admin y eliminación de clientes
- pagos: registro, confirmación y anulación de pagos, facturación mensual y cierre de mes
- network: cálculo de parámetros GPON, interacción con OLT y MikroTik, migración
- media: almacenamiento y optimización de fotos de cédula, fachada y equipos
- reports: generación de reportes mensuales en Excel y arqueo de clientes
- import_export: carga masiva de Excel y exportación completa de base de datos
"""
from fastapi import APIRouter

# Re-exportar utilidades y funciones requeridas externamente por main.py, whatsapp.py, scheduler.py
from .utils import (
    PLAN_PRICES,
    is_nodo_sayausi,
    try_float,
    clean_int_string_value,
    clean_existing_database_formats,
    auto_fix_initial_balances,
    sync_cliente_balances,
    verificar_y_reactivar_cliente_por_pago_completo,
    invalidate_stats_cache
)
from .pagos import procesar_facturacion_global

# Sub-routers de cada componente
from .import_export import router as import_export_router
from .reports import router as reports_router
from .pagos import router as pagos_router
from .network import router as network_router
from .media import router as media_router
from .crud import router as crud_router

# Router principal expuesto para main.py (con el prefijo /clientes intacto)
router = APIRouter(prefix="/clientes", tags=["clientes"])

# El orden de inclusión garantiza que las rutas fijas (ej. /test-db, /descargar-completo, /pagos/historial, /pendientes-count)
# sean evaluadas antes de las rutas con comodines dinámicos (/{id}, /{id}/pagar, etc.)
router.include_router(import_export_router)
router.include_router(reports_router)
router.include_router(pagos_router)
router.include_router(network_router)
router.include_router(media_router)
router.include_router(crud_router)

__all__ = [
    "router",
    "clean_existing_database_formats",
    "sync_cliente_balances",
    "verificar_y_reactivar_cliente_por_pago_completo",
    "procesar_facturacion_global",
    "auto_fix_initial_balances",
    "is_nodo_sayausi",
    "try_float",
    "clean_int_string_value",
    "PLAN_PRICES",
    "invalidate_stats_cache"
]
