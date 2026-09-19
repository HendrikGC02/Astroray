"""#840 — point/spot lamps with radius > 0 vs the Cycles-exact reference (CPU).

Before the fix a radius-r lamp sampled a uniform surface point with the AREA pdf
1/(4 pi r^2) against point-intensity emission, so brightness scaled with
4 pi r^2 (measured 0.031x / 0.126x / 0.76x at r = 0.05 / 0.1 / 0.25). The fix
ports Cycles kernel/light/point.h (astroray/lamp_sampling.h): the soft-falloff
disk (Blender's default use_soft_falloff) or the sphere, lamp radiance
P/(4 pi r^2 * pi), solid-angle pdf, NEE-only weight 1.

The reference (benchmarks/cycles-parity/ies_spot/ies_reference.py) matches
headless Cycles 5.2 to <= 0.2 % per 2-deg annulus for every leg below
(tests/test_pkg276_ies_spot_profile.py::test_reference_reproduces_recorded_cycles).
Band [0.95, 1.05] per channel above 5 % of the peak annulus.
"""

import math

import numpy as np
import pytest

from test_pkg276_ies_spot_profile import BAND, ref, render_astroray

RADII = [0.0, 0.05, 0.1, 0.25, 1.0]


def _radial_bad(img, sc):
    div = sc.res - 1
    refimg = ref.radiance(sc, None, sub=2, divisor=div)
    theta, _ = ref.pixel_geometry(sc, divisor=div)
    rows = ref.binned_ratio(img, refimg, theta, np.arange(0.0, 34.0, 2.0), min_ref_frac=0.05)
    checked = sum(1 for r in rows if not math.isnan(r["ratio"][1]))
    bad = ["[%g,%g) %s=%.3f" % (r["lo"], r["hi"], c, x)
           for r in rows for c, x in zip("RGB", r["ratio"])
           if not math.isnan(x) and not (BAND[0] <= x <= BAND[1])]
    return checked, bad


@pytest.mark.parametrize("radius", RADII)
@pytest.mark.parametrize("kind", ["POINT", "SPOT"])
def test_soft_falloff_radius_sweep(astroray_module, kind, radius):
    sc = ref.SpotScene(kind=kind, radius=radius, soft_falloff=True)
    img = render_astroray(astroray_module, sc, "", spp=64)
    checked, bad = _radial_bad(img, sc)
    assert checked >= 10, checked
    assert not bad, "%s r=%g (soft falloff) off the Cycles reference: %s" % (kind, radius, bad)


@pytest.mark.parametrize("radius", [0.25, 1.0])
@pytest.mark.parametrize("kind", ["POINT", "SPOT"])
def test_sphere_mode(astroray_module, kind, radius):
    sc = ref.SpotScene(kind=kind, radius=radius, soft_falloff=False)
    img = render_astroray(astroray_module, sc, "", spp=64)
    checked, bad = _radial_bad(img, sc)
    assert checked >= 10, checked
    assert not bad, "%s r=%g (sphere) off the Cycles reference: %s" % (kind, radius, bad)


def test_four_equal_lamps_keep_full_energy(astroray_module):
    """NEE-only lamps must not be MIS-weighted against BSDF sampling: with four
    equal radius-0.1 lamps the one under the camera still delivers the reference
    irradiance (the old weight gave 0.40x for four radius-0 lamps)."""
    base = ref.SpotScene(kind="POINT", radius=0.1, res=64, fov_deg=10.0,
                         light_pos=(0.0, 0.0, 2.0))
    r = astroray_module.Renderer()
    r.set_integrator("path_tracer")
    r.set_use_gpu(False)
    r.set_seed(7)
    r.set_pixel_filter(0, 1.0)
    r.set_background_color([0.0, 0.0, 0.0])
    m = r.create_material("lambertian", [base.albedo] * 3, {})
    s = 60.0
    r.add_triangle([-s, -s, 0], [s, -s, 0], [s, s, 0], m)
    r.add_triangle([-s, -s, 0], [s, s, 0], [-s, s, 0], m)
    em = {"mode": "rgb", "color": [1.0, 1.0, 1.0]}
    r.add_point_light([0.0, 0.0, 2.0], em, base.power, 0.1, "", 0, 0)
    for k in (1, 2, 3):
        r.add_point_light([40.0 * k, 40.0, 2.0], em, base.power, 0.1, "", 0, 0)
    r.setup_camera(look_from=[0, 0, base.cam_height], look_at=[0, 0, 0], vup=[0, 1, 0],
                   vfov=base.fov_deg, aspect_ratio=1.0, aperture=0.0,
                   focus_dist=base.cam_height, width=base.res, height=base.res)
    img = np.asarray(r.render(64, 4, None, False))[..., :3]
    want = ref.radiance(base, None, sub=2, divisor=base.res - 1)
    ratio = img[..., 1].mean() / want.mean()
    assert 0.95 <= ratio <= 1.05, ratio
