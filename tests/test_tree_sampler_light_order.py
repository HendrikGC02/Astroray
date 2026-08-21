"""Regression: light_sampler='tree' set BEFORE lights are added must still light.

Root cause (found via live Blender MCP 2026-08-21): the Blender addon calls
`renderer.set_light_sampler('tree')` in convert_scene BEFORE it adds any lights.
TreeLightSampler builds and caches its light tree in its constructor over the
CURRENT (then-empty) light list, and adding lights afterward never rebuilds it.
Result: LightTree::pick() sees an empty tree, returns pdf 0, NEE is skipped for
every pixel, and a spot/point/sun-lit scene renders fully black on the CPU
integrator. The 'power' sampler reads the light list live so it is immune; the
GPU flattens the tree at upload time (after lights) so it is unaffected.

These tests render on the CPU with the addon's call order (sampler first, lights
second) and assert the floor is actually lit.
"""

import numpy as np
import pytest


def _render(astroray_module, light_kind, sampler_first):
    r = astroray_module.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    # Addon order: sampler is selected in convert_scene before lights are added.
    if sampler_first:
        r.set_light_sampler('tree')
    r.setup_camera(look_from=[5.5, -5.5, 4], look_at=[0, 0, 0], vup=[0, 0, 1],
                   vfov=40.0, aspect_ratio=1.0, aperture=0.0, focus_dist=8.0,
                   width=64, height=64)
    mat = r.create_material('principled', [0.85, 0.85, 0.85], {'roughness': 0.0})
    r.add_triangle([-5, -5, 0], [5, -5, 0], [5, 5, 0], mat)
    r.add_triangle([-5, -5, 0], [5, 5, 0], [-5, 5, 0], mat)

    emission = {'mode': 'rgb', 'color': [1, 1, 1]}
    if light_kind == 'spot':
        r.add_spot_light_dedicated(center=[0, 0, 7.07], direction=[0, 0, -1],
                                   inner_angle=0.3825, outer_angle=0.45,
                                   emission=emission, intensity=1e5, radius=0.0)
    elif light_kind == 'point':
        r.add_point_light(position=[0, 0, 7.07], emission=emission,
                          intensity=1e5, radius=0.0)
    elif light_kind == 'sun':
        r.add_sun_light_dedicated(direction=[0, 0, -1], angular_diameter=0.009,
                                  emission=emission, intensity=5.0)
    else:
        raise ValueError(light_kind)

    r.set_use_gpu(False)
    return np.asarray(r.render(64, 2))


@pytest.mark.cpu
@pytest.mark.parametrize('light_kind', ['spot', 'point', 'sun'])
def test_tree_sampler_lights_added_after_selection(astroray_module, light_kind):
    """Addon call order (set_light_sampler('tree') then add lights) must light."""
    px = _render(astroray_module, light_kind, sampler_first=True)
    mean = float(px.mean())
    assert np.all(np.isfinite(px)), f"{light_kind}: non-finite pixels"
    assert mean > 0.01, (
        f"{light_kind}: tree sampler set before lights rendered black "
        f"(mean={mean:.6f}); the light tree was built over an empty light list "
        f"and never rebuilt.")


@pytest.mark.cpu
@pytest.mark.parametrize('light_kind', ['spot', 'point', 'sun'])
def test_tree_and_power_samplers_agree(astroray_module, light_kind):
    """The tree sampler (addon order) must match the power sampler brightness."""
    tree_px = _render(astroray_module, light_kind, sampler_first=True)

    r = astroray_module.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    r.setup_camera(look_from=[5.5, -5.5, 4], look_at=[0, 0, 0], vup=[0, 0, 1],
                   vfov=40.0, aspect_ratio=1.0, aperture=0.0, focus_dist=8.0,
                   width=64, height=64)
    mat = r.create_material('principled', [0.85, 0.85, 0.85], {'roughness': 0.0})
    r.add_triangle([-5, -5, 0], [5, -5, 0], [5, 5, 0], mat)
    r.add_triangle([-5, -5, 0], [5, 5, 0], [-5, 5, 0], mat)
    emission = {'mode': 'rgb', 'color': [1, 1, 1]}
    if light_kind == 'spot':
        r.add_spot_light_dedicated(center=[0, 0, 7.07], direction=[0, 0, -1],
                                   inner_angle=0.3825, outer_angle=0.45,
                                   emission=emission, intensity=1e5, radius=0.0)
    elif light_kind == 'point':
        r.add_point_light(position=[0, 0, 7.07], emission=emission,
                          intensity=1e5, radius=0.0)
    else:
        r.add_sun_light_dedicated(direction=[0, 0, -1], angular_diameter=0.009,
                                  emission=emission, intensity=5.0)
    r.set_use_gpu(False)
    power_px = np.asarray(r.render(64, 2))

    tree_mean = float(tree_px.mean())
    power_mean = float(power_px.mean())
    # Single light: both samplers select it every time, so means match closely
    # (only MC noise differs). A wide band still catches the black-tree bug.
    assert power_mean > 0.01, f"{light_kind}: power sampler itself was black"
    rel = abs(tree_mean - power_mean) / power_mean
    assert rel < 0.2, (
        f"{light_kind}: tree vs power brightness diverged "
        f"(tree={tree_mean:.5f}, power={power_mean:.5f}, rel={rel:.3f})")
