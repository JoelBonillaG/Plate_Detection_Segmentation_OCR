"""
Borra las carpetas de AUDITORIA del pipeline (las salidas regenerables de cada
etapa). No toca modelos, configs ni codigo: solo lo que se vuelve a crear al
correr batch.py / main.py.

Carpetas que limpia (relativas a esta carpeta, app/pipeline/):
    deteccion_carros/detecciones      (ETAPA 0: frames anotados + recortes)
    deteccion_placas/detecciones      (ETAPA 1: frames con bbox de placa)
    deteccion_placas/enderezadas      (ETAPA 1: placas horizontales)
    filtros/filtradas                 (ETAPA intermedia: placas filtradas)
    ocr/salidas                       (ETAPA 3: <nombre>.txt con el texto)
    segmentacion/segmentadas          (ETAPA 2: crops por caracter)

Deja cada carpeta VACIA (la borra y la vuelve a crear), asi las etapas escriben
sin problema en la proxima corrida.

Ejecutar:
    python limpiar_auditoria.py          # limpia todo
    python limpiar_auditoria.py --ver    # solo muestra que borraria (no borra)
"""

import os
import sys
import shutil

AQUI = os.path.dirname(os.path.abspath(__file__))

CARPETAS = [
    os.path.join("deteccion_carros", "detecciones"),
    os.path.join("deteccion_placas", "detecciones"),
    os.path.join("deteccion_placas", "enderezadas"),
    os.path.join("filtros", "filtradas"),
    os.path.join("ocr", "salidas"),
    os.path.join("segmentacion", "segmentadas"),
]


def _contar(ruta):
    """Cuantos archivos (recursivo) hay dentro de una carpeta."""
    return sum(len(files) for _, _, files in os.walk(ruta))


def main():
    solo_ver = "--ver" in sys.argv

    total = 0
    for rel in CARPETAS:
        ruta = os.path.join(AQUI, rel)
        if not os.path.isdir(ruta):
            print(f"  [no existe] {rel}")
            continue

        n = _contar(ruta)
        total += n
        if solo_ver:
            print(f"  [borraria] {rel}  ({n} archivos)")
            continue

        shutil.rmtree(ruta)        # borra carpeta + contenido
        os.makedirs(ruta)          # la deja vacia, lista para la proxima corrida
        print(f"  [limpia]   {rel}  ({n} archivos borrados)")

    accion = "se borrarian" if solo_ver else "borrados"
    print(f"\nTotal {accion}: {total} archivos.")


if __name__ == "__main__":
    main()
