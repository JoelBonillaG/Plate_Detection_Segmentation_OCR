"""
Etapa 1 - deteccion: localizar la placa en un frame con el modelo YOLOv11
entrenado desde cero (best.pt).
"""

from ultralytics import YOLO


def cargar_yolo(ruta_modelo):
    """Carga el modelo entrenado (.pt) y lo devuelve."""
    return YOLO(ruta_modelo)


def detectar(modelo, frame, conf=0.25, imgsz=416, return_conf=False):
    """
    Detecta placas en el frame (BGR).
    Devuelve (x1, y1, x2, y2) de la placa mas confiable, o None.
    Con return_conf=True devuelve (bbox, confianza) o (None, None).
    """
    r = modelo(frame, conf=conf, imgsz=imgsz, verbose=False)[0]
    if r.boxes is None or len(r.boxes) == 0:
        return (None, None) if return_conf else None
    i = int(r.boxes.conf.argmax())
    bbox = r.boxes.xyxy[i].cpu().int().tolist()
    if return_conf:
        return bbox, float(r.boxes.conf[i].cpu())
    return bbox
