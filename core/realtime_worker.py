"""
@file realtime_worker.py
@author David Mogrovejo dmogrovejo87@gmail.com
@copyright (c) 2026 David Mogrovejo. All Rights Reserved.
@notice Developed with AI assistance.
@hash bf26ee033418d5dcd984ad8115334e7ce788cfb5d2bd456cf6e6ee21b877a762

OPSATEL - Worker en Segundo Plano de Monitoreo y Sincronización en Tiempo Real
==============================================================================
Script asíncrono que se autoejecuta en segundo plano periódicamente (cada 5 seg).
Inspecciona firmas de cambios y conteos en las tablas principales de la base de datos
para detectar modificaciones generadas por:
- Operaciones externas (phpMyAdmin, scripts directos en MySQL, WhatsApp Bridge externo, LibreQoS)
- Procesos asíncronos y bots (SAM Bot, tareas OLT de fondo)

Al detectar novedades, emite de inmediato un pulso de actualización a todos los usuarios
conectados mediante el RealtimeManager para que sus pantallas se actualicen en vivo.
"""

import asyncio
import logging
from typing import Dict, Tuple
from sqlalchemy import text
from database import SessionLocal
from core.realtime import notify_change

logger = logging.getLogger("opsatel.realtime_worker")

# Consultas ligeras de firmas (Conteo y Máximo ID) por módulo
SNAPSHOT_QUERIES = {
    "clientes": "SELECT COUNT(*), COALESCE(MAX(NUMERO), 0) FROM hoja_de_c__lculo_sin_t__tulo",
    "whatsapp": "SELECT COUNT(*), COALESCE(MAX(id), 0) FROM comprobantes",
    "hoja_ruta": "SELECT COUNT(*), COALESCE(MAX(id), 0) FROM hoja_ruta",
    "tickets": "SELECT COUNT(*), COALESCE(MAX(id), 0) FROM tickets_desarrollo",
    "callcenter": "SELECT COUNT(*), COALESCE(MAX(id), 0) FROM call_center_tickets",
    "balance": "SELECT COUNT(*), COALESCE(MAX(id), 0) FROM historial_pagos",
    "caja": "SELECT COUNT(*), COALESCE(MAX(id), 0) FROM turnos_cajas",
    "extras": "SELECT COUNT(*), COALESCE(MAX(id), 0) FROM clientes_extras",
    "olt": "SELECT COUNT(*), COALESCE(MAX(id), 0) FROM olt_tasks"
}

class RealtimeWatcher:
    def __init__(self, check_interval_seconds: float = 5.0):
        self.interval = check_interval_seconds
        self.running = False
        self._last_state: Dict[str, Tuple[int, int]] = {}
        self._task: asyncio.Task = None

    async def start(self):
        """Inicia el ciclo de monitoreo en segundo plano."""
        if self.running:
            return
        self.running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"Worker de tiempo real iniciado (intervalo: {self.interval}s)")

    async def stop(self):
        """Detiene el ciclo de monitoreo."""
        self.running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Worker de tiempo real detenido.")

    async def _run_loop(self):
        # Tomar estado inicial sin disparar notificaciones falsas al arrancar
        await self._take_initial_snapshot()

        while self.running:
            try:
                await asyncio.sleep(self.interval)
                await self._check_database_changes()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error en ciclo de monitoreo de tiempo real: {e}")
                await asyncio.sleep(self.interval)

    async def _take_initial_snapshot(self):
        """Lee el estado inicial de las tablas."""
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._poll_sync_snapshot)
        except Exception as e:
            logger.warning(f"No se pudo obtener snapshot inicial de BD: {e}")

    def _poll_sync_snapshot(self) -> Dict[str, Tuple[int, int]]:
        db = SessionLocal()
        try:
            for mod, query in SNAPSHOT_QUERIES.items():
                try:
                    res = db.execute(text(query)).fetchone()
                    if res:
                        self._last_state[mod] = (int(res[0]), int(res[1]))
                except Exception:
                    # Si alguna tabla aún no existe o no responde, omitir silenciosamente
                    pass
            return self._last_state
        finally:
            db.close()

    async def _check_database_changes(self):
        """Compara el estado actual con el anterior y emite eventos si hay diferencias."""
        loop = asyncio.get_running_loop()
        cambios = await loop.run_in_executor(None, self._detect_changes_sync)
        for mod in cambios:
            logger.info(f"[Realtime Watcher] Cambio externo detectado en módulo: {mod}. Notificando clientes.")
            await notify_change(mod, action="external_sync", extra={"source": "realtime_watcher"})

    def _detect_changes_sync(self):
        changed_modules = []
        db = SessionLocal()
        try:
            for mod, query in SNAPSHOT_QUERIES.items():
                try:
                    res = db.execute(text(query)).fetchone()
                    if res:
                        current = (int(res[0]), int(res[1]))
                        prev = self._last_state.get(mod)
                        if prev is not None and prev != current:
                            changed_modules.append(mod)
                        self._last_state[mod] = current
                except Exception:
                    pass
            return changed_modules
        finally:
            db.close()

# Instancia global del observador
realtime_watcher = RealtimeWatcher(check_interval_seconds=5.0)

async def iniciar_realtime_worker():
    """Función de arranque para startup event de FastAPI."""
    await realtime_watcher.start()

async def detener_realtime_worker():
    """Función de apagado para shutdown event de FastAPI."""
    await realtime_watcher.stop()
