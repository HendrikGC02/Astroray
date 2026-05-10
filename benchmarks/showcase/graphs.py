"""pkg74 showcase — matplotlib graph helpers.

Phase 1: log-log RMSE-vs-SPP convergence curve. Phase 2 will add a
per-integrator timing bar chart and a memory profile.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np


def rmse(image: np.ndarray, reference: np.ndarray) -> float:
    """Pixel-wise RMSE between two HxWx3 float arrays."""
    diff = (image.astype(np.float64) - reference.astype(np.float64))
    return float(math.sqrt(float(np.mean(diff * diff))))


def save_convergence_curve(spp_values: list[int],
                           rmse_values: list[float],
                           output_path: Path,
                           scene_name: str) -> Path:
    """Log-log RMSE vs SPP, ground truth = highest SPP in this run."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    safe = [max(v, 1e-12) for v in rmse_values]

    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.loglog(spp_values, safe, marker="o", linewidth=2, markersize=6,
              color="#3b82f6", label="RMSE")
    ax.set_xlabel("Samples per pixel (log)")
    ax.set_ylabel("RMSE vs in-run reference (log)")
    ax.set_title(f"Convergence — {scene_name}")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(loc="upper right", frameon=False)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=140)
    plt.close(fig)
    return output_path
