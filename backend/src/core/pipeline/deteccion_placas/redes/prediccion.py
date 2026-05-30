"""
Carga el modelo YOLOv11 entrenado y detecta la placa en una imagen/frame.

Uso:
    python prediccion.py --imagen foto.jpg
    python prediccion.py --imagen foto.jpg --guardar resultado.jpg
"""

import argparse
import json
import os

import cv2
from ultralytics import YOLO

BASE   = os.path.dirname(os.path.abspath(__file__))   # redes/
ETAPA  = os.path.dirname(BASE)                         # deteccion_placas/

# config de la etapa (deteccion_placas/config.json): ruta del modelo, confianza, imgsz
with open(os.path.join(ETAPA, "config.json"), encoding="utf-8") as _f:
    _CFG = json.load(_f)

RUTA_MODELO = os.path.normpath(os.path.join(ETAPA, _CFG["modelo"]))
CONF_MIN    = _CFG.get("conf_min", 0.25)   # confianza minima para aceptar una deteccion
IMGSZ       = _CFG.get("imgsz", 416)        # mismo tamano con el que se entreno


def detectar_placa(modelo, imagen_bgr):
    """
    Recibe imagen BGR.
    Devuelve (x1, y1, x2, y2) en pixeles originales o None.
    Si hay varias placas, devuelve la de mayor confianza.
    """
    r = modelo(imagen_bgr, conf=CONF_MIN, imgsz=IMGSZ, verbose=False)[0]

    if r.boxes is None or len(r.boxes) == 0:
        return None

    i = int(r.boxes.conf.argmax())                       # caja mas confiable
    x1, y1, x2, y2 = r.boxes.xyxy[i].cpu().int().tolist()
    return x1, y1, x2, y2


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--imagen",  required=True)
    parser.add_argument("--modelo",  default=RUTA_MODELO)
    parser.add_argument("--guardar", default=None)
    args = parser.parse_args()

    img = cv2.imread(args.imagen)
    if img is None:
        print(f"No se pudo abrir: {args.imagen}")
        return

    modelo = YOLO(args.modelo)
    print(f"Modelo cargado: {args.modelo}")

    resultado = img.copy()
    bbox = detectar_placa(modelo, img)

    if bbox is None:
        print("Sin placa detectada.")
        cv2.putText(resultado, "Sin placa", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)
    else:
        x1, y1, x2, y2 = bbox
        print(f"Placa: x1={x1} y1={y1} x2={x2} y2={y2}  ({x2-x1}x{y2-y1} px)")
        cv2.rectangle(resultado, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(resultado, "Placa", (x1, y1 - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

    if args.guardar:
        cv2.imwrite(args.guardar, resultado)
        print(f"Guardado: {args.guardar}")
    else:
        cv2.imshow("Deteccion", resultado)
        cv2.waitKey(0)
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
