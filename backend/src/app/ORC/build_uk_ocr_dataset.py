import argparse
import ast
import shutil
from pathlib import Path

import cv2
import numpy as np


VALID_CLASSES = set("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")

_DATASETS = Path(__file__).parent / "Datasets_Crudos"
DATASET_UK  = _DATASETS / "en.v4i.yolov8"
DATASET_BR  = _DATASETS / "plate-ocr.v4i.yolov8"
OUTPUT_DIR  = Path(__file__).parent / "Dataset_OCR_Final"
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


def normalize_class_name(name):
    # Brasil usa nombres como '-0-', '-1-' -> strip guiones -> '0', '1'
    return name.strip("-")


def read_class_names(data_yaml_path):
    text = Path(data_yaml_path).read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("names:"):
            raw_names = stripped.split(":", 1)[1].strip()
            names = ast.literal_eval(raw_names)
            return [str(name) for name in names]
    raise ValueError(f"No se encontro la linea 'names:' en {data_yaml_path}")


def find_image(images_dir, label_stem):
    for extension in IMAGE_EXTENSIONS:
        image_path = images_dir / f"{label_stem}{extension}"
        if image_path.exists():
            return image_path
    return None


def yolo_to_xyxy(values, image_width, image_height, padding_ratio):
    x_center, y_center, box_width, box_height = values

    x1 = int((x_center - box_width / 2) * image_width)
    y1 = int((y_center - box_height / 2) * image_height)
    x2 = int((x_center + box_width / 2) * image_width)
    y2 = int((y_center + box_height / 2) * image_height)

    width = max(1, x2 - x1)
    height = max(1, y2 - y1)
    pad_x = int(width * padding_ratio)
    pad_y = int(height * padding_ratio)

    x1 = max(0, x1 - pad_x)
    y1 = max(0, y1 - pad_y)
    x2 = min(image_width, x2 + pad_x)
    y2 = min(image_height, y2 + pad_y)

    return x1, y1, x2, y2


def normalize_crop(crop_bgr, output_size):
    if crop_bgr.size == 0:
        return None

    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape[:2]
    if width == 0 or height == 0:
        return None

    scale = min(output_size / width, output_size / height) * 0.90
    resized_width = max(1, min(output_size, int(width * scale)))
    resized_height = max(1, min(output_size, int(height * scale)))

    resized = cv2.resize(
        gray,
        (resized_width, resized_height),
        interpolation=cv2.INTER_AREA,
    )

    light_pixels = gray[gray > 120]
    background = int(np.median(light_pixels)) if light_pixels.size else 245
    background = int(np.clip(background, 210, 255))

    canvas = np.full((output_size, output_size), background, dtype=np.uint8)
    x_offset = (output_size - resized_width) // 2
    y_offset = (output_size - resized_height) // 2
    canvas[
        y_offset:y_offset + resized_height,
        x_offset:x_offset + resized_width,
    ] = resized

    return canvas


def prepare_output_dirs(output_dir, clean):
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)

    for split in ("train", "valid", "test"):
        for class_name in sorted(VALID_CLASSES):
            (output_dir / split / class_name).mkdir(parents=True, exist_ok=True)


def count_files(path, pattern):
    if not path.exists():
        return 0
    return sum(1 for _ in path.glob(pattern))


def convert_split(dataset_dir, output_dir, split, class_names, output_size, padding_ratio, log_every, prefix=""):
    images_dir = dataset_dir / split / "images"
    labels_dir = dataset_dir / split / "labels"

    label_paths = sorted(labels_dir.glob("*.txt")) if labels_dir.exists() else []
    total_labels = len(label_paths)
    total_images = count_files(images_dir, "*.*")

    print(f"\n[{split}] imagenes={total_images} labels={total_labels}")

    if total_labels == 0:
        print(f"[{split}] No hay labels para procesar.")
        return {"saved": 0, "skipped": 0, "missing_images": 0, "class_counts": {}}

    saved = 0
    skipped = 0
    missing_images = 0
    class_counts = {class_name: 0 for class_name in sorted(VALID_CLASSES)}

    for index, label_path in enumerate(label_paths, start=1):
        image_path = find_image(images_dir, label_path.stem)
        if image_path is None:
            missing_images += 1
            skipped += 1
            continue

        image = cv2.imread(str(image_path))
        if image is None:
            skipped += 1
            continue

        image_height, image_width = image.shape[:2]
        lines = label_path.read_text(encoding="utf-8").splitlines()

        for line_index, line in enumerate(lines):
            parts = line.strip().split()
            if len(parts) != 5:
                skipped += 1
                continue

            try:
                class_id = int(float(parts[0]))
                box_values = [float(value) for value in parts[1:]]
            except ValueError:
                skipped += 1
                continue

            if class_id < 0 or class_id >= len(class_names):
                skipped += 1
                continue

            class_name = normalize_class_name(class_names[class_id])
            if class_name not in VALID_CLASSES:
                skipped += 1
                continue

            x1, y1, x2, y2 = yolo_to_xyxy(
                box_values,
                image_width,
                image_height,
                padding_ratio,
            )

            if x2 <= x1 or y2 <= y1:
                skipped += 1
                continue

            crop = image[y1:y2, x1:x2]
            normalized = normalize_crop(crop, output_size)
            if normalized is None:
                skipped += 1
                continue

            output_name = f"{prefix}{label_path.stem}_{line_index:02d}.png"
            output_path = output_dir / split / class_name / output_name
            cv2.imwrite(str(output_path), normalized)

            saved += 1
            class_counts[class_name] += 1

        if index == total_labels or index % log_every == 0:
            percent = (index / total_labels) * 100
            print(
                f"[{split}] {index}/{total_labels} labels "
                f"({percent:6.2f}%) | crops={saved} | omitidos={skipped}"
            )

    print(
        f"[{split}] terminado | crops={saved} | omitidos={skipped} "
        f"| imagenes_sin_match={missing_images}"
    )

    return {
        "saved": saved,
        "skipped": skipped,
        "missing_images": missing_images,
        "class_counts": class_counts,
    }


def write_classes_file(output_dir):
    classes_path = output_dir / "classes.txt"
    classes_path.write_text(
        "\n".join(sorted(VALID_CLASSES)) + "\n",
        encoding="utf-8",
    )
    return classes_path


def print_class_summary(results):
    print("\nResumen por clase:")
    header = f"{'Clase':>5} {'train':>8} {'valid':>8} {'test':>8} {'total':>8}"
    print(header)
    print("-" * len(header))

    for class_name in sorted(VALID_CLASSES):
        train_count = results.get("train", {}).get("class_counts", {}).get(class_name, 0)
        valid_count = results.get("valid", {}).get("class_counts", {}).get(class_name, 0)
        test_count = results.get("test", {}).get("class_counts", {}).get(class_name, 0)
        total = train_count + valid_count + test_count
        print(f"{class_name:>5} {train_count:8d} {valid_count:8d} {test_count:8d} {total:8d}")


def process_dataset(dataset_dir, output_dir, output_size, padding_ratio, log_every, prefix=""):
    data_yaml_path = dataset_dir / "data.yaml"
    if not data_yaml_path.exists():
        raise FileNotFoundError(f"No existe: {data_yaml_path}")

    class_names = read_class_names(data_yaml_path)
    invalid_names = [
        name for name in class_names
        if normalize_class_name(name) not in VALID_CLASSES
    ]
    if invalid_names:
        print(f"Clases ignoradas (no OCR estandar): {invalid_names}")

    results = {}
    for split in ("train", "valid", "test"):
        results[split] = convert_split(
            dataset_dir=dataset_dir,
            output_dir=output_dir,
            split=split,
            class_names=class_names,
            output_size=output_size,
            padding_ratio=padding_ratio,
            log_every=max(1, log_every),
            prefix=prefix,
        )
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Convierte datasets YOLOv8 a crops OCR separados en train/valid/test."
    )
    parser.add_argument("--dataset", default=str(DATASET_UK))
    parser.add_argument("--brazil-dataset", default=str(DATASET_BR))
    parser.add_argument("--brazil-only", action="store_true",
                        help="Solo procesa Brasil (omite UK).")
    parser.add_argument("--output", default=str(OUTPUT_DIR))
    parser.add_argument(
        "--size",
        type=int,
        default=64,
        help="Tamano final de cada crop en pixeles.",
    )
    parser.add_argument(
        "--padding",
        type=float,
        default=0.12,
        help="Padding proporcional alrededor de cada bounding box.",
    )
    parser.add_argument(
        "--log-every",
        type=int,
        default=250,
        help="Cada cuantos labels imprimir progreso.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Borra la carpeta de salida antes de generar los crops.",
    )
    args = parser.parse_args()

    output_dir = Path(args.output)
    prepare_output_dirs(output_dir, clean=args.clean)

    all_results = {}

    if not args.brazil_only:
        print("\n=== Procesando UK ===")
        uk_results = process_dataset(
            dataset_dir=Path(args.dataset),
            output_dir=output_dir,
            output_size=args.size,
            padding_ratio=args.padding,
            log_every=args.log_every,
            prefix="",
        )
        for split, r in uk_results.items():
            all_results.setdefault(split, {
                "saved": 0, "skipped": 0, "missing_images": 0,
                "class_counts": {c: 0 for c in sorted(VALID_CLASSES)},
            })
            all_results[split]["saved"] += r["saved"]
            all_results[split]["skipped"] += r["skipped"]
            all_results[split]["missing_images"] += r["missing_images"]
            for cls, cnt in r["class_counts"].items():
                all_results[split]["class_counts"][cls] = \
                    all_results[split]["class_counts"].get(cls, 0) + cnt

    print("\n=== Procesando Brasil ===")
    br_results = process_dataset(
        dataset_dir=Path(args.brazil_dataset),
        output_dir=output_dir,
        output_size=args.size,
        padding_ratio=args.padding,
        log_every=args.log_every,
        prefix="br_",
    )
    for split, r in br_results.items():
        all_results.setdefault(split, {
            "saved": 0, "skipped": 0, "missing_images": 0,
            "class_counts": {c: 0 for c in sorted(VALID_CLASSES)},
        })
        all_results[split]["saved"] += r["saved"]
        all_results[split]["skipped"] += r["skipped"]
        all_results[split]["missing_images"] += r["missing_images"]
        for cls, cnt in r["class_counts"].items():
            all_results[split]["class_counts"][cls] = \
                all_results[split]["class_counts"].get(cls, 0) + cnt

    classes_path = write_classes_file(output_dir)

    print_class_summary(all_results)
    print(f"\nDataset OCR generado en: {output_dir.resolve()}")
    print(f"Archivo de clases: {classes_path.resolve()}")


if __name__ == "__main__":
    main()
