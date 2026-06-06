"""
Punto de entrada del modulo de vision.

Arranca el puente WS hacia la API y el loop de camara. La API recibe los frames
en /ws/ingest y los reenvia al browser por /ws/video; los eventos/status viajan
por el mismo puente y salen por /ws cuando un carro completa el cruce.

Ejecutar desde backend/:
    python -m src.vision.main
    python -m src.vision.main video.mp4
    python -m src.vision.main http://192.168.x.x:4747/video
    python -m src.vision.main 1
"""

from __future__ import annotations

import sys
import json
from pathlib import Path

DIR = Path(__file__).resolve().parent
SRC_DIR = DIR.parent
BACKEND_DIR = SRC_DIR.parent

sys.path.insert(0, str(DIR))
sys.path.insert(0, str(DIR / "camara"))
sys.path.insert(0, str(DIR / "pipeline"))
sys.path.insert(0, str(BACKEND_DIR))

# ── config del modulo de vision (vision/config.json) -> sin tocar el codigo ──
#   usar_filtros    : True  -> enderezada -> filtros -> segmentacion
#                     False -> segmentacion directa (sin bilateral/unsharp: mas detalle)
#   usar_enderezado : True  -> corrige perspectiva (warp) si la placa esta torcida
#                     False -> placa al OCR SIN warp (recorte nativo, maxima calidad)
#   fuente          : null -> usa camara_idx de camara/config.json ; o int/ruta/URL.
#                     El argumento de linea de comandos SIEMPRE manda sobre esto.
_CONFIG_PATH = DIR / "config.json"
_CFG_DEFAULTS = {"usar_filtros": False, "usar_enderezado": True, "fuente": None}
_cfg = dict(_CFG_DEFAULTS)
try:
    with open(_CONFIG_PATH, encoding="utf-8") as _f:
        _cfg.update(json.load(_f))
except FileNotFoundError:
    print(f"[CONFIG] {_CONFIG_PATH} no existe -> usando valores por defecto.")

USAR_FILTROS    = _cfg["usar_filtros"]
USAR_ENDEREZADO = _cfg["usar_enderezado"]

from camara import iniciar, DETECTAR_CARROS, CAMARA_IDX
import cadena
import bridge
from integration import hacer_al_capturar, broadcast_status


if __name__ == "__main__":
    # arrancar el puente WS hacia la API antes del loop de camara
    bridge.start()

    # DETECTAR_CARROS (en camara.py) es la unica fuente de verdad: ajusta tanto
    # el detector (cadena) como el rastreo del cruce (lineas).
    modelos = cadena.cargar_modelos(usar_filtros=USAR_FILTROS, usar_carros=DETECTAR_CARROS,
                                    usar_enderezado=USAR_ENDEREZADO)
    print("Modelos cargados.")

    def detectar_en_vivo(frame):
        return cadena.detectar_placa_en_vivo(frame, modelos)

    # fuente: config (null -> camara_idx).
    fuente = CAMARA_IDX if _cfg.get("fuente") is None else _cfg["fuente"]
    # la fuente elegida desde el FRONTEND (runtime_config.json) manda sobre el config:
    # asi, cuando el API lanza la vision bajo demanda, arranca con el video elegido.
    try:
        from src.api.runtime import get_runtime
        _src = get_runtime().get("source")
        if _src == "live":
            fuente = CAMARA_IDX
        elif _src == "idle":
            fuente = "idle"                                  # arranca DETENIDO
        elif _src:
            fuente = int(_src) if str(_src).isdigit() else _src   # indice de camara o ruta
    except Exception:
        pass
    # el argumento CLI manda sobre todo (start_vision.ps1 "ruta\\video.mp4").
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        fuente = int(arg) if arg.isdigit() else arg

    iniciar(
        detector=detectar_en_vivo,
        al_capturar=hacer_al_capturar(modelos),
        fuente=fuente,
        on_frame=bridge.send_frame,         # cada frame anotado -> WS /ws/video
        on_fps=broadcast_status,            # ~1/s -> status WebSocket
    )
