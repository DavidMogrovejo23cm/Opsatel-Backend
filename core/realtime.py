"""
@file realtime.py
@author David Mogrovejo dmogrovejo87@gmail.com
@copyright (c) 2026 David Mogrovejo. All Rights Reserved.
@notice Developed with AI assistance.
@hash bf26ee033418d5dcd984ad8115334e7ce788cfb5d2bd456cf6e6ee21b877a762

OPSATEL - Gestor de Sincronización y Notificaciones en Tiempo Real
==================================================================
Gestiona eventos de sincronización para clientes conectados vía Server-Sent Events (SSE).
Permite que cualquier cambio en la base de datos o módulos del sistema se refleje
instantáneamente en las pantallas de todos los usuarios sin necesidad de recargar la página (F5).
"""

import asyncio
import json
import logging
import time
from typing import Dict, Set, Optional, Any

logger = logging.getLogger("opsatel.realtime")

class RealtimeManager:
    """Administrador centralizado de eventos y difusión en tiempo real."""
    
    MODULOS_VALIDOS = {
        "clientes",
        "balance",
        "caja",
        "hoja_ruta",
        "tickets",
        "callcenter",
        "whatsapp",
        "extras",
        "configuraciones",
        "olt",
        "libreqos",
        "asistencia",
        "all"
    }

    def __init__(self):
        self._versions: Dict[str, int] = {mod: 1 for mod in self.MODULOS_VALIDOS}
        self._timestamps: Dict[str, float] = {mod: time.time() for mod in self.MODULOS_VALIDOS}
        self._subscribers: Set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()

    def get_versions(self) -> Dict[str, Any]:
        """Retorna las versiones actuales y timestamps de cada módulo."""
        return {
            mod: {
                "version": self._versions.get(mod, 1),
                "timestamp": self._timestamps.get(mod, 0.0)
            }
            for mod in self.MODULOS_VALIDOS
        }

    async def notify_change(self, module: str, action: str = "update", extra: Optional[Dict[str, Any]] = None):
        """
        Notifica a todos los clientes conectados que hubo un cambio en un módulo.
        Incrementa la versión local y envía el evento vía SSE.
        """
        mod_key = module.lower()
        if mod_key not in self.MODULOS_VALIDOS:
            mod_key = "all"

        now = time.time()
        self._versions[mod_key] = self._versions.get(mod_key, 1) + 1
        self._timestamps[mod_key] = now
        
        # También se actualiza la versión global 'all'
        if mod_key != "all":
            self._versions["all"] = self._versions.get("all", 1) + 1
            self._timestamps["all"] = now

        payload = {
            "type": "MODULE_UPDATE",
            "module": mod_key,
            "action": action,
            "version": self._versions[mod_key],
            "timestamp": now,
            "extra": extra or {}
        }
        json_data = json.dumps(payload, ensure_ascii=False)

        # Difundir a todas las colas de suscriptores activos
        muertos = set()
        for queue in list(self._subscribers):
            try:
                # Si la cola está llena, descartar eventos antiguos para evitar bloqueo
                if queue.full():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                queue.put_nowait(json_data)
            except Exception:
                muertos.add(queue)

        if muertos:
            self._subscribers.difference_update(muertos)

    def notify_change_sync(self, module: str, action: str = "update", extra: Optional[Dict[str, Any]] = None):
        """Versión síncrona/segura para ser invocada desde threads o funciones síncronas."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.run_coroutine_threadsafe(self.notify_change(module, action, extra), loop)
            else:
                loop.run_until_complete(self.notify_change(module, action, extra))
        except RuntimeError:
            # Si no hay loop en el thread actual, crear uno puntual
            new_loop = asyncio.new_event_loop()
            new_loop.run_until_complete(self.notify_change(module, action, extra))
            new_loop.close()

    async def subscribe(self) -> asyncio.Queue:
        """Registra una nueva conexión de suscriptor."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue):
        """Elimina una conexión cuando el cliente se desconecta."""
        self._subscribers.discard(queue)

    @property
    def total_subscribers(self) -> int:
        return len(self._subscribers)


# Instancia única (Singleton) para toda la aplicación
realtime_manager = RealtimeManager()
notify_change = realtime_manager.notify_change
notify_change_sync = realtime_manager.notify_change_sync
