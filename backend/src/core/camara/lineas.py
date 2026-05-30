"""
Define las dos lineas virtuales y rastrea cuando un bbox las cruza.

Estado del rastreo:
    esperando  -> ninguna placa en zona
    rastreando -> placa entro por linea izq o der, guardando mejor frame
    capturado  -> placa salio por el otro lado, frame listo
"""


class ZonaDeteccion:
    """
    Dos lineas verticales que definen la zona de captura.

    Args:
        pos_izq: posicion de linea izquierda como fraccion del ancho (ej: 0.30)
        pos_der: posicion de linea derecha como fraccion del ancho (ej: 0.70)
    """

    def __init__(self, pos_izq=0.30, pos_der=0.70):
        self.pos_izq = pos_izq
        self.pos_der = pos_der

        self._estado      = "esperando"   # esperando | rastreando | capturado
        self._mejor_frame = None
        self._mejor_area  = 0
        self._entro_por   = None          # "izq" | "der"

    # ── coordenadas en pixeles ────────────────────────────────────────────

    def x_izq(self, ancho_frame):
        return int(self.pos_izq * ancho_frame)

    def x_der(self, ancho_frame):
        return int(self.pos_der * ancho_frame)

    # ── logica de cruce ───────────────────────────────────────────────────

    def actualizar(self, frame, bbox_pixels):
        """
        Llama en cada frame con el bbox detectado (x1, y1, x2, y2) en pixeles.
        Si no hay deteccion pasar bbox_pixels=None.

        Devuelve el mejor frame capturado cuando la placa sale de la zona,
        o None si aun no hay captura lista.
        """
        ancho = frame.shape[1]
        xi    = self.x_izq(ancho)
        xd    = self.x_der(ancho)

        if bbox_pixels is None:
            # si perdemos la deteccion dentro de la zona, resetear
            if self._estado == "rastreando":
                self._reset()
            return None

        x1, y1, x2, y2 = bbox_pixels
        xc   = (x1 + x2) / 2        # centro horizontal del bbox
        area = (x2 - x1) * (y2 - y1)

        if self._estado == "esperando":
            # vehiculo entra por izquierda
            if xc >= xi and xc < xd:
                self._estado    = "rastreando"
                self._entro_por = "izq" if xc < (xi + xd) / 2 else "der"
                self._guardar_si_mejor(frame, area)

        elif self._estado == "rastreando":
            if xi <= xc <= xd:
                # sigue dentro de la zona: guardar mejor frame
                self._guardar_si_mejor(frame, area)
            else:
                # salio de la zona por el lado opuesto
                salio_por = "izq" if xc < xi else "der"
                if salio_por != self._entro_por:
                    # cruce completo: devolver captura
                    frame_capturado = self._mejor_frame.copy()
                    self._reset()
                    return frame_capturado
                else:
                    # volvio por el mismo lado (dio marcha atras)
                    self._reset()

        return None

    def _guardar_si_mejor(self, frame, area):
        if area > self._mejor_area:
            self._mejor_area  = area
            self._mejor_frame = frame.copy()

    def _reset(self):
        self._estado      = "esperando"
        self._mejor_frame = None
        self._mejor_area  = 0
        self._entro_por   = None

    @property
    def estado(self):
        return self._estado
