"""
Paquete ai de OPSATEL.
Contiene el asistente SAM, lógica conversacional, prompts de sistema y herramientas de IA.
"""
from .system_prompt import SYSTEM_PROMPT
from .ai_tools import (
    TOOLS_SCHEMA,
    ejecutar_herramienta,
    consultar_cliente_por_telefono,
    verificar_conexion_y_potencia,
    crear_ticket_soporte,
    consultar_planes_internet,
    crear_orden_instalacion_hoja_ruta,
    reiniciar_ont,
)
from .chatbot_service import (
    procesar_mensaje_con_herramientas,
    resolver_identidad_whatsapp,
    obtener_cliente_db_seguro,
)
