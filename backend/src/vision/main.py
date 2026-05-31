"""
Punto de entrada del modulo de vision.

Arranca el servidor MJPEG y el loop de camara. La API consume el video
en /api/cameras/main/stream (proxy hacia stream_server) y recibe eventos
por WebSocket cuando un carro completa el cruce.

Ejecutar desde backend/:
    python -m src.vision.main
    python -m src.vision.main video.mp4
    python -m src.vision.main http://192.168.x.x:4747/video
    python -m src.vision.main 1
"""

from __future__ import annotations

import sys
from pathlib import Path

DIR = Path(__file__).resolve().parent
SRC_DIR = DIR.parent
BACKEND_DIR = SRC_DIR.parent

sys.path.insert(0, str(DIR))
sys.path.insert(0, str(DIR / "camara"))
sys.path.insert(0, str(DIR / "pipeline"))
sys.path.insert(0, str(BACKEND_DIR))

# True  -> enderezada -> filtros -> segmentacion
# False -> enderezada -> segmentacion directa
USAR_FILTROS = True

from camara import iniciar
import cadena
import stream_server
from integration import hacer_al_capturar, broadcast_status


if __name__ == "__main__":
    # arrancar el servidor MJPEG antes del loop de camara
    stream_server.start()

    modelos = cadena.cargar_modelos(usar_filtros=USAR_FILTROS)
    print("Modelos cargados.")

    def detectar_en_vivo(frame):
        return cadena.detectar_placa_en_vivo(frame, modelos)

    fuente = 0
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        fuente = int(arg) if arg.isdigit() else arg

    iniciar(
        detector=detectar_en_vivo,
        al_capturar=hacer_al_capturar(modelos),
        fuente=fuente,
        on_frame=stream_server.set_frame,   # cada frame anotado -> MJPEG
        on_fps=broadcast_status,            # ~1/s -> status WebSocket
    )
