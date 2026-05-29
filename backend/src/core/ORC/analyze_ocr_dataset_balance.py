import argparse
import csv
from pathlib import Path
from statistics import mean


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
DEFAULT_CLASSES = list("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")


def count_images(class_dir):
    if not class_dir.exists():
        return 0
    return sum(
        1
        for path in class_dir.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


def load_classes(dataset_dir):
    classes_path = dataset_dir / "classes.txt"
    if classes_path.exists():
        classes = [
            line.strip()
            for line in classes_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if classes:
            return classes
    return DEFAULT_CLASSES


def split_stats(counts):
    values = list(counts.values())
    nonzero = [value for value in values if value > 0]

    if not values:
        return {
            "total": 0,
            "min": 0,
            "max": 0,
            "avg": 0,
            "max_min_ratio": 0,
            "zero_classes": 0,
        }

    min_count = min(values)
    max_count = max(values)

    return {
        "total": sum(values),
        "min": min_count,
        "max": max_count,
        "avg": mean(values),
        "max_min_ratio": (max_count / min(nonzero)) if nonzero else 0,
        "zero_classes": len([value for value in values if value == 0]),
    }


def balance_label(ratio):
    if ratio == 0:
        return "sin datos"
    if ratio <= 2:
        return "balance aceptable"
    if ratio <= 4:
        return "desbalance moderado"
    return "desbalance fuerte"


def analyze(dataset_dir, low_threshold):
    classes = load_classes(dataset_dir)
    splits = ["train", "valid", "test"]

    counts_by_split = {
        split: {
            class_name: count_images(dataset_dir / split / class_name)
            for class_name in classes
        }
        for split in splits
    }

    print(f"Dataset: {dataset_dir.resolve()}")
    print(f"Clases esperadas: {len(classes)}")

    for split in splits:
        stats = split_stats(counts_by_split[split])
        print(f"\n[{split}]")
        print(f"Total imagenes: {stats['total']}")
        print(f"Minimo por clase: {stats['min']}")
        print(f"Maximo por clase: {stats['max']}")
        print(f"Promedio por clase: {stats['avg']:.2f}")
        print(f"Relacion max/min no-cero: {stats['max_min_ratio']:.2f}")
        print(f"Estado: {balance_label(stats['max_min_ratio'])}")
        print(f"Clases sin imagenes: {stats['zero_classes']}")

        low_classes = [
            class_name
            for class_name, count in counts_by_split[split].items()
            if count < low_threshold
        ]
        if low_classes:
            joined = ", ".join(
                f"{class_name}={counts_by_split[split][class_name]}"
                for class_name in low_classes
            )
            print(f"Clases por debajo de {low_threshold}: {joined}")

    print("\nTabla por clase:")
    header = f"{'Clase':>5} {'train':>8} {'valid':>8} {'test':>8} {'total':>8}"
    print(header)
    print("-" * len(header))

    rows = []
    for class_name in classes:
        train_count = counts_by_split["train"][class_name]
        valid_count = counts_by_split["valid"][class_name]
        test_count = counts_by_split["test"][class_name]
        total = train_count + valid_count + test_count
        rows.append({
            "class": class_name,
            "train": train_count,
            "valid": valid_count,
            "test": test_count,
            "total": total,
        })
        print(f"{class_name:>5} {train_count:8d} {valid_count:8d} {test_count:8d} {total:8d}")

    return rows


def write_csv(rows, csv_path):
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["class", "train", "valid", "test", "total"])
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(
        description="Analiza el balance de clases de Dataset_OCR_Final."
    )
    parser.add_argument(
        "--dataset",
        default="Dataset_OCR_Final",
        help="Ruta del dataset OCR generado.",
    )
    parser.add_argument(
        "--low-threshold",
        type=int,
        default=100,
        help="Umbral para reportar clases con pocos ejemplos.",
    )
    parser.add_argument(
        "--csv",
        default="Dataset_OCR_Final/balance_report.csv",
        help="Ruta opcional para guardar la tabla CSV.",
    )
    args = parser.parse_args()

    dataset_dir = Path(args.dataset)
    rows = analyze(dataset_dir, args.low_threshold)

    if args.csv:
        csv_path = Path(args.csv)
        write_csv(rows, csv_path)
        print(f"\nCSV guardado en: {csv_path.resolve()}")


if __name__ == "__main__":
    main()
