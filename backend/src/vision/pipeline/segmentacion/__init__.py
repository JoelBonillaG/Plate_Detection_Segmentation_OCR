"""
ETAPA 2 del pipeline: segmentacion de caracteres con el U-Net.

Envuelve predict_char_segmentation.py (script CLI) en funciones reusables para
que la cadena le pase la placa YA FILTRADA (gris) en memoria, sin pasar por
disco. Reusa mask_to_boxes (mascara -> cajas) tal cual.

API publica (la usa cadena.py):
    cargar_modelo(ruta=None)                       -> modelo keras (cargar 1 vez)
    segmentar(imagen, modelo, cfg=None)            -> (cajas, crops) izq->der
    guardar(nombre, crops, cfg=None)               -> guarda segmentadas/<nombre>/NN.png
    guardar_crops(nombre, imagen, modelo, cfg=None)-> segmenta y guarda (standalone)
"""

import os
from pathlib import Path

import cv2
import numpy as np

from .predict_char_segmentation import mask_to_boxes

_AQUI       = Path(__file__).resolve().parent
_PROJECT_ROOT = _AQUI.parents[4]
_MODELO_DEF = _PROJECT_ROOT / "ml" / "models" / "char_segmentation" / "Models" / "best_char_segmentation_unet.keras"

# defaults espejo de los argparse de predict_char_segmentation.py
_CFG_DEF = {
    "threshold": 0.50,
    "min_area_ratio": 0.002,
    "padding": 0.08,
    "char_aspect": 0.60,
    # refina cada caja al COMPONENTE CONECTADO de la tinta real (negro) de la placa:
    # el U-Net a veces sub-segmenta (no pinta toda la B / la cola de la J) y la caja
    # recorta tinta -> el OCR lee mal (B->E, P->F). Expandir al componente recupera
    # esa tinta SIN invadir al char vecino. Poner False para volver al recorte crudo.
    "refinar_tinta": True,
    "salidas": os.path.join(_AQUI, "segmentadas"),
}


def cargar_modelo(ruta=None):
    """Carga el U-Net entrenado. Cargar una sola vez y reusar en el bucle."""
    import tensorflow as tf
    return tf.keras.models.load_model(str(ruta or _MODELO_DEF), compile=False)


def _a_gris(img):
    return img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def _refinar_cajas_por_tinta(gris, cajas, tol_alto=1.7):
    """Expande cada caja al COMPONENTE CONECTADO de la tinta (negro) que le corresponde.

    Motivo: el U-Net sub-segmenta a veces y la caja recorta parte del caracter
    (panza de la B, cola de la J) -> el OCR lee otra letra. Aqui se binariza la tinta
    real de la placa (Otsu inverso: oscuro->blanco), se hallan los componentes
    conectados y cada caja se AGRANDA para cubrir el/los componentes que le pertenecen.

    Guardas para no romper nada:
      - solo se EXPANDE (min en x1/y1, max en x2/y2): nunca encoge una caja.
      - no cruza el punto medio hacia el char vecino -> no fusiona caracteres.
      - ignora componentes que no parecen char: el marco/sombra de la placa (muy alto
        o muy ancho) y el ruido fino (muy bajo).
      - solo toma un componente si la MAYORIA (>=50%) de su ancho cae en la caja ->
        evita robar tinta del char de al lado.
    """
    if not cajas:
        return cajas
    H, W = gris.shape[:2]

    blur = cv2.GaussianBlur(gris, (3, 3), 0)
    _, tinta = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    tinta = cv2.morphologyEx(tinta, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    num, _lab, stats, _cen = cv2.connectedComponentsWithStats(tinta, connectivity=8)

    alto_med = float(np.median([max(1, y2 - y1) for (x1, y1, x2, y2) in cajas]))
    centros = [(x1 + x2) / 2.0 for (x1, y1, x2, y2) in cajas]

    nuevas = []
    for i, (x1, y1, x2, y2) in enumerate(cajas):
        # limites de seguridad: punto medio con la caja vecina (no invadir al de al lado)
        lim_izq = 0 if i == 0 else int((centros[i - 1] + centros[i]) / 2)
        lim_der = W if i == len(cajas) - 1 else int((centros[i] + centros[i + 1]) / 2)
        nx1, ny1, nx2, ny2 = x1, y1, x2, y2
        ancho_caja = max(1, x2 - x1)

        for c in range(1, num):   # 0 = fondo
            cx, cy, cw, ch, _area = stats[c]
            if ch > tol_alto * alto_med or ch < 0.40 * alto_med:
                continue          # marco/sombra (muy alto) o ruido fino (muy bajo)
            if cw > 1.8 * ancho_caja and cw > tol_alto * alto_med:
                continue          # demasiado ancho = varios chars pegados / borde
            ox1, ox2 = max(x1, cx), min(x2, cx + cw)
            if ox2 <= ox1:
                continue          # no solapa horizontalmente con esta caja
            if (ox2 - ox1) / float(cw) < 0.50:
                continue          # la mayoria del componente es de otro char
            nx1 = max(lim_izq, min(nx1, cx))
            ny1 = min(ny1, cy)
            nx2 = min(lim_der, max(nx2, cx + cw))
            ny2 = max(ny2, cy + ch)

        nuevas.append((max(0, nx1), max(0, ny1), min(W, nx2), min(H, ny2)))
    return nuevas


def segmentar(imagen, modelo, cfg=None):
    """Placa filtrada (gris o BGR) -> (cajas, crops) de cada caracter, izq->der.
    El U-Net redimensiona internamente; las cajas vuelven a la escala de `imagen`."""
    cfg = {**_CFG_DEF, **(cfg or {})}
    gris = _a_gris(imagen)

    h = int(modelo.input_shape[1])
    w = int(modelo.input_shape[2])
    entrada = cv2.resize(gris, (w, h), interpolation=cv2.INTER_AREA)
    entrada = entrada.astype("float32")[None, :, :, None]

    mascara = modelo.predict(entrada, verbose=0)[0, :, :, 0]
    cajas, _ = mask_to_boxes(mascara, imagen.shape, cfg["threshold"],
                             cfg["min_area_ratio"], cfg["padding"], cfg["char_aspect"])
    # recupera la tinta que el U-Net dejo fuera de la caja (sin invadir al vecino)
    if cfg.get("refinar_tinta", True):
        cajas = _refinar_cajas_por_tinta(gris, cajas)
    crops = [imagen[y1:y2, x1:x2] for (x1, y1, x2, y2) in cajas]
    return cajas, crops


def guardar(nombre, crops, cfg=None):
    """Guarda crops YA segmentados en segmentadas/<nombre>/NN.png. Devuelve cuantos."""
    cfg = {**_CFG_DEF, **(cfg or {})}
    destino = os.path.join(cfg["salidas"], nombre)
    os.makedirs(destino, exist_ok=True)
    for i, crop in enumerate(crops):
        if crop.size:
            cv2.imwrite(os.path.join(destino, f"{i:02d}.png"), crop)
    return len(crops)


def guardar_crops(nombre, imagen, modelo, cfg=None):
    """Segmenta y guarda. Atajo para uso standalone."""
    cfg = {**_CFG_DEF, **(cfg or {})}
    _, crops = segmentar(imagen, modelo, cfg)
    return guardar(nombre, crops, cfg)


__all__ = ["cargar_modelo", "segmentar", "guardar", "guardar_crops"]
