"""
Utilidad: detecta que indices de camara estan disponibles.
Abre los indices 0..N, captura un frame de cada uno que funcione y lo guarda
como cam_<i>.jpg. Mira los .jpg para identificar cual es DroidCam (el celular).

Uso:
    python listar_camaras.py
"""
import cv2

MAX_INDICE = 5

for i in range(MAX_INDICE + 1):
    cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)   # CAP_DSHOW = enumera rapido en Windows
    if not cap.isOpened():
        print(f"indice {i}: (no disponible)")
        cap.release()
        continue
    ok, frame = cap.read()
    if ok and frame is not None:
        h, w = frame.shape[:2]
        cv2.imwrite(f"cam_{i}.jpg", frame)
        print(f"indice {i}: OK  {w}x{h}  -> cam_{i}.jpg")
    else:
        print(f"indice {i}: abre pero NO entrega frame")
    cap.release()

print("\nListo. Abre los cam_<i>.jpg y mira cual muestra lo que apunta el celular.")
