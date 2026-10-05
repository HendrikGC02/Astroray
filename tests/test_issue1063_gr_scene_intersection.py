"""#1063: scene geometry inside the black-hole influence region is intersected
along the geodesic (piecewise-linear chords, Groeller 1995).

Before the fix the march never tested the scene, so anything inside
r_max = 1.05 x influence radius was invisible (a straddling sphere was bitten
in two; a sphere fully inside vanished). Emissive spheres only (the straight
shadow rays of an NEE-lit diffuse surface are outside this fix's scope).
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
