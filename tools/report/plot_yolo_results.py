"""
Regenera results.png de una run YOLO a partir de su results.csv.
No necesita el dataset ni ultralytics: solo pandas + matplotlib.

Uso:
    python plot_yolo_results.py <ruta_a_results.csv> [...]
"""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

# Columnas tipicas de YOLO (B = bounding box) y titulos legibles.
PLOTS = [
    ("train/box_loss", "train/box_loss"),
    ("train/cls_loss", "train/cls_loss"),
    ("train/dfl_loss", "train/dfl_loss"),
    ("metrics/precision(B)", "precision"),
    ("metrics/recall(B)", "recall"),
    ("val/box_loss", "val/box_loss"),
    ("val/cls_loss", "val/cls_loss"),
    ("val/dfl_loss", "val/dfl_loss"),
    ("metrics/mAP50(B)", "mAP50"),
    ("metrics/mAP50-95(B)", "mAP50-95"),
]


def plot_one(csv_path):
    csv_path = Path(csv_path)
    df = pd.read_csv(csv_path)
    df.columns = [c.strip() for c in df.columns]

    cols = [(c, t) for c, t in PLOTS if c in df.columns]
    ncols = 5
    nrows = (len(cols) + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(4 * ncols, 3.2 * nrows))
    axes = axes.ravel()

    x = df["epoch"] if "epoch" in df.columns else range(len(df))
    for ax, (col, title) in zip(axes, cols):
        ax.plot(x, df[col], marker=".", linewidth=1.5)
        ax.set_title(title)
        ax.set_xlabel("epoch")
        ax.grid(alpha=0.3)
    for ax in axes[len(cols):]:
        ax.axis("off")

    fig.suptitle(csv_path.parent.name, fontsize=14)
    fig.tight_layout()
    out = csv_path.parent / "results.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"OK -> {out}  ({len(df)} epocas)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("uso: python plot_yolo_results.py <results.csv> [...]")
        sys.exit(1)
    for p in sys.argv[1:]:
        plot_one(p)
