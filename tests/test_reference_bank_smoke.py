"""Smoke + correctness tests for the visual reference bank harness.

Covers pkg104 acceptance criteria:
  - the runner exits 0 on a passing scene
  - gates correctly distinguish a blessed reference from a perturbed image
  - phenomenon-presence metrics distinguish rainbow vs flat-gray inputs
  - phenomenon-presence metrics distinguish dark-disk vs uniform-bright inputs

Does NOT test correctness of any actual vision scene (those are Phase 2
and require owner-blessed references).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest


_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))


# ----- Metric-level unit tests (no rendering required) -----

def _gradient_rgb(h: int, w: int) -> np.ndarray:
    """Synthetic RGB image: a horizontal hue sweep (visible rainbow analog)."""
    xs = np.linspace(0.0, 1.0, w, dtype=np.float32)
    rgb = np.zeros((h, w, 3), dtype=np.float32)
    # Approximate rainbow: hue=0->2pi mapped to RGB primaries.
    hue = xs * 2 * np.pi
    rgb[..., 0] = np.tile((np.cos(hue) * 0.5 + 0.5), (h, 1))
    rgb[..., 1] = np.tile((np.cos(hue - 2 * np.pi / 3) * 0.5 + 0.5), (h, 1))
    rgb[..., 2] = np.tile((np.cos(hue + 2 * np.pi / 3) * 0.5 + 0.5), (h, 1))
    # Centre band is brightened so the hue_spread bright_mask has pixels to score.
    return rgb


def _flat_gray_rgb(h: int, w: int, level: float = 0.5) -> np.ndarray:
    return np.full((h, w, 3), level, dtype=np.float32)


def _disk_dark_in_bright_rgb(h: int, w: int, dark_radius: float = 0.2) -> np.ndarray:
    """A bright image with a centred dark disk — synthetic BH shadow analog."""
    yy, xx = np.mgrid[:h, :w]
    cy, cx = h / 2, w / 2
    r = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2) / min(h, w)
    mask = r < dark_radius
    img = np.full((h, w, 3), 0.9, dtype=np.float32)
    img[mask] = 0.0
    return img


def test_ssim_self_is_perfect():
    from benchmarks.reference_bank.metrics import compute_ssim
    img = _gradient_rgb(64, 96)
    value, _ = compute_ssim(img, img)
    assert value > 0.999


def test_ssim_drops_on_perturbation():
    from benchmarks.reference_bank.metrics import compute_ssim
    img = _gradient_rgb(64, 96)
    perturbed = np.clip(img + np.random.default_rng(0).normal(0, 0.2, img.shape).astype(np.float32), 0, 1)
    value, _ = compute_ssim(img, perturbed)
    assert value < 0.9


def test_delta_e_self_is_zero():
    from benchmarks.reference_bank.metrics import compute_delta_e_2000
    img = _gradient_rgb(32, 48)
    value, _ = compute_delta_e_2000(img, img)
    assert value < 0.01


def test_delta_e_grows_with_hue_shift():
    from benchmarks.reference_bank.metrics import compute_delta_e_2000
    img = _gradient_rgb(32, 48)
    # Cyclically shift the rainbow — every pixel changes hue.
    shifted = np.roll(img, shift=12, axis=1)
    value, _ = compute_delta_e_2000(img, shifted)
    assert value > 5.0, f"expected significant ΔE on a hue shift, got {value:.3f}"


def test_phash_self_is_zero():
    from benchmarks.reference_bank.metrics import compute_phash_distance
    img = _gradient_rgb(64, 96)
    distance, _ = compute_phash_distance(img, img)
    assert distance == 0


def test_phash_grows_on_layout_change():
    from benchmarks.reference_bank.metrics import compute_phash_distance
    # Use a complex (high-frequency) image so the layout change moves many
    # DCT bits. A smooth gradient has only ~4 dominant AC coefficients and
    # a horizontal flip only sign-flips ~4 bits — that is real signal but
    # below the typical gate threshold (≤8). Use noise to exercise the
    # full hash dynamic range.
    rng = np.random.default_rng(7)
    img = rng.uniform(0.0, 1.0, (64, 96, 3)).astype(np.float32)
    flipped = img[:, ::-1, :].copy()
    distance, _ = compute_phash_distance(img, flipped)
    assert distance >= 8, f"expected pHash >=8 on layout change of noise image, got {distance}"


def test_hue_spread_distinguishes_rainbow_from_gray():
    from benchmarks.reference_bank.metrics import compute_hue_spread
    rainbow = _gradient_rgb(48, 96)
    gray = _flat_gray_rgb(48, 96, level=0.7)
    rainbow_score, _ = compute_hue_spread(rainbow, luminance_threshold=0.1)
    gray_score, _ = compute_hue_spread(gray, luminance_threshold=0.1)
    assert rainbow_score > 0.5, f"rainbow hue_spread {rainbow_score:.3f} should be >0.5"
    assert gray_score < 0.2, f"gray hue_spread {gray_score:.3f} should be <0.2"


def test_dark_disk_distinguishes_bh_from_uniform_bright():
    from benchmarks.reference_bank.metrics import compute_dark_disk_fraction
    bh = _disk_dark_in_bright_rgb(64, 64, dark_radius=0.25)
    bright = _flat_gray_rgb(64, 64, level=0.9)
    bh_score, _ = compute_dark_disk_fraction(bh, luminance_threshold=0.05)
    bright_score, _ = compute_dark_disk_fraction(bright, luminance_threshold=0.05)
    assert bh_score > 0.04, f"BH dark fraction {bh_score:.4f} should be >0.04"
    assert bright_score < 0.005, f"uniform-bright dark fraction {bright_score:.4f} should be ~0"


def test_bright_coverage_distinguishes_caustic_from_flat():
    from benchmarks.reference_bank.metrics import compute_bright_coverage
    caustic_like = np.zeros((64, 64, 3), dtype=np.float32)
    caustic_like[28:36, 28:36] = 0.9  # small bright region
    flat = np.full((64, 64, 3), 0.1, dtype=np.float32)
    c_score, _ = compute_bright_coverage(caustic_like, luminance_threshold=0.5)
    f_score, _ = compute_bright_coverage(flat, luminance_threshold=0.5)
    assert c_score > 0.01
    assert f_score == 0.0


# ----- Runner-level smoke test -----

@pytest.mark.timeout(60)
def test_runner_cornell_mini_passes():
    """Cornell-mini must render and gates must pass against the blessed reference.

    Requires the reference to already exist; the harness should fail loudly if
    it does not, prompting the owner to re-bless on a known-good commit.
    """
    ref = _REPO_ROOT / "benchmarks" / "reference_bank" / "scenes" / "cornell-mini" / "reference.png"
    if not ref.exists():
        pytest.skip(
            "cornell-mini reference not blessed yet; run "
            "`python -m benchmarks.reference_bank.runner --scenes cornell-mini --bless` "
            "on a known-good commit first."
        )
    result = subprocess.run(
        [sys.executable, "-m", "benchmarks.reference_bank.runner",
         "--scenes", "cornell-mini"],
        cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=60,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert result.returncode == 0, (
        f"runner failed (returncode={result.returncode})\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
    assert "PASS" in result.stdout, f"expected PASS in runner output: {result.stdout}"
