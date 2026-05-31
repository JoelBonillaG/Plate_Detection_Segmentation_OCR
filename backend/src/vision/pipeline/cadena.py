"""
Cadena-por-frame compartida (modo BATCH y modo EN VIVO usan ESTO).

Aqui vive la logica de procesar UN frame de punta a punta:
    frame -> [ETAPA 0] recorte carro -> [ETAPA 1] placa horizontal
          -> [filtros opcional] -> [ETAPA 2] crops por caracter -> [ETAPA 3] texto

NO sabe de donde sale el frame (carpeta, camara o video): eso lo deciden
batch.py (recorre carpeta) y main.py (dispara al cruzar la zona). Asi la
cadena vive en un solo lugar y los dos modos se actualizan juntos.
"""

import os
import sys
from dataclasses import dataclass

# permitir importar los paquetes de las etapas (mismo dir que este archivo)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deteccion_carros as etapa0
import deteccion_placas as etapa1
import filtros as etapa_filtros
import segmentacion as etapa2
import ocr as etapa3


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
    modelo_carros: object       # ETAPA 0 (carros); None si no esta entrenado
    usar_filtros: bool


def cargar_modelos(usar_filtros=False):
    """Carga los 5 modelos y sus configs una sola vez. Devuelve un Modelos."""
    cfg         = etapa1.cargar_config()
    modelo      = etapa1.cargar_modelo(cfg)
    conf        = cfg.get("conf_min", 0.25)
    cfg_filtros = etapa_filtros.cargar_config()
    modelo_seg  = etapa2.cargar_modelo()
    modelo_ocr, classes_ocr = etapa3.cargar_modelo()

    # ETAPA 0: detector de carros. Si no esta entrenado -> fallback: placa
    # sobre el frame completo (se descartan menos falsos positivos, pero corre).
    cfg_carros = etapa0.cargar_config()
    try:
        modelo_carros = etapa0.cargar_modelo(cfg_carros)
    except FileNotFoundError:
        modelo_carros = None
        print("[ETAPA 0] modelo de carros no entrenado -> fallback: placa sobre frame completo.")
        print("          entrena con: python deteccion_carros/redes/entrenamiento.py")

    return Modelos(cfg=cfg, modelo=modelo, conf=conf, cfg_filtros=cfg_filtros,
                   modelo_seg=modelo_seg, modelo_ocr=modelo_ocr, classes_ocr=classes_ocr,
                   cfg_carros=cfg_carros, modelo_carros=modelo_carros,
                   usar_filtros=usar_filtros)


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
    # sin modelo de carros -> fallback: no hay caja de carro, placa sobre el frame
    if m.modelo_carros is None:
        return None, etapa1.detectar(m.modelo, frame, m.conf)

    carro = etapa0.detectar_carro(m.modelo_carros, frame, m.cfg_carros)
    if carro is None:
        return None, None   # no hay carro -> no rastrear nada

    # recorte del carro (con margen) + offset para volver al frame
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
    placa: object
    crops: list
    carro_bbox: object = None
    placa_bbox: object = None
    entrada_segmentacion: object = None
    uso_filtros: bool = False


def procesar_frame_detallado(nombre, frame, m):
    """
    Igual que procesar_frame(), pero devuelve placa, crops y bboxes.
    Lo usa el backend para registrar evento, vision y difuso sin duplicar etapas.
    """
    # ETAPA 0: detectar carro -> recorte (en memoria). Sin carro, no hay placa.
    carro_bbox = None
    if m.modelo_carros is not None:
        carro_bbox = etapa0.detectar_carro(m.modelo_carros, frame, m.cfg_carros)
        if carro_bbox is None:
            print(f"  [SIN CARRO] {nombre}")
            return None
        etapa0.guardar_deteccion(nombre, frame, carro_bbox, m.cfg_carros)
        base = etapa0.recortar(frame, carro_bbox, m.cfg_carros.get("margen", 0.08))
    else:
        base = frame

    # ETAPA 1: detectar + recortar + enderezar -> placa horizontal.
    placa, bbox = etapa1.procesar_frame(m.modelo, base, m.cfg, return_bbox=True)
    if placa is None:
        print(f"  [SIN PLACA] {nombre}")
        return None
    etapa1.guardar_deteccion(nombre, base, bbox, m.cfg)
    etapa1.guardar_enderezada(nombre, placa, m.cfg)

    # ETAPA intermedia: filtros (segun flag usar_filtros).
    if m.usar_filtros:
        entrada_seg = etapa_filtros.filtrar(placa, m.cfg_filtros)
        etapa_filtros.guardar(nombre, entrada_seg, m.cfg_filtros)
    else:
        entrada_seg = placa

    # ETAPA 2: segmentar caracteres -> crops.
    _, crops = etapa2.segmentar(entrada_seg, m.modelo_seg)
    etapa2.guardar(nombre, crops)

    # ETAPA 3: OCR -> texto de la placa.
    texto = etapa3.clasificar(crops, m.modelo_ocr, m.classes_ocr)
    etapa3.guardar_resultado(nombre, texto)
    print(f"  [OK] {nombre}: {len(crops)} crops -> '{texto}'")
    return ResultadoFrame(
        texto=texto,
        placa=placa,
        crops=crops,
        carro_bbox=carro_bbox,
        placa_bbox=bbox,
        entrada_segmentacion=entrada_seg,
        uso_filtros=m.usar_filtros,
    )
