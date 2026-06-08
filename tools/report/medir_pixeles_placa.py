"""
Mide la densidad espacial real (px/m) de tus capturas usando la placa como
referencia conocida (0,40 m de ancho).

Idea:
  - El modelo YOLO detecta la placa y nos da su ancho en pixeles (w_p).
  - La placa ecuatoriana mide L_p = 0,40 m de ancho real.
  - Densidad rho = w_p / L_p   (pixeles por metro REAL en el plano de la placa)
  - Ancho de escena W = ancho_imagen / rho   (metros que abarca la foto a esa
    distancia, de izquierda a derecha)

Asi obtienes evidencia numerica real, no teorica, para el informe.

Uso:
    python medir_pixeles_placa.py <imagen_o_carpeta> [--save]

    --save  guarda cada imagen con la caja y los numeros dibujados.
"""

import sys
from pathlib import Path

import cv2
from ultralytics import YOLO

# --- Constantes del problema ---
PLACA_ANCHO_M = 0.40          # ancho real de la placa ecuatoriana (m)
UMBRAL_PX = 100               # minimo recomendado ANPR (px de placa)
UMBRAL_DENSIDAD = 250         # umbral IEC 62676-4 identificacion (px/m)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODELO = PROJECT_ROOT / "ml" / "models" / "plate_detection" / "runs" / \
    "placas_scratch-90000" / "weights" / "best.pt"

IMG_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


def medir(modelo, ruta_img, guardar=False):
    img = cv2.imread(str(ruta_img))
    if img is None:
        print(f"  [x] no se pudo leer {ruta_img.name}")
        return
    alto, ancho = img.shape[:2]

    res = modelo.predict(img, verbose=False)[0]
    if len(res.boxes) == 0:
        print(f"{ruta_img.name:35} -> sin placa detectada")
        return

    # Si hay varias, tomamos la mas grande (la mas cercana = mas pixeles).
    boxes = res.boxes.xyxy.cpu().numpy()
    anchos = boxes[:, 2] - boxes[:, 0]
    idx = anchos.argmax()
    x1, y1, x2, y2 = boxes[idx]
    w_p = float(anchos[idx])                       # ancho de placa en px
    conf = float(res.boxes.conf.cpu().numpy()[idx])

    rho = w_p / PLACA_ANCHO_M                       # densidad px/m
    W = ancho / rho                                 # ancho de escena (m)

    ok_px = "OK" if w_p >= UMBRAL_PX else "BAJO"
    ok_rho = "OK" if rho >= UMBRAL_DENSIDAD else "BAJO"

    print(f"{ruta_img.name:35} | placa {w_p:6.1f} px [{ok_px:4}] "
          f"| densidad {rho:6.1f} px/m [{ok_rho:4}] "
          f"| escena ~{W:4.1f} m | conf {conf:.2f}")

    if guardar:
        cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 2)
        txt = f"{w_p:.0f}px  {rho:.0f}px/m  W={W:.1f}m"
        cv2.putText(img, txt, (int(x1), int(y1) - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        out_dir = ruta_img.parent / "medido"
        out_dir.mkdir(exist_ok=True)
        cv2.imwrite(str(out_dir / ruta_img.name), img)


def main():
    if len(sys.argv) < 2:
        print("uso: python medir_pixeles_placa.py <imagen_o_carpeta> [--save]")
        sys.exit(1)

    objetivo = Path(sys.argv[1])
    guardar = "--save" in sys.argv

    print(f"Modelo: {MODELO.name}")
    print(f"Placa = {PLACA_ANCHO_M} m | umbral {UMBRAL_PX} px / "
          f"{UMBRAL_DENSIDAD} px/m\n")
    modelo = YOLO(str(MODELO))

    if objetivo.is_dir():
        imgs = sorted(p for p in objetivo.rglob("*") if p.suffix.lower() in IMG_EXTS)
    else:
        imgs = [objetivo]

    for img in imgs:
        medir(modelo, img, guardar)


if __name__ == "__main__":
    main()
