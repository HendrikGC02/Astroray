"""pkg198 Stage 1 — CPU light-path render-pass classification.

Real-binding tests (not the mocked-renderer viewport tests in
test_blender_viewport_passes.py). These render actual scenes on the CPU default
`path_tracer` integrator and read `get_render_pass_buffer(...)`, which pkg198
now populates for the first time (previously dead plumbing — SampleResult.passes
had zero write sites repo-wide).

Gates (coordinator dispatch):
  1. sum-to-beauty invariant, LINEAR, on a scene exercising all lobes.
  2. isolated-lobe sanity (pure-diffuse -> glossy/transmission ~zero, etc.).
  3. per-pass PNGs written for visual inspection.

Classification mirrors Cycles kernel/film/light_passes.h + shade_surface.h
(Apache-2.0); see .astroray_plan/docs/pkg198-lightpath-pass-classification-research.md.
"""
import os

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

from base_helpers import save_image

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")

LIGHT_PATH_PASSES = [
    "diffuse_direct", "diffuse_indirect",
    "glossy_direct", "glossy_indirect",
    "transmission_direct", "transmission_indirect",
    "emission", "environment",
]


def _camera(r, w=48, h=48):
    r.setup_camera(
        look_from=[0, 0, 6], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=45, aspect_ratio=1.0, aperture=0.0, focus_dist=6.0,
        width=w, height=h,
    )


def _sum_passes(r):
    total = None
    for name in LIGHT_PATH_PASSES:
        buf = np.array(r.get_render_pass_buffer(name), dtype=np.float64)
        total = buf if total is None else total + buf
    return total


def test_all_light_path_passes_readable(test_results_dir):
    """Every light-path pass buffer reads back with the right shape and finite values."""
    r = astroray.Renderer()
    _camera(r)
    r.set_background_color([0.05, 0.07, 0.12])
    diffuse = r.create_material("lambertian", [0.7, 0.2, 0.2], {})
    r.add_sphere([0, 0, 0], 1.4, diffuse)
    r.add_point_light([3, 4, 3], {'mode': 'rgb', 'color': [1.0, 1.0, 1.0]}, 40.0)
    r.render(samples_per_pixel=16, max_depth=4, apply_gamma=False)
    for name in LIGHT_PATH_PASSES:
        buf = np.array(r.get_render_pass_buffer(name), dtype=np.float32)
        assert buf.shape == (48, 48, 3), f"{name} wrong shape {buf.shape}"
        assert np.all(np.isfinite(buf)), f"{name} has non-finite values"


def test_sum_to_beauty_linear(test_results_dir):
    """Gate 1: Σ(light-path passes) == beauty, per-channel, in LINEAR space.

    Passes and beauty are built from the same per-sample radiance contributions
    (total partition), so the sum is near-exact; the only slack is the per-channel
    gamut clamp applied per-pass vs per-beauty."""
    r = astroray.Renderer()
    _camera(r)
    r.set_background_color([0.10, 0.12, 0.18])
    # All lobes: diffuse + glossy (metal) + transmission (glass) + emission,
    # plus a directly-visible non-black background (environment).
    diffuse = r.create_material("lambertian", [0.6, 0.6, 0.6], {})
    metal = r.create_material("metal", [0.9, 0.9, 0.9], {"roughness": 0.15})
    glass = r.create_material("dielectric", [1.0, 1.0, 1.0], {"ior": 1.5})
    emit = r.create_material("light", [1.0, 0.9, 0.7], {"intensity": 6.0})
    r.add_sphere([0, -1001.2, 0], 1000.0, diffuse)   # floor
    r.add_sphere([-1.4, -0.3, 0.2], 0.9, metal)
    r.add_sphere([1.4, -0.3, 0.4], 0.9, glass)
    r.add_sphere([0.0, 1.5, -0.5], 0.5, emit)
    r.add_point_light([3, 4, 3], {'mode': 'rgb', 'color': [1.0, 1.0, 1.0]}, 60.0)

    beauty = np.array(
        r.render(samples_per_pixel=96, max_depth=6, apply_gamma=False),
        dtype=np.float64,
    )
    passes_sum = _sum_passes(r)

    # Per-channel mean-ratio (the classic invariant gate; NOT SSIM).
    beauty_mean = beauty.reshape(-1, 3).mean(axis=0)
    passes_mean = passes_sum.reshape(-1, 3).mean(axis=0)
    ratio = passes_mean / np.maximum(beauty_mean, 1e-6)
    # Also a pixelwise relative L1 to catch localized partition leaks.
    denom = np.maximum(np.abs(beauty).sum(), 1e-6)
    rel_l1 = np.abs(passes_sum - beauty).sum() / denom

    save_image(beauty.astype(np.float32), os.path.join(test_results_dir, "pkg198_beauty.png"))
    save_image(passes_sum.astype(np.float32), os.path.join(test_results_dir, "pkg198_passes_sum.png"))

    print(f"[pkg198] sum-to-beauty per-channel ratio = {ratio}, rel_L1 = {rel_l1:.4f}")
    assert np.allclose(ratio, 1.0, atol=0.03), f"per-channel ratio off: {ratio}"
    assert rel_l1 < 0.03, f"pixelwise relative L1 too high: {rel_l1:.4f}"


def _pass_mean(r, name):
    return float(np.array(r.get_render_pass_buffer(name), dtype=np.float64).mean())


def test_isolated_diffuse(test_results_dir):
    """Gate 2a: a pure-diffuse lit scene -> diffuse passes carry energy,
    glossy and transmission passes are ~zero."""
    r = astroray.Renderer()
    _camera(r)
    r.set_background_color([0.0, 0.0, 0.0])
    diffuse = r.create_material("lambertian", [0.7, 0.7, 0.7], {})
    r.add_sphere([0, -1001.2, 0], 1000.0, diffuse)
    r.add_sphere([0, 0, 0], 1.2, diffuse)
    r.add_point_light([3, 4, 3], {'mode': 'rgb', 'color': [1.0, 1.0, 1.0]}, 60.0)
    r.render(samples_per_pixel=48, max_depth=5, apply_gamma=False)
    for name in LIGHT_PATH_PASSES:
        save_image(
            np.array(r.get_render_pass_buffer(name), dtype=np.float32),
            os.path.join(test_results_dir, f"pkg198_diffuse_{name}.png"),
        )
    d_direct = _pass_mean(r, "diffuse_direct")
    d_indirect = _pass_mean(r, "diffuse_indirect")
    glossy = _pass_mean(r, "glossy_direct") + _pass_mean(r, "glossy_indirect")
    trans = _pass_mean(r, "transmission_direct") + _pass_mean(r, "transmission_indirect")
    print(f"[pkg198] diffuse-scene: d_direct={d_direct:.4f} d_indirect={d_indirect:.4f} "
          f"glossy={glossy:.6f} trans={trans:.6f}")
    assert d_direct > 1e-3, "diffuse_direct should carry the point-light NEE"
    assert d_indirect > 1e-4, "diffuse_indirect should carry inter-reflection"
    assert glossy < d_direct * 1e-2, f"glossy leaked in a pure-diffuse scene: {glossy}"
    assert trans < d_direct * 1e-2, f"transmission leaked in a pure-diffuse scene: {trans}"


def test_isolated_glossy(test_results_dir):
    """Gate 2b: a metal sphere on a black background -> glossy passes carry the
    reflected light, diffuse/transmission ~zero on the metal."""
    r = astroray.Renderer()
    _camera(r)
    r.set_background_color([0.15, 0.15, 0.15])  # something for the mirror to reflect
    metal = r.create_material("metal", [0.95, 0.95, 0.95], {"roughness": 0.1})
    r.add_sphere([0, 0, 0], 1.4, metal)
    r.add_point_light([3, 4, 3], {'mode': 'rgb', 'color': [1.0, 1.0, 1.0]}, 60.0)
    r.render(samples_per_pixel=48, max_depth=5, apply_gamma=False)
    glossy = _pass_mean(r, "glossy_direct") + _pass_mean(r, "glossy_indirect")
    diffuse = _pass_mean(r, "diffuse_direct") + _pass_mean(r, "diffuse_indirect")
    print(f"[pkg198] glossy-scene: glossy={glossy:.4f} diffuse={diffuse:.6f}")
    assert glossy > 1e-3, "glossy passes should carry the metal reflection"
    # Only the metal sphere and background are present; diffuse must stay ~zero.
    assert diffuse < glossy * 1e-2, f"diffuse leaked in a metal scene: {diffuse}"


def test_isolated_transmission(test_results_dir):
    """Gate 2c: a glass sphere -> transmission passes carry the refracted light."""
    r = astroray.Renderer()
    _camera(r)
    r.set_background_color([0.2, 0.25, 0.3])
    glass = r.create_material("dielectric", [1.0, 1.0, 1.0], {"ior": 1.5})
    diffuse = r.create_material("lambertian", [0.6, 0.6, 0.6], {})
    r.add_sphere([0, -1001.2, 0], 1000.0, diffuse)
    r.add_sphere([0, 0, 0], 1.2, glass)
    r.add_point_light([3, 4, 3], {'mode': 'rgb', 'color': [1.0, 1.0, 1.0]}, 60.0)
    r.render(samples_per_pixel=64, max_depth=8, apply_gamma=False)
    trans = _pass_mean(r, "transmission_direct") + _pass_mean(r, "transmission_indirect")
    print(f"[pkg198] transmission-scene: trans={trans:.4f}")
    assert trans > 1e-3, "transmission passes should carry the refracted light through glass"


def test_emission_pass(test_results_dir):
    """A directly-visible emissive surface populates PASS_EMISSION."""
    r = astroray.Renderer()
    _camera(r)
    r.set_background_color([0.0, 0.0, 0.0])
    emit = r.create_material("light", [1.0, 0.85, 0.6], {"intensity": 5.0})
    r.add_sphere([0, 0, 0], 1.3, emit)
    r.render(samples_per_pixel=16, max_depth=3, apply_gamma=False)
    emission = _pass_mean(r, "emission")
    print(f"[pkg198] emission-scene: emission={emission:.4f}")
    assert emission > 1e-3, "emission pass empty for a directly-visible emitter"


def test_environment_pass(test_results_dir):
    """A directly-visible non-black background populates PASS_ENVIRONMENT."""
    r = astroray.Renderer()
    _camera(r)
    r.set_background_color([0.3, 0.4, 0.5])
    diffuse = r.create_material("lambertian", [0.7, 0.7, 0.7], {})
    r.add_sphere([0, 0, 0], 0.8, diffuse)  # small, leaves background visible
    r.add_point_light([3, 4, 3], {'mode': 'rgb', 'color': [1.0, 1.0, 1.0]}, 40.0)
    r.render(samples_per_pixel=16, max_depth=3, apply_gamma=False)
    environment = _pass_mean(r, "environment")
    print(f"[pkg198] environment-scene: environment={environment:.4f}")
    assert environment > 1e-3, "environment pass empty for a directly-visible background"
