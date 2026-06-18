"""Corre la segmentacion en LOTE sobre placas reales (salida del detector).

Es predict_char_segmentation.py pero para muchas imagenes: por cada placa guarda una
subcarpeta con como quedo la deteccion. Test manual/visual (no usa etiquetas).

Por cada imagen guarda en output-dir/<idx>_<nombre>/:
  - boxes.png            (placa con las cajas dibujadas y numeradas)
  - mask_binary.png      (mascara binarizada)
  - mask_probability.png (mascara cruda del modelo)
  - char_00.png ...      (cada caracter recortado)

Uso:
  py -3.10 evaluate_segmentation.py --num 40
"""
import argparse
import shutil
from pathlib import Path

import cv2
import numpy as np
import tensorflow as tf

from predict_char_segmentation import prepare_image, mask_to_boxes, CHAR_ASPECT

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_IMAGES_DIR = PROJECT_ROOT / "datasets" / "evaluation" / "real_plate_tests"
DEFAULT_MODEL = PROJECT_ROOT / "models" / "char_segmentation" / "Models" / "best_char_segmentation_unet.keras"


IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


def list_images(images_dir, num):
    files = sorted(p for p in Path(images_dir).iterdir() if p.suffix.lower() in IMAGE_EXTS)
    if num and num < len(files):
        step = max(1, len(files) // num)
        files = files[::step][:num]
    return files


def save_result(original, mask_prob, binary, boxes, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)

    cv2.imwrite(str(out_dir / "mask_probability.png"),
                np.clip(mask_prob * 255, 0, 255).astype("uint8"))
    cv2.imwrite(str(out_dir / "mask_binary.png"), binary)

    debug = original.copy()
    for index, (x1, y1, x2, y2) in enumerate(boxes):
        cv2.rectangle(debug, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(debug, str(index), (x1, max(0, y1 - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)
        crop = original[y1:y2, x1:x2]
        if crop.size:
            cv2.imwrite(str(out_dir / f"char_{index:02d}.png"), crop)

    cv2.imwrite(str(out_dir / "boxes.png"), debug)


def main():
    parser = argparse.ArgumentParser(description="Segmentacion en lote sobre placas reales (test visual).")
    parser.add_argument("--images-dir", default=str(DEFAULT_IMAGES_DIR))
    parser.add_argument("--model", default=str(DEFAULT_MODEL))
    parser.add_argument("--output-dir", default="test_resultados")
    parser.add_argument("--num", type=int, default=40, help="Cuantas imagenes procesar (muestreo uniforme).")
    parser.add_argument("--threshold", type=float, default=0.50)
    parser.add_argument("--min-area-ratio", type=float, default=0.002)
    parser.add_argument("--padding", type=float, default=0.08)
    parser.add_argument("--char-aspect", type=float, default=CHAR_ASPECT)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    model = tf.keras.models.load_model(args.model, compile=False)
    height = int(model.input_shape[1])
    width = int(model.input_shape[2])
    print(f"Modelo: {args.model}  | input {width}x{height}")

    files = list_images(args.images_dir, args.num)
    print(f"Procesando {len(files)} imagenes de {args.images_dir}\n")

    for index, image_path in enumerate(files):
        original, model_input = prepare_image(image_path, height, width)
        prediction = model.predict(model_input, verbose=0)[0, :, :, 0]
        boxes, binary = mask_to_boxes(
            prediction, original.shape,
            threshold=args.threshold,
            min_area_ratio=args.min_area_ratio,
            padding=args.padding,
            char_aspect=args.char_aspect,
        )

        sub_dir = output_dir / f"{index:03d}_{image_path.stem[:24]}"
        save_result(original, prediction, binary, boxes, sub_dir)
        print(f"[{index:03d}] chars={len(boxes):2d}  -> {sub_dir.name}")

    print(f"\nListo. Revisa las subcarpetas en: {output_dir.resolve()}")


if __name__ == "__main__":
    main()
