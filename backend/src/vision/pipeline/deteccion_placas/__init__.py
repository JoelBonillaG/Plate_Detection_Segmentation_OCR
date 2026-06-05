"""
ETAPA 1 del pipeline: deteccion de placa + enderezado.

API publica (lo que usa cadena.py):
    cargar_config()                  -> dict con la config de esta etapa
    cargar_modelo(cfg)               -> modelo YOLO listo
    procesar_frame(modelo, frame, cfg) -> placa enderezada (BGR) o None
    guardar_deteccion(nombre, frame, bbox, cfg) -> guarda detecciones/<nombre>.jpg
    guardar_enderezada(nombre, placa, cfg) -> guarda enderezadas/<nombre>.jpg

Internamente combina deteccion.py (YOLO) + enderezado.py (CV).
"""

import os
import json

import cv2

from .deteccion import cargar_yolo, detectar
from .enderezado import recortar, enderezar

_AQUI = os.path.dirname(os.path.abspath(__file__))


def _ruta_aqui(p):
    """Resuelve una ruta relativa respecto a esta carpeta (la etapa)."""
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(_AQUI, p))


def cargar_config():
    """Config de la etapa (deteccion_placas/config.json): modelo, conf, rutas."""
    with open(os.path.join(_AQUI, "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["detecciones"] = _ruta_aqui(cfg.get("detecciones", "detecciones"))
    cfg["enderezadas"] = _ruta_aqui(cfg.get("enderezadas", "enderezadas"))
    return cfg


def cargar_modelo(cfg):
    return cargar_yolo(_ruta_aqui(cfg["modelo"]))   # modelo de la etapa -> relativo a esta carpeta


def procesar_frame(modelo, frame, cfg, return_bbox=False):
    """
    Etapa completa sobre un frame:
        detectar placa -> recortar -> enderezar.
    Devuelve la placa horizontal (BGR) lista para OCR, o None si no hay placa.
    Si return_bbox=True devuelve (placa, bbox) -> util para auditar la deteccion.
    """
    bbox = detectar(modelo, frame, cfg.get("conf_min", 0.25))
    if bbox is None:
        return (None, None) if return_bbox else None
    crop = recortar(frame, bbox, cfg.get("margen", 0.08))
    placa = enderezar(crop)
    return (placa, bbox) if return_bbox else placa


def guardar_deteccion(nombre, frame, bbox, cfg):
    """Guarda el frame con el bbox de la placa dibujado en detecciones/<nombre>.jpg."""
    os.makedirs(cfg["detecciones"], exist_ok=True)
    vis = frame.copy()
    x1, y1, x2, y2 = bbox
    cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 255, 0), 2)
    cv2.putText(vis, "Placa", (x1, max(y1 - 8, 10)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    ruta = os.path.join(cfg["detecciones"], f"{nombre}.jpg")
    cv2.imwrite(ruta, vis)
    return ruta


def guardar_enderezada(nombre, placa, cfg):
    """Guarda la placa horizontal en enderezadas/<nombre>.jpg (para inspeccion)."""
    os.makedirs(cfg["enderezadas"], exist_ok=True)
    ruta = os.path.join(cfg["enderezadas"], f"{nombre}.jpg")
    cv2.imwrite(ruta, placa)
    return ruta


__all__ = ["cargar_config", "cargar_modelo", "procesar_frame",
           "guardar_deteccion", "guardar_enderezada",
           "detectar", "recortar", "enderezar"]
