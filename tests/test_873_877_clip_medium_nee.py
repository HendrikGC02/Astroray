"""#873 primary-ray camera clip on the GPU wavefront; #877 medium NEE vs set_light_nee.

#873: clip_start/clip_end bound the CAMERA ray only, as view-axis depths (Cycles
kernel/camera/camera.h: nearclip and cliplength scaled by 1/dot(D, forward); CPU
raytracer.h bounce-0 tMin/tMax). Scene, camera at z=5 looking -z, clip 2..10:
  red   full-view quad at depth 1   (before clip_start  -> hidden)
  green centre quad    at depth 5   (inside             -> visible)
  blue  full-view quad at depth 9.5 (inside on the view axis; its corner ray
        length 9.5/cos(24.9 deg) = 10.7 > 10, so along-ray clipping would drop
        the corners -> they must stay blue)
  white full-view quad at depth 11  (beyond clip_end    -> hidden)

#877: with set_light_nee(False) medium scattering still sampled lights while the
lamp hit took w_B = 1, double-counting (~2x). NEE on and off are two unbiased
estimators of one image, so their means must agree (pkg265 gate shape).
Adaptive sampling off (its stop rule biases on/off comparisons), linear output.
"""
import math

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

astroray = pytest.importorskip("astroray")


def _renderer(gpu):
    r = astroray.Renderer()
    if gpu:
        try:
            r.set_use_gpu(True)
        except Exception as e:  # noqa: BLE001 - CPU-only build
            pytest.skip("GPU unavailable: %s" % e)
        if not getattr(r, "gpu_available", False):
            pytest.skip("gpu_available is False")
    elif hasattr(r, "set_use_gpu"):
        r.set_use_gpu(False)
    r.set_integrator("path_tracer")
    r.set_adaptive_sampling(False)
    return r


def _quad(r, z, h, mat):
    r.add_triangle([-h, -h, z], [h, -h, z], [h, h, z], mat)
    r.add_triangle([-h, -h, z], [h, h, z], [-h, h, z], mat)


# --------------------------------------------------------------------------- #
# #873
# --------------------------------------------------------------------------- #
_RES = 48


def _clip_render(gpu, clip=True):
    r = _renderer(gpu)
    r.set_background_color([0.0, 0.0, 0.0])

    def light(c):
        return r.create_material("light", c, {"intensity": 1.0})

    _quad(r, 4.0, 2.0, light([1.0, 0.0, 0.0]))    # depth 1
    _quad(r, 0.0, 0.5, light([0.0, 1.0, 0.0]))    # depth 5
    _quad(r, -4.5, 6.0, light([0.0, 0.0, 1.0]))   # depth 9.5
    _quad(r, -6.0, 8.0, light([1.0, 1.0, 1.0]))   # depth 11
    kw = dict(look_from=[0, 0, 5], look_at=[0, 0, 0], vup=[0, 1, 0], vfov=40.0,
              aspect_ratio=1.0, aperture=0.0, focus_dist=5.0,
              width=_RES, height=_RES)
    if clip:
        kw.update(clip_near=2.0, clip_far=10.0)
    r.setup_camera(**kw)
    r.set_seed(873)
    img = np.asarray(r.render(4, 2, None, False), dtype=np.float32)
    return img.reshape(_RES, _RES, 3)


def _regions(img):
    c = _RES // 2
    centre = img[c - 3:c + 3, c - 3:c + 3].reshape(-1, 3).mean(axis=0)
    corners = np.concatenate([img[:4, :4], img[:4, -4:], img[-4:, :4], img[-4:, -4:]])
    return centre, corners.reshape(-1, 3).mean(axis=0)


def _assert_clip(img, tag):
    centre, corner = _regions(img)
    # centre: green only (red before clip_start removed)
    assert centre[1] > 0.5 and centre[0] < 0.15 and centre[2] < 0.15, (tag, centre)
    # (~0.05 R/G in the corners is light the other emitters bounce off blue)
    # corners: blue at depth 9.5 kept (view-axis), white at depth 11 removed
    assert corner[2] > 0.5 and corner[0] < 0.15 and corner[1] < 0.15, (tag, corner)


@pytest.mark.cpu
def test_873_primary_clip_cpu():
    img = _clip_render(gpu=False)
    _assert_clip(img, "cpu")
    # control: without clip args the red depth-1 quad covers everything
    centre, corner = _regions(_clip_render(gpu=False, clip=False))
    assert centre[0] > 0.5 and corner[0] > 0.5


@pytest.mark.gpu
def test_873_primary_clip_gpu():
    img = _clip_render(gpu=True)
    _assert_clip(img, "gpu")
    np.testing.assert_allclose(_regions(img), _regions(_clip_render(gpu=False)),
                               atol=0.02)


# --------------------------------------------------------------------------- #
# #877
# --------------------------------------------------------------------------- #
_SEEDS = (3, 5, 7, 9, 11, 13)
_SIGMA_MULT = 3.0
_REL_FLOOR = 0.03


def _medium_render(gpu, kind, nee, seed, spp=128, res=48):
    r = _renderer(gpu)
    r.set_background_color([0.0, 0.0, 0.0])
    if kind == "box":
        r.add_homogeneous_medium([-1, -1, -1], [1, 1, 1], 1.0, [0.8, 0.8, 0.8])
    else:
        r.set_world_volume(0.15, [1.0, 1.0, 1.0], 0.0, 0.8)
    r.add_area_light_dedicated([0.0, 3.0, 0.0], [1, 0, 0], [0, 0, 1], 4.0, 4.0,
                               "RECTANGLE", {"mode": "rgb", "color": [1, 1, 1]}, 10.0)
    r.set_light_nee(nee)
    r.setup_camera([0, 0, 5], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 5.0, res, res)
    r.set_seed(seed)
    img = np.asarray(r.render(spp, 16, None, False), dtype=np.float32)
    img = img.reshape(res, res, 3)
    lo, hi = res // 4, 3 * res // 4
    return float(img[lo:hi, lo:hi].mean())


def _stats(v):
    a = np.asarray(v, dtype=np.float64)
    return float(a.mean()), float(a.std(ddof=1) / math.sqrt(a.size))


def _assert_nee_invariant(gpu, kind):
    on_v = [_medium_render(gpu, kind, True, s) for s in _SEEDS]
    off_v = [_medium_render(gpu, kind, False, s) for s in _SEEDS]
    assert on_v != off_v, "set_light_nee(False) did not change the estimator"
    on, s_on = _stats(on_v)
    off, s_off = _stats(off_v)
    assert on > 0.0
    tol = max(_SIGMA_MULT * math.hypot(s_on, s_off), _REL_FLOOR * on)
    assert abs(on - off) <= tol, (
        f"{'gpu' if gpu else 'cpu'} {kind}: NEE-on {on:.5f}+-{s_on:.5f} vs "
        f"NEE-off {off:.5f}+-{s_off:.5f} ({100 * (off / on - 1):+.1f}%), tol {tol:.5f}")
    return on, off


@pytest.mark.cpu
@pytest.mark.parametrize("kind", ["box", "fog"])
def test_877_medium_nee_flag_cpu(kind):
    _assert_nee_invariant(False, kind)


@pytest.mark.gpu
@pytest.mark.parametrize("kind", ["box", "fog"])
def test_877_medium_nee_flag_gpu(kind):
    _assert_nee_invariant(True, kind)
