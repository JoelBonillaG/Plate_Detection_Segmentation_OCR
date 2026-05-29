"""
Abre la camara y muestra el feed con las dos lineas virtuales dibujadas.
Listo para conectar el detector de placas.
"""

import os
import time

import cv2
from lineas import ZonaDeteccion


# colores BGR
COLOR_LINEA   = (0, 200, 255)   # amarillo-naranja
COLOR_ZONA    = (0, 255, 0)     # verde (cuando esta rastreando)
COLOR_TEXTO   = (255, 255, 255)

CAMARA_IDX    = 0   # 0 = camara por defecto
VENTANA_W     = 1600
VENTANA_H     = 900

# posicion de las dos barras (fraccion del ancho) - mas separadas = zona amplia
ZONA_IZQ      = 0.15
ZONA_DER      = 0.85

# los frames crudos (carro centrado, con placa) se guardan aqui -> materia prima
CAPTURA_DIR   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "capturas")


def dibujar_lineas(frame, zona: ZonaDeteccion):
    h, w = frame.shape[:2]
    xi = zona.x_izq(w)
    xd = zona.x_der(w)

    color = COLOR_ZONA if zona.estado == "rastreando" else COLOR_LINEA

    # lineas verticales
    cv2.line(frame, (xi, 0), (xi, h), color, 2)
    cv2.line(frame, (xd, 0), (xd, h), color, 2)

    # etiquetas
    cv2.putText(frame, "L", (xi + 5, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
    cv2.putText(frame, "R", (xd + 5, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)

    # estado
    cv2.putText(frame, f"Estado: {zona.estado}", (10, h - 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, COLOR_TEXTO, 2)


def iniciar(detector=None, al_capturar=None, carpeta_captura=CAPTURA_DIR):
    """
    Abre la camara y corre el loop principal.

    Args:
        detector: funcion que recibe un frame BGR y devuelve (x1,y1,x2,y2) o None.
        al_capturar: callback (nombre, frame) que se llama cuando un carro con
                     placa cruza la zona. Aqui se engancha el pipeline (etapa 1 -> OCR).
        carpeta_captura: donde se guarda el frame crudo (por defecto camara/capturas/).
    """
    cap = cv2.VideoCapture(CAMARA_IDX)
    if not cap.isOpened():
        print("No se pudo abrir la camara.")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  VENTANA_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, VENTANA_H)

    os.makedirs(carpeta_captura, exist_ok=True)

    zona = ZonaDeteccion(pos_izq=ZONA_IZQ, pos_der=ZONA_DER)
    capturas_guardadas = 0
    bbox        = None   # ultimo bbox detectado
    n_frame     = 0
    INFERENCIA_CADA = 1  # GPU: detectar en cada frame (YOLO11n ~4ms)

    print("Camara abierta. Presiona Q para salir.")
    print(f"Capturas -> {carpeta_captura}")

    # ventana redimensionable, abierta al tamano configurado
    cv2.namedWindow("Detector de Placas", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Detector de Placas", VENTANA_W, VENTANA_H)

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # redimensionar por si la camara no soporta la resolucion pedida
        frame = cv2.resize(frame, (VENTANA_W, VENTANA_H))
        n_frame += 1

        # --- deteccion (cada N frames) ---
        if detector is not None and n_frame % INFERENCIA_CADA == 0:
            bbox = detector(frame)

        # --- logica de lineas ---
        frame_capturado = zona.actualizar(frame, bbox)

        if frame_capturado is not None:
            capturas_guardadas += 1
            nombre = f"captura_{time.strftime('%Y%m%d_%H%M%S')}_{capturas_guardadas:03d}"
            # guardar frame crudo (materia prima) en camara/capturas/
            ruta = os.path.join(carpeta_captura, f"{nombre}.jpg")
            cv2.imwrite(ruta, frame_capturado)
            print(f"Captura guardada: {ruta}")
            # pasar el frame al pipeline (etapa 1 -> OCR), si esta enganchado
            if al_capturar is not None:
                al_capturar(nombre, frame_capturado)

        # --- dibujar ---
        dibujar_lineas(frame, zona)

        if bbox is not None:
            x1, y1, x2, y2 = bbox
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(frame, "Placa", (x1, y1 - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        cv2.imshow("Detector de Placas", frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()
    print(f"Capturas guardadas: {capturas_guardadas}")
