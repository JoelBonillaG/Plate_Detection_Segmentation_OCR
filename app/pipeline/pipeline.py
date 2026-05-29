"""
Orquestador del pipeline (modo BATCH).

Cadena completa por imagen:
    foto cruda  ->  [ETAPA 1: deteccion_placas]   placa horizontal (BGR)
                ->  [ETAPA intermedia: filtros]   placa gris limpia y agrandada
                ->  [ETAPA 2: segmentacion U-Net] crops por caracter
                ->  [ETAPA 3: ocr (pendiente)]    texto -> ocr/salidas/<nombre>.txt

Lee las fotos crudas de camara/capturas/ y deja los crops en
segmentacion/segmentadas/<nombre>/. El OCR aun no esta conectado.
"""

import os
import sys
import glob

import cv2

# permitir importar los paquetes de las etapas
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deteccion_placas as etapa1
import filtros as etapa_filtros
import segmentacion as etapa2

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

    ok = 0
    for nombre, frame in fuente_de_frames():
        # ── ETAPA 1: deteccion + enderezado ──
        placa, bbox = etapa1.procesar_frame(modelo, frame, cfg, return_bbox=True)
        if placa is None:
            print(f"  [SIN PLACA] {nombre}")
            continue
        # auditar: frame con bbox + placa horizontal, antes de segmentar
        etapa1.guardar_deteccion(nombre, frame, bbox, cfg)
        etapa1.guardar_enderezada(nombre, placa, cfg)

        # ── ETAPA intermedia: filtros (limpieza + agrandado) -> filtradas/ ──
        placa_filtrada = etapa_filtros.filtrar(placa, cfg_filtros)
        etapa_filtros.guardar(nombre, placa_filtrada, cfg_filtros)

        # ── ETAPA 2: segmentacion U-Net (sobre la placa ya filtrada) -> crops ──
        _, crops = etapa2.segmentar(placa_filtrada, modelo_seg)
        etapa2.guardar(nombre, crops)

        # ── ETAPA 3 (pendiente): OCR (clasificador CNN) -> texto ──
        # modelo OCR aun sin conectar (mismatch de version Keras; ver ocr/__init__.py)
        # texto = etapa3.clasificar(crops, modelo_ocr, classes_ocr)
        # etapa3.guardar_resultado(nombre, texto)

        ok += 1
        print(f"  [OK] {nombre}: {len(crops)} crops")

    print(f"\nProcesadas con placa: {ok}")
    print(f"Crops en: {os.path.join(AQUI, 'segmentacion', 'segmentadas')}")


if __name__ == "__main__":
    main()
