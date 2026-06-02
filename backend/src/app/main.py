"""
API FastAPI del sistema de monitoreo vehicular.

Rutas:
    GET  /health                   estado general
    GET  /health/db                prueba conexion a Postgres
    WS   /ws/video                 video en vivo (frames JPEG binarios -> browser)
    WS   /ws/ingest                ingesta de frames+eventos desde el proceso de vision
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
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
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
from .realtime import get_current_frame, set_current_frame, manager, video_manager
from .events_db import fetch_eventos, fetch_evento, _row_to_payload, approve_evento, reject_evento
from .fuzzy import EXCESO, REINCI, SEVERIDAD, RULES, LIMITE_VELOCIDAD as FZ_LIMITE, UMBRAL_TEMERARIA as FZ_UMBRAL

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


# ── Video por WebSocket ───────────────────────────────────────────────────────

@app.websocket("/ws/video")
async def video_stream(ws: WebSocket) -> None:
    """
    Video en vivo. Emite frames JPEG en BINARIO. El frontend dibuja cada frame
    en un <canvas>. Reconecta solo: si vision aun no esta lista, el socket queda
    abierto y los frames empiezan a llegar cuando vision se conecta a /ws/ingest.
    NO se necesita F5.
    """
    await video_manager.connect(ws)
    try:
        # mandar el ultimo frame conocido de inmediato (arranque instantaneo)
        ultimo = get_current_frame()
        if ultimo:
            await ws.send_bytes(ultimo)
        # el browser no envia nada; solo mantenemos el socket vivo
        while True:
            await ws.receive_bytes()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await video_manager.disconnect(ws)


@app.websocket("/ws/ingest")
async def ingest_stream(ws: WebSocket) -> None:
    """
    Ingesta desde el proceso de vision (start_vision). Vision empuja:
        - mensaje BINARIO -> frame JPEG anotado  -> reenviar a /ws/video
        - mensaje TEXTO   -> JSON {type,data}    -> reenviar a /ws (eventos/status)
    Es el unico puente vision -> api (procesos separados).
    """
    await ws.accept()
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            data = msg.get("bytes")
            if data is not None:
                set_current_frame(data)
                await video_manager.broadcast_bytes(data)
                continue
            text = msg.get("text")
            if text is not None:
                try:
                    import json
                    await manager.broadcast(json.loads(text))
                except Exception:
                    pass
    except WebSocketDisconnect:
        pass
    except Exception:
        pass


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


# ── FIS: definiciones expuestas ───────────────────────────────────────────────

_ETIQUETAS = {
    # Exceso de velocidad
    "no_excess": "Sin exceso", "minor": "Leve", "moderate": "Moderado",
    "serious": "Grave", "critical": "Crítico",
    # Reincidencia
    "clean": "Limpio", "low": "Bajo", "high": "Alto", "chronic": "Crónico",
    # Severidad
    "no_action": "Sin acción", "warning": "Advertencia",
    "low_susp": "Susp. baja", "medium_susp": "Susp. media",
    "high_susp": "Susp. alta", "critical_susp": "Susp. crítica",
}


def _conjuntos(sets: dict) -> list[dict]:
    return [
        {"clave": k, "etiqueta": _ETIQUETAS.get(k, k), "tipo": v[0], "parametros": list(v[1])}
        for k, v in sets.items()
    ]


@app.get("/api/difuso/definiciones")
def difuso_definiciones() -> dict:
    """
    Devuelve las definiciones matemáticas del FIS Mamdani.
    El frontend usa esto para renderizar las gráficas de funciones de membresía.
    """
    return {
        "limite_velocidad": FZ_LIMITE,
        "umbral_temeraria": FZ_UMBRAL,
        "tipo_inferencia": "Mamdani",
        "metodo_implicacion": "mínimo",
        "metodo_agregacion": "máximo",
        "defuzzificacion": "centroide",
        "total_reglas": len(RULES),
        "variables_entrada": {
            "exceso_velocidad": {
                "nombre": "Exceso de velocidad",
                "universo": [0, 40],
                "unidad": "km/h",
                "conjuntos": _conjuntos(EXCESO),
            },
            "reincidencia": {
                "nombre": "Reincidencia del conductor",
                "universo": [0, 10],
                "unidad": "infracciones previas",
                "conjuntos": _conjuntos(REINCI),
            },
        },
        "salida": {
            "nombre": "Severidad de la sanción",
            "universo": [0, 100],
            "unidad": "índice",
            "conjuntos": _conjuntos(SEVERIDAD),
        },
        "reglas": [
            {
                "id": f"R{i + 1}",
                "exceso_set": es,
                "reincidencia_set": rs,
                "severidad_set": ss,
                "descripcion": (
                    f"SI exceso={_ETIQUETAS.get(es,es)} "
                    f"Y reincidencia={_ETIQUETAS.get(rs,rs)} "
                    f"→ {_ETIQUETAS.get(ss,ss)}"
                ),
            }
            for i, (es, rs, ss) in enumerate(RULES)
        ],
        "conversion_dias": [
            {"rango": [0, 29],   "dias": 0, "descripcion": "Advertencia — sin suspensión"},
            {"rango": [30, 52],  "dias": 1, "descripcion": "1 día de suspensión"},
            {"rango": [53, 74],  "dias": 2, "descripcion": "2 días de suspensión"},
            {"rango": [75, 90],  "dias": 3, "descripcion": "3 días de suspensión"},
            {"rango": [91, 100], "dias": 4, "descripcion": "4 días de suspensión (máxima)"},
        ],
    }


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
