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
import json
import subprocess
import sys
import threading
import time
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
from .mailer import (
    EmailPayload, send_email, build_detection_html, build_courtesy_html,
    email_enabled, set_email_enabled,
)
from .runtime import get_runtime, set_runtime
from .realtime import get_current_frame, set_current_frame, manager, video_manager, frames_flowing
from .events_db import (
    fetch_eventos, fetch_evento, _row_to_payload, approve_evento, reject_evento,
    resolve_evento_id,
)
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


# ── Auto-envio de correo en la DETECCION (si Correo ON, para TODO evento) ─────
_autosent_ids: set[str] = set()


def _autosend_email(event: dict) -> None:
    """Envia el correo de deteccion en un HILO (no bloquea el WS). Las imagenes se
    leen de disco; se espera un poco porque vision emite el evento antes de escribirlas."""
    try:
        time.sleep(0.6)
        from .config import get_settings
        to = get_settings().envio_infracciones_a
        if not to:
            return
        # normal (dentro del limite) -> correo de cortesia ; infraccion -> correo con difuso/multa
        es_normal = (event.get("tipo_evento") or "normal") == "normal"
        if es_normal:
            html, image_map = build_courtesy_html(event)
            cuerpo_txt = "Su vehiculo circulo dentro del limite. Gracias (ver version HTML)."
        else:
            html, image_map = build_detection_html(event)
            cuerpo_txt = "Evento detectado por el sistema (ver version HTML)."
        inline = {}
        for cid, rel in image_map.items():
            ruta = STATIC_DIR / rel
            if ruta.exists():
                inline[cid] = str(ruta)
        placa = event.get("placa_validada") or event.get("placa_ocr") or "—"
        send_email(EmailPayload(
            to=to,
            subject="Deteccion vehicular - Grupo C - Inteligencia artificial",
            body=cuerpo_txt,
            html=html, inline_images=inline or None))
        print(f"[CORREO] auto-enviado a {to}: {placa} ({'cortesia' if es_normal else 'infraccion'})")
    except Exception as exc:
        print(f"[CORREO] auto-envio fallo: {exc}")


def _maybe_autosend_email(event: dict) -> None:
    """Dispara el correo automatico si el correo esta ON, para TODO evento: infraccion
    -> correo con difuso/multa ; normal -> correo de cortesia (sin multa). Evita
    duplicados por id."""
    if not email_enabled():
        return
    eid = str(event.get("id") or event.get("db_id") or "")
    if eid and eid in _autosent_ids:
        return
    if eid:
        _autosent_ids.add(eid)
    threading.Thread(target=_autosend_email, args=(event,), daemon=True).start()


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
                    obj = json.loads(text)
                    await manager.broadcast(obj)
                    # correo automatico al detectar (si Correo ON y es infraccion)
                    if isinstance(obj, dict) and obj.get("type") == "event":
                        _maybe_autosend_email(obj.get("data") or {})
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
    """Aprueba la sancion, crea notificacion y envia correo al ingeniero."""
    # acepta UUID o id display 'EVT-...' (eventos en vivo llegan sin db_id)
    real_id = resolve_evento_id(evento_id)
    if not real_id:
        raise HTTPException(status_code=404, detail=f"Evento no encontrado: {evento_id}")
    evento_id = real_id
    try:
        approve_evento(evento_id, body.placa_corregida, body.motivo)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Kill-switch: si el correo esta apagado (p.ej. probando con video) NO se envia.
    # La notificacion queda 'pendiente' y se puede mandar luego con /notifications/send-pending.
    if not email_enabled():
        print(f"[MAIL] evento {evento_id} aprobado pero correo OFF -> notificacion en cola.")
        return {"status": "approved", "email-sent": 0, "email-skipped": True}

    sent = failed = 0
    try:
        notifs = fetch_pending_notifications(limit=1)
        notifs = [n for n in notifs if str(n.get("evento_id")) == evento_id]
        print(f"[MAIL] evento {evento_id} aprobado -> {len(notifs)} notificacion(es) por enviar.")
        # evento completo -> HTML con proceso de vision (imagenes inline) + difuso
        ev_row = fetch_evento(evento_id)
        ev = _row_to_payload(ev_row) if ev_row else None
        html, inline = None, {}
        if ev:
            html, image_map = build_detection_html(ev)
            for cid, rel in image_map.items():
                ruta = STATIC_DIR / rel
                if ruta.exists():
                    inline[cid] = str(ruta)

        for n in notifs:
            body_text = n.get("mensaje", "")
            try:
                send_email(EmailPayload(
                    to=n["correo_destino"], subject=n["asunto"], body=body_text,
                    html=html, inline_images=inline or None))
                mark_notification_sent(str(n["id"]))
                sent += 1
            except Exception as exc:
                print(f"[MAIL] FALLO -> {n.get('correo_destino')}: {exc}")
                mark_notification_error(str(n["id"]), str(exc))
                failed += 1
    except Exception as exc:
        print(f"[MAIL] error inesperado en el envio: {exc}")

    print(f"[MAIL] resumen evento {evento_id}: enviados={sent} fallidos={failed}")
    return {"status": "approved", "email-sent": sent, "email-failed": failed}


@app.patch("/api/events/{evento_id}/reject")
def reject_event(evento_id: str, body: ReviewRequest) -> dict:
    real_id = resolve_evento_id(evento_id)
    if not real_id:
        raise HTTPException(status_code=404, detail=f"Evento no encontrado: {evento_id}")
    evento_id = real_id
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
                "universo": [0, 30],
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

class EmailToggleRequest(BaseModel):
    enabled: bool


@app.get("/api/email/status")
def get_email_status() -> dict:
    """Estado del kill-switch de correo (para el toggle del frontend)."""
    return {"enabled": email_enabled()}


@app.post("/api/email/status")
def set_email_status(body: EmailToggleRequest) -> dict:
    """Enciende/apaga el envio de correo globalmente."""
    return {"enabled": set_email_enabled(body.enabled)}


class SpeedBoostRequest(BaseModel):
    enabled: bool
    kmh: float = 0.0


@app.get("/api/speed-boost")
def get_speed_boost() -> dict:
    """Estado del 'speed boost' de presentacion (km/h que se suman a la deteccion)."""
    rc = get_runtime()
    return {"enabled": rc.get("speed_boost_enabled", False), "kmh": rc.get("speed_boost_kmh", 0.0)}


@app.post("/api/speed-boost")
def set_speed_boost(body: SpeedBoostRequest) -> dict:
    """Suma artificial de velocidad para demostrar la sancion difusa en tiempo real.
    Lo lee el proceso de vision al capturar cada evento (storage/runtime_config.json)."""
    rc = set_runtime(speed_boost_enabled=bool(body.enabled), speed_boost_kmh=float(body.kmh))
    return {"enabled": rc["speed_boost_enabled"], "kmh": rc["speed_boost_kmh"]}


# ── Proceso de vision lanzado BAJO DEMANDA (el frontend no toca start_vision.ps1) ──
_BACKEND_DIR = Path(__file__).resolve().parents[2]   # .../backend
_vision_proc: "subprocess.Popen | None" = None


def _ensure_vision_running() -> bool:
    """Lanza el proceso de vision (con el mismo Python del venv) si no esta corriendo
    ni empujando frames. Devuelve True si lo acaba de lanzar (tarda ~15 s en cargar
    modelos). Si ya hay vision viva, no hace nada -> el hot-swap se encarga del cambio."""
    global _vision_proc
    if _vision_proc is not None and _vision_proc.poll() is None:
        return False
    if frames_flowing(3.0):
        return False
    try:
        _vision_proc = subprocess.Popen([sys.executable, "-m", "src.vision.main"],
                                        cwd=str(_BACKEND_DIR))
        print(f"[VISION] proceso lanzado bajo demanda (pid {_vision_proc.pid})")
        return True
    except Exception as exc:
        print(f"[VISION] no se pudo lanzar: {exc}")
        return False


class SourceRequest(BaseModel):
    source: str   # "live" (camara configurada), un indice de camara ("0","1",...) o ruta


@app.post("/api/source")
def set_source(body: SourceRequest) -> dict:
    """Fuente directa: 'live' (camara configurada), un INDICE de camara ('0','1',...)
    o una ruta de video. Usado por los botones EN VIVO / cámara #."""
    val = (body.source or "").strip().strip('"')
    if val.lower() == "live":
        val = "live"
    elif val.isdigit():
        val = val           # indice de camara explicito -> la vision lo abre como webcam
    else:
        if not Path(val).is_file():
            raise HTTPException(status_code=404, detail=f"No existe el archivo: {val}")
        val = str(Path(val).resolve())
    rc = get_runtime()
    rc = set_runtime(source=val, source_version=int(rc.get("source_version", 0)) + 1)
    launched = _ensure_vision_running()
    return {"source": rc["source"], "source_version": rc["source_version"], "vision_launched": launched}


@app.post("/api/source/stop")
def stop_source() -> dict:
    """DETIENE la fuente actual (video o en vivo): la vision suelta la camara y deja de
    procesar, pero el proceso sigue vivo (modelos en memoria) -> reanudar es instantaneo.
    No relanza la vision: si no hay proceso, no hay nada que detener."""
    rc = get_runtime()
    rc = set_runtime(source="idle", source_version=int(rc.get("source_version", 0)) + 1)
    return {"source": rc["source"], "source_version": rc["source_version"], "stopped": True}


# Explorador nativo de Windows via PowerShell (OpenFileDialog) -> sin depender de
# tkinter (que no esta instalado). -STA es obligatorio para los dialogos de WinForms.
_BROWSE_PS = (
    "Add-Type -AssemblyName System.Windows.Forms;"
    "$f = New-Object System.Windows.Forms.OpenFileDialog;"
    "$f.Title = 'Elige un video para reproducir';"
    "$f.Filter = 'Videos|*.mp4;*.avi;*.mov;*.mkv;*.webm|Todos|*.*';"
    "if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $f.FileName }"
)


@app.post("/api/source/browse")
def browse_source() -> dict:
    """Abre el EXPLORADOR DE ARCHIVOS nativo de Windows (en la maquina del backend =
    la del usuario, app local) para elegir un video de SU PC, sin teclear ni subir.
    El video elegido pasa a ser la fuente de la vision (hot-swap)."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", _BROWSE_PS],
            capture_output=True, text=True, timeout=300)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"No se pudo abrir el explorador: {exc}")
    path = (out.stdout or "").strip()
    if not path:
        return {"cancelled": True}
    if not Path(path).is_file():
        raise HTTPException(status_code=404, detail=f"No existe: {path}")
    rc = get_runtime()
    rc = set_runtime(source=str(Path(path).resolve()), source_version=int(rc.get("source_version", 0)) + 1)
    launched = _ensure_vision_running()
    return {"source": rc["source"], "source_version": rc["source_version"],
            "name": Path(path).name, "vision_launched": launched}


class TestEmailRequest(BaseModel):
    to: EmailStr
    subject: str = "Prueba SMTP - Monitoreo vehicular"
    body: str = "Correo de prueba enviado desde el sistema de monitoreo vehicular."


@app.post("/notifications/test-email")
def send_test_email(payload: TestEmailRequest) -> dict:
    if not email_enabled():
        raise HTTPException(status_code=409, detail="Envio de correo APAGADO (toggle en el panel).")
    try:
        send_email(EmailPayload(to=payload.to, subject=payload.subject, body=payload.body))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"No se pudo enviar el correo: {exc}") from exc
    return {"status": "sent", "to": payload.to}


@app.post("/notifications/send-pending")
def send_pending_notifications(limit: int = 10) -> dict:
    if not email_enabled():
        print("[MAIL] send-pending: correo OFF -> nada que enviar.")
        return {"status": "skipped", "sent": 0, "failed": 0, "reason": "correo apagado"}
    sent = failed = 0
    pendientes = fetch_pending_notifications(limit=limit)
    print(f"[MAIL] send-pending: {len(pendientes)} pendiente(s) en cola.")
    for n in pendientes:
        body = n.get("mensaje", "")
        try:
            send_email(EmailPayload(to=n["correo_destino"], subject=n["asunto"], body=body))
            mark_notification_sent(str(n["id"]))
            sent += 1
        except Exception as exc:
            print(f"[MAIL] FALLO -> {n.get('correo_destino')}: {exc}")
            mark_notification_error(str(n["id"]), str(exc))
            failed += 1
    print(f"[MAIL] send-pending resumen: enviados={sent} fallidos={failed}")
    return {"status": "processed", "sent": sent, "failed": failed}
