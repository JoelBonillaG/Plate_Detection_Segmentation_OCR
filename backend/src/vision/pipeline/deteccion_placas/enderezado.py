"""
Etapa 1 - enderezado: recortar la placa y dejarla HORIZONTAL (CV clasico),
lista para la red de OCR.

    a) busca el contorno cuadrilatero de la placa -> corrige perspectiva (warp)
    b) si no lo halla, usa minAreaRect            -> corrige rotacion
    c) si nada funciona, devuelve el recorte redimensionado
"""

import math

import cv2
import numpy as np


def recortar(frame, bbox, margen=0.08):
    """Recorta la caja de la placa con un pequeno margen relativo."""
    x1, y1, x2, y2 = bbox
    h, w = frame.shape[:2]
    mx = int((x2 - x1) * margen)
    my = int((y2 - y1) * margen)
    return frame[max(0, y1 - my):min(h, y2 + my),
                 max(0, x1 - mx):min(w, x2 + mx)]


def _ordenar_puntos(pts):
    """Ordena 4 puntos: sup-izq, sup-der, inf-der, inf-izq."""
    pts  = pts.reshape(4, 2).astype("float32")
    s    = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).ravel()        # y - x
    return np.array([
        pts[np.argmin(s)],      # sup-izq  (x+y minimo)
        pts[np.argmin(diff)],   # sup-der  (y-x minimo)
        pts[np.argmax(s)],      # inf-der  (x+y maximo)
        pts[np.argmax(diff)],   # inf-izq  (y-x maximo)
    ], dtype="float32")


def _warp(img, pts, margen=0.10):
    """Perspectiva a horizontal SIN encoger: el tamano de salida sale de las
    longitudes REALES de los lados del cuadrilatero detectado -> conserva la
    resolucion nativa de la placa (no se fuerza a un ancho x alto fijo).

    margen: expande el cuadrilatero hacia afuera (desde su centro) antes de
    warpear -> deja un poco de contexto de la placa y NO recorta tan pegado
    (evita el zoom excesivo que cortaba 'ECUADOR'). Se acota a los bordes del
    crop para no muestrear fuera (sin cunas negras)."""
    src = _ordenar_puntos(pts)
    if margen:
        centro = src.mean(axis=0)
        src = centro + (src - centro) * (1.0 + margen)
        h, w = img.shape[:2]
        src[:, 0] = src[:, 0].clip(0, w - 1)
        src[:, 1] = src[:, 1].clip(0, h - 1)
        src = src.astype("float32")
    tl, tr, br, bl = src
    ancho = int(round(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))))
    alto  = int(round(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))))
    if ancho < 1 or alto < 1:
        return img
    dst = np.array([[0, 0], [ancho - 1, 0],
                    [ancho - 1, alto - 1], [0, alto - 1]], dtype="float32")
    M = cv2.getPerspectiveTransform(src, dst)
    # INTER_CUBIC conserva mejor los bordes de caracteres durante el remuestreo.
    return cv2.warpPerspective(img, M, (ancho, alto), flags=cv2.INTER_CUBIC)


def _inclinacion(pts):
    """(rotacion_grados, perspectiva_rel) del cuadrilatero ordenado.
        rotacion    -> cuanto se inclina el borde sup/inf respecto a la horizontal.
        perspectiva -> cuanto difiere la altura del lado izq vs der (trapecio), 0..1.
    Sirve para decidir si vale la pena warpear o la placa ya esta casi de frente."""
    tl, tr, br, bl = _ordenar_puntos(pts)
    ang_sup = math.degrees(math.atan2(tr[1] - tl[1], tr[0] - tl[0]))
    ang_inf = math.degrees(math.atan2(br[1] - bl[1], br[0] - bl[0]))
    rot = max(abs(ang_sup), abs(ang_inf))
    alto_izq = math.hypot(bl[0] - tl[0], bl[1] - tl[1])
    alto_der = math.hypot(br[0] - tr[0], br[1] - tr[1])
    persp = abs(alto_izq - alto_der) / max(1.0, alto_izq, alto_der)
    return rot, persp


def enderezar(crop, ancho=300, alto=100, umbral_grados=5.0, umbral_persp=0.12,
              margen=0.05):
    """Devuelve la placa HORIZONTAL conservando su resolucion nativa, pero SOLO
    warpea si de verdad esta torcida. Si ya esta casi de frente, devuelve el
    recorte TAL CUAL -> NO se remuestrea, NO se pierde calidad (el warp siempre
    suaviza). Asi se corrige lo que vale la pena sin degradar las placas frontales.

        umbral_grados -> inclinacion (rotacion) maxima que se deja pasar sin warpear.
        umbral_persp  -> trapecio (perspectiva) maximo que se deja pasar sin warpear.
        margen        -> contexto extra alrededor de la placa cuando si se warpea.

    ancho/alto quedan por compatibilidad con llamadas viejas; ya NO se usan."""
    area = crop.shape[0] * crop.shape[1]

    gris  = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gris  = cv2.bilateralFilter(gris, 11, 17, 17)
    edges = cv2.Canny(gris, 30, 200)

    contornos, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contornos = sorted(contornos, key=cv2.contourArea, reverse=True)[:5]

    def _frontal(pts):
        rot, persp = _inclinacion(pts)
        return rot <= umbral_grados and persp <= umbral_persp

    # a) cuadrilatero -> perspectiva (solo si esta torcida)
    for c in contornos:
        peri   = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4 and cv2.contourArea(c) > 0.20 * area:
            if _frontal(approx):
                return crop          # placa frontal: no requiere transformacion
            return _warp(crop, approx, margen)

    # b) rectangulo rotado -> rotacion (solo si esta torcida)
    if contornos and cv2.contourArea(contornos[0]) > 0.20 * area:
        caja = cv2.boxPoints(cv2.minAreaRect(contornos[0]))
        if _frontal(caja):
            return crop
        return _warp(crop, caja, margen)

    # c) sin contorno fiable -> recorte original en resolucion nativa
    return crop
