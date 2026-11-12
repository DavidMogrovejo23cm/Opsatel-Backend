"""
@file realtime.py
@author David Mogrovejo dmogrovejo87@gmail.com
@copyright (c) 2026 David Mogrovejo. All Rights Reserved.
@notice Developed with AI assistance.
@hash bf26ee033418d5dcd984ad8115334e7ce788cfb5d2bd456cf6e6ee21b877a762

OPSATEL - Rutas de Sincronización en Tiempo Real (SSE y Versiones)
==================================================================
Proporciona canales en vivo para que los navegadores conectados
reciban notificaciones instantáneas de actualización de datos.
"""

import asyncio
import json
import logging
from fastapi import APIRouter, Request, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any

from core.realtime import realtime_manager, notify_change

logger = logging.getLogger("opsatel.realtime_routes")

router = APIRouter(prefix="/realtime", tags=["Sincronización en Tiempo Real"])

class NotifyPayload(BaseModel):
    module: str
    action: Optional[str] = "update"
    extra: Optional[Dict[str, Any]] = None

@router.get("/version")
def get_realtime_versions():
    """
    Retorna las versiones actuales de todos los módulos.
    Ultra liviano (< 1ms), ideal para revalidación cuando la pestaña recupera foco.
    """
    return {
        "success": True,
        "versions": realtime_manager.get_versions(),
        "total_subscribers": realtime_manager.total_subscribers
    }

@router.get("/status")
def get_realtime_status():
    """Retorna estado y métricas de conexiones activas."""
    return {
        "active_clients": realtime_manager.total_subscribers,
        "versions": realtime_manager.get_versions()
    }

@router.post("/notify")
async def trigger_realtime_notification(payload: NotifyPayload):
    """
    Dispara manualmente una notificación de cambio hacia todos los clientes conectados.
    """
    await notify_change(payload.module, action=payload.action or "update", extra=payload.extra)
    return {
        "success": True,
        "notified_module": payload.module,
        "version": realtime_manager.get_versions().get(payload.module)
    }

@router.get("/stream")
async def realtime_stream(request: Request, client_id: Optional[str] = Query(None)):
    """
    Canal de Server-Sent Events (SSE).
    Mantiene la conexión abierta y transmite eventos de actualización a los clientes.
    """
    async def sse_generator():
        queue = await realtime_manager.subscribe()
        try:
            # 1. Enviar evento inicial de bienvenida con las versiones actuales
            initial_data = {
                "type": "INITIAL_STATE",
                "client_id": client_id,
                "versions": realtime_manager.get_versions()
            }
            yield f"data: {json.dumps(initial_data, ensure_ascii=False)}\n\n"

            # 2. Bucle de transmisión de eventos y latidos (heartbeats)
            while True:
                # Si el cliente canceló la petición o se cerró la pestaña, salir
                if await request.is_disconnected():
                    break

                try:
                    # Esperar evento de la cola con timeout de 15 segundos
                    event_data = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {event_data}\n\n"
                except asyncio.TimeoutError:
                    # Enviar ping/keep-alive para evitar desconexiones por proxy o NAT
                    yield ": ping\n\n"
                except asyncio.CancelledError:
                    break
        except Exception as e:
            logger.debug(f"Desconexión de cliente SSE ({client_id}): {e}")
        finally:
            realtime_manager.unsubscribe(queue)

    return StreamingResponse(
        sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no", # Desactiva buffering en Nginx
            "Access-Control-Allow-Origin": "*"
        }
    )
