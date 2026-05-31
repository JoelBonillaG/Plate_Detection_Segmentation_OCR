"""
Envio de correos por SMTP.

Lo usa la API al aprobar un evento (`PATCH /events/{id}/approve`) y los endpoints
de notificaciones. La configuracion SMTP sale de `config.py` (variables `.env`).
"""

from dataclasses import dataclass
from email.message import EmailMessage
import smtplib
import ssl

from .config import get_settings


@dataclass(frozen=True)
class EmailPayload:
    to: str
    subject: str
    body: str


def _validate_smtp_settings() -> None:
    settings = get_settings()
    missing = [
        name
        for name, value in {
            "SMTP_HOST": settings.smtp_host,
            "SMTP_USER": settings.smtp_user,
            "SMTP_PASSWORD": settings.smtp_password,
            "SMTP_FROM": settings.smtp_from,
        }.items()
        if not value
    ]
    if missing:
        raise ValueError(f"Configuracion SMTP incompleta: {', '.join(missing)}")


def send_email(payload: EmailPayload) -> None:
    _validate_smtp_settings()
    settings = get_settings()

    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = payload.to
    message["Subject"] = payload.subject
    message.set_content(payload.body)

    if settings.smtp_encryption == "ssl":
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=context) as server:
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(message)
        return

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        if settings.smtp_encryption == "starttls":
            server.starttls(context=ssl.create_default_context())
        server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(message)


def build_vehicle_notification_body(notification: dict) -> str:
    plate = notification.get("placa_validada") or notification.get("placa_ocr")
    return (
        "Estimado propietario,\n\n"
        f"Se registra una notificacion del sistema de monitoreo vehicular para la placa {plate}.\n"
        f"Velocidad registrada: {notification.get('velocidad')} km/h.\n"
        f"Limite permitido: {notification.get('limite_velocidad')} km/h.\n\n"
        "Este mensaje fue generado por el sistema de monitoreo vehicular universitario.\n"
    )
