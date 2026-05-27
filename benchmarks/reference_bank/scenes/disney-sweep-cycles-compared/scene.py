"""Disney material sweep — Astroray side. Compared against Cycles.

A 5×3 grid of Disney-BSDF spheres parameterized by:
  - X axis: roughness ∈ {0.05, 0.25, 0.50, 0.75, 0.95}
  - Y axis: metallic ∈ {0.0, 0.5, 1.0}
Same albedo for all spheres (warm gray). Lit by a single overhead area
light over a neutral-gray floor.

The Cycles reference is rendered by `cycles_bless.py`, which runs
Blender 5.1 headlessly with the same camera, geometry, light, and
Principled-BSDF parameters. Gate: SSIM(Astroray, Cycles) ≥ 0.85 — loose
because:
  1. The two engines use different RNG streams, so MC noise is independent.
  2. Cycles' Principled BSDF and Astroray's Disney implementation are
     close but not bit-identical (closure decomposition differs).
  3. Gamma / tonemap defaults may differ slightly.

If the SSIM drops below 0.85, one of these is the suspect; the gate
catches gross BSDF regressions, not closure-graph subtleties.
"""

from __future__ import annotations


NAME = "disney-sweep-cycles-compared"
WIDTH = 384
HEIGHT = 256
SAMPLES = 256
MAX_DEPTH = 8
SEED = 17

ROUGHNESS_VALUES = [0.1, 0.5, 0.9]
METALLIC_VALUES = [0.0, 0.5, 1.0]
ALBEDO = [0.72, 0.50, 0.32]
SPHERE_RADIUS = 0.45
SPHERE_SPACING_X = 1.20
SPHERE_SPACING_Y = 1.20


def _grid_positions():
    """Yield (x, y, z, roughness, metallic) tuples for the grid."""
    n_x = len(ROUGHNESS_VALUES)
    n_y = len(METALLIC_VALUES)
    x0 = -(n_x - 1) * SPHERE_SPACING_X / 2
    y0 = -(n_y - 1) * SPHERE_SPACING_Y / 2
    for j, m in enumerate(METALLIC_VALUES):
        for i, r in enumerate(ROUGHNESS_VALUES):
            x = x0 + i * SPHERE_SPACING_X
            y = y0 + j * SPHERE_SPACING_Y
            yield (x, y, 0.0, r, m)


def make_scene(astroray):
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_background_color([0.04, 0.05, 0.06])

    # Neutral gray floor.
    floor = r.create_material("lambertian", [0.55, 0.55, 0.55], {})
    r.add_triangle([-5, -1.0, -5], [5, -1.0, -5], [5, -1.0, 5], floor)
    r.add_triangle([-5, -1.0, -5], [5, -1.0, 5], [-5, -1.0, 5], floor)

    # Overhead area light (single small panel).
    light_mat = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 14.0})
    lx, lz = 1.5, 1.0
    r.add_triangle([-lx, 4.0, -lz], [lx, 4.0, -lz], [lx, 4.0, lz], light_mat)
    r.add_triangle([-lx, 4.0, -lz], [lx, 4.0, lz], [-lx, 4.0, lz], light_mat)

    # Disney sphere grid.
    for x, y, z, rough, metal in _grid_positions():
        mat = r.create_material("disney", ALBEDO, {
            "roughness": rough,
            "metallic": metal,
            "specular": 0.5,
        })
        r.add_sphere([x, y - 0.55, z], SPHERE_RADIUS, mat)

    # Camera: front-and-slightly-above, looking at the grid centre.
    # vfov 30° ≈ 50mm lens on 35mm sensor (matches Blender default).
    r.setup_camera(
        [0.0, 0.3, 7.0], [0.0, -0.6, 0.0], [0.0, 1.0, 0.0],
        30.0,
        WIDTH / HEIGHT,
        0.0,
        7.0,
        WIDTH, HEIGHT,
    )
    return r
