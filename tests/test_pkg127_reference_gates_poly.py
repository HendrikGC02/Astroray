#!/usr/bin/env python
"""pkg127 acceptance — blessed reference-bank gates hold with poly seeding ON.

Renders the blessed `sms-refractive-glass-sphere` scene through the SAME
integrator/spp/seed the reference was blessed with, but with
``sms_specular_poly=1``, and asserts every gate in its gates.toml still passes
(ssim / delta_e_2000 / bright_coverage / phash vs the blessed reference.png).
This is the "caustic-quality gates equal-or-better at equal spp" acceptance
criterion for the deterministic Specular-Polynomials seed stage (pkg127).

Also checks the comparative: poly SSIM is no worse than the stochastic Newton
path at equal spp (deterministic enumeration should match or beat one-seed
Newton). Reuses the reference-bank runner's own gate evaluation so the metrics
are identical to `python -m benchmarks.reference_bank.runner`.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()
sys.path.insert(0, os.path.dirname(__file__))
_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

try:
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

_SCENE = _REPO / "benchmarks" / "reference_bank" / "scenes" / "sms-refractive-glass-sphere"


def _render(poly: bool) -> np.ndarray:
    from benchmarks.reference_bank import runner as rb
    mod = rb._load_scene_module(_SCENE)
    r = mod.make_scene(astroray)
    r.set_seed(mod.SEED)
    r.set_integrator_param("sms_specular_poly", 1 if poly else 0)
    pix = np.asarray(r.render(mod.SAMPLES, mod.MAX_DEPTH, None, True), dtype=np.float32)
    if pix.ndim == 1:
        pix = pix.reshape(mod.HEIGHT, mod.WIDTH, 3)
    return pix


@pytest.mark.skipif(not _SCENE.exists(), reason="glass-sphere reference scene not present")
def test_reference_gates_hold_with_poly():
    from benchmarks.reference_bank import runner as rb
    ref = rb._load_reference(_SCENE)
    _, gates, _ = rb._load_gates(_SCENE)
    pix = _render(poly=True)
    results = [rb._evaluate_gate(g, pix, ref) for g in gates]
    for res in results:
        print(f"  poly gate {res.spec.type:16s} measured={res.measured:.4f} "
              f"thr={res.spec.threshold} dir={res.spec.direction} "
              f"{'PASS' if res.passed else 'FAIL'}")
    failed = [f"{r.spec.type}={r.measured:.4f} (thr {r.spec.direction} {r.spec.threshold})"
              for r in results if not r.passed]
    assert not failed, "poly-on reference gates failed: " + "; ".join(failed)


@pytest.mark.skipif(not _SCENE.exists(), reason="glass-sphere reference scene not present")
def test_poly_ssim_not_worse_than_newton():
    from benchmarks.reference_bank import runner as rb
    from benchmarks.reference_bank.metrics import compute_ssim
    ref = rb._load_reference(_SCENE)
    if ref is None:
        pytest.skip("no blessed reference.png")
    ssim_newton, _ = compute_ssim(_render(poly=False), ref)
    ssim_poly, _ = compute_ssim(_render(poly=True), ref)
    print(f"\npkg127 SSIM vs blessed ref: newton={ssim_newton:.4f} poly={ssim_poly:.4f}")
    # Deterministic enumeration should be equal-or-better; small MC slack.
    assert ssim_poly >= ssim_newton - 0.01, (
        f"poly SSIM {ssim_poly:.4f} regressed vs newton {ssim_newton:.4f}")
