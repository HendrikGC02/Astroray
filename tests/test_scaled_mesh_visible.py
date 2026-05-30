"""Regression: a *scaled* triangle mesh must be visible to rays.

The `Scale` decorator (include/advanced_features.h) transforms a ray into the
mesh's local space by dividing origin and direction by the scale, then builds a
new `Ray`. But the `Ray` ctor normalizes the direction, which discarded the
length change from the scale — so the inner mesh measured `rec.t` in normalized
scaled-space distance (~1/scale too large). The scene BVH then mis-ordered the
scaled mesh behind nearer primitives and a scaled mesh became invisible to rays
(camera AND caustic photons passed straight through it). This bit the
samples/Glass.obj refractive-caustic showcase: the flagged mesh caster deposited
zero photons because no ray ever hit it.

The fix scales the t-bounds in and `rec.t` back out by the scaled-direction
length in `Scale::hit`. This test guards it with a runtime-generated cube so it
needs no large checked-in asset (and exercises the Scale-decorator path because
scale != 1).
"""

from __future__ import annotations

import os
import tempfile

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

# Unit cube (corners at +-1), triangulated. Loaded at scale 10 -> a 20-unit cube
# routed through the Scale decorator.
_CUBE_OBJ = """\
v -1 -1 -1
v  1 -1 -1
v  1  1 -1
v -1  1 -1
v -1 -1  1
v  1 -1  1
v  1  1  1
v -1  1  1
f 1 2 3
f 1 3 4
f 5 7 6
f 5 8 7
f 1 6 2
f 1 5 6
f 2 7 3
f 2 6 7
f 3 8 4
f 3 7 8
f 4 5 1
f 4 8 5
"""


def _render_scaled_cube(scale):
    r = astroray.Renderer()
    r.set_background_color([0.1, 0.2, 0.8])           # blue background
    red = r.create_material("lambertian", [0.9, 0.1, 0.1], {})
    fd, path = tempfile.mkstemp(suffix=".obj")
    with os.fdopen(fd, "w") as f:
        f.write(_CUBE_OBJ)
    try:
        r.add_mesh(path, red, [0.0, 0.0, 0.0], [scale, scale, scale], 0.0)
        r.add_sun_light_dedicated([-0.4, -1.0, -0.5], 0.1,
                                  {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 4.0)
        r.set_integrator("path_tracer")
        d = 2.0 * scale * 3.2
        r.setup_camera([d * 0.5, d * 0.4, d], [0, 0, 0], [0, 1, 0],
                       42.0, 1.0, 0.0, d * 2.0, 80, 80)
        r.set_seed(7)
        img = np.asarray(r.render(8, 6, None, True), dtype=np.float32).reshape(80, 80, 3)
    finally:
        os.unlink(path)
    return img


def test_scaled_mesh_is_visible():
    img = _render_scaled_cube(10.0)
    center = img[28:52, 28:52]                        # central region sits on the cube
    blue_bg = float(center[:, :, 2].mean())
    red_ch = float(center[:, :, 0].mean())
    # If the scaled mesh were invisible the centre would be pure blue background
    # (B ~= 0.8, R ~= 0.1). A visible red cube drops blue and raises red.
    assert blue_bg < 0.55, f"centre still blue ({blue_bg:.3f}) -> scaled mesh invisible to rays"
    assert red_ch > blue_bg, f"centre not reddish (R {red_ch:.3f} <= B {blue_bg:.3f}) -> scaled mesh invisible"
