"""#36 -- indirect-only objects (Blender LayerCollection.indirect_only), CPU.

Cycles clears the camera visibility bit of an indirect-only object
(intern/cycles/blender/object.cpp, Apache-2.0): primary camera rays pass through it,
every other ray -- reflections, GI, shadows, NEE -- still sees it. Gates, on the
CPU renderer (the GPU twin is test_36_indirect_only_gpu.py):

  * absent from the camera view: the red sphere's pixels are the backdrop's colour;
  * present in a mirror reflection: the mirror ball picks up the red;
  * casts a shadow: the backdrop under its shadow is as dark as with a visible sphere.
"""

from __future__ import annotations

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

W = H = 64
SPP = 64


def _px(x, y):
    """Pixel column/row of normalised image coordinates (x right, y up in [-1, 1])."""
    return int(round(W / 2 + x * W / 2)), int(round(H / 2 - y * H / 2))


def build(mode, scene, use_gpu=False):
    """mode: 'visible' | 'indirect' | 'absent'; scene: 'mirror' | 'shadow'."""
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_use_gpu(use_gpu)
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(11)
    r.setup_camera(look_from=[0, 0, 6], look_at=[0, 0, 0], vup=[0, 1, 0], vfov=40,
                   aspect_ratio=1.0, aperture=0.0, focus_dist=6.0, width=W, height=H)
    white = r.create_material("lambertian", [0.8, 0.8, 0.8], {})
    red = r.create_material("lambertian", [0.9, 0.05, 0.05], {})
    light = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 40.0})
    # Backdrop (two triangles) behind everything.
    z = -1.5 if scene == "shadow" else -2.0
    r.add_triangle([-20, -20, z], [20, -20, z], [20, 20, z], white)
    r.add_triangle([-20, -20, z], [20, 20, z], [-20, 20, z], white)
    if scene == "mirror":
        r.add_sphere([0.0, 4.0, 3.0], 0.6, light)  # above the view, lights backdrop + sphere
        mirror = r.create_material("metal", [1.0, 1.0, 1.0], {"roughness": 0.0})
        r.add_sphere([1.8, 0.0, 0.0], 1.0, mirror)
    else:
        r.add_sphere([-4.0, 0.0, 1.5], 0.6, light)  # out of view, left of the sphere
    if mode != "absent":
        r.add_sphere([-1.5, 0.0, 0.0], 1.0, red)
        if mode == "indirect":
            r.set_object_indirect_only(r.scene_object_count() - 1, True)
    return r


def render(r):
    img = np.asarray(r.render(SPP, 4, None, False), dtype=np.float32).reshape(H, W, 3)
    return img


def roi(img, cx, cy, half=2):
    x, y = _px(cx, cy)
    return img[y - half:y + half + 1, x - half:x + half + 1].reshape(-1, 3).mean(axis=0)


def red_fraction(c):
    return float(c[0] / max(1e-9, c.sum()))


def _scene_renders(scene, use_gpu=False):
    return {m: render(build(m, scene, use_gpu)) for m in ("visible", "indirect", "absent")}


# Sphere centre (-1.5, 0, 0) at distance 6 / tan(20 deg): normalised x = -1.5 / (6 tan 20) = -0.687.
SPHERE_UV = (-0.687, 0.0)
# Left limb of the mirror ball (centre x = 1.8 -> 0.824): reflects toward the red sphere.
MIRROR_UV = (0.60, 0.0)
# Backdrop shadow of the sphere (light at (-4,0,1.5)): centre (1.0, 0, -1.5) -> x = 0.37.
SHADOW_UV = (0.37, 0.0)


def test_indirect_only_invisible_to_camera():
    imgs = _scene_renders("mirror")
    vis, ind, ab = (roi(imgs[m], *SPHERE_UV) for m in ("visible", "indirect", "absent"))
    assert red_fraction(vis) > 0.6, f"visible red sphere should be red, got {vis}"
    assert abs(red_fraction(ind) - red_fraction(ab)) < 0.05, (ind, ab)
    assert red_fraction(ind) < 0.45, f"indirect-only sphere visible to the camera: {ind}"


def test_indirect_only_visible_in_mirror_reflection():
    imgs = _scene_renders("mirror")
    vis, ind, ab = (roi(imgs[m], *MIRROR_UV) for m in ("visible", "indirect", "absent"))
    assert red_fraction(vis) > red_fraction(ab) + 0.1, "scene broken: mirror does not show the sphere"
    assert red_fraction(ind) > red_fraction(ab) + 0.1, f"indirect-only sphere missing from the mirror: {ind} vs {ab}"
    assert abs(red_fraction(ind) - red_fraction(vis)) < 0.1, (ind, vis)


def test_indirect_only_casts_shadow():
    imgs = _scene_renders("shadow")
    vis, ind, ab = (roi(imgs[m], *SHADOW_UV, half=3).sum() for m in ("visible", "indirect", "absent"))
    assert vis < 0.6 * ab, f"scene broken: sphere casts no shadow ({vis} vs {ab})"
    assert ind < 0.6 * ab, f"indirect-only sphere casts no shadow ({ind} vs unshadowed {ab})"
    assert abs(ind - vis) < 0.3 * ab, (ind, vis)
