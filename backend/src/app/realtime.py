"""
Módulo de tiempo real: managers de WebSocket (eventos JSON + video binario).

Arquitectura (2 procesos):
    vision  (start_vision) -> abre WS cliente a la API en /ws/ingest y empuja
                              frames (binario) + eventos/status (JSON).
    api     (start_api)    -> recibe en /ws/ingest y reenvia:
                                 JSON   -> clientes de /ws        (manager)
                                 frames -> clientes de /ws/video  (video_manager)

Uso desde FastAPI (main.py):
    from .realtime import manager, video_manager, get_current_frame, set_current_frame
"""

from __future__ import annotations

import asyncio
import threading
import time
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


class VideoManager:
    """
    Igual que ConnectionManager pero emite frames JPEG en BINARIO a los browsers
    conectados a /ws/video. Si un socket esta lento se descarta (no se acumula
    lag: el video es "ultimo frame gana").
    """

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

    async def broadcast_bytes(self, data: bytes) -> None:
        dead: set[WebSocket] = set()
        async with self._lock:
            targets = set(self._connections)

        for ws in targets:
            try:
                await ws.send_bytes(data)
            except Exception:
                dead.add(ws)

        if dead:
            async with self._lock:
                self._connections -= dead

    @property
    def count(self) -> int:
        return len(self._connections)


manager = ConnectionManager()
video_manager = VideoManager()


# ── Buffer del ultimo frame (para enviarlo apenas un browser se conecta) ──────

_frame_lock = threading.Lock()
_current_frame: bytes | None = None
_last_frame_ts: float = 0.0


def set_current_frame(jpeg_bytes: bytes) -> None:
    """Guarda el ultimo frame JPEG recibido del proceso de vision (via /ws/ingest)."""
    global _current_frame, _last_frame_ts
    with _frame_lock:
        _current_frame = jpeg_bytes
        _last_frame_ts = time.monotonic()


def get_current_frame() -> bytes | None:
    with _frame_lock:
        return _current_frame


def frames_flowing(within: float = 3.0) -> bool:
    """True si la vision empujo un frame hace menos de `within` segundos -> hay un
    proceso de vision vivo (lo lanzamos nosotros o lo arrancaron aparte)."""
    with _frame_lock:
        return _last_frame_ts > 0 and (time.monotonic() - _last_frame_ts) < within
