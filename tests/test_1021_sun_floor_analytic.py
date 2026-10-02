"""#1021: a Lambertian floor under a finite sun and/or a uniform dome renders its analytic radiance.

pkg307 reported Astroray's sun-lit ``floor_far`` ROI (arb_prism_sun) 12-16 % above Cycles and Mitsuba. Not an
engine bias: the analytic floor below agrees on CPU and GPU, and Mitsuba at physical lamp units agrees too
(prism removed: 0.16115 vs 0.16098 analytic). ``floor_far`` also receives prism-borne (dispersed) sunlight that
Cycles barely renders, and the arbitration anchored Mitsuba's lamp to Cycles on that ROI, scaling Mitsuba down by
exactly the missing caustic (lamp_scale 0.886). The prism scene now runs Mitsuba in physical units (no anchor).

Analytic: L = rho * S * sin(elevation) / pi for a sun of irradiance S (Blender sun strength, W/m^2 normal to the
beam); L = rho * C for a uniform dome of radiance C (irradiance pi * C).
"""
import math

import numpy as np
import pytest

RHO, S, ELEV, ANGLE, DOME = 0.15, 9.0, math.radians(22.0), math.radians(4.0), 0.3  # = arbitration PARAMS


def _floor(gpu, sun, dome):
    import base_helpers as bh
    r = bh.create_renderer()
    if gpu:
        try:
            r.set_use_gpu(True)
        except Exception as e:  # noqa: BLE001 - CPU-only build
            pytest.skip("GPU unavailable: %s" % e)
        if not getattr(r, "gpu_available", False):
            pytest.skip("gpu_available is False")
    elif hasattr(r, "set_use_gpu"):
        r.set_use_gpu(False)
    r.set_seed(1021)
    r.set_background_color([DOME * dome] * 3)
    m = r.create_material("lambertian", [RHO] * 3, {})
    e = 200.0
    r.add_triangle([-e, 0, -e], [e, 0, -e], [e, 0, e], m)
    r.add_triangle([-e, 0, -e], [e, 0, e], [-e, 0, e], m)
    if sun:  # direction the light travels: 22 deg below the horizon
        r.add_sun_light_dedicated(direction=[math.cos(ELEV), -math.sin(ELEV), 0.0], angular_diameter=ANGLE,
                                  emission={"mode": "rgb", "color": [1, 1, 1]}, intensity=S)
    bh.setup_camera(r, look_from=[0.0, 20.0, 0.01], look_at=[0, 0, 0], vup=[0, 0, -1], vfov=10.0, width=32, height=32)
    img = bh.render_image(r, samples=256, max_depth=4, apply_gamma=False)
    return np.asarray(img, dtype=np.float64)[..., :3].reshape(-1, 3).mean(axis=0)


@pytest.mark.parametrize("gpu", [False, True], ids=["cpu", "gpu"])
@pytest.mark.parametrize("sun,dome", [(1, 0), (0, 1), (1, 1)], ids=["sun", "dome", "sun+dome"])
def test_floor_radiance_is_analytic(gpu, sun, dome):
    expected = sun * RHO * S * math.sin(ELEV) / math.pi + dome * RHO * DOME
    got = _floor(gpu, sun, dome)
    # 1024 px x 256 spp: MC error < 0.2 %; measured CPU -0.3 % (main 8363b2e3). Pre-fix pkg307 claim was +12-16 %.
    np.testing.assert_allclose(got, expected, rtol=0.015)


def test_prism_scene_mitsuba_sun_is_in_physical_units():
    """The arbitration prism scene must not anchor Mitsuba to a ROI that holds prism light (Cycles misses it)."""
    from benchmarks.reference_corpus.arbitration import mitsuba_scenes as ms
    assert ms.PARAMS["arb_prism_sun"]["anchor"] is None
    assert ms.calibration()["arb_prism_sun"]["lamp_scale"] == 1.0
