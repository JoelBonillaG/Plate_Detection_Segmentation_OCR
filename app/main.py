"""
Punto inicial del pipeline EN VIVO: la camara.

Muestra el video con las dos barras y la deteccion de la placa en tiempo real.
Cuando un carro con placa cruza la zona, corre la cadena completa sobre ese frame:

    frame -> [ETAPA 1] placa horizontal -> [ETAPA 2] crops por caracter
          -> [ETAPA 3 futuro] texto

Mismo modelo y mismas etapas que el batch (pipeline.py).

Ejecutar:
    python main.py
"""

import os
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(DIR, "camara"))
sys.path.insert(0, os.path.join(DIR, "pipeline"))

from camara import iniciar
import deteccion_placas as etapa1
from ocr import segmentacion as etapa2

if __name__ == "__main__":
    cfg     = etapa1.cargar_config()
    modelo  = etapa1.cargar_modelo(cfg)
    conf    = cfg.get("conf_min", 0.25)
    cfg_seg = etapa2.cargar_config()
    print("Modelo cargado.")

    def al_capturar(nombre, frame):
        # ETAPA 1: detectar + recortar + enderezar -> placa horizontal
        placa, bbox = etapa1.procesar_frame(modelo, frame, cfg, return_bbox=True)
        if placa is None:
            print(f"  [SIN PLACA] {nombre}")
            return
        # auditar: frame con bbox + placa horizontal, antes de segmentar
        etapa1.guardar_deteccion(nombre, frame, bbox, cfg)
        etapa1.guardar_enderezada(nombre, placa, cfg)
        # ETAPA 2: segmentar caracteres -> crops en ocr/segmentacion/salidas/<nombre>/
        n = etapa2.guardar_crops(nombre, placa, cfg_seg)
        print(f"  [OK] {nombre}: {n} crops")
        # ETAPA 3 (futuro): texto = ocr.leer_placa([c for _, c in etapa2.segmentar(placa, cfg_seg)])
        #                   ocr.guardar_resultado(nombre, {"texto": texto})

    # en vivo: la camara solo dispara captura cuando una placa cruza la zona
    iniciar(detector=lambda frame: etapa1.detectar(modelo, frame, conf),
            al_capturar=al_capturar)
