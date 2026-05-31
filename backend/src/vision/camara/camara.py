"""
Abre la fuente de video (webcam / archivo / stream del celular) y muestra el
feed con las dos lineas inclinadas. Cuando una placa cruza la zona, dispara la
captura del frame mas nitido y se lo pasa al pipeline.

Modo calibracion (CALIBRAR=True): se puede ajustar TODO por interfaz, sin tocar
el codigo:
    - arrastrar los extremos de las lineas con el mouse
    - sliders (arriba de la ventana) para los 3 gates
    - overlay con ancho de placa (px) y nitidez en vivo
    - tecla 's' -> imprime la config actual para pegarla aqui y dejarla fija
"""

import os
import json
import time

import cv2
from lineas import ZonaDeteccion, nitidez


# colores BGR
COLOR_LINEA   = (0, 200, 255)   # amarillo-naranja
COLOR_ZONA    = (0, 255, 0)     # verde (cuando esta rastreando)
COLOR_PLACA   = (0, 255, 0)     # verde: caja de la placa (lo que se rastrea)
COLOR_CARRO   = (255, 128, 0)   # naranja: caja del carro (solo visual)
COLOR_TEXTO   = (255, 255, 255)
COLOR_HANDLE  = (255, 0, 255)   # magenta: puntos arrastrables

CAMARA_IDX    = 0   # 0 = camara por defecto (fallback si no se pasa fuente)
VENTANA_W     = 1600
VENTANA_H     = 900

# lineas inclinadas (fracciones del frame). Calibrar con el video real.
#   ENTRA = lejos (arriba),  SALE = cerca (hacia la camara)
LINEA_ENTRA   = ((0.341875, 0.10888888888888888), (0.28875, 0.5722222222222222))
LINEA_SALE    = ((0.63875, 0.9688888888888889), (0.71625, 0.23555555555555555))

# gates iniciales (se pueden mover con los sliders en modo calibracion)
MIN_ANCHO_PX  = 60
MAX_ANCHO_PX  = 0      # 0 = sin tope
MIN_NITIDEZ   = 40

# distancia REAL en metros entre las dos lineas (para velocidad). Calibrable.
DISTANCIA_M   = 5.0
FPS_FALLBACK  = 30.0   # si la fuente no reporta FPS

# detectar cada N frames (1 = cada frame). Subir a 2-3 si va lento (mas fluido,
# timing de velocidad un poco mas grueso). Reusa el ultimo bbox entre detecciones.
INFERENCIA_CADA = 1

# modo calibracion: sliders + arrastrar lineas + overlay de numeros
CALIBRAR      = True

VENTANA       = "Detector de Placas"

# los frames crudos (carro centrado, con placa) se guardan aqui -> materia prima
CAPTURA_DIR   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "capturas")


# ── dibujo ────────────────────────────────────────────────────────────────

def dibujar_lineas(frame, zona: ZonaDeteccion, calibrar=False):
    h, w = frame.shape[:2]
    e1, e2 = zona.entra_px(w, h)
    s1, s2 = zona.sale_px(w, h)

    color = COLOR_ZONA if zona.estado == "rastreando" else COLOR_LINEA

    cv2.line(frame, e1, e2, color, 2)
    cv2.line(frame, s1, s2, color, 2)

    cv2.putText(frame, "ENTRA", (e1[0] + 5, e1[1] + 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    cv2.putText(frame, "SALE", (s1[0] + 5, s1[1] + 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

    # puntos arrastrables
    if calibrar:
        for p in (e1, e2, s1, s2):
            cv2.circle(frame, p, 8, COLOR_HANDLE, -1)

    cv2.putText(frame, f"Estado: {zona.estado}", (10, h - 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, COLOR_TEXTO, 2)


def dibujar_velocidad(frame, zona):
    """Velocidad del ultimo carro -> SIEMPRE visible (tambien en demo)."""
    if zona.ultima_velocidad is None:
        return
    w = frame.shape[1]
    txt = f"Velocidad: {zona.ultima_velocidad:.1f} km/h"
    cv2.putText(frame, txt, (w - 380, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, COLOR_ZONA, 2)


def dibujar_overlay(frame, zona, bbox):
    """Debug (solo calibracion): ancho/nitidez en vivo + gates + distancia."""
    y = 30
    def linea(txt, ok=None):
        nonlocal y
        col = COLOR_TEXTO if ok is None else ((0, 255, 0) if ok else (0, 0, 255))
        cv2.putText(frame, txt, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2)
        y += 28

    if bbox is not None:
        x1, y1, x2, y2 = bbox
        ancho = x2 - x1
        nit   = nitidez(frame[max(y1, 0):y2, max(x1, 0):x2])
        ok_ancho = ancho >= zona.min_ancho_px and (not zona.max_ancho_px or ancho <= zona.max_ancho_px)
        ok_nit   = nit >= zona.min_nitidez
        linea(f"ancho placa: {ancho}px  (min {zona.min_ancho_px}, max {zona.max_ancho_px or '-'})", ok_ancho)
        linea(f"nitidez: {nit:6.0f}  (min {zona.min_nitidez})", ok_nit)
    else:
        linea("sin deteccion")

    linea(f"distancia: {zona.distancia_m:.1f} m entre lineas")
    linea("s=guardar config  q=salir")


# ── mouse: arrastrar los extremos de las lineas ─────────────────────────────

def _hacer_mouse(estado, zona):
    PTS = [("linea_entra", 0), ("linea_entra", 1),
           ("linea_sale", 0),  ("linea_sale", 1)]

    def set_pt(linea, idx, fx, fy):
        pts = list(getattr(zona, linea))
        pts[idx] = (max(0.0, min(1.0, fx)), max(0.0, min(1.0, fy)))
        setattr(zona, linea, tuple(pts))

    def cb(event, x, y, flags, _param):
        fx, fy = x / VENTANA_W, y / VENTANA_H
        if event == cv2.EVENT_LBUTTONDOWN:
            # agarrar el punto mas cercano (dentro de ~25px)
            mejor, dmin = None, 25
            for i, (linea, idx) in enumerate(PTS):
                px, py = getattr(zona, linea)[idx]
                d = ((px * VENTANA_W - x) ** 2 + (py * VENTANA_H - y) ** 2) ** 0.5
                if d < dmin:
                    mejor, dmin = i, d
            estado["arrastrando"] = mejor
        elif event == cv2.EVENT_MOUSEMOVE and estado["arrastrando"] is not None:
            linea, idx = PTS[estado["arrastrando"]]
            set_pt(linea, idx, fx, fy)
        elif event == cv2.EVENT_LBUTTONUP:
            estado["arrastrando"] = None

    return cb


def _crear_trackbars(zona):
    cv2.createTrackbar("min_ancho", VENTANA, zona.min_ancho_px, 400,
                       lambda v: setattr(zona, "min_ancho_px", v))
    cv2.createTrackbar("max_ancho", VENTANA, zona.max_ancho_px, 600,
                       lambda v: setattr(zona, "max_ancho_px", v))
    cv2.createTrackbar("min_nitidez", VENTANA, int(zona.min_nitidez), 300,
                       lambda v: setattr(zona, "min_nitidez", float(v)))
    # distancia en cm (slider entero) -> metros
    cv2.createTrackbar("dist_cm", VENTANA, int(zona.distancia_m * 100), 3000,
                       lambda v: setattr(zona, "distancia_m", max(v, 1) / 100.0))


def _imprimir_config(zona):
    print("\n--- Pega esto en camara.py para fijar la calibracion ---")
    print(f"LINEA_ENTRA   = {zona.linea_entra}")
    print(f"LINEA_SALE    = {zona.linea_sale}")
    print(f"MIN_ANCHO_PX  = {zona.min_ancho_px}")
    print(f"MAX_ANCHO_PX  = {zona.max_ancho_px}")
    print(f"MIN_NITIDEZ   = {int(zona.min_nitidez)}")
    print(f"DISTANCIA_M   = {zona.distancia_m:.2f}")
    print("--------------------------------------------------------\n")


# ── guardar captura (carpeta por carro: entra/mejor/sale + datos.json) ──────

def _guardar_captura(captura, nombre, carpeta_captura, al_capturar):
    """
    Crea capturas/<nombre>/ con entra.jpg, mejor.jpg, sale.jpg y datos.json
    (solo metricas de camara). Luego entrega el mejor frame al pipeline.
    """
    carpeta = os.path.join(carpeta_captura, nombre)
    os.makedirs(carpeta, exist_ok=True)

    if captura["entra"] is not None:
        cv2.imwrite(os.path.join(carpeta, "entra.jpg"), captura["entra"])
    cv2.imwrite(os.path.join(carpeta, "mejor.jpg"), captura["mejor"])
    if captura["sale"] is not None:
        cv2.imwrite(os.path.join(carpeta, "sale.jpg"), captura["sale"])

    # metricas de la CAMARA (la placa la resuelve el pipeline, capa aparte)
    vel = captura["velocidad"]
    dt  = captura["tiempo_cruce"]
    datos = {
        "carro":           nombre,
        "con_placa":       captura.get("con_placa", None),  # False = mejor es respaldo de carro (sin placa detectada en vivo)
        "velocidad_kmh":   round(vel, 1) if vel is not None else None,
        "tiempo_cruce_s":  round(dt, 3) if dt is not None else None,
        "nitidez":         round(captura["nitidez"], 1),
        "ancho_placa_px":  captura["ancho_px"],  # 0 si con_placa=False
        "hora":            time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(os.path.join(carpeta, "datos.json"), "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=2, ensure_ascii=False)

    vel_txt = f"{vel:.1f} km/h" if vel is not None else "n/d"
    print(f"Carro {nombre}: vel={vel_txt}  -> {carpeta}")

    # entregar el mejor frame al pipeline (etapa 0 -> OCR), si esta enganchado.
    # se pasa la velocidad para que el backend la registre en el evento/DB.
    if al_capturar is not None:
        al_capturar(nombre, captura["mejor"], vel if vel is not None else 0.0)


# ── loop principal ──────────────────────────────────────────────────────────

def iniciar(detector=None, al_capturar=None, carpeta_captura=CAPTURA_DIR,
            fuente=CAMARA_IDX, on_frame=None, on_fps=None):
    """
    Abre la fuente de video y corre el loop principal.

    Args:
        detector: funcion(frame) -> (carro_bbox, placa_bbox) en coords del frame;
                  cualquiera puede ser None. El carro maneja el cruce; la placa
                  aporta el crop.
        al_capturar: callback (nombre, frame, velocidad) que corre el pipeline
                  (etapa 0 -> OCR). La velocidad va en km/h (0.0 si no medible).
        carpeta_captura: donde se guarda el frame crudo (por defecto camara/capturas/).
        fuente: de donde sale el video. Puede ser:
                - int  (0, 1, ...)            -> webcam fisica
                - ruta ("video.mp4")         -> archivo grabado (desarrollo)
                - URL  ("http://ip:port/...") -> celular via DroidCam/IP Webcam (demo)
        on_frame: callback opcional(jpeg_bytes) con CADA frame ya anotado, en JPEG.
                  Lo usa el backend para el feed MJPEG. None = no se usa (standalone).
        on_fps:   callback opcional(fps:float) ~1 vez por segundo con el FPS real.
                  Lo usa el backend para el status por WebSocket. None = no se usa.

    on_frame / on_fps son los UNICOS puentes con el backend. Si no se pasan, esta
    camara es 100% standalone: no sabe nada de web ni de base de datos.
    """
    es_archivo = isinstance(fuente, str) and "://" not in fuente

    cap = cv2.VideoCapture(fuente)
    if not cap.isOpened():
        print(f"No se pudo abrir la fuente: {fuente}")
        return

    if not es_archivo:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  VENTANA_W)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, VENTANA_H)
        # buffer minimo: evita que el stream del celu acumule lag (frames viejos)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    os.makedirs(carpeta_captura, exist_ok=True)

    # FPS de la fuente (para convertir frames -> segundos en video grabado)
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps <= 0:
        fps = FPS_FALLBACK

    zona = ZonaDeteccion(linea_entra=LINEA_ENTRA, linea_sale=LINEA_SALE,
                         min_ancho_px=MIN_ANCHO_PX, max_ancho_px=MAX_ANCHO_PX,
                         min_nitidez=MIN_NITIDEZ, distancia_m=DISTANCIA_M)
    capturas_guardadas = 0
    bbox        = None    # placa (lo que se rastrea)
    carro_bbox  = None    # carro (solo visual)
    n_frame     = 0

    # medicion de FPS real para el hook on_fps (se emite ~1 vez por segundo)
    fps_t0      = time.time()
    fps_frames  = 0

    print("Fuente abierta. Q=salir.", "Calibracion ON (s=guardar config)." if CALIBRAR else "")
    print(f"Capturas -> {carpeta_captura}")

    cv2.namedWindow(VENTANA, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(VENTANA, VENTANA_W, VENTANA_H)

    if CALIBRAR:
        _crear_trackbars(zona)
        estado_mouse = {"arrastrando": None}
        cv2.setMouseCallback(VENTANA, _hacer_mouse(estado_mouse, zona))

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame = cv2.resize(frame, (VENTANA_W, VENTANA_H))
        n_frame += 1

        # tiempo de este frame: video -> frame/FPS ; vivo -> reloj real
        t = (n_frame / fps) if es_archivo else time.time()

        if detector is not None and n_frame % INFERENCIA_CADA == 0:
            carro_bbox, bbox = detector(frame)

        captura = zona.actualizar(frame, carro_bbox, bbox, t)

        if captura is not None:
            capturas_guardadas += 1
            nombre = f"{time.strftime('%Y%m%d_%H%M%S')}_carro{capturas_guardadas:03d}"
            _guardar_captura(captura, nombre, carpeta_captura, al_capturar)

        # --- dibujar ---
        dibujar_lineas(frame, zona, calibrar=CALIBRAR)

        # caja del carro (naranja): solo si su centro cae dentro de la zona
        if carro_bbox is not None:
            cx1, cy1, cx2, cy2 = carro_bbox
            ccx, ccy = (cx1 + cx2) / 2, (cy1 + cy2) / 2
            if zona.punto_en_zona(ccx, ccy, VENTANA_W, VENTANA_H):
                cv2.rectangle(frame, (cx1, cy1), (cx2, cy2), COLOR_CARRO, 2)
                cv2.putText(frame, "Carro", (cx1, max(cy1 - 8, 10)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, COLOR_CARRO, 2)

        # dibujar la placa SOLO si su centro cae dentro de la zona ENTRA-SALE
        if bbox is not None:
            x1, y1, x2, y2 = bbox
            xc, yc = (x1 + x2) / 2, (y1 + y2) / 2
            if zona.punto_en_zona(xc, yc, VENTANA_W, VENTANA_H):
                cv2.rectangle(frame, (x1, y1), (x2, y2), COLOR_PLACA, 2)
                cv2.putText(frame, "Placa", (x1, y1 - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, COLOR_PLACA, 2)

        dibujar_velocidad(frame, zona)   # velocidad: siempre visible (demo incluida)

        if CALIBRAR:
            dibujar_overlay(frame, zona, bbox)

        # hook MJPEG: entregar el frame YA anotado (lineas + cajas) al backend
        if on_frame is not None:
            ok_enc, buf = cv2.imencode(".jpg", frame)
            if ok_enc:
                on_frame(buf.tobytes())

        # hook status: emitir el FPS real ~1 vez por segundo
        fps_frames += 1
        if on_fps is not None:
            ahora = time.time()
            if ahora - fps_t0 >= 1.0:
                on_fps(fps_frames / (ahora - fps_t0))
                fps_t0, fps_frames = ahora, 0

        cv2.imshow(VENTANA, frame)

        tecla = cv2.waitKey(1) & 0xFF
        if tecla == ord("q"):
            break
        if tecla == ord("s") and CALIBRAR:
            _imprimir_config(zona)

    cap.release()
    cv2.destroyAllWindows()
    print(f"Capturas guardadas: {capturas_guardadas}")
