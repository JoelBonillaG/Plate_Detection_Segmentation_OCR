"""
ETAPA 3 del pipeline: OCR (clasificador CNN de caracteres).

Recibe los crops de caracter que dejo la segmentacion (U-Net) y devuelve el
texto de la placa. Envuelve test_plate.py (script CLI) en funciones reusables:
reusa prepare_crop (mismo preprocesado del entrenamiento) y load_classes.

API publica (la usa cadena.py):
    cargar_modelo(ruta=None, classes_path=None) -> (modelo, classes)
    clasificar(crops, modelo, classes)          -> texto de la placa (str)
    guardar_resultado(nombre, texto, salidas=None) -> escribe salidas/<nombre>.txt
"""

import os
from pathlib import Path

import cv2
import numpy as np

from .test_plate import prepare_crop, load_classes

_AQUI        = Path(__file__).resolve().parent
_PROJECT_ROOT = _AQUI.parents[4]
# usar el .keras en formato HDF5 (legible por TF/Keras 2.10).
# OJO: los .keras de "Respaldo Modelo/" estan en formato zip (Keras 3) y NO cargan aqui.
_MODELO_DEF  = _PROJECT_ROOT / "ml" / "models" / "ocr" / "Modelos" / "best_cnn_ocr.keras"
_CLASSES_DEF = _PROJECT_ROOT / "ml" / "models" / "ocr" / "Modelos" / "classes.txt"
_SALIDAS_DEF = _AQUI / "salidas"


def cargar_modelo(ruta=None, classes_path=None):
    """Carga el clasificador CNN y sus clases. Cargar una vez y reusar."""
    import tensorflow as tf
    modelo = tf.keras.models.load_model(str(ruta or _MODELO_DEF), compile=False)
    classes = load_classes(str(classes_path or _CLASSES_DEF))
    return modelo, classes


def clasificar(crops, modelo, classes, return_conf=False, num_letters=3):
    """Lista de crops (gris) -> texto de la placa. Clasifica cada crop y concatena.

    Reglas posicionales (formato Ecuador: 3 letras + digitos): en las primeras
    `num_letters` posiciones se elige la mejor LETRA aunque un digito tenga mas
    confianza, y en el resto la mejor CIFRA. Asi se eliminan confusiones cruzadas
    (O/0, I/1, Z/2, S/5...). Con num_letters=None se usa el argmax libre.

    Con return_conf=True devuelve (texto, confianzas) donde confianzas es la lista
    del softmax de la clase ELEGIDA (ya restringida) de cada caracter."""
    if not crops:
        return ("", []) if return_conf else ""

    th = int(modelo.input_shape[1])
    tw = int(modelo.input_shape[2])
    canales = int(modelo.input_shape[3]) if len(modelo.input_shape) == 4 else 1

    letter_ids = [i for i, c in enumerate(classes) if c.isalpha()]
    digit_ids  = [i for i, c in enumerate(classes) if c.isdigit()]

    texto = ""
    confianzas = []
    posicion = 0
    for crop in crops:
        if crop is None or crop.size == 0:
            continue
        gris = crop if crop.ndim == 2 else cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        proc = prepare_crop(gris, th, tw)            # mismo preprocesado del entrenamiento

        if canales == 1:
            proc = np.expand_dims(proc, axis=-1)
        elif canales == 3:
            proc = cv2.cvtColor(proc.astype(np.uint8), cv2.COLOR_GRAY2RGB).astype("float32")
        proc = np.expand_dims(proc, axis=0)

        pred = modelo.predict(proc, verbose=0)[0]

        # restringir el argmax a la clase valida por posicion
        if num_letters is None:
            mejor = int(np.argmax(pred))
        else:
            permitidos = letter_ids if posicion < num_letters else digit_ids
            mejor = max(permitidos, key=lambda i: pred[i])

        texto += classes[mejor]
        confianzas.append(float(pred[mejor]))
        posicion += 1
    return (texto, confianzas) if return_conf else texto


def guardar_resultado(nombre, texto, salidas=None):
    """Escribe el texto de la placa en salidas/<nombre>.txt. Devuelve la ruta."""
    destino = salidas or _SALIDAS_DEF
    os.makedirs(destino, exist_ok=True)
    ruta = os.path.join(destino, f"{nombre}.txt")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(texto + "\n")
    return ruta


__all__ = ["cargar_modelo", "clasificar", "guardar_resultado"]
