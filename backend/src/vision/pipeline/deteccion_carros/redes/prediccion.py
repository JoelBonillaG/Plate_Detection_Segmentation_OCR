"""
Carga el modelo YOLOv11 de vehiculos entrenado y detecta los carros en una imagen/frame.

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
ETAPA  = os.path.dirname(BASE)                         # deteccion_carros/

# config de la etapa (deteccion_carros/config.json): ruta del modelo, confianza, imgsz
with open(os.path.join(ETAPA, "config.json"), encoding="utf-8") as _f:
    _CFG = json.load(_f)

RUTA_MODELO = os.path.normpath(os.path.join(ETAPA, _CFG["modelo"]))
CONF_MIN    = _CFG.get("conf_min", 0.25)   # confianza minima para aceptar una deteccion
IMGSZ       = _CFG.get("imgsz", 640)        # mismo tamano con el que se entreno


def detectar_carro(modelo, imagen_bgr):
    """
    Recibe imagen BGR.
    Devuelve (x1,y1,x2,y2) del carro mas confiable, o None.
    """
    r = modelo(imagen_bgr, conf=CONF_MIN, imgsz=IMGSZ, verbose=False)[0]
    if r.boxes is None or len(r.boxes) == 0:
        return None
    i = int(r.boxes.conf.argmax())
    return r.boxes.xyxy[i].cpu().int().tolist()


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
    bbox = detectar_carro(modelo, img)

    if bbox is None:
        print("Sin carros detectados.")
        cv2.putText(resultado, "Sin carros", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)
    else:
        x1, y1, x2, y2 = bbox
        print(f"Carro: x1={x1} y1={y1} x2={x2} y2={y2}  ({x2-x1}x{y2-y1} px)")
        cv2.rectangle(resultado, (x1, y1), (x2, y2), (255, 128, 0), 2)
        cv2.putText(resultado, "Carro", (x1, max(y1 - 8, 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 128, 0), 2)

    if args.guardar:
        cv2.imwrite(args.guardar, resultado)
        print(f"Guardado: {args.guardar}")
    else:
        cv2.imshow("Deteccion carros", resultado)
        cv2.waitKey(0)
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
