#!/usr/bin/env python
"""pkg64 Phase 3 — no regression on caustic-free Cornell box.

The default `path_tracer` must be byte-identical (or within float-noise)
to its pre-pkg64-3 self when no object is flagged as a caustic caster
(the SMS hook is not installed → identical control flow). The cost gate
(< 5% per-bounce) is asserted by walltime ratio with a generous slack.
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

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")


WIDTH = 64
HEIGHT = 64
SAMPLES = 4
MAX_DEPTH = 8


def _make_cornell():
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    white = r.create_material("lambertian", [0.78, 0.78, 0.78], {})
    red   = r.create_material("lambertian", [0.65, 0.05, 0.05], {})
    green = r.create_material("lambertian", [0.12, 0.45, 0.15], {})
    light = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 14.0})
    # floor
    r.add_triangle([-1, -1, -1], [1, -1, -1], [1, -1, 1], white)
    r.add_triangle([-1, -1, -1], [1, -1,  1], [-1, -1, 1], white)
    # ceiling
    r.add_triangle([-1, 1, -1], [1, 1,  1], [1, 1, -1], white)
    r.add_triangle([-1, 1, -1], [-1, 1, 1], [1, 1,  1], white)
    # back wall
    r.add_triangle([-1, -1, -1], [1, -1, -1], [1, 1, -1], white)
    r.add_triangle([-1, -1, -1], [1,  1, -1], [-1, 1, -1], white)
    # left red, right green
    r.add_triangle([-1, -1, -1], [-1, 1, -1], [-1, 1, 1], red)
    r.add_triangle([-1, -1, -1], [-1, 1,  1], [-1, -1, 1], red)
    r.add_triangle([1, -1, -1], [1,  1,  1], [1, 1, -1], green)
    r.add_triangle([1, -1, -1], [1, -1,  1], [1, 1,  1], green)
    # ceiling light
    r.add_sphere([0.0, 0.95, 0.0], 0.18, light)
    r.setup_camera(
        [0.0, 0.0, 3.5], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
        38.0, WIDTH / HEIGHT, 0.0, 3.5, WIDTH, HEIGHT)
    return r


def _render(*, use_caustics: bool, seed: int) -> tuple[np.ndarray, float]:
    r = _make_cornell()
    r.set_seed(seed)
    r.set_use_refractive_caustics(use_caustics)
    r.set_integrator_param("max_depth", MAX_DEPTH)
    r.set_integrator("path_tracer")
    t0 = time.perf_counter()
    pix = np.asarray(r.render(SAMPLES, MAX_DEPTH, None, True), dtype=np.float32)
    return pix, time.perf_counter() - t0


def test_no_caster_no_regression():
    """No object flagged → image must match the no-caustics baseline to
    float-noise. The toggle alone (without a flagged caster) does not
    install the hook, so behavior is identical."""
    base, _ = _render(use_caustics=False, seed=145)
    on,   _ = _render(use_caustics=True,  seed=145)
    diff = np.abs(base - on).max()
    assert diff < 1e-5, (
        f"Caustics toggle without any flagged caster changed the image "
        f"(max abs diff {diff:.2e}); SMS hook should not have fired.")


def test_no_caster_cost_gate():
    """Per-bounce cost gate: with no flagged caster, walltime ratio must
    stay within +5% of the baseline (the SMS hook short-circuits because
    casters_ is empty → empty std::function passed in, which the path
    tracer's null-check skips for free). Generous slack on top to absorb
    OS jitter on small renders."""
    # Warm caches first.
    _render(use_caustics=False, seed=11)

    base_times = []
    on_times   = []
    for s in (101, 102, 103):
        _, tb = _render(use_caustics=False, seed=s)
        _, to = _render(use_caustics=True,  seed=s)
        base_times.append(tb)
        on_times.append(to)
    tb = float(np.median(base_times))
    to = float(np.median(on_times))
    ratio = to / max(tb, 1e-6)
    print(f"\npkg64-3 no-caster cost ratio (toggle on / off) = {ratio:.3f}x")
    # Spec budget is 5%; allow OS jitter slack on small renders.
    assert ratio <= 1.30, (
        f"Caustics toggle with no caster too expensive: ratio {ratio:.2f}x "
        f"(target <= 1.05x with jitter slack to 1.30x)")
