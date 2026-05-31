"""
API FastAPI del sistema de monitoreo vehicular.

Rutas:
    GET  /health                   estado general
    GET  /health/db                prueba conexion a Postgres
    GET  /api/cameras/main/stream  proxy del MJPEG de vision
    GET  /ws                       WebSocket (eventos + status en vivo)
    GET  /api/events               historial de eventos
    GET  /api/events/{id}          detalle de un evento
    PATCH /api/events/{id}/approve aprobar sancion
    PATCH /api/events/{id}/reject  rechazar evento
    POST /notifications/test-email      correo de prueba
    POST /notifications/send-pending    enviar notificaciones pendientes
    GET  /static/...               imagenes guardadas por vision
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr

from .config import get_settings
from .database import (
    check_database_connection,
    fetch_pending_notifications,
    mark_notification_error,
    mark_notification_sent,
)
from .mailer import EmailPayload, build_vehicle_notification_body, send_email
from .realtime import get_current_frame, manager
from .events_db import fetch_eventos, fetch_evento, _row_to_payload, approve_evento, reject_evento

# URL del servidor MJPEG de vision (puede sobreescribirse con VISION_STREAM_URL)
VISION_STREAM_URL = os.getenv("VISION_STREAM_URL", "http://localhost:8001/stream.mjpeg")

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="API Monitoreo Vehicular Universitario")

STATIC_DIR = Path(__file__).resolve().parents[3] / "storage"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "database": settings.postgres_db,
        "smtp_host": settings.smtp_host,
        "ws_clients": manager.count,
    }


@app.get("/health/db")
def health_db() -> dict:
    try:
        return {"status": "ok", "connection": check_database_connection()}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"No se pudo conectar a Postgres: {exc}") from exc


# ── Video MJPEG (proxy hacia vision) ─────────────────────────────────────────

@app.get("/api/cameras/main/stream")
async def camera_stream() -> StreamingResponse:
    """
    Proxy del stream MJPEG de vision. El frontend consume esto con:
        <img src="/api/cameras/main/stream">

    Vision sirve el video en VISION_STREAM_URL (por defecto localhost:8001/stream.mjpeg).
    """
    client = httpx.AsyncClient(timeout=None)

    async def proxy():
        try:
            async with client.stream("GET", VISION_STREAM_URL) as resp:
                async for chunk in resp.aiter_bytes(chunk_size=4096):
                    yield chunk
        except (httpx.ConnectError, httpx.RemoteProtocolError):
            # vision no esta corriendo; devolver un frame vacio en vez de crash
            yield b""
        finally:
            await client.aclose()

    return StreamingResponse(
        proxy(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


# ── WebSocket /ws ─────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """
    Canal en tiempo real. Mensajes que emite el servidor:

        { "type": "event",  "data": { ... } }   placa detectada + velocidad + infraccion + evidencia
        { "type": "status", "data": { ... } }   fps, camara_conectada, hora

    El cliente puede enviar { "type": "ping" } y recibe { "type": "pong" }.
    """
    await manager.connect(ws)
    try:
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive_json(), timeout=60.0)
                if msg.get("type") == "ping":
                    await ws.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                try:
                    await ws.send_json({"type": "ping"})
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(ws)


# ── Eventos REST ──────────────────────────────────────────────────────────────

@app.get("/api/events")
def get_events(limit: int = 50, offset: int = 0) -> list[dict]:
    """Ultimos eventos con joins a vision y difuso."""
    rows = fetch_eventos(limit=limit, offset=offset)
    return [_row_to_payload(r) for r in rows]


@app.get("/api/events/{evento_id}")
def get_event(evento_id: str) -> dict:
    row = fetch_evento(evento_id)
    if not row:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    return _row_to_payload(row)


# ── Aprobar / Rechazar ────────────────────────────────────────────────────────

class ReviewRequest(BaseModel):
    placa_corregida: str | None = None
    motivo: str | None = None


@app.patch("/api/events/{evento_id}/approve")
def approve_event(evento_id: str, body: ReviewRequest) -> dict:
    """
    Aprueba la sancion:
    1. Actualiza estado_revision -> aprobado
    2. Crea notificacion (si hay correo del propietario)
    3. Envia el correo inmediatamente
    """
    try:
        approve_evento(evento_id, body.placa_corregida, body.motivo)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    sent = failed = 0
    try:
        notifs = fetch_pending_notifications(limit=1)
        notifs = [n for n in notifs if str(n.get("evento_id")) == evento_id]
        for n in notifs:
            body_text = n.get("mensaje") or build_vehicle_notification_body(n)
            try:
                send_email(EmailPayload(to=n["correo_destino"], subject=n["asunto"], body=body_text))
                mark_notification_sent(str(n["id"]))
                sent += 1
            except Exception as exc:
                mark_notification_error(str(n["id"]), str(exc))
                failed += 1
    except Exception:
        pass

    return {"status": "approved", "email-sent": sent, "email-failed": failed}


@app.patch("/api/events/{evento_id}/reject")
def reject_event(evento_id: str, body: ReviewRequest) -> dict:
    try:
        reject_evento(evento_id, body.motivo)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "rejected"}


# ── Notificaciones ────────────────────────────────────────────────────────────

class TestEmailRequest(BaseModel):
    to: EmailStr
    subject: str = "Prueba SMTP - Monitoreo vehicular"
    body: str = "Correo de prueba enviado desde el sistema de monitoreo vehicular."


@app.post("/notifications/test-email")
def send_test_email(payload: TestEmailRequest) -> dict:
    try:
        send_email(EmailPayload(to=payload.to, subject=payload.subject, body=payload.body))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"No se pudo enviar el correo: {exc}") from exc
    return {"status": "sent", "to": payload.to}


@app.post("/notifications/send-pending")
def send_pending_notifications(limit: int = 10) -> dict:
    sent = failed = 0
    for n in fetch_pending_notifications(limit=limit):
        body = n.get("mensaje") or build_vehicle_notification_body(n)
        try:
            send_email(EmailPayload(to=n["correo_destino"], subject=n["asunto"], body=body))
            mark_notification_sent(str(n["id"]))
            sent += 1
        except Exception as exc:
            mark_notification_error(str(n["id"]), str(exc))
            failed += 1
    return {"status": "processed", "sent": sent, "failed": failed}
