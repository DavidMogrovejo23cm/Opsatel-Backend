"""
Paquete ai de OPSATEL.
Contiene el asistente SAM, lógica conversacional, prompts de sistema y herramientas de IA.
"""
from .system_prompt import SYSTEM_PROMPT
from .ai_tools import (
    TOOLS_SCHEMA,
    ejecutar_herramienta,
    consultar_estado_cliente,
    verificar_conexion_y_potencia,
    generar_ticket_soporte,
    consultar_planes_disponibles,
    crear_orden_instalacion_hoja_ruta,
    reiniciar_ont,
    consultar_cliente_por_telefono,
    crear_ticket_soporte,
    consultar_planes_internet,
)
from .chatbot_service import (
    procesar_mensaje_con_herramientas,
    resolver_identidad_whatsapp,
    obtener_cliente_db_seguro,
)
