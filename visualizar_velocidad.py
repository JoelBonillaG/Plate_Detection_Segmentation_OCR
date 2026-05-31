"""
Visualizador STANDALONE de POR QUE salen velocidades absurdas (400 km/h) y
COMO la "tolerancia a parpadeos" lo arregla.

No importa nada de app/: es una simulacion para entender el problema.

Idea: un carro va a una velocidad REAL CONSTANTE (vos la elegis con el slider).
El detector:
   - esta CIEGO si la placa es mas chica que lock_px (lejos = chica)
   - aun viendola, PARPADEA: a veces pierde la deteccion un frame (parpadeo %)

El cronometro MEDIDO arranca cuando el detector VE la placa dentro de la zona.
PROBLEMA (como en lineas.py hoy): cada frame sin deteccion -> RESET -> borra el
t_entra temprano. Si reaparece tarde (cerca de SALE), el tiempo medido es chico
-> velocidad inflada.

ARREGLO (tolerancia): aguantar N frames seguidos sin deteccion antes de soltar
el rastreo. Asi un parpadeo no borra el t_entra temprano -> tiempo medido ~ real.

Sliders:
    vel_real    = velocidad VERDADERA del carro (km/h). La 'verdad'.
    lock_px     = ancho a partir del cual el detector VE la placa (lejos no ve).
    parpadeo_%  = probabilidad de perder la deteccion en un frame (ruido de YOLO).
    tolerancia  = frames seguidos sin deteccion que aguanta SIN resetear.
                  0 = comportamiento actual (resetea al primer parpadeo).

Probalo:  poné parpadeo_% alto y tolerancia=0  -> ves resets y velocidad inflada.
          subí tolerancia                       -> los resets desaparecen y la
                                                   velocidad medida se acerca a la real.

Ejecutar (desde la raiz del repo):
    python visualizar_velocidad.py

Teclas:  ESPACIO = pausa/sigue   R = reiniciar el cruce   Q = salir
"""

import random

import cv2
import numpy as np


W, H = 1200, 640
FPS = 30.0

# geometria del esquema (vista lateral simple de la calle)
X0, XN = 60, 1140          # donde aparece / desaparece la placa
X_ENTRA, X_SALE = 320, 880  # las dos lineas
DIST_M = 5.0               # metros REALES entre ENTRA y SALE
PX_POR_M = (X_SALE - X_ENTRA) / DIST_M

ANCHO_MIN, ANCHO_MAX = 8, 130   # la placa crece al acercarse (perspectiva)

VENT = "Velocidad: parpadeo y tolerancia"


def ancho_en(x):
    """Ancho (px) de la placa segun su posicion: lejos=chica, cerca=grande."""
    f = (x - X0) / (XN - X0)
    return ANCHO_MIN + (ANCHO_MAX - ANCHO_MIN) * f


def texto(frame, txt, org, col=(255, 255, 255), esc=0.7, grosor=2):
    cv2.putText(frame, txt, org, cv2.FONT_HERSHEY_SIMPLEX, esc, (0, 0, 0), grosor + 3)
    cv2.putText(frame, txt, org, cv2.FONT_HERSHEY_SIMPLEX, esc, col, grosor)


def nuevo_cruce():
    """Estado inicial de un cruce."""
    return {
        "x": float(X0), "frame_n": 0,
        "real_entra": None, "real_sale": None,
        "med_entra": None, "med_sale": None,
        "estado": "esperando", "perdidos": 0, "resets": 0,
        "resultado": None,
    }


def main():
    cv2.namedWindow(VENT, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(VENT, W, H)
    cv2.createTrackbar("vel_real",   VENT, 30, 120, lambda v: None)  # km/h (verdad)
    cv2.createTrackbar("lock_px",    VENT, 70, 130, lambda v: None)  # ancho de deteccion
    cv2.createTrackbar("parpadeo_%", VENT, 25, 60,  lambda v: None)  # ruido del detector
    cv2.createTrackbar("tolerancia", VENT, 0, 15,   lambda v: None)  # frames que aguanta

    s = nuevo_cruce()
    pausa = False

    while True:
        vel_real  = max(cv2.getTrackbarPos("vel_real", VENT), 1)
        lock_px   = cv2.getTrackbarPos("lock_px", VENT)
        parpadeo  = cv2.getTrackbarPos("parpadeo_%", VENT)
        tolerancia = cv2.getTrackbarPos("tolerancia", VENT)

        v_px = (vel_real / 3.6) * PX_POR_M / FPS   # px por frame (velocidad real)

        if not pausa:
            s["x"] += v_px
            s["frame_n"] += 1

        cx = s["x"]
        w_placa = ancho_en(cx)
        en_zona = X_ENTRA <= cx <= X_SALE

        # ── detector: ciego si chica + parpadeo aleatorio ──
        detectable = w_placa >= lock_px
        parpadea = (random.random() * 100) < parpadeo
        ve = detectable and not parpadea

        # ── marcas de tiempo REALES (fisicas) ──
        if s["real_entra"] is None and cx >= X_ENTRA:
            s["real_entra"] = s["frame_n"]
        if s["real_sale"] is None and cx >= X_SALE:
            s["real_sale"] = s["frame_n"]

        # ── maquina de estados MEDIDA (replica lineas.py + tolerancia) ──
        if not pausa and s["resultado"] is None:
            if not ve:
                if s["estado"] == "rastreando":
                    s["perdidos"] += 1
                    if s["perdidos"] > tolerancia:     # se acabo la paciencia -> reset
                        s["estado"] = "esperando"
                        s["med_entra"] = None
                        s["perdidos"] = 0
                        s["resets"] += 1
            else:
                s["perdidos"] = 0
                if s["estado"] == "esperando" and en_zona:
                    s["estado"] = "rastreando"
                    s["med_entra"] = s["frame_n"]
                elif s["estado"] == "rastreando" and cx >= X_SALE and s["med_sale"] is None:
                    s["med_sale"] = s["frame_n"]

        # ── congelar resultado cuando el carro cruza SALE (fisico) ──
        if s["resultado"] is None and s["real_sale"] is not None:
            t_real = (s["real_sale"] - s["real_entra"]) / FPS
            v_realc = DIST_M / t_real * 3.6 if t_real > 0 else 0
            if s["med_entra"] is not None and s["med_sale"] is not None and s["med_sale"] > s["med_entra"]:
                t_med = (s["med_sale"] - s["med_entra"]) / FPS
                v_med = DIST_M / t_med * 3.6
            else:
                t_med, v_med = None, None
            s["resultado"] = (t_real, v_realc, t_med, v_med)

        # ───────────── dibujo ─────────────
        frame = np.full((H, W, 3), 60, np.uint8)
        cv2.rectangle(frame, (0, 250), (W, 440), (80, 80, 80), -1)          # asfalto
        cv2.rectangle(frame, (X_ENTRA, 250), (X_SALE, 440), (0, 90, 0), -1)  # zona
        cv2.line(frame, (X_ENTRA, 230), (X_ENTRA, 460), (0, 165, 255), 3)
        cv2.line(frame, (X_SALE, 230), (X_SALE, 460), (0, 0, 255), 3)
        texto(frame, "ENTRA", (X_ENTRA - 30, 222), (0, 165, 255))
        texto(frame, "SALE", (X_SALE - 20, 222), (0, 0, 255))
        texto(frame, f"{DIST_M:.0f} m reales", ((X_ENTRA + X_SALE) // 2 - 70, 480),
              (200, 200, 200), 0.7)

        # franja donde el detector empieza a poder ver (por tamano)
        x_ve = X0 + (XN - X0) * ((lock_px - ANCHO_MIN) / (ANCHO_MAX - ANCHO_MIN))
        x_ve = int(np.clip(x_ve, X0, XN))
        cv2.line(frame, (x_ve, 250), (x_ve, 440), (255, 255, 0), 1)
        texto(frame, "ve desde aqui (por tamano) ->", (x_ve - 300, 270), (255, 255, 0), 0.5, 1)

        # la placa: verde=ve, gris=muy chica, rojo=parpadeo (la perdio este frame)
        if ve:
            col = (0, 255, 0); etq = "VE"
        elif not detectable:
            col = (130, 130, 130); etq = "ciego (chica)"
        else:
            col = (0, 0, 255); etq = "PARPADEO"
        wp = int(w_placa)
        cv2.rectangle(frame, (int(cx) - wp // 2, 330), (int(cx) + wp // 2, 370), col, -1)
        texto(frame, etq, (int(cx) - 30, 322), col, 0.5, 1)

        # panel arriba
        texto(frame, "Mismo carro, velocidad REAL constante. Mira la MEDIDA.", (20, 30))
        texto(frame, f"vel_real (verdad): {vel_real} km/h", (20, 66), (0, 255, 0), 0.7)
        texto(frame, f"estado: {s['estado']}   perdidos: {s['perdidos']}/{tolerancia}   RESETS: {s['resets']}",
              (20, 98), (0, 200, 255) if s["resets"] else (200, 200, 200), 0.6, 1)
        texto(frame, f"ancho placa: {int(w_placa)}px  (ve desde {lock_px}px)  parpadeo {parpadeo}%",
              (20, 126), (200, 200, 200), 0.55, 1)

        # resultado abajo
        if s["resultado"]:
            t_real, v_realc, t_med, v_med = s["resultado"]
            texto(frame, f"tiempo REAL : {t_real:.2f}s  ->  {v_realc:.0f} km/h (correcto)",
                  (20, 520), (0, 255, 0), 0.65)
            if t_med is None:
                texto(frame, "tiempo MEDIDO: ---  ->  CAPTURA PERDIDA (reset cerca de SALE)",
                      (20, 555), (0, 200, 255), 0.65)
            else:
                ok = abs(v_med - v_realc) <= v_realc * 0.15
                col_m = (0, 255, 0) if ok else (0, 0, 255)
                nota = "correcto :)" if ok else "INFLADO"
                texto(frame, f"tiempo MEDIDO: {t_med:.2f}s  ->  {v_med:.0f} km/h  ({nota})",
                      (20, 555), col_m, 0.65)
            texto(frame, "R = otro cruce   ESPACIO = pausa   Q = salir", (20, 590), (180, 180, 180), 0.55, 1)
        else:
            texto(frame, "...cruzando...", (20, 555), (200, 200, 200), 0.65)

        cv2.imshow(VENT, frame)

        if cx > XN + 60:               # salio de pantalla -> reinicia solo
            cv2.waitKey(900)
            s = nuevo_cruce()

        k = cv2.waitKey(int(1000 / FPS)) & 0xFF
        if k == ord("q"):
            break
        if k == ord(" "):
            pausa = not pausa
        if k == ord("r"):
            s = nuevo_cruce()

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
