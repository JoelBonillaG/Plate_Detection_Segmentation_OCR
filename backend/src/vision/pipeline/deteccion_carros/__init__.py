"""
ETAPA 0 del pipeline: deteccion de vehiculos.

Primer eslabon de la cadena: detecta el carro mas confiable del frame, lo recorta
(con margen) y entrega ese recorte a la ETAPA 1 (placas). Correr la red de placas
DENTRO del carro da zoom -> placa mas grande -> mejor OCR, y menos falsos
positivos del fondo. Si el modelo de carros no esta entrenado, la cadena hace
fallback: corre la placa sobre el frame completo (ver cadena.py).

Tambien guarda auditoria en disco:
    - el frame con la caja dibujada        -> detecciones/<nombre>.jpg
    - el recorte (con margen) del carro     -> detecciones/<nombre>_carro.jpg

API publica (la usa cadena.py):
    cargar_config()                       -> dict con la config de esta etapa
    cargar_modelo(cfg)                    -> modelo YOLO listo
    detectar_carro(modelo, frame, cfg)    -> caja (x1,y1,x2,y2) o None
    recortar(frame, bbox, margen)         -> recorte BGR del carro (con margen)
    guardar_deteccion(nombre, frame, bbox, cfg)  -> frame anotado
    guardar_recorte(nombre, frame, bbox, cfg)    -> crop del carro
"""

import os
import json

import cv2

from .deteccion import cargar_yolo, detectar

_AQUI = os.path.dirname(os.path.abspath(__file__))


def _ruta_aqui(p):
    """Resuelve una ruta relativa respecto a esta carpeta (la etapa)."""
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(_AQUI, p))


def cargar_config():
    """Config de la etapa (deteccion_carros/config.json): modelo, conf, margen, rutas."""
    with open(os.path.join(_AQUI, "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["detecciones"] = _ruta_aqui(cfg.get("detecciones", "detecciones"))
    return cfg


def cargar_modelo(cfg):
    return cargar_yolo(_ruta_aqui(cfg["modelo"]))   # modelo de la etapa -> relativo a esta carpeta


def detectar_carro(modelo, frame, cfg, return_conf=False):
    """Caja del carro mas confiable (x1,y1,x2,y2), o None.
    Con return_conf=True devuelve (bbox, confianza)."""
    return detectar(modelo, frame, cfg.get("conf_min", 0.25), cfg.get("imgsz", 640),
                    return_conf=return_conf)


def recortar(frame, bbox, margen=0.08):
    """
    Recorta el carro con un margen relativo, recortado a los limites del frame.
    Este es el crop que luego alimentara la red de placas (coords relativas al crop;
    para volver al frame se suma la esquina (x1, y1) del recorte).
    """
    x1, y1, x2, y2 = bbox
    h, w = frame.shape[:2]
    mx = int((x2 - x1) * margen)
    my = int((y2 - y1) * margen)
    x1 = max(0, x1 - mx); y1 = max(0, y1 - my)
    x2 = min(w, x2 + mx); y2 = min(h, y2 + my)
    return frame[y1:y2, x1:x2]


def guardar_deteccion(nombre, frame, bbox, cfg):
    """Guarda el frame con la caja del carro dibujada en detecciones/<nombre>.jpg."""
    os.makedirs(cfg["detecciones"], exist_ok=True)
    vis = frame.copy()
    x1, y1, x2, y2 = bbox
    cv2.rectangle(vis, (x1, y1), (x2, y2), (255, 128, 0), 2)
    cv2.putText(vis, "Carro", (x1, max(y1 - 8, 10)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 128, 0), 2)
    ruta = os.path.join(cfg["detecciones"], f"{nombre}.jpg")
    cv2.imwrite(ruta, vis)
    return ruta


def guardar_recorte(nombre, frame, bbox, cfg):
    """Guarda el recorte (con margen) del carro en detecciones/<nombre>_carro.jpg."""
    os.makedirs(cfg["detecciones"], exist_ok=True)
    crop = recortar(frame, bbox, cfg.get("margen", 0.08))
    if crop.size == 0:
        return None
    ruta = os.path.join(cfg["detecciones"], f"{nombre}_carro.jpg")
    cv2.imwrite(ruta, crop)
    return ruta


__all__ = ["cargar_config", "cargar_modelo", "detectar_carro", "recortar",
           "guardar_deteccion", "guardar_recorte", "detectar"]
