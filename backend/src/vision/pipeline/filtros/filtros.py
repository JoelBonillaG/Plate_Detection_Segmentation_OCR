"""
Filtros de placa: preprocesamiento SUAVE para el OCR.

Cadena (todo configurable por filtros/config.json):
    BGR -> gris -> suavizado (bilateral, respeta bordes) ->
    acentuado suave (unsharp) -> agrandar (opcional)

Idea: limpiar un poco y acentuar los caracteres SIN quemar la imagen. Nada de
CLAHE ni umbral por defecto: subian tanto el contraste que la placa se volvia
blanca y las letras finas desaparecian. Mejor poco y parejo.
"""

import cv2
import numpy as np


def _a_gris(img):
    return img if (img.ndim == 2) else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def filtrar(placa_bgr, cfg):
    """
    Aplica la cadena de filtros a UNA placa (BGR o gris).
    Devuelve la imagen procesada (gris). Cada paso se puede apagar por config.
    """
    g = _a_gris(placa_bgr)

    # 1) suavizado: bilateral filter quita ruido PERO respeta los bordes de las
    #    letras (a diferencia de un blur normal, que las desdibuja).
    if cfg.get("suavizar", True):
        g = cv2.bilateralFilter(g,
                                d=cfg.get("suavizar_d", 5),
                                sigmaColor=cfg.get("suavizar_sigma", 50),
                                sigmaSpace=cfg.get("suavizar_sigma", 50))

    # 2) acentuado suave (unsharp): resalta los bordes de los caracteres sin
    #    quemar. amount bajo (~0.5) para no empujar los claros a blanco.
    if cfg.get("acentuar", True):
        amount = cfg.get("acentuar_amount", 0.5)
        blur = cv2.GaussianBlur(g, (0, 0), cfg.get("acentuar_sigma", 1.5))
        g = cv2.addWeighted(g, 1.0 + amount, blur, -amount, 0)

    # 3) agrandar (opcional): la red OCR rinde mejor con caracteres grandes.
    if cfg.get("agrandar", True):
        f = cfg.get("agrandar_factor", 2.0)
        g = cv2.resize(g, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)

    return g
