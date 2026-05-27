"""Bright-coverage gate: 'is the caustic / glow present?'

Fraction of pixels in an optional ROI whose luminance exceeds a threshold.
Detects whether a focused-light phenomenon (caustic, ADAF glow, synchrotron
beam) actually deposited energy in the expected region.

Gate semantics: coverage >= threshold ⇒ phenomenon present.
"""

from __future__ import annotations

import numpy as np


_BT709 = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def compute_bright_coverage(
    image: np.ndarray,
    *,
    luminance_threshold: float = 0.5,
    roi: tuple[int, int, int, int] | None = None,
) -> tuple[float, np.ndarray]:
    """Return (fraction of pixels above threshold in ROI, mask).

    ROI is (y0, y1, x0, x1) in pixels; None means full image.
    Coverage range: [0, 1].
    """
    luma = image.astype(np.float32) @ _BT709
    if roi is not None:
        y0, y1, x0, x1 = roi
        sub = luma[y0:y1, x0:x1]
    else:
        sub = luma
    if sub.size == 0:
        return 0.0, np.zeros_like(luma, dtype=bool)
    mask_sub = sub > luminance_threshold
    coverage = float(mask_sub.sum()) / float(sub.size)
    # Project mask back to full-image shape for diagnostics.
    full_mask = np.zeros_like(luma, dtype=bool)
    if roi is not None:
        full_mask[y0:y1, x0:x1] = mask_sub
    else:
        full_mask = mask_sub
    return coverage, full_mask
