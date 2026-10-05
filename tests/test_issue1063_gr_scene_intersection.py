"""#1063: scene geometry inside the black-hole influence region is intersected
along the geodesic (piecewise-linear chords, Groeller 1995).

Before the fix the march never tested the scene, so anything inside
r_max = 1.05 x influence radius was invisible (a straddling sphere was bitten
in two; a sphere fully inside vanished). Emissive spheres only: lit surfaces
inside the region render dark because straight NEE rays hit the BH sphere
(#1081), and reflected light carries no gravitational shift (#1082).
Schwarzschild, no disk, r_obs_M = 20 over influence radius 5.5 (shadow radius
~1.4 world units).
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy import ndimage

from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

W, H = 240, 135
INFLUENCE = 5.5
R_MAX = 1.05 * INFLUENCE


def _render(spheres, black_hole=True, spp=8):
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(17)
    r.set_adaptive_sampling(False)
    for pos, rad in spheres:
        m = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 4.0})
        r.add_sphere(pos, rad, m)
    r.setup_camera([0.0, 0.0, 12.0], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                   42.0, W / H, 0.0, 12.0, W, H)
    if black_hole:
        r.add_black_hole([0.0, 0.0, 0.0], 4.0e6, INFLUENCE, {
            "spin": 0.0, "disk_outer": 0.0, "accretion_rate": 0.0,
            "inclination": 0.0, "enable_adaf": False, "r_obs_M": 20.0})
    return np.asarray(r.render(spp, 5, None, False), dtype=np.float32).mean(2)


def _blobs(lum, min_px=20):
    mask = lum > 0.5
    labels, n = ndimage.label(mask)
    sizes = ndimage.sum(mask, labels, range(1, n + 1))
    keep = [i + 1 for i, s in enumerate(sizes) if s >= min_px]
    return mask, labels, keep


def _centroid_x(mask):
    xs = np.nonzero(mask)[1]
    return (xs.mean() - W / 2) / (W / 2)


def test_sphere_straddling_r_max_is_continuous():
    # Centre 4.4 from the hole, radius 1.5: spans r = 2.9 .. 5.9 across r_max.
    lum = _render([([4.4, 0.0, 0.0], 1.5)])
    mask, labels, keep = _blobs(lum)
    assert 1 <= len(keep) <= 2, f"{len(keep)} images"
    for lab in keep:
        blob = labels == lab
        holes = int((ndimage.binary_fill_holes(blob) & ~blob).sum())
        assert holes == 0, f"image {lab} ({int(blob.sum())} px) has {holes} hole px"
    lit = int(mask.sum())
    assert sum(int((labels == lab).sum()) for lab in keep) >= 0.97 * lit
    # The seam/bite removed the inner part: the whole sphere must be there.
    # Unlensed projection of the sphere is ~ pi (1.5/12 * H/(2 tan 21 deg))^2 px.
    assert lit >= 900, f"only {lit} lit px"


def test_sphere_inside_region_renders_as_lensed_image():
    # Centre 3.0 from the hole (>= 2.1 x shadow radius), radius 0.5: r = 2.5 .. 3.5.
    sphere = ([3.0, 0.0, 0.0], 0.5)
    lum = _render([sphere])
    mask, labels, keep = _blobs(lum, min_px=10)
    assert keep, "sphere inside the GR region is invisible"
    lit = int(mask.sum())
    assert lit >= 150, f"only {lit} lit px"
    # Weak-to-moderate-field lensing pushes the primary image away from the
    # hole relative to the straight-line projection.
    straight = _render([sphere], black_hole=False)
    sm, _, _ = _blobs(straight, min_px=10)
    primary = max(keep, key=lambda lab: int((labels == lab).sum()))
    cx_lensed = _centroid_x(labels == primary)
    cx_straight = _centroid_x(sm)
    assert cx_lensed > cx_straight + 0.02, (cx_lensed, cx_straight)


def test_capture_beats_scene_hit_behind_the_horizon():
    # A sphere right behind the hole centre: rays aimed at the centre are
    # captured before they get there. The shadow stays black.
    lum = _render([([0.0, 0.0, -1.0], 0.3)])
    cy, cx = H // 2, W // 2
    assert float(lum[cy - 2:cy + 3, cx - 2:cx + 3].max()) < 0.05


def _interior_mean(lum):
    mask, labels, keep = _blobs(lum, min_px=10)
    primary = max(keep, key=lambda lab: int((labels == lab).sum()))
    core = ndimage.binary_erosion(labels == primary, iterations=2)
    assert core.sum() > 5
    return float(lum[core].mean())


def test_scene_hit_emission_is_gravitationally_redshifted():
    # Surface brightness obeys I_obs = g^4 I_emit (I_lambda * lambda^5 invariant,
    # Liouville). A small emissive sphere at r = 9 M, referenced to a static
    # observer at the region edge r_max = 21 M: g = sqrt((1-2/9)/(1-2/21)).
    sphere = ([9.0 * INFLUENCE / 20.0, 0.0, 0.0], 0.3)
    ratio = _interior_mean(_render([sphere])) / _interior_mean(_render([sphere], black_hole=False))
    g = np.sqrt((1.0 - 2.0 / 9.0) / (1.0 - 2.0 / 21.0))
    assert abs(ratio / g**4 - 1.0) < 0.12, (ratio, g**4)


def _adaf_render(spheres):
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(17)
    r.set_adaptive_sampling(False)
    for pos, rad in spheres:
        r.add_sphere(pos, rad, r.create_material("lambertian", [0.0, 0.0, 0.0], {}))
    r.setup_camera([0.0, 0.0, 12.0], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                   42.0, W / H, 0.0, 12.0, W, H)
    r.add_black_hole([0.0, 0.0, 0.0], 4.0e6, INFLUENCE, {
        "spin": 0.0, "disk_outer": 0.0, "accretion_rate": 0.0, "inclination": 0.0,
        "enable_adaf": True, "adaf_mdot_eddington": 1.0e-4, "adaf_electron_temp": 1.0e10,
        "adaf_beta_mag": 0.1, "adaf_r_inner": 1.5, "adaf_r_outer": 100.0,
        "adaf_flattening": 0.0, "adaf_alpha": 0.1, "adaf_s": 0.3,
        "adaf_intensity_scale": 1.0e30, "r_obs_M": 20.0})
    return np.asarray(r.render(8, 5, None, False), dtype=np.float32).mean(2)


def test_volumetric_emission_is_cut_at_the_scene_hit():
    # A black sphere in front of the hole hides the glow behind it: the march
    # ends at the hit, so the straight-line ADAF integral must too.
    bare = _adaf_render([])
    covered = _adaf_render([([0.0, 0.0, 3.0], 2.0)])
    yy, xx = np.mgrid[0:H, 0:W]
    ring = (np.hypot(yy - H // 2, xx - W // 2) >= 24) & (np.hypot(yy - H // 2, xx - W // 2) < 36)
    assert bare[ring].mean() > 1e6, "ADAF scene too dim to test"
    assert covered[ring].mean() < 0.1 * bare[ring].mean(), (covered[ring].mean(), bare[ring].mean())


def test_disk_crossing_past_the_scene_hit_in_the_same_step_is_dropped():
    helpers = pytest.importorskip("astroray_test_helpers")
    n0, n_late, stopped_late = helpers.gr_segment_hit_crossings_probe(1.0)
    _, n_early, stopped_early = helpers.gr_segment_hit_crossings_probe(0.0)
    assert n0 >= 1 and stopped_late == 1 and stopped_early == 1
    assert n_late == 1      # hit after the crossing: the crossing stays
    assert n_early == 0     # hit before the crossing in the same step: dropped
