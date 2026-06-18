"""
Entrenamiento del detector de vehiculos con YOLOv11, DESDE CERO.

Misma filosofia que el detector de placas: se carga la arquitectura desde el
.yaml (pesos ALEATORIOS), NO el .pt (que serian pesos pre-entrenados en COCO).
Asi el modelo aprende solo con nuestros datos -> sin transfer learning.

    YOLO("yolo11n.yaml")  -> solo diseno, init aleatorio   (lo que usamos)
    YOLO("yolo11n.pt")    -> pesos pre-entrenados           (NO usamos)

Ejecutar:
    python entrenamiento.py
"""

import os
from pathlib import Path
from ultralytics import YOLO

BASE        = os.path.dirname(os.path.abspath(__file__))
DATA_YAML   = os.path.join(BASE, "carros.yaml")
PROJECT_ROOT = Path(BASE).resolve().parents[2]
# guardar el modelo y resultados en ml/models/vehicle_detection/runs/
MODELOS_DIR = PROJECT_ROOT / "models" / "vehicle_detection" / "runs"

# nano = el mas chico; converge mas facil desde cero y con dataset pequeno
ARQUITECTURA = "yolo11n.yaml"

EPOCAS = 50
IMGSZ  = 640   # tamano tipico del dataset de carros; multiplo de 32
BATCH  = -1    # auto-batch: ultralytics elige segun VRAM libre (~60%)


def entrenar():
    # arquitectura de libreria + pesos aleatorios (desde cero)
    modelo = YOLO(ARQUITECTURA)

    modelo.train(
        data=DATA_YAML,
        epochs=EPOCAS,
        imgsz=IMGSZ,
        batch=BATCH,
        pretrained=False,     # refuerza: nada de pesos pre-entrenados
        project=str(MODELOS_DIR),  # guardar en ml/models/vehicle_detection/runs/
        name="carros_scratch",
        patience=20,          # early stopping si no mejora
    )

    # evaluacion final en validacion (mAP, precision, recall)
    metricas = modelo.val()
    print(metricas)


if __name__ == "__main__":
    entrenar()
