"""
ETAPA 2 del pipeline: segmentacion de caracteres con el U-Net.

Envuelve predict_char_segmentation.py (script CLI) en funciones reusables para
que el pipeline le pase la placa YA FILTRADA (gris) en memoria, sin pasar por
disco. Reusa mask_to_boxes (mascara -> cajas) tal cual.

API publica (la usa pipeline.py):
    cargar_modelo(ruta=None)                       -> modelo keras (cargar 1 vez)
    segmentar(imagen, modelo, cfg=None)            -> (cajas, crops) izq->der
    guardar_crops(nombre, imagen, modelo, cfg=None)-> guarda segmentadas/<nombre>/NN.png
"""

import os

import cv2

from .predict_char_segmentation import mask_to_boxes

_AQUI       = os.path.dirname(os.path.abspath(__file__))
_MODELO_DEF = os.path.join(_AQUI, "Models", "best_char_segmentation_unet.keras")

# defaults espejo de los argparse de predict_char_segmentation.py
_CFG_DEF = {
    "threshold": 0.50,
    "min_area_ratio": 0.002,
    "padding": 0.08,
    "char_aspect": 0.60,
    "salidas": os.path.join(_AQUI, "segmentadas"),
}


def cargar_modelo(ruta=None):
    """Carga el U-Net entrenado. Cargar una sola vez y reusar en el bucle."""
    import tensorflow as tf
    return tf.keras.models.load_model(ruta or _MODELO_DEF, compile=False)


def _a_gris(img):
    return img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


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
