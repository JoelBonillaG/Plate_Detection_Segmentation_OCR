import argparse
import shutil
from pathlib import Path

import cv2
import numpy as np
import tensorflow as tf


def prepare_image(image_path, height, width):
    original = cv2.imread(str(image_path))
    if original is None:
        raise ValueError(f"No se pudo leer la imagen: {image_path}")

    gray = cv2.cvtColor(original, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (width, height), interpolation=cv2.INTER_AREA)
    model_input = resized.astype("float32")[None, :, :, None]
    return original, model_input


CHAR_ASPECT = 0.60  # ancho/alto tipico de un char de placa (digito ~0.5, letra ~0.65)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = PROJECT_ROOT / "models" / "char_segmentation" / "Models" / "best_char_segmentation_unet.keras"


def split_box_by_projection(binary, x, y, w, h, expected_w):
    # Blob mas ancho que ~1 char = varios chars pegados. Cuantos caben se estima por
    # el ANCHO esperado (derivado de la ALTURA, que NUNCA se fusiona) -> robusto aunque
    # TODOS los chars vengan fusionados. Prior de pitch uniforme: cortes en i*w/n,
    # ajustados al valle real (minimo de proyeccion) mas cercano.
    n = max(1, int(round(w / expected_w)))
    if n <= 1:
        return [(x, y, w, h)]

    column_sum = binary[y:y + h, x:x + w].sum(axis=0).astype("float32")
    smooth = max(1, int(expected_w * 0.15))
    if smooth > 1:
        column_sum = np.convolve(column_sum, np.ones(smooth) / smooth, mode="same")

    window = max(1, int(expected_w * 0.40))
    min_seg = max(2, int(expected_w * 0.35))  # ancho minimo de sub-char: evita slivers

    cuts = []
    prev = 0
    for i in range(1, n):
        center = i * w / n
        lo = max(prev + min_seg, int(center - window))
        hi = min(w - min_seg, int(center + window))
        if hi <= lo:
            cut = int(center)
        else:
            cut = lo + int(np.argmin(column_sum[lo:hi]))
        cut = max(prev + min_seg, min(cut, w - min_seg))  # respeta orden y margenes
        if prev < cut < w:
            cuts.append(cut)
            prev = cut

    bounds = [0] + cuts + [w]
    sub_boxes = []
    for i in range(len(bounds) - 1):
        sw = bounds[i + 1] - bounds[i]
        if sw > 0:
            sub_boxes.append((x + bounds[i], y, sw, h))
    return sub_boxes


def mask_to_boxes(mask, original_shape, threshold, min_area_ratio, padding,
                  char_aspect=CHAR_ASPECT, height_keep_ratio=0.50):
    original_h, original_w = original_shape[:2]
    mask_h, mask_w = mask.shape[:2]

    binary = (mask >= threshold).astype("uint8") * 255
    kernel = np.ones((3, 3), np.uint8)
    # Solo OPEN (quita ruido). CLOSE pegaba chars vecinos -> eliminado.
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)

    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = mask_h * mask_w * min_area_ratio

    raw = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w * h >= min_area:
            raw.append((x, y, w, h))

    if not raw:
        return [], binary

    # Los chars son los blobs mas altos. Descarta subtexto/ruido por altura (p.ej.
    # "NEW SOUTH WALES", tornillos) antes de estimar el ancho de char.
    max_h = max(h for (_, _, _, h) in raw)
    chars = [b for b in raw if b[3] >= height_keep_ratio * max_h]
    if not chars:
        chars = raw

    median_h = float(np.median([h for (_, _, _, h) in chars]))
    median_w = float(np.median([w for (_, _, w, _) in chars]))
    # expected_w = pitch de char. Con VARIOS blobs el ancho mediano ES el pitch real y es
    # robusto a tilt/blur, donde char_aspect (ancho=0.6*alto) deja de valer y partia los
    # chars de mas. Con 1-2 blobs (posible fusion total) cae al estimado por altura.
    if len(chars) >= 3:
        expected_w = max(median_w, median_h * char_aspect * 0.8)
    else:
        expected_w = max(1.0, median_h * char_aspect)

    split = []
    for (x, y, w, h) in chars:
        # solo intenta partir si el blob es claramente mas ancho que un char (>1.5x pitch);
        # asi no trocea un char individual un poco ancho por tilt.
        if w >= 1.5 * expected_w:
            split.extend(split_box_by_projection(binary, x, y, w, h, expected_w))
        else:
            split.append((x, y, w, h))

    boxes = []
    scale_x = original_w / mask_w
    scale_y = original_h / mask_h

    for (x, y, w, h) in split:
        x1 = int(x * scale_x)
        y1 = int(y * scale_y)
        x2 = int((x + w) * scale_x)
        y2 = int((y + h) * scale_y)

        bw = max(1, x2 - x1)
        bh = max(1, y2 - y1)
        px = int(bw * padding)
        py = int(bh * padding)

        x1 = max(0, x1 - px)
        y1 = max(0, y1 - py)
        x2 = min(original_w, x2 + px)
        y2 = min(original_h, y2 + py)

        if x2 > x1 and y2 > y1:
            boxes.append((x1, y1, x2, y2))

    boxes = sorted(boxes, key=lambda box: box[0])
    return boxes, binary


def save_debug_outputs(original, mask, binary, boxes, output_dir):
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    mask_u8 = np.clip(mask * 255, 0, 255).astype("uint8")
    cv2.imwrite(str(output_dir / "mask_probability.png"), mask_u8)
    cv2.imwrite(str(output_dir / "mask_binary.png"), binary)

    debug = original.copy()
    for index, (x1, y1, x2, y2) in enumerate(boxes):
        cv2.rectangle(debug, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(
            debug,
            str(index),
            (x1, max(0, y1 - 4)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 255, 0),
            1,
            cv2.LINE_AA,
        )

        crop = original[y1:y2, x1:x2]
        cv2.imwrite(str(output_dir / f"char_{index:02d}.png"), crop)

    cv2.imwrite(str(output_dir / "boxes.png"), debug)


def main():
    parser = argparse.ArgumentParser(
        description="Predice mascara de caracteres y extrae cajas/crops sin usar YOLO."
    )
    parser.add_argument("--image", required=True, help="Imagen de placa recortada.")
    parser.add_argument(
        "--model",
        default=str(DEFAULT_MODEL),
        help="Modelo .keras entrenado.",
    )
    parser.add_argument("--output-dir", default="debug_segmentation")
    parser.add_argument("--threshold", type=float, default=0.50)
    parser.add_argument("--min-area-ratio", type=float, default=0.002)
    parser.add_argument("--padding", type=float, default=0.08)
    parser.add_argument(
        "--char-aspect", type=float, default=CHAR_ASPECT,
        help="Ancho/alto esperado de un char. Sube si parte chars de mas, baja si fusiona.",
    )
    args = parser.parse_args()

    model = tf.keras.models.load_model(args.model, compile=False)
    input_shape = model.input_shape
    height = int(input_shape[1])
    width = int(input_shape[2])

    print(f"Modelo cargado: {args.model}")
    print(f"Input esperado: {width}x{height}x1")

    original, model_input = prepare_image(args.image, height, width)
    prediction = model.predict(model_input, verbose=0)[0, :, :, 0]

    boxes, binary = mask_to_boxes(
        prediction,
        original.shape,
        threshold=args.threshold,
        min_area_ratio=args.min_area_ratio,
        padding=args.padding,
        char_aspect=args.char_aspect,
    )

    save_debug_outputs(
        original=original,
        mask=prediction,
        binary=binary,
        boxes=boxes,
        output_dir=Path(args.output_dir),
    )

    print(f"Caracteres detectados: {len(boxes)}")
    for index, box in enumerate(boxes):
        print(f"Char {index}: box={box}")
    print(f"Salidas debug en: {Path(args.output_dir).resolve()}")


if __name__ == "__main__":
    main()
