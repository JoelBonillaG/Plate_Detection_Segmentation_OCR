"""
Dos lineas virtuales INCLINABLES (definidas por dos puntos cada una) y
rastreo del mejor frame mientras un CARRO cruza la zona.

El CARRO maneja el cruce (entra/sale/velocidad): es grande y estable, casi no
parpadea -> el tiempo de cruce sale confiable. La PLACA solo aporta el mejor
crop para el OCR (chica, parpadea: no sirve para medir el cruce).

Por que inclinables: en la vereda el carro se mueve en diagonal (lejos
arriba -> cerca abajo). Lineas verticales no representan bien el carril.
Cada linea se define por dos puntos en fracciones del frame, asi se
alinea al carril a cualquier angulo. El cruce se prueba con el signo del
producto cruz (de que lado de la recta esta el centro del carro).

Parpadeo: si el detector pierde el carro un frame suelto, NO se suelta el
rastreo al toque; se aguantan tolerancia_frames seguidos sin verlo antes de
darlo por ido (asi el cronometro arranca temprano y la velocidad sale real).

Direccion del trafico (Av. Chasquis, desde la vereda izq):
    ENTRA (lejos)  ->  zona dorada  ->  SALE (cerca, hacia la camara)

Estado:
    esperando  -> ningun carro en zona
    rastreando -> carro dentro de la zona; se elige el mejor frame (placa nitida,
                  o carro nitido como respaldo si la placa no aparece)
    (al cruzar SALE)-> devuelve la captura; por ENTRA -> descarta (marcha atras)
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
        min_ancho_px: ancho minimo de la PLACA para que su crop valga la pena
                      para el OCR (placa muy chica = ilegible). Ya NO controla el
                      cruce: eso lo maneja el carro.
        max_ancho_px: (en desuso) quedaba del rastreo por placa.
        min_nitidez:  (en desuso) antes descartaba capturas borrosas.
        distancia_m:  distancia REAL en metros entre las dos lineas (calibrable).
                      velocidad = distancia / tiempo de cruce DEL CARRO.
        tolerancia_frames: frames seguidos SIN carro que se aguantan antes de
                      soltar el rastreo (absorbe parpadeos del detector).

    El CARRO maneja el cruce (entra/sale/velocidad): grande y estable, casi no
    parpadea. La PLACA solo aporta el mejor crop para el OCR cuando aparece.
    """

    def __init__(self,
                 linea_entra=((0.30, 0.15), (0.20, 0.62)),
                 linea_sale =((0.62, 0.28), (0.52, 0.98)),
                 min_ancho_px=80,
                 max_ancho_px=0,
                 min_nitidez=40.0,
                 distancia_m=5.0,
                 tolerancia_frames=3,
                 rastrear_por="carro"):
        self.linea_entra = linea_entra
        self.linea_sale  = linea_sale
        self.min_ancho_px = min_ancho_px
        self.max_ancho_px = max_ancho_px
        self.min_nitidez  = min_nitidez
        self.distancia_m  = distancia_m
        # parpadeo: cuantos frames seguidos SIN el objeto rastreado aguanta sin
        # soltar el rastreo. El carro casi no parpadea (2-3 alcanza); la placa
        # parpadea mas (subir a 5-8). 0 = sin tolerancia.
        self.tolerancia_frames = tolerancia_frames
        # que objeto maneja el cruce/velocidad:
        #   "carro" -> bbox del carro (default; estable, timing confiable)
        #   "placa" -> bbox de la placa (cuando DETECTAR_CARROS=False; mas ruidoso)
        self.rastrear_por = rastrear_por

        self._estado        = "esperando"   # esperando | rastreando
        self._mejor_frame   = None
        self._mejor_nitidez = 0.0
        self._mejor_ancho   = 0       # ancho de placa (px) en el mejor frame
        self._mejor_tiene_placa = False  # ¿el mejor frame tenia placa? (vs respaldo de carro)
        self._frame_entra   = None    # primer frame al entrar a la zona
        self._frame_sale    = None    # frame al cruzar la linea SALE
        self._perdidos      = 0       # frames seguidos SIN carro (parpadeo)

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

    def punto_en_zona(self, px, py, w, h):
        """True si el punto (px,py) cae entre las dos lineas (dentro de la zona)."""
        de, ds = self._dentro(px, py, w, h)
        return de and ds

    # ── logica de cruce ───────────────────────────────────────────────────

    def actualizar(self, frame, carro_bbox, placa_bbox, t=None):
        """
        Llama cada frame con el bbox del CARRO y el de la PLACA (cualquiera None).

        El CARRO maneja el cruce (entra/sale/velocidad): grande y estable. La
        PLACA solo se usa para elegir el mejor crop (OCR).

        t: tiempo en segundos de ESTE frame (para medir velocidad). Usar el
           tiempo del video (frame/FPS) si es archivo, o time.time() si es vivo.
           Si t=None no se calcula velocidad.

        Devuelve un dict con la captura cuando el CARRO sale por la linea CERCANA,
        o None si aun no hay captura lista. El dict trae:
            entra, mejor, sale  -> frames BGR (el mejor es el que va al OCR)
            velocidad           -> km/h o None
            nitidez, ancho_px   -> del mejor frame
            tiempo_cruce        -> segundos entre ENTRA y SALE (o None)
        """
        h, w = frame.shape[:2]

        # objeto que maneja el cruce: carro (default) o placa (DETECTAR_CARROS=False).
        track_bbox = carro_bbox if self.rastrear_por == "carro" else placa_bbox

        # con tolerancia a parpadeos del detector. Sin el objeto este frame: NO
        # soltar el rastreo al toque (puede ser parpadeo); aguantar
        # tolerancia_frames y recien ahi darlo por ido.
        if track_bbox is None:
            if self._estado == "rastreando":
                self._perdidos += 1
                if self._perdidos > self.tolerancia_frames:
                    self._reset()
            return None
        self._perdidos = 0

        x1, y1, x2, y2 = track_bbox
        xc = (x1 + x2) / 2
        yc = (y1 + y2) / 2
        dentro_e, dentro_s = self._dentro(xc, yc, w, h)
        en_zona = dentro_e and dentro_s

        if self._estado == "esperando":
            if en_zona:
                self._estado      = "rastreando"
                self._t_entra     = t            # cronometro: el CARRO cruzo ENTRA
                self._frame_entra = frame.copy()
                self._evaluar(frame, placa_bbox, carro_bbox)

        elif self._estado == "rastreando":
            if en_zona:
                self._evaluar(frame, placa_bbox, carro_bbox)
            elif not dentro_s:
                # el CARRO cruzo la linea CERCANA (SALE) -> cruce completo
                return self._cerrar(frame, t)
            else:
                # salio por la linea LEJANA (ENTRA) -> marcha atras, descartar
                self._reset()

        return None

    def _evaluar(self, frame, placa_bbox, carro_bbox):
        """
        Elige el mejor frame del cruce para el OCR.
        Prioridad: un frame CON placa (suficientemente grande) le gana a cualquiera
        sin placa; entre frames del mismo tipo, gana el mas nitido. Si la placa
        nunca aparece, queda como respaldo el frame de CARRO mas nitido (asi igual
        hay 'mejor' y velocidad, aunque el OCR quiza no lea).
        """
        placa_ok = placa_bbox is not None and (placa_bbox[2] - placa_bbox[0]) >= self.min_ancho_px
        if placa_ok:
            x1, y1, x2, y2 = placa_bbox
            tiene, ancho = True, x2 - x1
        elif carro_bbox is not None:
            x1, y1, x2, y2 = carro_bbox      # respaldo: nitidez del carro
            tiene, ancho = False, 0
        elif placa_bbox is not None:
            # modo placa sin carro: la placa es chica pero igual es lo unico que hay
            x1, y1, x2, y2 = placa_bbox
            tiene, ancho = False, placa_bbox[2] - placa_bbox[0]
        else:
            return                           # nada que evaluar este frame
        crop = frame[max(y1, 0):y2, max(x1, 0):x2]
        n = _nitidez(crop)

        # un frame CON placa siempre supera a uno sin placa; si empatan en tipo, el mas nitido
        gana = (tiene and not self._mejor_tiene_placa) or \
               (tiene == self._mejor_tiene_placa and n > self._mejor_nitidez)
        if gana:
            self._mejor_nitidez     = n
            self._mejor_frame       = frame.copy()
            self._mejor_ancho       = ancho
            self._mejor_tiene_placa = tiene

    def _cerrar(self, frame, t=None):
        """Cierra el cruce del CARRO: calcula velocidad y arma la captura con el
        mejor frame disponible (con placa si la hubo; si no, respaldo de carro).
        Siempre devuelve captura: la velocidad se mide con el carro, exista placa
        o no (el OCR despues lee, o no, segun el crop)."""
        self._t_sale = t
        self._frame_sale = frame.copy()
        self.ultima_velocidad = self._calcular_velocidad()

        if self._mejor_frame is None:       # por las dudas: nunca se evaluo nada
            self._mejor_frame = self._frame_sale
        captura = {
            "entra":        self._frame_entra,
            "mejor":        self._mejor_frame.copy(),
            "sale":         self._frame_sale,
            "velocidad":    self.ultima_velocidad,
            "nitidez":      self._mejor_nitidez,
            "ancho_px":     self._mejor_ancho,
            "tiempo_cruce": self._tiempo_cruce(),   # resta directa (s)
            "con_placa":    self._mejor_tiene_placa,  # True = mejor con placa ; False = respaldo de carro
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
        self._mejor_tiene_placa = False
        self._frame_entra   = None
        self._frame_sale    = None
        self._t_entra       = None
        self._t_sale        = None
        self._perdidos      = 0

    @property
    def estado(self):
        return self._estado
