"""
Orquestador del pipeline (modo BATCH).

Cadena completa por imagen:
    foto cruda  ->  [ETAPA 0: deteccion_carros]   SOLO auditoria (NO conectada)
                ->  [ETAPA 1: deteccion_placas]   placa horizontal (BGR)
                ->  [ETAPA intermedia: filtros]   placa gris limpia y agrandada
                ->  [ETAPA 2: segmentacion U-Net] crops por caracter
                ->  [ETAPA 3: ocr CNN]            texto -> ocr/salidas/<nombre>.txt

Lee las fotos crudas de camara/capturas/, deja los crops en
segmentacion/segmentadas/<nombre>/ y el texto en ocr/salidas/<nombre>.txt.
La etapa 0 (carros) corre aparte: guarda evidencia y no alimenta a placas.
"""

import os
import sys
import glob

import cv2

# permitir importar los paquetes de las etapas
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deteccion_carros as etapa0
import deteccion_placas as etapa1
import filtros as etapa_filtros
import segmentacion as etapa2
import ocr as etapa3

AQUI   = os.path.dirname(os.path.abspath(__file__))
APP    = os.path.dirname(AQUI)
IN_DIR = os.path.join(APP, "camara", "capturas")


def fuente_de_frames():
    """Genera (nombre, frame) leyendo las fotos crudas de camara/capturas/."""
    exts = (".jpg", ".jpeg", ".png")
    for ruta in sorted(glob.glob(os.path.join(IN_DIR, "*"))):
        if ruta.lower().endswith(exts):
            frame = cv2.imread(ruta)
            if frame is not None:
                yield os.path.splitext(os.path.basename(ruta))[0], frame


def main():
    cfg         = etapa1.cargar_config()
    modelo      = etapa1.cargar_modelo(cfg)
    cfg_filtros = etapa_filtros.cargar_config()
    modelo_seg  = etapa2.cargar_modelo()
    modelo_ocr, classes_ocr = etapa3.cargar_modelo()

    # ── ETAPA 0: deteccion de carros (CONECTADA: el recorte alimenta a placas) ──
    # si el modelo de carros no esta entrenado -> fallback: placas sobre el frame completo.
    cfg_carros = etapa0.cargar_config()
    try:
        modelo_carros = etapa0.cargar_modelo(cfg_carros)
    except FileNotFoundError:
        modelo_carros = None
        print("[ETAPA 0] modelo de carros no entrenado -> fallback: placa sobre frame completo.")
        print("          entrena con: python deteccion_carros/redes/entrenamiento.py")

    ok = 0
    for nombre, frame in fuente_de_frames():
        # ── ETAPA 0: detectar carro -> recorte (en memoria) ──
        # sin carro no hay placa que buscar (asi se descartan falsos positivos
        # tipo cuadros/carteles que no estan dentro de un vehiculo).
        if modelo_carros is not None:
            carro = etapa0.detectar_carro(modelo_carros, frame, cfg_carros)
            if carro is None:
                print(f"  [SIN CARRO] {nombre}")
                continue
            etapa0.guardar_deteccion(nombre, frame, carro, cfg_carros)   # auditar carro
            base = etapa0.recortar(frame, carro, cfg_carros.get("margen", 0.08))
        else:
            base = frame   # fallback sin detector de carros

        # ── ETAPA 1: deteccion + enderezado (SOBRE el recorte del carro) ──
        placa, bbox = etapa1.procesar_frame(modelo, base, cfg, return_bbox=True)
        if placa is None:
            print(f"  [SIN PLACA] {nombre}")
            continue
        # auditar: recorte con bbox de placa + placa horizontal, antes de segmentar
        etapa1.guardar_deteccion(nombre, base, bbox, cfg)
        etapa1.guardar_enderezada(nombre, placa, cfg)

        # ── ETAPA intermedia: filtros (limpieza + agrandado) -> filtradas/ ──
        placa_filtrada = etapa_filtros.filtrar(placa, cfg_filtros)
        etapa_filtros.guardar(nombre, placa_filtrada, cfg_filtros)

        # ── ETAPA 2: segmentacion U-Net (sobre la placa ya filtrada) -> crops ──
        _, crops = etapa2.segmentar(placa_filtrada, modelo_seg)
        etapa2.guardar(nombre, crops)

        # ── ETAPA 3: OCR (clasificador CNN) -> texto de la placa ──
        texto = etapa3.clasificar(crops, modelo_ocr, classes_ocr)
        etapa3.guardar_resultado(nombre, texto)

        ok += 1
        print(f"  [OK] {nombre}: {len(crops)} crops -> '{texto}'")

    print(f"\nProcesadas con placa: {ok}")
    print(f"Crops en  : {os.path.join(AQUI, 'segmentacion', 'segmentadas')}")
    print(f"Textos en : {os.path.join(AQUI, 'ocr', 'salidas')}")


if __name__ == "__main__":
    main()
