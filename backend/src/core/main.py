"""
Punto inicial del pipeline EN VIVO: la camara.

Muestra el video con las dos barras y la deteccion de la placa en tiempo real.
Cuando una placa cruza la zona, corre la cadena completa sobre ese frame:

    frame -> [ETAPA 0] recorte del carro -> [ETAPA 1] placa horizontal
          -> [filtros] -> [ETAPA 2] crops por caracter -> [ETAPA 3] texto

Mismos modelos y mismas etapas que el batch (pipeline.py).

Ejecutar desde backend/:
    python -m src.core.main                           # webcam por defecto (indice 0)
    python -m src.core.main video.mp4                 # archivo grabado (desarrollo)
    python -m src.core.main http://192.168.x.x:4747/video   # celular (DroidCam/IP Webcam)
    python -m src.core.main 1                         # otra webcam por indice
"""

from __future__ import annotations

import os
import sys
import time
import datetime
import cv2

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(DIR, "camara"))
sys.path.insert(0, os.path.join(DIR, "pipeline"))

# Flag de prueba: filtros a veces empeora el OCR (ver pipeline.py).
# True  -> enderezada -> filtros -> segmentacion
# False -> enderezada -> segmentacion (cruda, sin filtros)
USAR_FILTROS = False

# Límite de velocidad del campus (km/h)
LIMITE_VELOCIDAD = 50.0

# Importaciones del pipeline
from camara import iniciar
import deteccion_carros as etapa0
import deteccion_placas as etapa1
import filtros as etapa_filtros
import segmentacion as etapa2
import ocr as etapa3

# Integración con el servidor FastAPI (tiempo real)
try:
    from src.app.realtime import broadcast_event, broadcast_status, set_current_frame
    from src.app.events_db import (
        insert_evento, insert_vision, insert_difuso,
        lookup_vehiculo_id, count_reincidencias,
    )
    REALTIME_ENABLED = True
    print("[REALTIME] Integración con FastAPI activa.")
except ImportError:
    REALTIME_ENABLED = False
    print("[REALTIME] FastAPI no disponible — modo standalone.")

    # Stubs vacíos para que el código de abajo funcione igual
    def broadcast_event(data): pass
    def broadcast_status(fps, camera_connected=True): pass
    def set_current_frame(jpeg): pass
    def insert_evento(**kw): return None
    def insert_vision(**kw): pass
    def insert_difuso(**kw): pass
    def lookup_vehiculo_id(placa): return None
    def count_reincidencias(placa): return 0


# ── Helpers ────────────────────────────────────────────────────────────────────

def _clasificar_evento(velocidad: float, limite: float, reincidencias: int) -> str:
    exceso = velocidad - limite
    if exceso <= 0:
        return "normal"
    if exceso <= 10:
        return "advertencia"
    if exceso <= 25 or reincidencias < 2:
        return "infraccion"
    return "grave"


def _nivel_riesgo(tipo_evento: str, exceso: float, reincidencias: int) -> str:
    if tipo_evento == "normal":
        return "bajo"
    if tipo_evento == "advertencia":
        return "medio"
    if tipo_evento == "grave" or (exceso > 20 and reincidencias >= 3):
        return "critico"
    return "alto"


def _dias_sancion(tipo_evento: str, reincidencias: int) -> int:
    if tipo_evento in ("normal", "advertencia"):
        return 0
    base = 3 if tipo_evento == "infraccion" else 7
    return min(base + reincidencias, 30)


def _storage_path(evento_id: str, nombre: str) -> str:
    """Ruta relativa bajo storage/ para servir via /static/."""
    return f"eventos/{evento_id}/{nombre}"


def _guardar_frame(evento_id: str, nombre: str, frame) -> str:
    """Guarda frame en storage/eventos/<id>/ y devuelve ruta relativa."""
    from pathlib import Path
    base = Path(__file__).resolve().parents[2] / "storage" / "eventos" / evento_id
    base.mkdir(parents=True, exist_ok=True)
    ruta = base / nombre
    cv2.imwrite(str(ruta), frame)
    return _storage_path(evento_id, nombre)


# ── Callback principal ────────────────────────────────────────────────────────

def _hacer_al_capturar(
    modelo, cfg, cfg_filtros, modelo_seg, modelo_ocr, classes_ocr,
    modelo_carros, cfg_carros,
):
    """Genera la función callback que la cámara llama al detectar un cruce."""

    def al_capturar(nombre: str, frame, velocidad: float = 0.0):
        # ─ ETAPA 0: detectar carro ────────────────────────────────────────────
        if modelo_carros is not None:
            carro = etapa0.detectar_carro(modelo_carros, frame, cfg_carros)
            if carro is None:
                print(f"  [SIN CARRO] {nombre}")
                return None
            etapa0.guardar_deteccion(nombre, frame, carro, cfg_carros)
            base = etapa0.recortar(frame, carro, cfg_carros.get("margen", 0.08))
            bbox_v = {
                "x": int(carro[0]), "y": int(carro[1]),
                "w": int(carro[2] - carro[0]), "h": int(carro[3] - carro[1]),
            }
            conf_v = float(getattr(carro, "conf", 0.95))
        else:
            base = frame
            bbox_v = None
            conf_v = None

        # ─ ETAPA 1: detectar + enderezar placa ───────────────────────────────
        placa, bbox = etapa1.procesar_frame(modelo, base, cfg, return_bbox=True)
        if placa is None:
            print(f"  [SIN PLACA] {nombre}")
            return None

        etapa1.guardar_deteccion(nombre, base, bbox, cfg)
        etapa1.guardar_enderezada(nombre, placa, cfg)
        bbox_p = {
            "x": int(bbox[0]), "y": int(bbox[1]),
            "w": int(bbox[2] - bbox[0]), "h": int(bbox[3] - bbox[1]),
        }
        conf_p = float(getattr(bbox, "conf", 0.92))

        # ─ Filtros (opcional) ─────────────────────────────────────────────────
        if USAR_FILTROS:
            entrada_seg = etapa_filtros.filtrar(placa, cfg_filtros)
            etapa_filtros.guardar(nombre, entrada_seg, cfg_filtros)
        else:
            entrada_seg = placa

        # ─ ETAPA 2: segmentar caracteres ─────────────────────────────────────
        _, crops = etapa2.segmentar(entrada_seg, modelo_seg)
        etapa2.guardar(nombre, crops)

        # ─ ETAPA 3: OCR ──────────────────────────────────────────────────────
        texto = etapa3.clasificar(crops, modelo_ocr, classes_ocr)
        etapa3.guardar_resultado(nombre, texto)
        print(f"  [OK] {nombre}: {len(crops)} crops -> '{texto}'  vel={velocidad:.1f} km/h")

        # ─ Lógica de evento ───────────────────────────────────────────────────
        placa_str = texto.upper().strip() if texto else "DESCONOCIDA"
        reincidencias = count_reincidencias(placa_str)
        tipo_evento   = _clasificar_evento(velocidad, LIMITE_VELOCIDAD, reincidencias)
        nivel_riesgo  = _nivel_riesgo(tipo_evento, velocidad - LIMITE_VELOCIDAD, reincidencias)
        dias_sancion  = _dias_sancion(tipo_evento, reincidencias)
        estado_rev    = "automatica" if tipo_evento == "normal" else "pendiente"
        conf_ocr      = float(len(crops)) / 7.0 if crops else 0.5   # approx; reemplazar con conf real del OCR

        # ─ Guardar frames en disco ────────────────────────────────────────────
        import uuid
        evento_id_str = str(uuid.uuid4())[:8].upper()
        evento_id_full = f"EVT-{evento_id_str}"

        ruta_frame = _guardar_frame(evento_id_full, "frame.jpg", frame)
        ruta_placa = _guardar_frame(evento_id_full, "placa.jpg", placa)

        # ─ Persistir en DB ────────────────────────────────────────────────────
        vehiculo_id = lookup_vehiculo_id(placa_str)
        db_id = insert_evento(
            placa_ocr=placa_str,
            placa_validada=placa_str,
            velocidad=velocidad,
            limite_velocidad=LIMITE_VELOCIDAD,
            tipo_evento=tipo_evento,
            estado_revision=estado_rev,
            estado_notificacion="pendiente",
            nivel_riesgo=nivel_riesgo,
            dias_sancion_sugeridos=dias_sancion,
            confianza_ocr=min(conf_ocr, 1.0),
            reincidencias=reincidencias,
            imagen_frame=ruta_frame,
            imagen_placa=ruta_placa,
            vehiculo_id=vehiculo_id,
        )

        if db_id:
            insert_vision(
                evento_id=db_id,
                vehiculo_detectado=(modelo_carros is not None),
                confianza_vehiculo=conf_v,
                bbox_vehiculo=bbox_v,
                placa_detectada=True,
                confianza_placa=conf_p,
                bbox_placa=bbox_p,
                ruta_placa_enderezada=ruta_placa,
                caracteres_segmentados=len(crops),
                resultado_ocr=placa_str,
                confianza_ocr=min(conf_ocr, 1.0),
            )

            exceso = max(0.0, velocidad - LIMITE_VELOCIDAD)
            insert_difuso(
                evento_id=db_id,
                exceso_velocidad=exceso,
                pertenencia_velocidad={
                    "normal":   max(0.0, 1.0 - exceso / 10),
                    "moderado": max(0.0, min(1.0, exceso / 10)),
                    "severo":   max(0.0, (exceso - 20) / 10),
                },
                pertenencia_reincidencia={
                    "sin_reincidencia": 1.0 if reincidencias == 0 else 0.0,
                    "reincidente": min(1.0, reincidencias / 3.0),
                },
                pertenencia_confianza_ocr={
                    "baja":  max(0.0, 1.0 - conf_ocr * 2),
                    "media": max(0.0, min(1.0, conf_ocr)),
                    "alta":  max(0.0, conf_ocr - 0.5) * 2,
                },
                nivel_riesgo=nivel_riesgo,
                dias_sancion_sugeridos=dias_sancion,
                reglas_activadas=[
                    f"exceso={exceso:.1f} tipo={tipo_evento} reincidencias={reincidencias}"
                ],
            )

            # ─ Broadcast WebSocket ────────────────────────────────────────────
            broadcast_event({
                "id": evento_id_full,
                "placa_ocr": placa_str,
                "placa_validada": placa_str,
                "velocidad": velocidad,
                "limite_velocidad": LIMITE_VELOCIDAD,
                "tipo_evento": tipo_evento,
                "estado_revision": estado_rev,
                "estado_notificacion": "pendiente",
                "nivel_riesgo": nivel_riesgo,
                "dias_sancion_sugeridos": dias_sancion,
                "confianza_ocr": min(conf_ocr, 1.0),
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
                    "caracteres_segmentados": len(crops),
                    "resultado_ocr": placa_str,
                    "confianza_ocr": min(conf_ocr, 1.0),
                },
                "fuzzy": {
                    "exceso_velocidad": exceso,
                    "nivel_riesgo": nivel_riesgo,
                    "dias_sancion_sugeridos": dias_sancion,
                    "reglas_activadas": [],
                    "salida_crisp": None,
                },
            })

        return texto

    return al_capturar


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cfg         = etapa1.cargar_config()
    modelo      = etapa1.cargar_modelo(cfg)
    conf        = cfg.get("conf_min", 0.25)
    cfg_filtros = etapa_filtros.cargar_config()
    modelo_seg  = etapa2.cargar_modelo()
    modelo_ocr, classes_ocr = etapa3.cargar_modelo()

    cfg_carros = etapa0.cargar_config()
    try:
        modelo_carros = etapa0.cargar_modelo(cfg_carros)
    except FileNotFoundError:
        modelo_carros = None
        print("[ETAPA 0] modelo de carros no entrenado -> fallback: placa sobre frame completo.")

    print("Modelos cargados.")

    al_capturar = _hacer_al_capturar(
        modelo, cfg, cfg_filtros, modelo_seg, modelo_ocr, classes_ocr,
        modelo_carros, cfg_carros,
    )

    fuente = 0
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        fuente = int(arg) if arg.isdigit() else arg

    iniciar(
        detector=lambda frame: etapa1.detectar(modelo, frame, conf),
        al_capturar=al_capturar,
        fuente=fuente,
        on_frame=set_current_frame,          # hook para el MJPEG feed
        on_fps=broadcast_status,             # hook para status en WS
    )
