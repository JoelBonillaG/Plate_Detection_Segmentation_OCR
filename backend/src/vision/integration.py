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

sys.path.insert(0, str(DIR))            # para 'import bridge'
sys.path.insert(0, str(DIR / "pipeline"))
sys.path.insert(0, str(BACKEND_DIR))

import cadena
import bridge


# Eventos y status viajan por el puente WS hacia la API (procesos separados).
def broadcast_event(payload: dict) -> None:
    bridge.send_event(payload)


def broadcast_status(fps: float, source_type: str = None, source_name: str = None,
                     camera_connected: bool = True) -> None:
    bridge.send_status({
        "fps": round(fps, 1),
        "camera_connected": camera_connected,
        "backend_connected": True,
        "current_time": datetime.datetime.now().strftime("%H:%M:%S"),
        "source_type": source_type,   # "video" | "live"
        "source_name": source_name,   # nombre del video o "EN VIVO"
    })


try:
    from src.app.events_db import (
        count_reincidencias,
        insert_difuso,
        insert_evento,
        insert_vision,
    )
    from src.app.fuzzy import evaluar as fuzzy_evaluar, LIMITE_VELOCIDAD
    from src.app.runtime import get_runtime

    REALTIME_ENABLED = True
    print("[REALTIME] Integracion con FastAPI activa.")
except ImportError:
    REALTIME_ENABLED = False
    LIMITE_VELOCIDAD = 20.0
    print("[REALTIME] FastAPI no disponible; modo standalone.")

    def get_runtime(): return {}

    def insert_evento(**kw): return None
    def insert_vision(**kw): pass
    def insert_difuso(**kw): pass
    def count_reincidencias(placa): return 0

    class _FallbackResult:
        tipo_evento = "normal"; nivel_riesgo = "bajo"; dias_sancion = 0
        exceso = 0.0; es_temeraria = False; salida_crisp = 0.0
        pertenencia_exceso = {}; pertenencia_reincidencia = {}; reglas_activadas = []

    def fuzzy_evaluar(velocidad, reincidencia): return _FallbackResult()


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
        # redondeo a 1 decimal en el ORIGEN -> DB, WS, correo y entrada al difuso
        # quedan limpios (evita 1.4535666218035004 km/h en el panel).
        velocidad = round(float(velocidad or 0.0), 1)
        # SPEED BOOST (presentacion): suma km/h configurables desde el frontend para
        # demostrar la sancion difusa en tiempo real (los carros del video van lento).
        rc = get_runtime()
        if rc.get("speed_boost_enabled"):
            velocidad = round(velocidad + float(rc.get("speed_boost_kmh", 0) or 0), 1)
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

        # Sistema difuso Mamdani — evaluación completa
        fz = fuzzy_evaluar(velocidad, reincidencias)
        tipo_evento = fz.tipo_evento
        riesgo      = fz.nivel_riesgo
        sancion     = max(0, fz.dias_sancion)   # -1 (temeraria) → 0 para DB
        estado_rev  = "automatica" if tipo_evento == "normal" else "pendiente"

        evento_id_full = f"EVT-{str(uuid.uuid4())[:8].upper()}"

        # frame.jpg = miniatura del evento en la lista -> se escribe ANTES del broadcast
        # para que NO salga la imagen rota. El resto (detalle: se abre al click ms despues)
        # se difiere para no añadir latencia a la llegada del evento.
        guardar_antes = [("frame.jpg", frame), ("placa.jpg", resultado.placa)]
        por_guardar = []
        ruta_frame = storage_path(evento_id_full, "frame.jpg")
        ruta_placa = storage_path(evento_id_full, "placa.jpg")  # enderezada

        ruta_placa_detectada = None
        if resultado.placa_crop is not None and resultado.placa_crop.size:
            ruta_placa_detectada = storage_path(evento_id_full, "placa_detectada.jpg")
            por_guardar.append(("placa_detectada.jpg", resultado.placa_crop))

        ruta_filtrada = None
        if resultado.uso_filtros and resultado.entrada_segmentacion is not None:
            ruta_filtrada = storage_path(evento_id_full, "placa_filtrada.jpg")
            por_guardar.append(("placa_filtrada.jpg", resultado.entrada_segmentacion))

        ruta_segmentacion = None
        if resultado.seg_overlay is not None and resultado.seg_overlay.size:
            ruta_segmentacion = storage_path(evento_id_full, "segmentacion.jpg")
            por_guardar.append(("segmentacion.jpg", resultado.seg_overlay))

        # recorte por caracter (crop[i] <-> ocr_por_caracter[i]) para el front
        for i, crop in enumerate(resultado.crops or []):
            if crop is not None and getattr(crop, "size", 0) and i < len(ocr_por_caracter):
                nombre_crop = f"char_{i:02d}.jpg"
                ocr_por_caracter[i]["ruta"] = storage_path(evento_id_full, nombre_crop)
                por_guardar.append((nombre_crop, crop))

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
                    "enderezado": "activo" if resultado.uso_enderezado else "omitido",
                    "ocr_por_caracter": ocr_por_caracter,
                },
            },
            "fuzzy": {
                "exceso_velocidad": fz.exceso,
                "pertenencia_velocidad": fz.pertenencia_exceso,
                "pertenencia_reincidencia": fz.pertenencia_reincidencia,
                "pertenencia_confianza_ocr": {},   # no usado en este FIS
                "nivel_riesgo": riesgo,
                "dias_sancion_sugeridos": sancion,
                "reglas_activadas": fz.reglas_activadas,
                "salida_crisp": fz.salida_crisp,
                "es_temeraria": fz.es_temeraria,
            },
        }

        # 1) escribe la miniatura (frame/placa) para que la lista no muestre imagen rota
        for nombre_img, img in guardar_antes:
            try:
                guardar_frame(evento_id_full, nombre_img, img)
            except Exception as exc:
                print(f"[IMG] No se pudo guardar {nombre_img}: {exc}")

        # 2) Broadcast al frontend — ya con la miniatura en disco; el detalle (crops,
        #    segmentacion) se escribe despues (se abre al click, ms mas tarde).
        broadcast_event(payload)
        print(f"  [EVENTO] {evento_id_full}: placa={placa_str} vel={velocidad:.1f} km/h tipo={tipo_evento}")

        # 3) ahora el resto de imagenes (detalle) a disco
        for nombre_img, img in por_guardar:
            try:
                guardar_frame(evento_id_full, nombre_img, img)
            except Exception as exc:
                print(f"[IMG] No se pudo guardar {nombre_img}: {exc}")

        try:
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
                    exceso_velocidad=fz.exceso,
                    pertenencia_velocidad=payload["fuzzy"]["pertenencia_velocidad"],
                    pertenencia_reincidencia=payload["fuzzy"]["pertenencia_reincidencia"],
                    pertenencia_confianza_ocr=payload["fuzzy"]["pertenencia_confianza_ocr"],
                    nivel_riesgo=riesgo,
                    dias_sancion_sugeridos=sancion,
                    reglas_activadas=payload["fuzzy"]["reglas_activadas"],
                )

        except Exception as exc:
            print(f"[DB] No se pudo persistir evento {evento_id_full}: {exc}")

        return texto

    return al_capturar
