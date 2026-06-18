"""
Enderezado por ROTACION (deskew) con OpenCV NATIVO -> sin dependencias extra.

Implementa el MISMO algoritmo que la libreria `deskew` (open source,
sbrunner/deskew): transformada de HOUGH sobre los bordes pra estimar hacia donde
se inclina el texto/placa, y ROTAR por ese angulo. NO corrige perspectiva (eso
pediria las 4 esquinas); corrige la inclinacion (placa "chueca pero de frente"),
que es el caso comun cuando el carro pasa casi frontal a la camara.

Por que Hough y no esquinas: buscar las 4 esquinas exactas es fragil
(reflejos, carroceria, banda ECUADOR). Hough solo necesita "hacia donde se inclina
la estructura general" -> promedia muchos bordes -> mucho mas estable.

Decisiones:
  - Solo rota si |angulo| > `umbral_grados` para evitar remuestrear placas frontales.
  - Ignora |angulo| > `max_grados` -> estimacion poco fiable -> deja el crop igual.
  - Usa la MEDIANA de los angulos de las lineas (robusta a lineas sueltas raras).
  - Al rotar EXPANDE el lienzo (no corta esquinas), INTER_CUBIC (menos blur) y
    borde replicado (sin cunas negras).
"""

import cv2
import numpy as np


def _estimar_angulo(gris):
    """Angulo de inclinacion (grados) del texto/placa via Hough. None si no hay."""
    edges = cv2.Canny(gris, 50, 150, apertureSize=3)
    h, w = gris.shape[:2]
    # HoughLinesP: segmentos largos (bordes de placa / filas de texto) -> robusto.
    segmentos = cv2.HoughLinesP(
        edges, 1, np.pi / 180.0,
        threshold=max(30, w // 6),
        minLineLength=max(20, w // 4),
        maxLineGap=max(5, w // 20),
    )
    if segmentos is None:
        return None

    angulos = []
    for x1, y1, x2, y2 in segmentos[:, 0]:
        deg = np.degrees(np.arctan2(y2 - y1, x2 - x1))   # angulo del segmento
        # nos quedamos con lo CASI horizontal (texto / borde sup-inf de la placa);
        # las verticales (bordes izq-der) se normalizan fuera del rango y se ignoran
        if deg < -45:
            deg += 90
        elif deg > 45:
            deg -= 90
        if abs(deg) <= 45:
            angulos.append(deg)

    if not angulos:
        return None
    return float(np.median(angulos))   # mediana = robusta a outliers


def _rotar(img, angulo):
    """Rota `img` `angulo` grados expandiendo el lienzo pra no cortar esquinas."""
    h, w = img.shape[:2]
    centro = (w / 2.0, h / 2.0)
    M = cv2.getRotationMatrix2D(centro, angulo, 1.0)
    cos, sin = abs(M[0, 0]), abs(M[0, 1])
    nw = int(h * sin + w * cos)
    nh = int(h * cos + w * sin)
    M[0, 2] += nw / 2.0 - centro[0]
    M[1, 2] += nh / 2.0 - centro[1]
    return cv2.warpAffine(img, M, (nw, nh), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_REPLICATE)


def enderezar_rotacion(crop, umbral_grados=1.5, max_grados=30.0):
    """
    Devuelve la placa rotada a horizontal. Si ya esta derecha (|angulo| <
    umbral_grados) o el angulo es poco fiable (> max_grados), devuelve el crop
    SIN tocar (sin remuestreo -> sin perdida de calidad).
    """
    if crop is None or crop.size == 0:
        return crop

    gris = crop if crop.ndim == 2 else cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    angulo = _estimar_angulo(gris)
    if angulo is None:
        return crop
    if abs(angulo) < umbral_grados or abs(angulo) > max_grados:
        return crop

    # el segmento inclinado +deg (en coords de imagen, y hacia abajo) se endereza
    # rotando +deg con getRotationMatrix2D -> ver prueba de signo en el test.
    return _rotar(crop, angulo)


__all__ = ["enderezar_rotacion"]
