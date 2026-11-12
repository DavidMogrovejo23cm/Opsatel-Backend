from pydantic import BaseModel
from typing import Optional, List, Dict, Union, Any


class WhatsAppWebhookPayload(BaseModel):
    numero: str
    mensaje: str
    nombre: Optional[str] = None
    jid_original: Optional[str] = None
    url_archivo: Optional[str] = None
    nombre_archivo: Optional[str] = None
    ruta_archivo: Optional[str] = None
    mimetype: Optional[str] = None
    tamano_bytes: Optional[int] = None
    es_documento_valido: Optional[bool] = None
    es_invalido: Optional[bool] = None
    ya_notificado_cliente: Optional[bool] = None


class EnviarMensajeChatPayload(BaseModel):
    mensaje: str


class VincularClienteChatPayload(BaseModel):
    cliente_id: int
