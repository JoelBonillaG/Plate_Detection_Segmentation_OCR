"""
Punto inicial del pipeline EN VIVO: la camara.

Muestra el video con las dos barras y la deteccion de la placa en tiempo real.
Cuando una placa cruza la zona, corre la cadena completa sobre ese frame:

    frame -> [ETAPA 0] recorte del carro -> [ETAPA 1] placa horizontal
          -> [filtros] -> [ETAPA 2] crops por caracter -> [ETAPA 3] texto

Mismos modelos y mismas etapas que el batch (pipeline.py).

Ejecutar:
    python main.py
"""

import os
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(DIR, "camara"))
sys.path.insert(0, os.path.join(DIR, "pipeline"))

# Flag de prueba: filtros a veces empeora el OCR (ver pipeline.py).
# True  -> enderezada -> filtros -> segmentacion
# False -> enderezada -> segmentacion (cruda, sin filtros)
USAR_FILTROS = False

from camara import iniciar
import deteccion_carros as etapa0
import deteccion_placas as etapa1
import filtros as etapa_filtros
import segmentacion as etapa2
import ocr as etapa3

if __name__ == "__main__":
    cfg         = etapa1.cargar_config()
    modelo      = etapa1.cargar_modelo(cfg)
    conf        = cfg.get("conf_min", 0.25)
    cfg_filtros = etapa_filtros.cargar_config()
    modelo_seg  = etapa2.cargar_modelo()
    modelo_ocr, classes_ocr = etapa3.cargar_modelo()

    # ETAPA 0: detector de carros (recorta el carro antes de buscar la placa)
    cfg_carros = etapa0.cargar_config()
    try:
        modelo_carros = etapa0.cargar_modelo(cfg_carros)
    except FileNotFoundError:
        modelo_carros = None
        print("[ETAPA 0] modelo de carros no entrenado -> fallback: placa sobre frame completo.")
    print("Modelos cargados.")

    def al_capturar(nombre, frame):
        # ETAPA 0: detectar carro -> recorte (en memoria). Sin carro, no hay placa.
        if modelo_carros is not None:
            carro = etapa0.detectar_carro(modelo_carros, frame, cfg_carros)
            if carro is None:
                print(f"  [SIN CARRO] {nombre}")
                return
            etapa0.guardar_deteccion(nombre, frame, carro, cfg_carros)   # auditar carro
            base = etapa0.recortar(frame, carro, cfg_carros.get("margen", 0.08))
        else:
            base = frame   # fallback sin detector de carros

        # ETAPA 1: detectar + recortar + enderezar -> placa horizontal (SOBRE el recorte)
        placa, bbox = etapa1.procesar_frame(modelo, base, cfg, return_bbox=True)
        if placa is None:
            print(f"  [SIN PLACA] {nombre}")
            return
        # auditar: recorte con bbox + placa horizontal, antes de segmentar
        etapa1.guardar_deteccion(nombre, base, bbox, cfg)
        etapa1.guardar_enderezada(nombre, placa, cfg)
        # ETAPA intermedia: filtros (segun flag USAR_FILTROS)
        if USAR_FILTROS:
            entrada_seg = etapa_filtros.filtrar(placa, cfg_filtros)
            etapa_filtros.guardar(nombre, entrada_seg, cfg_filtros)
        else:
            entrada_seg = placa   # enderezada cruda, sin filtros
        # ETAPA 2: segmentar caracteres -> crops
        _, crops = etapa2.segmentar(entrada_seg, modelo_seg)
        etapa2.guardar(nombre, crops)
        # ETAPA 3: OCR -> texto de la placa
        texto = etapa3.clasificar(crops, modelo_ocr, classes_ocr)
        etapa3.guardar_resultado(nombre, texto)
        print(f"  [OK] {nombre}: {len(crops)} crops -> '{texto}'")

    # en vivo: la camara solo dispara captura cuando una placa cruza la zona
    iniciar(detector=lambda frame: etapa1.detectar(modelo, frame, conf),
            al_capturar=al_capturar)
