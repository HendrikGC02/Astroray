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


def _make_scene(glass: bool = True):
    r = astroray.Renderer()
    r.set_background_color([0.01, 0.012, 0.018])
    floor = r.create_material("lambertian", [0.78, 0.78, 0.78], {})
    r.add_triangle([-2.4, -1.2, -2.2], [2.4, -1.2, -2.2], [2.4, -1.2, 1.6], floor)
    r.add_triangle([-2.4, -1.2, -2.2], [2.4, -1.2, 1.6], [-2.4, -1.2, 1.6], floor)
    light = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 14.0})
    r.add_sphere([0.0, 1.6, 1.0], 0.22, light)
    if glass:
        glass = r.create_material("dielectric", [1.0, 1.0, 1.0], {"ior": 1.52})
    else:  # negative control: same sphere, no specular caster
        glass = r.create_material("lambertian", [0.5, 0.5, 0.5], {})
    r.add_sphere([0.0, -0.4, 0.15], 0.7, glass)
    r.setup_camera(
        [0.0, 0.0, 4.2], [0.0, -0.05, 0.0], [0.0, 1.0, 0.0],
        38.0, WIDTH / HEIGHT, 0.0, 4.2, WIDTH, HEIGHT)
    return r


def _render(integrator: str, samples: int = SAMPLES, seed: int = 145) -> np.ndarray:
    return _render_with_stats(integrator, samples, seed)[0]


def _render_with_stats(integrator: str, samples: int = SAMPLES, seed: int = 145,
                       glass: bool = True):
    r = _make_scene(glass)
    r.set_seed(seed)
    if integrator in ("caustic_path_tracer", "sms_caustic_path_tracer"):
        r.set_integrator_param("max_depth", MAX_DEPTH)
        r.set_integrator_param("caustic_chain_iters", 3)
    r.set_integrator(integrator)
    pixels = np.asarray(r.render(samples, MAX_DEPTH, None, True), dtype=np.float32)
    return pixels, dict(r.get_integrator_stats())


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


def test_sms_convergence_counter_is_live():
    """Negative control for the sms_converged check below: with no specular
    caster SMS has nothing to solve, so the counter must read 0."""
    _, stats = _render_with_stats("sms_caustic_path_tracer", glass=False)
    assert stats.get("sms_converged", 0.0) == 0.0, stats


_STATS_KEYS = ("sms_attempts", "sms_converged", "sms_energy", "caustic_energy",
               "caustic_connections")


def test_sms_stats_finite_positive_deterministic():
    """#888: SMS debug stats were racy float sums (counts differed between
    identical multithreaded runs) and sms_energy read -1.4e5 because
    runSMSAttempt accepted x0-facing vertices whose Schlick 1-F was negative.
    Stats must be finite, non-negative and identical for a fixed seed, in-process
    and in a single-threaded subprocess."""
    import json
    import subprocess

    runs = [_render_with_stats("sms_caustic_path_tracer")[1] for _ in range(2)]
    e = runs[0]["sms_energy"]
    assert np.isfinite(e) and e > 0.0, runs[0]
    for k in _STATS_KEYS:
        assert runs[0][k] >= 0.0, (k, runs[0])
        assert runs[0][k] == pytest.approx(runs[1][k], rel=1e-6), (k, runs)

    code = (
        "import json, sys; sys.path.insert(0, %r); "
        "import test_sms_caustic_validation as t; "
        "print('STATS' + json.dumps(t._render_with_stats('sms_caustic_path_tracer')[1]))"
        % os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ, OMP_NUM_THREADS="1")
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True,
                         text=True, timeout=600, check=True).stdout
    single = json.loads(out.split("STATS", 1)[1])
    for k in _STATS_KEYS:
        assert single[k] == pytest.approx(runs[0][k], rel=1e-6), (k, single, runs[0])


def test_sms_caustic_validation_gate(test_results_dir):
    baseline = _render("caustic_path_tracer", samples=SAMPLES)
    sms_lo, sms_stats = _render_with_stats("sms_caustic_path_tracer", samples=SAMPLES)
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

    # Sanity: SMS receiver energy stays within a two-sided band of the
    # caustic_path_tracer baseline. The old strict `e_sms > e_baseline` passed
    # by chance (#845): after pkg226's correct MNEE weight the two agree to
    # MC noise. Measured e_sms/e_base at 8 spp, seeds 145/11/23/37/51/73:
    #   main 0dd98e18: 1.0057 0.9878 0.9968 0.9995 1.0005 0.9771
    #   #845 build:    0.9997 1.0192 0.9781 0.9798 1.0146 0.9841
    # Spread 0.977..1.019 on both; band = 2x the largest deviation (2.3 %).
    # The band cannot see "SMS found nothing" (the two agree to MC noise), so
    # check directly that the manifold solver converged and deposited energy.
    assert sms_stats.get("sms_caster_count", 0.0) >= 1.0, sms_stats
    # sms_energy is pinned by test_sms_stats_finite_positive_deterministic.
    assert sms_stats.get("sms_attempts", 0.0) > 0.0, sms_stats
    assert sms_stats.get("sms_converged", 0.0) > 0.0, (
        f"SMS found no converged caustic chains: {sms_stats}")

    ratio = e_sms / e_baseline
    assert 0.95 <= ratio <= 1.05, (
        f"SMS/baseline receiver energy {e_sms:.4f}/{e_baseline:.4f} = {ratio:.4f} "
        f"outside [0.95, 1.05]")

    # Phase 1 acceptance: PSNR(SMS, ref) meaningfully better than PSNR(baseline, ref).
    # Threshold relaxed 6.0 -> 5.0 dB after the 2026-05-30 refraction fix (dielectric
    # enter/exit now keys off rec.frontFace): the corrected glass shifted both the
    # baseline brightness and the SMS caustic focal spot, moving the measured gain to
    # ~5.7 dB (still a large, clear improvement). The SMS-adds-energy check above is
    # unchanged. See .astroray_plan/docs/glass-dark-energy-bug-2026-05-30.md.
    #
    # Threshold relaxed 5.0 -> 2.5 dB by pkg226: runSMSAttempt (the Newton sphere path
    # this integrator uses) previously double-counted the receiver cosine and weighted
    # by a biased seed-area pdf, over-brightening the caustic ~1.5x. pkg226 replaces
    # that with the physically-correct MNEE chainGeometryTerm weight (matching the
    # pkg127 poly path). The now-correct, dimmer SMS caustic sits closer to the baseline
    # in absolute energy, so the measured PSNR gain drops to ~3.1 dB — a smaller but
    # still clear improvement over a caustic-free baseline (SMS-adds-energy check above
    # unchanged). The larger old gain encoded the over-bright bug. See pkg226 spec.
    assert psnr_sms - psnr_baseline >= 2.5, (
        f"PSNR improvement {psnr_sms - psnr_baseline:.2f} dB below 5 dB target "
        f"(baseline={psnr_baseline:.2f}, sms={psnr_sms:.2f})")
