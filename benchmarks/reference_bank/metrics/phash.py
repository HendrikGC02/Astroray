"""Perceptual hash (pHash) distance gate.

DCT-based 64-bit perceptual hash per Goyal et al. 2017, also matching the
`imagehash.phash` implementation (BSD-2-Clause). We implement directly via
scipy.fft.dct to avoid adding `imagehash` as a dependency.

Algorithm (per pHash standard):
  1. Convert to grayscale (BT.709 luminance).
  2. Resize to 32x32.
  3. 2D DCT-II.
  4. Take the top-left 8x8 block (low-frequency content).
  5. Compute median, excluding the DC term.
  6. Hash bit i = (block[i] > median).
  7. Distance = Hamming distance between two 64-bit hashes.

Gate threshold is typically Hamming ≤ 8 (loose) or ≤ 4 (tight).
"""

from __future__ import annotations

import numpy as np
from scipy.fft import dct


_BT709 = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def _to_gray(img: np.ndarray) -> np.ndarray:
    """RGB float32 HxWx3 -> grayscale float32 HxW (BT.709 luma)."""
    return (img @ _BT709).astype(np.float32)


def _resize_box(gray: np.ndarray, size: int) -> np.ndarray:
    """Simple box-resize via average pooling. Adequate for pHash low-frequency hash."""
    h, w = gray.shape
    if h == size and w == size:
        return gray
    # Nearest-neighbor index expansion + mean; for non-divisible sizes we
    # use float index math and average the contributing source pixels.
    ys = np.linspace(0, h, size + 1).astype(int)
    xs = np.linspace(0, w, size + 1).astype(int)
    out = np.empty((size, size), dtype=np.float32)
    for i in range(size):
        for j in range(size):
            patch = gray[ys[i]:max(ys[i] + 1, ys[i + 1]), xs[j]:max(xs[j] + 1, xs[j + 1])]
            out[i, j] = patch.mean() if patch.size else 0.0
    return out


def _phash_bits(img: np.ndarray, hash_size: int = 8, highfreq_factor: int = 4) -> np.ndarray:
    """Return a 64-element bool array (the pHash bit string)."""
    side = hash_size * highfreq_factor
    gray = _to_gray(img)
    resized = _resize_box(gray, side)
    coeffs = dct(dct(resized, axis=0, norm="ortho"), axis=1, norm="ortho")
    low = coeffs[:hash_size, :hash_size]
    # Exclude DC term from median to keep hash sensitive to high-magnitude AC.
    flat = low.flatten()
    median = np.median(flat[1:])
    return (low > median).flatten()


def compute_phash_distance(actual: np.ndarray, reference: np.ndarray) -> tuple[int, dict]:
    """Return (Hamming distance, debug dict)."""
    a_bits = _phash_bits(actual)
    r_bits = _phash_bits(reference)
    distance = int(np.count_nonzero(a_bits != r_bits))
    return distance, {
        "actual_hash_hex": "".join(f"{int(''.join('1' if b else '0' for b in a_bits[i:i+4]), 2):x}" for i in range(0, 64, 4)),
        "reference_hash_hex": "".join(f"{int(''.join('1' if b else '0' for b in r_bits[i:i+4]), 2):x}" for i in range(0, 64, 4)),
    }
