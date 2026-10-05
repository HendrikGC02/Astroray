"""#1075 -- the first-hit AOV passes (albedo / normal / depth) skip indirect-only objects.

Cycles clears the camera visibility bit of an indirect-only object, and data passes
are written only for camera-visible surfaces (intern/cycles/blender/object.cpp,
Apache-2.0). The CPU AOV first hit used ``bvh->hit`` instead of
``Renderer::hitCameraRay``, so a sphere the beauty pass correctly hides still showed
up in albedo, normal and depth. The GPU twin (wavefront intersect stage re-traces
camera rays past GPRIM_FLAG_INDIRECT_ONLY prims, the guide write sits right after) is
parametrised below and skipped without CUDA.
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

N = 24
WALL_Z = -4.0        # backdrop plane; camera at z = +4 looking down -z, so wall depth = 8
BACKDROP = (0.2, 0.7, 0.2)
SPHERE = (0.9, 0.1, 0.1)


def _gpu_ok():
    return AVAILABLE and astroray.__features__.get("cuda", False) and astroray.Renderer().gpu_available


BACKENDS = [False, pytest.param(True, marks=pytest.mark.skipif(not _gpu_ok(), reason="CUDA GPU not available"))]


def _aovs(use_gpu, indirect):
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_use_gpu(use_gpu)
    if use_gpu:
        r.set_gpu_guide_aovs(True)
    r.set_seed(5)
    r.set_background_color([0.5, 0.5, 0.5])
    wall = r.create_material("lambertian", list(BACKDROP), {})
    ball = r.create_material("lambertian", list(SPHERE), {})
    r.add_triangle([-20, -20, WALL_Z], [20, -20, WALL_Z], [20, 20, WALL_Z], wall)
    r.add_triangle([-20, -20, WALL_Z], [20, 20, WALL_Z], [-20, 20, WALL_Z], wall)
    r.add_sphere([0.0, 0.0, 0.0], 1.0, ball)
    if indirect:
        r.set_object_indirect_only(r.scene_object_count() - 1, True)
    r.setup_camera(look_from=[0, 0, 4], look_at=[0, 0, 0], vup=[0, 1, 0], vfov=20,
                   aspect_ratio=1.0, aperture=0.0, focus_dist=4.0, width=N, height=N)
    r.render(8, 3, None, False)
    alb = np.asarray(r.get_albedo_buffer(), dtype=np.float32).reshape(N, N, 3)
    nrm = np.asarray(r.get_normal_buffer(), dtype=np.float32).reshape(N, N, 3)
    dep = np.asarray(r.get_depth_buffer(), dtype=np.float32).reshape(N, N)
    c = N // 2
    return alb[c, c], nrm[c, c], float(dep[c, c])


@pytest.mark.parametrize("use_gpu", BACKENDS)
def test_visible_sphere_is_in_the_aovs(use_gpu):
    """Scene sanity: without the flag the centre pixel's AOVs are the sphere's (depth ~3)."""
    alb, nrm, dep = _aovs(use_gpu, indirect=False)
    assert dep == pytest.approx(3.0, abs=0.1), dep
    assert alb[0] > alb[1] + 0.3, alb
    assert nrm[2] > 0.9, nrm


@pytest.mark.parametrize("use_gpu", BACKENDS)
def test_indirect_only_sphere_is_absent_from_albedo_normal_depth(use_gpu):
    alb, nrm, dep = _aovs(use_gpu, indirect=True)
    assert dep == pytest.approx(8.0, abs=0.1), f"depth shows the indirect-only sphere: {dep}"
    assert np.allclose(alb, BACKDROP, atol=0.05), f"albedo shows the indirect-only sphere: {alb}"
    assert np.allclose(nrm, [0.0, 0.0, 1.0], atol=0.05), f"normal shows the indirect-only sphere: {nrm}"
