import asyncio
import os
from pathlib import Path

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
from .events_db import fetch_eventos, fetch_evento, _row_to_payload

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="API Monitoreo Vehicular Universitario")

# Archivos estáticos: imágenes de frames y placas guardadas por el pipeline
STATIC_DIR = Path(__file__).resolve().parents[3] / "storage"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# CORS — permite que el frontend (localhost:5173/5174/5175) consuma la API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # ajustar a dominios específicos en producción
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


# ── WebSocket /ws ─────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive_json(), timeout=60.0)
                if msg.get("type") == "ping":
                    await ws.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                # No hay actividad — mandamos ping propio para chequear que sigue vivo
                try:
                    await ws.send_json({"type": "ping"})
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(ws)


# ── MJPEG video feed /video_feed ──────────────────────────────────────────────

@app.get("/video_feed")
async def video_feed() -> StreamingResponse:
    """
    Transmite el frame más reciente como MJPEG multipart.
    El loop de cámara llama set_current_frame() con cada frame codificado en JPEG.
    El frontend consume esto con: <img src="http://localhost:8000/video_feed" />
    """
    async def generate():
        last_frame = None
        while True:
            frame = get_current_frame()
            if frame and frame is not last_frame:
                last_frame = frame
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + frame
                    + b"\r\n"
                )
            await asyncio.sleep(0.033)   # ~30 fps máximo

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


# ── Eventos REST ──────────────────────────────────────────────────────────────

@app.get("/events")
def get_events(limit: int = 50, offset: int = 0) -> list[dict]:
    """Devuelve los últimos eventos con joins a visión y difuso."""
    rows = fetch_eventos(limit=limit, offset=offset)
    return [_row_to_payload(r) for r in rows]


@app.get("/events/{evento_id}")
def get_event(evento_id: str) -> dict:
    row = fetch_evento(evento_id)
    if not row:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    return _row_to_payload(row)


# ── Notificaciones ────────────────────────────────────────────────────────────

class TestEmailRequest(BaseModel):
    to: EmailStr
    subject: str = "Prueba SMTP - Monitoreo vehicular"
    body: str = "Correo de prueba enviado desde el backend del sistema de monitoreo vehicular."


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
    notifications = fetch_pending_notifications(limit=limit)

    for notification in notifications:
        body = notification.get("mensaje") or build_vehicle_notification_body(notification)
        try:
            send_email(EmailPayload(
                to=notification["correo_destino"],
                subject=notification["asunto"],
                body=body,
            ))
            mark_notification_sent(str(notification["id"]))
            sent += 1
        except Exception as exc:
            mark_notification_error(str(notification["id"]), str(exc))
            failed += 1

    return {"status": "processed", "sent": sent, "failed": failed}
