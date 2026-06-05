"""
Entrenamiento de detector de placas con YOLOv11, DESDE CERO.

Clave: se carga la arquitectura desde el .yaml (pesos ALEATORIOS), NO el .pt
(que serian pesos pre-entrenados en COCO). Asi el modelo aprende solo con
nuestros datos -> entrenamiento desde cero, sin transfer learning.

    YOLO("yolo11n.yaml")  -> solo diseno, init aleatorio   (lo que usamos)
    YOLO("yolo11n.pt")    -> pesos pre-entrenados           (NO usamos)

Ejecutar:
    python entrenamiento.py
"""

import os
from ultralytics import YOLO

BASE        = os.path.dirname(os.path.abspath(__file__))
DATA_YAML   = os.path.join(BASE, "placas.yaml")
# guardar el modelo y resultados en deteccion_placas/modelos/
MODELOS_DIR = os.path.join(os.path.dirname(BASE), "modelos")

# nano = el mas chico; converge mas facil desde cero y con dataset pequeno
ARQUITECTURA = "yolo11n.yaml"

EPOCAS = 20
IMGSZ  = 640   # tamano nativo del dataset (no reescalar); multiplo de 32
BATCH  = 16    # auto-batch: ultralytics elige segun VRAM libre (~60%)


def entrenar():
    # arquitectura de libreria + pesos aleatorios (desde cero)
    modelo = YOLO(ARQUITECTURA)

    modelo.train(
        data=DATA_YAML,
        epochs=EPOCAS,
        imgsz=IMGSZ,
        batch=BATCH,
        pretrained=False,     # refuerza: nada de pesos pre-entrenados
        project=MODELOS_DIR,  # guardar en deteccion_placas/modelos/
        name="placas_scratch",
        patience=20,          # early stopping si no mejora
    )

    # evaluacion final en validacion (mAP, precision, recall)
    metricas = modelo.val()
    print(metricas)


if __name__ == "__main__":
    entrenar()
