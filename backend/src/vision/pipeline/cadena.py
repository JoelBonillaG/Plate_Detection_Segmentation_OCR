"""
Cadena-por-frame compartida (modo BATCH y modo EN VIVO usan ESTO).

Procesa un frame de punta a punta:
    frame -> [ETAPA 0] recorte carro -> [ETAPA 1] placa horizontal
          -> [filtros opcional] -> [ETAPA 2] crops por caracter -> [ETAPA 3] texto

El origen del frame se define en batch.py o main.py, por lo que la cadena
mantiene una unica implementacion para modo batch y modo en vivo.
"""

import os
import sys
from dataclasses import dataclass

import cv2

# Permite importar los paquetes de las etapas desde este directorio.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deteccion_carros as etapa0
import deteccion_placas as etapa1
import filtros as etapa_filtros
import segmentacion as etapa2
import ocr as etapa3
# Postprocesamiento de cajas y formato de placa.
from segmentacion import postprocesamiento as seg_pp
from ocr import postprocesamiento as ocr_pp
from deteccion_placas import deskew_rotacion as deskew   # enderezado por ROTACION (Hough)

# Criterio de validez de placa: una placa ecuatoriana tiene 6-7 caracteres
# (3 letras + 3/4 digitos). Si la segmentacion queda fuera de ese rango, el
# frame se descarta para evitar eventos inconsistentes o lecturas incompletas.
MIN_CHARS_PLACA = 6
MAX_CHARS_PLACA = 7


@dataclass
class Modelos:
    """Todos los modelos + config ya cargados. Se construye UNA vez al arrancar."""
    cfg: dict
    modelo: object              # ETAPA 1 (placas)
    conf: float                 # umbral de deteccion de placa (para detectar en vivo)
    cfg_filtros: dict
    modelo_seg: object          # ETAPA 2 (segmentacion)
    modelo_ocr: object          # ETAPA 3 (OCR)
    classes_ocr: object
    cfg_carros: dict
    modelo_carros: object       # ETAPA 0 (carros); None si no esta entrenado o desactivado
    usar_filtros: bool
    usar_carros: bool = True     # False -> se omite la ETAPA 0.
    usar_enderezado: bool = True # False -> se usa el recorte nativo de la placa.


def cargar_modelos(usar_filtros=False, usar_carros=True, usar_enderezado=True):
    """
    Carga los modelos y sus configs una sola vez. Devuelve un Modelos.

    usar_carros=False -> no carga el detector de carros. En ese modo, la placa
    se detecta sobre el frame completo.

    usar_enderezado=False -> la placa se procesa con el recorte nativo, sin
    correccion de perspectiva.
    """
    cfg         = etapa1.cargar_config()
    modelo      = etapa1.cargar_modelo(cfg)
    conf        = cfg.get("conf_min", 0.25)
    cfg_filtros = etapa_filtros.cargar_config()
    modelo_seg  = etapa2.cargar_modelo()
    modelo_ocr, classes_ocr = etapa3.cargar_modelo()

    # ETAPA 0: detector de carros. Si no esta disponible, la placa se busca
    # sobre el frame completo.
    cfg_carros = etapa0.cargar_config()
    if not usar_carros:
        modelo_carros = None
        print("[ETAPA 0] deteccion de carros DESACTIVADA -> placa sobre frame completo.")
    else:
        try:
            modelo_carros = etapa0.cargar_modelo(cfg_carros)
        except FileNotFoundError:
            modelo_carros = None
            print("[ETAPA 0] modelo de carros no entrenado -> placa sobre frame completo.")
            print("          entrena con: python ml/training/vehicle_detection/redes/entrenamiento.py")

    return Modelos(cfg=cfg, modelo=modelo, conf=conf, cfg_filtros=cfg_filtros,
                   modelo_seg=modelo_seg, modelo_ocr=modelo_ocr, classes_ocr=classes_ocr,
                   cfg_carros=cfg_carros, modelo_carros=modelo_carros,
                   usar_filtros=usar_filtros, usar_carros=usar_carros,
                   usar_enderezado=usar_enderezado)


def procesar_frame(nombre, frame, m):
    """
    Corre la cadena completa sobre UN frame. Guarda auditoria en cada etapa.
    Devuelve el texto de la placa leida, o None si no hubo carro/placa.

    Args:
        nombre: id de la captura (para nombrar las salidas).
        frame:  imagen BGR cruda.
        m:      Modelos ya cargados (de cargar_modelos()).
    """
    resultado = procesar_frame_detallado(nombre, frame, m)
    return resultado.texto if resultado is not None else None


def detectar_placa_en_vivo(frame, m):
    """
    Detector para el rastreo EN VIVO: carro primero, luego placa DENTRO del
    carro (zoom -> placa mas grande, menos falsos positivos del fondo).
    Devuelve (carro_bbox, placa_bbox) en coords del frame completo; cualquiera
    puede ser None. Lo usa main.py para alimentar las lineas (rastrea la placa)
    y dibujar ambas cajas; el batch no lo necesita.
    """
    # Sin modelo de carros, la placa se busca directamente sobre el frame.
    if m.modelo_carros is None:
        return None, etapa1.detectar(m.modelo, frame, m.conf)

    carro = etapa0.detectar_carro(m.modelo_carros, frame, m.cfg_carros)
    if carro is None:
        return None, None   # no hay carro -> no rastrear nada

    # Recorte del carro con margen y offset para volver al frame completo.
    x1, y1, x2, y2 = carro
    h, w = frame.shape[:2]
    margen = m.cfg_carros.get("margen", 0.08)
    mx = int((x2 - x1) * margen); my = int((y2 - y1) * margen)
    cx1 = max(0, x1 - mx); cy1 = max(0, y1 - my)
    cx2 = min(w, x2 + mx); cy2 = min(h, y2 + my)
    crop = frame[cy1:cy2, cx1:cx2]
    if crop.size == 0:
        return carro, None

    # placa DENTRO del carro
    pb = etapa1.detectar(m.modelo, crop, m.conf)
    if pb is None:
        return carro, None
    px1, py1, px2, py2 = pb
    placa = (px1 + cx1, py1 + cy1, px2 + cx1, py2 + cy1)   # -> coords del frame
    return carro, placa


# ========
# Resultado detallado para integraciones externas (backend/DB/WebSocket).

@dataclass
class ResultadoFrame:
    """Resultado completo de procesar un frame, para integraciones web/DB."""
    texto: str
    placa: object                       # placa enderezada (BGR)
    crops: list
    carro_bbox: object = None
    placa_bbox: object = None
    entrada_segmentacion: object = None
    uso_filtros: bool = False
    uso_enderezado: bool = True         # False -> la placa fue al OCR sin warp (recorte nativo)
    placa_crop: object = None           # recorte CRUDO de la placa (antes de enderezar)
    seg_overlay: object = None          # entrada de segmentacion con las cajas dibujadas
    conf_vehiculo: float = None         # confianza YOLO del carro
    conf_placa: float = None            # confianza YOLO de la placa
    conf_ocr: float = 0.0               # promedio de confianza por caracter
    ocr_por_caracter: list = None       # [(caracter, confianza), ...]


def procesar_frame_detallado(nombre, frame, m):
    """
    Igual que procesar_frame(), pero devuelve placa, crops y bboxes.
    Lo usa el backend para registrar evento, vision y difuso sin duplicar etapas.
    """
    # ETAPA 0: detectar carro -> recorte (en memoria). Sin carro, no hay placa.
    carro_bbox = None
    conf_v = None
    if m.modelo_carros is not None:
        carro_bbox, conf_v = etapa0.detectar_carro(
            m.modelo_carros, frame, m.cfg_carros, return_conf=True)
        if carro_bbox is None:
            print(f"  [SIN CARRO] {nombre}")
            return None
        etapa0.guardar_deteccion(nombre, frame, carro_bbox, m.cfg_carros)
        base = etapa0.recortar(frame, carro_bbox, m.cfg_carros.get("margen", 0.08))
    else:
        base = frame

    # ETAPA 1: detectar (con confianza) -> recortar (crudo) -> enderezar (horizontal).
    bbox, conf_p = etapa1.detectar(m.modelo, base, m.cfg.get("conf_min", 0.25),
                                   return_conf=True)
    if bbox is None:
        print(f"  [SIN PLACA] {nombre}")
        return None
    placa_crop = etapa1.recortar(base, bbox, m.cfg.get("margen", 0.08))   # crudo
    # ETAPA 1c: enderezado por rotacion cuando la configuracion lo habilita.
    if m.usar_enderezado:
        placa = deskew.enderezar_rotacion(placa_crop)
    else:
        placa = placa_crop
    etapa1.guardar_deteccion(nombre, base, bbox, m.cfg)
    etapa1.guardar_enderezada(nombre, placa, m.cfg)

    # ETAPA intermedia: filtros (segun flag usar_filtros).
    if m.usar_filtros:
        entrada_seg = etapa_filtros.filtrar(placa, m.cfg_filtros)
        etapa_filtros.guardar(nombre, entrada_seg, m.cfg_filtros)
    else:
        entrada_seg = placa

    # ETAPA 2: segmentar caracteres -> crops (+ cajas para visualizar).
    cajas, crops = etapa2.segmentar(entrada_seg, m.modelo_seg)
    # POSTPROCESAMIENTO: filtro geometrico de cajas que no corresponden a
    # caracteres, como guiones, tornillos o restos visuales.
    cajas, crops = seg_pp.filtrar_ruido(cajas, crops)

    # GATE de validez: si el numero de caracteres esta fuera del rango de una placa
    # real, lo detectado no es una placa -> se descarta (no se guarda ni registra).
    n_chars = len(crops)
    if n_chars < MIN_CHARS_PLACA or n_chars > MAX_CHARS_PLACA:
        print(f"  [DESCARTADO] {nombre}: {n_chars} caracteres "
              f"(fuera de {MIN_CHARS_PLACA}-{MAX_CHARS_PLACA}) -> no es una placa")
        return None

    etapa2.guardar(nombre, crops)

    # visualizacion de la segmentacion: entrada_seg con las cajas de caracteres
    seg_overlay = entrada_seg.copy()
    if seg_overlay.ndim == 2:
        seg_overlay = cv2.cvtColor(seg_overlay, cv2.COLOR_GRAY2BGR)
    for (sx1, sy1, sx2, sy2) in cajas:
        # La caja dibujada se reduce solo para mejorar la visualizacion.
        dx = int((sx2 - sx1) * 0.08)
        dy = int((sy2 - sy1) * 0.08)
        cv2.rectangle(seg_overlay, (sx1 + dx, sy1 + dy), (sx2 - dx, sy2 - dy), (0, 255, 0), 1)

    # ETAPA 3: OCR con FORMATO de placa forzado (3 letras + 4/3 digitos): elige la
    # mejor subsecuencia y descarta cajas sobrantes -> evita salidas tipo
    # 'IHB124514689'. Reemplaza a clasificar() (mismo modelo, + seleccion).
    texto, confs = ocr_pp.leer_placa(crops, m.modelo_ocr, m.classes_ocr, return_conf=True)
    etapa3.guardar_resultado(nombre, texto)
    conf_ocr = (sum(confs) / len(confs)) if confs else 0.0
    ocr_por_caracter = list(zip(texto, confs))
    print(f"  [OK] {nombre}: {len(crops)} crops -> '{texto}' (conf {conf_ocr:.2f})")
    return ResultadoFrame(
        texto=texto,
        placa=placa,
        crops=crops,
        carro_bbox=carro_bbox,
        placa_bbox=bbox,
        entrada_segmentacion=entrada_seg,
        uso_filtros=m.usar_filtros,
        uso_enderezado=m.usar_enderezado,
        placa_crop=placa_crop,
        seg_overlay=seg_overlay,
        conf_vehiculo=conf_v,
        conf_placa=conf_p,
        conf_ocr=conf_ocr,
        ocr_por_caracter=ocr_por_caracter,
    )
