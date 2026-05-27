"""Hue-spread gate: 'is the rainbow present?'

Computes the circular variance of hue in a thresholded bright region.
A monochromatic bright band has near-zero hue spread; a true spectral
dispersion (red→violet) has high hue spread. Reference: Hanbury 2003
'Circular Statistics Applied to Colour Images', Pattern Recognition.

Gate semantics: hue_spread >= threshold ⇒ rainbow present.
Typical threshold: 0.5 for visible dispersion, 0.7 for sharp full spectrum.
Range: 0 (single hue) to 1 (uniform over full circle).
"""

from __future__ import annotations

import numpy as np


def _rgb_to_hue(rgb: np.ndarray) -> np.ndarray:
    """RGB → hue in [0, 2π). Returns NaN where saturation is undefined."""
    r = rgb[..., 0]
    g = rgb[..., 1]
    b = rgb[..., 2]
    mx = np.max(rgb, axis=-1)
    mn = np.min(rgb, axis=-1)
    d = mx - mn

    hue = np.zeros_like(mx)
    mask = d > 1e-6
    # Choose dominant channel for hue branch
    r_dom = mask & (mx == r)
    g_dom = mask & (mx == g) & ~r_dom
    b_dom = mask & (mx == b) & ~r_dom & ~g_dom

    hue[r_dom] = ((g[r_dom] - b[r_dom]) / d[r_dom]) % 6.0
    hue[g_dom] = (b[g_dom] - r[g_dom]) / d[g_dom] + 2.0
    hue[b_dom] = (r[b_dom] - g[b_dom]) / d[b_dom] + 4.0
    hue = hue * (np.pi / 3.0)  # 0..2π
    hue[~mask] = np.nan
    return hue


def _bright_mask(rgb: np.ndarray, luminance_threshold: float, roi: tuple[int, int, int, int] | None) -> np.ndarray:
    """Bool mask of pixels above threshold inside optional ROI (y0,y1,x0,x1)."""
    luma = rgb @ np.array([0.2126, 0.7152, 0.0722], dtype=rgb.dtype)
    mask = luma > luminance_threshold
    if roi is not None:
        y0, y1, x0, x1 = roi
        sub = np.zeros_like(mask)
        sub[y0:y1, x0:x1] = True
        mask = mask & sub
    return mask


def compute_hue_spread(
    image: np.ndarray,
    *,
    luminance_threshold: float = 0.05,
    roi: tuple[int, int, int, int] | None = None,
    saturation_floor: float = 0.05,
) -> tuple[float, np.ndarray]:
    """Return (circular variance of hue over bright/saturated pixels in ROI, mask).

    Circular variance = 1 - |mean(exp(i*hue))|; range [0, 1].
    """
    rgb = np.clip(image.astype(np.float32), 0.0, None)
    # Normalize to [0,1] for hue extraction (preserve relative chroma).
    mx = rgb.max()
    if mx > 0:
        rgb_n = rgb / mx
    else:
        return 0.0, np.zeros(image.shape[:2], dtype=bool)

    bright = _bright_mask(rgb, luminance_threshold, roi)
    # Saturation floor: drop near-gray pixels (their hue is undefined and ruins the statistic).
    sat = (rgb_n.max(axis=-1) - rgb_n.min(axis=-1))
    sel = bright & (sat > saturation_floor)
    if sel.sum() < 4:
        return 0.0, sel

    hue = _rgb_to_hue(rgb_n)
    h = hue[sel]
    h = h[~np.isnan(h)]
    if h.size < 4:
        return 0.0, sel

    z = np.exp(1j * h)
    r_bar = float(np.abs(z.mean()))
    return float(1.0 - r_bar), sel
