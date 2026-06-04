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


def build_detection_body(data: dict) -> str:
    """Cuerpo del correo al ingeniero con todos los resultados del sistema."""
    placa     = data.get("placa_validada") or data.get("placa_ocr", "—")
    velocidad = float(data.get("velocidad", 0))
    limite    = float(data.get("limite_velocidad", 20))
    exceso    = velocidad - limite
    nivel     = data.get("nivel_riesgo", "—")
    dias      = data.get("dias_sancion_sugeridos", 0)
    tipo      = data.get("tipo_evento", "—")
    confianza = float(data.get("confianza_ocr", 0)) * 100
    reinc     = data.get("reincidencias", 0)

    sep = "=" * 62

    lines = [
        sep,
        "  SISTEMA DE MONITOREO VEHICULAR — UNIVERSIDAD TÉCNICA DE AMBATO",
        sep,
        "  Grupo C  |  Joel Bonilla · Josué García",
        sep,
        "",
        "── RESUMEN DEL EVENTO ──────────────────────────────────────────",
        f"  Placa detectada      : {placa}",
        f"  Tipo de evento       : {tipo.upper()}",
        f"  Reincidencias previas: {reinc}",
        "",
        "── VISIÓN ARTIFICIAL ───────────────────────────────────────────",
        f"  Velocidad registrada : {velocidad:.1f} km/h",
        f"  Límite permitido     : {limite:.0f} km/h",
        f"  Exceso de velocidad  : +{exceso:.1f} km/h" if exceso > 0 else "  Dentro del límite   : Sí",
        f"  Confianza OCR        : {confianza:.1f}%",
    ]

    # detalle por carácter si viene del payload extendido
    ocr_chars = (data.get("vision") or {}).get("ocr_por_caracter") or []
    if ocr_chars:
        chars_str = "  ".join(
            f"{c.get('caracter','?')}({float(c.get('confianza', 0))*100:.0f}%)"
            for c in ocr_chars
        )
        lines.append(f"  OCR por carácter     : {chars_str}")

    conf_v = (data.get("vision") or {}).get("confianza_vehiculo")
    conf_p = (data.get("vision") or {}).get("confianza_placa")
    if conf_v is not None:
        lines.append(f"  Conf. vehículo       : {float(conf_v)*100:.1f}%")
    if conf_p is not None:
        lines.append(f"  Conf. placa          : {float(conf_p)*100:.1f}%")

    n_chars = (data.get("vision") or {}).get("caracteres_segmentados")
    if n_chars is not None:
        lines.append(f"  Caracteres segmentados: {n_chars}")

    fuzzy = data.get("fuzzy") or {}
    lines += [
        "",
        "── SISTEMA DIFUSO (MAMDANI) ────────────────────────────────────",
        f"  Nivel de riesgo      : {nivel}",
        f"  Sanción sugerida     : {dias} día(s) de suspensión",
        f"  Conducción temeraria : {'Sí' if fuzzy.get('es_temeraria') else 'No'}",
    ]

    crisp = fuzzy.get("salida_crisp")
    if crisp is not None:
        lines.append(f"  Salida crisp         : {float(crisp):.4f}")

    reglas = fuzzy.get("reglas_activadas") or []
    if reglas:
        lines.append(f"  Reglas activadas     : {len(reglas)}")
        for r in reglas:
            lines.append(f"    · {r}")

    pert_v = fuzzy.get("pertenencia_velocidad") or {}
    if pert_v:
        pv_str = "  |  ".join(f"{k}: {float(v):.2f}" for k, v in pert_v.items())
        lines.append(f"  Pertenencia velocidad: {pv_str}")

    pert_r = fuzzy.get("pertenencia_reincidencia") or {}
    if pert_r:
        pr_str = "  |  ".join(f"{k}: {float(v):.2f}" for k, v in pert_r.items())
        lines.append(f"  Pertenencia reinc.   : {pr_str}")

    lines += [
        "",
        sep,
        "  Mensaje generado automáticamente por el sistema de visión artificial.",
        "  No responder a este correo.",
        sep,
    ]
    return "\n".join(lines)
