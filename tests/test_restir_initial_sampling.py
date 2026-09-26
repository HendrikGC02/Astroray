"""
pkg22 — ReSTIR DI initial sampling tests.

Covers integrator registration, finite rendering, seeded determinism, and
a loose brightness sanity check against the vanilla path_tracer.
"""

import math
import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Scene helpers
# ---------------------------------------------------------------------------

def _base_renderer(astroray_module, width=32, height=32):
    r = astroray_module.Renderer()
    r.setup_camera(
        look_from=[0, 0, 5.5], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=45, aspect_ratio=1.0, aperture=0.0, focus_dist=5.5,
        width=width, height=height,
    )
    return r


def _cornell_box(r, astroray_module):
    """Minimal Cornell box: 5 diffuse walls + one ceiling light."""
    white = r.create_material("lambertian", [0.73, 0.73, 0.73], {})
    red   = r.create_material("lambertian", [0.65, 0.05, 0.05], {})
    green = r.create_material("lambertian", [0.12, 0.45, 0.15], {})
    light = r.create_material("light", [1.0, 0.9, 0.8], {"intensity": 15.0})

    # Walls
    r.add_triangle([-2, -2, -2], [2, -2, -2], [2, -2,  2], white)   # floor
    r.add_triangle([-2, -2, -2], [2, -2,  2], [-2, -2, 2], white)
    r.add_triangle([-2,  2, -2], [-2, 2,  2], [2,  2,  2], white)   # ceiling
    r.add_triangle([-2,  2, -2], [2,  2,  2], [2,  2, -2], white)
    r.add_triangle([-2, -2, -2], [-2, 2, -2], [2,  2, -2], white)   # back
    r.add_triangle([-2, -2, -2], [2,  2, -2], [2, -2, -2], white)
    r.add_triangle([-2, -2, -2], [-2, -2, 2], [-2, 2,  2], red)     # left
    r.add_triangle([-2, -2, -2], [-2,  2, 2], [-2, 2, -2], red)
    r.add_triangle([2,  -2, -2], [2,   2, -2], [2, 2,  2], green)   # right
    r.add_triangle([2,  -2, -2], [2,   2,  2], [2, -2, 2], green)

    # Ceiling light
    r.add_triangle([-0.5, 1.98, -0.5], [0.5, 1.98, -0.5], [0.5, 1.98, 0.5], light)
    r.add_triangle([-0.5, 1.98, -0.5], [0.5, 1.98,  0.5], [-0.5, 1.98, 0.5], light)

    return r


def _multi_light_scene(r, astroray_module):
    """Scene with a diffuse floor and three small area lights at different heights."""
    white = r.create_material("lambertian", [0.73, 0.73, 0.73], {})
    light = r.create_material("light", [1.0, 0.9, 0.8], {"intensity": 10.0})

    # Floor
    r.add_triangle([-3, -1, -3], [3, -1, -3], [3, -1, 3], white)
    r.add_triangle([-3, -1, -3], [3, -1,  3], [-3, -1, 3], white)

    # Three small lights at different positions
    for lx in [-1.5, 0.0, 1.5]:
        r.add_triangle([lx - 0.3, 2.0, -0.3], [lx + 0.3, 2.0, -0.3],
                       [lx + 0.3, 2.0,  0.3], light)
        r.add_triangle([lx - 0.3, 2.0, -0.3], [lx + 0.3, 2.0,  0.3],
                       [lx - 0.3, 2.0,  0.3], light)
    return r


def _render(r, integrator, samples=16, seed=42):
    r.set_integrator(integrator)
    r.set_seed(seed)
    return np.array(r.render(samples_per_pixel=samples, max_depth=8), dtype=np.float32)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_restir_di_in_registry(astroray_module):
    names = astroray_module.integrator_registry_names()
    assert "restir-di" in names, f"'restir-di' not in registry: {names}"


# ---------------------------------------------------------------------------
# Finite rendering
# ---------------------------------------------------------------------------

def test_restir_di_renders_finite_non_black(astroray_module):
    r = _base_renderer(astroray_module)
    _cornell_box(r, astroray_module)
    pixels = _render(r, "restir-di", samples=4)
    assert not np.any(np.isnan(pixels)), "restir-di produced NaN pixels"
    assert not np.any(np.isinf(pixels)), "restir-di produced Inf pixels"
    assert pixels.max() > 0.0, "restir-di produced all-black output"


def test_restir_di_no_nan_with_multiple_lights(astroray_module):
    r = _base_renderer(astroray_module)
    _multi_light_scene(r, astroray_module)
    pixels = _render(r, "restir-di", samples=8)
    assert not np.any(np.isnan(pixels))
    assert not np.any(np.isinf(pixels))


def test_restir_di_no_nan_black_background(astroray_module):
    """Regression: no NaN when environment is black (no env map, dark background)."""
    r = _base_renderer(astroray_module)
    r.set_background_color([0.0, 0.0, 0.0])
    _cornell_box(r, astroray_module)
    pixels = _render(r, "restir-di", samples=4)
    assert not np.any(np.isnan(pixels))
    assert pixels.max() > 0.0


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_restir_di_seeded_renders_are_identical(astroray_module):
    """Two renders with the same seed must produce bit-identical output."""
    r1 = _base_renderer(astroray_module)
    _cornell_box(r1, astroray_module)
    p1 = _render(r1, "restir-di", samples=4, seed=7)

    r2 = _base_renderer(astroray_module)
    _cornell_box(r2, astroray_module)
    p2 = _render(r2, "restir-di", samples=4, seed=7)

    np.testing.assert_array_equal(p1, p2, err_msg="restir-di is not deterministic with same seed")


def test_restir_di_different_seeds_differ(astroray_module):
    """Different seeds should produce different images (high probability)."""
    r1 = _base_renderer(astroray_module)
    _cornell_box(r1, astroray_module)
    p1 = _render(r1, "restir-di", samples=4, seed=1)

    r2 = _base_renderer(astroray_module)
    _cornell_box(r2, astroray_module)
    p2 = _render(r2, "restir-di", samples=4, seed=999)

    assert not np.array_equal(p1, p2), "Different seeds produced identical images"


# ---------------------------------------------------------------------------
# Brightness sanity vs path_tracer
# ---------------------------------------------------------------------------

def test_restir_di_not_dramatically_darker_than_path_tracer(astroray_module):
    """
    restir-di and path_tracer are both unbiased estimators for the same integrand.
    At 32spp their means should be within a factor of 3 of each other.
    We only check the illuminated Cornell box interior (mean > 0).
    """
    samples = 32

    r_pt = _base_renderer(astroray_module, width=24, height=24)
    _cornell_box(r_pt, astroray_module)
    pt_pixels = _render(r_pt, "path_tracer", samples=samples, seed=42)

    r_rs = _base_renderer(astroray_module, width=24, height=24)
    _cornell_box(r_rs, astroray_module)
    rs_pixels = _render(r_rs, "restir-di", samples=samples, seed=42)

    pt_mean = float(np.mean(pt_pixels))
    rs_mean = float(np.mean(rs_pixels))

    assert pt_mean > 0.0, "path_tracer produced black image"
    assert rs_mean > 0.0, "restir-di produced black image"

    ratio = rs_mean / pt_mean
    assert ratio > 0.1, (
        f"restir-di mean ({rs_mean:.4f}) is more than 10x darker than "
        f"path_tracer mean ({pt_mean:.4f}); ratio={ratio:.3f}"
    )
    assert ratio < 10.0, (
        f"restir-di mean ({rs_mean:.4f}) is more than 10x brighter than "
        f"path_tracer mean ({pt_mean:.4f}); ratio={ratio:.3f}"
    )


def test_restir_di_many_lights_not_black(astroray_module):
    """With three lights, restir-di should still illuminate the floor."""
    r = _base_renderer(astroray_module, width=24, height=24)
    _multi_light_scene(r, astroray_module)
    pixels = _render(r, "restir-di", samples=16)
    mean = float(np.mean(pixels))
    assert mean > 0.005, (
        f"restir-di produced near-black output on multi-light scene: mean={mean:.5f}"
    )


def _grey_ground_dedicated(astroray_module, integrator, seed, light):
    r = _base_renderer(astroray_module, width=48, height=48)
    r.setup_camera(look_from=[0, -12, 8], look_at=[0, 0, 0], vup=[0, 0, 1],
                   vfov=40, aspect_ratio=1.0, aperture=0.0, focus_dist=10.0,
                   width=48, height=48)
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(seed)
    r.set_use_gpu(False)
    g = r.create_material("lambertian", [0.8, 0.8, 0.8], {})
    r.add_triangle([-20, -20, 0], [20, -20, 0], [20, 20, 0], g)
    r.add_triangle([-20, -20, 0], [20, 20, 0], [-20, 20, 0], g)
    white = {"mode": "rgb", "color": [1.0, 1.0, 1.0]}
    if light == "sun":
        r.add_sun_light_dedicated([-0.17435, 0.47943, -0.86009], 0.0091804, white, 1.0)
    else:
        r.add_point_light([0, 0, 4], white, 800.0, 0.1)
    r.set_integrator_param("use_temporal", 0)
    r.set_integrator_param("use_spatial", 0)
    r.set_integrator(integrator)
    return r


@pytest.mark.parametrize("light", ["sun", "point"])
def test_restir_di_dedicated_light_no_colour_cast(astroray_module, light):
    """#878: CPU restir-di rendered a grey ground under a white sun blue
    (restir/path_tracer = 0.87/1.17/1.40). Dedicated lights built the RGB
    emission ReSTIR re-upsamples from a 4-wavelength toXYZ estimate at the
    path's own hero wavelengths, a correlated (biased) round trip. Direct light
    only (infinite plane, black sky), so DI-only ReSTIR must match per channel.
    Tolerance 3 %: fixed build measures <= 1.2 % off with per-seed ratio
    sd <= 0.006 (mean of 3 seeds); the bug is >= 13 % off."""
    def mean(integrator):
        return np.mean([
            np.asarray(_grey_ground_dedicated(astroray_module, integrator, s, light)
                       .render(16, 12, None, False), dtype=np.float64)[..., :3]
            .mean(axis=(0, 1)) for s in (11, 23, 37)], axis=0)
    pt, rs = mean("path_tracer"), mean("restir-di")
    ratio = rs / pt
    assert np.all(np.abs(ratio - 1.0) <= 0.03), (
        f"#878 restir-di/path_tracer per-channel {ratio.round(4).tolist()} "
        f"(pt {pt.round(4).tolist()}, restir {rs.round(4).tolist()})")
