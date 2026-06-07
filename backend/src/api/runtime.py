"""Estado de runtime compartido entre el proceso de la API y el de vision.

Son procesos separados, por lo que el estado se persiste en storage/. La API lo
actualiza desde los endpoints del frontend y vision lo lee al capturar eventos.
Tambien almacena el ajuste opcional de velocidad usado en pruebas controladas
del sistema difuso.
"""
from __future__ import annotations

import json
from pathlib import Path

# Archivo de estado compartido en la raiz del proyecto.
_FILE = Path(__file__).resolve().parents[3] / "storage" / "runtime_config.json"

_DEFAULT = {
    "speed_boost_enabled": False,
    "speed_boost_kmh": 0.0,
    # Fuente de video que el proceso de vision debe usar.
    # source_version se incrementa para reabrir la fuente cuando cambia.
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
