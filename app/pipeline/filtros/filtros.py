"""
Etapa intermedia - filtros: limpia y agranda la placa enderezada antes del OCR.

Entrada : placa enderezada (BGR, resolucion real) de la etapa 1.
Salida  : placa en gris, sin ruido, agrandada y nitida.

Todo es AUTOMATICO y por-imagen (generalizable): no se elige filtro ni fuerza a
mano. Se MIDE cada placa y se dosifica:
    - ruido  -> se estima sigma del ruido (Immerkaer) y se denoisea proporcional.
    - desenfoque -> se mide DESPUES de limpiar (asi el ruido no enga;a la medida)
      y se acentua mas cuanto mas borrosa este.

Flujo:
    placa (BGR) -> gris -> denoise adaptativo (Non-Local Means)
                -> agrandar (Lanczos) -> acentuado adaptativo (unsharp)
"""

import cv2
import numpy as np

# kernel del estimador de ruido de Immerkaer (laplaciano de 2do orden)
_K_RUIDO = np.array([[ 1, -2,  1],
                     [-2,  4, -2],
                     [ 1, -2,  1]], dtype=np.float32)


def _a_gris(img):
    """Convierte a gris solo si viene en color."""
    if img.ndim == 2:
        return img
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def _estimar_ruido(gris):
    """Estima sigma del ruido (metodo de Immerkaer): convoluciona con un
    laplaciano que cancela la se;al suave y deja solo ruido, y promedia."""
    h, w = gris.shape[:2]
    if h < 3 or w < 3:
        return 0.0
    lap = cv2.filter2D(gris.astype(np.float32), -1, _K_RUIDO)
    sigma = np.abs(lap).sum() * np.sqrt(np.pi / 2.0) / (6.0 * (w - 2) * (h - 2))
    return float(sigma)


def _denoise_auto(gris, cfg):
    """Denoise dosificado al ruido real de la placa.
    Poco ruido -> casi no toca (conserva trazos); mucho -> limpia mas fuerte."""
    sigma = _estimar_ruido(gris)
    h_min = cfg.get("denoise_h_min", 3.0)
    h_max = cfg.get("denoise_h_max", 12.0)
    ruido_ref = cfg.get("ruido_ref", 12.0)          # sigma al que se aplica h_max
    t = min(1.0, sigma / ruido_ref) if ruido_ref else 0.0
    h = h_min + t * (h_max - h_min)
    return cv2.fastNlMeansDenoising(gris, None, h=float(h),
                                    templateWindowSize=7, searchWindowSize=21)


def _agrandar(gris, alto_objetivo):
    """Lleva la placa a 'alto_objetivo' px de alto manteniendo la proporcion.
    Lanczos para ampliar (mejor en texto); AREA para reducir."""
    h, w = gris.shape[:2]
    if h == 0 or not alto_objetivo:
        return gris
    escala = alto_objetivo / h
    if abs(escala - 1.0) < 1e-3:
        return gris
    nw = max(1, int(round(w * escala)))
    interp = cv2.INTER_LANCZOS4 if escala > 1 else cv2.INTER_AREA
    return cv2.resize(gris, (nw, alto_objetivo), interpolation=interp)


def _amount_auto(gris, cfg):
    """Fuerza del unsharp segun el desenfoque (sobre la imagen YA limpia).
    Poca varianza de Laplaciano (borrosa) -> mas fuerza; nitida -> menos."""
    fm = cv2.Laplacian(gris, cv2.CV_64F).var()
    a_min = cfg.get("amount_min", 0.4)
    a_max = cfg.get("amount_max", 1.3)
    nitido_ok = cfg.get("nitido_ok", 150.0)
    if fm >= nitido_ok:
        return a_min
    t = fm / nitido_ok                               # 0 (borrosa) .. 1 (nitida)
    return a_max - t * (a_max - a_min)


def _unsharp(gris, amount, sigma):
    """Unsharp mask: realza bordes restando una version suavizada (highboost)."""
    suave = cv2.GaussianBlur(gris, (0, 0), sigma)
    return cv2.addWeighted(gris, 1.0 + amount, suave, -amount, 0)


def _normalizar_iluminacion(gris, k):
    """Aplana la iluminacion: estima el fondo (closing rellena los caracteres
    oscuros con la luz vecina) y divide -> fondo blanco parejo, caracter oscuro
    solido, sin importar sombras ni que el recorte traiga carroceria alrededor.
    El tamano ya esta fijo (alto_objetivo) -> un kernel fijo generaliza."""
    if k < 1:
        return gris
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    fondo = cv2.morphologyEx(gris, cv2.MORPH_CLOSE, kernel)
    return cv2.divide(gris, fondo, scale=255)


def filtrar(placa_bgr, cfg):
    """Placa enderezada (BGR) -> gris limpia, agrandada y nitida (uint8)."""
    gris = _a_gris(placa_bgr)

    if cfg.get("denoise", True):
        gris = _denoise_auto(gris, cfg)

    gris = _agrandar(gris, cfg.get("alto_objetivo", 280))

    if cfg.get("acentuar", True):
        amount = _amount_auto(gris, cfg)
        gris = _unsharp(gris, amount, cfg.get("unsharp_sigma", 1.0))

    if cfg.get("normalizar", True):
        gris = _normalizar_iluminacion(gris, cfg.get("norm_kernel", 25))

    return np.clip(gris, 0, 255).astype(np.uint8)
