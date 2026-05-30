"""Refractive caustic showcase — a cut-glass crystal MESH (samples/Glass.obj).

The pkg110 forward light-tracer focuses a collimated sun through a glass
*caster* and deposits a caustic on the floor. `glass-sphere-caustic` exercises a
primitive sphere caster; this scene exercises an arbitrary triangle **mesh**
caster — the owner-provided `samples/Glass.obj`, a finely-tessellated cut-glass
crystal — reproducing the grazing-light caustic streak of the Cycles reference
`Glass_Blender_ref.png` (crystal on the right, lit from the right, a long
focused caustic streaming left).

Three fixes landed together to make a transformed mesh caster work (see the PR):
  * Scale::hit t-units bug — a scaled mesh was invisible to rays (the Ray ctor
    normalized away the scale, so rec.t came back ~1/scale too large and the
    scene BVH mis-ordered the mesh). Without it the caster deposited 0 photons.
  * loadOBJ(smooth_normals=True) — area-weighted per-vertex normals so a
    tessellated smooth surface refracts continuously (clean caustic), not
    per-facet.
  * light_tracer_caustic marks the L S+ D path on transmission rather than the
    per-hit caster flag (a mesh caster's flag lives on the wrapping decorator,
    not its per-triangle hits).

Asset note: `samples/Glass.obj` is ~18 MB and `*.obj` is gitignored, so it is
NOT checked in. This is a LOCAL showcase scene — `make_scene` raises if the mesh
is absent (CI does not render it). The owner renders it with the asset present.

Integrator: `light_tracer_caustic` (CPU forward light-tracer; caustic baked in
beginFrame so the camera pass needs few samples for the caustic itself — the
glass body still benefits from more spp).
"""

from __future__ import annotations

import math
import os


NAME = "glass-mesh-caustic"
WIDTH = 768
HEIGHT = 480
SAMPLES = 96
MAX_DEPTH = 40   # glass needs deep transmission bounces or grazing edges go black
SEED = 17

# samples/Glass.obj relative to the repo root (this file is 4 dirs deep:
# benchmarks/reference_bank/scenes/glass-mesh-caustic/scene.py).
_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
_MESH = os.path.join(_REPO, "samples", "Glass.obj")


def _norm(v):
    n = math.sqrt(sum(c * c for c in v))
    return [c / n for c in v]


def make_scene(astroray):
    if not os.path.exists(_MESH):
        raise FileNotFoundError(
            f"glass-mesh-caustic needs the owner-provided crystal mesh at {_MESH} "
            "(~18 MB, *.obj is gitignored). Render this showcase locally with the "
            "asset present.")

    r = astroray.Renderer()
    # Slightly dimmed studio ambient: a too-bright environment floods the floor and
    # drowns the shadow the glass casts, which is where the focused caustic reads.
    r.set_background_color([0.78, 0.80, 0.85])

    # Clear cut-glass crystal (ior 1.5), smooth-shaded so the tessellated surface
    # refracts continuously. Scaled 0.1 (~15 units across) and lifted to sit on
    # the floor; rotated for a pleasing facet orientation. Flagged as a caustic
    # caster so the forward light-tracer aims photons at it.
    glass = r.create_material("dielectric", [1.0, 1.0, 1.0], {"ior": 1.5})
    mesh_idx = r.scene_object_count()
    r.add_mesh(_MESH, glass, [5.0, 4.05, 0.0], [0.1, 0.1, 0.1], 25.0, smooth_normals=True)
    r.set_object_caustic_caster(mesh_idx, True)

    # Grazing collimated sun from the right (travelling down-left) -> a long,
    # focused caustic streak landing on the floor to the left of the crystal.
    # Strong so the crystal casts a clear shadow (vs the dimmed ambient) for the
    # caustic to land inside.
    r.add_sun_light_dedicated(_norm([-0.92, -0.33, 0.04]), 0.02,
                              {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 16.0)

    # Mid-grey studio floor catches the caustic and lets it pop.
    floor = r.create_material("lambertian", [0.62, 0.63, 0.66], {})
    r.add_triangle([-60, 0, -60], [60, 0, -60], [60, 0, 60], floor)
    r.add_triangle([-60, 0, -60], [60, 0, 60], [-60, 0, 60], floor)

    r.set_integrator("light_tracer_caustic")
    r.set_integrator_param("max_depth", MAX_DEPTH)
    r.set_integrator_param("photon_count", 4000000)
    r.set_integrator_param_float("caustic_boost", 2.2)

    # Low, near-level camera: crystal on the right, caustic streaming left.
    r.setup_camera([-1.0, 4.5, 23.0], [1.5, 1.2, 0.0], [0.0, 1.0, 0.0],
                   40.0, WIDTH / HEIGHT, 0.0, 23.0, WIDTH, HEIGHT)
    return r
