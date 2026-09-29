"""pkg294 (#922): full-spread rectangle lamps are sampled in solid angle.

Cycles draws a rectangular area light with the spherical-rectangle map of
Urena, Fajardo & King 2013 (kernel/light/area.h::area_light_rect_sample) for
every non-segment sample and lamp-hit pdf; Astroray drew it uniformly over the
area. Both are unbiased; the solid-angle draw removes the r^2/cos pdf variation,
which dominates for points close to a large lamp.

Control: the same lamp with a half-spread just below pi/2 keeps the
area-uniform draw (the spread-clamped rectangle is not ported), so the
variance ratio fails (about 1) before the change and passes after it. The
means of both legs must agree (the spread attenuation at 89.99 deg is ~1).
NEE on/off and analytic gates for the same lamp: test_issue883 (area kind)
and test_925/929 (box, fog).
"""
import math

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

astroray = pytest.importorskip("astroray")

_RES = 16
_SEEDS = tuple(range(1, 25))
_FULL = math.pi / 2.0          # Blender spread 180 deg (binding default)
_AREA = 1.5707                 # just below: area-uniform control


def _render(spread, seed, spp, gpu=False):
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
    r.set_background_color([0.0, 0.0, 0.0])
    # Isotropic scattering slab right under a large down-facing lamp.
    r.add_homogeneous_medium([-1, -1, 0], [1, 1, 1], 2.0, [0.9, 0.9, 0.9],
                             [0.0, 0.0, 0.0], 0.0)
    r.add_area_light_dedicated([0, 0, 1.02], [0, 1, 0], [1, 0, 0], 3.0, 3.0, "RECTANGLE",
                               {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 50.0, spread)
    r.setup_camera([0, -5, 0.5], [0, 0, 0.5], [0, 0, 1], 22.0, 1.0, 0.0, 5.0, _RES, _RES)
    r.set_seed(seed)
    img = np.asarray(r.render(spp, 8, None, False), dtype=np.float64)
    return img.reshape(_RES, _RES, 3).mean(-1)


def _leg(spread, spp, gpu=False):
    st = np.stack([_render(spread, s, spp, gpu) for s in _SEEDS])
    m = st.mean(0)
    mask = m > 0.25 * m.max()
    rel_var = float((st.var(0, ddof=1)[mask] / m[mask] ** 2).mean())
    seed_means = st[:, mask].mean(1)
    return float(seed_means.mean()), float(seed_means.std(ddof=1) / math.sqrt(len(_SEEDS))), rel_var


def _check(gpu):
    m_sa, se_sa, v_sa = _leg(_FULL, 4, gpu)
    m_ar, se_ar, v_ar = _leg(_AREA, 4, gpu)
    assert abs(m_sa - m_ar) <= 4.0 * math.hypot(se_sa, se_ar) + 0.005 * m_ar, (
        f"means differ: solid-angle {m_sa:.5f}+-{se_sa:.5f} vs area {m_ar:.5f}+-{se_ar:.5f}")
    assert v_sa < 0.6 * v_ar, (
        f"solid-angle draw should cut per-pixel variance: relVar {v_sa:.4f} vs area {v_ar:.4f} "
        f"(ratio {v_sa / v_ar:.3f})")


@pytest.mark.cpu
def test_pkg294_rect_solid_angle_draw_cpu():
    _check(False)


@pytest.mark.gpu
def test_pkg294_rect_solid_angle_draw_gpu():
    if not getattr(astroray, "__features__", {}).get("cuda", False):
        pytest.skip("CUDA build required")
    _check(True)
