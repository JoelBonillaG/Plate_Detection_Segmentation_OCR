"""
ETAPA 0 - deteccion: localizar el vehiculo en un frame con el modelo YOLOv11
entrenado desde cero (best.pt).

Por tiempo, se toma SOLO el carro de mayor confianza (igual que la placa),
aunque haya varios en el frame.
"""

from ultralytics import YOLO


def cargar_yolo(ruta_modelo):
    """Carga el modelo entrenado (.pt) y lo devuelve."""
    return YOLO(ruta_modelo)


def detectar(modelo, frame, conf=0.25, imgsz=640):
    """
    Detecta vehiculos en el frame (BGR).
    Devuelve (x1, y1, x2, y2) del carro mas confiable, o None.
    """
    r = modelo(frame, conf=conf, imgsz=imgsz, verbose=False)[0]
    if r.boxes is None or len(r.boxes) == 0:
        return None
    i = int(r.boxes.conf.argmax())                       # caja mas confiable
    return r.boxes.xyxy[i].cpu().int().tolist()
