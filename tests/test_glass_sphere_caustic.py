#!/usr/bin/env python
"""pkg110 acceptance — glass-sphere focused caustic (general BSDF photon loop).

A clear glass SPHERE (a NON-triangle caustic caster the old hard-coded 2-face
prism path could not handle) focuses a collimated sun into a concentrated caustic
on the floor, rendered by the general deterministic refraction loop in
`light_tracer_caustic` (pkg110). Asserts the caustic is (1) PRESENT (a bright
spot) and (2) FOCUSED (peak >> lit-floor median) — the concentration is what
distinguishes a real refractive caustic from flat direct lighting, and proves the
general loop refracts enter->exit correctly through an arbitrary solid.

CPU-only; deterministic (fixed photon seed); runs on CI.
"""

from __future__ import annotations

import importlib.util
import os
import sys

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

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCENE = os.path.join(_REPO, "benchmarks", "reference_bank", "scenes",
                      "glass-sphere-caustic", "scene.py")


@pytest.mark.skipif(not os.path.exists(_SCENE), reason="glass-sphere scene not present")
def test_glass_sphere_focused_caustic():
    if not hasattr(astroray.Renderer(), "add_sun_light_dedicated"):
        pytest.skip("build lacks add_sun_light_dedicated")
    spec = importlib.util.spec_from_file_location("_gs_scene", _SCENE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    r = mod.make_scene(astroray)
    r.set_seed(mod.SEED)
    img = np.asarray(r.render(mod.SAMPLES, mod.MAX_DEPTH, None, True), dtype=np.float32)
    if img.ndim == 1:
        img = img.reshape(mod.HEIGHT, mod.WIDTH, 3)

    lum = 0.2126 * img[:, :, 0] + 0.7152 * img[:, :, 1] + 0.0722 * img[:, :, 2]
    peak = float(lum.max())
    lit = lum[lum > 0.002]                      # exclude the black background
    med = float(np.median(lit)) if lit.size else 0.0
    conc = peak / max(med, 1e-4)
    bright_frac = float((lum > 0.3).mean())     # the caustic is a small bright spot

    # Measured (deterministic, RTX): peak 0.673, conc 41.4, bright_frac 1e-4.
    # Conservative gates with wide margin (the render is deterministic, so stable).
    assert peak >= 0.25, f"no bright caustic spot (peak luminance {peak:.3f})"
    assert conc >= 8.0, f"caustic not focused (peak/lit-median {conc:.1f} < 8)"
    assert bright_frac < 0.05, \
        f"bright region too large to be a focused caustic ({bright_frac:.3f})"
