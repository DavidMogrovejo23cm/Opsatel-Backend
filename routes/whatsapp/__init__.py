from fastapi import APIRouter

# Importar sub-routers modulares
from .bridge import router as bridge_router
from .broadcast import router as broadcast_router
from .configuracion import router as configuracion_router
from .chat import router as chat_router
from .comprobantes import router as comprobantes_router
from .webhook import router as webhook_router

# Re-exportar utilidades y variables compartidas requeridas por main.py, scheduler.py y sam_bot_service.py
from .utils import (
    ECUADOR_TZ,
    CANCELLED_DIFUSIONES,
    GLOBAL_CANCEL_REQUESTED,
    personalizar_mensaje_cliente,
    remove_accents,
    registrar_mensaje_chat,
    obtener_info_contacto_bridge,
    extract_port_number,
    matches_puerto,
    _try_float_val,
    obtener_tarifa_plan_cliente,
    calcular_deuda_pendiente_cliente,
    buscar_cliente_por_telefono_comprobante
)
from .comprobantes import (
    asegurar_tabla_destinos_ocr,
    asegurar_tabla_comprobantes,
    evaluar_validacion_comprobante,
    revalidar_comprobantes_existentes_pendientes
)
from .schemas import (
    WhatsAppWebhookPayload,
    EnviarMensajeChatPayload,
    VincularClienteChatPayload
)

# Router principal de WhatsApp
router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])

# Montar sub-routers en orden
router.include_router(bridge_router)
router.include_router(configuracion_router)
router.include_router(broadcast_router)
router.include_router(chat_router)
router.include_router(comprobantes_router)
router.include_router(webhook_router)

__all__ = [
    "router",
    "ECUADOR_TZ",
    "CANCELLED_DIFUSIONES",
    "GLOBAL_CANCEL_REQUESTED",
    "personalizar_mensaje_cliente",
    "remove_accents",
    "registrar_mensaje_chat",
    "obtener_info_contacto_bridge",
    "extract_port_number",
    "matches_puerto",
    "_try_float_val",
    "obtener_tarifa_plan_cliente",
    "calcular_deuda_pendiente_cliente",
    "buscar_cliente_por_telefono_comprobante",
    "asegurar_tabla_destinos_ocr",
    "asegurar_tabla_comprobantes",
    "evaluar_validacion_comprobante",
    "revalidar_comprobantes_existentes_pendientes",
    "WhatsAppWebhookPayload",
    "EnviarMensajeChatPayload",
    "VincularClienteChatPayload"
]
