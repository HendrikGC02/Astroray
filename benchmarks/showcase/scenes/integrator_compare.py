"""pkg74 Phase 2 — integrator-comparison scene.

Renders the same Cornell box (with one glass sphere added so refractive
integrators have something to bite on) using every entry from
`integrator_registry_names()` that the runner doesn't explicitly
exclude. Failed integrators are recorded with `skip_reason`, not
silently dropped — same pattern as the material zoo.

This is the "scene gallery" and "integrator compare" rolled together:
one scene, many integrators, side-by-side contact sheet + bar chart of
total render times.
"""

from __future__ import annotations

from typing import Iterator

from .. import config


# Integrators that need extra setup (training/warmup, dedicated camera
# layout, or specific scene topology) and would either crash on this
# scene or silently produce all-black. Skipped by default; the runner
# records them with skip_reason="skiplisted by integrator_compare".
INTEGRATOR_COMPARE_SKIPLIST: set[str] = {
    "ambient_occlusion",        # produces an AO map, not a beauty render
    "neural-cache",             # needs warmup + tcnn build; pkg27/27a/28
    "restir-di",                # CPU-only, also needs careful setup
}


def integrator_entries(astroray_module) -> Iterator[str]:
    """Yield integrator names to compare on the integrator_compare scene."""
    names = sorted(astroray_module.integrator_registry_names())
    for name in names:
        if name in INTEGRATOR_COMPARE_SKIPLIST:
            continue
        yield name


def build_cornell_with_glass(renderer, width: int, height: int,
                             *, integrator: str = "path_tracer") -> dict:
    """Cornell box with one diffuse sphere swapped for glass.

    Geometry matches the convergence-grid Cornell so cross-integrator
    comparisons sit on the same camera/scene framing.
    """
    renderer.set_integrator(integrator)
    if hasattr(renderer, "set_seed"):
        renderer.set_seed(config.QUICK_SEED)

    renderer.setup_camera(
        look_from=[0.0, 0.15, 5.4],
        look_at=[0.0, -0.15, 0.0],
        vup=[0.0, 1.0, 0.0],
        vfov=42.0,
        aspect_ratio=width / height,
        aperture=0.0,
        focus_dist=5.4,
        width=width,
        height=height,
    )
    renderer.set_background_color([0.0, 0.0, 0.0])

    white = renderer.create_material("lambertian", [0.74, 0.74, 0.72], {})
    red   = renderer.create_material("lambertian", [0.72, 0.08, 0.06], {})
    green = renderer.create_material("lambertian", [0.10, 0.50, 0.16], {})
    light = renderer.create_material("light",      [1.0, 0.96, 0.84],  {"intensity": 18.0})
    glass = renderer.create_material("dielectric", [1.0, 1.0, 1.0],    {"ior": 1.5})

    renderer.add_triangle([-2, -2, -2], [2, -2, -2], [2, -2, 2], white)
    renderer.add_triangle([-2, -2, -2], [2, -2, 2], [-2, -2, 2], white)
    renderer.add_triangle([-2, 2, -2], [-2, 2, 2], [2, 2, 2], white)
    renderer.add_triangle([-2, 2, -2], [2, 2, 2], [2, 2, -2], white)
    renderer.add_triangle([-2, -2, -2], [-2, 2, -2], [2, 2, -2], white)
    renderer.add_triangle([-2, -2, -2], [2, 2, -2], [2, -2, -2], white)
    renderer.add_triangle([-2, -2, -2], [-2, -2, 2], [-2, 2, 2], red)
    renderer.add_triangle([-2, -2, -2], [-2, 2, 2], [-2, 2, -2], red)
    renderer.add_triangle([2, -2, -2], [2, 2, -2], [2, 2, 2], green)
    renderer.add_triangle([2, -2, -2], [2, 2, 2], [2, -2, 2], green)
    # Glass sphere — the visual differentiator across integrators.
    renderer.add_sphere([0.0, -1.1, 0.55], 0.78, glass)
    # Ceiling light.
    renderer.add_triangle([-0.42, 1.96, -0.35], [0.42, 1.96, -0.35], [0.42, 1.96, 0.35], light)
    renderer.add_triangle([-0.42, 1.96, -0.35], [0.42, 1.96, 0.35], [-0.42, 1.96, 0.35], light)

    triangles = 14
    spheres = 1
    return {
        "triangles":  triangles,
        "spheres":    spheres,
        "primitives": triangles + spheres,
        "materials":  5,
        "lights":     1,
    }
