from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, EmailStr

from .config import get_settings
from .database import (
    check_database_connection,
    fetch_pending_notifications,
    mark_notification_error,
    mark_notification_sent,
)
from .mailer import EmailPayload, build_vehicle_notification_body, send_email


app = FastAPI(title="API Monitoreo Vehicular Universitario")


class TestEmailRequest(BaseModel):
    to: EmailStr
    subject: str = "Prueba SMTP - Monitoreo vehicular"
    body: str = "Correo de prueba enviado desde el backend del sistema de monitoreo vehicular."


@app.get("/health")
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "database": settings.postgres_db,
        "smtp_host": settings.smtp_host,
    }


@app.get("/health/db")
def health_db() -> dict:
    try:
        return {"status": "ok", "connection": check_database_connection()}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"No se pudo conectar a Postgres: {exc}") from exc


@app.post("/notifications/test-email")
def send_test_email(payload: TestEmailRequest) -> dict:
    try:
        send_email(EmailPayload(to=payload.to, subject=payload.subject, body=payload.body))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"No se pudo enviar el correo: {exc}") from exc
    return {"status": "sent", "to": payload.to}


@app.post("/notifications/send-pending")
def send_pending_notifications(limit: int = 10) -> dict:
    sent = 0
    failed = 0
    notifications = fetch_pending_notifications(limit=limit)

    for notification in notifications:
        body = notification.get("mensaje") or build_vehicle_notification_body(notification)
        try:
            send_email(
                EmailPayload(
                    to=notification["correo_destino"],
                    subject=notification["asunto"],
                    body=body,
                )
            )
            mark_notification_sent(str(notification["id"]))
            sent += 1
        except Exception as exc:
            mark_notification_error(str(notification["id"]), str(exc))
            failed += 1

    return {"status": "processed", "sent": sent, "failed": failed}
