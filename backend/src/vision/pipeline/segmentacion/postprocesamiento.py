"""
POST-PROCESO de la segmentacion: filtro GEOMETRICO de las cajas de caracteres.

El U-Net puede producir cajas sobre regiones que no corresponden a caracteres,
como guiones, tornillos, bordes o restos visuales. Como la salida es una mascara
por pixel, el filtrado se realiza por geometria y no por confianza de caja.

Reglas (todas RELATIVAS a la propia placa, no umbrales fijos en pixeles -> sirven
igual con placa cercana grande o lejana chica):

    - ALTURA: se descarta toda caja con alto < alto_min_rel * (mediana de alturas).
      Los caracteres reales tienen altura parecida; regiones pequenas quedan
      por debajo de este umbral.
    - ASPECTO (ancho/alto): se descarta toda caja con ancho/alto > aspecto_max.
      Un caracter suele ser mas alto que ancho; regiones muy anchas se descartan.

Este modulo se aplica despues de segmentar:

    from segmentacion import postprocesamiento as pp
    cajas, crops = pp.filtrar_ruido(cajas, crops)
"""


def filtrar_ruido(cajas, crops=None, alto_min_rel=0.55, aspecto_max=1.4,
                  minimo_para_filtrar=4):
    """
    Filtra cajas que no parecen caracteres por geometria.

    cajas : lista [(x1, y1, x2, y2), ...] (la salida de segmentar()).
    crops : lista paralela opcional; se filtra en el MISMO orden.
    alto_min_rel : fraccion de la mediana de altura por debajo de la cual se descarta.
    aspecto_max  : ancho/alto maximo permitido (mas que esto = ancho y chato = ruido).
    minimo_para_filtrar : si hay menos cajas que esto, no se filtra para evitar
        eliminar caracteres reales en placas parciales.

    Devuelve (cajas_filtradas, crops_filtrados|None) en el mismo orden. Si el filtro
    dejaria 0 cajas, devuelve las originales para conservar una salida util.
    """
    if not cajas or len(cajas) < minimo_para_filtrar:
        return cajas, crops

    alturas = sorted(max(1, y2 - y1) for (x1, y1, x2, y2) in cajas)
    mediana = alturas[len(alturas) // 2]
    umbral_alto = alto_min_rel * mediana

    elegidas = []
    for i, (x1, y1, x2, y2) in enumerate(cajas):
        alto = max(1, y2 - y1)
        ancho = max(1, x2 - x1)
        if alto < umbral_alto:               # region demasiado baja
            continue
        if ancho / alto > aspecto_max:       # region demasiado ancha
            continue
        elegidas.append(i)

    if not elegidas:                          # conserva la salida original
        return cajas, crops

    cajas_f = [cajas[i] for i in elegidas]
    crops_f = [crops[i] for i in elegidas] if crops is not None else None
    return cajas_f, crops_f


__all__ = ["filtrar_ruido"]
