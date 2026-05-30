"""Spectral-dispersion reference — SF11 flint triangulated-prism rainbow caustic.

Same collimated-prism light path as ``prism-bk7-collimated`` but with SF11 flint
glass (n_d 1.785, Abbe 25) replacing BK7 (n_d 1.517, Abbe 64). SF11's dispersion
is ~4x BK7's (dn over 450..650nm: 0.043 vs 0.011), so its rainbow fans out into a
**visibly wider, fuller** red->violet spread. This scene is the A/B distinguisher:
if the Sellmeier-preset dispatch ever silently shared BK7 coefficients across both
presets, the two bands would collapse to the same spread and this gate would catch
it.

**Two geometry differences from the BK7 scene, both forced by SF11's high index:**
1. *Shallower apex (15deg half-angle vs BK7's 30deg).* At a 30deg half-angle the
   internal ray hits the exit face at ~30deg, but SF11's critical angle is only
   arcsin(1/1.785) ~= 34deg, so a 30deg prism is right at TIR and SF11 deposits
   *zero* light on the floor (the beam totally-internally-reflects). A 15deg apex
   keeps the internal ray well below critical so the full spectrum transmits.
2. *Narrower entry aperture (half_u 0.15 vs 0.62).* SF11's large dispersion fans
   each wavelength so far that a wide beam's wavelengths overlap and average to a
   washed-out salt-and-pepper white core (the pkg110 noise failure mode). A thin
   beam keeps each wavelength a clean separated line -> a continuous rainbow.

**Why forward light-tracing, not camera-side SMS/MNEE (pkg106 finish):** a flat
prism does not focus, so the camera-side specular connection is a near-delta
whose Newton basin is spatially chaotic -> salt-and-pepper chromatic noise that
does not clean up with samples. A prism rainbow is a forward light-transport
phenomenon, so this scene uses the ``light_tracer_caustic`` integrator (Arvo 1986
backward ray tracing / Jensen 1996 photon deposition): wavelengths are traced
FROM the sun through the prism and deposited on the floor, giving a smooth
spectrum with no specular-connection noise. See ../prism-bk7-collimated/notes.md.

**Integrator**: ``light_tracer_caustic`` (CPU forward light-tracer; the caustic is
baked in beginFrame so the camera pass needs few samples).
"""

from __future__ import annotations

import math


NAME = "prism-sf11-collimated"
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

    # SF11 flint dispersive prism — two refracting faces of a shallow prism
    # (30deg dihedral = 15deg half-angle, apex +y), each a finite quad flagged as a
    # caustic caster. The shallow apex keeps SF11's internal ray below its ~34deg
    # critical angle so the spectrum transmits instead of totally-internally-
    # reflecting; the thin entry aperture (half_u 0.15) keeps wavelengths separated.
    glass = r.create_material("dielectric", [1.0, 1.0, 1.0], {"sellmeier_preset": "flint_sf11"})
    apex_y, base_y, half_v = 0.5, -0.5, 0.7
    half = math.radians(15.0)
    bx = (apex_y - base_y) * math.tan(half)
    cy = (apex_y + base_y) / 2.0
    faces = [
        ([-bx / 2, cy, 0.0], _norm([-math.cos(half), math.sin(half), 0.0])),  # left
        ([bx / 2, cy, 0.0], _norm([math.cos(half), math.sin(half), 0.0])),    # right
    ]
    casters = []
    for p, n in faces:
        casters += _add_quad(r, _quad_from_plane(p, n, 0.15, half_v), glass)
    for idx in casters:
        r.set_object_caustic_caster(idx, True)

    # Collimated sun: distant directional light travelling +x into the prism.
    r.add_sun_light_dedicated([1.0, 0.0, 0.0], 0.01,
                              {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 6.0)

    # White diffuse floor — the dispersed spectrum lands here. The shallow SF11
    # prism deviates the beam less than the BK7 30deg prism, so the band lands
    # farther out (~x 4.9..7.0); the floor extends to +x16 to catch the full band.
    floor = r.create_material("lambertian", [0.9, 0.9, 0.9], {})
    _add_quad(r, [[-3.0, -3.0, -2.5], [16.0, -3.0, -2.5], [16.0, -3.0, 2.5], [-3.0, -3.0, 2.5]], floor)

    # Forward light-tracer: bakes the prism caustic onto the floor in beginFrame.
    # More photons + a higher boost than BK7 because the thin aperture passes less
    # flux per wavelength (the trade for clean color separation).
    r.set_integrator("light_tracer_caustic")
    r.set_integrator_param("max_depth", MAX_DEPTH)
    r.set_integrator_param("photon_count", 6000000)
    # pkg-integrator-float-param: caustic_boost is a direct float multiplier
    # routed via set_integrator_param_float.
    r.set_integrator_param_float("caustic_boost", 1.6)

    # Camera zoomed tight onto the (wider) SF11 rainbow band centered at ~x6.0,
    # narrow vfov so the continuous red->violet spectrum fills the frame.
    r.setup_camera([6.0, 0.55, 3.0], [6.0, -3.0, 0.05], [0.0, 1.0, 0.0],
                   21.0, WIDTH / HEIGHT, 0.0, 4.0, WIDTH, HEIGHT)
    return r
