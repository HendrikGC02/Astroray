"""Tests for pkg33: OIDN FetchContent integration.

Verifies that the oidn_denoiser pass is present in the registry (meaning the
build found/fetched OIDN), that it actually reduces noise, and produces a
side-by-side comparison image in test_results/.
"""
import os
import sys
import numpy as np
import pytest
from PIL import Image

from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")

OIDN_ENABLED = AVAILABLE and "oidn_denoiser" in (astroray.pass_registry_names() if AVAILABLE else [])


def _cornell_renderer(width: int = 256, height: int = 256) -> "astroray.Renderer":
    r = astroray.Renderer()
    r.setup_camera(
        look_from=[0, 0, 5.5], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=40, aspect_ratio=width / height, aperture=0.0, focus_dist=5.5,
        width=width, height=height,
    )
    r.set_background_color([0.0, 0.0, 0.0])

    red   = r.create_material("lambertian", [0.65, 0.05, 0.05], {})
    green = r.create_material("lambertian", [0.12, 0.45, 0.15], {})
    white = r.create_material("lambertian", [0.73, 0.73, 0.73], {})
    light = r.create_material("light",      [1.0, 0.9, 0.8],    {"intensity": 15.0})

    # Floor, ceiling, back wall
    r.add_triangle([-2, -2, -2], [ 2, -2, -2], [ 2, -2,  2], white)
    r.add_triangle([-2, -2, -2], [ 2, -2,  2], [-2, -2,  2], white)
    r.add_triangle([-2,  2, -2], [-2,  2,  2], [ 2,  2,  2], white)
    r.add_triangle([-2,  2, -2], [ 2,  2,  2], [ 2,  2, -2], white)
    r.add_triangle([-2, -2, -2], [-2,  2, -2], [ 2,  2, -2], white)
    r.add_triangle([-2, -2, -2], [ 2,  2, -2], [ 2, -2, -2], white)
    # Left wall (red), right wall (green)
    r.add_triangle([-2, -2, -2], [-2, -2,  2], [-2,  2,  2], red)
    r.add_triangle([-2, -2, -2], [-2,  2,  2], [-2,  2, -2], red)
    r.add_triangle([ 2, -2, -2], [ 2,  2, -2], [ 2,  2,  2], green)
    r.add_triangle([ 2, -2, -2], [ 2,  2,  2], [ 2, -2,  2], green)
    # Ceiling light
    r.add_triangle([-0.5, 1.98, -0.5], [0.5, 1.98, -0.5], [0.5, 1.98, 0.5], light)
    r.add_triangle([-0.5, 1.98, -0.5], [0.5, 1.98,  0.5], [-0.5, 1.98, 0.5], light)
    # A sphere in the scene
    r.add_sphere([0, -1.0, 0], 1.0, white)
    return r


def _to_uint8(img_float: np.ndarray) -> np.ndarray:
    """Tone-map and convert a linear HDR image to uint8."""
    mapped = np.clip(img_float ** (1.0 / 2.2), 0.0, 1.0)
    return (mapped * 255).astype(np.uint8)


def test_oidn_in_pass_registry():
    """oidn_denoiser must appear in the pass registry when built with OIDN."""
    names = astroray.pass_registry_names()
    assert "oidn_denoiser" in names, (
        f"'oidn_denoiser' missing from registry {names}; "
        "rebuild with ASTRORAY_ENABLE_OIDN=ON and OIDN found by CMake"
    )


@pytest.mark.skipif(not OIDN_ENABLED, reason="OIDN not compiled in")
def test_oidn_reduces_variance(test_results_dir):
    """OIDN denoiser must reduce per-pixel variance compared to a raw low-spp render.

    Saves a side-by-side PNG (noisy | denoised) to test_results/.
    """
    W, H = 256, 256
    SPP = 4  # intentionally very noisy

    # --- Render noisy baseline (no passes) ---
    r_noisy = _cornell_renderer(W, H)
    r_noisy.set_seed(42)
    noisy_raw = np.array(r_noisy.render(samples_per_pixel=SPP, max_depth=6), dtype=np.float32)

    # --- Render same frame then apply OIDN ---
    r_denoised = _cornell_renderer(W, H)
    r_denoised.set_seed(42)
    r_denoised.add_pass("oidn_denoiser")
    denoised_raw = np.array(r_denoised.render(samples_per_pixel=SPP, max_depth=6), dtype=np.float32)

    # Sanity: denoised output must be finite and non-negative
    assert np.all(np.isfinite(denoised_raw)), "denoised output contains non-finite values"
    assert np.all(denoised_raw >= 0.0), "denoised output contains negative values"

    # Variance check: OIDN should smooth the image; measure local 3×3 patch variance.
    def local_variance(img: np.ndarray) -> float:
        """Mean of per-pixel variance within a 3-pixel neighbourhood (pure numpy)."""
        padded = np.pad(img, ((1, 1), (1, 1), (0, 0)), mode="edge")
        neighbours = np.stack([
            padded[r:r + img.shape[0], c:c + img.shape[1]]
            for r in range(3) for c in range(3)
        ])  # (9, H, W, 3)
        return float(neighbours.var(axis=0).mean())

    var_noisy = local_variance(noisy_raw)
    var_denoised = local_variance(denoised_raw)
    assert var_denoised < var_noisy * 0.9, (
        f"OIDN did not reduce local variance: noisy={var_noisy:.6f}, "
        f"denoised={var_denoised:.6f}"
    )

    # --- Side-by-side comparison image ---
    noisy_u8    = _to_uint8(noisy_raw)
    denoised_u8 = _to_uint8(denoised_raw)
    gap = np.full((H, 8, 3), 200, dtype=np.uint8)
    comparison = np.concatenate([noisy_u8, gap, denoised_u8], axis=1)

    out_path = os.path.join(test_results_dir, "oidn_before_after.png")
    Image.fromarray(comparison).save(out_path)
    print(f"\n  Saved side-by-side comparison to {out_path}")
    print(f"  Local variance: noisy={var_noisy:.6f}, denoised={var_denoised:.6f}")


@pytest.mark.skipif(not OIDN_ENABLED, reason="OIDN not compiled in")
def test_oidn_off_by_default_does_not_denoise():
    """Without add_pass('oidn_denoiser'), output must differ from denoised output."""
    W, H = 64, 64
    SPP = 2

    r_noisy = _cornell_renderer(W, H)
    r_noisy.set_seed(7)
    noisy = np.array(r_noisy.render(samples_per_pixel=SPP, max_depth=4), dtype=np.float32)

    r_den = _cornell_renderer(W, H)
    r_den.set_seed(7)
    r_den.add_pass("oidn_denoiser")
    denoised = np.array(r_den.render(samples_per_pixel=SPP, max_depth=4), dtype=np.float32)

    # The denoised image must not be pixel-identical to the raw render.
    assert not np.allclose(noisy, denoised, atol=1e-4), (
        "OIDN pass produced identical output — denoiser may not have run"
    )
