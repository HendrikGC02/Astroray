"""pkg225 Stage 1 — CPU ray-curve (swept-circle) intersection: analytic parity.

CurveSegment ports pbrt-v3's Curve::Intersect / recursiveIntersect (Pharr,
Humphreys, Jakob — src/shapes/curve.cpp, BSD-2-Clause), CurveType::Cylinder
branch (see include/astroray/curves.h and
.astroray_plan/docs/pkg225-curve-intersect-research.md for the full citation
and derivation this test relies on).

KEY FACT this test exploits (proved in the research note, re-derived below):
for a STRAIGHT (colinear-control-point) curve segment, the algorithm's
reported hit distance `t` is EXACTLY the ray-parameter depth of Q* — the
point on the curve's AXIS LINE closest to the ray's infinite line — a
textbook closed-form quantity (the classic two-skew-lines closest-point
formula). This holds for ANY ray/radius combination that lands within the
segment's finite span (not just the tangent/grazing case): the reported `t`
is the algorithm's *defined* semantics (depth of the axis-closest-point), not
an attempt at "true cylinder-surface entry" (which would require a slower
per-ray quadratic solve pbrt/Cycles deliberately avoid for this style of
fast hair-fiber intersector). At EXACT tangency (radius == distance(P*, Q*))
P* (closest point ON the ray) is provably exactly ON the true cylindrical
surface too (the P*-Q* segment is perpendicular to both lines, hence lies in
the cross-sectional plane at Q*), which is what the "tangent-grazing" cases
below also check against the reconstructed shading normal.

Geometry is probed via the existing depth/position/normal AOV buffers
(get_depth_buffer / get_position_buffer / get_normal_buffer) rather than a
full noisy render: aperture=0 (pinhole, so the ray ORIGIN is exact, no lens
jitter) and the AOV buffers are captured from the FIRST sample only
(include/raytracer.h, "if (s == 0) { depth = sDepth; position = sPosition; }"
— confirmed by reading the render loop), so each probe is exactly ONE
(sub-pixel-jittered) ray. The jitter is bounded by one pixel's angular
footprint; with a narrow vfov and large resolution that footprint is chosen
to be far smaller than the numeric tolerance used below (see
_PIXEL_FOOTPRINT_BOUND). Hit/miss test radii are offset from the exact
tangent radius by a margin well above that bound, so pass/fail is
deterministic (not a coin-flip on which side of the boundary the single
jittered sample lands).
"""

from __future__ import annotations

import math

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

# Odd resolution -> a true single centre pixel; narrow vfov -> tiny angular
# footprint per pixel. At the ~50-120 unit distances used below, footprint
# ~= distance * radians(VFOV_DEG)/RESOLUTION, i.e. well under 1e-2 world
# units. Tolerances chosen with a wide safety margin over that bound.
_RESOLUTION = 401
_VFOV_DEG = 0.6
_PIXEL_FOOTPRINT_BOUND = 0.02  # generous upper bound on sub-pixel position error
_T_TOL = 0.05
_POS_TOL = 0.05
_NORMAL_TOL = 0.05
_MARGIN = 0.05  # >> _PIXEL_FOOTPRINT_BOUND; separates "clearly hit" / "clearly miss"


def _closest_points(ray_o, ray_d, axis_o, axis_d):
    """Standard closed-form closest points between two (non-parallel) 3D
    lines (e.g. Ericson, "Real-Time Collision Detection" S5.1.9). Returns
    (p_ray, q_axis, s_ray): the closest point on each line, and the ray
    parameter of the closest point on the ray (== the analytic hit distance
    CurveSegment must reproduce, per the module docstring)."""
    ray_o = np.asarray(ray_o, dtype=np.float64)
    ray_d = np.asarray(ray_d, dtype=np.float64)
    axis_o = np.asarray(axis_o, dtype=np.float64)
    axis_d = np.asarray(axis_d, dtype=np.float64)
    ray_d = ray_d / np.linalg.norm(ray_d)
    axis_d = axis_d / np.linalg.norm(axis_d)
    w0 = ray_o - axis_o
    b = float(np.dot(ray_d, axis_d))
    d = float(np.dot(ray_d, w0))
    e = float(np.dot(axis_d, w0))
    denom = 1.0 - b * b
    assert abs(denom) > 1e-6, "ray (near-)parallel to axis; pick different test geometry"
    s_ray = (b * e - d) / denom
    s_axis = (e - b * d) / denom
    p_ray = ray_o + s_ray * ray_d
    q_axis = axis_o + s_axis * axis_d
    return p_ray, q_axis, s_ray


def _render_curve_probe(points, radii, ray_origin, ray_target, radius_override=None):
    """Build a scene with one hair strand (via add_curves_bulk) and probe a
    single camera ray (ray_origin -> ray_target) for depth/position/normal.
    Returns (depth, position(3,), normal(3,))."""
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    mat = r.create_material("lambertian", [0.6, 0.6, 0.6], {})
    pts = np.asarray(points, dtype=np.float32)
    if radius_override is not None:
        rad = np.full(len(points), radius_override, dtype=np.float32)
    else:
        rad = np.asarray(radii, dtype=np.float32)
    r.add_curves_bulk(pts, rad, [len(points)], mat)
    r.set_integrator("path_tracer")
    ray_origin = np.asarray(ray_origin, dtype=np.float64)
    ray_target = np.asarray(ray_target, dtype=np.float64)
    dist = float(np.linalg.norm(ray_target - ray_origin))
    r.setup_camera(list(ray_origin), list(ray_target), [0.0, 1.0, 0.0],
                    _VFOV_DEG, 1.0, 0.0, dist, _RESOLUTION, _RESOLUTION)
    r.set_seed(7)
    r.render(2, 2, None, False)
    cx = cy = (_RESOLUTION - 1) // 2
    depth = float(np.asarray(r.get_depth_buffer())[cy, cx])
    position = np.asarray(r.get_position_buffer())[cy, cx].astype(np.float64)
    normal = np.asarray(r.get_normal_buffer())[cy, cx].astype(np.float64)
    return depth, position, normal


# A single straight strand (4 collinear points along +X) — exercises
# CurveStrip::buildCurveSegments()'s Cycles-convention phantom-endpoint
# clamping at both ends (3 segments), while the whole strand stays one
# straight line so every segment shares the same closed-form axis. Aim probes
# at the MIDDLE segment's real span [-10, 10] to stay comfortably clear of
# either end.
_STRAIGHT_POINTS = [(-20.0, 0.0, 0.0), (-10.0, 0.0, 0.0), (10.0, 0.0, 0.0), (20.0, 0.0, 0.0)]
_AXIS_O = (0.0, 0.0, 0.0)
_AXIS_D = (1.0, 0.0, 0.0)


def test_straight_cylinder_perpendicular_ray_hit_distance():
    """Ray perpendicular to the strand axis, aimed through it: t must match
    the closed-form axis-closest-point depth exactly (module docstring)."""
    ray_o = (0.0, 60.0, 0.15)
    ray_d = (0.0, -1.0, 0.0)
    p_ray, q_axis, s_ray = _closest_points(ray_o, ray_d, _AXIS_O, _AXIS_D)
    radius = float(np.linalg.norm(p_ray - q_axis)) + _MARGIN  # comfortably inside
    ray_target = tuple(np.asarray(ray_o) + np.asarray(ray_d))
    depth, position, normal = _render_curve_probe(
        _STRAIGHT_POINTS, None, ray_o, ray_target, radius_override=radius)
    assert depth == pytest.approx(s_ray, abs=_T_TOL), f"depth {depth} != analytic {s_ray}"
    assert np.linalg.norm(position - p_ray) < _POS_TOL, f"position {position} != analytic {p_ray}"


def test_straight_cylinder_oblique_ray_hit_distance():
    """Same closed-form check with a ray neither perpendicular nor parallel
    to the axis — confirms the match isn't an artifact of the perpendicular
    special case (the underlying skew-line theorem is fully general)."""
    ray_o = (2.0, 45.0, -6.0)
    ray_d = (0.3, -1.0, 0.4)
    p_ray, q_axis, s_ray = _closest_points(ray_o, ray_d, _AXIS_O, _AXIS_D)
    assert -9.0 < q_axis[0] < 9.0, "test geometry drifted outside the middle segment's span"
    radius = float(np.linalg.norm(p_ray - q_axis)) + _MARGIN
    ray_target = tuple(np.asarray(ray_o) + np.asarray(ray_d))
    depth, position, normal = _render_curve_probe(
        _STRAIGHT_POINTS, None, ray_o, ray_target, radius_override=radius)
    assert depth == pytest.approx(s_ray, abs=_T_TOL), f"depth {depth} != analytic {s_ray}"
    assert np.linalg.norm(position - p_ray) < _POS_TOL, f"position {position} != analytic {p_ray}"


def test_straight_cylinder_miss():
    """Radius pulled below the true clearance distance: must miss."""
    ray_o = (0.0, 60.0, 0.15)
    ray_d = (0.0, -1.0, 0.0)
    p_ray, q_axis, _s_ray = _closest_points(ray_o, ray_d, _AXIS_O, _AXIS_D)
    true_clearance = float(np.linalg.norm(p_ray - q_axis))
    radius = max(true_clearance - _MARGIN, 1e-4)
    ray_target = tuple(np.asarray(ray_o) + np.asarray(ray_d))
    depth, _position, _normal = _render_curve_probe(
        _STRAIGHT_POINTS, None, ray_o, ray_target, radius_override=radius)
    assert depth < 1.0, f"expected a clean miss (depth~=0), got depth={depth}"


def test_straight_cylinder_tangent_grazing_normal():
    """Radius set to (clearance + a small-but-safe margin): P* is provably
    within numerical tolerance of the TRUE cylinder surface at tangency (the
    P*-Q* segment is perpendicular to both the ray and the axis — module
    docstring), so the reconstructed shading normal must point along
    normalize(P* - Q*), the true geometric outward radial direction."""
    ray_o = (0.0, 60.0, 0.15)
    ray_d = (0.0, -1.0, 0.0)
    p_ray, q_axis, s_ray = _closest_points(ray_o, ray_d, _AXIS_O, _AXIS_D)
    true_clearance = float(np.linalg.norm(p_ray - q_axis))
    radius = true_clearance + _MARGIN
    expected_normal = (p_ray - q_axis) / np.linalg.norm(p_ray - q_axis)
    ray_target = tuple(np.asarray(ray_o) + np.asarray(ray_d))
    depth, position, normal = _render_curve_probe(
        _STRAIGHT_POINTS, None, ray_o, ray_target, radius_override=radius)
    assert depth == pytest.approx(s_ray, abs=_T_TOL)
    normal = normal / (np.linalg.norm(normal) + 1e-12)
    assert np.linalg.norm(normal - expected_normal) < _NORMAL_TOL, (
        f"normal {normal} != analytic outward radial {expected_normal}")


def test_endcap_beyond_segment_extent_misses():
    """A ray aimed dead-centre through the axis (clearance == 0, which would
    hit an INFINITE cylinder trivially) but beyond the strand's finite [P1,
    P2] extent must miss — this is pbrt's endpoint edge-function reject
    (curves.h recursiveIntersect leaf test)."""
    points = [(-5.0, 0.0, 0.0), (5.0, 0.0, 0.0)]  # single segment, no phantom ambiguity
    ray_o = (8.0, 60.0, 0.0)   # x=8 is well beyond the [-5, 5] real span
    ray_target = (8.0, 0.0, 0.0)
    depth, _position, _normal = _render_curve_probe(
        points, None, ray_o, ray_target, radius_override=0.3)
    assert depth < 1.0, f"expected endcap miss (x=8 outside [-5,5] span), got depth={depth}"


def test_endcap_within_segment_extent_hits():
    """Sanity twin of the endcap-miss test: the same aim, but x=4 IS inside
    the finite [-5, 5] span, must hit at the expected closed-form distance."""
    points = [(-5.0, 0.0, 0.0), (5.0, 0.0, 0.0)]
    axis_o, axis_d = (0.0, 0.0, 0.0), (1.0, 0.0, 0.0)
    ray_o = (4.0, 60.0, 0.0)
    ray_d = (0.0, -1.0, 0.0)
    p_ray, q_axis, s_ray = _closest_points(ray_o, ray_d, axis_o, axis_d)
    radius = float(np.linalg.norm(p_ray - q_axis)) + _MARGIN
    ray_target = (4.0, 0.0, 0.0)
    depth, position, _normal = _render_curve_probe(
        points, None, ray_o, ray_target, radius_override=radius)
    assert depth == pytest.approx(s_ray, abs=_T_TOL)
    assert np.linalg.norm(position - p_ray) < _POS_TOL


def test_curved_strand_smoke():
    """Qualitative regression check for a genuinely curved (non-collinear)
    strand — no simple closed form exists for a general curved segment (that
    is exactly why pbrt/Cycles use the recursive-subdivision approximation
    under test), so this only asserts a sane hit: finite positive depth, and
    the hit position lands within the strand's own loose bounding region."""
    # A quarter-circle-ish bent poly-line (not a true circle; the point is
    # non-collinear curvature, not analytic exactness).
    points = [(-10.0, 0.0, 0.0), (-5.0, 3.0, 0.0), (0.0, 5.0, 0.0),
              (5.0, 3.0, 0.0), (10.0, 0.0, 0.0)]
    radius = 0.4
    ray_o = (0.0, 5.0, 60.0)
    ray_target = (0.0, 5.0, 0.0)
    depth, position, normal = _render_curve_probe(
        points, None, ray_o, ray_target, radius_override=radius)
    assert 40.0 < depth < 70.0, f"unreasonable depth for a near-frontal strand hit: {depth}"
    # Loose AABB check: every strand point is within [-10,10]x[0,5]x[-radius,radius].
    assert -10.5 <= position[0] <= 10.5
    assert -0.5 <= position[1] <= 5.5
    assert -1.0 <= position[2] <= 1.0
    assert np.linalg.norm(normal) == pytest.approx(1.0, abs=0.05)
