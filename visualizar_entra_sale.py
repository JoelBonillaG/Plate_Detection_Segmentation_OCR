"""
Visualizador STANDALONE de la logica ENTRA / SALE (geometria de las lineas).

No importa nada de app/: replica a mano la MISMA matematica que usa
app/camara/lineas.py (producto cruz -> de que lado de la diagonal cae el centro)
para que veas, sin ruido, COMO se decide "entra" y "sale".

Que muestra:
    - las dos lineas inclinadas: ENTRA (naranja) y SALE (roja)
    - las 3 regiones pintadas:
          azul  = antes de ENTRA  (esperando)
          verde = dentro de la zona (rastreando)
          rojo  = ya paso SALE     (cierra -> FOTO)
    - una placa que cruza animada, con el estado en vivo y un cartel cuando
      ocurre el evento ENTRA y el evento SALE (= momento de la foto).

La frontera es la DIAGONAL COMPLETA entre sus dos puntas, no un punto ni una
vertical: por eso el cruce se detecta a cualquier altura de la recta.

Ejecutar (desde la raiz del repo):
    python visualizar_entra_sale.py                 # fondo sintetico
    python visualizar_entra_sale.py foto.jpg        # sobre tu propia imagen

Teclas:  ESPACIO = pausa/sigue   R = reiniciar   Q = salir
"""

import sys

import cv2
import numpy as np


# ── coordenadas de las lineas (MISMAS fracciones que app/camara/camara.py) ──
#   cada linea = dos puntos en fracciones [0..1] del frame -> es INCLINABLE
LINEA_ENTRA = ((0.30, 0.15), (0.20, 0.62))   # lejana
LINEA_SALE  = ((0.62, 0.28), (0.52, 0.98))   # cercana a la camara

W, H = 1280, 720

# colores BGR
C_ENTRA  = (0, 165, 255)    # naranja
C_SALE   = (0, 0, 255)      # rojo
C_DENTRO = (0, 200, 0)      # verde
C_HANDLE = (255, 0, 255)    # magenta (puntas)
C_TEXTO  = (255, 255, 255)
C_PLACA  = (0, 255, 255)    # amarillo


def a_px(linea, w, h):
    """Fracciones -> pixeles."""
    (ax, ay), (bx, by) = linea
    return (int(ax * w), int(ay * h)), (int(bx * w), int(by * h))


def signo(px, py, linea_px):
    """
    Producto cruz: de que LADO de la recta (a->b) cae el punto (px,py).
    >0 un lado, <0 el otro, 0 justo encima. Es EXACTAMENTE _signo() de lineas.py.
    Acepta px,py escalares o arrays numpy (para pintar regiones de un saque).
    """
    (ax, ay), (bx, by) = linea_px
    return (bx - ax) * (py - ay) - (by - ay) * (px - ax)


def medio(linea_px):
    (a, b) = linea_px
    return ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)


def lados(px, py, e_px, s_px):
    """
    (dentro_e, dentro_s) para el punto (px,py). Misma logica que ZonaDeteccion._dentro:
    el punto medio de UNA linea define cual es el lado 'interior' de la OTRA.
    """
    me, ms = medio(e_px), medio(s_px)
    dentro_e = signo(px, py, e_px) * signo(*ms, e_px) > 0   # mismo lado que SALE
    dentro_s = signo(px, py, s_px) * signo(*me, s_px) > 0   # mismo lado que ENTRA
    return dentro_e, dentro_s


def capa_regiones(e_px, s_px):
    """Imagen RGB con las 3 regiones pintadas (vectorizado sobre todo el frame)."""
    ys, xs = np.mgrid[0:H, 0:W]
    dentro_e, dentro_s = lados(xs, ys, e_px, s_px)
    dentro = dentro_e & dentro_s

    capa = np.zeros((H, W, 3), np.uint8)
    capa[~dentro_e] = (120, 60, 0)     # antes de ENTRA  -> azul oscuro
    capa[~dentro_s & dentro_e] = (0, 0, 120)   # ya paso SALE -> rojo oscuro
    capa[dentro] = (0, 90, 0)          # zona            -> verde oscuro
    return capa


def fondo_base(ruta=None):
    """Imagen de fondo: la del usuario, o una calle sintetica simple."""
    if ruta is not None:
        img = cv2.imread(ruta)
        if img is not None:
            return cv2.resize(img, (W, H))
        print(f"No pude abrir '{ruta}', uso fondo sintetico.")
    img = np.full((H, W, 3), 70, np.uint8)            # asfalto gris
    cv2.line(img, (0, int(H * 0.30)), (W, int(H * 0.20)), (90, 90, 90), 3)
    for i in range(-2, 12):                            # lineas de carril punteadas
        x = int(W * 0.1 * i)
        cv2.line(img, (x, H), (x + 250, int(H * 0.3)), (200, 200, 200), 2)
    return img


def dibujar_lineas(frame, e_px, s_px):
    cv2.line(frame, e_px[0], e_px[1], C_ENTRA, 3)
    cv2.line(frame, s_px[0], s_px[1], C_SALE, 3)
    for p in (e_px[0], e_px[1], s_px[0], s_px[1]):
        cv2.circle(frame, p, 8, C_HANDLE, -1)
    cv2.putText(frame, "ENTRA", (e_px[0][0] + 8, e_px[0][1]),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, C_ENTRA, 2)
    cv2.putText(frame, "SALE", (s_px[1][0] + 8, s_px[1][1] - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, C_SALE, 2)


def panel(frame, lineas_txt):
    """Cartel semitransparente arriba-izq con texto explicativo / estado."""
    y = 30
    for txt, col in lineas_txt:
        cv2.putText(frame, txt, (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4)
        cv2.putText(frame, txt, (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, col, 2)
        y += 32


def main():
    ruta = sys.argv[1] if len(sys.argv) > 1 else None
    base = fondo_base(ruta)
    e_px = a_px(LINEA_ENTRA, W, H)
    s_px = a_px(LINEA_SALE, W, H)
    regiones = capa_regiones(e_px, s_px)

    # trayectoria de la PLACA: de antes de ENTRA hasta pasar SALE
    p0 = np.array([W * 0.02, H * 0.45])
    p1 = np.array([W * 0.98, H * 0.78])

    estado = "esperando"     # esperando -> rastreando -> (cierra) -> esperando
    flash, flash_t = "", 0   # cartel de evento
    trail = []
    t = 0.0
    paso = 0.006
    pausa = False

    print("ENTRA = cruzar la diagonal naranja hacia adentro.")
    print("SALE  = cruzar la diagonal roja hacia afuera -> FOTO.\n")

    while True:
        frame = cv2.addWeighted(base, 1.0, regiones, 0.45, 0)
        dibujar_lineas(frame, e_px, s_px)

        cx, cy = (p0 + (p1 - p0) * t).astype(int)
        dentro_e, dentro_s = lados(cx, cy, e_px, s_px)
        dentro = dentro_e and dentro_s

        # --- maquina de estados (replica ZonaDeteccion.actualizar, simplificada) ---
        if estado == "esperando":
            if dentro:
                estado = "rastreando"
                flash, flash_t = "ENTRA  ->  empieza a rastrear", 45
                print(f"t={t:4.2f}  ENTRA: el centro cruzo la diagonal naranja")
        elif estado == "rastreando":
            if dentro:
                pass                              # sigue rastreando (elige mas nitido)
            elif not dentro_s:
                estado = "esperando"
                flash, flash_t = "SALE  ->  TOMA LA FOTO", 60
                print(f"t={t:4.2f}  SALE: cruzo la diagonal roja -> captura\n")
            else:
                estado = "esperando"             # salio por ENTRA (marcha atras)
                flash, flash_t = "salio por ENTRA (descarta)", 45

        # --- dibujo de la placa + rastro ---
        trail.append((cx, cy))
        trail = trail[-60:]
        for i in range(1, len(trail)):
            cv2.line(frame, trail[i - 1], trail[i], (180, 180, 180), 1)
        col_caja = C_DENTRO if dentro else C_PLACA
        cv2.rectangle(frame, (cx - 55, cy - 22), (cx + 55, cy + 22), col_caja, 2)
        cv2.putText(frame, "PCS-007", (cx - 48, cy + 7),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, col_caja, 2)
        cv2.circle(frame, (cx, cy), 5, (0, 0, 255), -1)   # el CENTRO (lo que se evalua)

        # --- textos ---
        col_estado = C_DENTRO if estado == "rastreando" else C_TEXTO
        panel(frame, [
            (f"Estado: {estado}", col_estado),
            (f"dentro_ENTRA={bool(dentro_e)}   dentro_SALE={bool(dentro_s)}", C_TEXTO),
            ("rojo=centro de la placa (eso es lo que se evalua)", (0, 0, 255)),
            ("ESPACIO=pausa  R=reiniciar  Q=salir", (200, 200, 200)),
        ])
        if flash_t > 0:
            cv2.putText(frame, flash, (W // 2 - 280, H - 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 6)
            cv2.putText(frame, flash, (W // 2 - 280, H - 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2)
            flash_t -= 1

        cv2.imshow("ENTRA / SALE - como se decide", frame)

        if not pausa:
            t += paso
            if t > 1.0:
                t = 0.0
                estado = "esperando"
                trail.clear()

        k = cv2.waitKey(25) & 0xFF
        if k == ord("q"):
            break
        if k == ord(" "):
            pausa = not pausa
        if k == ord("r"):
            t, estado, trail = 0.0, "esperando", []

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
