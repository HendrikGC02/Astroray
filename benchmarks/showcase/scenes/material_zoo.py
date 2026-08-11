"""pkg74 showcase — material zoo: one sphere per registered material,
plus curated multi-preset variants for materials with more than one
visually distinct configuration.

Drives the entry list from `astroray.material_registry_names()` so newly
registered materials appear automatically. Per-material parameter
defaults live in `benchmarks/showcase/config.py`; entries that fail to
construct or render are reported as skip rows by the runner, not
silently dropped.

`config.MATERIAL_ZOO_VARIANTS` adds named presets (glass IOR/dispersion
presets, a disney_glass roughness sweep, metal roughness spread) ported
from the now-deleted `scripts/diagnostics/material_contact_sheet.py`,
which curated these by hand before pkg74 existed. pkg74 is the single
canonical contact-sheet generator.
"""

from __future__ import annotations

from typing import Iterator

from .. import config


def material_entries(astroray_module) -> Iterator[tuple[str, str, list[float], dict]]:
    """Yield (display_name, material_type, base_color, params) per registered material,
    followed by the curated variants.

    Skiplist entries from config are filtered out; everything else is
    yielded with type-default parameters or a generic grey fallback.
    """
    names = list(astroray_module.material_registry_names())
    for name in sorted(names):
        if name in config.ZOO_SKIPLIST:
            continue
        color, params = config.MATERIAL_ZOO_DEFAULTS.get(
            name, config.GENERIC_MATERIAL_DEFAULT)
        yield name, name, list(color), dict(params)
    for display_name, mat_type, color, params in config.MATERIAL_ZOO_VARIANTS:
        yield display_name, mat_type, list(color), dict(params)


def build_material_preview_scene(renderer, material_id: int, resolution: int) -> dict:
    """Single-sphere preview scene under uniform sun + grey background.

    Mirrors `scripts/diagnostics/_preview_helpers.add_preview_scene` so
    the zoo and the existing per-material diagnostic compose visually.

    Returns a `scene_meta` dict counting what was added — Phase 2 stat
    collectors record these as `geom_*` columns.
    """
    renderer.set_integrator("path_tracer")
    if hasattr(renderer, "set_seed"):
        renderer.set_seed(config.QUICK_SEED)

    renderer.set_background_color([0.18, 0.19, 0.21])

    sun_mat = renderer.create_material("light", [1.0, 0.96, 0.88], {"intensity": 2.8})
    sun_used_geom = False  # whether the sun was added as a sphere fallback
    if hasattr(renderer, "add_sun_light"):
        renderer.add_sun_light([-0.45, -0.75, -0.48], 0.53, sun_mat)
    else:
        renderer.add_sphere([-1.8, 2.4, 2.1], 0.25, sun_mat)
        sun_used_geom = True

    renderer.add_sphere([0.0, 0.0, 0.0], 0.9, material_id)
    renderer.setup_camera(
        look_from=[0.0, 0.25, 3.3],
        look_at=[0.0, 0.02, 0.0],
        vup=[0.0, 1.0, 0.0],
        vfov=32.0,
        aspect_ratio=1.0,
        aperture=0.0,
        focus_dist=3.3,
        width=resolution,
        height=resolution,
    )

    spheres = 2 if sun_used_geom else 1
    return {
        "triangles":  0,
        "spheres":    spheres,
        "primitives": spheres,
        "materials":  2,    # subject + sun
        "lights":     1,    # the sun
    }
