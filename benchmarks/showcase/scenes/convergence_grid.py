"""pkg74 showcase — Cornell box driver for the convergence grid + curve.

The same scene is rendered at the geometric SPP series in
`config.QUICK_SPP_SERIES`, and the highest-SPP entry serves as the
in-run ground truth for the log-log RMSE plot. Pinned ground-truth
EXRs are explicitly out of scope for Phase 1 — that's pkg71's pattern.

Pattern adapted from `scripts/diagnostics/convergence_tracker.py`'s
Cornell builder; geometry kept identical so the two diagnostics
produce visually-equivalent renders.
"""

from __future__ import annotations

from .. import config


def build_cornell(renderer, width: int, height: int) -> None:
    """Cornell box: diffuse coloured walls, white sphere, ceiling area light."""
    renderer.set_integrator("path_tracer")
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
    red = renderer.create_material("lambertian", [0.72, 0.08, 0.06], {})
    green = renderer.create_material("lambertian", [0.10, 0.50, 0.16], {})
    light = renderer.create_material("light", [1.0, 0.96, 0.84], {"intensity": 18.0})

    # Floor / ceiling / back wall.
    renderer.add_triangle([-2, -2, -2], [2, -2, -2], [2, -2, 2], white)
    renderer.add_triangle([-2, -2, -2], [2, -2, 2], [-2, -2, 2], white)
    renderer.add_triangle([-2, 2, -2], [-2, 2, 2], [2, 2, 2], white)
    renderer.add_triangle([-2, 2, -2], [2, 2, 2], [2, 2, -2], white)
    renderer.add_triangle([-2, -2, -2], [-2, 2, -2], [2, 2, -2], white)
    renderer.add_triangle([-2, -2, -2], [2, 2, -2], [2, -2, -2], white)
    # Side walls.
    renderer.add_triangle([-2, -2, -2], [-2, -2, 2], [-2, 2, 2], red)
    renderer.add_triangle([-2, -2, -2], [-2, 2, 2], [-2, 2, -2], red)
    renderer.add_triangle([2, -2, -2], [2, 2, -2], [2, 2, 2], green)
    renderer.add_triangle([2, -2, -2], [2, 2, 2], [2, -2, 2], green)
    # Diffuse sphere.
    renderer.add_sphere([0.0, -1.1, 0.55], 0.78, white)
    # Ceiling light.
    renderer.add_triangle([-0.42, 1.96, -0.35], [0.42, 1.96, -0.35], [0.42, 1.96, 0.35], light)
    renderer.add_triangle([-0.42, 1.96, -0.35], [0.42, 1.96, 0.35], [-0.42, 1.96, 0.35], light)
