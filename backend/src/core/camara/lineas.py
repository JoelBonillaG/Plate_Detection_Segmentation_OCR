"""
Dos lineas virtuales INCLINABLES (definidas por dos puntos cada una) y
rastreo del mejor frame mientras un bbox de placa cruza la zona.

Por que inclinables: en la vereda el carro se mueve en diagonal (lejos
arriba -> cerca abajo). Lineas verticales no representan bien el carril.
Cada linea se define por dos puntos en fracciones del frame, asi se
alinea al carril a cualquier angulo. El cruce se prueba con el signo del
producto cruz (de que lado de la recta esta el centro del bbox).

Direccion del trafico (Av. Chasquis, desde la vereda izq):
    ENTRA (lejos)  ->  zona dorada  ->  SALE (cerca, hacia la camara)

Estado:
    esperando  -> ninguna placa en zona
    rastreando -> placa dentro de la zona, guardando el frame mas NITIDO
    (al salir por SALE)-> devuelve el mejor frame; por ENTRA -> descarta
"""

import cv2


def _signo(px, py, linea):
    """Signo del lado de la recta linea=((ax,ay),(bx,by)) donde cae (px,py)."""
    (ax, ay), (bx, by) = linea
    return (bx - ax) * (py - ay) - (by - ay) * (px - ax)


def nitidez(crop):
    """Varianza del Laplaciano: alto = nitido, bajo = borroso (motion blur)."""
    if crop is None or crop.size == 0:
        return 0.0
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    return cv2.Laplacian(g, cv2.CV_64F).var()


_nitidez = nitidez   # alias interno


class ZonaDeteccion:
    """
    Zona de captura entre dos lineas inclinables.

    Args:
        linea_entra: ((x1,y1),(x2,y2)) en fracciones [0..1]. Linea LEJANA.
        linea_sale:  ((x1,y1),(x2,y2)) en fracciones [0..1]. Linea CERCANA.
        min_ancho_px: ancho minimo del bbox de placa para rastrear (gate lejos).
        max_ancho_px: ancho maximo; mas alla la placa ya va a perfil (0 = sin tope).
        min_nitidez:  umbral; si el mejor frame queda por debajo, se descarta.
        distancia_m:  distancia REAL en metros entre las dos lineas (calibrable).
                      Sirve para calcular velocidad = distancia / tiempo de cruce.
    """

    def __init__(self,
                 linea_entra=((0.30, 0.15), (0.20, 0.62)),
                 linea_sale =((0.62, 0.28), (0.52, 0.98)),
                 min_ancho_px=80,
                 max_ancho_px=0,
                 min_nitidez=40.0,
                 distancia_m=5.0):
        self.linea_entra = linea_entra
        self.linea_sale  = linea_sale
        self.min_ancho_px = min_ancho_px
        self.max_ancho_px = max_ancho_px
        self.min_nitidez  = min_nitidez
        self.distancia_m  = distancia_m

        self._estado        = "esperando"   # esperando | rastreando
        self._mejor_frame   = None
        self._mejor_nitidez = 0.0
        self._mejor_ancho   = 0       # ancho de placa (px) en el mejor frame
        self._frame_entra   = None    # primer frame al entrar a la zona
        self._frame_sale    = None    # frame al cruzar la linea SALE

        # cronometro de velocidad
        self._t_entra        = None   # tiempo (s) al cruzar ENTRA
        self._t_sale         = None   # tiempo (s) al cruzar SALE
        self.ultima_velocidad = None  # km/h del ultimo carro capturado (None si no medible)

    # ── lineas en pixeles (para dibujar) ──────────────────────────────────

    def _px(self, linea, w, h):
        (ax, ay), (bx, by) = linea
        return (int(ax * w), int(ay * h)), (int(bx * w), int(by * h))

    def entra_px(self, w, h):
        return self._px(self.linea_entra, w, h)

    def sale_px(self, w, h):
        return self._px(self.linea_sale, w, h)

    # ── lado "dentro" precalculado vs cada linea ──────────────────────────

    def _dentro(self, xc, yc, w, h):
        """True si (xc,yc) esta entre las dos lineas (lado interior de ambas)."""
        e = self.entra_px(w, h)
        s = self.sale_px(w, h)
        # punto medio de una linea define el lado interior de la otra
        me = ((e[0][0] + e[1][0]) / 2, (e[0][1] + e[1][1]) / 2)
        ms = ((s[0][0] + s[1][0]) / 2, (s[0][1] + s[1][1]) / 2)
        dentro_e = _signo(xc, yc, e) * _signo(*ms, e) > 0   # mismo lado que SALE
        dentro_s = _signo(xc, yc, s) * _signo(*me, s) > 0   # mismo lado que ENTRA
        return dentro_e, dentro_s

    # ── logica de cruce ───────────────────────────────────────────────────

    def actualizar(self, frame, bbox_pixels, t=None):
        """
        Llama cada frame con el bbox de placa (x1,y1,x2,y2) o None.

        t: tiempo en segundos de ESTE frame (para medir velocidad). Usar el
           tiempo del video (frame/FPS) si es archivo, o time.time() si es vivo.
           Si t=None no se calcula velocidad.

        Devuelve un dict con la captura cuando el carro sale por la linea CERCANA,
        o None si aun no hay captura lista. El dict trae:
            entra, mejor, sale  -> frames BGR (el mejor es el que va al OCR)
            velocidad           -> km/h o None
            nitidez, ancho_px   -> del mejor frame
            tiempo_cruce        -> segundos entre ENTRA y SALE (o None)
        """
        h, w = frame.shape[:2]

        if bbox_pixels is None:
            if self._estado == "rastreando":
                self._reset()
            return None

        x1, y1, x2, y2 = bbox_pixels
        ancho = x2 - x1
        xc = (x1 + x2) / 2
        yc = (y1 + y2) / 2

        # gate de tamano: placa muy lejos (chica) o ya muy cerca (perfil)
        if ancho < self.min_ancho_px:
            if self._estado == "rastreando":
                self._reset()
            return None
        if self.max_ancho_px and ancho > self.max_ancho_px:
            # placa demasiado cerca/oblicua: cerrar SOLO si veniamos rastreando;
            # si estabamos esperando, ignorar (no resetear ni borrar velocidad)
            if self._estado == "rastreando":
                return self._cerrar(frame, t)
            return None

        dentro_e, dentro_s = self._dentro(xc, yc, w, h)
        en_zona = dentro_e and dentro_s

        if self._estado == "esperando":
            if en_zona:
                self._estado    = "rastreando"
                self._t_entra   = t            # cronometro: cruzo ENTRA
                self._frame_entra = frame.copy()
                self._evaluar(frame, bbox_pixels)

        elif self._estado == "rastreando":
            if en_zona:
                self._evaluar(frame, bbox_pixels)
            elif not dentro_s:
                # cruzo la linea CERCANA (SALE) -> cruce completo
                return self._cerrar(frame, t)
            else:
                # salio por la linea LEJANA (ENTRA) -> marcha atras, descartar
                self._reset()

        return None

    def _evaluar(self, frame, bbox):
        """Mide nitidez del crop de la placa; guarda el frame si mejora."""
        x1, y1, x2, y2 = bbox
        crop = frame[max(y1, 0):y2, max(x1, 0):x2]
        n = _nitidez(crop)
        if n > self._mejor_nitidez:
            self._mejor_nitidez = n
            self._mejor_frame   = frame.copy()
            self._mejor_ancho   = x2 - x1

    def _cerrar(self, frame, t=None):
        """Devuelve el dict de la captura si el mejor frame supera el umbral de
        nitidez; si no, None. Calcula la velocidad del cruce (km/h)."""
        self._t_sale = t
        self._frame_sale = frame.copy()
        self.ultima_velocidad = self._calcular_velocidad()

        captura = None
        if self._mejor_frame is not None and self._mejor_nitidez >= self.min_nitidez:
            captura = {
                "entra":        self._frame_entra,
                "mejor":        self._mejor_frame.copy(),
                "sale":         self._frame_sale,
                "velocidad":    self.ultima_velocidad,
                "nitidez":      self._mejor_nitidez,
                "ancho_px":     self._mejor_ancho,
                "tiempo_cruce": self._tiempo_cruce(),   # resta directa (s)
            }
        self._reset()
        return captura

    def _tiempo_cruce(self):
        """Segundos entre cruzar ENTRA y SALE. None si no medible."""
        if self._t_entra is None or self._t_sale is None:
            return None
        dt = self._t_sale - self._t_entra
        return dt if dt > 0 else None

    def _calcular_velocidad(self):
        """km/h = distancia_m / tiempo_cruce * 3.6. None si no medible."""
        if self._t_entra is None or self._t_sale is None or not self.distancia_m:
            return None
        dt = self._t_sale - self._t_entra
        if dt <= 0:
            return None
        return self.distancia_m / dt * 3.6

    def _reset(self):
        self._estado        = "esperando"
        self._mejor_frame   = None
        self._mejor_nitidez = 0.0
        self._mejor_ancho   = 0
        self._frame_entra   = None
        self._frame_sale    = None
        self._t_entra       = None
        self._t_sale        = None

    @property
    def estado(self):
        return self._estado
