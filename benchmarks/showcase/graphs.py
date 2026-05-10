"""pkg74 showcase — matplotlib graph helpers.

Phase 1: log-log RMSE-vs-SPP convergence curve.
Phase 2: per-integrator timing bar chart, plus the convergence-curve
helper now annotates the legend with the fitted log-log slope so a
viewer sees immediately whether the integrator hits the −0.5
Monte-Carlo target (RMSE ∝ 1/√spp).
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
                           scene_name: str,
                           slope: float | None = None) -> Path:
    """Log-log RMSE vs SPP, ground truth = highest SPP in this run.

    `slope` (when provided) is the fitted log-log slope; the legend
    annotates the plot so a viewer can see immediately whether the
    integrator hits the −0.5 Monte-Carlo target.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    safe = [max(v, 1e-12) for v in rmse_values]

    label = "RMSE"
    if slope is not None and slope == slope:  # not-NaN
        label = f"RMSE (log-log slope = {slope:+.3f})"

    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.loglog(spp_values, safe, marker="o", linewidth=2, markersize=6,
              color="#3b82f6", label=label)
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


def save_integrator_timing_bar(integrator_to_ms: dict[str, float],
                               output_path: Path,
                               scene_name: str) -> Path:
    """Horizontal bar chart of total render time per integrator.

    Failed integrators are charted with bars of zero height annotated
    "FAIL" so missing coverage is visible rather than silently dropped.
    Pass a negative `ms` value for an entry to mark it failed.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    items = sorted(integrator_to_ms.items(),
                   key=lambda kv: kv[1] if kv[1] >= 0 else 1e18)
    names = [k for k, _ in items]
    values = [max(v, 0.0) for _, v in items]
    failed = [v < 0 for _, v in items]
    span = max(values) if values else 1.0

    fig, ax = plt.subplots(figsize=(7, max(2.5, 0.45 * len(names) + 1.5)))
    colors = ["#ef4444" if f else "#3b82f6" for f in failed]
    bars = ax.barh(names, values, color=colors)
    for bar, v, f in zip(bars, values, failed):
        text = "FAIL" if f else f"{v:.0f} ms"
        ax.text(bar.get_width() + span * 0.01,
                bar.get_y() + bar.get_height() / 2,
                text, va="center", fontsize=9)
    ax.set_xlabel("Total render time (ms)")
    ax.set_title(f"Integrator comparison — {scene_name}")
    ax.invert_yaxis()
    ax.grid(True, axis="x", alpha=0.3)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=140)
    plt.close(fig)
    return output_path
