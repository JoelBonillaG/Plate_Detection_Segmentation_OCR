"""Renderiza los TARGETS de entrenamiento (mascara + separadores + mapa de pesos)
sobre imagenes reales del dataset, para verificar que la red va a aprender chars
SEPARADOS y a ANCHO COMPLETO antes de lanzar un entrenamiento largo.

Uso:
    py -3.10 preview_targets.py --num 6
Salida: carpeta preview_targets/ con un PNG por muestra (imagen | mascara | pesos).
"""
import argparse
from pathlib import Path

import cv2
import numpy as np

from train_char_segmentation import collect_pairs, load_gray_image, parse_boxes, build_targets

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = PROJECT_ROOT / "datasets" / "raw" / "india_char_segmentation"


def render(image, target):
    gray = image[:, :, 0].astype("uint8")
    base = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    mask = (target[:, :, 0] > 0.5).astype("uint8")
    weight = target[:, :, 1]

    # Overlay: mascara en verde semi-transparente, separadores (peso>1) en rojo.
    overlay = base.copy()
    overlay[mask == 1] = (0.5 * overlay[mask == 1] + np.array([0, 120, 0])).clip(0, 255)
    overlay[weight > 1.0] = (0.4 * overlay[weight > 1.0] + np.array([0, 0, 150])).clip(0, 255)

    mask_vis = cv2.cvtColor(mask * 255, cv2.COLOR_GRAY2BGR)
    w_norm = (255 * (weight - weight.min()) / max(1e-6, weight.max() - weight.min())).astype("uint8")
    weight_vis = cv2.applyColorMap(w_norm, cv2.COLORMAP_JET)

    sep = np.full((base.shape[0], 4, 3), 255, dtype="uint8")
    return np.hstack([base, sep, overlay, sep, mask_vis, sep, weight_vis])


def main():
    parser = argparse.ArgumentParser(description="Previsualiza targets de entrenamiento.")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--split", default="train")
    parser.add_argument("--height", type=int, default=96)
    parser.add_argument("--width", type=int, default=256)
    parser.add_argument("--sep-ratio", type=float, default=0.08)
    parser.add_argument("--shrink-y", type=float, default=0.95)
    parser.add_argument("--border-weight", type=float, default=8.0)
    parser.add_argument("--num", type=int, default=6)
    parser.add_argument("--output-dir", default="preview_targets")
    parser.add_argument("--filter", action="store_true",
                        help="Aplica el filtro de calidad (util para revisar UK/Brasil).")
    args = parser.parse_args()

    # collect_pairs ahora espera una lista de datasets (dicts). Para previsualizar
    # un solo dataset lo envolvemos; --filter activa el mismo gate del entrenamiento.
    pairs = collect_pairs(
        [{"name": Path(args.dataset).name, "path": Path(args.dataset),
          "filter": args.filter, "max": 0, "splits": (args.split,)}],
        args.split,
    )
    if not pairs:
        raise ValueError("No se encontraron pares imagen/label.")

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    step = max(1, len(pairs) // args.num)
    chosen = pairs[::step][: args.num]

    for index, (image_path, label_path) in enumerate(chosen):
        image = load_gray_image(image_path, args.height, args.width)
        boxes = parse_boxes(label_path)
        target = build_targets(boxes, args.height, args.width,
                               args.sep_ratio, args.shrink_y, args.border_weight)
        panel = render(image, target)
        panel = cv2.resize(panel, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_NEAREST)
        cv2.imwrite(str(out / f"preview_{index:02d}.png"), panel)
        n_boxes = len(boxes)
        print(f"[{index}] {label_path.stem[:24]}  chars_label={n_boxes}")

    print(f"Previews en: {out.resolve()}")
    print("Lee el orden: ORIGINAL | OVERLAY(verde=mascara,rojo=separador) | MASCARA | PESOS")


if __name__ == "__main__":
    main()
