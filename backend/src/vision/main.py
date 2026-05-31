"""
Punto inicial del pipeline EN VIVO para el backend.

La camara decide cuando existe un cruce. La integracion con DB, WebSocket y
MJPEG vive en `integration.py` para no mezclar responsabilidades aqui.

Ejecutar desde `backend/`:
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
from integration import hacer_al_capturar, broadcast_status, set_current_frame


if __name__ == "__main__":
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
        on_frame=set_current_frame,
        on_fps=broadcast_status,
    )
