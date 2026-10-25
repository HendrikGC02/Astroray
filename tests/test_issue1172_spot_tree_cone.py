"""#1172 -- light-tree orientation cone of a spot light.

Cycles v5.2.0 scene/light_tree.cpp:187-208 bounds a spot with theta_o = 0,
theta_e = half spot angle. Astroray used theta_o = theta_e = half angle, so the
tree gave the spot importance out to twice its cone (v2_dispersion_caustics:
sun-lit floor points picked the spot 87 % of the time).

Probe: a radius-0 spot (blend 0, so Cycles' emitter smoothstep is a step and
the node form is exact) plus a sun. The tree root splits local (spot) / distant
(sun). Zero normals drop the incidence term, so the sun's importance is a
constant S and the spot's at distance d is E/d^2 * cos(theta'), with
(kernel/light/tree.h:173-215, theta_u = 0, theta_o = 0):
  cos(theta') = cos(theta) for theta < theta_e, else 0 (invisible).
Pick odds O = p_spot / (1 - p_spot) = I_spot / S, hence
  O(theta) / O(0) = |cos(theta)| inside the cone (Cycles takes fabsf, tree.h:215)
  and O = 0 outside.
The old cone gave 1 inside and cos(theta - half) out to 2 * half. A spot wider
than 90 deg (Python API; Blender caps spot_size at 180 deg) must keep a nonzero
importance past 90 deg: it is NEE-only, so a zero importance loses its energy.

Run: pytest tests/test_issue1172_spot_tree_cone.py -v
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()
astroray = pytest.importorskip("astroray")

DIST = 2.0
AXIS = np.array([0.0, -1.0, 0.0])
# (half angle, inside, outside) in degrees off the axis
CASES = {"narrow": (20.0, (0.0, 10.0, 19.0), (21.0, 25.0, 35.0)),  # old cone kept up to 40 deg
         "wide": (100.0, (0.0, 60.0, 95.0), (105.0, 150.0))}
U_HI = 1.0 - 2.0 ** -20       # always descends right (sun) unless p_spot ~ 1


def _scene(gpu, half):
    r = astroray.Renderer()
    r.set_use_gpu(gpu)
    r.set_background_color([0.0, 0.0, 0.0])
    floor = r.create_material("lambertian", [0.5, 0.5, 0.5], {})
    r.add_triangle([-20, -5, -20], [20, -5, -20], [20, -5, 20], floor)
    white = {"mode": "rgb", "color": [1.0, 1.0, 1.0]}
    r.add_spot_light_dedicated([0.0, 0.0, 0.0], AXIS.tolist(), half, half, white, 100.0, 0.0)
    r.add_sun_light_dedicated([0.3, -1.0, 0.2], 0.0093, white, 25.0)
    r.setup_camera([0, 2.0, 9.0], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 9.0, 16, 16)
    r.set_light_sampler("tree")
    if gpu:
        r.upload_scene()
    else:
        r.render(1, 1, None, False)  # builds the tree
    return r


def _points(degs):
    """Points at distance DIST from the spot, theta degrees off its axis."""
    pts = []
    for deg in degs:
        t = math.radians(deg)
        pts.append((DIST * math.sin(t), -DIST * math.cos(t), 0.0))
    return pts


def _spot_prob(pick, degs):
    pts = _points(degs)
    flat = [c for p in pts for c in p]
    zeros = [0.0] * len(flat)
    _, pdf_lo = pick(flat, zeros, [0.0] * len(pts))
    _, pdf_hi = pick(flat, zeros, [U_HI] * len(pts))
    pdf_lo, pdf_hi = np.asarray(pdf_lo, float), np.asarray(pdf_hi, float)
    # u = 0 picks the spot (left child) iff p_spot > 0, with pdf p_spot; u ~ 1
    # picks the sun with pdf 1 - p_spot.
    p_spot = 1.0 - pdf_hi
    seen = p_spot > 1e-6
    np.testing.assert_allclose(pdf_lo[seen], p_spot[seen], rtol=1e-4)
    assert np.all(pdf_lo[~seen] == pytest.approx(1.0))
    return p_spot


def _check(p_spot, inside, outside):
    n_in = len(inside)
    odds = p_spot[:n_in] / (1.0 - p_spot[:n_in])
    assert 0.05 < p_spot[0] < 0.95, f"on-axis p_spot {p_spot[0]:.3f}: rebalance the sun"
    want = np.abs(np.cos(np.radians(inside)))
    assert np.all(p_spot[:n_in] > 0.0), f"spot not picked inside its cone: {p_spot[:n_in]} at {inside} deg"
    np.testing.assert_allclose(odds / odds[0], want, rtol=2e-4,
                               err_msg="inside the cone importance must scale as cos(theta)")
    assert np.all(p_spot[n_in:] == 0.0), (
        f"spot picked outside its cone: p_spot {p_spot[n_in:]} at {outside} deg")


@pytest.mark.parametrize("case", sorted(CASES))
def test_spot_tree_importance_matches_cycles_cone_cpu(case):
    half, inside, outside = CASES[case]
    r = _scene(False, math.radians(half))
    _check(_spot_prob(r.debug_light_tree_pick, inside + outside), inside, outside)


@pytest.mark.parametrize("case", sorted(CASES))
def test_spot_tree_importance_matches_cycles_cone_gpu(case):
    if not astroray.__features__.get("cuda", False):
        pytest.skip("CUDA feature not in this build")
    half, inside, outside = CASES[case]
    r = _scene(True, math.radians(half))
    _check(_spot_prob(r.debug_light_tree_pick_gpu, inside + outside), inside, outside)
