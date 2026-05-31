"""
Punto de integracion entre el pipeline de camara/cadena y el backend FastAPI.

Aqui vive lo que no pertenece al loop de camara ni a la cadena OCR:
persistencia en DB, payloads WebSocket, rutas MJPEG y almacenamiento estatico.
"""

from __future__ import annotations

import datetime
import sys
import uuid
from pathlib import Path

import cv2

DIR = Path(__file__).resolve().parent
SRC_DIR = DIR.parent
BACKEND_DIR = SRC_DIR.parent
PROJECT_DIR = BACKEND_DIR.parent

sys.path.insert(0, str(DIR / "pipeline"))
sys.path.insert(0, str(BACKEND_DIR))

import cadena

LIMITE_VELOCIDAD = 50.0

try:
    from src.app.realtime import broadcast_event, broadcast_status, set_current_frame
    from src.app.events_db import (
        count_reincidencias,
        insert_difuso,
        insert_evento,
        insert_vision,
        lookup_vehiculo_id,
    )

    REALTIME_ENABLED = True
    print("[REALTIME] Integracion con FastAPI activa.")
except ImportError:
    REALTIME_ENABLED = False
    print("[REALTIME] FastAPI no disponible; modo standalone.")

    def broadcast_event(data): pass
    def broadcast_status(fps, camera_connected=True): pass
    def set_current_frame(jpeg): pass
    def insert_evento(**kw): return None
    def insert_vision(**kw): pass
    def insert_difuso(**kw): pass
    def lookup_vehiculo_id(placa): return None
    def count_reincidencias(placa): return 0


def clasificar_evento(velocidad: float, limite: float, reincidencias: int) -> str:
    exceso = velocidad - limite
    if exceso <= 0:
        return "normal"
    if exceso <= 10:
        return "advertencia"
    if exceso <= 25 or reincidencias < 2:
        return "infraccion"
    return "grave"


def nivel_riesgo(tipo_evento: str, exceso: float, reincidencias: int) -> str:
    if tipo_evento == "normal":
        return "bajo"
    if tipo_evento == "advertencia":
        return "medio"
    if tipo_evento == "grave" or (exceso > 20 and reincidencias >= 3):
        return "critico"
    return "alto"


def dias_sancion(tipo_evento: str, reincidencias: int) -> int:
    if tipo_evento in ("normal", "advertencia"):
        return 0
    base = 3 if tipo_evento == "infraccion" else 7
    return min(base + reincidencias, 30)


def storage_path(evento_id: str, nombre: str) -> str:
    return f"eventos/{evento_id}/{nombre}"


def guardar_frame(evento_id: str, nombre: str, frame) -> str:
    base = PROJECT_DIR / "storage" / "eventos" / evento_id
    base.mkdir(parents=True, exist_ok=True)
    ruta = base / nombre
    if not cv2.imwrite(str(ruta), frame):
        raise RuntimeError(f"No se pudo guardar imagen: {ruta}")
    return storage_path(evento_id, nombre)


def bbox_dict(bbox) -> dict | None:
    if bbox is None:
        return None
    x1, y1, x2, y2 = bbox
    return {
        "x": int(x1),
        "y": int(y1),
        "w": int(x2 - x1),
        "h": int(y2 - y1),
    }


def hacer_al_capturar(modelos):
    """Callback que la camara llama cuando un carro completa el cruce."""

    def al_capturar(nombre: str, frame, velocidad: float = 0.0):
        velocidad = float(velocidad or 0.0)
        resultado = cadena.procesar_frame_detallado(nombre, frame, modelos)
        if resultado is None:
            return None

        texto = resultado.texto or ""
        placa_str = texto.upper().strip() or "DESCONOCIDA"
        bbox_v = bbox_dict(resultado.carro_bbox)
        bbox_p = bbox_dict(resultado.placa_bbox)
        # confianzas REALES del pipeline (YOLO carro/placa, softmax OCR por caracter)
        conf_v = resultado.conf_vehiculo
        conf_p = resultado.conf_placa
        conf_ocr = float(resultado.conf_ocr or 0.0)
        # [(caracter, confianza), ...] -> lista de dicts serializable
        ocr_por_caracter = [
            {"caracter": ch, "confianza": round(float(c), 4)}
            for ch, c in (resultado.ocr_por_caracter or [])
        ]

        try:
            reincidencias = count_reincidencias(placa_str)
        except Exception as exc:
            print(f"[DB] No se pudo consultar reincidencias: {exc}")
            reincidencias = 0

        tipo_evento = clasificar_evento(velocidad, LIMITE_VELOCIDAD, reincidencias)
        exceso = max(0.0, velocidad - LIMITE_VELOCIDAD)
        riesgo = nivel_riesgo(tipo_evento, velocidad - LIMITE_VELOCIDAD, reincidencias)
        sancion = dias_sancion(tipo_evento, reincidencias)
        estado_rev = "automatica" if tipo_evento == "normal" else "pendiente"

        evento_id_full = f"EVT-{str(uuid.uuid4())[:8].upper()}"
        ruta_frame = guardar_frame(evento_id_full, "frame.jpg", frame)
        ruta_placa = guardar_frame(evento_id_full, "placa.jpg", resultado.placa)  # enderezada
        # recorte CRUDO de la placa (antes de enderezar)
        ruta_placa_detectada = None
        if resultado.placa_crop is not None and resultado.placa_crop.size:
            ruta_placa_detectada = guardar_frame(
                evento_id_full, "placa_detectada.jpg", resultado.placa_crop)
        # placa filtrada (solo si paso por filtros)
        ruta_filtrada = None
        if resultado.uso_filtros and resultado.entrada_segmentacion is not None:
            ruta_filtrada = guardar_frame(
                evento_id_full,
                "placa_filtrada.jpg",
                resultado.entrada_segmentacion,
            )
        # visualizacion de la segmentacion (placa con las cajas de caracteres)
        ruta_segmentacion = None
        if resultado.seg_overlay is not None and resultado.seg_overlay.size:
            ruta_segmentacion = guardar_frame(
                evento_id_full, "segmentacion.jpg", resultado.seg_overlay)

        payload = {
            "id": evento_id_full,
            "db_id": None,
            "placa_ocr": placa_str,
            "placa_validada": placa_str,
            "velocidad": velocidad,
            "limite_velocidad": LIMITE_VELOCIDAD,
            "tipo_evento": tipo_evento,
            "estado_revision": estado_rev,
            "estado_notificacion": "pendiente",
            "nivel_riesgo": riesgo,
            "dias_sancion_sugeridos": sancion,
            "confianza_ocr": conf_ocr,
            "reincidencias": reincidencias,
            "imagen_frame": ruta_frame,
            "imagen_placa": ruta_placa,
            "fecha_hora": datetime.datetime.now().isoformat(),
            "vehiculo": {
                "propietario_nombre": None,
                "propietario_correo": None,
            },
            "vision": {
                "confianza_vehiculo": conf_v,
                "bbox_vehiculo": bbox_v,
                "confianza_placa": conf_p,
                "bbox_placa": bbox_p,
                "ruta_placa_detectada": ruta_placa_detectada,
                "ruta_placa_enderezada": ruta_placa,
                "ruta_placa_filtrada": ruta_filtrada,
                "ruta_segmentacion": ruta_segmentacion,
                "caracteres_segmentados": len(resultado.crops),
                "resultado_ocr": placa_str,
                "confianza_ocr": conf_ocr,
                "ocr_por_caracter": ocr_por_caracter,
                "metadata": {
                    "pipeline": "cadena.py",
                    "captura": nombre,
                    "filtros": "activos" if resultado.uso_filtros else "omitidos",
                    "ocr_por_caracter": ocr_por_caracter,
                },
            },
            "fuzzy": {
                "exceso_velocidad": exceso,
                "pertenencia_velocidad": {
                    "normal": max(0.0, 1.0 - exceso / 10),
                    "moderado": max(0.0, min(1.0, exceso / 10)),
                    "severo": max(0.0, (exceso - 20) / 10),
                },
                "pertenencia_reincidencia": {
                    "sin_reincidencia": 1.0 if reincidencias == 0 else 0.0,
                    "reincidente": min(1.0, reincidencias / 3.0),
                },
                "pertenencia_confianza_ocr": {
                    "baja": max(0.0, 1.0 - conf_ocr * 2),
                    "media": max(0.0, min(1.0, conf_ocr)),
                    "alta": max(0.0, conf_ocr - 0.5) * 2,
                },
                "nivel_riesgo": riesgo,
                "dias_sancion_sugeridos": sancion,
                "reglas_activadas": [
                    f"exceso={exceso:.1f} tipo={tipo_evento} reincidencias={reincidencias}"
                ],
                "salida_crisp": None,
            },
        }

        try:
            vehiculo_id = lookup_vehiculo_id(placa_str)
            db_id = insert_evento(
                placa_ocr=placa_str,
                placa_validada=placa_str,
                velocidad=velocidad,
                limite_velocidad=LIMITE_VELOCIDAD,
                tipo_evento=tipo_evento,
                estado_revision=estado_rev,
                estado_notificacion="pendiente",
                nivel_riesgo=riesgo,
                dias_sancion_sugeridos=sancion,
                confianza_ocr=conf_ocr,
                reincidencias=reincidencias,
                imagen_frame=ruta_frame,
                imagen_placa=ruta_placa,
                vehiculo_id=vehiculo_id,
            )
            payload["db_id"] = db_id

            if db_id:
                insert_vision(
                    evento_id=db_id,
                    vehiculo_detectado=resultado.carro_bbox is not None,
                    confianza_vehiculo=conf_v,
                    bbox_vehiculo=bbox_v,
                    placa_detectada=resultado.placa_bbox is not None,
                    confianza_placa=conf_p,
                    bbox_placa=bbox_p,
                    ruta_placa_detectada=ruta_placa_detectada,
                    ruta_placa_enderezada=ruta_placa,
                    ruta_placa_filtrada=ruta_filtrada,
                    ruta_segmentacion=ruta_segmentacion,
                    caracteres_segmentados=len(resultado.crops),
                    resultado_ocr=placa_str,
                    confianza_ocr=conf_ocr,
                    metadata=payload["vision"]["metadata"],
                )
                insert_difuso(
                    evento_id=db_id,
                    exceso_velocidad=exceso,
                    pertenencia_velocidad=payload["fuzzy"]["pertenencia_velocidad"],
                    pertenencia_reincidencia=payload["fuzzy"]["pertenencia_reincidencia"],
                    pertenencia_confianza_ocr=payload["fuzzy"]["pertenencia_confianza_ocr"],
                    nivel_riesgo=riesgo,
                    dias_sancion_sugeridos=sancion,
                    reglas_activadas=payload["fuzzy"]["reglas_activadas"],
                )
        except Exception as exc:
            print(f"[DB] No se pudo persistir evento {evento_id_full}: {exc}")

        broadcast_event(payload)
        print(f"  [EVENTO] {evento_id_full}: placa={placa_str} vel={velocidad:.1f} km/h")
        return texto

    return al_capturar
