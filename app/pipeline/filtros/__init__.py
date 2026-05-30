"""
ETAPA intermedia del pipeline: filtros (limpieza + agrandado).

Entrada: placa enderezada (BGR) que dejo la etapa 1.
Salida : placa gris, limpia, agrandada y nitida, lista para el OCR.

API publica (la usa cadena.py / main.py):
    cargar_config()                               -> dict de config de la etapa
    filtrar(placa_bgr, cfg=None)                  -> placa gris filtrada
    guardar_filtrada(nombre, placa_bgr, cfg=None) -> guarda filtradas/<nombre>.jpg
"""

import os
import json

import cv2

from .filtros import filtrar as _filtrar

_AQUI = os.path.dirname(os.path.abspath(__file__))


def _ruta(p):
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(_AQUI, p))


def cargar_config():
    with open(os.path.join(_AQUI, "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["salidas"] = _ruta(cfg.get("salidas", "filtradas"))
    return cfg


def filtrar(placa_bgr, cfg=None):
    return _filtrar(placa_bgr, cfg or cargar_config())


def guardar(nombre, img, cfg=None):
    """Guarda una imagen YA filtrada en filtradas/<nombre>.jpg. Devuelve la ruta."""
    cfg = cfg or cargar_config()
    os.makedirs(cfg["salidas"], exist_ok=True)
    ruta = os.path.join(cfg["salidas"], f"{nombre}.jpg")
    cv2.imwrite(ruta, img)
    return ruta


def guardar_filtrada(nombre, placa_bgr, cfg=None):
    """Filtra la placa y la guarda. Atajo para uso standalone."""
    cfg = cfg or cargar_config()
    return guardar(nombre, filtrar(placa_bgr, cfg), cfg)


__all__ = ["cargar_config", "filtrar", "guardar", "guardar_filtrada"]
