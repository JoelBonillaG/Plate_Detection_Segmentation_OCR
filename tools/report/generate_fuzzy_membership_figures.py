from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORT_PICTURES = (
    PROJECT_ROOT.parent
    / "Informe"
    / "Informe_Proyecto_Final"
    / "picture"
    / "Metricas"
)

EXCESO = {
    "Sin exceso": ("trap", (0, 0, 2, 5), (31, 178, 84)),
    "Leve": ("tri", (2, 8, 14), (125, 190, 30)),
    "Moderado": ("tri", (8, 14, 20), (245, 158, 11)),
    "Grave": ("tri", (14, 20, 26), (230, 93, 25)),
    "Critico": ("trap", (20, 26, 30, 30), (220, 38, 38)),
}

REINCI = {
    "Limpio": ("trap", (0, 0, 1, 2.5), (31, 178, 84)),
    "Bajo": ("tri", (0, 2.5, 5), (125, 190, 30)),
    "Moderado": ("tri", (2.5, 5, 7.5), (245, 158, 11)),
    "Alto": ("tri", (5, 7.5, 10), (230, 93, 25)),
    "Cronico": ("trap", (7.5, 9, 10, 10), (220, 38, 38)),
}

SEVERIDAD = {
    "Sin accion": ("trap", (0, 0, 5, 15), (31, 178, 84)),
    "Advertencia": ("tri", (10, 20, 30), (125, 190, 30)),
    "Susp. baja": ("tri", (25, 40, 55), (245, 158, 11)),
    "Susp. media": ("tri", (50, 65, 80), (230, 126, 34)),
    "Susp. alta": ("tri", (75, 85, 95), (230, 93, 25)),
    "Susp. critica": ("trap", (90, 96, 100, 100), (220, 38, 38)),
}


def trimf(x: float, a: float, b: float, c: float) -> float:
    if x <= a or x >= c:
        return 0.0
    if x <= b:
        return (x - a) / (b - a) if b != a else 1.0
    return (c - x) / (c - b) if c != b else 1.0


def trapmf(x: float, a: float, b: float, c: float, d: float) -> float:
    if x < a or x > d:
        return 0.0
    if b <= x <= c:
        return 1.0
    if x < b:
        return (x - a) / (b - a) if b != a else 1.0
    return (d - x) / (d - c) if d != c else 1.0


def eval_mf(kind: str, x: float, params: tuple[float, ...]) -> float:
    return trimf(x, *params) if kind == "tri" else trapmf(x, *params)


def get_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    names = ["arialbd.ttf", "arial.ttf"] if bold else ["arial.ttf"]
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def draw_membership(
    title: str,
    subtitle: str,
    universe: tuple[float, float],
    sets: dict[str, tuple[str, tuple[float, ...], tuple[int, int, int]]],
    output: Path,
    current_value: float | None = None,
) -> None:
    width, height = 1050, 430
    left, top, right, bottom = 72, 92, 35, 72
    plot_w = width - left - right
    plot_h = height - top - bottom
    base_y = top + plot_h

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title_font = get_font(24, bold=True)
    text_font = get_font(15)
    small_font = get_font(12)

    draw.rounded_rectangle((16, 16, width - 16, height - 16), radius=16, outline=(220, 225, 235), width=2)
    draw.text((left, 28), title, fill=(8, 42, 83), font=title_font)
    draw.text((left, 58), subtitle, fill=(80, 92, 112), font=text_font)

    draw.line((left, base_y, left + plot_w, base_y), fill=(70, 70, 70), width=2)
    draw.line((left, top, left, base_y), fill=(70, 70, 70), width=2)

    min_x, max_x = universe

    def sx(x: float) -> int:
        return left + int((x - min_x) / (max_x - min_x) * plot_w)

    def sy(mu: float) -> int:
        return base_y - int(mu * plot_h)

    for tick in range(0, 6):
        value = min_x + (max_x - min_x) * tick / 5
        x = sx(value)
        draw.line((x, base_y, x, base_y + 5), fill=(70, 70, 70), width=1)
        label = f"{value:g}"
        draw.text((x - 8, base_y + 10), label, fill=(80, 80, 80), font=small_font)

    draw.text((left - 28, top - 5), "1", fill=(80, 80, 80), font=small_font)
    draw.text((left - 28, base_y - 5), "0", fill=(80, 80, 80), font=small_font)

    samples = [min_x + (max_x - min_x) * i / 500 for i in range(501)]
    legend_x = left
    legend_y = height - 42
    for name, (kind, params, color) in sets.items():
        points = [(sx(x), sy(eval_mf(kind, x, params))) for x in samples]
        draw.line(points, fill=color, width=4)
        draw.rectangle((legend_x, legend_y, legend_x + 16, legend_y + 16), fill=color)
        draw.text((legend_x + 22, legend_y - 1), name, fill=(45, 45, 45), font=small_font)
        legend_x += 145

    if current_value is not None:
        x = sx(current_value)
        draw.line((x, top, x, base_y), fill=(245, 158, 11), width=3)
        draw.ellipse((x - 7, base_y - 7, x + 7, base_y + 7), fill=(245, 158, 11))
        draw.text((x + 8, top + 5), f"ej. {current_value:g}", fill=(120, 80, 20), font=small_font)

    image.save(output)


def main() -> None:
    REPORT_PICTURES.mkdir(parents=True, exist_ok=True)
    draw_membership(
        "Funciones de pertenencia: exceso de velocidad",
        "Universo [0, 30] km/h; se obtiene como velocidad medida menos limite institucional de 20 km/h.",
        (0, 30),
        EXCESO,
        REPORT_PICTURES / "funciones_pertenencia_exceso_velocidad.png",
        current_value=14,
    )
    draw_membership(
        "Funciones de pertenencia: reincidencia",
        "Universo [0, 10] infracciones previas; se usa como agravante cuando existe exceso de velocidad.",
        (0, 10),
        REINCI,
        REPORT_PICTURES / "funciones_pertenencia_reincidencia.png",
        current_value=2,
    )
    draw_membership(
        "Funciones de pertenencia: severidad",
        "Universo [0, 100]; salida defuzzificada por centroide y convertida a suspension sugerida.",
        (0, 100),
        SEVERIDAD,
        REPORT_PICTURES / "funciones_pertenencia_severidad.png",
        current_value=65,
    )


if __name__ == "__main__":
    main()
