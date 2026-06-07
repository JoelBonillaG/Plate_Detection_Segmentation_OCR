"""
Abre la fuente de video (webcam / archivo / stream del celular) y muestra el
feed con las dos lineas inclinadas. Cuando una placa cruza la zona, dispara la
captura del frame mas nitido y se lo pasa al pipeline.

Toda la configuracion ajustable vive en camara/config.json (no en el codigo).
Lo que esta abajo solo LEE ese archivo y expone los valores como constantes del
modulo (asi el resto del codigo y `from camara import DETECTAR_CARROS` siguen
funcionando igual).

Modo calibracion (calibrar=true en config.json): los parametros principales se
pueden ajustar desde la interfaz:
    - arrastrar los extremos de las lineas con el mouse
    - sliders (arriba de la ventana) para los 3 gates
    - overlay con ancho de placa (px) y nitidez en vivo
    - tecla 's' -> guarda la calibracion actual en config.json
"""

import os
import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor

import cv2
from lineas import ZonaDeteccion, nitidez


_AQUI       = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(_AQUI, "config.json")

# Valores por defecto usados cuando falta config.json o alguna clave.
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

# Paleta BGR para el overlay de monitoreo.
COLOR_ENTRA   = (255, 176, 0)    # azul-cian: linea LEJANA (entra)
COLOR_SALE    = (140, 210, 64)   # verde-teal: linea CERCANA (sale)
COLOR_TRACK   = (96, 220, 130)   # verde: zona rastreando (acento activo)
COLOR_PLACA   = (96, 200, 96)    # verde: caja de la placa
COLOR_CARRO   = (200, 144, 56)   # azul acero: caja del carro
COLOR_TEXTO   = (240, 240, 240)  # casi blanco
COLOR_MUTED   = (184, 163, 148)  # gris-slate: texto secundario
COLOR_ALERTA  = (80, 80, 235)    # rojo suave: valor fuera de rango
COLOR_HANDLE  = (200, 120, 255)  # magenta suave: puntos arrastrables
_PANEL_BG     = (28, 20, 12)     # fondo de panel (navy/slate oscuro)
_PANEL_BORDE  = (70, 52, 38)     # borde sutil del panel
_FUENTE       = cv2.FONT_HERSHEY_SIMPLEX

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

# Directorio donde se almacenan los frames capturados para auditoria.
CAPTURA_DIR   = os.path.join(_AQUI, "capturas")


# ── dibujo ────────────────────────────────────────────────────────────────
# El overlay usa bordes suavizados, etiquetas con fondo y paneles
# semitransparentes para mantener legibilidad sobre el video.

def _texto(frame, txt, org, escala=0.5, color=COLOR_TEXTO, grosor=1):
    cv2.putText(frame, txt, org, _FUENTE, escala, color, grosor, cv2.LINE_AA)


def _chip(frame, txt, org, color, escala=0.46):
    """Etiqueta 'chip': fondo relleno del color + texto blanco. org = esquina sup-izq."""
    (tw, th), base = cv2.getTextSize(txt, _FUENTE, escala, 1)
    px, py = 7, 5
    x, y = org
    cv2.rectangle(frame, (x, y), (x + tw + 2 * px, y + th + base + 2 * py),
                  color, -1, cv2.LINE_AA)
    _texto(frame, txt, (x + px, y + th + py), escala, (255, 255, 255), 1)


def _panel(frame, x, y, w, filas, titulo=None):
    """Panel semi-transparente con filas [(texto, color), ...] y titulo opcional."""
    pad, lh = 12, 24
    n = len(filas) + (1 if titulo else 0)
    h = pad * 2 + lh * n
    cap = frame.copy()
    cv2.rectangle(cap, (x, y), (x + w, y + h), _PANEL_BG, -1)
    cv2.addWeighted(cap, 0.66, frame, 0.34, 0, frame)
    cv2.rectangle(frame, (x, y), (x + w, y + h), _PANEL_BORDE, 1, cv2.LINE_AA)
    yy = y + pad + 15
    if titulo:
        _texto(frame, titulo, (x + pad, yy), 0.5, COLOR_TEXTO, 1)
        yy += lh
    for txt, color in filas:
        _texto(frame, txt, (x + pad, yy), 0.48, color, 1)
        yy += lh


def dibujar_lineas(frame, zona: ZonaDeteccion, calibrar=False):
    h, w = frame.shape[:2]
    e1, e2 = zona.entra_px(w, h)
    s1, s2 = zona.sale_px(w, h)

    rastreando = zona.estado == "rastreando"
    col_e = COLOR_TRACK if rastreando else COLOR_ENTRA
    col_s = COLOR_TRACK if rastreando else COLOR_SALE

    cv2.line(frame, e1, e2, col_e, 2, cv2.LINE_AA)
    cv2.line(frame, s1, s2, col_s, 2, cv2.LINE_AA)

    _chip(frame, "ENTRA", (e1[0] + 6, e1[1] + 6), col_e)
    _chip(frame, "SALE",  (s1[0] + 6, s1[1] + 6), col_s)

    # puntos arrastrables (solo calibracion): relleno + anillo blanco
    if calibrar:
        for p in (e1, e2, s1, s2):
            cv2.circle(frame, p, 6, COLOR_HANDLE, -1, cv2.LINE_AA)
            cv2.circle(frame, p, 6, (255, 255, 255), 1, cv2.LINE_AA)

    # pildora de estado, abajo-izquierda (siempre)
    estado_txt = "RASTREANDO" if rastreando else "ESPERANDO"
    _chip(frame, estado_txt, (12, h - 32), COLOR_TRACK if rastreando else COLOR_MUTED)


def dibujar_caja_etiqueta(frame, bbox, etiqueta, color):
    """Caja del detector con etiqueta tipo chip (fondo relleno, texto blanco). La
    barra va arriba de la caja; si no cabe (pegada al borde), se dibuja por dentro."""
    x1, y1, x2, y2 = bbox
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2, cv2.LINE_AA)

    escala, grosor = 0.5, 1
    (tw, th), base = cv2.getTextSize(etiqueta, _FUENTE, escala, grosor)
    pad = 6
    y_barra = y1 - (th + base + pad)
    if y_barra < 0:               # no cabe arriba -> barra por dentro de la caja
        y_barra = y1
    cv2.rectangle(frame, (x1, y_barra),
                  (x1 + tw + 2 * pad, y_barra + th + base + pad), color, -1, cv2.LINE_AA)
    _texto(frame, etiqueta, (x1 + pad, y_barra + th + pad), escala, (255, 255, 255), grosor)


def dibujar_velocidad(frame, zona):
    """Velocidad del ultimo carro en un panel limpio arriba-derecha (siempre visible)."""
    if zona.ultima_velocidad is None:
        return
    w = frame.shape[1]
    txt = f"{zona.ultima_velocidad:.1f} km/h"
    (tw, th), base = cv2.getTextSize(txt, _FUENTE, 0.7, 2)
    x1 = w - tw - 28
    y1 = 14
    x2 = w - 12
    y2 = y1 + th + base + 16
    cap = frame.copy()
    cv2.rectangle(cap, (x1, y1), (x2, y2), _PANEL_BG, -1)
    cv2.addWeighted(cap, 0.66, frame, 0.34, 0, frame)
    cv2.rectangle(frame, (x1, y1), (x2, y2), _PANEL_BORDE, 1, cv2.LINE_AA)
    _texto(frame, "VELOCIDAD", (x1 + 12, y1 + 4 + th - 4), 0.34, COLOR_MUTED, 1)
    _texto(frame, txt, (x1 + 12, y2 - 9), 0.7, COLOR_TRACK, 2)


def dibujar_overlay(frame, zona, bbox):
    """Panel de calibracion (solo en modo calibrar): ancho de placa + distancia + teclas."""
    filas = []
    if bbox is not None:
        ancho = bbox[2] - bbox[0]
        ok = ancho >= zona.min_ancho_px
        filas.append((f"Ancho placa: {ancho}px  (min {zona.min_ancho_px})",
                      COLOR_TRACK if ok else COLOR_ALERTA))
    else:
        filas.append(("Sin deteccion de placa", COLOR_MUTED))
    filas.append((f"Distancia lineas: {zona.distancia_m:.1f} m", COLOR_TEXTO))
    filas.append(("[s] guardar     [q] salir", COLOR_MUTED))
    _panel(frame, 12, 12, 360, filas, titulo="CALIBRACION")


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
    # SOLO los controles que de verdad se usan:
    #   min_ancho -> gate de ancho minimo de placa para el OCR.
    #   dist_cm   -> distancia real entre lineas (para la velocidad).
    # Quitados: max_ancho y min_nitidez (en desuso: el "mejor" se elige por
    # cercania, no por esos gates) -> no se muestran para no confundir.
    cv2.createTrackbar("min_ancho", VENTANA, zona.min_ancho_px, 400,
                       lambda v: setattr(zona, "min_ancho_px", v))
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

    # El mejor frame se entrega al pipeline cuando existe callback de captura.
    # La velocidad se adjunta para registrarla en el evento y la base de datos.
    if al_capturar is not None:
        al_capturar(nombre, captura["mejor"], vel if vel is not None else 0.0)


# ── loop principal ──────────────────────────────────────────────────────────

def _abrir_fuente(fuente, es_archivo):
    """
    Abre la fuente de video y, si es un stream en vivo, aplica resolucion +
    buffer minimo. Devuelve el VideoCapture (el llamador revisa cap.isOpened()).
    Se reusa en la apertura inicial y en cada reintento de reconexion.
    """
    es_url = isinstance(fuente, str) and "://" in fuente
    es_webcam = isinstance(fuente, int)

    if es_url:
        # RTSP: forzar TCP + sin buffer -> menos latencia (clave para tiempo real).
        # H.264/H.265 de RTSP comprime el movimiento mucho mejor que el MJPEG http.
        if str(fuente).lower().startswith("rtsp"):
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|fflags;nobuffer"
        # backend FFMPEG explicito: evita que OpenCV trate la URL como secuencia de
        # imagenes (error CAP_IMAGES) y le da soporte real de streaming (rtsp/http).
        cap = cv2.VideoCapture(fuente, cv2.CAP_FFMPEG)
    else:
        cap = cv2.VideoCapture(fuente)   # webcam (indice) o archivo de video

    if cap.isOpened() and not es_archivo:
        # buffer minimo: evita que la fuente en vivo acumule lag (frames viejos)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        # NO forzar resolucion en webcam: camaras virtuales (DroidCam) entregan
        # negro si se les pide una resolucion que no soportan (p.ej. 960x720). El
        # frame se reescala a VENTANA_W x VENTANA_H mas adelante, asi que la nativa
        # de la camara sirve igual.
        if not es_webcam:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,  VENTANA_W)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, VENTANA_H)
    return cap


class FuenteVideo:
    """
    Envuelve cv2.VideoCapture y unifica los dos modos:

    - Video grabado (es_archivo): lectura SECUENCIAL, no se pierde ningun frame
      (importa para el timing frame/FPS y para no saltarse autos).
    - EN VIVO (webcam/URL/RTSP): un hilo lee sin parar y guarda SOLO el ultimo
      frame; el loop principal procesa siempre el mas reciente y descarta los
      atrasados -> el DELAY NO se acumula. La reconexion (si esta activa) vive
      aqui: si la camara se cae, reintenta reabrir sin frenar el loop.

    leer() devuelve (vivo, frame, version):
        vivo    -> False = se acabo el video / la fuente murio sin reconexion.
        frame   -> ultimo frame (vivo) o el siguiente (video); None si aun no hay.
        version -> contador que sube con cada frame nuevo (para no reprocesar).
    """

    def __init__(self, fuente, es_archivo):
        self.fuente = fuente
        self.es_archivo = es_archivo
        self.cap = _abrir_fuente(fuente, es_archivo)
        self._lock = threading.Lock()
        self._frame = None
        self._version = 0
        self._vivo = self.cap.isOpened()
        self._hilo = None
        # solo en vivo: hilo lector "ultimo frame gana"
        if not es_archivo and self._vivo:
            self._hilo = threading.Thread(target=self._bucle_vivo, daemon=True)
            self._hilo.start()

    def abierta(self):
        return self.cap is not None and self.cap.isOpened()

    def get_fps(self):
        return self.cap.get(cv2.CAP_PROP_FPS)

    def _bucle_vivo(self):
        fallos = 0
        while self._vivo:
            ret, frame = self.cap.read()
            if not ret:
                if not RECONECTAR:
                    self._vivo = False          # caida sin reconexion -> terminar
                    break
                fallos += 1
                if fallos == 1:
                    print("[CAMARA] sin frames de la fuente en vivo...")
                if fallos >= RECONECTAR_MAX_FALLOS:
                    print(f"[CAMARA] reabriendo {self.fuente} (espera {RECONECTAR_ESPERA}s)...")
                    self.cap.release()
                    time.sleep(RECONECTAR_ESPERA)
                    self.cap = _abrir_fuente(self.fuente, self.es_archivo)
                    fallos = 0
                continue
            fallos = 0
            with self._lock:
                self._frame = frame
                self._version += 1

    def leer(self):
        if self.es_archivo:
            ret, frame = self.cap.read()
            self._version += 1
            return ret, frame, self._version
        with self._lock:
            return self._vivo, self._frame, self._version

    def indice_fuente(self):
        """Solo video: indice del proximo frame que leer() va a entregar.
        Sirve para el pacing en tiempo real (saber cuanto vamos adelantados/atrasados)."""
        return self._version

    def saltar(self):
        """Solo video: descarta UN frame sin decodificarlo (cap.grab() es barato).
        Lo usa el pacing para ponerse al dia saltando los frames ya 'vencidos' en vez
        de procesarlos -> el video se reproduce a su FPS real, no a la del pipeline."""
        ret = self.cap.grab()
        if ret:
            self._version += 1
        return ret

    def liberar(self):
        self._vivo = False
        if self._hilo is not None:
            self._hilo.join(timeout=1.0)
        if self.cap is not None:
            self.cap.release()


# Archivo de estado compartido con la API (mismo que usa el speed-boost). La API
# escribe aqui la fuente deseada; el loop de camara la lee para hacer hot-swap.
_RUNTIME_FILE = os.path.normpath(
    os.path.join(_AQUI, "..", "..", "..", "..", "storage", "runtime_config.json"))


def _leer_fuente_runtime():
    """(fuente_resuelta, version) desde runtime_config.json para hot-swap, o None."""
    try:
        with open(_RUNTIME_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    src = data.get("source")
    if not src:
        return None
    ver = int(data.get("source_version", 0) or 0)
    fuente = CAMARA_IDX if src == "live" else (int(src) if str(src).isdigit() else src)
    return fuente, ver


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
    # "idle" = fuente DETENIDA desde el frontend (boton Detener): el proceso sigue
    # vivo pero suelta la camara y no procesa nada hasta que se elija otra fuente.
    en_idle = (fuente == "idle")
    es_archivo = (not en_idle) and isinstance(fuente, str) and "://" not in fuente

    fuente_video = None
    if not en_idle:
        fuente_video = FuenteVideo(fuente, es_archivo)
        if not fuente_video.abierta():
            print(f"No se pudo abrir la fuente: {fuente}")
            return

    os.makedirs(carpeta_captura, exist_ok=True)

    # FPS de la fuente (para convertir frames -> segundos en video grabado)
    fps = FPS_FALLBACK
    if fuente_video is not None:
        fps = fuente_video.get_fps()
        if not fps or fps <= 0:
            fps = FPS_FALLBACK

    rastrear_por = "carro" if DETECTAR_CARROS else "placa"
    tolerancia   = TOLERANCIA_CARRO if DETECTAR_CARROS else TOLERANCIA_PLACA
    zona = ZonaDeteccion(linea_entra=LINEA_ENTRA, linea_sale=LINEA_SALE,
                         min_ancho_px=MIN_ANCHO_PX, max_ancho_px=MAX_ANCHO_PX,
                         min_nitidez=MIN_NITIDEZ, distancia_m=DISTANCIA_M,
                         tolerancia_frames=tolerancia, rastrear_por=rastrear_por)
    capturas_guardadas = 0

    # El guardado de captura y el pipeline se ejecutan en un hilo aparte para no
    # frenar el video. Un solo worker serializa las capturas y evita concurrencia.
    guardado_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="captura")

    bbox        = None    # placa (lo que se rastrea)
    carro_bbox  = None    # carro (solo visual)
    n_frame     = 0

    # medicion de FPS real para el hook on_fps (se emite ~1 vez por segundo)
    fps_t0      = time.time()
    fps_frames  = 0

    # pacing de VIDEO grabado: reloj de pared para reproducir a su FPS real. Si el
    # pipeline no alcanza, se SALTAN frames (grab) en vez de procesarlos -> el video
    # va a velocidad normal, no en camara lenta. (En vivo no aplica: ahi ya se
    # descarta lo atrasado con "ultimo frame gana".)
    t_video_inicio = None

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

    ultima_version = -1

    # ── estado de fuente para HOT-SWAP (cambiar de video sin reiniciar el proceso) ──
    fuente_actual = fuente
    _rt = _leer_fuente_runtime()
    source_version = _rt[1] if _rt else 0    # arranca sincronizado: no swap inmediato
    if en_idle:
        source_type, source_name = "idle", "DETENIDO"
    elif es_archivo:
        source_type, source_name = "video", os.path.basename(str(fuente_actual))
    else:
        source_type, source_name = "live", "EN VIVO"
    print(f"[FUENTE] hot-swap ACTIVO. Inicial: {source_name} (v{source_version}). "
          f"Cambialo desde el frontend ('Elegir video' / 'EN VIVO').")

    while True:
        # ── hot-swap / DETENER: aplicar el cambio de fuente sin reiniciar el proceso.
        #    En idle se revisa cada iteracion (n_frame no avanza); con fuente activa,
        #    cada ~15 frames. fuente="idle" suelta la camara y deja el proceso vivo.
        if en_idle or n_frame % 15 == 0:
            _rt = _leer_fuente_runtime()
            if _rt and _rt[1] != source_version:
                source_version = _rt[1]
                fuente_actual = _rt[0]
                if fuente_video is not None:
                    fuente_video.liberar()
                    fuente_video = None
                if fuente_actual == "idle":
                    en_idle = True
                    source_type, source_name = "idle", "DETENIDO"
                    print("[FUENTE] DETENIDO -> camara liberada (proceso sigue vivo)")
                    continue
                en_idle = False
                es_archivo = isinstance(fuente_actual, str) and "://" not in fuente_actual
                fuente_video = FuenteVideo(fuente_actual, es_archivo)
                fps = fuente_video.get_fps()
                if not fps or fps <= 0:
                    fps = FPS_FALLBACK
                zona = ZonaDeteccion(linea_entra=LINEA_ENTRA, linea_sale=LINEA_SALE,
                                     min_ancho_px=MIN_ANCHO_PX, max_ancho_px=MAX_ANCHO_PX,
                                     min_nitidez=MIN_NITIDEZ, distancia_m=DISTANCIA_M,
                                     tolerancia_frames=tolerancia, rastrear_por=rastrear_por)
                t_video_inicio = None
                n_frame = 0
                ultima_version = -1
                carro_bbox = bbox = None
                source_type = "video" if es_archivo else "live"
                source_name = os.path.basename(str(fuente_actual)) if es_archivo else "EN VIVO"
                print(f"[FUENTE] cambiada -> {source_name} ({source_type})")
                continue

        # ── DETENIDO (idle): no hay camara. Emitir status ~1/s y dormir. ──
        if en_idle:
            if on_fps is not None and time.time() - fps_t0 >= 1.0:
                on_fps(0.0, source_type, source_name)
                fps_t0, fps_frames = time.time(), 0
            time.sleep(0.1)
            continue

        # ── pacing tiempo real (solo video grabado) ──────────────────────────
        # objetivo = indice de frame que el reloj de pared dice que deberia mostrarse
        # ahora. Si vamos ADELANTADOS, esperar; si vamos ATRASADOS, saltar (grab) los
        # frames vencidos sin decodificarlos. Asi el video corre a su FPS real.
        if es_archivo:
            if t_video_inicio is None:
                t_video_inicio = time.time()
            objetivo = int((time.time() - t_video_inicio) * fps)
            proximo  = fuente_video.indice_fuente()
            if proximo > objetivo:
                espera = proximo / fps - (time.time() - t_video_inicio)
                if espera > 0:
                    time.sleep(espera)
            else:
                while fuente_video.indice_fuente() < objetivo:
                    if not fuente_video.saltar():
                        break

        vivo, frame, version = fuente_video.leer()
        if not vivo:
            if es_archivo:
                # Video terminado: se reabre en bucle y el cambio de fuente se
                # mantiene gestionado por el bloque superior.
                fuente_video.liberar()
                fuente_video = FuenteVideo(fuente_actual, es_archivo)
                t_video_inicio = None
                n_frame = 0
                ultima_version = -1
                continue
            # Fuente en vivo sin frame: se espera y se permite cambiar la fuente
            # desde el frontend sin reiniciar el proceso.
            time.sleep(0.1)
            continue
        # En vivo: si no hay frame nuevo, se evita reprocesar el mismo cuadro.
        if frame is None or (not es_archivo and version == ultima_version):
            time.sleep(0.005)
            continue
        ultima_version = version

        # DOS frames distintos a proposito:
        #   frame_nativo -> resolucion REAL de la fuente; es lo que se GUARDA y va
        #                   al OCR (mas pixeles reales en la placa = mas legible).
        #   frame        -> reescalado a VENTANA_W x VENTANA_H para deteccion,
        #                   dibujo y stream (rapido y tamano fijo de ventana).
        # Antes se reescalaba ANTES de capturar y la placa llegaba al OCR encogida.
        frame_nativo = frame
        if n_frame == 0:
            hn, wn = frame_nativo.shape[:2]
            print(f"[CAMARA] resolucion nativa de la fuente: {wn}x{hn} "
                  f"(captura/OCR) ; display {VENTANA_W}x{VENTANA_H}")
        frame = cv2.resize(frame, (VENTANA_W, VENTANA_H))
        n_frame += 1

        # Tiempo del frame: video -> indice real de fuente / FPS; vivo -> reloj
        # real. Esto conserva el calculo de velocidad aunque se salten frames.
        t = (version / fps) if es_archivo else time.time()

        if detector is not None and n_frame % INFERENCIA_CADA == 0:
            carro_bbox, bbox = detector(frame)

        captura = zona.actualizar(frame, carro_bbox, bbox, t, frame_captura=frame_nativo)

        if captura is not None:
            capturas_guardadas += 1
            nombre = f"{time.strftime('%Y%m%d_%H%M%S')}_carro{capturas_guardadas:03d}"
            guardado_pool.submit(_guardar_captura, captura, nombre,
                                 carpeta_captura, al_capturar)

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

        dibujar_velocidad(frame, zona)

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
                on_fps(fps_frames / (ahora - fps_t0), source_type, source_name)
                fps_t0, fps_frames = ahora, 0

        # headless: sin imshow/waitKey -> el estado de la ventana no frena el loop
        if MOSTRAR_VENTANA:
            cv2.imshow(VENTANA, frame)
            tecla = cv2.waitKey(1) & 0xFF
            if tecla == ord("q"):
                break
            if tecla == ord("s") and CALIBRAR:
                _guardar_config(zona)

    if fuente_video is not None:
        fuente_video.liberar()
    if MOSTRAR_VENTANA:
        cv2.destroyAllWindows()
    # esperar a que terminen las capturas en vuelo antes de cerrar
    guardado_pool.shutdown(wait=True)
    print(f"Capturas guardadas: {capturas_guardadas}")
