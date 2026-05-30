#!/usr/bin/env python
"""pkg106 acceptance — triangulated prism rainbow caustic (forward light-tracer).

Renders benchmarks/reference_bank/scenes/prism-bk7-collimated (the equilateral
BK7 prism + collimated sun + floor, light_tracer_caustic integrator) and asserts
the pkg106 acceptance:
  - hue_spread >= 0.7 in the rainbow ROI (full red->violet dispersion), AND
  - bright_coverage >= 0.5 in that ROI (a CONTINUOUS band, not salt-and-pepper —
    chromatic noise also scores high hue_spread, so this is the discriminator).

CPU-only (forward light-tracer); runs on CI. The render is deterministic (fixed
photon seed + baked caustic grid), so the gate is stable.
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
                      "prism-bk7-collimated", "scene.py")
_ROI = (150, 390, 125, 322)  # band ROI (y0,y1,x0,x1) in the 512x512 showcase frame


@pytest.mark.skipif(not os.path.exists(_SCENE), reason="prism scene not present")
def test_prism_rainbow_band():
    if not hasattr(astroray.Renderer(), "add_sun_light_dedicated"):
        pytest.skip("build lacks add_sun_light_dedicated")
    spec = importlib.util.spec_from_file_location("_prism_scene", _SCENE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    r = mod.make_scene(astroray)
    r.set_seed(mod.SEED)
    img = np.asarray(r.render(mod.SAMPLES, mod.MAX_DEPTH, None, True), dtype=np.float32)
    if img.ndim == 1:
        img = img.reshape(mod.HEIGHT, mod.WIDTH, 3)

    from benchmarks.reference_bank.metrics.hue_spread import compute_hue_spread
    from benchmarks.reference_bank.metrics.bright_coverage import compute_bright_coverage

    hs, _ = compute_hue_spread(img, luminance_threshold=0.1, roi=_ROI, saturation_floor=0.04)
    bc, _ = compute_bright_coverage(img, luminance_threshold=0.1, roi=_ROI)
    assert hs >= 0.7, f"rainbow hue_spread {hs:.3f} < 0.7 (dispersion collapsed)"
    assert bc >= 0.5, f"band coverage {bc:.3f} < 0.5 (band is patchy / salt-and-pepper, not continuous)"
