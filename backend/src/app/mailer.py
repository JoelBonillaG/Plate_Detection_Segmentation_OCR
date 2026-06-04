"""
Envio de correos por SMTP.

Lo usa la API al aprobar un evento (`PATCH /events/{id}/approve`) y los endpoints
de notificaciones. La configuracion SMTP sale de `config.py` (variables `.env`).
"""

from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
import smtplib
import ssl

from .config import get_settings


@dataclass(frozen=True)
class EmailPayload:
    to: str
    subject: str
    body: str                                    # texto plano (fallback)
    html: str | None = None                      # version HTML opcional
    inline_images: dict | None = None            # {cid: ruta_absoluta} para <img src="cid:...">



# Kill-switch global de envio de correo. En pruebas con video llegan muchos eventos;
# si se aprueban en lote el SMTP satura/bloquea -> este flag (toggle desde el frontend)
# corta el envio sin perder las notificaciones (quedan 'pendiente' y se envian luego).
_EMAIL_ENABLED = True


def email_enabled() -> bool:
    return _EMAIL_ENABLED


def set_email_enabled(value: bool) -> bool:
    global _EMAIL_ENABLED
    _EMAIL_ENABLED = bool(value)
    return _EMAIL_ENABLED


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
    message.set_content(payload.body)            # parte texto plano (fallback)

    # version HTML con imagenes embebidas (inline CID). La parte HTML pasa a ser
    # multipart/related: [html, img1, img2, ...] y el HTML referencia src="cid:<id>".
    if payload.html:
        message.add_alternative(payload.html, subtype="html")
        if payload.inline_images:
            html_part = message.get_payload()[-1]
            for cid, ruta in payload.inline_images.items():
                try:
                    data = Path(ruta).read_bytes()
                except OSError:
                    continue                     # imagen faltante -> se omite, no rompe el envio
                html_part.add_related(
                    data, maintype="image", subtype="jpeg", cid=f"<{cid}>")

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


# ---------------------------------------------------------------------------
# Version HTML con el PROCESO DE VISION paso a paso (imagenes inline) + difuso.
# Refleja la grilla del frontend. Se renderiza al momento de enviar el correo.
# ---------------------------------------------------------------------------

_RIESGO_COLOR = {"alto": "#c0392b", "medio": "#e67e22", "bajo": "#27ae60"}

# (cid, titulo, fuente_en_data) -> de donde sale la ruta relativa de cada etapa
_ETAPAS = [
    ("frame",            "1. Vehículo",          ("imagen_frame",)),
    ("placa_detectada",  "2. Placa detectada",   ("vision", "ruta_placa_detectada")),
    ("placa_enderezada", "3. Enderezada",        ("vision", "ruta_placa_enderezada")),
    ("placa_filtrada",   "4. Filtrada",          ("vision", "ruta_placa_filtrada")),
    ("segmentacion",     "5. Segmentación",      ("vision", "ruta_segmentacion")),
]


def _dig(data: dict, ruta: tuple):
    cur = data
    for k in ruta:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _conf_color(c: float) -> str:
    return "#27ae60" if c >= 0.85 else "#e67e22" if c >= 0.6 else "#c0392b"


def build_detection_html(data: dict):
    """Devuelve (html, image_map) donde image_map={cid: ruta_relativa}. El caller
    resuelve la ruta a archivo absoluto y solo embebe las que existan."""
    vision = data.get("vision") or {}
    fuzzy = data.get("fuzzy") or {}
    meta = vision.get("metadata") or {}

    placa     = data.get("placa_validada") or data.get("placa_ocr") or "—"
    placa_fmt = f"{placa[:3]}-{placa[3:]}" if isinstance(placa, str) and len(placa) > 3 else placa
    tipo      = (data.get("tipo_evento") or "—").upper()
    velocidad = float(data.get("velocidad", 0) or 0)
    limite    = float(data.get("limite_velocidad", 20) or 20)
    exceso    = velocidad - limite
    nivel     = (data.get("nivel_riesgo") or fuzzy.get("nivel_riesgo") or "—")
    dias      = data.get("dias_sancion_sugeridos", 0)
    reinc     = data.get("reincidencias", 0)
    crisp     = fuzzy.get("salida_crisp")
    color     = _RIESGO_COLOR.get(str(nivel).lower(), "#555")

    # qué etapas se omitieron (mismo criterio que el frontend)
    omitido = {
        "placa_enderezada": str(meta.get("enderezado", "")).lower() == "omitido",
        "placa_filtrada":   str(meta.get("filtros", "")).lower() in ("omitido", "omitidos"),
    }

    image_map, etapas_html = {}, []
    for cid, titulo, ruta in _ETAPAS:
        rel = _dig(data, ruta)
        if rel:
            image_map[cid] = rel
            cuerpo = (f'<img src="cid:{cid}" alt="{titulo}" '
                      f'style="max-width:150px;border:1px solid #ddd;border-radius:4px;display:block;">')
        elif omitido.get(cid):
            cuerpo = ('<div style="width:120px;height:48px;line-height:48px;text-align:center;'
                      'background:#eee;color:#999;border-radius:4px;font-size:12px;">Omitido</div>')
        else:
            continue
        etapas_html.append(
            f'<td style="padding:6px;vertical-align:top;text-align:center;font-size:11px;color:#444;">'
            f'{cuerpo}<div style="margin-top:4px;">{titulo}</div></td>')

    # OCR por caracter -> crop del char (inline) + letra leida + confianza (color)
    chips = []
    for i, c in enumerate(vision.get("ocr_por_caracter") or []):
        ch = c.get("caracter", "?")
        cf = float(c.get("confianza", 0) or 0)
        rel = c.get("ruta")
        img_html = ""
        if rel:
            cid = f"char{i}"
            image_map[cid] = rel
            img_html = (f'<img src="cid:{cid}" alt="{ch}" style="display:block;width:34px;'
                        f'height:46px;object-fit:contain;background:#fff;border:1px solid #ddd;'
                        f'border-radius:3px;margin:0 auto 3px;">')
        chips.append(
            f'<td style="text-align:center;padding:3px;vertical-align:bottom;">{img_html}'
            f'<div style="font-family:monospace;font-weight:bold;font-size:14px;">{ch}</div>'
            f'<div style="color:{_conf_color(cf)};font-size:11px;">{cf*100:.0f}%</div></td>')
    chips_html = (f'<table style="border-collapse:collapse;"><tr>{"".join(chips)}</tr></table>'
                  if chips else "<i>sin datos</i>")

    # reglas difusas activadas
    reglas = fuzzy.get("reglas_activadas") or []
    reglas_html = "".join(f"<li>{r}</li>" for r in reglas) or "<li><i>—</i></li>"

    # pertenencias velocidad como mini-barras
    def _barras(d: dict):
        filas = []
        for k, v in (d or {}).items():
            v = float(v or 0)
            filas.append(
                f'<tr><td style="font-size:11px;color:#555;padding:1px 6px;">{k}</td>'
                f'<td style="width:120px;"><div style="background:#eee;border-radius:3px;">'
                f'<div style="width:{v*100:.0f}%;background:{color};height:8px;border-radius:3px;"></div>'
                f'</div></td><td style="font-size:11px;color:#555;padding:1px 6px;">{v:.2f}</td></tr>')
        return "".join(filas) or '<tr><td style="font-size:11px;color:#999;">—</td></tr>'

    exceso_txt = (f'<span style="color:#c0392b;">+{exceso:.1f} km/h</span>'
                  if exceso > 0 else '<span style="color:#27ae60;">dentro del límite</span>')

    html = f"""\
<div style="font-family:Arial,Helvetica,sans-serif;max-width:680px;margin:auto;color:#222;">
  <div style="background:{color};color:#fff;padding:16px 20px;border-radius:8px 8px 0 0;">
    <div style="font-size:13px;opacity:.85;">SISTEMA DE MONITOREO VEHICULAR · UTA · Grupo C</div>
    <div style="font-size:26px;font-weight:bold;letter-spacing:2px;">{placa_fmt}</div>
    <div style="font-size:13px;">{tipo} · {reinc} reincidencia(s) ·
      <b>RIESGO {str(nivel).upper()}</b></div>
  </div>
  <div style="border:1px solid #eee;border-top:none;padding:18px 20px;border-radius:0 0 8px 8px;">

    <h3 style="margin:0 0 8px;font-size:15px;color:#333;">Proceso de visión — paso a paso</h3>
    <table style="border-collapse:collapse;"><tr>{''.join(etapas_html)}</tr></table>
    <div style="margin-top:10px;font-size:13px;"><b>OCR:</b> {chips_html}</div>

    <h3 style="margin:20px 0 8px;font-size:15px;color:#333;">Sistema difuso (Mamdani)</h3>
    <table style="font-size:13px;line-height:1.7;">
      <tr><td style="color:#666;padding-right:14px;">Velocidad / límite</td>
          <td><b>{velocidad:.1f}</b> / {limite:.0f} km/h &nbsp; {exceso_txt}</td></tr>
      <tr><td style="color:#666;">Nivel de riesgo</td>
          <td><b style="color:{color};">{str(nivel).upper()}</b></td></tr>
      <tr><td style="color:#666;">Sanción sugerida</td><td><b>{dias}</b> día(s)</td></tr>
      {f'<tr><td style="color:#666;">Salida crisp</td><td>{float(crisp):.4f}</td></tr>' if crisp is not None else ''}
    </table>
    <div style="margin-top:8px;font-size:12px;color:#666;">Pertenencia velocidad:</div>
    <table>{_barras(fuzzy.get('pertenencia_velocidad'))}</table>
    <div style="margin-top:6px;font-size:12px;color:#666;">Reglas activadas ({len(reglas)}):</div>
    <ul style="margin:4px 0;font-size:12px;color:#444;">{reglas_html}</ul>

    <div style="margin-top:16px;padding-top:10px;border-top:1px solid #eee;font-size:11px;color:#999;">
      Mensaje generado automáticamente por el sistema de visión artificial. No responder a este correo.
    </div>
  </div>
</div>"""
    return html, image_map
