"""
Postprocesamiento del clasificador de caracteres.

El modulo fuerza el formato de placa ecuatoriana sobre las cajas entregadas por
la segmentacion. El clasificador base produce un caracter por cada caja recibida;
por ello, cuando existen regiones adicionales, se selecciona la mejor subsecuencia
con estructura de tres letras y tres o cuatro digitos.

La seleccion combina confianza del clasificador, consistencia de altura y
penalizacion por saltos internos. El criterio es relativo y evita depender de un
umbral fijo por caracter.
"""

from itertools import combinations

import cv2
import numpy as np

from .test_plate import prepare_crop   # preprocesamiento usado en entrenamiento


# Limite de candidatos para controlar el costo combinatorio.
_MAX_CANDIDATOS = 12


def _predecir(crop, modelo, th, tw, canales):
    """Softmax del clasificador para UN crop de caracter (gris)."""
    gris = crop if crop.ndim == 2 else cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    proc = prepare_crop(gris, th, tw)
    if canales == 1:
        proc = np.expand_dims(proc, axis=-1)
    elif canales == 3:
        proc = cv2.cvtColor(proc.astype(np.uint8), cv2.COLOR_GRAY2RGB).astype("float32")
    proc = np.expand_dims(proc, axis=0)
    return modelo.predict(proc, verbose=0)[0]


def leer_placa(crops, modelo, classes, num_letras=3, digitos_validos=(4, 3),
               return_conf=True):
    """
    Crops de caracter (de la segmentacion) -> texto de placa con formato forzado.

    num_letras       : letras iniciales (Ecuador = 3).
    digitos_validos  : longitudes de digitos a probar, en orden de preferencia.
    return_conf      : True -> (texto, [confianzas]) ; False -> texto.

    Devuelve la mejor secuencia 3 letras + N digitos. Si hay MENOS cajas que el
    formato minimo, clasifica todas con la regla posicional (sin recortar).
    """
    if not crops:
        return ("", []) if return_conf else ""

    th = int(modelo.input_shape[1])
    tw = int(modelo.input_shape[2])
    canales = int(modelo.input_shape[3]) if len(modelo.input_shape) == 4 else 1

    letras_ids = [i for i, c in enumerate(classes) if c.isalpha()]
    digitos_ids = [i for i, c in enumerate(classes) if c.isdigit()]

    # Candidato por caja: mejor letra, mejor digito y altura del recorte.
    candidatos = []
    for crop in crops:
        if crop is None or crop.size == 0:
            continue
        pred = _predecir(crop, modelo, th, tw, canales)
        il = max(letras_ids, key=lambda i: pred[i])
        idg = max(digitos_ids, key=lambda i: pred[i])
        candidatos.append({
            "letra": classes[il],  "conf_letra": float(pred[il]),
            "digito": classes[idg], "conf_digito": float(pred[idg]),
            "alto": int(crop.shape[0]),
        })

    n = len(candidatos)
    if n == 0:
        return ("", []) if return_conf else ""

    # Acota el combinatorio si llegan demasiadas cajas.
    if n > _MAX_CANDIDATOS:
        candidatos = sorted(
            candidatos,
            key=lambda c: max(c["conf_letra"], c["conf_digito"]),
            reverse=True,
        )[:_MAX_CANDIDATOS]
        n = len(candidatos)

    alturas = sorted(c["alto"] for c in candidatos)
    alto_medio = alturas[len(alturas) // 2]

    def _emitir(indices):
        texto, confs = "", []
        for pos, i in enumerate(indices):
            c = candidatos[i]
            if pos < num_letras:
                texto += c["letra"];  confs.append(c["conf_letra"])
            else:
                texto += c["digito"]; confs.append(c["conf_digito"])
        return texto, confs

    # Busca la mejor subsecuencia que encaje en 3 letras + N digitos.
    mejor = None   # (score, indices)
    for nd in digitos_validos:
        largo = num_letras + nd
        if n < largo:
            continue
        for indices in combinations(range(n), largo):
            score = 0.0
            for pos, i in enumerate(indices):
                c = candidatos[i]
                score += c["conf_letra"] if pos < num_letras else c["conf_digito"]
            # La consistencia de altura penaliza regiones mucho mas bajas.
            penal_alto = sum(
                max(0.0, (alto_medio * 0.6 - candidatos[i]["alto"]) / alto_medio)
                for i in indices
            )
            saltos = (indices[-1] - indices[0] + 1) - largo   # huecos internos
            s = score / largo - 0.12 * saltos - 0.35 * penal_alto
            if nd == 4:
                s += 0.05   # leve preferencia al formato 3+4
            if mejor is None or s > mejor[0]:
                mejor = (s, indices)

    indices = mejor[1] if mejor is not None else tuple(range(n))
    texto, confs = _emitir(indices)
    return (texto, confs) if return_conf else texto


__all__ = ["leer_placa"]

