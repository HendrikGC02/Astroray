#!/usr/bin/env python
"""pkg-integrator-float-param — float route for integrator params.

`set_integrator_param` stores an int, and `ParamDict::get_<T>` matches the exact
variant type, so float-valued integrator params previously had no route from
Python (light_tracer_caustic's `caustic_boost` was an int x 0.1 hack). This adds
`set_integrator_param_float` + `ParamDict::getNumber` (reads int OR float as
float) and wires `caustic_boost` to it.

The decisive test that the value is honored as a FLOAT (not truncated to int):
a fractional boost in (0,1) produces a caustic; if it were truncated to int 0 the
caustic would be absent (black). Brightness also scales with the float magnitude,
and the int route still works (back-compat via getNumber).

CPU-only; deterministic; runs on CI.
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


def _prism_caustic_signal(boost, route_float):
    """Render the prism scene with the given caustic_boost (via the float or int
    route) and return the total floor caustic luminance (background is black, the
    floor is unlit except by the baked caustic, so the image-sum tracks the
    caustic energy). Uses a reduced photon count + samples for speed."""
    spec = importlib.util.spec_from_file_location("_prism_fp", _SCENE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    r = mod.make_scene(astroray)
    r.set_seed(mod.SEED)
    r.set_integrator_param("photon_count", 500000)
    if route_float:
        r.set_integrator_param_float("caustic_boost", float(boost))
    else:
        r.set_integrator_param("caustic_boost", int(round(boost)))
    img = np.asarray(r.render(16, mod.MAX_DEPTH, None, True), dtype=np.float32)
    if img.ndim == 1:
        img = img.reshape(mod.HEIGHT, mod.WIDTH, 3)
    lum = 0.2126 * img[:, :, 0] + 0.7152 * img[:, :, 1] + 0.0722 * img[:, :, 2]
    return float(lum.sum())


@pytest.mark.skipif(not os.path.exists(_SCENE), reason="prism scene not present")
def test_integrator_float_param_route():
    if not hasattr(astroray.Renderer(), "set_integrator_param_float"):
        pytest.skip("build lacks set_integrator_param_float")
    if not hasattr(astroray.Renderer(), "add_sun_light_dedicated"):
        pytest.skip("build lacks add_sun_light_dedicated")

    base = _prism_caustic_signal(0.0, route_float=True)   # no caustic (scale 0)
    quarter = _prism_caustic_signal(0.25, route_float=True)
    half = _prism_caustic_signal(0.5, route_float=True)
    int_one = _prism_caustic_signal(1.0, route_float=False)  # int route -> getNumber

    # A fractional float boost MUST produce a caustic — proving the value is honored
    # as a float, not truncated to int 0 (which would leave the floor black).
    assert quarter > base * 1.1 + 1.0, \
        f"float boost 0.25 produced no caustic (truncated to int?): {quarter:.1f} vs base {base:.1f}"
    # Brightness scales with the float magnitude.
    assert half > quarter * 1.15, \
        f"float boost does not scale brightness: half {half:.1f} <= 1.15 * quarter {quarter:.1f}"
    # The int route still works (back-compat: getNumber reads int as float).
    assert int_one > base * 1.1 + 1.0, \
        f"int route regressed (no caustic): {int_one:.1f} vs base {base:.1f}"
