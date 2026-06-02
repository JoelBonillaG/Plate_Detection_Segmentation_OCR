"""
Puente vision -> api (procesos separados).

El proceso de vision (start_vision) NO comparte memoria con la API (start_api),
asi que abre un WebSocket CLIENTE hacia /ws/ingest de la API y le empuja:

    - frames JPEG anotados   -> mensaje BINARIO  (la API los reenvia a /ws/video)
    - eventos / status (JSON)-> mensaje TEXTO    (la API los reenvia a /ws)

El loop de camara es SINCRONO; este modulo corre un event loop asyncio en un
daemon thread y expone funciones thread-safe:

    bridge.start()                 # arrancar una sola vez al inicio
    bridge.send_frame(jpeg_bytes)  # ultimo frame gana (no se acumula lag)
    bridge.send_event(payload)     # JSON, NO se descarta (cola)
    bridge.send_status(payload)    # JSON, NO se descarta (cola)

Si la API no esta lista, el cliente reintenta conectar solo (no bloquea la camara).
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import threading

import websockets

# URL del endpoint de ingesta en la API. Sobreescribible con API_INGEST_URL.
INGEST_URL = os.getenv("API_INGEST_URL", "ws://127.0.0.1:8000/ws/ingest")

# poll del sender: cada cuanto revisa si hay frame/evento nuevo (~50 Hz)
_POLL_S = 0.02

_lock = threading.Lock()
_latest_frame: bytes | None = None
_json_q: "queue.Queue[dict]" = queue.Queue(maxsize=1000)

_started = False


def send_frame(jpeg_bytes: bytes) -> None:
    """Ultimo frame gana: si el sender va atrasado se pisa el frame viejo."""
    global _latest_frame
    with _lock:
        _latest_frame = jpeg_bytes


def send_event(payload: dict) -> None:
    """Encola un evento (no se descarta) para /ws."""
    _enqueue({"type": "event", "data": payload})


def send_status(payload: dict) -> None:
    """Encola un status para /ws."""
    _enqueue({"type": "status", "data": payload})


def _enqueue(msg: dict) -> None:
    try:
        _json_q.put_nowait(msg)
    except queue.Full:
        # cola saturada (API caida mucho rato): descartar el mas viejo y reintentar
        try:
            _json_q.get_nowait()
            _json_q.put_nowait(msg)
        except queue.Empty:
            pass


async def _sender(ws) -> None:
    """Drena la cola JSON y empuja el ultimo frame mientras el socket viva."""
    last_frame_sent = None
    while True:
        # 1) eventos/status pendientes (prioridad: no se pierden)
        while True:
            try:
                msg = _json_q.get_nowait()
            except queue.Empty:
                break
            await ws.send(json.dumps(msg))

        # 2) ultimo frame (binario) si cambio
        with _lock:
            frame = _latest_frame
        if frame is not None and frame is not last_frame_sent:
            await ws.send(frame)
            last_frame_sent = frame

        await asyncio.sleep(_POLL_S)


async def _run() -> None:
    while True:
        try:
            async with websockets.connect(INGEST_URL, max_size=None) as ws:
                print(f"[BRIDGE] Conectado a la API en {INGEST_URL}")
                await _sender(ws)
        except asyncio.CancelledError:
            raise
        except Exception:
            # API aun no levanta o se reinicio: reintentar
            await asyncio.sleep(1.0)


def start() -> None:
    """Arranca el puente en un daemon thread. Idempotente."""
    global _started
    if _started:
        return
    _started = True

    def _loop() -> None:
        asyncio.run(_run())

    threading.Thread(target=_loop, daemon=True).start()
    print(f"[BRIDGE] Puente vision->api iniciado (destino {INGEST_URL})")
