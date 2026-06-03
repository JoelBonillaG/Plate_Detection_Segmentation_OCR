"""
Etapa 1 - enderezado: recortar la placa y dejarla HORIZONTAL (CV clasico),
lista para la red de OCR.

    a) busca el contorno cuadrilatero de la placa -> corrige perspectiva (warp)
    b) si no lo halla, usa minAreaRect            -> corrige rotacion
    c) si nada funciona, devuelve el recorte redimensionado
"""

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


def _warp(img, pts):
    """Perspectiva a horizontal SIN encoger: el tamano de salida sale de las
    longitudes REALES de los lados del cuadrilatero detectado -> conserva la
    resolucion nativa de la placa (no se fuerza a un ancho x alto fijo)."""
    src = _ordenar_puntos(pts)
    tl, tr, br, bl = src
    ancho = int(round(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))))
    alto  = int(round(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))))
    if ancho < 1 or alto < 1:
        return img
    dst = np.array([[0, 0], [ancho - 1, 0],
                    [ancho - 1, alto - 1], [0, alto - 1]], dtype="float32")
    M = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(img, M, (ancho, alto))


def enderezar(crop, ancho=300, alto=100):
    """Recibe el recorte de la placa y la devuelve HORIZONTAL conservando su
    resolucion nativa. Solo corrige perspectiva/rotacion; NO infla con pixeles
    sinteticos ni encoge a un tamano fijo (eso pixelaba).

    ancho/alto quedan en la firma por compatibilidad con las llamadas viejas,
    pero ya NO se usan (el tamano lo decide la placa real)."""
    area = crop.shape[0] * crop.shape[1]

    gris  = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gris  = cv2.bilateralFilter(gris, 11, 17, 17)
    edges = cv2.Canny(gris, 30, 200)

    contornos, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contornos = sorted(contornos, key=cv2.contourArea, reverse=True)[:5]

    # a) cuadrilatero -> perspectiva
    for c in contornos:
        peri   = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4 and cv2.contourArea(c) > 0.20 * area:
            return _warp(crop, approx)

    # b) rectangulo rotado -> rotacion
    if contornos and cv2.contourArea(contornos[0]) > 0.20 * area:
        caja = cv2.boxPoints(cv2.minAreaRect(contornos[0]))
        return _warp(crop, caja)

    # c) sin contorno fiable -> crop tal cual (resolucion nativa, sin tocar)
    return crop
