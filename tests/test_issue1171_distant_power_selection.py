"""#1171 -- DistantLight::power() must follow the pkg122 irradiance convention.

Before the fix power() was Y * S * Omega (solid angle ~7e-5 for 0.526 deg), so
the flat light sampler (`set_light_sampler("power")`, i.e. use_light_tree off)
gave the sun a selection probability ~1e-4 next to any real lamp. NEE then
fired the sun so rarely that each fired sample was S / selPdf, far above the
per-sample firefly clamp, and the sun's contribution was clamped away
(v2_dispersion_caustics sphere_limb read 0.36x Cycles with the tree off).

The scene is a Lambertian floor under a sun (irradiance S, tilted) plus a
second, strong area light so that selection really splits between two lights
(with the sun alone selPdf == 1 whatever power() says). The sun's own
contribution is recovered as (with sun) - (without sun) and compared with
rho / pi * S * cos(theta). Both light samplers must reproduce it, and must
agree with each other.

Run: pytest tests/test_issue1171_distant_power_selection.py -v
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()
astroray = pytest.importorskip("astroray")

ALBEDO = 0.5
SUN_S = 4.0            # irradiance (W/m^2), pkg122 units
SUN_ANGLE = 0.00918    # Blender default 0.526 deg
TILT = math.radians(30.0)
SEEDS = (1171, 1172, 1173, 1174)
SPP = 96


def _luma(px):
    return 0.2126 * px[..., 0] + 0.7152 * px[..., 1] + 0.0722 * px[..., 2]


def _floor_mean(sampler, with_sun, seed):
    r = astroray.Renderer()
    r.set_use_gpu(False)
    r.set_adaptive_sampling(False)
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_light_sampler(sampler)
    r.set_seed(seed)
    r.setup_camera(look_from=[0.0, 20.0, 0.01], look_at=[0.0, 0.0, 0.0],
                   vup=[0.0, 0.0, -1.0], vfov=20.0, aspect_ratio=1.0, aperture=0.0,
                   focus_dist=20.0, width=32, height=32)
    mat = r.create_material('lambertian', [ALBEDO] * 3, {})
    e = 20.0
    r.add_triangle([-e, 0, -e], [e, 0, -e], [e, 0, e], mat)
    r.add_triangle([-e, 0, -e], [e, 0, e], [-e, 0, e], mat)
    # Strong second light: its power() dwarfs the sun's old S*Omega weight.
    r.add_area_light_dedicated(
        center=[0, 6, 0], axis_u=[1, 0, 0], axis_v=[0, 0, 1], size_x=2.0, size_y=2.0,
        shape='RECTANGLE', emission={'mode': 'rgb', 'color': [1, 1, 1]},
        intensity=300.0, spread=1.5708)
    if with_sun:
        r.add_sun_light_dedicated(
            direction=[math.sin(TILT), -math.cos(TILT), 0.0], angular_diameter=SUN_ANGLE,
            emission={'mode': 'rgb', 'color': [1, 1, 1]}, intensity=SUN_S)
    px = np.asarray(r.render(SPP, 3, None, False), dtype=np.float64)
    return float(_luma(px[..., :3]).mean())


def _sun_contribution(sampler):
    on = np.mean([_floor_mean(sampler, True, s) for s in SEEDS])
    off = np.mean([_floor_mean(sampler, False, s) for s in SEEDS])
    return on - off


ANALYTIC = ALBEDO / math.pi * SUN_S * math.cos(TILT)


@pytest.mark.parametrize("sampler", ["power", "tree"])
def test_1171_sun_contribution_matches_irradiance(sampler):
    got = _sun_contribution(sampler)
    assert 0.85 < got / ANALYTIC < 1.15, (sampler, got, ANALYTIC, got / ANALYTIC)


def test_1171_flat_sampler_matches_light_tree():
    p, t = _sun_contribution("power"), _sun_contribution("tree")
    assert 0.9 < p / t < 1.1, (p, t, p / t)
