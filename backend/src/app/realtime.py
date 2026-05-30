"""
Módulo de tiempo real: WebSocket manager + buffer de frame para MJPEG.

Uso desde el pipeline (core/main.py):
    from src.app.realtime import broadcast_event, set_current_frame

Uso desde FastAPI (main.py):
    from .realtime import manager, get_current_frame
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from fastapi import WebSocket


# ── WebSocket connection manager ──────────────────────────────────────────────

class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(ws)

    async def broadcast(self, message: dict[str, Any]) -> None:
        dead: set[WebSocket] = set()
        async with self._lock:
            targets = set(self._connections)

        for ws in targets:
            try:
                await ws.send_json(message)
            except Exception:
                dead.add(ws)

        if dead:
            async with self._lock:
                self._connections -= dead

    @property
    def count(self) -> int:
        return len(self._connections)


manager = ConnectionManager()


# ── Broadcast helpers (called from sync pipeline code via asyncio) ────────────

def broadcast_event(event_data: dict[str, Any]) -> None:
    """
    Llama esto desde el pipeline (hilo separado) después de insertar el evento en DB.
    event_data debe tener todos los campos del EventPayload (ver ws_schema abajo).
    """
    _run_coroutine(manager.broadcast({"type": "event", "data": event_data}))


def broadcast_status(fps: float, camera_connected: bool = True) -> None:
    """Llamar periódicamente desde el loop de cámara."""
    import datetime
    _run_coroutine(manager.broadcast({
        "type": "status",
        "data": {
            "fps": round(fps, 1),
            "camera_connected": camera_connected,
            "backend_connected": True,
            "current_time": datetime.datetime.now().strftime("%H:%M:%S"),
        },
    }))


def _run_coroutine(coro) -> None:
    """Ejecuta una corutina desde un hilo sincrónico."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, loop)
        else:
            loop.run_until_complete(coro)
    except RuntimeError:
        # No hay event loop en este hilo — crear uno nuevo
        asyncio.run(coro)


# ── MJPEG frame buffer ────────────────────────────────────────────────────────

_frame_lock = threading.Lock()
_current_frame: bytes | None = None


def set_current_frame(jpeg_bytes: bytes) -> None:
    """
    Llamar desde el loop de cámara con cada frame JPEG codificado.
    Ejemplo:
        _, buf = cv2.imencode(".jpg", frame)
        set_current_frame(buf.tobytes())
    """
    global _current_frame
    with _frame_lock:
        _current_frame = jpeg_bytes


def get_current_frame() -> bytes | None:
    with _frame_lock:
        return _current_frame
