"""Spectral-dispersion reference — BK7 triangulated-prism rainbow caustic.

**Geometry**: a triangulated equilateral BK7 prism (two refracting faces, each a
finite quad = 2 triangles, flagged as caustic casters), a collimated "sun"
(distant directional light) entering the prism, and a white diffuse floor that
catches the dispersed spectrum. Each wavelength refracts by its own Sellmeier
IOR and lands at a different floor position -> a clean continuous red->violet
rainbow band.

**Why forward light-tracing, not camera-side SMS/MNEE (pkg106 finish, 2026-05-29):**
The original plan refracted the caustic with the camera-side SMS/MNEE integrator.
The full MNEE machinery was implemented and unit-tested (analytic transfer-matrix
geometry term, positional + collimated branches, caster-aimed seed — see
include/astroray/manifold/ and tests/test_mnee_*.py), and it does produce a
*localized dispersive* caustic. But a flat prism does not focus: its dispersion
is weak and the camera-side specular connection is a near-delta whose Newton
basin is spatially chaotic, so the result is salt-and-pepper chromatic noise that
does not clean up with samples (deterministic structure). A prism rainbow is a
forward light-transport phenomenon, so this scene uses the `light_tracer_caustic`
integrator (Arvo 1986 backward ray tracing / Jensen 1996 photon deposition):
wavelengths are traced FROM the sun through the prism and deposited on the floor,
giving a smooth spectrum with no specular-connection noise. The MNEE math remains
for genuinely focusing casters (lenses, spheres).

**Integrator**: `light_tracer_caustic` (CPU forward light-tracer; the caustic is
baked in beginFrame so the camera pass needs few samples).
"""

from __future__ import annotations

import math


NAME = "prism-bk7-collimated"
WIDTH = 384
HEIGHT = 288
SAMPLES = 64
MAX_DEPTH = 8
SEED = 17


def _add_quad(r, corners, mat):
    a, b, c, d = corners
    r.add_triangle(a, b, c, mat)
    r.add_triangle(a, c, d, mat)


def _tri_outward(r, v0, v1, v2, centroid, mat):
    """Add a triangle wound so its geometric normal points AWAY from centroid.

    pkg110 traces photons through the prism with the general BSDF loop, which
    relies on consistent OUTWARD geometric normals for the dielectric to detect
    entry (air->glass) vs exit (glass->air). Auto-orienting the winding guarantees
    that regardless of vertex order. Returns the object index.
    """
    e1 = [v1[i] - v0[i] for i in range(3)]
    e2 = [v2[i] - v0[i] for i in range(3)]
    n = [e1[1] * e2[2] - e1[2] * e2[1],
         e1[2] * e2[0] - e1[0] * e2[2],
         e1[0] * e2[1] - e1[1] * e2[0]]
    c = [(v0[i] + v1[i] + v2[i]) / 3.0 - centroid[i] for i in range(3)]
    if sum(n[i] * c[i] for i in range(3)) < 0.0:   # normal points inward -> flip
        v1, v2 = v2, v1
    idx = r.scene_object_count()
    r.add_triangle(v0, v1, v2, mat)
    return idx


def _add_solid_prism(r, mat, half_v=0.7):
    """Closed SOLID equilateral triangular prism (apex +y), extruded in z.

    A real glass solid (8 triangles: 2 slanted refracting faces + bottom + 2 end
    caps) so the pkg110 BSDF photon loop refracts correctly enter->exit. The
    slanted-face angles match the original 2-quad prism, so the dispersed band
    lands in the same place.
    """
    A = (0.0, 0.5, 0.0)
    B = (-0.577, -0.5, 0.0)
    C = (0.577, -0.5, 0.0)
    centroid = [0.0, -1.0 / 6.0, 0.0]   # triangle centroid (z=0)

    def at(p, z):
        return [p[0], p[1], z]
    z0, z1 = -half_v, half_v
    A0, A1 = at(A, z0), at(A, z1)
    B0, B1 = at(B, z0), at(B, z1)
    C0, C1 = at(C, z0), at(C, z1)

    idxs = []
    for q in [(A0, A1, B1, B0), (A0, A1, C1, C0), (B0, B1, C1, C0)]:  # left, right, bottom
        idxs.append(_tri_outward(r, q[0], q[1], q[2], centroid, mat))
        idxs.append(_tri_outward(r, q[0], q[2], q[3], centroid, mat))
    idxs.append(_tri_outward(r, A0, B0, C0, centroid, mat))   # end cap z=-half_v
    idxs.append(_tri_outward(r, A1, B1, C1, centroid, mat))   # end cap z=+half_v
    return idxs


def make_scene(astroray):
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])

    # BK7 dispersive prism — a closed solid equilateral triangular prism (apex +y),
    # all faces flagged as caustic casters. pkg110: the forward photon loop refracts
    # through it via the dielectric's spectral BSDF (no hard-coded 2-face path).
    glass = r.create_material("dielectric", [1.0, 1.0, 1.0], {"sellmeier_preset": "bk7"})
    for idx in _add_solid_prism(r, glass):
        r.set_object_caustic_caster(idx, True)

    # Collimated sun: distant directional light travelling +x into the prism.
    r.add_sun_light_dedicated([1.0, 0.0, 0.0], 0.01,
                              {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 6.0)

    # White diffuse floor — the dispersed spectrum lands here (beam deviates
    # ~52deg down; lands ~x=1.9 at y=-3).
    floor = r.create_material("lambertian", [0.9, 0.9, 0.9], {})
    _add_quad(r, [[-1.0, -3.0, -2.5], [9.0, -3.0, -2.5], [9.0, -3.0, 2.5], [-1.0, -3.0, 2.5]], floor)

    # Forward light-tracer: bakes the prism caustic onto the floor in beginFrame.
    r.set_integrator("light_tracer_caustic")
    r.set_integrator_param("max_depth", MAX_DEPTH)
    r.set_integrator_param("photon_count", 9000000)
    r.set_integrator_param("caustic_boost", 12)

    # Camera looks down the floor at the rainbow landing zone.
    r.setup_camera([1.86, 1.5, 3.2], [1.86, -3.0, 0.0], [0.0, 1.0, 0.0],
                   42.0, WIDTH / HEIGHT, 0.0, 4.5, WIDTH, HEIGHT)
    return r
