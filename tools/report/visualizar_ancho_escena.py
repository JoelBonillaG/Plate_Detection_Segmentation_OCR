"""
Visualiza por que el "ancho de escena" (W) cambia con la distancia.

La camara ve un CONO que se abre. A mayor distancia, el cono abarca mas
metros de lado a lado (W mas grande), y como los 1920 px se reparten sobre
mas metros, la placa recibe MENOS pixeles.

    W(d) = 2 * d * tan(FOV_horizontal / 2)
    densidad rho = Nh / W
    ancho de placa w_p = rho * L_p   (L_p = 0,40 m)

Genera un dibujo (vista desde arriba) del cono con W marcado a varias
distancias, mas una tabla por consola.

Uso:
    python visualizar_ancho_escena.py [--fov 70] [--out salida.png]
"""

import argparse
import math
from pathlib import Path

import matplotlib.pyplot as plt

NH = 1920          # pixeles horizontales del flujo
LP = 0.40          # ancho real de placa (m)
UMBRAL_PX = 100    # minimo recomendado ANPR
UMBRAL_RHO = 250   # umbral IEC 62676-4 identificacion (px/m)


def calcular(distancias, fov_deg):
    media = math.radians(fov_deg) / 2.0
    filas = []
    for d in distancias:
        W = 2.0 * d * math.tan(media)
        rho = NH / W
        wp = rho * LP
        filas.append((d, W, rho, wp))
    return filas


def dibujar(filas, fov_deg, out):
    media = math.radians(fov_deg) / 2.0
    dmax = max(f[0] for f in filas) * 1.1
    half_max = dmax * math.tan(media)

    fig, ax = plt.subplots(figsize=(9, 7))

    # Bordes del cono (vista superior): camara en (0,0), mira hacia +Y.
    ax.plot([0, half_max], [0, dmax], color="gray", lw=1.5)
    ax.plot([0, -half_max], [0, dmax], color="gray", lw=1.5)
    ax.plot(0, 0, "ks", markersize=10)
    ax.annotate("CÁMARA\n(1920 px)", (0, 0), textcoords="offset points",
                xytext=(0, -28), ha="center", fontsize=9, weight="bold")

    # Distancia donde rho = 250 (umbral): W = Nh/250 -> d = W/(2 tan)
    W_umbral = NH / UMBRAL_RHO
    d_umbral = W_umbral / (2.0 * math.tan(media))
    if d_umbral < dmax:
        hw = W_umbral / 2.0
        ax.plot([-hw, hw], [d_umbral, d_umbral], color="red", lw=1.2, ls="--")
        ax.annotate(f"límite norma 250 px/m\n(W={W_umbral:.1f} m, d={d_umbral:.1f} m)",
                    (hw, d_umbral), textcoords="offset points", xytext=(8, 0),
                    fontsize=8, color="red", va="center")

    colores = plt.cm.viridis([i / max(1, len(filas) - 1) for i in range(len(filas))])
    for (d, W, rho, wp), c in zip(filas, colores):
        hw = W / 2.0
        ax.plot([-hw, hw], [d, d], color=c, lw=3)
        ok = "OK" if wp >= UMBRAL_PX else "BAJO"
        ax.annotate(f"d={d:.0f} m  →  W={W:.1f} m  |  {rho:.0f} px/m  |  placa {wp:.0f} px [{ok}]",
                    (hw, d), textcoords="offset points", xytext=(10, 0),
                    fontsize=8, va="center", color=c)

    ax.set_xlabel("ancho real (m)  ←  de lado a lado  →")
    ax.set_ylabel("distancia cámara → objeto (m)")
    ax.set_title(f"El ancho de escena W crece con la distancia (FOV horizontal = {fov_deg}°)\n"
                 f"más lejos = W mayor = menos píxeles sobre la placa")
    ax.set_xlim(-half_max * 1.05, half_max * 1.6)
    ax.set_ylim(-1, dmax)
    ax.grid(alpha=0.3)
    ax.set_aspect("equal", adjustable="box")
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    print(f"\nFigura guardada en: {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fov", type=float, default=70.0,
                    help="campo de visión horizontal en grados (def 70)")
    ap.add_argument("--out", default="tools/results/ancho_escena_vs_distancia.png")
    args = ap.parse_args()

    distancias = [2, 5, 10, 15, 20]
    filas = calcular(distancias, args.fov)

    print(f"FOV horizontal = {args.fov}°  |  Nh = {NH} px  |  placa = {LP} m\n")
    print(f"{'dist (m)':>8} {'W (m)':>8} {'densidad px/m':>14} {'placa px':>10}  estado")
    for d, W, rho, wp in filas:
        estado = "OK" if wp >= UMBRAL_PX else "BAJO"
        print(f"{d:>8.0f} {W:>8.1f} {rho:>14.0f} {wp:>10.0f}  {estado}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    dibujar(filas, args.fov, str(out))


if __name__ == "__main__":
    main()
