"""CIEDE2000 perceptual color difference.

Sharma, Wu, Dalal 2005 'The CIEDE2000 Color-Difference Formula: Implementation
Notes, Supplementary Test Data, and Mathematical Observations', Color Research
& Application 30(1). DOI 10.1002/col.20070.

Reference implementation cross-checked against the colour-science/colour library
(BSD-3-Clause). This file is a clean reimplementation following Sharma 2005
equations directly so we have a single-file dependency-light source of truth.

The Sharma 2005 paper provides 34 supplementary test pairs with expected ΔE
values; test_metrics.py exercises a sample of these for regression coverage.

Inputs are linear scene-referred RGB (float32, HxWx3). Pipeline:
  linear RGB -> sRGB display (gamma 2.2 approx) -> XYZ (sRGB D65) -> Lab (D65) -> ΔE2000.
"""

from __future__ import annotations

import numpy as np


# sRGB → XYZ matrix (D65), per IEC 61966-2-1.
_M_RGB_TO_XYZ = np.array(
    [
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ],
    dtype=np.float64,
)

# D65 reference white in XYZ.
_XYZ_D65 = np.array([0.95047, 1.00000, 1.08883], dtype=np.float64)


def _linear_to_srgb_display(linear: np.ndarray) -> np.ndarray:
    """Clip + gamma-encode linear scene-referred to display-referred (sRGB)."""
    x = np.clip(linear, 0.0, 1.0)
    # sRGB piecewise transfer: linear segment near 0, gamma elsewhere.
    out = np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(np.maximum(x, 1e-6), 1 / 2.4) - 0.055)
    return np.clip(out, 0.0, 1.0)


def _srgb_display_to_xyz(srgb: np.ndarray) -> np.ndarray:
    """Display-referred sRGB → linear sRGB → XYZ."""
    s = srgb.astype(np.float64)
    # Inverse sRGB transfer to get back to linear before XYZ matrix.
    linear = np.where(s <= 0.04045, s / 12.92, np.power((s + 0.055) / 1.055, 2.4))
    return linear @ _M_RGB_TO_XYZ.T


def _xyz_to_lab(xyz: np.ndarray) -> np.ndarray:
    """XYZ (D65) → CIELAB."""
    x = xyz / _XYZ_D65
    delta = 6.0 / 29.0
    f = np.where(x > delta ** 3, np.cbrt(x), x / (3 * delta ** 2) + 4.0 / 29.0)
    L = 116.0 * f[..., 1] - 16.0
    a = 500.0 * (f[..., 0] - f[..., 1])
    b = 200.0 * (f[..., 1] - f[..., 2])
    return np.stack([L, a, b], axis=-1)


def _delta_e_2000_lab(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    """Per-pixel ΔE2000, following Sharma 2005 equations (1)–(20).

    Vectorised; lab1/lab2 are float64 HxWx3.
    """
    L1, a1, b1 = lab1[..., 0], lab1[..., 1], lab1[..., 2]
    L2, a2, b2 = lab2[..., 0], lab2[..., 1], lab2[..., 2]

    C1 = np.sqrt(a1 * a1 + b1 * b1)
    C2 = np.sqrt(a2 * a2 + b2 * b2)
    C_bar = 0.5 * (C1 + C2)

    G = 0.5 * (1.0 - np.sqrt(C_bar ** 7 / (C_bar ** 7 + 25.0 ** 7 + 1e-30)))
    a1p = (1.0 + G) * a1
    a2p = (1.0 + G) * a2

    C1p = np.sqrt(a1p * a1p + b1 * b1)
    C2p = np.sqrt(a2p * a2p + b2 * b2)

    def _atan2_deg(y, x):
        h = np.degrees(np.arctan2(y, x))
        return np.where(h < 0, h + 360.0, h)

    h1p = np.where((b1 == 0) & (a1p == 0), 0.0, _atan2_deg(b1, a1p))
    h2p = np.where((b2 == 0) & (a2p == 0), 0.0, _atan2_deg(b2, a2p))

    dLp = L2 - L1
    dCp = C2p - C1p

    dhp_raw = h2p - h1p
    abs_dh = np.abs(dhp_raw)
    dhp = np.where(C1p * C2p == 0, 0.0,
                   np.where(abs_dh <= 180.0, dhp_raw,
                            np.where(dhp_raw > 180.0, dhp_raw - 360.0, dhp_raw + 360.0)))
    dHp = 2.0 * np.sqrt(C1p * C2p) * np.sin(np.radians(dhp / 2.0))

    Lp_bar = 0.5 * (L1 + L2)
    Cp_bar = 0.5 * (C1p + C2p)

    hp_sum = h1p + h2p
    hp_bar = np.where(
        C1p * C2p == 0,
        hp_sum,
        np.where(abs_dh <= 180.0, 0.5 * hp_sum,
                 np.where(hp_sum < 360.0, 0.5 * (hp_sum + 360.0),
                          0.5 * (hp_sum - 360.0))),
    )

    T = (
        1.0
        - 0.17 * np.cos(np.radians(hp_bar - 30.0))
        + 0.24 * np.cos(np.radians(2.0 * hp_bar))
        + 0.32 * np.cos(np.radians(3.0 * hp_bar + 6.0))
        - 0.20 * np.cos(np.radians(4.0 * hp_bar - 63.0))
    )

    d_theta = 30.0 * np.exp(-(((hp_bar - 275.0) / 25.0) ** 2))
    R_C = 2.0 * np.sqrt(Cp_bar ** 7 / (Cp_bar ** 7 + 25.0 ** 7 + 1e-30))
    S_L = 1.0 + (0.015 * (Lp_bar - 50.0) ** 2) / np.sqrt(20.0 + (Lp_bar - 50.0) ** 2)
    S_C = 1.0 + 0.045 * Cp_bar
    S_H = 1.0 + 0.015 * Cp_bar * T
    R_T = -np.sin(np.radians(2.0 * d_theta)) * R_C

    kL = kC = kH = 1.0
    term_L = dLp / (kL * S_L)
    term_C = dCp / (kC * S_C)
    term_H = dHp / (kH * S_H)

    return np.sqrt(term_L ** 2 + term_C ** 2 + term_H ** 2 + R_T * term_C * term_H)


def compute_delta_e_2000(
    actual: np.ndarray,
    reference: np.ndarray,
    *,
    mask: np.ndarray | None = None,
) -> tuple[float, np.ndarray]:
    """Return (mean ΔE2000 over mask, per-pixel ΔE map).

    Inputs: float32 HxWx3 linear scene-referred RGB. Optional bool mask HxW
    restricts the mean to a region of interest. ΔE map is always full-image.
    """
    if actual.shape != reference.shape:
        raise ValueError(f"shape mismatch: actual {actual.shape} vs reference {reference.shape}")

    a_srgb = _linear_to_srgb_display(actual.astype(np.float64))
    r_srgb = _linear_to_srgb_display(reference.astype(np.float64))
    a_xyz = _srgb_display_to_xyz(a_srgb)
    r_xyz = _srgb_display_to_xyz(r_srgb)
    a_lab = _xyz_to_lab(a_xyz)
    r_lab = _xyz_to_lab(r_xyz)

    delta_e = _delta_e_2000_lab(a_lab, r_lab)
    if mask is not None:
        mean_val = float(delta_e[mask].mean()) if mask.any() else 0.0
    else:
        mean_val = float(delta_e.mean())
    return mean_val, delta_e.astype(np.float32)
