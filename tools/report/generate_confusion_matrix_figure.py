from __future__ import annotations

import csv
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CSV_PATH = PROJECT_ROOT / "ml" / "training" / "ocr" / "Modelos" / "confusion_matrix.csv"
OUTPUT_PATH = (
    PROJECT_ROOT.parent
    / "Informe"
    / "Informe_Proyecto_Final"
    / "picture"
    / "matriz_confusion_clasificacion_caracteres.png"
)

LABELS = [str(i) for i in range(10)] + [chr(ord("A") + i) for i in range(26)]


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    names = ["arialbd.ttf", "arial.ttf"] if bold else ["arial.ttf"]
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def load_matrix() -> list[list[int]]:
    rows: list[list[int]] = []
    with CSV_PATH.open(newline="", encoding="utf-8") as csv_file:
        for row in csv.reader(csv_file):
            if row:
                rows.append([int(float(value)) for value in row])

    if len(rows) != len(LABELS) or any(len(row) != len(LABELS) for row in rows):
        width = len(rows[0]) if rows else 0
        raise ValueError(f"Expected 36x36 matrix without header, got {len(rows)}x{width}")
    return rows


def main() -> None:
    rows = load_matrix()
    total = sum(map(sum, rows))
    correct = sum(rows[i][i] for i in range(len(LABELS)))
    errors = total - correct

    offdiag: list[tuple[int, str, str]] = []
    for i, real in enumerate(LABELS):
        for j, pred in enumerate(LABELS):
            value = rows[i][j]
            if i != j and value:
                offdiag.append((value, real, pred))
    offdiag.sort(reverse=True)

    width, height = 1720, 1600
    left, top = 150, 145
    cell = 32
    plot = cell * len(LABELS)

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title_font = font(30, bold=True)
    text_font = font(14)
    small_font = font(11)
    tiny_font = font(9)

    draw.text(
        (width // 2 - 345, 35),
        "Matriz de confusion del clasificador de caracteres",
        fill=(8, 42, 83),
        font=title_font,
    )
    draw.text(
        (width // 2 - 230, 75),
        f"Test completo: {total} recortes | Accuracy: {correct / total:.4f} | Errores: {errors}",
        fill=(70, 70, 70),
        font=text_font,
    )

    max_value = max(max(row) for row in rows)
    for i in range(len(LABELS)):
        for j in range(len(LABELS)):
            value = rows[i][j]
            if value == 0:
                color = (253, 246, 253)
            elif i == j:
                t = math.sqrt(value / max_value)
                color = (int(230 - 210 * t), int(240 - 135 * t), int(255 - 30 * t))
            else:
                t = min(1, math.sqrt(value / 50))
                color = (255, int(245 - 150 * t), int(220 - 180 * t))

            x = left + j * cell
            y = top + i * cell
            draw.rectangle((x, y, x + cell, y + cell), fill=color, outline=(215, 215, 215))

            if value > 0:
                label = str(value)
                fill = "white" if (i == j and value > 40) or (i != j and value > 15) else (60, 30, 30)
                bbox = draw.textbbox((0, 0), label, font=tiny_font)
                draw.text(
                    (x + (cell - (bbox[2] - bbox[0])) / 2, y + (cell - (bbox[3] - bbox[1])) / 2),
                    label,
                    fill=fill,
                    font=tiny_font,
                )

    for index, label in enumerate(LABELS):
        x = left + index * cell + cell / 2
        bbox = draw.textbbox((0, 0), label, font=small_font)
        draw.text((x - (bbox[2] - bbox[0]) / 2, top - 20), label, fill=(20, 20, 20), font=small_font)

        y = top + index * cell + cell / 2
        bbox = draw.textbbox((0, 0), label, font=small_font)
        draw.text((left - 28, y - (bbox[3] - bbox[1]) / 2), label, fill=(20, 20, 20), font=small_font)

    draw.text((left + plot / 2 - 45, top + plot + 48), "Clase predicha", fill=(40, 40, 40), font=text_font)
    draw.text((35, top + plot / 2), "Clase real", fill=(40, 40, 40), font=text_font)
    draw.text(
        (left, top + plot + 82),
        "La diagonal indica aciertos. Las celdas rojas fuera de la diagonal muestran confusiones; "
        "se usa escala resaltada para que errores pequenos sean visibles.",
        fill=(80, 80, 80),
        font=small_font,
    )

    x0 = left + plot + 55
    y0 = top
    draw.text((x0, y0), "Principales confusiones", fill=(8, 42, 83), font=text_font)
    for index, (count, real, pred) in enumerate(offdiag[:18], start=1):
        draw.text((x0, y0 + 25 + index * 22), f"{index:02d}. {real} -> {pred}: {count}", fill=(70, 45, 45), font=small_font)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT_PATH)
    print(f"total={total} correct={correct} errors={errors} accuracy={correct / total:.4f}")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
