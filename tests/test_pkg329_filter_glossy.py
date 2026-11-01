"""pkg329: Cycles Filter Glossy (scene.cycles.blur_glossy) on CPU and GPU.

Cycles v5.2.0 (Apache-2.0): ``min_ray_pdf`` starts at FLT_MAX (path_state.h:62) and takes the
min of every non-transparent scatter pdf (shade_surface.h:608-612); at the next surface the
glossy microfacet closures shade with alpha = max(alpha, sqrt(1 - min_ray_pdf / blur_glossy) / 2)
when min_ray_pdf < blur_glossy (surface_shader.h:189-213, bsdf_microfacet.h:1095-1101).

Twin tests of that floor rule (each runs on the CPU and the GPU backend):
- the floor is a max on alpha and never exceeds 0.5, so a scene whose glossy closures all have
  alpha >= 0.5 renders bit-identically with Filter Glossy on and off;
- the camera ray is never blurred, so an isolated convex glossy object (no surface seen after
  a scatter) renders bit-identically with Filter Glossy on and off;
- a smooth metal seen from a diffuse floor IS blurred: the floor's reflection of it changes.
Spec: .astroray_plan/packages/pkg329-filter-glossy.md.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from test_issue991_light_path import _render, _renderer  # noqa: E402

BACKENDS = [pytest.param(False, id="cpu"), pytest.param(True, id="gpu", marks=pytest.mark.gpu)]
LUM = np.array([0.2126, 0.7152, 0.0722])


def _scene(use_gpu, blur_glossy, sphere_roughness, floor=True):
    """A metal sphere (Principled metallic 1) on a diffuse floor under a white world, seen
    from above at an angle so the floor around the contact shows the sphere's reflection."""
    r = _renderer(use_gpu)
    r.set_background_color([1.0, 1.0, 1.0])
    r.set_filter_glossy(blur_glossy)
    metal = r.create_material("principled", [0.9, 0.6, 0.3],
                              {"metallic": 1.0, "roughness": sphere_roughness})
    r.add_sphere([0.0, 0.0, 1.0], 1.0, metal)
    if floor:
        ground = r.create_material("principled", [0.8, 0.8, 0.8],
                                   {"roughness": 1.0, "specular_ior_level": 0.0})
        for tri in (([-8, -8, 0], [8, -8, 0], [8, 8, 0]), ([-8, -8, 0], [8, 8, 0], [-8, 8, 0])):
            r.add_triangle(*tri, ground)
    return _render(r, [0.0, -6.0, 3.0], [0.0, 0.0, 0.6], spp=64, depth=6, size=48, vfov=40)


@pytest.mark.parametrize("use_gpu", BACKENDS)
def test_rough_closures_are_never_blurred(use_gpu):
    """alpha = 0.75^2 = 0.5625 >= the largest possible floor (0.5): Filter Glossy is a no-op."""
    off = _scene(use_gpu, 0.0, 0.75)
    on = _scene(use_gpu, 1.0, 0.75)
    np.testing.assert_array_equal(on, off)


@pytest.mark.parametrize("use_gpu", BACKENDS)
def test_camera_ray_is_never_blurred(use_gpu):
    """A lone convex sphere: every surface hit is camera-direct, min_ray_pdf stays FLT_MAX."""
    off = _scene(use_gpu, 0.0, 0.2, floor=False)
    on = _scene(use_gpu, 1.0, 0.2, floor=False)
    np.testing.assert_array_equal(on, off)


@pytest.mark.parametrize("use_gpu", BACKENDS)
def test_smooth_metal_seen_from_diffuse_floor_is_blurred(use_gpu):
    """Floor pixels next to the contact see the sphere through a diffuse bounce: blurring its
    alpha (0.04 -> >= 0.41 after a diffuse bounce, whose pdf is <= 1/pi) changes them."""
    off = _scene(use_gpu, 0.0, 0.2)
    on = _scene(use_gpu, 1.0, 0.2)
    band = (slice(36, 44), slice(14, 34))  # floor in front of the contact
    l_off = float(off[band].reshape(-1, 3).mean(axis=0) @ LUM)
    l_on = float(on[band].reshape(-1, 3).mean(axis=0) @ LUM)
    assert abs(l_on / l_off - 1.0) > 0.01, (l_on, l_off)
