from __future__ import annotations

from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = PROJECT_ROOT / "ml" / "datasets" / "processed" / "ocr_characters_final"
REPORT_PICTURES = (
    PROJECT_ROOT.parent
    / "Informe"
    / "Informe_Proyecto_Final"
    / "picture"
)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


def _font(name: str, size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype(name, size)
    except OSError:
        return ImageFont.load_default()


BIG_FONT = _font("arial.ttf", 22)
MED_FONT = _font("arial.ttf", 16)
SMALL_FONT = _font("arial.ttf", 12)


def find_sample(label: str) -> Path:
    for split in ("test", "valid", "train"):
        folder = DATASET_DIR / split / label
        if not folder.exists():
            continue
        files = sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS)
        if files:
            return files[len(files) // 2]
    raise FileNotFoundError(f"No samples found for class {label!r}")


def resized_cell(image_path: Path, size: int) -> Image.Image:
    image = Image.open(image_path).convert("L")
    image = ImageOps.autocontrast(image)
    resized = image.resize((size, size), Image.Resampling.BILINEAR)
    return resized.resize((128, 128), Image.Resampling.NEAREST).convert("RGB")


def generate_resolution_comparison() -> Path:
    labels = ["O", "0"]
    sizes = [32, 48, 64]
    cell_size = 150
    cell_w, cell_h = 205, 190
    margin_x, margin_y = 55, 65
    canvas_w = margin_x + len(sizes) * cell_w + 35
    canvas_h = margin_y + len(labels) * cell_h + 35

    canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
    draw = ImageDraw.Draw(canvas)

    for column, size in enumerate(sizes):
        x = margin_x + column * cell_w
        title = f"{size} x {size}"
        box = draw.textbbox((0, 0), title, font=BIG_FONT)
        draw.text(
            (x + (cell_size - (box[2] - box[0])) / 2, 22),
            title,
            fill=(8, 42, 83),
            font=BIG_FONT,
        )

    for row, label in enumerate(labels):
        sample = find_sample(label)
        y = margin_y + row * cell_h
        for column, size in enumerate(sizes):
            x = margin_x + column * cell_w
            tile = resized_cell(sample, size)
            tile = tile.resize((cell_size, cell_size), Image.Resampling.NEAREST)
            canvas.paste(tile, (x, y))
            draw.rectangle((x, y, x + cell_size - 1, y + cell_size - 1), outline=(8, 42, 83), width=3)

    output = REPORT_PICTURES / "comparacion_resolucion_caracteres_32_48_64.png"
    canvas.save(output)
    return output


def generate_class_distribution() -> Path:
    counts: Counter[str] = Counter()
    for split in ("train", "valid", "test"):
        for class_dir in (DATASET_DIR / split).iterdir():
            if class_dir.is_dir():
                counts[class_dir.name] += sum(
                    1 for image in class_dir.iterdir() if image.suffix.lower() in IMAGE_EXTENSIONS
                )

    labels = [str(i) for i in range(10)] + [chr(ord("A") + i) for i in range(26)]
    values = [counts[label] for label in labels]
    max_value = max(values)

    chart_w, chart_h = 1200, 520
    left, top, right, bottom = 70, 50, 35, 80
    image = Image.new("RGB", (chart_w, chart_h), "white")
    draw = ImageDraw.Draw(image)
    draw.text(
        (left, 18),
        "Distribucion de muestras por clase del clasificador de caracteres",
        fill=(8, 42, 83),
        font=BIG_FONT,
    )

    plot_w = chart_w - left - right
    plot_h = chart_h - top - bottom
    axis_y = top + plot_h
    draw.line((left, top, left, axis_y), fill=(40, 40, 40), width=2)
    draw.line((left, axis_y, left + plot_w, axis_y), fill=(40, 40, 40), width=2)

    for tick in range(6):
        value = int(max_value * tick / 5)
        y = axis_y - int(plot_h * tick / 5)
        draw.line((left - 5, y, left + plot_w, y), fill=(230, 230, 230), width=1)
        draw.text((8, y - 7), f"{value}", fill=(80, 80, 80), font=SMALL_FONT)

    gap = 5
    bar_w = (plot_w - gap * (len(labels) - 1)) / len(labels)
    for index, (label, value) in enumerate(zip(labels, values)):
        x0 = left + int(index * (bar_w + gap))
        x1 = left + int(index * (bar_w + gap) + bar_w)
        height = int((value / max_value) * plot_h) if max_value else 0
        y0 = axis_y - height
        color = (16, 75, 129) if label.isalpha() else (48, 116, 70)
        draw.rectangle((x0, y0, x1, axis_y), fill=color)
        draw.text((x0 + 2, axis_y + 8), label, fill=(45, 45, 45), font=SMALL_FONT)

    total = sum(values)
    note = (
        f"Total: {total:,} recortes. El desbalance se mitiga con pesos por clase "
        "y perdida focal durante el entrenamiento."
    ).replace(",", ".")
    draw.text((left, chart_h - 30), note, fill=(60, 60, 60), font=SMALL_FONT)

    output = REPORT_PICTURES / "distribucion_clases_caracteres.png"
    image.save(output)
    return output


def main() -> None:
    REPORT_PICTURES.mkdir(parents=True, exist_ok=True)
    print(generate_resolution_comparison())
    print(generate_class_distribution())


if __name__ == "__main__":
    main()
