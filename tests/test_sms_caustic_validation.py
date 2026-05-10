#!/usr/bin/env python
"""pkg64 Phase 1 — SMS skeleton regression.

Acceptance gate (Phase 1):
  - sms_caustic_path_tracer integrator is registered.
  - On a sphere-on-floor caustic scene, sms_caustic_path_tracer adds
    measurable receiver energy beyond the caustic_path_tracer baseline
    at equal sample count, with PSNR (relative to a high-quality
    reference produced by sms_caustic_path_tracer at high spp) at least
    6 dB better than caustic_path_tracer's PSNR against the same
    reference.

Phase 2 (spectral) and Phase 3 (default-integrator integration) extend
this — they do NOT regress this gate.
"""

from __future__ import annotations

import os
import sys
import time

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()
sys.path.insert(0, os.path.dirname(__file__))

try:
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

from base_helpers import save_image  # noqa: E402

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")


WIDTH = 64
HEIGHT = 64
SAMPLES = 8
MAX_DEPTH = 10


def _make_scene():
    r = astroray.Renderer()
    r.set_background_color([0.01, 0.012, 0.018])
    floor = r.create_material("lambertian", [0.78, 0.78, 0.78], {})
    r.add_triangle([-2.4, -1.2, -2.2], [2.4, -1.2, -2.2], [2.4, -1.2, 1.6], floor)
    r.add_triangle([-2.4, -1.2, -2.2], [2.4, -1.2, 1.6], [-2.4, -1.2, 1.6], floor)
    light = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 14.0})
    r.add_sphere([0.0, 1.6, 1.0], 0.22, light)
    glass = r.create_material("dielectric", [1.0, 1.0, 1.0], {"ior": 1.52})
    r.add_sphere([0.0, -0.4, 0.15], 0.7, glass)
    r.setup_camera(
        [0.0, 0.0, 4.2], [0.0, -0.05, 0.0], [0.0, 1.0, 0.0],
        38.0, WIDTH / HEIGHT, 0.0, 4.2, WIDTH, HEIGHT)
    return r


def _render(integrator: str, samples: int = SAMPLES, seed: int = 145) -> np.ndarray:
    r = _make_scene()
    r.set_seed(seed)
    if integrator in ("caustic_path_tracer", "sms_caustic_path_tracer"):
        r.set_integrator_param("max_depth", MAX_DEPTH)
        r.set_integrator_param("caustic_chain_iters", 3)
    r.set_integrator(integrator)
    pixels = np.asarray(r.render(samples, MAX_DEPTH, None, True), dtype=np.float32)
    return pixels


def _receiver_energy(pixels: np.ndarray) -> float:
    lum = 0.2126 * pixels[..., 0] + 0.7152 * pixels[..., 1] + 0.0722 * pixels[..., 2]
    h, w = lum.shape
    yy, xx = np.mgrid[:h, :w]
    receiver = (xx > w * 0.20) & (xx < w * 0.80) & (yy < h * 0.55) & (yy > h * 0.20)
    return float(np.sum(lum[receiver]))


def _psnr(test: np.ndarray, ref: np.ndarray) -> float:
    diff = (test - ref).astype(np.float64)
    mse = float(np.mean(diff * diff))
    if mse < 1e-12:
        return 99.0
    peak = max(1.0, float(ref.max()))
    return 10.0 * np.log10(peak * peak / mse)


def test_sms_integrator_registered():
    assert "sms_caustic_path_tracer" in astroray.integrator_registry_names()


def test_sms_caustic_validation_gate(test_results_dir):
    baseline = _render("caustic_path_tracer", samples=SAMPLES)
    sms_lo  = _render("sms_caustic_path_tracer", samples=SAMPLES)
    # Reference: same SMS integrator at higher spp. Phase 1 cares about
    # *relative* improvement; we don't compare absolute pixel-perfect.
    sms_hi  = _render("sms_caustic_path_tracer", samples=SAMPLES * 4, seed=911)

    save_image(baseline, os.path.join(test_results_dir, "pkg64_baseline.png"))
    save_image(sms_lo,   os.path.join(test_results_dir, "pkg64_sms_lo.png"))
    save_image(sms_hi,   os.path.join(test_results_dir, "pkg64_sms_reference.png"))

    psnr_baseline = _psnr(baseline, sms_hi)
    psnr_sms      = _psnr(sms_lo,   sms_hi)

    e_baseline = _receiver_energy(baseline)
    e_sms      = _receiver_energy(sms_lo)

    # Sanity: SMS adds energy in the receiver region (it finds caustic
    # paths the baseline missed).
    assert e_sms > e_baseline, (
        f"SMS receiver energy {e_sms:.4f} should exceed baseline {e_baseline:.4f}")

    # Phase 1 acceptance: PSNR(SMS, ref) at least 6 dB better than
    # PSNR(baseline, ref) — i.e. SMS converges to the reference faster.
    assert psnr_sms - psnr_baseline >= 6.0, (
        f"PSNR improvement {psnr_sms - psnr_baseline:.2f} dB below 6 dB target "
        f"(baseline={psnr_baseline:.2f}, sms={psnr_sms:.2f})")
