"""
Abre la fuente de video (webcam / archivo / stream del celular) y muestra el
feed con las dos lineas inclinadas. Cuando una placa cruza la zona, dispara la
captura del frame mas nitido y se lo pasa al pipeline.

Toda la configuracion ajustable vive en camara/config.json (no en el codigo).
Lo que esta abajo solo LEE ese archivo y expone los valores como constantes del
modulo (asi el resto del codigo y `from camara import DETECTAR_CARROS` siguen
funcionando igual).

Modo calibracion (calibrar=true en config.json): se puede ajustar TODO por
interfaz, sin tocar el codigo:
    - arrastrar los extremos de las lineas con el mouse
    - sliders (arriba de la ventana) para los 3 gates
    - overlay con ancho de placa (px) y nitidez en vivo
    - tecla 's' -> guarda la calibracion actual en config.json
"""

import os
import json
import time

import cv2
from lineas import ZonaDeteccion, nitidez


_AQUI       = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(_AQUI, "config.json")

# valores por defecto -> sirven si falta config.json o alguna clave (no rompe).
_DEFAULTS = {
    "camara_idx": 0,
    "ventana_w": 1600,
    "ventana_h": 900,
    "stream_w": 640,
    "stream_jpeg_q": 60,
    "linea_entra": [[0.341875, 0.10888888888888888], [0.28875, 0.5722222222222222]],
    "linea_sale":  [[0.63875, 0.9688888888888889], [0.71625, 0.23555555555555555]],
    "min_ancho_px": 60,
    "max_ancho_px": 0,
    "min_nitidez": 40,
    "distancia_m": 5.0,
    "fps_fallback": 30.0,
    "inferencia_cada": 1,
    "detectar_carros": True,
    "tolerancia_carro": 3,
    "tolerancia_placa": 8,
    "calibrar": False,
    "mostrar_ventana": False,
    # reconexion: SOLO para fuentes en vivo (webcam/IP/RTSP). Con video grabado
    # se ignora (al terminar el archivo el loop sale normal).
    #   reconectar=false (default) -> un fallo de frame termina el loop (modo video).
    #   reconectar=true            -> si la camara en vivo falla, reintenta reabrir.
    "reconectar": False,
    "espera_entre_reintentos_s": 2.0,    # segundos entre reintentos de reapertura
    "frames_antes_de_reconectar": 30,    # frames sin leer seguidos antes de reabrir
}


def cargar_config():
    """Lee camara/config.json sobre los defaults. Claves faltantes usan default."""
    cfg = dict(_DEFAULTS)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except FileNotFoundError:
        print(f"[CONFIG] {CONFIG_PATH} no existe -> usando valores por defecto.")
    return cfg


def _par_lineas(p):
    """[[x1,y1],[x2,y2]] (JSON) -> ((x1,y1),(x2,y2)) de floats (lo que usa lineas)."""
    (a, b), (c, d) = p
    return ((float(a), float(b)), (float(c), float(d)))


CFG = cargar_config()

# colores BGR (constantes visuales: no son configuracion, viven en el codigo)
COLOR_LINEA   = (0, 200, 255)   # amarillo-naranja
COLOR_ZONA    = (0, 255, 0)     # verde (cuando esta rastreando)
COLOR_PLACA   = (75, 130, 30)   # verde esmeralda (BGR): caja + etiqueta de la placa
COLOR_CARRO   = (120, 65, 25)   # azul acero (BGR): caja + etiqueta del carro
COLOR_TEXTO   = (255, 255, 255)
COLOR_HANDLE  = (255, 0, 255)   # magenta: puntos arrastrables

# ── valores leidos de config.json (ver _DEFAULTS para que es cada uno) ────────
CAMARA_IDX      = CFG["camara_idx"]
VENTANA_W       = CFG["ventana_w"]
VENTANA_H       = CFG["ventana_h"]
STREAM_W        = CFG["stream_w"]
STREAM_JPEG_Q   = CFG["stream_jpeg_q"]
LINEA_ENTRA     = _par_lineas(CFG["linea_entra"])
LINEA_SALE      = _par_lineas(CFG["linea_sale"])
MIN_ANCHO_PX    = CFG["min_ancho_px"]
MAX_ANCHO_PX    = CFG["max_ancho_px"]
MIN_NITIDEZ     = CFG["min_nitidez"]
DISTANCIA_M     = CFG["distancia_m"]
FPS_FALLBACK    = CFG["fps_fallback"]
INFERENCIA_CADA = CFG["inferencia_cada"]
DETECTAR_CARROS = CFG["detectar_carros"]
TOLERANCIA_CARRO = CFG["tolerancia_carro"]
TOLERANCIA_PLACA = CFG["tolerancia_placa"]
CALIBRAR        = CFG["calibrar"]
MOSTRAR_VENTANA = CFG["mostrar_ventana"]
RECONECTAR           = CFG["reconectar"]
RECONECTAR_ESPERA    = CFG["espera_entre_reintentos_s"]
RECONECTAR_MAX_FALLOS = CFG["frames_antes_de_reconectar"]

VENTANA       = "Detector de Placas"

# los frames crudos (carro centrado, con placa) se guardan aqui -> materia prima
CAPTURA_DIR   = os.path.join(_AQUI, "capturas")


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


def dibujar_caja_etiqueta(frame, bbox, etiqueta, color):
    """
    Caja del detector con etiqueta de fondo relleno y texto blanco (estilo limpio,
    como las cajas tipicas de YOLO). La barra va arriba de la caja; si no cabe
    (caja pegada al borde superior), se dibuja por dentro.
    """
    x1, y1, x2, y2 = bbox
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

    fuente, escala, grosor = cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2
    (tw, th), base = cv2.getTextSize(etiqueta, fuente, escala, grosor)
    pad = 6
    y_barra = y1 - (th + base + pad)
    if y_barra < 0:               # no cabe arriba -> barra por dentro de la caja
        y_barra = y1
    cv2.rectangle(frame, (x1, y_barra),
                  (x1 + tw + 2 * pad, y_barra + th + base + pad), color, -1)
    cv2.putText(frame, etiqueta, (x1 + pad, y_barra + th + pad),
                fuente, escala, COLOR_TEXTO, grosor, cv2.LINE_AA)


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


def _guardar_config(zona):
    """Tecla 's' en calibracion: vuelca lineas + gates + distancia a config.json
    (conserva las demas claves). Asi la calibracion queda fija sin tocar codigo."""
    cfg = cargar_config()
    cfg["linea_entra"] = [list(p) for p in zona.linea_entra]
    cfg["linea_sale"]  = [list(p) for p in zona.linea_sale]
    cfg["min_ancho_px"] = zona.min_ancho_px
    cfg["max_ancho_px"] = zona.max_ancho_px
    cfg["min_nitidez"]  = int(zona.min_nitidez)
    cfg["distancia_m"]  = round(zona.distancia_m, 2)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    print(f"\n[CONFIG] Calibracion guardada en {CONFIG_PATH}\n")


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

def _abrir_fuente(fuente, es_archivo):
    """
    Abre la fuente de video y, si es un stream en vivo, aplica resolucion +
    buffer minimo. Devuelve el VideoCapture (el llamador revisa cap.isOpened()).
    Se reusa en la apertura inicial y en cada reintento de reconexion.
    """
    cap = cv2.VideoCapture(fuente)
    if cap.isOpened() and not es_archivo:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  VENTANA_W)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, VENTANA_H)
        # buffer minimo: evita que el stream en vivo acumule lag (frames viejos)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


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

    cap = _abrir_fuente(fuente, es_archivo)
    if not cap.isOpened():
        print(f"No se pudo abrir la fuente: {fuente}")
        return

    os.makedirs(carpeta_captura, exist_ok=True)

    # FPS de la fuente (para convertir frames -> segundos en video grabado)
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps <= 0:
        fps = FPS_FALLBACK

    rastrear_por = "carro" if DETECTAR_CARROS else "placa"
    tolerancia   = TOLERANCIA_CARRO if DETECTAR_CARROS else TOLERANCIA_PLACA
    zona = ZonaDeteccion(linea_entra=LINEA_ENTRA, linea_sale=LINEA_SALE,
                         min_ancho_px=MIN_ANCHO_PX, max_ancho_px=MAX_ANCHO_PX,
                         min_nitidez=MIN_NITIDEZ, distancia_m=DISTANCIA_M,
                         tolerancia_frames=tolerancia, rastrear_por=rastrear_por)
    capturas_guardadas = 0
    bbox        = None    # placa (lo que se rastrea)
    carro_bbox  = None    # carro (solo visual)
    n_frame     = 0

    # medicion de FPS real para el hook on_fps (se emite ~1 vez por segundo)
    fps_t0      = time.time()
    fps_frames  = 0

    salir = "Q=salir." if MOSTRAR_VENTANA else "Ctrl+C=salir (headless, solo MJPEG)."
    print("Fuente abierta.", salir, "Calibracion ON (s=guardar config)." if (CALIBRAR and MOSTRAR_VENTANA) else "")
    print(f"Capturas -> {carpeta_captura}")

    if MOSTRAR_VENTANA:
        cv2.namedWindow(VENTANA, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(VENTANA, VENTANA_W, VENTANA_H)

        # sliders + mouse solo con ventana (HighGUI los necesita)
        if CALIBRAR:
            _crear_trackbars(zona)
            estado_mouse = {"arrastrando": None}
            cv2.setMouseCallback(VENTANA, _hacer_mouse(estado_mouse, zona))

    fallos_lectura = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            # video grabado terminado, o reconexion desactivada -> salir normal
            if es_archivo or not RECONECTAR:
                break
            # fuente EN VIVO caida: no matar el loop, reintentar reabrir.
            fallos_lectura += 1
            if fallos_lectura == 1:
                print("[CAMARA] sin frames de la fuente en vivo...")
            if fallos_lectura >= RECONECTAR_MAX_FALLOS:
                print(f"[CAMARA] reabriendo {fuente} (espera {RECONECTAR_ESPERA}s)...")
                cap.release()
                time.sleep(RECONECTAR_ESPERA)
                cap = _abrir_fuente(fuente, es_archivo)
                fallos_lectura = 0
            continue
        fallos_lectura = 0

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

        # caja del carro (azul): solo si su centro cae dentro de la zona
        if carro_bbox is not None:
            cx1, cy1, cx2, cy2 = carro_bbox
            ccx, ccy = (cx1 + cx2) / 2, (cy1 + cy2) / 2
            if zona.punto_en_zona(ccx, ccy, VENTANA_W, VENTANA_H):
                dibujar_caja_etiqueta(frame, carro_bbox, "Carro", COLOR_CARRO)

        # caja de la placa (verde): SOLO si su centro cae dentro de la zona ENTRA-SALE
        if bbox is not None:
            x1, y1, x2, y2 = bbox
            xc, yc = (x1 + x2) / 2, (y1 + y2) / 2
            if zona.punto_en_zona(xc, yc, VENTANA_W, VENTANA_H):
                dibujar_caja_etiqueta(frame, bbox, "Placa vehicular", COLOR_PLACA)

        dibujar_velocidad(frame, zona)   # velocidad: siempre visible (demo incluida)

        if CALIBRAR:
            dibujar_overlay(frame, zona, bbox)

        # hook MJPEG: entregar el frame YA anotado (lineas + cajas) al backend.
        # Se encoge + baja calidad SOLO para el stream (el browser decodifica menos).
        if on_frame is not None:
            stream_frame = frame
            if STREAM_W and STREAM_W < VENTANA_W:
                h_s = int(VENTANA_H * STREAM_W / VENTANA_W)
                stream_frame = cv2.resize(frame, (STREAM_W, h_s))
            ok_enc, buf = cv2.imencode(".jpg", stream_frame,
                                       [cv2.IMWRITE_JPEG_QUALITY, STREAM_JPEG_Q])
            if ok_enc:
                on_frame(buf.tobytes())

        # hook status: emitir el FPS real ~1 vez por segundo
        fps_frames += 1
        if on_fps is not None:
            ahora = time.time()
            if ahora - fps_t0 >= 1.0:
                on_fps(fps_frames / (ahora - fps_t0))
                fps_t0, fps_frames = ahora, 0

        # headless: sin imshow/waitKey -> el estado de la ventana no frena el loop
        if MOSTRAR_VENTANA:
            cv2.imshow(VENTANA, frame)
            tecla = cv2.waitKey(1) & 0xFF
            if tecla == ord("q"):
                break
            if tecla == ord("s") and CALIBRAR:
                _guardar_config(zona)

    cap.release()
    if MOSTRAR_VENTANA:
        cv2.destroyAllWindows()
    print(f"Capturas guardadas: {capturas_guardadas}")
