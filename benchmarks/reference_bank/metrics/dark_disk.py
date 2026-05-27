"""Dark-disk gate: 'is the black-hole shadow present?'

Fraction of pixels in an ROI whose luminance is below a small threshold.
For Schwarzschild + Kerr scenes, the geodesic-trapped photon-sphere boundary
produces a clearly dark region. If GR is mis-wired or the integrator skips
geodesic dispatch, the dark disk vanishes.

Gate semantics: dark_fraction >= threshold ⇒ BH shadow present.
"""

from __future__ import annotations

import numpy as np


_BT709 = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def compute_dark_disk_fraction(
    image: np.ndarray,
    *,
    luminance_threshold: float = 0.02,
    roi: tuple[int, int, int, int] | None = None,
) -> tuple[float, np.ndarray]:
    """Return (fraction of pixels below threshold in ROI, mask)."""
    luma = image.astype(np.float32) @ _BT709
    if roi is not None:
        y0, y1, x0, x1 = roi
        sub = luma[y0:y1, x0:x1]
    else:
        sub = luma
    if sub.size == 0:
        return 0.0, np.zeros_like(luma, dtype=bool)
    mask_sub = sub < luminance_threshold
    fraction = float(mask_sub.sum()) / float(sub.size)
    full_mask = np.zeros_like(luma, dtype=bool)
    if roi is not None:
        full_mask[y0:y1, x0:x1] = mask_sub
    else:
        full_mask = mask_sub
    return fraction, full_mask
