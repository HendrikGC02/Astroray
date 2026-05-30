"""pkg111 TDD red anchor — prism caustic on a TILTED receiver (NOT horizontal).

This scene is identical to prism-bk7-collimated except the receiver plane is
tilted ~30deg about the z-axis, so its normal is NOT vertical (normal.y ~ 0.87,
< 0.9). The pkg106/109/110 photon gather in light_tracer_caustic.cpp is gated
on `rec.normal.y > 0.9f` (horizontal receiver only), so this scene FAILS with
those packages. pkg111 lifts that restriction: the generalized gather works at
ANY (point, normal, bsdf), making this scene GREEN.

**Integrator**: initially `light_tracer_caustic` (to verify the TDD failure),
then switches to the default `path_tracer` with `caustics = photon_map` when
pkg111 wires the gather into the default integrator.
"""

from __future__ import annotations

import math


NAME = "prism-tilted-receiver"
WIDTH = 512
HEIGHT = 512
SAMPLES = 96
MAX_DEPTH = 8
SEED = 17


def _norm(v):
    n = math.sqrt(sum(c * c for c in v))
    return [c / n for c in v]


def _quad_from_plane(p, n, half_u, half_v):
    """Finite quad on plane(p, n): pick an in-plane (u,v) frame -> 4 CCW corners."""
    n = _norm(n)
    up = [0.0, 1.0, 0.0] if abs(n[1]) < 0.9 else [1.0, 0.0, 0.0]
    d = sum(up[i] * n[i] for i in range(3))
    u = _norm([up[i] - d * n[i] for i in range(3)])
    v = [n[1] * u[2] - n[2] * u[1], n[2] * u[0] - n[0] * u[2], n[0] * u[1] - n[1] * u[0]]
    def corner(su, sv):
        return [p[i] + su * half_u * u[i] + sv * half_v * v[i] for i in range(3)]
    return [corner(-1, -1), corner(1, -1), corner(1, 1), corner(-1, 1)]


def _add_quad(r, corners, mat):
    i0 = r.scene_object_count()
    a, b, c, d = corners
    r.add_triangle(a, b, c, mat)
    r.add_triangle(a, c, d, mat)
    return [i0, i0 + 1]


def make_scene(astroray):
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])

    # BK7 dispersive prism (same as prism-bk7-collimated).
    glass = r.create_material("dielectric", [1.0, 1.0, 1.0], {"sellmeier_preset": "bk7"})
    apex_y, base_y, half_v = 0.5, -0.5, 0.7
    half = math.radians(30.0)
    bx = (apex_y - base_y) * math.tan(half)
    cy = (apex_y + base_y) / 2.0
    faces = [
        ([-bx / 2, cy, 0.0], _norm([-math.cos(half), math.sin(half), 0.0])),
        ([bx / 2, cy, 0.0], _norm([math.cos(half), math.sin(half), 0.0])),
    ]
    casters = []
    for p, n in faces:
        casters += _add_quad(r, _quad_from_plane(p, n, 0.62, half_v), glass)
    for idx in casters:
        r.set_object_caustic_caster(idx, True)

    # Collimated sun (same as prism-bk7-collimated).
    r.add_sun_light_dedicated([1.0, 0.0, 0.0], 0.01,
                              {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 6.0)

    # TILTED receiver plane: rotated ~30deg from horizontal about the z-axis.
    # Normal: rotate +y by 30deg about z -> n = (sin(30), cos(30), 0) ~ (0.5, 0.866, 0).
    # This fails the pkg106/109/110 `rec.normal.y > 0.9` gate (0.866 < 0.9).
    # Place the receiver so the dispersed beam still hits it (adjust y + center).
    tilt_deg = 30.0
    tilt_rad = math.radians(tilt_deg)
    rx_normal = [math.sin(tilt_rad), math.cos(tilt_rad), 0.0]  # ~ (0.5, 0.866, 0)
    # Receiver center: adjusted so the beam (exiting ~(1.9, -3, 0) on the floor)
    # lands on the tilted plane. For a tilt of 30deg, shift center down a bit.
    rx_center = [2.5, -2.5, 0.0]
    floor = r.create_material("lambertian", [0.9, 0.9, 0.9], {})
    _add_quad(r, _quad_from_plane(rx_center, rx_normal, 3.0, 2.0), floor)

    # pkg111: default path_tracer with photon-map caustics (NOT light_tracer_caustic).
    # The photon map build + gather works on ANY diffuse surface (not just horizontal).
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", MAX_DEPTH)
    r.set_integrator_param_str("caustics", "photon_map")
    r.set_integrator_param("photon_knn", 50)

    # Camera aimed at the tilted receiver (adjust to frame the rainbow band).
    r.setup_camera([2.5, 0.1, 3.4], [2.5, -2.5, 0.0], [0.0, 1.0, 0.0],
                   25.0, WIDTH / HEIGHT, 0.0, 4.5, WIDTH, HEIGHT)
    return r
