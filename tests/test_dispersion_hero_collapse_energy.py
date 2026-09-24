"""Dispersive glass must transmit the same energy as flat glass (hero collapse).

A dispersive refraction collapses the wavelength quad to the hero lane
(terminateSecondary). pbrt-v4 then divides the hero pdf by N so toXYZ, which
still averages over N lanes, keeps the estimate unbiased. Without that rescale
dispersive (Sellmeier) glass rendered ~4x too dark on CPU and GPU.

Fixture: a BK7 sphere in front of a uniform white emitter vs flat glass with
IOR = BK7 at 550 nm. Over a uniform backdrop the dispersion only moves where
each wavelength lands, not how much arrives, so the transmitted energy must
match. Gate: per-channel mean over 5 seeds within 2 %.
"""

from __future__ import annotations

import math
import os
import sys

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()
sys.path.insert(0, os.path.dirname(__file__))

astroray = pytest.importorskip("astroray")

W = H = 48
SAMPLES = 128
MAX_DEPTH = 8
SEEDS = (11, 23, 37, 51, 73)
TOL = 0.02

# Schott BK7 Sellmeier (include/astroray/optical_presets.h), lambda in um.
_B = (1.03961212, 0.231792344, 1.01046945)
_C = (0.00600069867, 0.0200179144, 103.560653)


def _bk7_ior(lam_nm: float) -> float:
    l2 = (lam_nm * 1e-3) ** 2
    return math.sqrt(1.0 + sum(b * l2 / (l2 - c) for b, c in zip(_B, _C)))


def _render(use_gpu: bool, params: dict, seed: int) -> np.ndarray:
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    white = r.create_material("light", [1, 1, 1], {"intensity": 1.0})
    r.add_triangle([-6, -6, -3], [6, -6, -3], [6, 6, -3], white)
    r.add_triangle([-6, -6, -3], [6, 6, -3], [-6, 6, -3], white)
    r.add_sphere([0, 0, 0], 0.9, r.create_material("dielectric", [1, 1, 1], params))
    # Narrow FOV: every pixel looks through the sphere.
    r.setup_camera([0, 0, 4.0], [0, 0, 0], [0, 1, 0], 12.0, 1.0, 0.0, 4.0, W, H)
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", MAX_DEPTH)
    r.set_adaptive_sampling(False)
    if use_gpu:
        r.set_use_gpu(True)
        r.set_wavelength_range(380.0, 780.0)
        r.set_output_mode("srgb")
    r.set_seed(seed)
    img = np.asarray(r.render(SAMPLES, MAX_DEPTH, None, False), dtype=np.float64)
    return img.reshape(H, W, 3) if img.ndim == 1 else img


def _energy(use_gpu: bool, params: dict) -> np.ndarray:
    return np.mean([_render(use_gpu, params, s).reshape(-1, 3).mean(0) for s in SEEDS], axis=0)


@pytest.mark.parametrize("backend", ["cpu", "gpu"])
def test_dispersive_glass_transmits_flat_glass_energy(backend):
    use_gpu = backend == "gpu"
    if use_gpu and not (astroray.__features__.get("cuda", False)
                        and astroray.Renderer().gpu_available):
        pytest.skip("CUDA GPU not available")
    flat = _energy(use_gpu, {"ior": _bk7_ior(550.0)})
    disp = _energy(use_gpu, {"sellmeier_preset": "bk7"})
    ratio = disp / np.maximum(flat, 1e-8)
    print(f"\n[{backend}] flat={np.round(flat, 4)} bk7={np.round(disp, 4)} "
          f"bk7/flat={np.round(ratio, 4)}")
    assert flat.min() > 0.05, f"fixture too dark: flat={flat}"
    for c, ch in enumerate("RGB"):
        assert abs(ratio[c] - 1.0) <= TOL, (
            f"{backend} ch {ch}: dispersive/flat energy {ratio[c]:.4f} outside 1+-{TOL} "
            f"(hero-collapse pdf rescale missing or doubled?)")
