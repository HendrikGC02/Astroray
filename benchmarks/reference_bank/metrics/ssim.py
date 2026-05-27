"""SSIM gate.

Wang, Bovik, Sheikh, Simoncelli 2004 'Image Quality Assessment: From Error
Visibility to Structural Similarity', IEEE TIP 13(4). Reference implementation:
skimage.metrics.structural_similarity.

Mirrors pkg71's clip-to-shared-99.9-percentile preprocessing so isolated firefly
outliers cannot dominate the structural comparison on MC-noisy renders.
"""

from __future__ import annotations

import numpy as np


def compute_ssim(
    actual: np.ndarray,
    reference: np.ndarray,
    *,
    clip_percentile: float = 99.9,
) -> tuple[float, np.ndarray]:
    """Return (SSIM, per-pixel SSIM map).

    Both inputs are float32 HxWx3 linear scene-referred.
    """
    from skimage.metrics import structural_similarity  # lazy import (already in deps)

    if actual.shape != reference.shape:
        raise ValueError(f"shape mismatch: actual {actual.shape} vs reference {reference.shape}")

    lo = 0.0
    hi = float(max(
        np.percentile(actual, clip_percentile),
        np.percentile(reference, clip_percentile),
        1e-6,  # avoid degenerate range on pure-black renders
    ))
    a = np.clip(actual.astype(np.float32), lo, hi)
    b = np.clip(reference.astype(np.float32), lo, hi)

    value, ssim_map = structural_similarity(
        a, b, channel_axis=-1, data_range=hi - lo, full=True
    )
    return float(value), ssim_map.astype(np.float32)
