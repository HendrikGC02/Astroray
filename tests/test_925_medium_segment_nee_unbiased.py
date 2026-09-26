"""#925: per-segment medium NEE must stay unbiased for HITTABLE (area) lights.

The segment NEE connects from an equiangular/distance-sampled point P with
w_L = p_L^2/(p_L^2+p_phase^2) at P; a phase-sampled continuation from the
free-flight scatter point P' that hits the lamp gets w_B at P'. Both are the
same point function of (x, w), so they sum to 1 everywhere (Cycles
shade_volume.h: light_sample_mis_weight_nee at the direct point, mis_ray_pdf =
phase pdf at the indirect point). Independent reference: NEE off (pure phase
sampling, w_B = 1, no light pdf). Gate: per-channel image means agree within
4 standard errors (+0.5 % floor), fixed seeds, adaptive off.

Scenes: rectangular area lamp inside a scattering box / world fog, and an
emissive mesh quad in the box (legacy Hittable emitter). The box case also
caught a pre-existing bug: a lamp hit inside a bounded medium was weighted by
survival to the SURFACE, not Tr(lamp) (NEE off ~17 % dark; fixed in #925 by
running the lamp pass before the bounded free flight with explicit Tr).
"""
import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

astroray = pytest.importorskip("astroray")

_RES = 24
_SPP = 256
_SEEDS = tuple(range(1, 9))


def _render(kind, nee, seed, gpu=False):
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
    r.set_light_nee(nee)
    r.set_background_color([0.0, 0.0, 0.0])
    floor = r.create_material("lambertian", [0.3, 0.3, 0.3], {})
    r.add_triangle([-6, -6, -0.5], [6, -6, -0.5], [6, 6, -0.5], floor)
    r.add_triangle([-6, -6, -0.5], [6, 6, -0.5], [-6, 6, -0.5], floor)
    if kind == "mesh":
        lm = r.create_material("light", [1.0, 0.9, 0.7], {"intensity": 3.0})
        r.add_triangle([-1, -1, 3.5], [1, 1, 3.5], [1, -1, 3.5], lm)
        r.add_triangle([-1, -1, 3.5], [-1, 1, 3.5], [1, 1, 3.5], lm)
    else:
        # axis_u x axis_v = -z: the lamp faces the floor.
        r.add_area_light_dedicated([0, 0, 3.5], [0, 1, 0], [1, 0, 0], 2.0, 2.0, "RECTANGLE",
                                   {"mode": "rgb", "color": [1.0, 0.9, 0.7]}, 40.0)
    if kind == "fog":
        r.set_world_volume(0.25, [0.8, 0.8, 0.8], 0.0, 0.3)
    else:
        r.add_homogeneous_medium([-3, -3, -1], [3, 3, 4], 0.25, [0.8, 0.8, 0.8],
                                 [0.0, 0.0, 0.0], 0.3)
    r.setup_camera([0, -8, 1.5], [0, 0, 1.5], [0, 0, 1], 40.0, 1.0, 0.0, 8.0, _RES, _RES)
    r.set_seed(seed)
    img = np.asarray(r.render(_SPP, 8, None, False), dtype=np.float64)
    return img.reshape(_RES, _RES, 3).mean(axis=(0, 1))


def _stats(kind, nee, gpu=False):
    m = np.stack([_render(kind, nee, s, gpu) for s in _SEEDS])
    return m.mean(0), m.std(0, ddof=1) / np.sqrt(len(_SEEDS))


def _assert_nee_on_matches_off(kind, gpu):
    on, se_on = _stats(kind, True, gpu)
    off, se_off = _stats(kind, False, gpu)
    tol = 4.0 * np.hypot(se_on, se_off) + 0.005 * off
    assert np.all(np.abs(on - off) <= tol), (
        f"{kind}: NEE on {on} vs off {off} (rel {on / off - 1}), tol {tol}")


@pytest.mark.cpu
@pytest.mark.parametrize("kind", ["box", "fog", "mesh"])
def test_925_segment_nee_matches_nee_off_cpu(kind):
    _assert_nee_on_matches_off(kind, False)


# #929: GPU twin (segment direct light parked by the intersect stage, resolved
# by the shadow stage; lamp pass before the bounded free flight with Tr(lamp)).
@pytest.mark.gpu
@pytest.mark.parametrize("kind", ["box", "fog", "mesh"])
def test_929_segment_nee_matches_nee_off_gpu(kind):
    _assert_nee_on_matches_off(kind, True)
