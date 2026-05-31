"""
Punto inicial del pipeline EN VIVO: la camara.

Muestra el video con las dos barras y la deteccion de la placa en tiempo real.
Cuando una placa cruza la zona, corre la cadena completa sobre ese frame:

    frame -> [ETAPA 0] recorte del carro -> [ETAPA 1] placa horizontal
          -> [filtros] -> [ETAPA 2] crops por caracter -> [ETAPA 3] texto

La cadena vive en cadena.py (la MISMA que usa el batch en batch.py): main solo
decide CUANDO correrla (al cruzar la zona) y como detectar en vivo.

Ejecutar:
    python main.py                       # webcam por defecto (indice 0)
    python main.py video.mp4             # archivo grabado (desarrollo)
    python main.py http://192.168.x.x:4747/video   # celular (DroidCam/IP Webcam, demo)
    python main.py 1                     # otra webcam por indice
"""

import os
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(DIR, "camara"))
sys.path.insert(0, os.path.join(DIR, "pipeline"))

# Flag de prueba: filtros a veces empeora el OCR (ver cadena.py).
# True  -> enderezada -> filtros -> segmentacion
# False -> enderezada -> segmentacion (cruda, sin filtros)
USAR_FILTROS = False

from camara import iniciar
import cadena

if __name__ == "__main__":
    m = cadena.cargar_modelos(usar_filtros=USAR_FILTROS)
    print("Modelos cargados.")

    def al_capturar(nombre, frame):
        # Corre la cadena completa sobre el frame capturado.
        # Devuelve el texto de la placa (o None) -> la camara lo guarda en datos.json.
        return cadena.procesar_frame(nombre, frame, m)

    def detectar_en_vivo(frame):
        # Detector que alimenta las lineas EN VIVO: devuelve (carro, placa) para
        # dibujar ambas cajas y rastrear la placa (carro -> placa con zoom).
        return cadena.detectar_placa_en_vivo(frame, m)

    # fuente de video: argumento de linea de comandos (default = webcam 0)
    #   un numero  -> indice de webcam ; cualquier otra cosa -> ruta o URL
    fuente = 0
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        fuente = int(arg) if arg.isdigit() else arg

    # en vivo: carro->placa dispara el rastreo; al cruzar la zona corre el OCR
    iniciar(detector=detectar_en_vivo,
            al_capturar=al_capturar,
            fuente=fuente)
