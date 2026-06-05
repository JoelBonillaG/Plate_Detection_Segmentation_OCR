"""Estado de runtime COMPARTIDO entre el proceso de la API y el de vision.

Son procesos separados, asi que el estado no puede vivir en memoria: se persiste
en un JSON en storage/. La API lo escribe (endpoints del frontend) y vision lo
lee al capturar cada evento.

Uso actual: "speed boost" para la presentacion -> suma km/h a la velocidad
detectada (los carros del video van lento y nunca pasan el limite de 20 km/h,
asi se puede demostrar la sancion del sistema difuso en tiempo real).
"""
from __future__ import annotations

import json
from pathlib import Path

# storage/ a nivel raiz del proyecto (mismo dir que usan API y vision).
_FILE = Path(__file__).resolve().parents[3] / "storage" / "runtime_config.json"

_DEFAULT = {
    "speed_boost_enabled": False,
    "speed_boost_kmh": 0.0,
    # fuente de video que la vision debe usar (hot-swap sin reiniciar el proceso).
    # source = ruta absoluta del .mp4 o "live"; source_version se incrementa en cada
    # cambio -> la vision detecta el cambio y reabre la fuente.
    "source": None,
    "source_version": 0,
}


def get_runtime() -> dict:
    try:
        data = json.loads(_FILE.read_text(encoding="utf-8"))
        return {**_DEFAULT, **data}
    except Exception:
        return dict(_DEFAULT)


def set_runtime(**cambios) -> dict:
    actual = get_runtime()
    actual.update(cambios)
    try:
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        _FILE.write_text(json.dumps(actual), encoding="utf-8")
    except Exception as exc:
        print(f"[RUNTIME] No se pudo guardar estado: {exc}")
    return actual
