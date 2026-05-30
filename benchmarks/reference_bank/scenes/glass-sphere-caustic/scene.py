"""Focusing-caster caustic — clear glass SPHERE + collimated sun (pkg110).

The pkg106/109 forward light-tracer was prism-specific (a hard-coded 2-face
refraction). pkg110 makes the photon bounce BSDF-driven, so photons traverse ANY
glass shape via the material's sampleSpectral. This scene is the acceptance gate:
a primitive glass *sphere* (a NON-triangle caustic caster the old 2-face code
could not handle) FOCUSES a collimated sun into a concentrated "burning-glass"
caustic on the floor — a bright cusp/spot, much brighter than the surrounding
direct-lit floor.

**Composition (2026-05-30 reference-bank polish):** the sphere is LIFTED well off
the floor and the collimated sun is angled down-and-+x so the focused caustic
lands on the floor OFFSET from the sphere's own shadow (it no longer hides its
own caustic). The floor sits near the sphere's focal distance so the cone
converges to a tight, structured spot — not a dim re-diverged ring. The camera is
zoomed onto the caustic landing zone (the hero), not the whole scene.

Geometry: a clear ior-1.5 glass sphere (radius 0.6) centred at +y, flagged as a
caustic caster; a distant collimated sun angled down (+x, -y); a white diffuse
floor positioned just past the focal distance below; camera zoomed onto the spot.

Integrator: `light_tracer_caustic` (forward; caustic baked in beginFrame).
"""

from __future__ import annotations

import math


NAME = "glass-sphere-caustic"
WIDTH = 512
HEIGHT = 512
SAMPLES = 96
MAX_DEPTH = 12
SEED = 17


def _norm(v):
    n = math.sqrt(sum(c * c for c in v))
    return [c / n for c in v]


def _add_quad(r, corners, mat):
    a, b, c, d = corners
    r.add_triangle(a, b, c, mat)
    r.add_triangle(a, c, d, mat)


# --- Focusing geometry ------------------------------------------------------
# Sphere of radius R=0.6, ior n=1.5. Paraxial back-focal distance from centre
# along the chief (through-centre) ray: f = R*n / (2*(n-1)) = 0.9. The bright
# spherical-aberration cusp forms slightly short of that. We aim the collimated
# sun down-and-+x and place the floor so the focal cusp lands ON it, offset in
# +x from the sphere's shadow.
SPHERE_C = [0.0, 0.4, 0.0]
SPHERE_R = 0.6
SUN_DIR = _norm([0.55, -1.0, 0.0])   # chief ray direction through the centre
# Floor placed a little PAST the paraxial focus (~0.9 along the beam from the
# centre): close enough that the spherical-aberration caustic reads as a bright
# cusp with a small structured footprint, not a single re-diverged point.
FLOOR_Y = -0.95
# Where the chief ray (through the centre) meets the floor — the caustic lands
# near here. Solve C + t*SUN_DIR hitting y = FLOOR_Y.
_t = (FLOOR_Y - SPHERE_C[1]) / SUN_DIR[1]
CAUSTIC_X = SPHERE_C[0] + _t * SUN_DIR[0]
CAUSTIC_Z = SPHERE_C[2] + _t * SUN_DIR[2]


def make_scene(astroray):
    r = astroray.Renderer()
    # Dim studio ambient (uniform environment) so the floor reads as a lit
    # surface — context for the focused spot to pop against. Kept low so the
    # caustic stays the hero. (A second fill *sun* perturbs the forward
    # light-tracer's photon emission; a background color does not — same pattern
    # as glass-mesh-caustic.)
    r.set_background_color([0.055, 0.058, 0.072])

    # Clear glass sphere (ior 1.5), flagged as a caustic caster. A sphere is a
    # primitive (non-triangle) caster — the pkg110 general BSDF photon loop traces
    # through it via Sphere::hit + dielectric sampleSpectral.
    glass = r.create_material("dielectric", [1.0, 1.0, 1.0], {"ior": 1.5})
    sphere_idx = r.scene_object_count()
    r.add_sphere(SPHERE_C, SPHERE_R, glass)
    r.set_object_caustic_caster(sphere_idx, True)

    # Distant collimated sun, angled down and +x so the focused caustic lands on
    # the floor offset in +x from the sphere (out of its shadow). This is the
    # caustic caster's light.
    r.add_sun_light_dedicated(SUN_DIR, 0.01,
                              {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 6.0)

    # White diffuse floor positioned at the focal distance below the sphere.
    floor = r.create_material("lambertian", [0.85, 0.85, 0.85], {})
    _add_quad(r, [[-3.0, FLOOR_Y, -3.0], [4.0, FLOOR_Y, -3.0],
                  [4.0, FLOOR_Y, 3.0], [-3.0, FLOOR_Y, 3.0]], floor)

    r.set_integrator("light_tracer_caustic")
    r.set_integrator_param("max_depth", MAX_DEPTH)
    # High photon count so the spherical-aberration tail fills in densely (a low
    # count leaves a sparse salt-and-pepper scatter around the core — pkg110
    # lesson); the caustic is baked once in beginFrame so this is a one-off cost.
    r.set_integrator_param("photon_count", 24000000)
    # Direct float brightness multiplier (pkg-integrator-float-param route).
    r.set_integrator_param_float("caustic_boost", 2.4)

    # Camera zoomed TIGHT onto the caustic landing zone and pulled closer/lower so
    # the bright spherical-aberration cusp + its ring fill the middle of the frame
    # against the dim-lit floor (the hero). A sphere caustic is an inherently small,
    # concentrated focus, so a narrow FOV is needed to make it read as the subject
    # instead of a speck in a sea of grey floor. The sphere stays above the top of
    # frame so it no longer hides its own caustic.
    r.setup_camera([CAUSTIC_X, FLOOR_Y + 1.05, 1.25], [CAUSTIC_X, FLOOR_Y, CAUSTIC_Z],
                   [0.0, 1.0, 0.0], 11.0, WIDTH / HEIGHT, 0.0, 1.65, WIDTH, HEIGHT)
    return r
