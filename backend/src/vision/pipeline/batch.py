"""
Orquestador del pipeline (modo BATCH).

Recorre las fotos crudas de camara/capturas/ y corre sobre cada una la cadena
completa (la MISMA que usa main.py en vivo, definida en cadena.py):

    foto cruda  ->  [ETAPA 0: deteccion_carros]   recorte del carro
                ->  [ETAPA 1: deteccion_placas]   placa horizontal (BGR)
                ->  [ETAPA intermedia: filtros]   placa gris limpia y agrandada
                ->  [ETAPA 2: segmentacion U-Net] crops por caracter
                ->  [ETAPA 3: ocr CNN]            texto -> ocr/salidas/<nombre>.txt

Deja los crops en segmentacion/segmentadas/<nombre>/ y el texto en
ocr/salidas/<nombre>.txt. La unica diferencia con main.py es la FUENTE de los
frames (aqui carpeta; alli camara) y el disparo (aqui loop; alli cruce de zona).

Ejecutar:
    python batch.py     # procesa todas las fotos de camara/capturas/
"""

import os
import sys
import glob

import cv2

# permitir importar la cadena compartida y los paquetes de las etapas
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cadena

AQUI   = os.path.dirname(os.path.abspath(__file__))
APP    = os.path.dirname(AQUI)
IN_DIR = os.path.join(APP, "camara", "capturas")

# Flag de prueba: la etapa de filtros (limpieza + agrandado) a veces empeora el
# OCR (aleja la imagen de la distribucion con que entrenaron U-Net/CNN).
# True  -> enderezada -> filtros -> segmentacion
# False -> enderezada -> segmentacion (cruda, sin filtros)
USAR_FILTROS = True


def fuente_de_frames():
    """Genera (nombre, frame) leyendo las fotos crudas de camara/capturas/."""
    exts = (".jpg", ".jpeg", ".png")
    for ruta in sorted(glob.glob(os.path.join(IN_DIR, "*"))):
        if ruta.lower().endswith(exts):
            frame = cv2.imread(ruta)
            if frame is not None:
                yield os.path.splitext(os.path.basename(ruta))[0], frame


def main():
    m = cadena.cargar_modelos(usar_filtros=USAR_FILTROS)

    ok = 0
    for nombre, frame in fuente_de_frames():
        if cadena.procesar_frame(nombre, frame, m) is not None:
            ok += 1

    print(f"\nProcesadas con placa: {ok}")
    print(f"Crops en  : {os.path.join(AQUI, 'segmentacion', 'segmentadas')}")
    print(f"Textos en : {os.path.join(AQUI, 'clasificacion_caracteres', 'salidas')}")


if __name__ == "__main__":
    main()
