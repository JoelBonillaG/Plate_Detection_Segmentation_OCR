"""
POST-PROCESO de la segmentacion: filtro GEOMETRICO de las cajas de caracteres.

Por que existe: el U-Net deja a veces cajas que NO son caracteres -> el guion '-'
entre letras y digitos, un tornillo/borde de la placa, o restos. Esas inflan el
resultado del OCR. Como el U-Net da una mascara por PIXEL (no una confianza por
caja), aqui NO se filtra por confianza: se filtra por FORMA, que es lo que
distingue un caracter de un guion o un tornillo.

Reglas (todas RELATIVAS a la propia placa, no umbrales fijos en pixeles -> sirven
igual con placa cercana grande o lejana chica):

    - ALTURA: se descarta toda caja con alto < alto_min_rel * (mediana de alturas).
      Los caracteres reales tienen altura parecida; el guion y los tornillos son
      mas bajos -> caen.
    - ASPECTO (ancho/alto): se descarta toda caja con ancho/alto > aspecto_max.
      Un caracter es mas alto que ancho; el guion es ancho y chato -> cae.

Este modulo NO modifica segmentacion/__init__.py. Se usa DESPUES de segmentar:

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
    minimo_para_filtrar : si hay menos cajas que esto, NO se filtra (placa parcial:
        mejor no arriesgarse a borrar un caracter real).

    Devuelve (cajas_filtradas, crops_filtrados|None) en el mismo orden. Si el filtro
    dejaria 0 cajas, devuelve las originales (mejor ruidoso que vacio).
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
        if alto < umbral_alto:               # muy baja -> guion / tornillo
            continue
        if ancho / alto > aspecto_max:       # ancha y chata -> ruido
            continue
        elegidas.append(i)

    if not elegidas:                          # seguridad: no dejar la placa vacia
        return cajas, crops

    cajas_f = [cajas[i] for i in elegidas]
    crops_f = [crops[i] for i in elegidas] if crops is not None else None
    return cajas_f, crops_f


__all__ = ["filtrar_ruido"]
