"""Recorta la PLACA de las fotos de carro entero del dataset Ecuador
(Modelo_DeteccionPlacasEc) para que queden a la MISMA escala que los demas
datasets (recortes de placa, no escena completa).

Razon: en ese dataset el caracter mide ~3% del alto de la imagen (carro entero);
las otras fuentes son recortes donde el char mide ~45%. Si se mezcla crudo, al
redimensionar a 256x96 la placa queda en ~3 px y la red aprende informacion
poco util.

Cada imagen trae la geometria de la placa (clase 'car plate', poligono o bbox).
Se recorta por esa placa + padding y:
  - si la foto trae cajas de caracteres -> recorte + label renormalizado
  - si solo trae la placa               -> recorte sin label para evaluacion visual

Salidas (one-shot, se regeneran con --clean):
  Datasets/ecuador_real_crops/train/{images,labels}   (placas con chars)
  ml/datasets/evaluation/ecuador_plate_tests/         (placas sin label, juez real)

Uso:
    py -3.10 crop_ecuador_plates.py
    py -3.10 crop_ecuador_plates.py --clean      # borra salidas antes
"""
import argparse
import shutil
from pathlib import Path

import cv2

_HERE = Path(__file__).parent
PROJECT_ROOT = _HERE.resolve().parents[1]
SRC = PROJECT_ROOT / "datasets" / "raw" / "ecuador_plate_detection"
OUT_TRAIN = PROJECT_ROOT / "datasets" / "processed" / "ecuador_plate_crops" / "train"
OUT_TEST = PROJECT_ROOT / "datasets" / "evaluation" / "ecuador_plate_tests"

NAMES = ['0', '1', '10', '11', '12', '13', '14', '15', '16', '17', '2', '20',
         '21', '22', '23', '24', '25', '27', '28', '29', '3', '30', '31', '33',
         '4', '5', '6', '7', '8', '9', 'car plate']
PLATE = 'car plate'
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


def find_image(images_dir, stem):
    for ext in IMAGE_EXTS:
        p = images_dir / f"{stem}{ext}"
        if p.exists():
            return p
    return None


def parse_lines(label_path):
    """Devuelve (chars, plates). chars=[(cx,cy,w,h)], plates=[(x1,y1,x2,y2)] norm."""
    chars, plates = [], []
    for line in label_path.read_text(encoding="utf-8").splitlines():
        t = line.split()
        if not t:
            continue
        name = NAMES[int(t[0])]
        vals = [float(v) for v in t[1:]]
        if name == PLATE:
            if len(vals) == 4:  # bbox cx,cy,w,h
                cx, cy, w, h = vals
                plates.append((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2))
            elif len(vals) >= 6:  # poligono x1 y1 x2 y2 ...
                xs = vals[0::2]
                ys = vals[1::2]
                plates.append((min(xs), min(ys), max(xs), max(ys)))
        elif len(vals) == 4:  # char bbox limpio
            chars.append(tuple(vals))
    return chars, plates


def pick_plate(plates, chars):
    """Placa que enmarca los chars (la que contiene su centro); si no hay chars,
    la placa de mayor area (sujeto principal)."""
    if not plates:
        return None
    if chars:
        ccx = sum(c[0] for c in chars) / len(chars)
        ccy = sum(c[1] for c in chars) / len(chars)
        for (x1, y1, x2, y2) in plates:
            if x1 <= ccx <= x2 and y1 <= ccy <= y2:
                return (x1, y1, x2, y2)
    return max(plates, key=lambda p: (p[2] - p[0]) * (p[3] - p[1]))


def crop_window(plate, pad, img_w, img_h):
    x1, y1, x2, y2 = plate
    pw, ph = (x2 - x1), (y2 - y1)
    x1 = max(0.0, x1 - pw * pad)
    y1 = max(0.0, y1 - ph * pad)
    x2 = min(1.0, x2 + pw * pad)
    y2 = min(1.0, y2 + ph * pad)
    px1, py1 = int(x1 * img_w), int(y1 * img_h)
    px2, py2 = int(x2 * img_w), int(y2 * img_h)
    return (x1, y1, x2, y2), (px1, py1, px2, py2)


def renorm_chars(chars, win):
    """Reexpresa cajas char respecto a la ventana de recorte (coords del recorte)."""
    wx1, wy1, wx2, wy2 = win
    ww, wh = (wx2 - wx1), (wy2 - wy1)
    out = []
    for (cx, cy, w, h) in chars:
        ncx = (cx - wx1) / ww
        ncy = (cy - wy1) / wh
        nw, nh = w / ww, h / wh
        if 0 <= ncx <= 1 and 0 <= ncy <= 1:
            out.append((ncx, ncy, nw, nh))
    return out


def main():
    ap = argparse.ArgumentParser(description="Recorta placas Ecuador a escala de recorte.")
    ap.add_argument("--pad", type=float, default=0.08, help="Padding alrededor de la placa.")
    ap.add_argument("--min-chars", type=int, default=4, help="Minimo de chars para ir a entreno.")
    ap.add_argument("--clean", action="store_true", help="Borra las carpetas de salida antes.")
    args = ap.parse_args()

    if args.clean:
        for d in (OUT_TRAIN.parent, OUT_TEST):
            if d.exists():
                shutil.rmtree(d)

    (OUT_TRAIN / "images").mkdir(parents=True, exist_ok=True)
    (OUT_TRAIN / "labels").mkdir(parents=True, exist_ok=True)
    OUT_TEST.mkdir(parents=True, exist_ok=True)

    n_skip = 0
    seen_train, seen_test = set(), set()  # unicos por foto base (dedupe)
    for split in ("train", "valid", "test"):
        labels_dir = SRC / split / "labels"
        images_dir = SRC / split / "images"
        if not labels_dir.exists():
            continue
        for label_path in sorted(labels_dir.glob("*.txt")):
            image_path = find_image(images_dir, label_path.stem)
            if image_path is None:
                continue
            image = cv2.imread(str(image_path))
            if image is None:
                n_skip += 1
                continue
            h, w = image.shape[:2]

            chars, plates = parse_lines(label_path)
            plate = pick_plate(plates, chars)
            if plate is None:
                n_skip += 1
                continue

            win, (px1, py1, px2, py2) = crop_window(plate, args.pad, w, h)
            if px2 - px1 < 10 or py2 - py1 < 10:
                n_skip += 1
                continue
            crop = image[py1:py2, px1:px2]

            # dedupe por foto base: roboflow trae la misma imagen aumentada Nx con
            # distinto sufijo .rf.<hash>; nos quedamos con una (la nuestra aug en vivo).
            base = label_path.stem.split(".rf.")[0]
            stem = f"{split}_{base}"
            new_chars = renorm_chars(chars, win) if chars else []
            if len(new_chars) >= args.min_chars:
                cv2.imwrite(str(OUT_TRAIN / "images" / f"{stem}.jpg"), crop)
                lines = [f"0 {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}"
                         for (cx, cy, bw, bh) in new_chars]
                (OUT_TRAIN / "labels" / f"{stem}.txt").write_text(
                    "\n".join(lines) + "\n", encoding="utf-8")
                seen_train.add(stem)
            else:
                cv2.imwrite(str(OUT_TEST / f"{stem}.jpg"), crop)
                seen_test.add(stem)

    print(f"Entreno (con chars):   {len(seen_train)} placas unicas -> {OUT_TRAIN}")
    print(f"Test visual (s/label): {len(seen_test)} placas unicas -> {OUT_TEST}")
    print(f"Saltadas:              {n_skip}")


if __name__ == "__main__":
    main()
