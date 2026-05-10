"""pkg74 showcase — labelled contact-sheet composer.

matplotlib + Agg backend, no GUI. PIL is reachable transitively via
matplotlib's PNG writer; we don't import it directly.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np


def save_contact_sheet(tiles: list[tuple[str, np.ndarray]],
                       output_path: Path,
                       columns: int = 4,
                       title: str | None = None) -> Path:
    """Composite a labelled grid of (name, HxWx3 float image) tiles to PNG.

    Failed tiles can be passed as `(name, None)` and will render as a
    placeholder cell labelled FAILED.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    n = max(1, len(tiles))
    rows = max(1, math.ceil(n / columns))
    fig, axes = plt.subplots(rows, columns,
                             figsize=(columns * 2.7, rows * 3.0))
    axes_arr = np.atleast_1d(axes).reshape(rows, columns)
    for ax in axes_arr.flat:
        ax.axis("off")

    for ax, (name, pixels) in zip(axes_arr.flat, tiles):
        if pixels is None:
            ax.set_facecolor("#222")
            ax.text(0.5, 0.5, "FAILED",
                    ha="center", va="center",
                    color="#f55", fontsize=11,
                    transform=ax.transAxes)
        else:
            ax.imshow(np.clip(pixels, 0.0, 1.0))
        ax.set_title(name, fontsize=9)
        ax.axis("off")

    if title:
        fig.suptitle(title, fontsize=12)

    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return output_path


def save_strip(tiles: list[tuple[str, np.ndarray]],
               output_path: Path,
               title: str | None = None) -> Path:
    """1xN labelled strip — used for the convergence-grid contact sheet."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    n = max(1, len(tiles))
    fig, axes = plt.subplots(1, n, figsize=(n * 2.0, 2.6))
    if n == 1:
        axes = [axes]
    for ax, (name, pixels) in zip(axes, tiles):
        if pixels is not None:
            ax.imshow(np.clip(pixels, 0.0, 1.0))
        ax.set_title(name, fontsize=9)
        ax.axis("off")
    if title:
        fig.suptitle(title, fontsize=12)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return output_path
